import asyncio
import ipaddress
import os
import re
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

import anthropic
import httpx

import browser_env
import llm
import persistence
from server import app, get_current_user
import server as server_module
from tests.fakes import install_fake_anthropic, text_response

client = TestClient(app)

FAKE_USER = {"user_id": "test-user-id"}


def _reset_server_state():
    server_module._runs.clear()
    server_module._run_tasks.clear()
    server_module._active_runs.clear()
    server_module._task_gen_requests.clear()
    server_module._user_run_timestamps.clear()
    server_module._quota_loaded = False
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def clear_runs():
    _reset_server_state()
    yield
    _reset_server_state()


PUBLIC_ADDRINFO = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """Every host name resolves to a public address, so no test needs the network or a working
    resolver. Address literals still go through the real lookup (they are parsed, not queried)."""
    real = socket.getaddrinfo

    def lookup(host, *args, **kwargs):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return PUBLIC_ADDRINFO
        return real(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", lookup)


@pytest.fixture
def clerk_mode(monkeypatch):
    """AUTH_MODE=clerk (the old, hosted behavior: a Bearer token is required)."""
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.setenv("CLERK_ISSUER_URL", "https://test.clerk.accounts.dev")


async def _fake_run_done(state, url, goal, viewport=None):
    state.status = "complete"
    state.success = True
    state.summary = "Done"
    state.total_ms = 1000


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_start_returns_run_id():
    """Authenticated start returns a run_id."""
    async def fake_run(state, url, goal, viewport=None):
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


@pytest.mark.parametrize("url", [
    "http://127.0.0.1",
    "http://127.0.0.1:8000/admin",
    "http://localhost:8080",
    "http://[::1]/",
    "http://0.0.0.0",
    "http://10.0.0.1",
    "http://192.168.1.100",
    "http://172.16.0.1",
    "http://100.64.0.1",
    "http://169.254.169.254/latest/meta-data",  # the cloud metadata address
    "http://metadata.google.internal/computeMetadata/v1/",
])
def test_start_refuses_this_machine_and_internal_addresses(url):
    """The check generate-tasks makes also guards start: a direct API call cannot aim the browser inward."""
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    with patch("server.run_benchmark", new_callable=AsyncMock) as run:
        resp = client.post("/benchmark/start", json={"url": url, "goal": "Test"})
    assert resp.status_code == 422
    assert resp.json()["detail"] == f"Invalid or disallowed URL: {url}"
    run.assert_not_called()
    assert not server_module._runs and not server_module._active_runs  # no run, no slot taken


def test_start_refuses_a_host_that_resolves_to_an_internal_address():
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    internal = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0))]
    with patch("task_generator.socket.getaddrinfo", return_value=internal), \
            patch("server.run_benchmark", new_callable=AsyncMock) as run:
        resp = client.post("/benchmark/start", json={"url": "https://rebinding.example.com", "goal": "Test"})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Invalid or disallowed URL: https://rebinding.example.com"
    run.assert_not_called()


def test_start_says_so_when_the_host_does_not_resolve():
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    with patch("task_generator.socket.getaddrinfo", side_effect=socket.gaierror(8, "unknown host")), \
            patch("server.run_benchmark", new_callable=AsyncMock) as run:
        resp = client.post("/benchmark/start", json={"url": "https://no-such-shop.example/", "goal": "Test"})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Could not resolve this host: no-such-shop.example"
    run.assert_not_called()


def test_start_accepts_a_public_url():
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    with patch("server.run_benchmark", side_effect=_fake_run_done) as run:
        resp = client.post("/benchmark/start", json={"url": "https://www.example.com/shop?q=1", "goal": "Test"})
    assert resp.status_code == 200
    assert resp.json()["run_id"]
    run.assert_called_once()


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

def test_benchmark_start_no_token(clerk_mode):
    """In clerk mode, requests without a Bearer token get 401."""
    resp = client.post("/benchmark/start", json={"url": "https://example.com", "goal": "Test"})
    assert resp.status_code == 401


def test_benchmark_start_invalid_token(clerk_mode):
    """In clerk mode, requests with an invalid JWT get 401."""
    resp = client.post(
        "/benchmark/start",
        json={"url": "https://example.com", "goal": "Test"},
        headers={"Authorization": "Bearer invalid-jwt-token"},
    )
    assert resp.status_code == 401


@patch("server.verify_clerk_jwt", return_value={"sub": "test-user-id"})
def test_start_with_mocked_clerk_jwt(mock_verify, clerk_mode):
    """Mocking verify_clerk_jwt directly allows auth to pass."""
    async def fake_run(state, url, goal, viewport=None):
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
        async def fake_run(state, url, goal, viewport=None):
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
    server_module._active_runs["test-user-id"] = 2  # At the default limit
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


# ---------------------------------------------------------------------------
# Helpers for the tests below
# ---------------------------------------------------------------------------

START = {"url": "https://books.toscrape.com", "goal": "Add any book to the basket.", "label": "Add a book"}


@pytest.fixture
def configured(monkeypatch):
    """A server that passes startup: a (fake) key is set and Chromium is 'installed'."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    monkeypatch.setattr(browser_env, "chromium_path", lambda: "/fake/chromium")


@pytest.fixture
def live(configured):
    """A TestClient that runs the app's lifespan, so background run tasks really run."""
    with TestClient(app) as c:
        yield c


def wait_for_status(c, run_id, wanted=("complete", "error"), timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = c.get(f"/benchmark/status/{run_id}").json()
        if body["status"] in wanted:
            return body
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} still {body['status']} after {timeout}s")


@pytest.fixture
def instant_sleep(monkeypatch):
    """Demo runs sleep for seconds; make those waits (not the test's own) near-instant."""
    real_sleep = asyncio.sleep

    async def quick(delay, *args, **kwargs):
        return await real_sleep(min(delay, 0.01), *args, **kwargs)

    monkeypatch.setattr(asyncio, "sleep", quick)


# ---------------------------------------------------------------------------
# AUTH_MODE
# ---------------------------------------------------------------------------


def test_auth_none_is_the_default_and_needs_no_token():
    assert server_module.auth_mode() == "none"
    with patch("server.run_benchmark", side_effect=_fake_run_done):
        resp = client.post("/benchmark/start", json=START)  # no Authorization header
    assert resp.status_code == 200
    state = server_module._runs[resp.json()["run_id"]]
    assert state.user_id == "local"


def test_auth_none_ignores_any_token(monkeypatch):
    monkeypatch.setattr(server_module, "verify_clerk_jwt", lambda token: pytest.fail("Clerk must not be consulted"))
    with patch("server.run_benchmark", side_effect=_fake_run_done):
        resp = client.post("/benchmark/start", json=START, headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 200


async def test_get_current_user_is_the_local_user_in_none_mode():
    assert await get_current_user(None) == {"user_id": "local"}


def test_quota_and_generate_tasks_need_no_token_in_none_mode():
    assert client.get("/benchmark/quota").status_code == 200
    with patch("server.fetch_and_generate", new_callable=AsyncMock, return_value=[]):
        assert client.post("/benchmark/generate-tasks", json={"url": "https://example.com"}).status_code == 200


def test_invalid_auth_mode_is_a_config_error(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "basic")
    with pytest.raises(server_module.ConfigError, match="AUTH_MODE"):
        server_module.auth_mode()


@pytest.mark.parametrize("raw", ["clerk", "CLERK", " Clerk "])
def test_auth_mode_is_case_and_space_insensitive(monkeypatch, raw):
    monkeypatch.setenv("AUTH_MODE", raw)
    assert server_module.auth_mode() == "clerk"


def test_clerk_mode_requires_a_token_on_start_quota_and_generate_tasks(clerk_mode):
    assert client.post("/benchmark/start", json=START).status_code == 401
    assert client.get("/benchmark/quota").status_code == 401
    assert client.post("/benchmark/generate-tasks", json={"url": "https://example.com"}).status_code == 401


@patch("server.verify_clerk_jwt", return_value={"sub": "user_abc", "email": "someone@example.invalid"})
def test_clerk_mode_uses_the_token_subject_as_the_user(mock_verify, clerk_mode):
    with patch("server.run_benchmark", side_effect=_fake_run_done):
        resp = client.post("/benchmark/start", json=START, headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    assert server_module._runs[resp.json()["run_id"]].user_id == "user_abc"


@patch("server.verify_clerk_jwt", side_effect=Exception("signature check failed"))
def test_clerk_mode_failed_verification_is_401_without_details(mock_verify, clerk_mode):
    resp = client.post("/benchmark/start", json=START, headers={"Authorization": "Bearer t"})
    assert resp.status_code == 401
    assert "signature" not in resp.text


@patch("server.verify_clerk_jwt", return_value={"sub": "user_abc", "email": "someone@example.invalid"})
def test_there_is_no_admin_bypass(mock_verify, clerk_mode, monkeypatch):
    """No email in the token buys anything: the quota applies to everyone."""
    assert not hasattr(server_module, "ADMIN_EMAILS")
    monkeypatch.setenv("DAILY_RUN_QUOTA", "1")
    headers = {"Authorization": "Bearer t"}
    with patch("server.run_benchmark", side_effect=_fake_run_done):
        assert client.post("/benchmark/start", json=START, headers=headers).status_code == 200
        assert client.post("/benchmark/start", json=START, headers=headers).status_code == 429


# ---------------------------------------------------------------------------
# DAILY_RUN_QUOTA and MAX_CONCURRENT_RUNS
# ---------------------------------------------------------------------------


def test_quota_defaults_to_unlimited_without_sign_in():
    assert server_module.daily_run_quota() == 0
    assert client.get("/benchmark/quota").json() == {"remaining": None, "resets_in": 0, "limit": 0}


def test_quota_defaults_to_three_in_clerk_mode(clerk_mode):
    assert server_module.daily_run_quota() == 3
    with patch("server.verify_clerk_jwt", return_value={"sub": "u"}):
        body = client.get("/benchmark/quota", headers={"Authorization": "Bearer t"}).json()
    assert body == {"remaining": 3, "resets_in": 0, "limit": 3}


def test_quota_env_overrides_the_default_in_both_modes(monkeypatch):
    monkeypatch.setenv("DAILY_RUN_QUOTA", "5")
    assert server_module.daily_run_quota() == 5
    monkeypatch.setenv("AUTH_MODE", "clerk")
    assert server_module.daily_run_quota() == 5
    monkeypatch.setenv("DAILY_RUN_QUOTA", "0")  # explicit 0 = unlimited, even with Clerk
    assert server_module.daily_run_quota() == 0


@pytest.mark.parametrize("raw", ["abc", "-1", "1.5"])
def test_bad_numeric_settings_are_config_errors(monkeypatch, raw):
    monkeypatch.setenv("DAILY_RUN_QUOTA", raw)
    with pytest.raises(server_module.ConfigError, match="DAILY_RUN_QUOTA"):
        server_module.daily_run_quota()
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", raw)
    with pytest.raises(server_module.ConfigError, match="MAX_CONCURRENT_RUNS"):
        server_module.max_concurrent_runs()


def test_unlimited_quota_never_blocks_and_writes_no_quota_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "0")
    with patch("server.run_benchmark", side_effect=_fake_run_done):
        for _ in range(6):
            resp = client.post("/benchmark/start", json=START)
            assert resp.status_code == 200
    assert resp.json()["remaining"] is None and resp.json()["limit"] == 0
    assert not (tmp_path / "runs" / ".quota_data.json").exists()


def test_daily_quota_blocks_the_run_after_the_limit(monkeypatch):
    monkeypatch.setenv("DAILY_RUN_QUOTA", "2")
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "0")
    with patch("server.run_benchmark", side_effect=_fake_run_done):
        first = client.post("/benchmark/start", json=START)
        second = client.post("/benchmark/start", json=START)
        third = client.post("/benchmark/start", json=START)

    assert first.status_code == 200 and first.json()["remaining"] == 1 and first.json()["limit"] == 2
    assert second.status_code == 200 and second.json()["remaining"] == 0
    assert third.status_code == 429
    detail = third.json()["detail"]
    assert "Daily limit reached" in detail["error"]
    assert detail["remaining"] == 0 and 0 < detail["resets_in"] <= 24 * 3600

    body = client.get("/benchmark/quota").json()
    assert body["remaining"] == 0 and body["limit"] == 2 and body["resets_in"] > 0


def test_quota_window_rolls_after_24_hours(monkeypatch):
    monkeypatch.setenv("DAILY_RUN_QUOTA", "1")
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "0")
    server_module._ensure_quota_loaded()
    server_module._user_run_timestamps["local"] = [time.time() - 24 * 3600 - 5]
    assert client.get("/benchmark/quota").json()["remaining"] == 1
    server_module._user_run_timestamps["local"] = [time.time() - 3600]
    body = client.get("/benchmark/quota").json()
    assert body["remaining"] == 0 and 22 * 3600 < body["resets_in"] <= 23 * 3600


def test_quota_survives_a_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("DAILY_RUN_QUOTA", "1")
    with patch("server.run_benchmark", side_effect=_fake_run_done):
        assert client.post("/benchmark/start", json=START).status_code == 200
    assert (tmp_path / "runs" / ".quota_data.json").exists()

    # A fresh process: nothing in memory, the file is read on first use.
    server_module._user_run_timestamps.clear()
    server_module._quota_loaded = False
    assert client.get("/benchmark/quota").json()["remaining"] == 0


def test_max_concurrent_runs_defaults_to_two():
    assert server_module.max_concurrent_runs() == 2


def test_concurrency_limit_follows_the_env(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")
    server_module._active_runs["local"] = 1
    resp = client.post("/benchmark/start", json=START)
    assert resp.status_code == 429
    assert "Too many runs" in resp.json()["detail"]["error"]

    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "3")
    with patch("server.run_benchmark", side_effect=_fake_run_done):
        assert client.post("/benchmark/start", json=START).status_code == 200


def test_zero_max_concurrent_runs_means_unlimited(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "0")
    server_module._active_runs["local"] = 50
    with patch("server.run_benchmark", side_effect=_fake_run_done):
        assert client.post("/benchmark/start", json=START).status_code == 200


def test_a_finished_run_frees_its_slot(live, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")
    with patch("server.run_benchmark", side_effect=_fake_run_done):
        run_id = live.post("/benchmark/start", json=START).json()["run_id"]
        wait_for_status(live, run_id)
        deadline = time.time() + 2
        while server_module._active_runs.get("local") and time.time() < deadline:
            time.sleep(0.01)
        assert server_module._active_runs.get("local", 0) == 0
        assert live.post("/benchmark/start", json=START).status_code == 200


def test_a_crashed_run_frees_its_slot_and_ends_as_an_error(live, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")

    async def crash(state, url, goal, viewport=None):
        raise RuntimeError("boom")

    with patch("server.run_benchmark", side_effect=crash):
        run_id = live.post("/benchmark/start", json=START).json()["run_id"]
        body = wait_for_status(live, run_id)
    assert body["status"] == "error"
    assert body["message"] == "The run encountered an error."
    deadline = time.time() + 2
    while server_module._active_runs.get("local") and time.time() < deadline:
        time.sleep(0.01)
    assert server_module._active_runs.get("local", 0) == 0


# ---------------------------------------------------------------------------
# Startup: fail fast on a bad setup
# ---------------------------------------------------------------------------


@pytest.fixture
def no_keys(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(browser_env, "chromium_path", lambda: "/fake/chromium")


def test_startup_fails_fast_without_an_anthropic_key(no_keys):
    with pytest.raises(server_module.ConfigError) as excinfo:
        with TestClient(app):
            pytest.fail("the server must not come up")
    message = str(excinfo.value)
    assert "ANTHROPIC_API_KEY" in message
    assert "DEMO_MODE=true" in message  # the way out is in the message


SERVER_DIR = Path(__file__).resolve().parent.parent


async def _run_lifespan(application):
    """Drive the ASGI lifespan the way uvicorn does; returns (messages sent, exception raised)."""
    sent = []
    inbox = asyncio.Queue()
    await inbox.put({"type": "lifespan.startup"})

    async def receive():
        return await inbox.get()

    async def send(message):
        sent.append(message)

    scope = {"type": "lifespan", "asgi": {"version": "3.0", "spec_version": "2.0"}, "state": {}}
    try:
        await application(scope, receive, send)
    except BaseException as exc:  # noqa: BLE001 - the test inspects it
        return sent, exc
    return sent, None


async def test_a_failed_startup_reports_only_the_reason_to_uvicorn(no_keys):
    sent, exc = await _run_lifespan(app)

    assert isinstance(exc, server_module.ConfigError)  # the server still does not come up
    assert [m["type"] for m in sent] == ["lifespan.startup.failed"]
    message = sent[0]["message"]
    assert message == str(exc)
    assert "ANTHROPIC_API_KEY" in message and "DEMO_MODE=true" in message
    assert "Traceback" not in message and "\n" not in message


async def test_a_good_startup_is_untouched_by_the_error_reporting(configured):
    inbox = asyncio.Queue()
    sent = []
    await inbox.put({"type": "lifespan.startup"})
    await inbox.put({"type": "lifespan.shutdown"})

    async def receive():
        return await inbox.get()

    async def send(message):
        sent.append(message["type"])

    await app({"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}, receive, send)
    assert sent == ["lifespan.startup.complete", "lifespan.shutdown.complete"]


def _child_env(**extra):
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    # Set to empty rather than removed, so that a developer's .env cannot fill them in again.
    env.update(ANTHROPIC_API_KEY="", ANTHROPIC_AUTH_TOKEN="", OPENAI_API_KEY="", DEMO_MODE="")
    env.update(LLM_PROVIDER="anthropic", AUTH_MODE="none")
    env.update(extra)
    return env


def test_uvicorn_without_a_key_prints_one_clear_line_and_exits_non_zero():
    """The real thing: start uvicorn on the app with no key (this is what 'make dev' does)."""
    result = subprocess.run(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "0"],
        cwd=SERVER_DIR, env=_child_env(), capture_output=True, text=True, timeout=120,
    )
    log = result.stdout + result.stderr
    assert result.returncode == 3, log
    assert "ANTHROPIC_API_KEY is not set" in log
    assert "DEMO_MODE=true" in log
    assert "Traceback" not in log
    assert "Application startup failed. Exiting." in log
    assert len([line for line in log.splitlines() if "ANTHROPIC_API_KEY" in line]) == 1


def test_startup_succeeds_with_a_key(no_keys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200


def test_startup_accepts_an_auth_token_instead_of_a_key(no_keys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-not-real")
    server_module.validate_startup()


def test_demo_mode_starts_with_no_keys_at_all(no_keys, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setattr(browser_env, "chromium_path", lambda: None)
    with TestClient(app) as c:
        assert c.get("/health").json()["demo_mode"] is True


def test_openai_provider_needs_openai_key_not_anthropic(no_keys, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    with pytest.raises(server_module.ConfigError, match="OPENAI_API_KEY"):
        server_module.validate_startup()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    server_module.validate_startup()


def test_unknown_llm_provider_is_a_config_error(no_keys, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(server_module.ConfigError, match="LLM_PROVIDER"):
        server_module.validate_startup()


def test_bad_effort_setting_is_a_config_error(no_keys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    monkeypatch.setenv("BENCHMARK_AGENT_EFFORT", "turbo")
    with pytest.raises(server_module.ConfigError, match="BENCHMARK_AGENT_EFFORT"):
        server_module.validate_startup()


@pytest.mark.parametrize("name,value", [
    ("AUTH_MODE", "basic"),
    ("DAILY_RUN_QUOTA", "lots"),
    ("MAX_CONCURRENT_RUNS", "-2"),
    ("BENCHMARK_TIMEOUT_S", "0"),
])
def test_invalid_settings_stop_the_server(configured, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(server_module.ConfigError, match=name):
        server_module.validate_startup()


def test_clerk_mode_needs_clerk_settings(configured, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "clerk")
    monkeypatch.delenv("CLERK_ISSUER_URL", raising=False)
    monkeypatch.delenv("CLERK_PUBLISHABLE_KEY", raising=False)
    with pytest.raises(server_module.ConfigError, match="CLERK_ISSUER_URL"):
        server_module.validate_startup()
    monkeypatch.setenv("CLERK_ISSUER_URL", "https://test.clerk.accounts.dev")
    server_module.validate_startup()


def test_browserbase_provider_needs_its_keys(configured, monkeypatch):
    monkeypatch.setenv("BENCHMARK_BROWSER_PROVIDER", "browserbase")
    monkeypatch.delenv("BROWSERBASE_API_KEY", raising=False)
    with pytest.raises(server_module.ConfigError, match="BROWSERBASE_API_KEY"):
        server_module.validate_startup()


def test_missing_chromium_warns_but_does_not_stop_the_server(configured, monkeypatch, caplog):
    monkeypatch.setattr(browser_env, "chromium_path", lambda: None)
    with caplog.at_level("WARNING"):
        server_module.validate_startup()
    assert "playwright install chromium" in caplog.text


# ---------------------------------------------------------------------------
# Logging starts with the server
# ---------------------------------------------------------------------------


def test_the_first_task_generation_cost_line_reaches_the_server_log():
    """Before the first run imports browser-use nothing configured logging, so this line was lost."""
    script = textwrap.dedent(
        """
        import runtime_env
        import server
        from _pytest.monkeypatch import MonkeyPatch
        from tests.fakes import install_fake_anthropic, text_response

        install_fake_anthropic(MonkeyPatch(), text_response(
            {"tasks": [{"label": "A", "goal": "Do A."}, {"label": "B", "goal": "Do B."}, {"label": "C", "goal": "Do C."}]}
        ))
        server.configure_logging()
        import task_generator
        task_generator.generate_tasks({"title": "Shop", "description": "", "visible_text": "", "url": "https://shop.example.com"})
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=SERVER_DIR, env=_child_env(), capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "task generation: model=claude-sonnet-5-5 cost=$" in result.stderr


def test_without_configure_logging_that_line_is_lost():
    """The control for the test above: it fails for the reason it claims."""
    script = textwrap.dedent(
        """
        import runtime_env
        import task_generator
        from _pytest.monkeypatch import MonkeyPatch
        from tests.fakes import install_fake_anthropic, text_response

        install_fake_anthropic(MonkeyPatch(), text_response({"tasks": [{"label": "A", "goal": "Do A."}]}))
        task_generator.generate_tasks({"title": "Shop", "description": "", "visible_text": "", "url": "https://shop.example.com"})
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=SERVER_DIR, env=_child_env(), capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "task generation" not in result.stderr


def test_the_startup_runs_configure_logging(configured, monkeypatch):
    called = []
    monkeypatch.setattr(server_module, "configure_logging", lambda: called.append(True))
    with TestClient(app):
        pass
    assert called == [True]


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health_reports_provider_and_models(monkeypatch):
    body = client.get("/health").json()
    assert body["ok"] is True
    assert body["provider"] == "anthropic"
    assert body["models"] == {
        "agent": "claude-sonnet-5-5",
        "judge": "claude-sonnet-5-5",
        "taskgen": "claude-sonnet-5-5",
    }
    assert body["browser_provider"] == "local"
    assert body["auth_mode"] == "none"
    assert body["demo_mode"] is False


def test_health_reports_the_effective_run_time_limit(monkeypatch):
    body = client.get("/health").json()
    assert body["timeout_s"] == 180 and isinstance(body["timeout_s"], int)
    assert body["demo_mode"] is False  # still there, still a bool
    monkeypatch.setenv("BENCHMARK_TIMEOUT_S", "45")
    assert client.get("/health").json()["timeout_s"] == 45
    monkeypatch.setenv("BENCHMARK_TIMEOUT_S", "90.4")
    assert client.get("/health").json()["timeout_s"] == 90
    monkeypatch.setenv("BENCHMARK_TIMEOUT_S", "0.25")
    assert client.get("/health").json()["timeout_s"] == 1  # never 0 for a positive limit


def test_health_has_exactly_the_documented_fields():
    assert set(client.get("/health").json()) == {
        "ok", "browser_provider", "provider", "models", "auth_mode", "demo_mode", "timeout_s",
    }


def test_health_follows_the_model_settings(monkeypatch):
    monkeypatch.setenv("BENCHMARK_AGENT_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("BENCHMARK_JUDGE_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("AUTH_MODE", "clerk")
    body = client.get("/health").json()
    assert body["models"]["agent"] == "claude-opus-5-5"
    assert body["models"]["judge"] == "claude-haiku-5-5"
    assert body["models"]["taskgen"] == "claude-sonnet-5-5"
    assert body["auth_mode"] == "clerk"


def test_health_never_shows_keys(monkeypatch):
    secrets = {
        # Assembled from pieces so no key-shaped literal sits in the source.
        "ANTHROPIC_API_KEY": "sk-ant-" + "SECRET-anthropic-" + "0001",
        "OPENAI_API_KEY": "sk-" + "SECRET-openai-" + "0002",
        "INTERNAL_API_KEY": "SECRET-" + "internal-" + "0003",
        "BROWSERBASE_API_KEY": "SECRET-" + "bb-" + "0004",
    }
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)
    text = client.get("/health").text
    assert "SECRET" not in text
    assert "key" not in text.lower().replace("browser_provider", "")


# ---------------------------------------------------------------------------
# Status: cost_usd and agent_model, over HTTP
# ---------------------------------------------------------------------------


def test_status_of_a_finished_run_has_cost_usd_and_agent_model(live):
    async def priced_run(state, url, goal, viewport=None):
        state.record_usage(type("U", (), {
            "total_prompt_tokens": 12_000, "total_prompt_cached_tokens": 0,
            "total_completion_tokens": 1_000, "total_prompt_cache_creation_tokens": 0,
            "total_tokens": 13_000,
        })())
        state.total_ms = 5000
        state.status = "complete"
        state.result_state = "pass"
        state.success = True

    with patch("server.run_benchmark", side_effect=priced_run):
        run_id = live.post("/benchmark/start", json=START).json()["run_id"]
        body = wait_for_status(live, run_id)

    assert body["status"] == "complete"
    assert body["agent_model"] == "claude-sonnet-5-5"
    assert body["cost_usd"] == pytest.approx((12_000 * 2.0 + 1_000 * 10.0) / 1_000_000)
    assert (body["input_tokens"], body["output_tokens"], body["total_tokens"]) == (12_000, 1_000, 13_000)


def test_status_cost_is_null_for_an_unpriced_agent_model(live, monkeypatch):
    monkeypatch.setenv("BENCHMARK_AGENT_MODEL", "some-unpriced-model")

    async def run(state, url, goal, viewport=None):
        state.record_usage(type("U", (), {"total_prompt_tokens": 10, "total_completion_tokens": 5, "total_tokens": 15})())
        state.status = "complete"

    with patch("server.run_benchmark", side_effect=run):
        run_id = live.post("/benchmark/start", json=START).json()["run_id"]
        body = wait_for_status(live, run_id)
    assert body["agent_model"] == "some-unpriced-model"
    assert body["cost_usd"] is None
    assert body["total_tokens"] == 15


# ---------------------------------------------------------------------------
# Local persistence through the API
# ---------------------------------------------------------------------------


def test_start_creates_the_run_file_for_the_local_user(live, tmp_path):
    async def finished(state, url, goal, viewport=None):
        state.status = "complete"

    with patch("server.run_benchmark", side_effect=finished):
        run_id = live.post("/benchmark/start", json=START).json()["run_id"]
        wait_for_status(live, run_id)

    record = persistence.read_run(run_id)
    assert record["user_id"] == "local"
    assert record["start_url"] == START["url"]
    assert record["task_label"] == "Add a book"
    assert record["task_goal"] == START["goal"]
    assert record["agent_model"] == "claude-sonnet-5-5"
    assert (tmp_path / "runs" / f"{run_id}.json").exists()


def test_the_run_state_knows_its_run_file(live):
    async def finished(state, url, goal, viewport=None):
        assert state.persisted_run_id == state.run_id
        state.status = "complete"

    with patch("server.run_benchmark", side_effect=finished):
        run_id = live.post("/benchmark/start", json=START).json()["run_id"]
        wait_for_status(live, run_id)


def test_an_unwritable_runs_dir_does_not_stop_a_run(live, monkeypatch, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("x")
    monkeypatch.setenv("RUNS_DIR", str(blocker / "runs"))
    seen = {}

    async def finished(state, url, goal, viewport=None):
        seen["persisted"] = state.persisted_run_id
        state.status = "complete"

    with patch("server.run_benchmark", side_effect=finished):
        run_id = live.post("/benchmark/start", json=START).json()["run_id"]
        wait_for_status(live, run_id)
    assert seen["persisted"] is None


def test_start_passes_the_viewport_to_the_runner(live):
    seen = {}

    async def finished(state, url, goal, viewport=None):
        seen["viewport"] = viewport
        state.status = "complete"

    with patch("server.run_benchmark", side_effect=finished):
        body = {**START, "viewport_width": 390, "viewport_height": 844}
        run_id = live.post("/benchmark/start", json=body).json()["run_id"]
        wait_for_status(live, run_id)
    assert seen["viewport"] == {"width": 390, "height": 844}


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stuck_status", ["running", "analyzing"])
def test_cancel_ends_a_run_in_either_phase(live, stuck_status):
    async def hang(state, url, goal, viewport=None):
        state.status = stuck_status
        await asyncio.sleep(60)

    with patch("server.run_benchmark", side_effect=hang):
        run_id = live.post("/benchmark/start", json=START).json()["run_id"]
        wait_for_status(live, run_id, wanted=(stuck_status,))
        assert live.post(f"/benchmark/cancel/{run_id}").json() == {"ok": True}
        body = wait_for_status(live, run_id, wanted=("error",))
    assert body["message"] == "Run cancelled by user."
    deadline = time.time() + 2
    while server_module._active_runs.get("local") and time.time() < deadline:
        time.sleep(0.01)
    assert server_module._active_runs.get("local", 0) == 0


def test_cancel_leaves_a_finished_run_alone(live):
    async def finished(state, url, goal, viewport=None):
        state.status = "complete"
        state.success = True

    with patch("server.run_benchmark", side_effect=finished):
        run_id = live.post("/benchmark/start", json=START).json()["run_id"]
        wait_for_status(live, run_id)
        live.post(f"/benchmark/cancel/{run_id}")
        assert live.get(f"/benchmark/status/{run_id}").json()["status"] == "complete"


# ---------------------------------------------------------------------------
# generate-tasks: model failures map to HTTP answers
# ---------------------------------------------------------------------------

SITE = {"url": "https://www.dominos.com"}  # a known shop, so no page is fetched


def _api_error(cls, status):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("nope", response=httpx.Response(status, request=request), body=None)


def test_generate_tasks_end_to_end_with_a_fake_model(monkeypatch):
    payload = {"tasks": [{"label": f"Task {i}", "goal": f"Do {i}."} for i in (1, 2, 3)]}
    calls = install_fake_anthropic(monkeypatch, text_response(payload))
    resp = client.post("/benchmark/generate-tasks", json=SITE)
    assert resp.status_code == 200
    assert [t["id"] for t in resp.json()["tasks"]] == [1, 2, 3]
    assert calls[0]["model"] == "claude-sonnet-5-5"


def test_generate_tasks_refusal_is_422_with_a_readable_reason(monkeypatch):
    from tests.fakes import refusal_response
    install_fake_anthropic(monkeypatch, refusal_response())
    resp = client.post("/benchmark/generate-tasks", json=SITE)
    assert resp.status_code == 422
    assert "declined" in resp.json()["detail"]


def test_generate_tasks_non_commerce_answer_is_422(monkeypatch):
    install_fake_anthropic(monkeypatch, text_response({"error": "Not a shop."}))
    resp = client.post("/benchmark/generate-tasks", json=SITE)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Not a shop."


def test_generate_tasks_bad_api_key_is_502_and_names_no_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SECRET-key-9999")
    install_fake_anthropic(monkeypatch, _api_error(anthropic.AuthenticationError, 401))
    resp = client.post("/benchmark/generate-tasks", json=SITE)
    assert resp.status_code == 502
    assert "SECRET" not in resp.text


def test_generate_tasks_unresolvable_host_is_422_and_says_so(monkeypatch):
    import socket

    install_fake_anthropic(monkeypatch, text_response({"tasks": []}))
    with patch("task_generator.socket.getaddrinfo", side_effect=socket.gaierror(8, "unknown host")):
        resp = client.post("/benchmark/generate-tasks", json={"url": "https://no-such-shop.example/"})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Could not resolve this host: no-such-shop.example"


def test_generate_tasks_internal_address_is_422_disallowed():
    resp = client.post("/benchmark/generate-tasks", json={"url": "http://169.254.169.254/latest/meta-data"})
    assert resp.status_code == 422
    assert resp.json()["detail"].startswith("Invalid or disallowed URL")


def test_generate_tasks_truncated_reply_is_500(monkeypatch):
    install_fake_anthropic(monkeypatch, text_response('{"tasks": [', stop_reason="max_tokens"))
    resp = client.post("/benchmark/generate-tasks", json=SITE)
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Task generation failed"


# ---------------------------------------------------------------------------
# DEMO_MODE: the whole loop with no keys, no browser, no model
# ---------------------------------------------------------------------------


def test_demo_mode_runs_the_whole_loop_without_any_key(no_keys, monkeypatch, instant_sleep, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setattr(llm, "_anthropic_client", lambda: pytest.fail("demo mode must not call a model"))
    monkeypatch.setattr(browser_env, "browser_profile", lambda **kw: pytest.fail("demo mode must not open a browser"))

    with TestClient(app) as c:
        tasks = c.post("/benchmark/generate-tasks", json={"url": "https://example.com"}).json()["tasks"]
        assert len(tasks) == 3
        run_id = c.post("/benchmark/start", json={**START, "goal": tasks[0]["goal"]}).json()["run_id"]
        body = wait_for_status(c, run_id, timeout=15)

    assert body["status"] == "complete"
    assert body["result_state"] in ("pass", "fail")
    assert len(body["steps"]) == 9
    # Canned steps fit whichever task was picked: no address, filter or variant of their own.
    descriptions = " ".join(step["description"] for step in body["steps"])
    for task_specific in ("Times Square", "address", "price filter", "Size", "Color", "promotion"):
        assert task_specific.lower() not in descriptions.lower()
    assert "cart" in descriptions
    # The phases cover every step exactly once.
    assert sorted(n for phase in body["phases"] for n in phase["steps"]) == list(range(1, 10))
    assert body["agent_model"] == "claude-sonnet-5-5"
    assert not (tmp_path / "runs").exists()  # demo runs leave no files


def test_demo_run_has_tokens_but_no_dollar_cost(no_keys, monkeypatch, instant_sleep):
    """The tokens are made up and no model is called, so a dollar figure at real prices would be a lie."""
    monkeypatch.setenv("DEMO_MODE", "true")
    with TestClient(app) as c:
        run_id = c.post("/benchmark/start", json=START).json()["run_id"]
        body = wait_for_status(c, run_id, timeout=15)
    assert body["status"] == "complete"
    assert body["cost_usd"] is None
    assert body["input_tokens"] > 0 and body["output_tokens"] > 0
    assert body["total_tokens"] == body["input_tokens"] + body["output_tokens"]
    assert body["agent_model"] == "claude-sonnet-5-5"  # everything else is still reported


def test_demo_start_does_not_look_the_host_up(no_keys, monkeypatch, instant_sleep):
    """A demo run opens nothing, so there is nothing for the URL check to guard (generate-tasks skips it too)."""
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("demo mode must not resolve hosts"))
    with TestClient(app) as c:
        resp = c.post("/benchmark/start", json={**START, "url": "http://localhost:3000"})
    assert resp.status_code == 200


# What a line of a task can ask for, and the words of the canned step that does it.
_CANNED_ACTIONS = [
    (r"\bsearch", "searching for the product"),
    (r"first result", "first matching result"),
    (r"\b(size|colou?r|options)\b", "choosing the options"),
    (r"add (it )?to (the )?(cart|bag)", "adding the item to the cart"),
    (r"open the cart", "opening the cart"),
    (r"\btotal\b", "cart total"),
]
# Things a canned run never does, so a canned task must not ask for them.
_NOT_CANNED = [r"address", r"deliver", r"times square", r"\bzip\b", r"quantit", r"\btwo\b", r"\b2\b",
               r"distinct", r"different", r"second", r"another", r"\bboth\b"]


def test_every_canned_task_is_covered_by_the_canned_steps(no_keys, monkeypatch, instant_sleep):
    """The demo plays one fixed list of steps whichever task is picked, and ends by saying the item was
    added to the cart and the cart checked. A canned task asking for an address, a quantity of 2 or a
    second item would be reported as done without any of it having happened."""
    monkeypatch.setenv("DEMO_MODE", "true")
    with TestClient(app) as c:
        tasks = c.post("/benchmark/generate-tasks", json={"url": "https://example.com"}).json()["tasks"]
        run_id = c.post("/benchmark/start", json={**START, "goal": tasks[0]["goal"]}).json()["run_id"]
        body = wait_for_status(c, run_id, timeout=15)
    steps = " ".join(step["description"] for step in body["steps"]).lower()
    assert body["status"] == "complete"
    assert len(tasks) == 3

    for task in tasks:
        for text in (task["label"], task["goal"]):
            for word in _NOT_CANNED:
                assert not re.search(word, text, re.I), f"task {task['id']} asks for {word!r}: {text!r}"
        lines = [line.strip() for line in task["goal"].splitlines() if line.strip()]
        assert any(line.upper().startswith("VERIFY") for line in lines)
        for line in lines:
            matched = [step for pattern, step in _CANNED_ACTIONS if re.search(pattern, line, re.I)]
            if not line.startswith("Go to") and not line.upper().startswith("VERIFY"):
                assert matched, f"task {task['id']} asks for something no canned step does: {line!r}"
            for step in matched:
                assert step in steps, f"no canned step {step!r} for {line!r}"
        assert "cart" in lines[-1].lower()  # the check at the end is about the cart, which the steps do reach


# ---------------------------------------------------------------------------
# Deleted hosting
# ---------------------------------------------------------------------------


def test_railway_hosting_files_are_gone():
    from pathlib import Path
    server_dir = Path(server_module.__file__).parent
    assert not (server_dir / "Dockerfile").exists()
    assert not (server_dir / "railway.toml").exists()
