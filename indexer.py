"""
SiteSage — Text Extraction & Search Indexer (Phase 3).

Responsible for:
1. Converting HTML content and crawled pages into structured, clean passages.
2. Preserving headings, page title, source URL, and passage position.
3. Text tokenisation, normalization, punctuation handling, and stopword filtering.
4. Building and persisting an inverted term index in SQLite.
5. Idempotent re-indexing without duplicate records.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup, NavigableString, Tag

import config
import database
from models import CrawledPage, HeadingInfo, Passage

logger = logging.getLogger(__name__)

# ── Stopword list ────────────────────────────────────────────────────
STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an",
    "and", "any", "are", "aren't", "as", "at", "be", "because", "been",
    "before", "being", "below", "between", "both", "but", "by", "can",
    "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does",
    "doesn't", "doing", "don't", "down", "during", "each", "few", "for",
    "from", "further", "had", "hadn't", "has", "hasn't", "have", "haven't",
    "having", "he", "he'd", "he'll", "he's", "her", "here", "here's",
    "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd",
    "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's",
    "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or",
    "other", "ought", "our", "ours", "ourselves", "out", "over", "own",
    "same", "shan't", "she", "she'd", "she'll", "she's", "should",
    "shouldn't", "so", "some", "such", "than", "that", "that's", "the",
    "their", "theirs", "them", "themselves", "then", "there", "there's",
    "these", "they", "they'd", "they'll", "they're", "they've", "this",
    "those", "through", "to", "too", "under", "until", "up", "very", "was",
    "wasn't", "we", "we'd", "we'll", "we're", "we've", "were", "weren't",
    "what", "what's", "when", "when's", "where", "where's", "which", "while",
    "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your",
    "yours", "yourself", "yourselves",
}


# ── Text Tokenisation ────────────────────────────────────────────────

# Pattern matches alphanumeric tokens, preserving technical identifiers like
# c++, v1.2, node.js, python3, utf-8, 100%, $50, etc.
TOKEN_PATTERN = re.compile(
    r"\b[a-zA-Z0-9]+\+\+|\$?\b[a-zA-Z0-9]+(?:[.\-_/][a-zA-Z0-9]+)*%?",
    re.IGNORECASE,
)


def tokenize_text(text: str, remove_stopwords: bool = True) -> list[str]:
    """Tokenize text into normalized lowercase tokens.

    Preserves technical terms, numbers, version strings, while removing
    punctuation noise and optionally filtering stopwords.
    """
    if not text:
        return []

    raw_tokens = TOKEN_PATTERN.findall(text)
    tokens: list[str] = []

    for t in raw_tokens:
        clean = t.lower().strip(".-_/,")
        if not clean or len(clean) < 1:
            continue
        if remove_stopwords and clean in STOPWORDS:
            continue
        tokens.append(clean)

    return tokens


# ── Passage Splitting & Overlap ──────────────────────────────────────

def split_text_into_passages(
    text: str,
    max_length: int = config.MAX_PASSAGE_LENGTH,
    min_length: int = config.MIN_PASSAGE_LENGTH,
    overlap_chars: int = 60,
) -> list[str]:
    """Split long text into coherent passages with slight overlap.

    Attempts to break along sentence boundaries ('. ', '! ', '? ', '\n')
    when possible, falling back to whitespace breaks.
    """
    text = text.strip()
    if not text or len(text) < min_length:
        return []

    if len(text) <= max_length:
        return [text]

    # Sentence boundary regex
    sentence_end = re.compile(r"(?<=[.!?])\s+|\n+")
    sentences = [s.strip() for s in sentence_end.split(text) if s.strip()]

    if not sentences:
        sentences = [text]

    passages: list[str] = []
    current_chunk: list[str] = []
    current_len = 0

    for sentence in sentences:
        sent_len = len(sentence)

        # If a single sentence exceeds max_length, chunk it by words
        if sent_len > max_length:
            if current_chunk:
                passages.append(" ".join(current_chunk))
                current_chunk = []
                current_len = 0

            words = sentence.split()
            word_chunk: list[str] = []
            word_len = 0
            for w in words:
                if word_len + len(w) + 1 > max_length and word_chunk:
                    passages.append(" ".join(word_chunk))
                    # Retain last few words for overlap
                    overlap_words = []
                    overlap_acc = 0
                    for ow in reversed(word_chunk):
                        if overlap_acc + len(ow) + 1 <= overlap_chars:
                            overlap_words.insert(0, ow)
                            overlap_acc += len(ow) + 1
                        else:
                            break
                    word_chunk = list(overlap_words)
                    word_len = sum(len(x) + 1 for x in word_chunk)

                word_chunk.append(w)
                word_len += len(w) + 1

            if word_chunk and len(" ".join(word_chunk)) >= min_length:
                passages.append(" ".join(word_chunk))
            continue

        if current_len + sent_len + 1 > max_length and current_chunk:
            chunk_str = " ".join(current_chunk)
            passages.append(chunk_str)

            # Overlap: keep the last sentence or last few words from current_chunk
            overlap_words: list[str] = []
            overlap_acc = 0
            for w in reversed(chunk_str.split()):
                if overlap_acc + len(w) + 1 <= overlap_chars:
                    overlap_words.insert(0, w)
                    overlap_acc += len(w) + 1
                else:
                    break

            if overlap_words:
                overlap_prefix = " ".join(overlap_words)
                current_chunk = [overlap_prefix, sentence]
                current_len = len(overlap_prefix) + sent_len + 1
            else:
                current_chunk = [sentence]
                current_len = sent_len
        else:
            current_chunk.append(sentence)
            current_len += sent_len + 1

    if current_chunk:
        chunk_str = " ".join(current_chunk)
        if len(chunk_str) >= min_length:
            passages.append(chunk_str)
        elif passages:
            # Append tiny remainder to previous passage if space permits
            if len(passages[-1]) + len(chunk_str) + 1 <= max_length * 1.2:
                passages[-1] = f"{passages[-1]} {chunk_str}"
            else:
                passages.append(chunk_str)

    return passages


# ── HTML Passage Extraction ──────────────────────────────────────────

NOISE_TAGS = {"script", "style", "noscript", "svg", "iframe", "nav", "footer", "header", "aside"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK_TAGS = {"p", "li", "blockquote", "dt", "dd", "td", "th", "pre", "code"}


def extract_passages_from_html(
    html: str,
    page_url: str,
    page_title: str = "",
) -> list[Passage]:
    """Parse HTML, removing noise and extracting clean text passages grouped

    by structural heading context.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove boilerplate & noise elements
    for tag in soup.find_all(list(NOISE_TAGS)):
        tag.decompose()

    # Extract or fallback title
    if not page_title:
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            page_title = title_tag.string.strip()

    body = soup.find("body") or soup

    current_heading: Optional[str] = None
    current_heading_level: Optional[int] = None
    extracted_passages: list[Passage] = []
    position_counter = 0

    # Collect structural sections
    def walk_blocks(container: Tag):
        nonlocal current_heading, current_heading_level, position_counter

        for elem in container.children:
            if isinstance(elem, NavigableString):
                text = elem.strip()
                if len(text) >= config.MIN_PASSAGE_LENGTH:
                    chunks = split_text_into_passages(text)
                    for chunk in chunks:
                        extracted_passages.append(
                            Passage(
                                id=0,
                                page_url=page_url,
                                page_title=page_title,
                                text=chunk,
                                position=position_counter,
                                section_heading=current_heading,
                                heading_level=current_heading_level,
                                token_count=len(tokenize_text(chunk, remove_stopwords=False)),
                            )
                        )
                        position_counter += 1
                continue

            if not isinstance(elem, Tag):
                continue

            tag_name = elem.name.lower() if elem.name else ""

            if tag_name in HEADING_TAGS:
                h_text = elem.get_text(separator=" ", strip=True)
                if h_text:
                    current_heading = h_text
                    current_heading_level = int(tag_name[1])
                continue

            if tag_name in BLOCK_TAGS:
                block_text = elem.get_text(separator=" ", strip=True)
                # Clean multiple whitespaces
                block_text = re.sub(r"\s+", " ", block_text).strip()
                if len(block_text) >= config.MIN_PASSAGE_LENGTH:
                    chunks = split_text_into_passages(block_text)
                    for chunk in chunks:
                        extracted_passages.append(
                            Passage(
                                id=0,
                                page_url=page_url,
                                page_title=page_title,
                                text=chunk,
                                position=position_counter,
                                section_heading=current_heading,
                                heading_level=current_heading_level,
                                token_count=len(tokenize_text(chunk, remove_stopwords=False)),
                            )
                        )
                        position_counter += 1
            else:
                # Recurse into divs, sections, articles, tables
                walk_blocks(elem)

    walk_blocks(body)

    # Fallback: if no block elements yielded passages, extract from entire body text
    if not extracted_passages:
        full_text = body.get_text(separator=" ", strip=True)
        full_text = re.sub(r"\s+", " ", full_text).strip()
        if len(full_text) >= config.MIN_PASSAGE_LENGTH:
            chunks = split_text_into_passages(full_text)
            for idx, chunk in enumerate(chunks):
                extracted_passages.append(
                    Passage(
                        id=0,
                        page_url=page_url,
                        page_title=page_title,
                        text=chunk,
                        position=idx,
                        section_heading=None,
                        heading_level=None,
                        token_count=len(tokenize_text(chunk, remove_stopwords=False)),
                    )
                )

    return extracted_passages


def extract_passages_from_crawled_page(page: CrawledPage) -> list[Passage]:
    """Extract passages from a CrawledPage instance using its text and heading metadata."""
    if not page.text or len(page.text.strip()) < config.MIN_PAGE_TEXT_LENGTH:
        return []

    # Map headings to character offsets if available
    headings_sorted = sorted(page.headings, key=lambda h: h.position)
    passages: list[Passage] = []
    position = 0

    if not headings_sorted:
        chunks = split_text_into_passages(page.text)
        for chunk in chunks:
            passages.append(
                Passage(
                    id=0,
                    page_url=page.url,
                    page_title=page.title,
                    text=chunk,
                    position=position,
                    section_heading=None,
                    heading_level=None,
                    token_count=len(tokenize_text(chunk, remove_stopwords=False)),
                )
            )
            position += 1
        return passages

    # Slice text by heading positions
    for i, h in enumerate(headings_sorted):
        start_pos = h.position
        end_pos = headings_sorted[i + 1].position if (i + 1 < len(headings_sorted)) else len(page.text)
        section_text = page.text[start_pos:end_pos].strip()

        # Remove the heading text itself if at the beginning of the slice
        if section_text.lower().startswith(h.text.lower()):
            section_text = section_text[len(h.text):].strip()

        if len(section_text) >= config.MIN_PASSAGE_LENGTH:
            chunks = split_text_into_passages(section_text)
            for chunk in chunks:
                passages.append(
                    Passage(
                        id=0,
                        page_url=page.url,
                        page_title=page.title,
                        text=chunk,
                        position=position,
                        section_heading=h.text,
                        heading_level=h.level,
                        token_count=len(tokenize_text(chunk, remove_stopwords=False)),
                    )
                )
                position += 1

    # If splitting by headings yielded nothing, fall back to global text splitting
    if not passages:
        chunks = split_text_into_passages(page.text)
        for idx, chunk in enumerate(chunks):
            passages.append(
                Passage(
                    id=0,
                    page_url=page.url,
                    page_title=page.title,
                    text=chunk,
                    position=idx,
                    section_heading=None,
                    heading_level=None,
                    token_count=len(tokenize_text(chunk, remove_stopwords=False)),
                )
            )

    return passages


# ── Search Indexer ───────────────────────────────────────────────────

class SiteIndexer:
    """Builds and stores inverted index for crawled pages in SQLite."""

    def __init__(self, db_path: Path | str = config.DB_PATH) -> None:
        self.db_path = db_path

    def index_crawled_pages(
        self,
        session_id: str,
        pages: list[CrawledPage],
    ) -> list[Passage]:
        """Index a list of CrawledPage instances for a session.

        Clears existing session index to prevent duplicates.
        """
        all_passages: list[Passage] = []

        with database.get_db(self.db_path) as conn:
            # 1. Clear any prior index for this session (idempotency)
            database.clear_session_index(conn, session_id)

            # 2. Extract and insert passages for each page
            total_tokens = 0
            for page in pages:
                # Find page_id in SQLite
                cur = conn.execute(
                    "SELECT id FROM pages WHERE session_id = ? AND url = ?",
                    (session_id, page.url),
                ).fetchone()

                if cur:
                    page_id = cur["id"]
                else:
                    # Page wasn't inserted yet; insert it now
                    page_id = database.insert_page(
                        conn,
                        session_id,
                        page.url,
                        page.title,
                        page.text,
                        page.crawl_depth,
                        page.status_code or 200,
                    )
                    for h in page.headings:
                        database.insert_heading(conn, page_id, h.level, h.text, h.position)

                page_passages = extract_passages_from_crawled_page(page)

                for p in page_passages:
                    # Body tokens
                    body_tokens = tokenize_text(p.text, remove_stopwords=True)
                    token_count = len(body_tokens)
                    total_tokens += token_count

                    passage_id = database.insert_passage(
                        conn,
                        session_id=session_id,
                        page_id=page_id,
                        text=p.text,
                        position=p.position,
                        section_heading=p.section_heading,
                        heading_level=p.heading_level,
                        token_count=token_count,
                    )

                    p.id = passage_id
                    p.token_count = token_count
                    all_passages.append(p)

                    # Inverted index for body terms
                    term_counts = Counter(body_tokens)
                    for term, count in term_counts.items():
                        database.insert_term(conn, term, passage_id, count, field="body")

                    # Inverted index for section heading terms
                    if p.section_heading:
                        h_tokens = tokenize_text(p.section_heading, remove_stopwords=True)
                        for term, count in Counter(h_tokens).items():
                            database.insert_term(conn, term, passage_id, count, field="heading")

                    # Inverted index for page title terms
                    if p.page_title:
                        title_tokens = tokenize_text(p.page_title, remove_stopwords=True)
                        for term, count in Counter(title_tokens).items():
                            database.insert_term(conn, term, passage_id, count, field="title")

            # 3. Store corpus statistics
            total_passages = len(all_passages)
            avg_length = (total_tokens / total_passages) if total_passages > 0 else 0.0
            database.update_corpus_stats(conn, session_id, total_passages, avg_length)

            # 4. Update session status to INDEXING / DONE
            database.update_session_status(conn, session_id, "indexing")

        logger.info(
            "Session %s: indexed %d passages across %d pages (avg len: %.2f)",
            session_id,
            len(all_passages),
            len(pages),
            avg_length,
        )
        return all_passages

    def index_from_database(self, session_id: str) -> list[Passage]:
        """Index all pages currently stored in SQLite for the session."""
        with database.get_db(self.db_path) as conn:
            page_rows = database.get_pages_by_session(conn, session_id)
            pages: list[CrawledPage] = []
            for row in page_rows:
                h_rows = database.get_headings_by_page(conn, row["id"])
                headings = [
                    HeadingInfo(level=h["level"], text=h["text"], position=h["position"])
                    for h in h_rows
                ]
                pages.append(
                    CrawledPage(
                        url=row["url"],
                        title=row["title"],
                        text=row["text"],
                        headings=headings,
                        crawl_depth=row["depth"],
                        status_code=row["status_code"],
                    )
                )

        return self.index_crawled_pages(session_id, pages)
