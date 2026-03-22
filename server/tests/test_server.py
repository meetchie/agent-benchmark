import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from server import app, get_current_user
import server as server_module

client = TestClient(app)

FAKE_USER = {"user_id": "test-user-id"}


@pytest.fixture(autouse=True)
def clear_runs():
    server_module._runs.clear()
    app.dependency_overrides.pop(get_current_user, None)
    yield
    server_module._runs.clear()
    app.dependency_overrides.pop(get_current_user, None)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_start_returns_run_id():
    """Authenticated start returns a run_id."""
    async def fake_run(state, url, goal):
        state.status = "complete"
        state.success = True
        state.summary = "Done"
        state.total_ms = 1000

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
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
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    resp = client.post("/benchmark/start", json={"url": "https://example.com"})
    assert resp.status_code == 422  # FastAPI validation error


def test_start_invalid_url():
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    resp = client.post("/benchmark/start", json={"url": "not-a-url", "goal": "Test"})
    assert resp.status_code == 422


def test_status_running():
    """Status of a just-started run should be 'running' before background task completes."""
    from benchmark_runner import RunState

    run_id = "test-running-id"
    state = RunState(run_id=run_id, status="running")
    server_module._runs[run_id] = state

    resp = client.get(f"/benchmark/status/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_generate_tasks_success():
    fake_tasks = [
        {"id": "task_1", "label": "Test task", "goal": "Do something."},
        {"id": "task_2", "label": "Test task 2", "goal": "Do something else."},
        {"id": "task_3", "label": "Test task 3", "goal": "Do another thing."},
    ]
    with patch("server.fetch_and_generate", new_callable=AsyncMock, return_value=fake_tasks):
        resp = client.post("/benchmark/generate-tasks", json={"url": "https://www.dominos.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tasks"]) == 3
    assert data["tasks"][0]["id"] == "task_1"


def test_generate_tasks_invalid_url():
    resp = client.post("/benchmark/generate-tasks", json={"url": "not-a-url"})
    assert resp.status_code == 422


def test_generate_tasks_site_unreachable():
    with patch("server.fetch_and_generate", new_callable=AsyncMock, side_effect=ConnectionError("timeout")):
        resp = client.post("/benchmark/generate-tasks", json={"url": "https://unreachable-site.com"})
    assert resp.status_code == 502
    assert "detail" in resp.json()


# --- Clerk auth tests ---

def test_benchmark_start_no_token():
    """Requests without a Bearer token should get 401."""
    resp = client.post("/benchmark/start", json={"url": "https://example.com", "goal": "Test"})
    assert resp.status_code == 401


def test_benchmark_start_invalid_token():
    """Requests with an invalid JWT should get 401."""
    resp = client.post(
        "/benchmark/start",
        json={"url": "https://example.com", "goal": "Test"},
        headers={"Authorization": "Bearer invalid-jwt-token"},
    )
    assert resp.status_code == 401


@patch("server.verify_clerk_jwt", return_value={"sub": "test-user-id"})
def test_start_with_mocked_clerk_jwt(mock_verify):
    """Mocking verify_clerk_jwt directly allows auth to pass."""
    async def fake_run(state, url, goal):
        state.status = "complete"
        state.success = True
        state.summary = "Done"
        state.total_ms = 1000

    with patch("server.run_benchmark", side_effect=fake_run):
        resp = client.post(
            "/benchmark/start",
            json={"url": "https://example.com", "goal": "Test"},
            headers={"Authorization": "Bearer fake-token"},
        )
    assert resp.status_code == 200
    assert "run_id" in resp.json()
    mock_verify.assert_called_once_with("fake-token")


# --- Security tests ---

def test_internal_key_rejects_wrong_key():
    """When INTERNAL_API_KEY is set, requests with wrong key get 403."""
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    with patch.object(server_module, "_INTERNAL_API_KEY", "correct-key"):
        resp = client.post(
            "/benchmark/start",
            json={"url": "https://example.com", "goal": "Test"},
            headers={"X-Internal-Key": "wrong-key"},
        )
    assert resp.status_code == 403


def test_internal_key_rejects_missing_key():
    """When INTERNAL_API_KEY is set, requests without key get 403."""
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    with patch.object(server_module, "_INTERNAL_API_KEY", "correct-key"):
        resp = client.post(
            "/benchmark/start",
            json={"url": "https://example.com", "goal": "Test"},
        )
    assert resp.status_code == 403


def test_internal_key_skipped_when_not_set():
    """When INTERNAL_API_KEY is empty, requests pass through."""
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    with patch.object(server_module, "_INTERNAL_API_KEY", ""):
        async def fake_run(state, url, goal):
            state.status = "complete"
        with patch("server.run_benchmark", side_effect=fake_run):
            resp = client.post(
                "/benchmark/start",
                json={"url": "https://example.com", "goal": "Test"},
            )
    assert resp.status_code == 200


def test_concurrency_limit():
    """User exceeding max concurrent runs gets 429."""
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    server_module._active_runs["test-user-id"] = 5  # At limit
    try:
        resp = client.post(
            "/benchmark/start",
            json={"url": "https://example.com", "goal": "Test"},
        )
        assert resp.status_code == 429
    finally:
        server_module._active_runs.clear()


def test_generate_tasks_rate_limit():
    """Exceeding task generation rate limit gets 429."""
    import time
    now = time.time()
    # Simulate 5 recent requests from same IP
    server_module._task_gen_requests["testclient"] = [now] * 5
    try:
        with patch("server.fetch_and_generate", new_callable=AsyncMock, return_value=[]):
            resp = client.post("/benchmark/generate-tasks", json={"url": "https://example.com"})
        assert resp.status_code == 429
    finally:
        server_module._task_gen_requests.clear()


def test_generate_tasks_error_no_internal_details():
    """Error responses from generate-tasks must not leak internal details."""
    with patch("server.fetch_and_generate", new_callable=AsyncMock,
               side_effect=Exception("Internal error: DB connection to 10.0.0.5 failed")):
        resp = client.post("/benchmark/generate-tasks", json={"url": "https://example.com"})
    assert resp.status_code == 500
    body = resp.json()
    assert "10.0.0.5" not in str(body)
    assert "DB connection" not in str(body)


def test_status_not_found_no_id_leak():
    """Status 404 must not echo back the run_id."""
    resp = client.get("/benchmark/status/secret-run-id-12345")
    assert resp.status_code == 404
    body = resp.json()
    assert "secret-run-id-12345" not in str(body)


def test_run_eviction():
    """Completed runs should be evicted when store exceeds limit."""
    from benchmark_runner import RunState
    # Fill with completed runs
    for i in range(210):
        state = RunState(run_id=f"run-{i}", status="complete")
        server_module._runs[f"run-{i}"] = state
    assert len(server_module._runs) == 210
    server_module._evict_stale_runs()
    assert len(server_module._runs) < 210
