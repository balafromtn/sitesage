"""
Tests for Phase 8: Quality Evaluation and Benchmark Metrics.
Verifies:
- Precision & Recall metrics against known ground truth.
- Claim-to-source traceability.
- Multi-aspect question decomposition.
- Missing information and contradiction detection.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import database
from evaluate_benchmark import EVALUATION_DATASET, build_evaluation_corpus
from extractor import EvidenceExtractor, decompose_question
from indexer import SiteIndexer
from ranker import BM25Ranker


@pytest.fixture
def eval_db(tmp_path):
    db_file = tmp_path / "test_eval.db"
    database.init_db(db_file)
    return db_file


def test_benchmark_recall_and_traceability(eval_db):
    session_id = "test_eval_session"
    with database.get_db(eval_db) as conn:
        database.create_session(conn, session_id, "https://sitesage-test.local", "Test Eval")

    pages = build_evaluation_corpus()
    indexer = SiteIndexer(db_path=eval_db)
    indexer.index_crawled_pages(session_id, pages)

    ranker = BM25Ranker(db_path=eval_db)
    extractor = EvidenceExtractor(db_path=eval_db)

    # Test Q01: Simple factual recall
    q1 = "What is the pricing for the Starter plan?"
    top_passages = ranker.rank_passages(session_id, q1, top_k=5)
    retrieved_urls = [p.passage.page_url for p in top_passages]
    assert "https://sitesage-test.local/pricing" in retrieved_urls

    res1 = extractor.process_question(session_id, q1)
    assert len(res1.claims) >= 1
    assert any("$19" in c.claim for c in res1.claims)
    # Check claim traceability
    for c in res1.claims:
        for s in c.sources:
            assert s.page_url != ""
            assert s.exact_quote != ""

    # Test Q02: Multi-aspect compound
    q2 = "What are the pricing tiers, and what features does each tier include?"
    aspects = decompose_question(q2)
    assert len(aspects) >= 2

    # Test Q07: Contradiction detection (14-day vs 30-day refund)
    q7 = "What is the refund window duration?"
    res7 = extractor.process_question(session_id, q7)
    assert len(res7.conflicts) >= 1

    # Test Q09: Out-of-domain missing aspect detection
    q9 = "How do you bake a sourdough chocolate cake?"
    res9 = extractor.process_question(session_id, q9)
    assert len(res9.missing_aspects) >= 1
