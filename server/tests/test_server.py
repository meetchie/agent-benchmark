import os
os.environ.setdefault("AUTH_SECRET", "test-secret-key-for-testing")

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from server import app, get_current_user
import server as server_module

client = TestClient(app)

FAKE_USER = {"user_id": "00000000-0000-0000-0000-000000000001", "email": "test@test.com"}


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
    # Mock run_benchmark so no actual agent runs during the test
    async def fake_run(state, url, goal):
        state.status = "complete"
        state.success = True
        state.summary = "Done"
        state.total_ms = 1000

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    with patch("server.try_record_run", new_callable=AsyncMock, return_value={"id": "run-1", "remaining_runs": 2, "reset_time": None}), \
         patch("server.run_benchmark", side_effect=fake_run):
        resp = client.post(
            "/benchmark/start",
            json={"url": "https://example.com", "goal": "Test"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert isinstance(data["run_id"], str)
    assert data["remaining_runs"] == 2


def test_status_not_found():
    resp = client.get("/benchmark/status/nonexistent-id")
    assert resp.status_code == 404


def test_start_missing_fields():
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    with patch("server.try_record_run", new_callable=AsyncMock, return_value={"id": "run-1", "remaining_runs": 2, "reset_time": None}):
        resp = client.post("/benchmark/start", json={"url": "https://example.com"})
    assert resp.status_code == 422  # FastAPI validation error


def test_start_invalid_url():
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    with patch("server.try_record_run", new_callable=AsyncMock, return_value={"id": "run-1", "remaining_runs": 2, "reset_time": None}):
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


# --- Auth endpoint tests ---

def test_auth_signup_success():
    with patch("server.signup", new_callable=AsyncMock, return_value={"token": "fake-jwt"}):
        resp = client.post("/auth/signup", json={"email": "test@example.com", "password": "password123"})
    assert resp.status_code == 200
    assert resp.json()["token"] == "fake-jwt"


def test_auth_signup_bad_email():
    with patch("server.signup", new_callable=AsyncMock, side_effect=ValueError("Invalid email format")):
        resp = client.post("/auth/signup", json={"email": "bad", "password": "password123"})
    assert resp.status_code == 422


def test_auth_signin_success():
    with patch("server.signin", new_callable=AsyncMock, return_value={"token": "fake-jwt"}):
        resp = client.post("/auth/signin", json={"email": "test@example.com", "password": "password123"})
    assert resp.status_code == 200


def test_auth_signin_bad_creds():
    with patch("server.signin", new_callable=AsyncMock, side_effect=PermissionError("Invalid email or password")):
        resp = client.post("/auth/signin", json={"email": "test@example.com", "password": "wrong"})
    assert resp.status_code == 401


def test_auth_me_no_token():
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_benchmark_start_no_token():
    resp = client.post("/benchmark/start", json={"url": "https://example.com", "goal": "Test"})
    assert resp.status_code == 401
