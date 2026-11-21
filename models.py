"""
SiteSage — Pydantic data structures.

Every data object exchanged between modules is defined here so that
contracts are explicit and validated at the boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, HttpUrl


# ── Enums ────────────────────────────────────────────────────────────

class SessionStatus(str, Enum):
    PENDING = "pending"
    CRAWLING = "crawling"
    INDEXING = "indexing"
    RANKING = "ranking"
    EXTRACTING = "extracting"
    POLISHING = "polishing"
    DONE = "done"
    CANCELLED = "cancelled"
    ERROR = "error"


# ── Request / Response ───────────────────────────────────────────────

class CrawlRequest(BaseModel):
    """Incoming search request from the user."""
    url: str = Field(..., description="Seed URL to crawl")
    question: str = Field(..., min_length=3, description="User's question")
    max_pages: int = Field(default=30, ge=1, description="Page cap (hard max 30)")
    polish: bool = Field(default=False, description="Enable optional AI polishing of extracted answer")

    @field_validator("max_pages")
    @classmethod
    def clamp_max_pages(cls, v: int) -> int:
        return min(v, 30)


class StartSearchResponse(BaseModel):
    session_id: str


class CancelResponse(BaseModel):
    session_id: str
    cancelled: bool


# ── Crawl progress (SSE payload) ────────────────────────────────────

class CrawlProgress(BaseModel):
    """Real-time progress event pushed over SSE."""
    session_id: str
    status: SessionStatus
    event_id: int = 0
    event_type: str = "progress"
    stage: str = "crawling"
    pages_discovered: int = 0
    pages_queued: int = 0
    pages_crawled: int = 0
    pages_failed: int = 0
    max_pages: int = 30
    current_url: Optional[str] = None
    message: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Crawled page ─────────────────────────────────────────────────────

class HeadingInfo(BaseModel):
    """A single heading extracted from a page."""
    level: int = Field(..., ge=1, le=6)
    text: str
    position: int = Field(..., ge=0, description="Character offset in cleaned text")


class CrawledPage(BaseModel):
    """Result of fetching and parsing a single page."""
    url: str
    title: str = ""
    text: str = ""
    headings: list[HeadingInfo] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    crawl_depth: int = 0
    status_code: int = 0


# ── Indexing ─────────────────────────────────────────────────────────

class Passage(BaseModel):
    """A single searchable text passage with structural metadata."""
    id: int = 0
    page_url: str = ""
    page_title: str = ""
    text: str = ""
    position: int = 0
    section_heading: Optional[str] = None
    heading_level: Optional[int] = None
    token_count: int = 0


# ── Ranking / scoring ───────────────────────────────────────────────

class ScoreBreakdown(BaseModel):
    """Transparent, explainable score decomposition."""
    bm25_score: float = 0.0
    title_boost: float = 0.0
    heading_boost: float = 0.0
    position_boost: float = 0.0
    depth_penalty: float = 0.0
    total_score: float = 0.0
    explanation: str = ""


class ScoredPassage(BaseModel):
    """A passage with its ranking score and explanation."""
    passage: Passage
    score_breakdown: ScoreBreakdown


# ── Question decomposition ──────────────────────────────────────────

class QuestionAspect(BaseModel):
    """One sub-aspect of a multi-faceted question."""
    aspect: str
    keywords: list[str] = Field(default_factory=list)


# ── Evidence & claims ────────────────────────────────────────────────

class SourceReference(BaseModel):
    """A direct reference to an exact passage and source URL."""
    page_url: str
    page_title: str = ""
    passage_id: int = 0
    section_heading: Optional[str] = None
    exact_quote: str = ""


class ClaimEvidence(BaseModel):
    """A single claim extracted from evidence with source references."""
    claim: str
    supporting_passages: list[ScoredPassage] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Evidence-based confidence")
    aspect: Optional[str] = None
    conflict_detected: bool = False
    conflict_details: Optional[str] = None


class ConflictReport(BaseModel):
    """A detected contradiction between sources."""
    aspect: str
    conflicting_statements: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    explanation: str = ""


# ── Final search result ──────────────────────────────────────────────

class SearchResult(BaseModel):
    """Complete answer returned to the user."""
    answer: str = ""
    claims: list[ClaimEvidence] = Field(default_factory=list)
    evidence: list[ScoredPassage] = Field(default_factory=list)
    alternative_sources: list[ScoredPassage] = Field(default_factory=list)
    question_aspects: list[QuestionAspect] = Field(default_factory=list)
    missing_aspects: list[str] = Field(default_factory=list)
    conflicts: list[ConflictReport] = Field(default_factory=list)
    pages_crawled: int = 0
    pages_failed: int = 0
    ai_polished: bool = False
