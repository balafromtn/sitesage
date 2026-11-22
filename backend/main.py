"""
SiteSage — Application entry point.

Run with:  python main.py
Or:        uvicorn main:app --reload
"""

import sys
from pathlib import Path
from contextlib import asynccontextmanager

# Ensure backend and root directories are in sys.path
_BACKEND_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _BACKEND_DIR.parent
for _p in (str(_BACKEND_DIR), str(_ROOT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import config
from api import router as api_router
from database import init_db

# ── Lifespan ─────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the database on startup."""
    init_db()
    yield


app = FastAPI(
    title="SiteSage",
    description="Question-aware website search engine",
    version="0.1.0",
    lifespan=lifespan,
)

# ── Routes & static files ───────────────────────────────────────────

app.include_router(api_router)


@app.get("/health")
async def health_check():
    """Top-level health check."""
    return {"status": "healthy", "service": "sitesage", "version": "0.1.0"}


app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="static")


# ── CLI entry point ──────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=config.HOST, port=config.PORT, reload=True)
