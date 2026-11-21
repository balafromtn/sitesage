"""Tests for Pydantic models — validation, defaults, edge cases."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from pydantic import ValidationError

from models import (
    CancelResponse,
    ClaimEvidence,
    CrawlProgress,
    CrawlRequest,
    CrawledPage,
    HeadingInfo,
    Passage,
    QuestionAspect,
    ScoreBreakdown,
    ScoredPassage,
    SearchResult,
    SessionStatus,
    StartSearchResponse,
)


class TestCrawlRequest:
    def test_valid_request(self):
        req = CrawlRequest(url="https://example.com", question="What is this?")
        assert req.max_pages == 30

    def test_max_pages_clamped_to_30(self):
        req = CrawlRequest(url="https://example.com", question="Hello?", max_pages=100)
        assert req.max_pages == 30

    def test_min_question_length(self):
        with pytest.raises(ValidationError):
            CrawlRequest(url="https://example.com", question="ab")

    def test_max_pages_min_1(self):
        with pytest.raises(ValidationError):
            CrawlRequest(url="https://example.com", question="Hello?", max_pages=0)


class TestCrawlProgress:
    def test_defaults(self):
        p = CrawlProgress(session_id="abc", status=SessionStatus.CRAWLING)
        assert p.pages_discovered == 0
        assert p.pages_crawled == 0
        assert p.pages_failed == 0
        assert p.current_url is None
        assert p.timestamp is not None


class TestHeadingInfo:
    def test_valid_heading(self):
        h = HeadingInfo(level=2, text="Introduction", position=0)
        assert h.level == 2

    def test_invalid_level(self):
        with pytest.raises(ValidationError):
            HeadingInfo(level=7, text="Bad", position=0)


class TestCrawledPage:
    def test_defaults(self):
        page = CrawledPage(url="https://example.com")
        assert page.title == ""
        assert page.headings == []
        assert page.links == []


class TestPassage:
    def test_defaults(self):
        p = Passage()
        assert p.id == 0
        assert p.section_heading is None


class TestScoreBreakdown:
    def test_defaults(self):
        s = ScoreBreakdown()
        assert s.total_score == 0.0
        assert s.explanation == ""


class TestClaimEvidence:
    def test_confidence_bounds(self):
        c = ClaimEvidence(claim="test", confidence=0.5)
        assert c.confidence == 0.5

    def test_confidence_out_of_range(self):
        with pytest.raises(ValidationError):
            ClaimEvidence(claim="test", confidence=1.5)


class TestSearchResult:
    def test_defaults(self):
        r = SearchResult()
        assert r.answer == ""
        assert r.claims == []
        assert r.ai_polished is False


class TestSessionStatus:
    def test_all_statuses(self):
        expected = {"pending", "crawling", "indexing", "ranking",
                    "extracting", "polishing", "done", "cancelled", "error"}
        assert {s.value for s in SessionStatus} == expected
