"""
SiteSage — Unified Pipeline Orchestrator & Real-Time SSE Streaming (Phase 6).

Coordinates the complete search workflow:
1. Session Initialization & Request Validation
2. Question-Aware Priority Crawling (WebCrawler)
3. Passage Extraction & Inverted Indexing (SiteIndexer)
4. Multi-Aspect Decomposition & BM25 Evidence Retrieval (EvidenceExtractor)
5. Optional AI Polishing with Strict Evidence Boundaries (AnswerPolisher)
6. SQLite Result Persistence & Real-Time SSE Event Streaming with Reconnection.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Optional

import config
import database
from crawler import WebCrawler
from extractor import EvidenceExtractor
from indexer import SiteIndexer
from models import CrawlProgress, CrawlRequest, SearchResult, SessionStatus
from polisher import AnswerPolisher

logger = logging.getLogger(__name__)


# ── Pipeline Session State ───────────────────────────────────────────

@dataclass
class PipelineSession:
    """In-memory state for an active or completed search pipeline."""
    session_id: str
    request: CrawlRequest
    status: SessionStatus = SessionStatus.PENDING
    stage: str = "initialization"
    pages_discovered: int = 0
    pages_queued: int = 0
    pages_crawled: int = 0
    pages_failed: int = 0
    max_pages: int = 30
    current_url: Optional[str] = None
    crawler: Optional[WebCrawler] = None
    cancelled: bool = False
    task: Optional[asyncio.Task] = None
    events: list[CrawlProgress] = field(default_factory=list)
    subscribers: list[asyncio.Queue[CrawlProgress]] = field(default_factory=list)
    result: Optional[SearchResult] = None
    error: Optional[str] = None


# Session registry
_PIPELINE_SESSIONS: dict[str, PipelineSession] = {}


def get_pipeline_session(session_id: str) -> Optional[PipelineSession]:
    """Retrieve an active or registered pipeline session."""
    return _PIPELINE_SESSIONS.get(session_id)


def create_pipeline_session(
    req: CrawlRequest,
    session_id: str,
    db_path: Path | str = config.DB_PATH,
) -> PipelineSession:
    """Create and register a new pipeline session."""
    session = PipelineSession(
        session_id=session_id,
        request=req,
        max_pages=req.max_pages,
    )
    _PIPELINE_SESSIONS[session_id] = session

    # Ensure recorded in SQLite
    try:
        with database.get_db(db_path) as conn:
            if not database.get_session(conn, session_id):
                database.create_session(conn, session_id, req.url, req.question)
    except Exception as e:
        logger.warning("Could not insert session %s into DB: %s", session_id, e)

    return session


TERMINAL_EVENTS = frozenset({"pipeline_completed", "pipeline_error", "session_cancelled"})


# ── Event Broadcasting & SSE ─────────────────────────────────────────

def broadcast_event(
    session: PipelineSession,
    event_type: str,
    stage: str,
    status: SessionStatus,
    message: str,
    *,
    current_url: Optional[str] = None,
    db_path: Path | str = config.DB_PATH,
) -> Optional[CrawlProgress]:
    """Create, record, and dispatch a structured pipeline progress event."""
    # Ensure terminal events cannot be emitted after a session has already terminated
    for ev in session.events:
        if ev.event_type in TERMINAL_EVENTS:
            logger.debug(
                "Suppressing event '%s' on session %s: already terminated with '%s'",
                event_type,
                session.session_id,
                ev.event_type,
            )
            return None

    # If this event itself is a terminal event, make sure it's not a duplicate terminal event
    if event_type in TERMINAL_EVENTS:
        if any(ev.event_type == event_type for ev in session.events):
            return None

    session.status = status
    session.stage = stage
    if current_url:
        session.current_url = current_url

    event_id = len(session.events) + 1
    event = CrawlProgress(
        session_id=session.session_id,
        status=status,
        event_id=event_id,
        event_type=event_type,
        stage=stage,
        pages_discovered=session.pages_discovered,
        pages_queued=session.pages_queued,
        pages_crawled=session.pages_crawled,
        pages_failed=session.pages_failed,
        max_pages=session.max_pages,
        current_url=session.current_url,
        message=message,
        timestamp=datetime.now(timezone.utc),
    )

    session.events.append(event)

    # Dispatch to all active SSE listener queues
    for q in list(session.subscribers):
        try:
            q.put_nowait(event)
        except Exception:
            pass

    # Synchronize status to SQLite
    try:
        with database.get_db(db_path) as conn:
            database.update_session_status(
                conn,
                session.session_id,
                status=status.value,
                pages_discovered=session.pages_discovered,
                pages_queued=session.pages_queued,
                pages_crawled=session.pages_crawled,
                pages_failed=session.pages_failed,
            )
    except Exception as e:
        logger.debug("Failed updating session status in DB: %s", e)

    return event


def format_sse_message(event: CrawlProgress) -> str:
    """Format a CrawlProgress event into an official SSE chunk."""
    data_json = json.dumps(
        {
            "session_id": event.session_id,
            "status": event.status.value,
            "event_id": event.event_id,
            "event_type": event.event_type,
            "stage": event.stage,
            "pages_discovered": event.pages_discovered,
            "pages_queued": event.pages_queued,
            "pages_crawled": event.pages_crawled,
            "pages_failed": event.pages_failed,
            "max_pages": event.max_pages,
            "current_url": event.current_url,
            "message": event.message,
            "timestamp": event.timestamp.isoformat(),
        }
    )
    return f"id: {event.event_id}\nevent: {event.event_type}\ndata: {data_json}\n\n"


async def subscribe_session_events(
    session_id: str,
    last_event_id: Optional[int] = None,
) -> AsyncGenerator[str, None]:
    """Yield a continuous SSE event stream for a session, supporting reconnection."""
    session = get_pipeline_session(session_id)
    if not session:
        # Check SQLite if session exists in DB but not active in memory
        with database.get_db() as conn:
            row = database.get_session(conn, session_id)
        if not row:
            err_event = CrawlProgress(
                session_id=session_id,
                status=SessionStatus.ERROR,
                event_type="pipeline_error",
                stage="error",
                message="Session not found",
            )
            yield format_sse_message(err_event)
            return

        # Reconstruct completed event from DB
        status_val = SessionStatus(row["status"]) if row["status"] in [s.value for s in SessionStatus] else SessionStatus.DONE
        final_event = CrawlProgress(
            session_id=session_id,
            status=status_val,
            event_id=1,
            event_type="pipeline_completed" if status_val == SessionStatus.DONE else "pipeline_error",
            stage=status_val.value,
            pages_discovered=row["pages_discovered"] or 0,
            pages_crawled=row["pages_crawled"] or 0,
            pages_failed=row["pages_failed"] or 0,
            message=f"Session status: {status_val.value}",
        )
        yield format_sse_message(final_event)
        return

    # 1. Replay historical events since last_event_id for reconnection
    start_id = last_event_id or 0
    for ev in session.events:
        if ev.event_id > start_id:
            yield format_sse_message(ev)

    # If session is already terminal, end stream
    if session.status in (SessionStatus.DONE, SessionStatus.CANCELLED, SessionStatus.ERROR):
        return

    # 2. Subscribe to live events
    queue: asyncio.Queue[CrawlProgress] = asyncio.Queue()
    session.subscribers.append(queue)

    try:
        while True:
            try:
                # Wait for next event with keepalive timeout
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
                yield format_sse_message(event)

                # Terminal events close stream
                if event.event_type in ("pipeline_completed", "pipeline_error", "session_cancelled"):
                    break
            except asyncio.TimeoutError:
                # SSE keepalive comment
                yield ": keepalive\n\n"
    finally:
        # Clean up subscriber on client disconnect without terminating pipeline
        if queue in session.subscribers:
            session.subscribers.remove(queue)


# ── Pipeline Orchestration Logic ─────────────────────────────────────

async def execute_pipeline(
    session: PipelineSession,
    db_path: Path | str = config.DB_PATH,
) -> SearchResult:
    """Execute the end-to-end SiteSage search pipeline asynchronously."""
    session_id = session.session_id
    req = session.request

    # Ensure session exists in target DB
    try:
        with database.get_db(db_path) as conn:
            if not database.get_session(conn, session_id):
                database.create_session(conn, session_id, req.url, req.question)
    except Exception as e:
        logger.debug("Session record ensure check: %s", e)

    # Stage 1: Session Started (Ensure emitted first and exactly once)
    if not any(e.event_type == "session_started" for e in session.events):
        broadcast_event(
            session,
            event_type="session_started",
            stage="initialization",
            status=SessionStatus.PENDING,
            message=f"Session initialized for {req.url}",
            db_path=db_path,
        )

    if session.cancelled:
        return _handle_cancellation(session, db_path)

    # Stage 2: Crawling
    broadcast_event(
        session,
        event_type="crawling_started",
        stage="crawling",
        status=SessionStatus.CRAWLING,
        message=f"Starting priority crawl of {req.url} (max {req.max_pages} pages)",
        db_path=db_path,
    )

    crawler = WebCrawler(
        session_id=session_id,
        seed_url=req.url,
        question=req.question,
        max_pages=req.max_pages,
        persist_to_db=True,
        db_path=db_path,
    )
    session.crawler = crawler

    def on_crawl_progress(cp: CrawlProgress) -> None:
        session.pages_discovered = cp.pages_discovered
        session.pages_queued = cp.pages_queued
        session.pages_crawled = cp.pages_crawled
        session.pages_failed = cp.pages_failed

        event_name = "page_crawled" if cp.pages_crawled > 0 else "page_discovered"
        if cp.status == SessionStatus.ERROR:
            event_name = "page_failed"

        broadcast_event(
            session,
            event_type=event_name,
            stage="crawling",
            status=SessionStatus.CRAWLING,
            message=cp.message or f"Fetching {cp.current_url}",
            current_url=cp.current_url,
            db_path=db_path,
        )

    try:
        pages = await crawler.crawl(progress_callback=on_crawl_progress)
    except Exception as e:
        logger.exception("Crawler failed with unhandled exception: %s", e)
        return _handle_error(session, f"Crawler error: {e}", db_path)

    if session.cancelled or crawler.is_cancelled:
        return _handle_cancellation(session, db_path)

    if not pages:
        return _handle_error(session, "No pages could be crawled from the provided URL.", db_path)

    session.pages_queued = 0
    broadcast_event(
        session,
        event_type="crawling_completed",
        stage="crawling",
        status=SessionStatus.CRAWLING,
        message=f"Successfully crawled {len(pages)} pages.",
        db_path=db_path,
    )

    # Stage 3: Indexing
    if session.cancelled:
        return _handle_cancellation(session, db_path)

    broadcast_event(
        session,
        event_type="indexing_started",
        stage="indexing",
        status=SessionStatus.INDEXING,
        message=f"Extracting passages and constructing inverted index for {len(pages)} pages...",
        db_path=db_path,
    )

    try:
        indexer = SiteIndexer(db_path=db_path)
        passages = indexer.index_crawled_pages(session_id, pages)
        broadcast_event(
            session,
            event_type="indexing_completed",
            stage="indexing",
            status=SessionStatus.INDEXING,
            message=f"Constructed index with {len(passages)} searchable passages.",
            db_path=db_path,
        )
    except Exception as e:
        logger.exception("Indexing failed: %s", e)
        return _handle_error(session, f"Indexing error: {e}", db_path)

    # Stage 4: Multi-Aspect Decomposition & Evidence Retrieval
    if session.cancelled:
        return _handle_cancellation(session, db_path)

    broadcast_event(
        session,
        event_type="retrieval_started",
        stage="retrieval",
        status=SessionStatus.RANKING,
        message="Decomposing question into aspects and scoring passages with BM25...",
        db_path=db_path,
    )

    try:
        extractor = EvidenceExtractor(db_path=db_path)
        det_result = extractor.process_question(session_id, req.question)

        broadcast_event(
            session,
            event_type="evidence_found",
            stage="retrieval",
            status=SessionStatus.EXTRACTING,
            message=f"Identified {len(det_result.claims)} verified claims across {det_result.pages_crawled} pages.",
            db_path=db_path,
        )

        broadcast_event(
            session,
            event_type="answer_generated",
            stage="extracting",
            status=SessionStatus.EXTRACTING,
            message="Synthesized deterministic evidence-backed answer.",
            db_path=db_path,
        )
    except Exception as e:
        logger.exception("Evidence extraction failed: %s", e)
        return _handle_error(session, f"Extraction error: {e}", db_path)

    final_result = det_result

    # Stage 5: Optional AI Polishing
    if session.cancelled:
        return _handle_cancellation(session, db_path)

    should_polish = getattr(req, "polish", False) or config.AI_POLISH_ENABLED
    if should_polish:
        broadcast_event(
            session,
            event_type="polishing_started",
            stage="polishing",
            status=SessionStatus.POLISHING,
            message="Improving prose readability with evidence-constrained polisher...",
            db_path=db_path,
        )

        try:
            polisher = AnswerPolisher(enable_ai=True)
            polished = await polisher.polish_result(det_result, requested=True)
            final_result = polished

            status_msg = (
                f"AI polishing: {final_result.polish_status} ({final_result.polish_reason})"
                if final_result.polish_reason
                else ("AI polishing completed successfully." if final_result.ai_polished else "Polishing skipped or reverted to deterministic fallback.")
            )
            broadcast_event(
                session,
                event_type="polishing_completed",
                stage="polishing",
                status=SessionStatus.POLISHING,
                message=status_msg,
                db_path=db_path,
            )
        except Exception as e:
            logger.warning("Optional AI polisher failed: %s; keeping deterministic.", e)
            final_result = det_result
            final_result.polish_status = "unavailable"
            final_result.polish_reason = "AI polisher encountered an unhandled error."
    else:
        final_result = det_result
        final_result.polish_status = "disabled"
        final_result.polish_reason = "Readability polish was not requested."

    # Stage 6: Completion & Persistence
    if session.cancelled:
        return _handle_cancellation(session, db_path)

    session.result = final_result
    session.status = SessionStatus.DONE

    # Persist final result to SQLite
    try:
        with database.get_db(db_path) as conn:
            database.save_session_result(conn, session_id, final_result.model_dump_json())
    except Exception as e:
        logger.warning("Failed saving result JSON to DB: %s", e)

    broadcast_event(
        session,
        event_type="pipeline_completed",
        stage="completed",
        status=SessionStatus.DONE,
        message="Search pipeline completed successfully.",
        db_path=db_path,
    )

    return final_result


def _handle_cancellation(session: PipelineSession, db_path: Path | str) -> SearchResult:
    """Handle session cancellation gracefully."""
    session.status = SessionStatus.CANCELLED
    session.cancelled = True

    # Broadcast session_cancelled only if not already emitted
    if not any(e.event_type == "session_cancelled" for e in session.events):
        broadcast_event(
            session,
            event_type="session_cancelled",
            stage="cancelled",
            status=SessionStatus.CANCELLED,
            message="Search session was cancelled by user.",
            db_path=db_path,
        )
    empty_res = SearchResult(
        answer="Search session was cancelled.",
        pages_crawled=session.pages_crawled,
        pages_failed=session.pages_failed,
        ai_polished=False,
    )
    session.result = empty_res
    return empty_res


def _handle_error(session: PipelineSession, error_msg: str, db_path: Path | str) -> SearchResult:
    """Handle pipeline errors cleanly without unhandled exceptions."""
    session.status = SessionStatus.ERROR
    session.error = error_msg
    try:
        with database.get_db(db_path) as conn:
            database.save_session_error(conn, session.session_id, error_msg)
    except Exception:
        pass

    if not any(e.event_type == "pipeline_error" for e in session.events):
        broadcast_event(
            session,
            event_type="pipeline_error",
            stage="error",
            status=SessionStatus.ERROR,
            message=error_msg,
            db_path=db_path,
        )
    err_res = SearchResult(
        answer=f"Error: {error_msg}",
        pages_crawled=session.pages_crawled,
        pages_failed=session.pages_failed,
        ai_polished=False,
    )
    session.result = err_res
    return err_res


def cancel_pipeline_session(session_id: str) -> bool:
    """Cancel an active or pending pipeline session."""
    session = get_pipeline_session(session_id)
    if not session:
        return False

    # If session is already terminal, ignore cancellation
    if session.status in (SessionStatus.DONE, SessionStatus.ERROR, SessionStatus.CANCELLED):
        return False
    if any(e.event_type in TERMINAL_EVENTS for e in session.events):
        return False

    session.cancelled = True
    session.status = SessionStatus.CANCELLED
    if session.crawler:
        session.crawler.cancel()

    # Ensure session_started is always emitted first
    if not any(e.event_type == "session_started" for e in session.events):
        broadcast_event(
            session,
            event_type="session_started",
            stage="initialization",
            status=SessionStatus.PENDING,
            message=f"Session initialized for {session.request.url}",
        )

    # Ensure session_cancelled is emitted exactly once
    if not any(e.event_type == "session_cancelled" for e in session.events):
        broadcast_event(
            session,
            event_type="session_cancelled",
            stage="cancelled",
            status=SessionStatus.CANCELLED,
            message="Cancellation requested.",
        )
    return True
