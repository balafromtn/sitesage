"""
SiteSage — Central configuration.

All tuneable constants live here. Modules import from config rather
than hard-coding values, making the system easy to test and adjust.
"""

import os
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("SITESAGE_DB_PATH", str(BASE_DIR / "sitesage.db")))
STATIC_DIR = BASE_DIR / "static"

# ── Crawl limits ─────────────────────────────────────────────────────
MAX_PAGES: int = 30                  # hard cap on successfully crawled HTML pages
MAX_CRAWL_DEPTH: int = 5            # BFS depth from seed URL
CRAWL_TIMEOUT_PER_PAGE: float = 10.0  # seconds per HTTP request
CRAWL_TOTAL_TIMEOUT: float = 120.0    # overall crawl budget in seconds
MAX_CONCURRENT_REQUESTS: int = 3      # httpx concurrency semaphore
MAX_RESPONSE_BYTES: int = 5 * 1024 * 1024  # 5 MB per page
MAX_REDIRECTS: int = 5               # redirect-chain cap
CRAWL_DELAY: float = 0.25            # seconds between requests to same host
USER_AGENT: str = "SiteSage/0.1 (hackathon crawler)"

# Known tracking query parameters to strip during URL normalization
TRACKING_PARAMS: set[str] = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid",
    "ref", "referrer", "_ga", "_gl", "yclid",
}

# ── SSRF protection ──────────────────────────────────────────────────
# Block requests to private / loopback / link-local ranges.
BLOCKED_IP_PREFIXES: list[str] = [
    "127.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
    "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.",
    "192.168.", "0.", "169.254.", "::1", "fe80:", "fc00:", "fd00:",
]
BLOCKED_PORTS: set[int] = {22, 25, 445, 3306, 5432, 6379, 11211}

# ── Indexing ─────────────────────────────────────────────────────────
MIN_PAGE_TEXT_LENGTH: int = 50       # skip pages with less body text
MIN_PASSAGE_LENGTH: int = 20        # skip tiny passages
MAX_PASSAGE_LENGTH: int = 500       # split longer passages

# ── BM25 parameters ─────────────────────────────────────────────────
BM25_K1: float = 1.2
BM25_B: float = 0.75

# BM25 field-boost weights (additive, explainable)
BOOST_TITLE_MATCH: float = 2.0      # query terms appear in page title
BOOST_HEADING_MATCH: float = 1.5    # query terms appear in section heading
BOOST_POSITION: float = 0.5         # max boost for passage near top of page
BOOST_DEPTH_PENALTY: float = 0.3    # max penalty for deep pages

# ── Evidence & answers ───────────────────────────────────────────────
TOP_K_EVIDENCE: int = 5             # primary evidence passages
TOP_K_ALTERNATIVES: int = 5         # secondary matches shown
MIN_EVIDENCE_SCORE: float = 0.1     # ignore passages below this score
MAX_ASPECTS: int = 5                # max question sub-aspects

# ── AI polishing ─────────────────────────────────────────────────────
AI_POLISH_ENABLED: bool = os.getenv("AI_POLISH_ENABLED", "false").lower() in ("true", "1", "yes")
AI_POLISH_MODEL: str = os.getenv("AI_POLISH_MODEL", "gemini-1.5-flash")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# ── Server ───────────────────────────────────────────────────────────
HOST: str = os.getenv("HOST", "127.0.0.1")
PORT: int = int(os.getenv("PORT", "8000"))
