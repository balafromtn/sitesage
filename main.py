"""
SiteSage — Application entry point.

Run with:  python main.py
Or:        uvicorn main:app --reload
"""

from contextlib import asynccontextmanager

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
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
