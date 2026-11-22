"""
SiteSage — FastAPI routes.

Phase 1: stub endpoints that validate inputs and return shaped responses.
Real crawl/search orchestration will be wired in Phase 2+.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from pydantic import BaseModel, Field

import database
from extractor import EvidenceExtractor, decompose_question
from indexer import SiteIndexer
from models import (
    CancelResponse,
    CrawlRequest,
    QuestionAspect,
    ScoredPassage,
    SearchResult,
    SessionStatus,
    StartSearchResponse,
)
from pipeline import (
    create_pipeline_session,
    execute_pipeline,
    get_pipeline_session,
    cancel_pipeline_session,
    subscribe_session_events,
)
from polisher import AnswerPolisher
from ranker import BM25Ranker

router = APIRouter(prefix="/api", tags=["search"])
logger = logging.getLogger(__name__)

# In-memory session registry (preserved for backwards-compatibility)
_sessions: dict[str, dict] = {}


class QuestionAnalysisRequest(BaseModel):
    question: str = Field(..., min_length=1)


class QuestionAnalysisResponse(BaseModel):
    question: str
    aspects: list[QuestionAspect]


@router.get("/health")
async def health_check() -> dict:
    """Service health check endpoint."""
    return {"status": "healthy", "service": "sitesage", "version": "0.1.0"}


@router.post("/search", response_model=StartSearchResponse)
async def start_search(req: CrawlRequest) -> StartSearchResponse:
    """Accept a search request, initialize session, and launch async pipeline."""
    session_id = uuid.uuid4().hex[:12]

    # Initialize in-memory compatibility map
    _sessions[session_id] = {
        "request": req,
        "status": SessionStatus.PENDING,
    }

    # Create pipeline session and spawn background execution task
    pipeline_sess = create_pipeline_session(req, session_id)
    pipeline_sess.task = asyncio.create_task(execute_pipeline(pipeline_sess))

    return StartSearchResponse(session_id=session_id)


@router.get("/search/{session_id}/stream")
async def stream_session_events(
    session_id: str,
    last_event_id: Optional[int] = Header(default=None, alias="Last-Event-ID"),
):
    """Server-Sent Events (SSE) stream providing real-time pipeline progress updates."""
    # Check if session exists in memory or DB
    sess = get_pipeline_session(session_id)
    if not sess:
        with database.get_db() as conn:
            if not database.get_session(conn, session_id):
                raise HTTPException(status_code=404, detail="Session not found")

    return StreamingResponse(
        subscribe_session_events(session_id, last_event_id=last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/progress/{session_id}")
async def get_progress(
    session_id: str,
    request: Request,
    last_event_id: Optional[int] = Header(default=None, alias="Last-Event-ID"),
):
    """Compatibility progress endpoint.

    If requested with Accept: text/event-stream, streams SSE.
    Otherwise returns current progress JSON.
    """
    if session_id not in _sessions and not get_pipeline_session(session_id):
        with database.get_db() as conn:
            if not database.get_session(conn, session_id):
                raise HTTPException(status_code=404, detail="Session not found")

    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept.lower():
        return StreamingResponse(
            subscribe_session_events(session_id, last_event_id=last_event_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    sess = get_pipeline_session(session_id)
    status_str = sess.status.value if sess else (_sessions.get(session_id, {}).get("status", "pending"))
    return JSONResponse({
        "session_id": session_id,
        "status": status_str,
        "stage": sess.stage if sess else "pending",
        "pages_discovered": sess.pages_discovered if sess else 0,
        "pages_crawled": sess.pages_crawled if sess else 0,
        "pages_failed": sess.pages_failed if sess else 0,
        "current_url": sess.current_url if sess else None,
        "message": sess.events[-1].message if (sess and sess.events) else "Session active",
    })


@router.get("/search/{session_id}/status")
async def get_search_status(session_id: str) -> dict:
    """Return structured status details for an active or completed search session."""
    sess = get_pipeline_session(session_id)
    if sess:
        return {
            "session_id": session_id,
            "status": sess.status.value,
            "stage": sess.stage,
            "pages_discovered": sess.pages_discovered,
            "pages_queued": sess.pages_queued,
            "pages_crawled": sess.pages_crawled,
            "pages_failed": sess.pages_failed,
            "max_pages": sess.max_pages,
            "current_url": sess.current_url,
            "message": sess.events[-1].message if sess.events else "",
        }

    with database.get_db() as conn:
        row = database.get_session(conn, session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session_id,
        "status": row["status"],
        "stage": "completed" if row["status"] == "done" else row["status"],
        "pages_discovered": row["pages_discovered"] or 0,
        "pages_queued": row["pages_queued"] or 0,
        "pages_crawled": row["pages_crawled"] or 0,
        "pages_failed": row["pages_failed"] or 0,
        "max_pages": 30,
        "current_url": None,
        "message": f"Session status: {row['status']}",
    }


@router.post("/search/{session_id}/cancel", response_model=CancelResponse)
@router.post("/cancel/{session_id}", response_model=CancelResponse)
async def cancel_search(session_id: str) -> CancelResponse:
    """Cancel an in-progress search pipeline."""
    if session_id not in _sessions and not get_pipeline_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    cancel_pipeline_session(session_id)
    if session_id in _sessions:
        _sessions[session_id]["status"] = SessionStatus.CANCELLED

    return CancelResponse(session_id=session_id, cancelled=True)


@router.get("/search/{session_id}/results", response_model=SearchResult)
@router.get("/results/{session_id}", response_model=SearchResult)
async def get_results(
    session_id: str,
    polish: bool = Query(default=False, description="Request optional AI polish if enabled"),
) -> SearchResult:
    """Return the final answer once processing completes.

    Checks active pipeline result first, then SQLite cached result,
    falling back to deterministic extraction or initial stub.
    """
    # 1. Check in-memory pipeline result
    sess = get_pipeline_session(session_id)
    if sess and sess.result:
        if polish and not sess.result.ai_polished:
            polisher = AnswerPolisher(enable_ai=True)
            return await polisher.polish_result(sess.result, requested=True)
        return sess.result

    if session_id not in _sessions and not sess:
        with database.get_db() as conn:
            if not database.get_session(conn, session_id):
                raise HTTPException(status_code=404, detail="Session not found")

    # 2. Check SQLite persisted result
    try:
        with database.get_db() as conn:
            row = database.get_session(conn, session_id)
            if row and "result_json" in row.keys() and row["result_json"]:
                import json
                data = json.loads(row["result_json"])
                return SearchResult(**data)

            # Fallback to direct extraction if passages exist in DB
            stats = database.get_corpus_stats(conn, session_id)
            if stats and stats["total_passages"] > 0:
                q = (
                    sess.request.question if sess
                    else (_sessions.get(session_id, {}).get("request").question if session_id in _sessions
                    else (row["question"] if row and "question" in row.keys() else ""))
                )
                extractor = EvidenceExtractor()
                det_result = extractor.process_question(session_id, q)
                if polish:
                    polisher = AnswerPolisher(enable_ai=True)
                    return await polisher.polish_result(det_result, requested=True)
                det_result.polish_status = "disabled"
                det_result.polish_reason = "Readability polish was not requested."
                return det_result
    except Exception as e:
        logger.debug("Failed loading result from DB: %s", e)

    return SearchResult(
        answer="Search pipeline not yet implemented.",
        pages_crawled=0,
        pages_failed=0,
        ai_polished=False,
        polish_status="disabled" if not polish else "unavailable",
        polish_reason="Readability polish was not requested." if not polish else "AI polisher unavailable.",
    )


@router.get("/sessions")
async def list_recent_sessions(limit: int = Query(default=20, ge=1, le=100)) -> list[dict]:
    """List recent search sessions recorded in the database."""
    with database.get_db() as conn:
        rows = database.list_sessions(conn, limit=limit)
    return [
        {
            "session_id": r["session_id"],
            "seed_url": r["seed_url"],
            "question": r["question"],
            "status": r["status"],
            "pages_crawled": r["pages_crawled"] or 0,
            "created_at": r["created_at"],
            "completed_at": r["completed_at"],
        }
        for r in rows
    ]


@router.post("/index/{session_id}")
async def index_session(session_id: str) -> dict:
    """Trigger indexing of all crawled pages for a given session."""
    indexer = SiteIndexer()
    passages = indexer.index_from_database(session_id)
    if session_id in _sessions:
        _sessions[session_id]["status"] = SessionStatus.INDEXING
    return {
        "session_id": session_id,
        "passages_indexed": len(passages),
        "status": "indexed",
    }


@router.get("/search_passages/{session_id}", response_model=list[ScoredPassage])
async def search_passages(
    session_id: str,
    q: str = Query(..., min_length=1, description="Search query string"),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[ScoredPassage]:
    """Retrieve ranked passages for a query using the BM25 index."""
    ranker = BM25Ranker()
    scored = ranker.rank_passages(session_id, q, top_k=limit)
    return scored


@router.post("/analyze_question", response_model=QuestionAnalysisResponse)
async def analyze_question(req: QuestionAnalysisRequest) -> QuestionAnalysisResponse:
    """Analyze and decompose a question into distinct searchable aspects."""
    aspects = decompose_question(req.question)
    return QuestionAnalysisResponse(question=req.question, aspects=aspects)


@router.post("/extract_evidence/{session_id}", response_model=SearchResult)
async def extract_evidence(
    session_id: str,
    question: Optional[str] = Query(default=None),
) -> SearchResult:
    """Run deterministic evidence extraction and claim assembly for a session."""
    if session_id not in _sessions and not get_pipeline_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    q = (
        question
        or (get_pipeline_session(session_id).request.question if get_pipeline_session(session_id) else None)
        or (_sessions[session_id]["request"].question if session_id in _sessions else None)
    )
    if not q:
        raise HTTPException(status_code=400, detail="Question required")

    extractor = EvidenceExtractor()
    return extractor.process_question(session_id, q)


@router.post("/polish/{session_id}", response_model=SearchResult)
async def polish_answer(session_id: str) -> SearchResult:
    """Explicitly trigger optional AI polishing for an already extracted session result."""
    if session_id not in _sessions and not get_pipeline_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    with database.get_db() as conn:
        stats = database.get_corpus_stats(conn, session_id)
        if not stats or stats["total_passages"] == 0:
            raise HTTPException(status_code=400, detail="No indexed data available for session")

    q = (
        (get_pipeline_session(session_id).request.question if get_pipeline_session(session_id) else None)
        or (_sessions[session_id]["request"].question if session_id in _sessions else None)
    )
    extractor = EvidenceExtractor()
    det_result = extractor.process_question(session_id, q)
    polisher = AnswerPolisher()
    return await polisher.polish_result(det_result)
