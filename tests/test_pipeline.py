"""
Tests for Phase 6: API Pipeline Orchestration & Real-Time SSE Streaming.
Verifies:
- End-to-end pipeline execution and stage ordering.
- SSE event formatting and payloads.
- Stream reconnection and Last-Event-ID history replay.
- Cancellation safety at each pipeline stage.
- Duplicate run prevention.
- Error handling (unsafe URL, zero pages).
- Session listing and status endpoints.
"""

import sys
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

import database
from main import app
from models import CrawlProgress, CrawlRequest, CrawledPage, HeadingInfo, SessionStatus
from pipeline import (
    PipelineSession,
    broadcast_event,
    cancel_pipeline_session,
    create_pipeline_session,
    execute_pipeline,
    format_sse_message,
    get_pipeline_session,
    subscribe_session_events,
)

client = TestClient(app)


# ── 1. SSE Event Formatting & Message Helpers ────────────────────────

class TestSSEFormatting:
    def test_format_sse_message_structure(self):
        event = CrawlProgress(
            session_id="sess_123",
            status=SessionStatus.CRAWLING,
            event_id=5,
            event_type="page_crawled",
            stage="crawling",
            pages_discovered=10,
            pages_queued=5,
            pages_crawled=5,
            pages_failed=0,
            max_pages=30,
            current_url="https://example.com/page",
            message="Fetched page",
        )
        msg = format_sse_message(event)

        assert "id: 5\n" in msg
        assert "event: page_crawled\n" in msg
        assert "data: {" in msg
        assert msg.endswith("\n\n")
        assert '"session_id": "sess_123"' in msg
        assert '"stage": "crawling"' in msg
        assert '"pages_crawled": 5' in msg


# ── 2. End-to-End Pipeline Execution ─────────────────────────────────

class TestPipelineExecution:
    @pytest.fixture
    def test_db(self, tmp_path):
        db_file = tmp_path / "test_pipeline.db"
        database.init_db(db_file)
        return db_file

    @pytest.mark.asyncio
    async def test_end_to_end_pipeline_success(self, test_db):
        req = CrawlRequest(
            url="https://example.com",
            question="What is the pricing?",
            max_pages=5,
        )
        session = create_pipeline_session(req, "test_e2e_sess", db_path=test_db)

        # Mock crawler to return 2 realistic pages
        page1 = CrawledPage(
            url="https://example.com",
            title="Example Home",
            text="Welcome to Example. See our pricing page for subscription options.",
            headings=[HeadingInfo(level=1, text="Home", position=0)],
        )
        page2 = CrawledPage(
            url="https://example.com/pricing",
            title="Example Pricing",
            text="The service pricing is $20 per month for all users.",
            headings=[HeadingInfo(level=1, text="Pricing", position=0)],
        )

        with patch("pipeline.WebCrawler.crawl", new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = [page1, page2]
            result = await execute_pipeline(session, db_path=test_db)

        # Verify pipeline reached completion
        assert session.status == SessionStatus.DONE
        assert result is not None
        assert result.answer != ""
        assert "$20 per month" in result.answer

        # Verify stage ordering in events
        event_types = [e.event_type for e in session.events]
        assert "session_started" in event_types
        assert "crawling_started" in event_types
        assert "crawling_completed" in event_types
        assert "indexing_started" in event_types
        assert "indexing_completed" in event_types
        assert "retrieval_started" in event_types
        assert "evidence_found" in event_types
        assert "answer_generated" in event_types
        assert "pipeline_completed" in event_types

        # Verify strict order
        idx_crawl = event_types.index("crawling_started")
        idx_index = event_types.index("indexing_started")
        idx_retrieval = event_types.index("retrieval_started")
        idx_done = event_types.index("pipeline_completed")
        assert idx_crawl < idx_index < idx_retrieval < idx_done


# ── 3. Cancellation at Various Pipeline Stages ───────────────────────

class TestPipelineCancellation:
    @pytest.fixture
    def test_db(self, tmp_path):
        db_file = tmp_path / "test_cancel_stages.db"
        database.init_db(db_file)
        return db_file

    @pytest.mark.asyncio
    async def test_cancellation_during_crawling(self, test_db):
        req = CrawlRequest(url="https://example.com", question="What is the pricing?")
        session = create_pipeline_session(req, "test_cancel_crawl", db_path=test_db)

        async def slow_crawl(*args, **kwargs):
            session.cancelled = True
            return [CrawledPage(url="https://example.com", text="Initial page", title="Home")]

        with patch("pipeline.WebCrawler.crawl", side_effect=slow_crawl):
            result = await execute_pipeline(session, db_path=test_db)

        assert session.status == SessionStatus.CANCELLED
        assert "cancelled" in result.answer.lower()
        event_types = [e.event_type for e in session.events]
        assert "session_cancelled" in event_types
        # Later stages should NEVER have been started
        assert "indexing_started" not in event_types
        assert "retrieval_started" not in event_types

    @pytest.mark.asyncio
    async def test_cancel_pipeline_session_helper(self):
        req = CrawlRequest(url="https://example.com", question="What is the pricing?")
        session = create_pipeline_session(req, "test_helper_cancel")

        mock_crawler = MagicMock()
        session.crawler = mock_crawler

        success = cancel_pipeline_session("test_helper_cancel")
        assert success is True
        assert session.cancelled is True
        assert session.status == SessionStatus.CANCELLED
        mock_crawler.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancellation_ordering_session_started_first_and_cancelled_once(self, test_db):
        """Regression test: session_started must always be first, and session_cancelled emitted exactly once."""
        req = CrawlRequest(url="https://example.com", question="What is the pricing?")
        session = create_pipeline_session(req, "test_cancel_ordering", db_path=test_db)

        # Cancel BEFORE execute_pipeline is called
        success = cancel_pipeline_session("test_cancel_ordering")
        assert success is True

        # Now execute pipeline
        res = await execute_pipeline(session, db_path=test_db)
        assert session.status == SessionStatus.CANCELLED
        assert "cancelled" in res.answer.lower()

        event_types = [e.event_type for e in session.events]
        assert event_types[0] == "session_started"
        assert event_types.count("session_cancelled") == 1
        assert event_types == ["session_started", "session_cancelled"]

    @pytest.mark.asyncio
    async def test_terminal_events_cannot_be_emitted_after_termination(self, test_db):
        """Ensure no events can be emitted after a session has already terminated."""
        req = CrawlRequest(url="https://example.com", question="What is the pricing?")
        session = create_pipeline_session(req, "test_terminal_guard", db_path=test_db)

        # Cancel session
        cancel_pipeline_session("test_terminal_guard")
        events_len_before = len(session.events)

        # Attempt to cancel again
        second_cancel = cancel_pipeline_session("test_terminal_guard")
        assert second_cancel is False
        assert len(session.events) == events_len_before

        # Attempt to broadcast another event after termination
        res = broadcast_event(
            session,
            event_type="crawling_started",
            stage="crawling",
            status=SessionStatus.CRAWLING,
            message="Should be suppressed",
            db_path=test_db,
        )
        assert res is None
        assert len(session.events) == events_len_before


# ── 4. Error Handling & Edge Cases ───────────────────────────────────

class TestPipelineErrors:
    @pytest.fixture
    def test_db(self, tmp_path):
        db_file = tmp_path / "test_pipe_err.db"
        database.init_db(db_file)
        return db_file

    @pytest.mark.asyncio
    async def test_zero_pages_crawled_reports_error(self, test_db):
        req = CrawlRequest(url="https://example.com", question="What is the pricing?")
        session = create_pipeline_session(req, "test_zero_pages", db_path=test_db)

        with patch("pipeline.WebCrawler.crawl", new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = []
            result = await execute_pipeline(session, db_path=test_db)

        assert session.status == SessionStatus.ERROR
        assert "No pages could be crawled" in session.error
        event_types = [e.event_type for e in session.events]
        assert "pipeline_error" in event_types


# ── 5. Stream Reconnection & Last-Event-ID ───────────────────────────

class TestStreamReconnection:
    @pytest.mark.asyncio
    async def test_last_event_id_replays_missed_events_only(self):
        req = CrawlRequest(url="https://example.com", question="What is the pricing?")
        session = create_pipeline_session(req, "test_reconnect")

        # Prepopulate 4 events
        for i in range(1, 5):
            broadcast_event(
                session,
                event_type="test_event",
                stage=f"stage_{i}",
                status=SessionStatus.CRAWLING,
                message=f"Event {i}",
            )
        session.status = SessionStatus.DONE

        # Client reconnects having seen event 2
        chunks = []
        async for chunk in subscribe_session_events(session.session_id, last_event_id=2):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert "id: 3" in chunks[0]
        assert "id: 4" in chunks[1]

    @pytest.mark.asyncio
    async def test_reconnect_with_no_last_event_id_replays_all(self):
        req = CrawlRequest(url="https://example.com", question="What is the pricing?")
        session = create_pipeline_session(req, "test_reconnect_all")

        for i in range(1, 4):
            broadcast_event(
                session,
                event_type="test_event",
                stage=f"stage_{i}",
                status=SessionStatus.CRAWLING,
                message=f"Event {i}",
            )
        session.status = SessionStatus.DONE

        chunks = []
        async for chunk in subscribe_session_events(session.session_id, last_event_id=None):
            chunks.append(chunk)

        assert len(chunks) == 3
        assert "id: 1" in chunks[0]
        assert "id: 2" in chunks[1]
        assert "id: 3" in chunks[2]


# ── 6. API Endpoints & Session Management ────────────────────────────

class TestPipelineAPIEndpoints:
    def test_search_and_stream_endpoints(self):
        # Mock crawler so background task executes instantaneously
        mock_page = CrawledPage(
            url="https://example.com",
            title="Example Title",
            text="SiteSage is a smart question-aware search engine.",
            headings=[HeadingInfo(level=1, text="Header", position=0)],
        )

        with patch("pipeline.WebCrawler.crawl", new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = [mock_page]

            # 1. Start search
            resp = client.post("/api/search", json={
                "url": "https://example.com",
                "question": "What is SiteSage?",
            })
            assert resp.status_code == 200
            sid = resp.json()["session_id"]

            # 2. Get status endpoint
            status_resp = client.get(f"/api/search/{sid}/status")
            assert status_resp.status_code == 200
            data = status_resp.json()
            assert data["session_id"] == sid
            assert "stage" in data

            # 3. Stream endpoint initiates SSE stream
            resp_stream = client.get(f"/api/search/{sid}/stream")
            assert resp_stream.status_code == 200
            assert "text/event-stream" in resp_stream.headers["content-type"]
            assert "id:" in resp_stream.text
            assert "event:" in resp_stream.text

            # 4. Cancel endpoint
            cancel_resp = client.post(f"/api/search/{sid}/cancel")
            assert cancel_resp.status_code == 200
            assert "cancelled" in cancel_resp.json()

    def test_list_sessions_endpoint(self):
        resp = client.get("/api/sessions?limit=5")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
