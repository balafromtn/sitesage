"""
Tests for the extractor module (Phase 4) — question decomposition,
aspect evidence retrieval, claim extraction, exact source traceability,
conflict detection, missing aspect detection, and API endpoints.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

import database
from extractor import (
    EvidenceExtractor,
    calculate_jaccard_similarity,
    decompose_question,
    detect_conflicts,
    extract_aspect_claims,
    retrieve_aspect_evidence,
    synthesize_deterministic_answer,
)
from indexer import SiteIndexer
from main import app
from models import ClaimEvidence, CrawledPage, HeadingInfo, QuestionAspect, SourceReference

client = TestClient(app)


# ── 1. Question Decomposition Tests ──────────────────────────────────

class TestQuestionDecomposition:
    def test_simple_question_not_decomposed(self):
        aspects = decompose_question("What is the refund policy?")
        assert len(aspects) == 1
        assert "refund policy" in aspects[0].aspect.lower()

    def test_pricing_simple_question(self):
        aspects = decompose_question("How much does the annual subscription cost?")
        assert len(aspects) == 1
        assert "cost" in aspects[0].keywords or "subscription" in aspects[0].keywords

    def test_idiom_with_and_not_split(self):
        # "terms and conditions" should remain single aspect
        aspects = decompose_question("What are the terms and conditions?")
        assert len(aspects) == 1
        assert "terms and conditions" in aspects[0].aspect.lower()

    def test_compound_question_split_by_conjunction(self):
        q = "What are the pricing plans, and what features does each include?"
        aspects = decompose_question(q)
        assert len(aspects) >= 2
        asp_texts = [a.aspect.lower() for a in aspects]
        assert any("pricing" in t for t in asp_texts)
        assert any("features" in t for t in asp_texts)

    def test_compound_question_split_by_punctuation(self):
        q = "Where is the head office located? What are the support hours?"
        aspects = decompose_question(q)
        assert len(aspects) == 2
        assert "office" in aspects[0].keywords or "located" in aspects[0].keywords
        assert "hours" in aspects[1].keywords or "support" in aspects[1].keywords

    def test_comparison_vs_question(self):
        q = "Docker vs Kubernetes"
        aspects = decompose_question(q)
        assert len(aspects) >= 2
        asp_texts = [a.aspect.lower() for a in aspects]
        assert any("docker" in t for t in asp_texts)
        assert any("kubernetes" in t for t in asp_texts)

    def test_difference_between_question(self):
        q = "What is the difference between SQLite and PostgreSQL?"
        aspects = decompose_question(q)
        assert len(aspects) >= 2
        asp_texts = [a.aspect.lower() for a in aspects]
        assert any("sqlite" in t for t in asp_texts)
        assert any("postgresql" in t for t in asp_texts)

    def test_empty_question(self):
        assert decompose_question("") == []
        assert decompose_question("   ") == []


# ── 2. Evidence Retrieval & Deduplication ────────────────────────────

class TestEvidenceRetrieval:
    @pytest.fixture
    def indexed_session(self, tmp_path):
        db_file = tmp_path / "test_extract.db"
        database.init_db(db_file)
        session_id = "test_extract_sess"

        with database.get_db(db_file) as conn:
            database.create_session(conn, session_id, "https://example.com", "q")

        page1 = CrawledPage(
            url="https://example.com/pricing",
            title="Pricing Plans",
            text="The Basic plan costs $10 monthly. The Pro plan costs $30 monthly.",
            headings=[HeadingInfo(level=1, text="Pricing", position=0)],
            crawl_depth=1,
        )
        page2 = CrawledPage(
            url="https://example.com/features",
            title="Feature Matrix",
            text="The Pro plan includes priority support and unlimited exports.",
            headings=[HeadingInfo(level=1, text="Features", position=0)],
            crawl_depth=1,
        )

        indexer = SiteIndexer(db_path=db_file)
        indexer.index_crawled_pages(session_id, [page1, page2])
        return session_id, db_file

    def test_retrieve_aspect_evidence(self, indexed_session):
        session_id, db_path = indexed_session
        aspects = [
            QuestionAspect(aspect="pricing plans", keywords=["pricing", "plans"]),
            QuestionAspect(aspect="features included", keywords=["features", "included"]),
        ]
        evidence_map, all_evidence = retrieve_aspect_evidence(
            session_id=session_id,
            aspects=aspects,
            db_path=db_path,
        )
        assert "pricing plans" in evidence_map
        assert "features included" in evidence_map
        assert len(all_evidence) >= 2

    def test_jaccard_similarity_calculation(self):
        text1 = "Python programming language is versatile and popular."
        text2 = "Python programming language is versatile and popular."
        text3 = "Completely different text about gardening tools."
        assert calculate_jaccard_similarity(text1, text2) == 1.0
        assert calculate_jaccard_similarity(text1, text3) == 0.0


# ── 3. Claim Extraction & Exact Source Traceability ──────────────────

class TestClaimExtraction:
    @pytest.fixture
    def populated_db(self, tmp_path):
        db_file = tmp_path / "test_claims.db"
        database.init_db(db_file)
        session_id = "sess_claims"

        with database.get_db(db_file) as conn:
            database.create_session(conn, session_id, "https://example.com", "q")

        page1 = CrawledPage(
            url="https://example.com/plans",
            title="Subscriptions",
            text="The starter plan begins at $15 per month. It includes 5GB cloud storage.",
            headings=[HeadingInfo(level=1, text="Plans", position=0)],
            crawl_depth=1,
        )
        page2 = CrawledPage(
            url="https://example.com/support",
            title="Customer Support",
            text="Support is available 24/7 via live chat. The starter plan begins at $15 per month.",
            headings=[HeadingInfo(level=1, text="Help Desk", position=0)],
            crawl_depth=1,
        )

        indexer = SiteIndexer(db_path=db_file)
        indexer.index_crawled_pages(session_id, [page1, page2])
        return session_id, db_file

    def test_claim_traceability_to_exact_url_and_passage(self, populated_db):
        session_id, db_path = populated_db
        aspect = QuestionAspect(aspect="starter plan pricing", keywords=["starter", "plan", "month"])

        aspect_evidence, _ = retrieve_aspect_evidence(session_id, [aspect], db_path=db_path)
        claims = extract_aspect_claims(aspect, aspect_evidence[aspect.aspect])

        assert len(claims) >= 1
        claim = claims[0]

        # Verify exact supporting text preserved
        assert "$15 per month" in claim.claim

        # Verify source references exist and are complete
        assert len(claim.sources) >= 1
        src = claim.sources[0]
        assert src.page_url.startswith("https://example.com/")
        assert src.passage_id > 0
        assert src.exact_quote == claim.claim

        # Verify confidence is bounded [0.0, 1.0]
        assert 0.0 <= claim.confidence <= 1.0

    def test_multi_page_corroboration_boosts_confidence(self, populated_db):
        session_id, db_path = populated_db
        aspect = QuestionAspect(aspect="starter plan", keywords=["starter", "plan", "month"])

        aspect_evidence, _ = retrieve_aspect_evidence(session_id, [aspect], db_path=db_path)
        claims = extract_aspect_claims(aspect, aspect_evidence[aspect.aspect])

        # The claim "The starter plan begins at $15 per month." appears on both page 1 and page 2
        matching = [c for c in claims if "$15 per month" in c.claim]
        assert len(matching) == 1
        corroborated_claim = matching[0]

        # Should have sources from both pages
        source_urls = {s.page_url for s in corroborated_claim.sources}
        assert len(source_urls) == 2
        assert corroborated_claim.confidence > 0.4


# ── 4. Multi-Page Reasoning & Missing Information ────────────────────

class TestMultiPageReasoning:
    @pytest.fixture
    def multi_page_db(self, tmp_path):
        db_file = tmp_path / "test_multi.db"
        database.init_db(db_file)
        session_id = "sess_multi"

        with database.get_db(db_file) as conn:
            database.create_session(conn, session_id, "https://example.com", "q")

        page_pricing = CrawledPage(
            url="https://example.com/pricing",
            title="Pricing Information",
            text="Team plan costs $50 per user per month. Invoices can be paid via credit card.",
            headings=[HeadingInfo(level=1, text="Pricing", position=0)],
        )
        page_features = CrawledPage(
            url="https://example.com/features",
            title="Feature Capabilities",
            text="Team plan includes SSO integration and audit logging features.",
            headings=[HeadingInfo(level=1, text="Features", position=0)],
        )

        indexer = SiteIndexer(db_path=db_file)
        indexer.index_crawled_pages(session_id, [page_pricing, page_features])
        return session_id, db_file

    def test_compound_question_extracts_from_both_pages(self, multi_page_db):
        session_id, db_path = multi_page_db
        extractor = EvidenceExtractor(db_path=db_path)

        compound_q = "What does the team plan cost, and what features does it include?"
        result = extractor.process_question(session_id, compound_q)

        assert len(result.claims) >= 2
        urls = {s.page_url for c in result.claims for s in c.sources}
        assert "https://example.com/pricing" in urls
        assert "https://example.com/features" in urls

        # Answer should contain both sections
        assert "cost" in result.answer.lower() or "$50" in result.answer
        assert "sso" in result.answer.lower() or "audit" in result.answer.lower()

    def test_missing_aspect_detected(self, multi_page_db):
        session_id, db_path = multi_page_db
        extractor = EvidenceExtractor(db_path=db_path)

        partially_missing_q = "What does the team plan cost, and what is your Tokyo office address?"
        result = extractor.process_question(session_id, partially_missing_q)

        # Team plan cost should be answered
        assert any("$50" in c.claim for c in result.claims)

        # Tokyo office address should be flagged as missing
        assert len(result.missing_aspects) >= 1
        assert any("tokyo" in m.lower() or "address" in m.lower() for m in result.missing_aspects)
        assert "Unanswered Aspects" in result.answer


# ── 5. Conflict Detection Tests ──────────────────────────────────────

class TestConflictDetection:
    def test_detect_numeric_conflict(self):
        c1 = ClaimEvidence(
            claim="The basic plan price is $20 per month.",
            sources=[SourceReference(page_url="https://example.com/pricing1", exact_quote="The basic plan price is $20 per month.")],
            aspect="Pricing",
        )
        c2 = ClaimEvidence(
            claim="The basic plan price is $50 per month.",
            sources=[SourceReference(page_url="https://example.com/pricing2", exact_quote="The basic plan price is $50 per month.")],
            aspect="Pricing",
        )

        conflicts = detect_conflicts([c1, c2])
        assert len(conflicts) == 1
        assert c1.conflict_detected is True
        assert c2.conflict_detected is True
        assert "Conflicting numeric figures" in conflicts[0].explanation

    def test_detect_negation_conflict(self):
        c1 = ClaimEvidence(
            claim="SSO authentication is supported on all tiers.",
            sources=[SourceReference(page_url="https://example.com/auth1", exact_quote="SSO authentication is supported on all tiers.")],
            aspect="Authentication",
        )
        c2 = ClaimEvidence(
            claim="SSO authentication is not supported on all tiers.",
            sources=[SourceReference(page_url="https://example.com/auth2", exact_quote="SSO authentication is not supported on all tiers.")],
            aspect="Authentication",
        )

        conflicts = detect_conflicts([c1, c2])
        assert len(conflicts) == 1
        assert c1.conflict_detected is True
        assert c2.conflict_detected is True


# ── 6. Deterministic Answer Assembly ────────────────────────────────

class TestAnswerAssembly:
    def test_completely_unanswered_question(self):
        aspects = [QuestionAspect(aspect="Secret Alien Base", keywords=["alien", "base"])]
        answer = synthesize_deterministic_answer(
            question="Where is the secret alien base located?",
            aspects=aspects,
            claims=[],
            missing_aspects=["Secret Alien Base"],
            conflicts=[],
        )
        assert "does not contain adequate information" in answer
        assert "Secret Alien Base" in answer


# ── 7. API Integration Tests ─────────────────────────────────────────

class TestAPIIntegration:
    def test_analyze_question_endpoint(self):
        resp = client.post("/api/analyze_question", json={
            "question": "What is the cost of the plan, and what features are included?"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "aspects" in data
        assert len(data["aspects"]) >= 2

    def test_extract_evidence_endpoint(self, tmp_path):
        # Create session
        create = client.post("/api/search", json={
            "url": "https://example.com",
            "question": "What are the pricing details?",
        })
        sid = create.json()["session_id"]

        # Insert page & index
        with database.get_db() as conn:
            pid = database.insert_page(
                conn, sid, "https://example.com/p", "Pricing",
                "Our software pricing is free for open source projects.", 0, 200
            )
            database.insert_heading(conn, pid, 1, "Price", 0)

        client.post(f"/api/index/{sid}")

        # Extract evidence endpoint
        extract_resp = client.post(f"/api/extract_evidence/{sid}?question=What+is+the+pricing")
        assert extract_resp.status_code == 200
        result = extract_resp.json()
        assert "claims" in result
        assert len(result["claims"]) >= 1
        assert "free for open source" in result["answer"].lower()
