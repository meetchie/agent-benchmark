import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from server import app
import server as server_module

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_runs():
    server_module._runs.clear()
    yield
    server_module._runs.clear()


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_start_returns_run_id():
    # Mock run_benchmark so no actual agent runs during the test
    async def fake_run(state, url, goal):
        state.status = "complete"
        state.success = True
        state.summary = "Done"
        state.total_ms = 1000

    with patch("server.run_benchmark", side_effect=fake_run):
        resp = client.post(
            "/benchmark/start",
            json={"url": "https://example.com", "goal": "Test"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert isinstance(data["run_id"], str)


def test_status_not_found():
    resp = client.get("/benchmark/status/nonexistent-id")
    assert resp.status_code == 404


def test_start_missing_fields():
    resp = client.post("/benchmark/start", json={"url": "https://example.com"})
    assert resp.status_code == 422  # FastAPI validation error


def test_start_invalid_url():
    resp = client.post("/benchmark/start", json={"url": "not-a-url", "goal": "Test"})
    assert resp.status_code == 422


def test_status_running():
    """Status of a just-started run should be 'running' before background task completes."""
    import server as server_module
    from benchmark_runner import RunState

    run_id = "test-running-id"
    state = RunState(run_id=run_id, status="running")
    server_module._runs[run_id] = state

    resp = client.get(f"/benchmark/status/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"
