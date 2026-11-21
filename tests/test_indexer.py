"""
Tests for indexer module — tokenisation, passage extraction, splitting, overlap,
inverted-index construction, persistence, and duplicate prevention.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import database
from indexer import (
    SiteIndexer,
    extract_passages_from_crawled_page,
    extract_passages_from_html,
    split_text_into_passages,
    tokenize_text,
)
from models import CrawledPage, HeadingInfo


# ── Text Tokenisation ────────────────────────────────────────────────

class TestTokenization:
    def test_basic_tokenization(self):
        tokens = tokenize_text("The quick brown fox jumps over the lazy dog.")
        assert "quick" in tokens
        assert "brown" in tokens
        assert "fox" in tokens
        # Stopwords removed by default
        assert "the" not in tokens
        assert "over" not in tokens

    def test_case_normalization(self):
        tokens = tokenize_text("Python PYTHOn python")
        assert tokens == ["python", "python", "python"]

    def test_preserve_stopwords_option(self):
        tokens = tokenize_text("To be or not to be", remove_stopwords=False)
        assert len(tokens) == 6
        assert "to" in tokens
        assert "be" in tokens

    def test_technical_terms_and_numbers(self):
        text = "Running Python 3.12 with Node.js v20 on Port 8080 costing $50 with 99.9% uptime and C++ core."
        tokens = tokenize_text(text, remove_stopwords=True)
        assert "node.js" in tokens
        assert "c++" in tokens
        assert "$50" in tokens
        assert "8080" in tokens
        assert "99.9%" in tokens

    def test_empty_string(self):
        assert tokenize_text("") == []
        assert tokenize_text("   \n\t  ") == []

    def test_only_punctuation(self):
        assert tokenize_text("!@#$%^&*()_+=-{}[]:;\"'<>?,./") == []


# ── Passage Splitting & Overlap ──────────────────────────────────────

class TestPassageSplitting:
    def test_short_text_remains_single_passage(self):
        text = "This is a single short sentence that should not be split."
        passages = split_text_into_passages(text, max_length=500, min_length=20)
        assert len(passages) == 1
        assert passages[0] == text

    def test_text_shorter_than_min_length_discarded(self):
        assert split_text_into_passages("Too short", min_length=20) == []

    def test_split_long_text_with_overlap(self):
        sentences = [f"Sentence number {i} is here to add meaningful content." for i in range(25)]
        long_text = " ".join(sentences)

        passages = split_text_into_passages(long_text, max_length=200, min_length=20, overlap_chars=40)
        assert len(passages) > 1

        # Check all passages are within max length bounds
        for p in passages:
            assert len(p) >= 20

        # Check overlap: last sentence or part of previous passage appears in the next
        overlap_found = False
        for i in range(len(passages) - 1):
            p1_words = set(passages[i].split()[-3:])
            p2_words = set(passages[i + 1].split()[:5])
            if p1_words & p2_words:
                overlap_found = True
                break
        assert overlap_found

    def test_giant_single_sentence_chunked(self):
        long_word_sentence = " ".join([f"word{i}" for i in range(200)])
        passages = split_text_into_passages(long_word_sentence, max_length=150, min_length=20)
        assert len(passages) > 1
        for p in passages:
            assert len(p) <= 200


# ── HTML Passage Extraction ──────────────────────────────────────────

class TestHTMLExtraction:
    def test_extract_passages_removes_noise(self):
        html = """
        <html>
        <head><title>Test Documentation</title></head>
        <body>
            <header><p>Site Header Navigation</p></header>
            <nav><a href="/">Home</a><a href="/docs">Docs</a></nav>
            <main>
                <h1>Installation Guide</h1>
                <p>Run pip install sitesage to install the package on your local system.</p>
                <h2>Configuration</h2>
                <p>Configure your settings inside config.py using environment variables.</p>
            </main>
            <footer><p>Copyright 2026 SiteSage Inc. All rights reserved.</p></footer>
            <script>console.log('noise')</script>
            <style>.hidden{display:none}</style>
        </body>
        </html>
        """
        passages = extract_passages_from_html(html, "https://example.com/docs")
        assert len(passages) == 2

        # Verify noise tags excluded
        all_text = " ".join(p.text for p in passages)
        assert "Site Header Navigation" not in all_text
        assert "Copyright 2026" not in all_text
        assert "console.log" not in all_text

        # Verify heading context
        assert passages[0].section_heading == "Installation Guide"
        assert passages[0].heading_level == 1
        assert "pip install sitesage" in passages[0].text
        assert passages[0].page_title == "Test Documentation"

        assert passages[1].section_heading == "Configuration"
        assert passages[1].heading_level == 2
        assert "config.py" in passages[1].text

    def test_extract_passages_from_crawled_page(self):
        page = CrawledPage(
            url="https://example.com/api",
            title="API Reference",
            text="Welcome to the API. Section One: First passage details here. Section Two: Second passage content goes here.",
            headings=[
                HeadingInfo(level=1, text="Section One", position=20),
                HeadingInfo(level=2, text="Section Two", position=60),
            ],
            crawl_depth=0,
            status_code=200,
        )
        passages = extract_passages_from_crawled_page(page)
        assert len(passages) >= 2
        assert passages[0].page_url == "https://example.com/api"
        assert passages[0].page_title == "API Reference"
        assert passages[0].section_heading == "Section One"
        assert passages[1].section_heading == "Section Two"


# ── Search Indexer & Persistence ─────────────────────────────────────

class TestSiteIndexer:
    @pytest.fixture
    def db_file(self, tmp_path):
        db = tmp_path / "test_indexer.db"
        database.init_db(db)
        return db

    def test_index_crawled_pages_and_stats(self, db_file):
        indexer = SiteIndexer(db_path=db_file)
        session_id = "sess_idx_01"

        with database.get_db(db_file) as conn:
            database.create_session(conn, session_id, "https://example.com", "test query")

        page1 = CrawledPage(
            url="https://example.com/intro",
            title="Introduction to SiteSage",
            text="SiteSage is a deterministic search engine that crawls websites and answers questions with evidence.",
            headings=[HeadingInfo(level=1, text="Introduction", position=0)],
        )
        page2 = CrawledPage(
            url="https://example.com/features",
            title="Features Overview",
            text="It features question-aware priority crawling, custom BM25 ranking, and real-time progress updates.",
            headings=[HeadingInfo(level=1, text="Core Features", position=0)],
        )

        passages = indexer.index_crawled_pages(session_id, [page1, page2])
        assert len(passages) >= 2

        with database.get_db(db_file) as conn:
            # Check passages table
            p_rows = database.get_passages_by_session(conn, session_id)
            assert len(p_rows) == len(passages)

            # Check term_index table
            search_postings = database.get_term_postings(conn, session_id, "sitesage")
            assert len(search_postings) >= 1

            # Check corpus_stats
            stats = database.get_corpus_stats(conn, session_id)
            assert stats is not None
            assert stats["total_passages"] == len(passages)
            assert stats["avg_length"] > 0

    def test_idempotent_reindexing_prevents_duplicates(self, db_file):
        indexer = SiteIndexer(db_path=db_file)
        session_id = "sess_idx_idempotent"

        with database.get_db(db_file) as conn:
            database.create_session(conn, session_id, "https://example.com", "test query")

        page = CrawledPage(
            url="https://example.com/page",
            title="Page Title",
            text="Passage content for checking duplicate prevention during repeated indexing runs.",
            headings=[HeadingInfo(level=1, text="Heading", position=0)],
        )

        # First indexing run
        indexer.index_crawled_pages(session_id, [page])
        with database.get_db(db_file) as conn:
            count1 = len(database.get_passages_by_session(conn, session_id))

        # Second indexing run (re-index same page)
        indexer.index_crawled_pages(session_id, [page])
        with database.get_db(db_file) as conn:
            count2 = len(database.get_passages_by_session(conn, session_id))

        assert count1 == count2
        assert count1 > 0

    def test_index_from_database(self, db_file):
        indexer = SiteIndexer(db_path=db_file)
        session_id = "sess_from_db"

        with database.get_db(db_file) as conn:
            database.create_session(conn, session_id, "https://example.com", "q")
            pid = database.insert_page(
                conn, session_id, "https://example.com/p1", "Page 1",
                "Text content stored in database ready for indexing.", 0, 200
            )
            database.insert_heading(conn, pid, 1, "DB Heading", 0)

        passages = indexer.index_from_database(session_id)
        assert len(passages) >= 1
        assert passages[0].page_url == "https://example.com/p1"
