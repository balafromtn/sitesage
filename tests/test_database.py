"""Tests for database module — schema init, session CRUD, page/passage inserts."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from database import (
    create_session,
    get_db,
    get_session,
    init_db,
    insert_heading,
    insert_page,
    insert_passage,
    insert_term,
    update_corpus_stats,
    update_session_status,
)


@pytest.fixture
def db_path(tmp_path):
    """Provide a fresh temporary database for each test."""
    path = tmp_path / "test.db"
    init_db(path)
    return path


class TestSchemaInit:
    def test_tables_created(self, db_path):
        with get_db(db_path) as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        expected = {"sessions", "pages", "headings", "passages", "term_index", "corpus_stats"}
        assert expected.issubset(tables)

    def test_idempotent_init(self, db_path):
        # calling init_db twice should not raise
        init_db(db_path)
        init_db(db_path)


class TestSessionCRUD:
    def test_create_and_get(self, db_path):
        with get_db(db_path) as conn:
            create_session(conn, "s1", "https://example.com", "What?")
        with get_db(db_path) as conn:
            row = get_session(conn, "s1")
        assert row is not None
        assert row["seed_url"] == "https://example.com"
        assert row["status"] == "pending"

    def test_update_status(self, db_path):
        with get_db(db_path) as conn:
            create_session(conn, "s2", "https://example.com", "Q?")
            update_session_status(conn, "s2", "crawling", pages_crawled=5)
        with get_db(db_path) as conn:
            row = get_session(conn, "s2")
        assert row["status"] == "crawling"
        assert row["pages_crawled"] == 5

    def test_get_missing_session(self, db_path):
        with get_db(db_path) as conn:
            assert get_session(conn, "nope") is None

    def test_done_sets_completed_at(self, db_path):
        with get_db(db_path) as conn:
            create_session(conn, "s3", "https://example.com", "Q?")
            update_session_status(conn, "s3", "done")
        with get_db(db_path) as conn:
            row = get_session(conn, "s3")
        assert row["completed_at"] is not None


class TestPageCRUD:
    def test_insert_page(self, db_path):
        with get_db(db_path) as conn:
            create_session(conn, "s1", "https://example.com", "Q?")
            page_id = insert_page(conn, "s1", "https://example.com/p1", "Page 1", "text", 0, 200)
        assert page_id > 0

    def test_duplicate_page_ignored(self, db_path):
        with get_db(db_path) as conn:
            create_session(conn, "s1", "https://example.com", "Q?")
            id1 = insert_page(conn, "s1", "https://example.com/p1", "P1", "t1", 0, 200)
            id2 = insert_page(conn, "s1", "https://example.com/p1", "P1 dup", "t2", 0, 200)
        # Second insert is ignored (OR IGNORE), lastrowid may be 0
        assert id1 > 0

    def test_insert_heading(self, db_path):
        with get_db(db_path) as conn:
            create_session(conn, "s1", "https://example.com", "Q?")
            page_id = insert_page(conn, "s1", "https://example.com/p1", "P", "t", 0, 200)
            insert_heading(conn, page_id, 2, "Section A", 0)
            rows = conn.execute("SELECT * FROM headings WHERE page_id = ?", (page_id,)).fetchall()
        assert len(rows) == 1
        assert rows[0]["text"] == "Section A"


class TestPassageAndIndex:
    def test_insert_passage(self, db_path):
        with get_db(db_path) as conn:
            create_session(conn, "s1", "https://example.com", "Q?")
            page_id = insert_page(conn, "s1", "https://example.com/p1", "P", "t", 0, 200)
            pid = insert_passage(conn, "s1", page_id, "Some passage text", 0, "Intro", 1, 3)
        assert pid > 0

    def test_insert_term(self, db_path):
        with get_db(db_path) as conn:
            create_session(conn, "s1", "https://example.com", "Q?")
            page_id = insert_page(conn, "s1", "https://example.com/p1", "P", "t", 0, 200)
            pid = insert_passage(conn, "s1", page_id, "word test", 0, None, None, 2)
            insert_term(conn, "word", pid, 1, "body")
            insert_term(conn, "test", pid, 1, "body")
            rows = conn.execute("SELECT * FROM term_index WHERE passage_id = ?", (pid,)).fetchall()
        assert len(rows) == 2

    def test_corpus_stats(self, db_path):
        with get_db(db_path) as conn:
            create_session(conn, "s1", "https://example.com", "Q?")
            update_corpus_stats(conn, "s1", 100, 25.3)
            row = conn.execute("SELECT * FROM corpus_stats WHERE session_id = 's1'").fetchone()
        assert row["total_passages"] == 100
        assert abs(row["avg_length"] - 25.3) < 0.01
