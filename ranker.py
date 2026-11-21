"""
SiteSage — BM25 Ranking Engine (Phase 3).

Implemented completely from scratch without external search engines or APIs.
Features:
- Pure Python Okapi BM25 with Lucene-style non-negative IDF.
- Explainable structural field boosts: Page Title, Section Heading, Position, Depth.
- Transparent score breakdown for every retrieved passage.
- Multi-page ranking and empty/stopword query handling.
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Optional

import config
import database
from indexer import tokenize_text
from models import Passage, ScoreBreakdown, ScoredPassage


class BM25Ranker:
    """Deterministic BM25 passage ranker with explainable field boosts."""

    def __init__(
        self,
        db_path: Path | str = config.DB_PATH,
        k1: float = config.BM25_K1,
        b: float = config.BM25_B,
    ) -> None:
        self.db_path = db_path
        self.k1 = k1
        self.b = b

    def compute_idf(self, total_docs: int, doc_freq: int) -> float:
        """Calculate Lucene-style Robertson-Spärck Jones IDF (always non-negative).

        IDF(q) = ln((N - n(q) + 0.5) / (n(q) + 0.5) + 1.0)
        """
        if total_docs <= 0:
            return 0.0
        return math.log(((total_docs - doc_freq + 0.5) / (doc_freq + 0.5)) + 1.0)

    def rank_passages(
        self,
        session_id: str,
        query: str,
        top_k: int = 10,
    ) -> list[ScoredPassage]:
        """Rank passages for a session against a search query using BM25 and field boosts.

        Returns explainable ScoredPassage list ordered by total_score descending.
        """
        query_terms = tokenize_text(query, remove_stopwords=True)
        if not query_terms:
            return []

        with database.get_db(self.db_path) as conn:
            # 1. Fetch corpus stats
            stats_row = database.get_corpus_stats(conn, session_id)
            if not stats_row or stats_row["total_passages"] == 0:
                return []

            total_passages = stats_row["total_passages"]
            avgdl = stats_row["avg_length"]
            if avgdl <= 0:
                avgdl = 1.0

            # 2. Accumulate postings and term document frequencies
            # term -> set of passage_ids containing this term
            term_docs: dict[str, set[int]] = defaultdict(set)
            # passage_id -> {field: {term: freq}}
            passage_term_freqs: dict[int, dict[str, dict[str, int]]] = defaultdict(
                lambda: defaultdict(lambda: defaultdict(int))
            )
            # passage_id -> passage metadata dict
            passage_meta: dict[int, dict] = {}

            for term in set(query_terms):
                postings = database.get_term_postings(conn, session_id, term)
                for p in postings:
                    pid = p["passage_id"]
                    field = p["field"]
                    freq = p["frequency"]

                    term_docs[term].add(pid)
                    passage_term_freqs[pid][field][term] = freq

                    if pid not in passage_meta:
                        passage_meta[pid] = {
                            "id": pid,
                            "page_url": p["page_url"],
                            "page_title": p["page_title"] or "",
                            "text": p["text"],
                            "position": p["position"],
                            "section_heading": p["section_heading"],
                            "heading_level": p["heading_level"],
                            "token_count": p["token_count"],
                            "page_depth": p["page_depth"] or 0,
                        }

            # If no passages contain any query terms, return empty
            if not passage_meta:
                return []

            # 3. Compute IDF for each query term
            idfs: dict[str, float] = {}
            for term in set(query_terms):
                doc_freq = len(term_docs[term])
                idfs[term] = self.compute_idf(total_passages, doc_freq)

            # 4. Score each matched passage
            scored_results: list[ScoredPassage] = []

            for pid, meta in passage_meta.items():
                body_freqs = passage_term_freqs[pid]["body"]
                heading_freqs = passage_term_freqs[pid]["heading"]
                title_freqs = passage_term_freqs[pid]["title"]

                doc_len = meta["token_count"]
                bm25_score = 0.0
                term_details: list[str] = []

                # Core BM25 across body tokens
                for term in query_terms:
                    tf = body_freqs.get(term, 0)
                    if tf > 0:
                        idf = idfs.get(term, 0.0)
                        denom = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / avgdl))
                        term_score = idf * ((tf * (self.k1 + 1.0)) / denom) if denom > 0 else 0.0
                        bm25_score += term_score
                        term_details.append(f"{term}(tf={tf}, idf={idf:.2f}, score={term_score:.2f})")

                # Field Boost 1: Page Title match
                title_boost = 0.0
                matched_title_terms = []
                for term in query_terms:
                    t_tf = title_freqs.get(term, 0)
                    if t_tf > 0:
                        # Additive boost proportional to term IDF
                        t_score = config.BOOST_TITLE_MATCH * min(1.0, idfs.get(term, 1.0) / 2.0)
                        title_boost += t_score
                        matched_title_terms.append(f"{term}(+{t_score:.2f})")

                # Field Boost 2: Section Heading match
                heading_boost = 0.0
                matched_heading_terms = []
                for term in query_terms:
                    h_tf = heading_freqs.get(term, 0)
                    if h_tf > 0:
                        h_score = config.BOOST_HEADING_MATCH * min(1.0, idfs.get(term, 1.0) / 2.0)
                        heading_boost += h_score
                        matched_heading_terms.append(f"{term}(+{h_score:.2f})")

                # Field Boost 3: Position on page (earlier passages get boost)
                pos = meta["position"]
                position_boost = max(0.0, config.BOOST_POSITION * (1.0 - min(pos, 20) / 20.0))

                # Field Penalty 4: Crawl Depth (pages closer to seed preferred)
                depth = meta["page_depth"]
                depth_penalty = min(config.BOOST_DEPTH_PENALTY, depth * 0.06)

                total_score = max(0.0, bm25_score + title_boost + heading_boost + position_boost - depth_penalty)

                # Human-readable explanation
                explanation_parts = [
                    f"BM25={bm25_score:.2f} [{', '.join(term_details) if term_details else 'no body match'}]",
                ]
                if title_boost > 0:
                    explanation_parts.append(f"TitleBoost=+{title_boost:.2f} ({', '.join(matched_title_terms)})")
                if heading_boost > 0:
                    explanation_parts.append(f"HeadingBoost=+{heading_boost:.2f} ({', '.join(matched_heading_terms)})")
                if position_boost > 0:
                    explanation_parts.append(f"PosBoost=+{position_boost:.2f} (pos={pos})")
                if depth_penalty > 0:
                    explanation_parts.append(f"DepthPenalty=-{depth_penalty:.2f} (depth={depth})")
                explanation_parts.append(f"Final={total_score:.2f}")

                explanation = "; ".join(explanation_parts)

                breakdown = ScoreBreakdown(
                    bm25_score=round(bm25_score, 4),
                    title_boost=round(title_boost, 4),
                    heading_boost=round(heading_boost, 4),
                    position_boost=round(position_boost, 4),
                    depth_penalty=round(depth_penalty, 4),
                    total_score=round(total_score, 4),
                    explanation=explanation,
                )

                passage_obj = Passage(
                    id=meta["id"],
                    page_url=meta["page_url"],
                    page_title=meta["page_title"],
                    text=meta["text"],
                    position=meta["position"],
                    section_heading=meta["section_heading"],
                    heading_level=meta["heading_level"],
                    token_count=meta["token_count"],
                )

                scored_results.append(
                    ScoredPassage(
                        passage=passage_obj,
                        score_breakdown=breakdown,
                    )
                )

            # Sort descending by total_score
            scored_results.sort(key=lambda x: x.score_breakdown.total_score, reverse=True)
            return scored_results[:top_k]
