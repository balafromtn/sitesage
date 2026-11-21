"""Tests for API endpoints — validation, session lifecycle, error handling."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


class TestSearchEndpoint:
    def test_valid_search(self):
        resp = client.post("/api/search", json={
            "url": "https://example.com",
            "question": "What is this site about?",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert len(data["session_id"]) == 12

    def test_missing_question(self):
        resp = client.post("/api/search", json={"url": "https://example.com"})
        assert resp.status_code == 422

    def test_short_question_rejected(self):
        resp = client.post("/api/search", json={
            "url": "https://example.com",
            "question": "ab",
        })
        assert resp.status_code == 422

    def test_max_pages_clamped(self):
        resp = client.post("/api/search", json={
            "url": "https://example.com",
            "question": "Hello world?",
            "max_pages": 999,
        })
        assert resp.status_code == 200


class TestProgressEndpoint:
    def test_missing_session_404(self):
        resp = client.get("/api/progress/nonexistent")
        assert resp.status_code == 404

    def test_valid_session(self):
        create = client.post("/api/search", json={
            "url": "https://example.com",
            "question": "What is here?",
        })
        sid = create.json()["session_id"]
        resp = client.get(f"/api/progress/{sid}")
        assert resp.status_code == 200


class TestResultsEndpoint:
    def test_missing_session_404(self):
        resp = client.get("/api/results/nonexistent")
        assert resp.status_code == 404

    def test_valid_session_returns_stub(self):
        create = client.post("/api/search", json={
            "url": "https://example.com",
            "question": "Tell me about this",
        })
        sid = create.json()["session_id"]
        resp = client.get(f"/api/results/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert data["ai_polished"] is False


class TestCancelEndpoint:
    def test_missing_session_404(self):
        resp = client.post("/api/cancel/nonexistent")
        assert resp.status_code == 404

    def test_cancel_valid_session(self):
        create = client.post("/api/search", json={
            "url": "https://example.com",
            "question": "What is this?",
        })
        sid = create.json()["session_id"]
        resp = client.post(f"/api/cancel/{sid}")
        assert resp.status_code == 200
        assert resp.json()["cancelled"] is True


class TestIndexingAndSearchEndpoints:
    def test_index_and_search_flow(self):
        # 1. Create search session
        create = client.post("/api/search", json={
            "url": "https://example.com",
            "question": "What is Python?",
        })
        sid = create.json()["session_id"]

        # 2. Insert dummy page in DB for this session
        import database
        with database.get_db() as conn:
            pid = database.insert_page(
                conn, sid, "https://example.com/page1", "Python Guide",
                "Python is a versatile programming language known for readability.", 0, 200
            )
            database.insert_heading(conn, pid, 1, "Python Overview", 0)

        # 3. Trigger index endpoint
        idx_resp = client.post(f"/api/index/{sid}")
        assert idx_resp.status_code == 200
        assert idx_resp.json()["passages_indexed"] >= 1

        # 4. Search passages endpoint
        search_resp = client.get(f"/api/search_passages/{sid}?q=versatile+programming")
        assert search_resp.status_code == 200
        results = search_resp.json()
        assert len(results) >= 1
        assert "score_breakdown" in results[0]
        assert results[0]["passage"]["page_url"] == "https://example.com/page1"


class TestStaticFrontendServing:
    def test_root_serves_html(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "SiteSage" in resp.text
        assert 'id="search-form"' in resp.text
        assert 'id="dashboard-section"' in resp.text
        assert 'id="results-section"' in resp.text

    def test_static_assets_serve_correctly(self):
        for path in ["/style.css", "/js/api.js", "/js/stream.js", "/js/ui.js", "/js/app.js"]:
            resp = client.get(path)
            assert resp.status_code == 200, f"Failed serving {path}"
            assert len(resp.text) > 50
