"""
SiteSage — SQLite database schema and helpers.

Provides synchronous helpers around a single-file SQLite database.
All writes go through this module so schema changes are centralised.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

from config import DB_PATH

# ── Schema ───────────────────────────────────────────────────────────

SCHEMA_SQL = """
-- Sessions (one per search request)
CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    seed_url        TEXT NOT NULL,
    question        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    pages_discovered INTEGER DEFAULT 0,
    pages_queued    INTEGER DEFAULT 0,
    pages_crawled   INTEGER DEFAULT 0,
    pages_failed    INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL,
    completed_at    TEXT,
    result_json     TEXT,
    error_message   TEXT
);

-- Crawled pages
CREATE TABLE IF NOT EXISTS pages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(session_id),
    url             TEXT NOT NULL,
    title           TEXT DEFAULT '',
    text            TEXT DEFAULT '',
    depth           INTEGER DEFAULT 0,
    status_code     INTEGER DEFAULT 0,
    crawled_at      TEXT NOT NULL,
    UNIQUE(session_id, url)
);

-- Structural headings per page
CREATE TABLE IF NOT EXISTS headings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id         INTEGER NOT NULL REFERENCES pages(id),
    level           INTEGER NOT NULL,
    text            TEXT NOT NULL,
    position        INTEGER NOT NULL
);

-- Passages (sentences / paragraphs)
CREATE TABLE IF NOT EXISTS passages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(session_id),
    page_id         INTEGER NOT NULL REFERENCES pages(id),
    text            TEXT NOT NULL,
    position        INTEGER NOT NULL,
    section_heading TEXT,
    heading_level   INTEGER,
    token_count     INTEGER DEFAULT 0
);

-- Inverted index: term → passage, per field
CREATE TABLE IF NOT EXISTS term_index (
    term            TEXT NOT NULL,
    passage_id      INTEGER NOT NULL REFERENCES passages(id),
    frequency       INTEGER NOT NULL DEFAULT 1,
    field           TEXT NOT NULL DEFAULT 'body',
    PRIMARY KEY (term, passage_id, field)
);

-- Corpus-level stats for BM25 computation
CREATE TABLE IF NOT EXISTS corpus_stats (
    session_id      TEXT PRIMARY KEY REFERENCES sessions(session_id),
    total_passages  INTEGER NOT NULL DEFAULT 0,
    avg_length      REAL NOT NULL DEFAULT 0.0
);

-- Indices for fast lookups
CREATE INDEX IF NOT EXISTS idx_pages_session ON pages(session_id);
CREATE INDEX IF NOT EXISTS idx_passages_session ON passages(session_id);
CREATE INDEX IF NOT EXISTS idx_passages_page ON passages(page_id);
CREATE INDEX IF NOT EXISTS idx_term_index_term ON term_index(term);
CREATE INDEX IF NOT EXISTS idx_headings_page ON headings(page_id);
"""


# ── Connection helpers ───────────────────────────────────────────────

def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Return a new SQLite connection with recommended pragmas."""
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def get_db(db_path: Path | str = DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    """Context manager that yields a connection and commits on clean exit."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str = DB_PATH) -> None:
    """Create all tables and indices if they don't exist, and migrate columns."""
    with get_db(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        # Migrate existing tables if columns are missing
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()]
        if "result_json" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN result_json TEXT")
        if "error_message" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN error_message TEXT")


# ── Session CRUD ─────────────────────────────────────────────────────

def create_session(
    conn: sqlite3.Connection,
    session_id: str,
    seed_url: str,
    question: str,
) -> None:
    conn.execute(
        "INSERT INTO sessions (session_id, seed_url, question, status, created_at) "
        "VALUES (?, ?, ?, 'pending', ?)",
        (session_id, seed_url, question, _now_iso()),
    )


def update_session_status(
    conn: sqlite3.Connection,
    session_id: str,
    status: str,
    *,
    pages_discovered: Optional[int] = None,
    pages_queued: Optional[int] = None,
    pages_crawled: Optional[int] = None,
    pages_failed: Optional[int] = None,
) -> None:
    parts = ["status = ?"]
    params: list = [status]

    for col, val in [
        ("pages_discovered", pages_discovered),
        ("pages_queued", pages_queued),
        ("pages_crawled", pages_crawled),
        ("pages_failed", pages_failed),
    ]:
        if val is not None:
            parts.append(f"{col} = ?")
            params.append(val)

    if status in ("done", "error", "cancelled"):
        parts.append("completed_at = ?")
        params.append(_now_iso())

    params.append(session_id)
    conn.execute(
        f"UPDATE sessions SET {', '.join(parts)} WHERE session_id = ?",
        params,
    )


def get_session(conn: sqlite3.Connection, session_id: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()


def list_sessions(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    """List recent sessions ordered by creation time descending."""
    return conn.execute(
        "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()


def save_session_result(
    conn: sqlite3.Connection,
    session_id: str,
    result_json: str,
    status: str = "done",
) -> None:
    """Save the final SearchResult JSON to the session record."""
    conn.execute(
        "UPDATE sessions SET result_json = ?, status = ?, completed_at = ? WHERE session_id = ?",
        (result_json, status, _now_iso(), session_id),
    )


def save_session_error(
    conn: sqlite3.Connection,
    session_id: str,
    error_message: str,
) -> None:
    """Save an error message and set status to error."""
    conn.execute(
        "UPDATE sessions SET error_message = ?, status = 'error', completed_at = ? WHERE session_id = ?",
        (error_message, _now_iso(), session_id),
    )


# ── Page CRUD ────────────────────────────────────────────────────────

def insert_page(
    conn: sqlite3.Connection,
    session_id: str,
    url: str,
    title: str,
    text: str,
    depth: int,
    status_code: int,
) -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO pages (session_id, url, title, text, depth, status_code, crawled_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, url, title, text, depth, status_code, _now_iso()),
    )
    return cur.lastrowid or 0


def insert_heading(
    conn: sqlite3.Connection,
    page_id: int,
    level: int,
    text: str,
    position: int,
) -> None:
    conn.execute(
        "INSERT INTO headings (page_id, level, text, position) VALUES (?, ?, ?, ?)",
        (page_id, level, text, position),
    )


# ── Passage CRUD ─────────────────────────────────────────────────────

def insert_passage(
    conn: sqlite3.Connection,
    session_id: str,
    page_id: int,
    text: str,
    position: int,
    section_heading: Optional[str],
    heading_level: Optional[int],
    token_count: int,
) -> int:
    cur = conn.execute(
        "INSERT INTO passages "
        "(session_id, page_id, text, position, section_heading, heading_level, token_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, page_id, text, position, section_heading, heading_level, token_count),
    )
    return cur.lastrowid or 0


# ── Term index CRUD ──────────────────────────────────────────────────

def insert_term(
    conn: sqlite3.Connection,
    term: str,
    passage_id: int,
    frequency: int,
    field: str = "body",
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO term_index (term, passage_id, frequency, field) "
        "VALUES (?, ?, ?, ?)",
        (term, passage_id, frequency, field),
    )


def update_corpus_stats(
    conn: sqlite3.Connection,
    session_id: str,
    total_passages: int,
    avg_length: float,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO corpus_stats (session_id, total_passages, avg_length) "
        "VALUES (?, ?, ?)",
        (session_id, total_passages, avg_length),
    )


def clear_session_index(conn: sqlite3.Connection, session_id: str) -> None:
    """Clear all passages and inverted index entries for a session to allow clean re-indexing."""
    conn.execute(
        "DELETE FROM term_index WHERE passage_id IN (SELECT id FROM passages WHERE session_id = ?)",
        (session_id,),
    )
    conn.execute("DELETE FROM passages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM corpus_stats WHERE session_id = ?", (session_id,))


def get_pages_by_session(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    """Retrieve all crawled pages for a given session."""
    return conn.execute(
        "SELECT * FROM pages WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()


def get_headings_by_page(conn: sqlite3.Connection, page_id: int) -> list[sqlite3.Row]:
    """Retrieve all headings for a given page."""
    return conn.execute(
        "SELECT * FROM headings WHERE page_id = ? ORDER BY position ASC",
        (page_id,),
    ).fetchall()


def get_passages_by_session(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    """Retrieve all passages for a session joined with page info."""
    return conn.execute(
        """
        SELECT p.*, pg.url AS page_url, pg.title AS page_title, pg.depth AS page_depth
        FROM passages p
        JOIN pages pg ON p.page_id = pg.id
        WHERE p.session_id = ?
        ORDER BY p.id ASC
        """,
        (session_id,),
    ).fetchall()


def get_corpus_stats(conn: sqlite3.Connection, session_id: str) -> Optional[sqlite3.Row]:
    """Retrieve corpus-level stats for BM25 calculation."""
    return conn.execute(
        "SELECT * FROM corpus_stats WHERE session_id = ?",
        (session_id,),
    ).fetchone()


def get_term_postings(
    conn: sqlite3.Connection, session_id: str, term: str
) -> list[sqlite3.Row]:
    """Retrieve postings for a term in a given session."""
    return conn.execute(
        """
        SELECT ti.passage_id, ti.frequency, ti.field, p.token_count,
               p.position, p.section_heading, p.heading_level, p.text,
               pg.url AS page_url, pg.title AS page_title, pg.depth AS page_depth
        FROM term_index ti
        JOIN passages p ON ti.passage_id = p.id
        JOIN pages pg ON p.page_id = pg.id
        WHERE ti.term = ? AND p.session_id = ?
        """,
        (term, session_id),
    ).fetchall()


# ── Utilities ────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
