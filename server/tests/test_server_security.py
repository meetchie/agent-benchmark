"""Security tests for the benchmark FastAPI server."""

import pytest
from fastapi.testclient import TestClient

from server import app, _runs


@pytest.fixture(autouse=True)
def clear_runs():
    """Clear run state between tests."""
    _runs.clear()
    yield
    _runs.clear()


client = TestClient(app)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
class TestCORS:
    def test_allows_localhost_origin(self):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_blocks_unknown_origin(self):
        resp = client.options(
            "/health",
            headers={
                "Origin": "https://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # FastAPI CORS middleware won't set allow-origin for disallowed origins
        assert resp.headers.get("access-control-allow-origin") != "https://evil.com"


# ---------------------------------------------------------------------------
# Input validation — /benchmark/start
# ---------------------------------------------------------------------------
class TestStartValidation:
    def test_rejects_missing_url(self):
        resp = client.post("/benchmark/start", json={"goal": "test"})
        assert resp.status_code == 422

    def test_rejects_missing_goal(self):
        resp = client.post("/benchmark/start", json={"url": "https://example.com"})
        assert resp.status_code == 422

    def test_rejects_non_http_url(self):
        resp = client.post(
            "/benchmark/start",
            json={"url": "ftp://example.com", "goal": "test"},
        )
        assert resp.status_code == 422

    def test_rejects_javascript_url(self):
        resp = client.post(
            "/benchmark/start",
            json={"url": "javascript:alert(1)", "goal": "test"},
        )
        assert resp.status_code == 422

    def test_rejects_goal_too_long(self):
        resp = client.post(
            "/benchmark/start",
            json={"url": "https://example.com", "goal": "x" * 5001},
        )
        assert resp.status_code == 422

    def test_accepts_goal_at_max_length(self):
        resp = client.post(
            "/benchmark/start",
            json={"url": "https://example.com", "goal": "x" * 5000},
        )
        assert resp.status_code == 200

    def test_accepts_valid_request(self):
        resp = client.post(
            "/benchmark/start",
            json={"url": "https://example.com", "goal": "Find cheapest bananas"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "run_id" in data


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------
class TestStatusEndpoint:
    def test_returns_404_for_unknown_run(self):
        resp = client.get("/benchmark/status/nonexistent-id")
        assert resp.status_code == 404

    def test_error_detail_does_not_leak_run_id(self):
        resp = client.get("/benchmark/status/secret-run-123")
        assert resp.status_code == 404
        assert "secret-run-123" not in resp.json().get("detail", "")


# ---------------------------------------------------------------------------
# Run eviction
# ---------------------------------------------------------------------------
class TestRunEviction:
    def test_evicts_old_runs_when_over_capacity(self):
        # Create 105 runs
        for i in range(105):
            resp = client.post(
                "/benchmark/start",
                json={"url": "https://example.com", "goal": f"goal {i}"},
            )
            assert resp.status_code == 200

        # Should have at most 100 runs
        assert len(_runs) <= 100
