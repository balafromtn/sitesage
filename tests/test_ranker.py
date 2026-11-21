"""
Tests for the BM25 ranker module — custom BM25 algorithm, IDF calculation,
structural field boosts, score explainability, known dataset ranking, and edge cases.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import database
from indexer import SiteIndexer
from models import CrawledPage, HeadingInfo
from ranker import BM25Ranker


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_ranker.db"
    database.init_db(db_file)
    return db_file


@pytest.fixture
def populated_session(test_db):
    """Create a populated search index with 3 distinct pages for testing."""
    session_id = "test_rank_sess"
    with database.get_db(test_db) as conn:
        database.create_session(conn, session_id, "https://example.com", "sample question")

    # Page 1: Pricing page
    page1 = CrawledPage(
        url="https://example.com/pricing",
        title="SiteSage Pricing and Subscription Plans",
        text="SiteSage pricing starts at twenty dollars per month for individuals and one hundred dollars for enterprise teams.",
        headings=[
            HeadingInfo(level=1, text="Subscription Plans", position=0),
            HeadingInfo(level=2, text="Enterprise Pricing", position=40),
        ],
        crawl_depth=1,
    )

    # Page 2: Architecture page
    page2 = CrawledPage(
        url="https://example.com/docs/architecture",
        title="Technical Architecture Overview",
        text="The system architecture uses Python, FastAPI, SQLite inverted index, and custom BM25 ranking algorithm.",
        headings=[
            HeadingInfo(level=1, text="System Architecture", position=0),
            HeadingInfo(level=2, text="Inverted Index Implementation", position=45),
        ],
        crawl_depth=2,
    )

    # Page 3: FAQ page
    page3 = CrawledPage(
        url="https://example.com/faq",
        title="Frequently Asked Questions",
        text="Frequently asked questions about billing, deployment, installation, and enterprise features.",
        headings=[
            HeadingInfo(level=1, text="General FAQ", position=0),
        ],
        crawl_depth=3,
    )

    indexer = SiteIndexer(db_path=test_db)
    indexer.index_crawled_pages(session_id, [page1, page2, page3])
    return session_id, test_db


# ── IDF Computation ──────────────────────────────────────────────────

class TestIDFComputation:
    def test_idf_always_non_negative(self, test_db):
        ranker = BM25Ranker(db_path=test_db)
        # Even if all documents contain the term (doc_freq == total_docs)
        idf_all = ranker.compute_idf(total_docs=10, doc_freq=10)
        assert idf_all >= 0.0

    def test_rare_terms_have_higher_idf(self, test_db):
        ranker = BM25Ranker(db_path=test_db)
        idf_rare = ranker.compute_idf(total_docs=100, doc_freq=2)
        idf_common = ranker.compute_idf(total_docs=100, doc_freq=80)
        assert idf_rare > idf_common

    def test_zero_docs_returns_zero(self, test_db):
        ranker = BM25Ranker(db_path=test_db)
        assert ranker.compute_idf(total_docs=0, doc_freq=0) == 0.0


# ── BM25 Ranking on Known Dataset ────────────────────────────────────

class TestBM25Ranking:
    def test_relevant_passage_ranks_first(self, populated_session):
        session_id, db_path = populated_session
        ranker = BM25Ranker(db_path=db_path)

        results = ranker.rank_passages(session_id, "How much does enterprise pricing cost?")
        assert len(results) > 0
        top = results[0]

        # Top passage should be from the pricing page
        assert top.passage.page_url == "https://example.com/pricing"
        assert "pricing" in top.passage.text.lower() or "enterprise" in top.passage.text.lower()
        assert top.score_breakdown.total_score > 0

    def test_architecture_query_ranks_architecture_page(self, populated_session):
        session_id, db_path = populated_session
        ranker = BM25Ranker(db_path=db_path)

        results = ranker.rank_passages(session_id, "What is the SQLite inverted index architecture?")
        assert len(results) > 0
        top = results[0]
        assert top.passage.page_url == "https://example.com/docs/architecture"
        assert "sqlite" in top.passage.text.lower()

    def test_title_boost_boosts_matching_page(self, populated_session):
        session_id, db_path = populated_session
        ranker = BM25Ranker(db_path=db_path)

        # Query matches "Architecture" in page 2 title
        results = ranker.rank_passages(session_id, "Technical Architecture")
        assert len(results) > 0
        top = results[0]
        assert top.score_breakdown.title_boost > 0
        assert "TitleBoost" in top.score_breakdown.explanation

    def test_heading_boost_applies(self, populated_session):
        session_id, db_path = populated_session
        ranker = BM25Ranker(db_path=db_path)

        # Query matches "Subscription Plans" heading
        results = ranker.rank_passages(session_id, "Subscription Plans")
        assert len(results) > 0
        top = results[0]
        assert top.score_breakdown.heading_boost > 0
        assert "HeadingBoost" in top.score_breakdown.explanation

    def test_position_boost_applies(self, populated_session):
        session_id, db_path = populated_session
        ranker = BM25Ranker(db_path=db_path)

        results = ranker.rank_passages(session_id, "enterprise")
        assert len(results) > 0
        for r in results:
            assert r.score_breakdown.position_boost >= 0

    def test_depth_penalty_applies(self, populated_session):
        session_id, db_path = populated_session
        ranker = BM25Ranker(db_path=db_path)

        results = ranker.rank_passages(session_id, "enterprise")
        assert len(results) > 0
        # Results from deeper pages have positive depth_penalty
        has_depth_penalty = any(r.score_breakdown.depth_penalty > 0 for r in results)
        assert has_depth_penalty

    def test_explainability_breakdown(self, populated_session):
        session_id, db_path = populated_session
        ranker = BM25Ranker(db_path=db_path)

        results = ranker.rank_passages(session_id, "pricing enterprise")
        assert len(results) > 0
        sb = results[0].score_breakdown

        assert sb.bm25_score >= 0
        assert sb.total_score >= 0
        assert isinstance(sb.explanation, str)
        assert "BM25=" in sb.explanation
        assert "Final=" in sb.explanation

    def test_multi_page_results(self, populated_session):
        session_id, db_path = populated_session
        ranker = BM25Ranker(db_path=db_path)

        # "enterprise" appears on both Page 1 (pricing) and Page 3 (FAQ)
        results = ranker.rank_passages(session_id, "enterprise", top_k=5)
        urls = {r.passage.page_url for r in results}
        assert len(urls) >= 2


# ── Edge Cases ───────────────────────────────────────────────────────

class TestRankerEdgeCases:
    def test_empty_query(self, populated_session):
        session_id, db_path = populated_session
        ranker = BM25Ranker(db_path=db_path)
        assert ranker.rank_passages(session_id, "") == []
        assert ranker.rank_passages(session_id, "   \n\t  ") == []

    def test_stopword_only_query(self, populated_session):
        session_id, db_path = populated_session
        ranker = BM25Ranker(db_path=db_path)
        # All words are stopwords
        assert ranker.rank_passages(session_id, "what is the and or") == []

    def test_unknown_term_query(self, populated_session):
        session_id, db_path = populated_session
        ranker = BM25Ranker(db_path=db_path)
        assert ranker.rank_passages(session_id, "xylophone quantum thermodynamics") == []

    def test_nonexistent_session(self, test_db):
        ranker = BM25Ranker(db_path=test_db)
        assert ranker.rank_passages("no_such_session", "pricing") == []
