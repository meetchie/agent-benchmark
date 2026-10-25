"""No browser outlives an interrupted run: Ctrl-C of the arena, and stopping the server.

These start the real programs in a child process, with a real headless Chromium on the
local fixture shop and a stand-in model API that accepts the request and never answers,
so the agent is mid-run, waiting on the model, when the signal arrives. Nothing leaves
127.0.0.1 and no model is billed. Every browser the test saw is killed by PID at the
end whatever happens, so a failing test leaves nothing behind either.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import psutil
import pytest

from tests.fixture_shop import FixtureShop

SERVER_DIR = Path(__file__).resolve().parents[1]


def _have_chromium() -> bool:
    from browser_env import chromium_path

    return bool(chromium_path())


pytestmark = pytest.mark.skipif(not _have_chromium(), reason="no local Chromium (uv run playwright install chromium)")


class SilentModelAPI:
    """Accepts connections and reads requests, but never answers: a model call that hangs."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.requests = 0
        self.conns: list[socket.socket] = []
        self.thread = threading.Thread(target=self._serve, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.sock.getsockname()[1]}"

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.conns.append(conn)
            threading.Thread(target=self._read, args=(conn,), daemon=True).start()

    def _read(self, conn):
        try:
            while conn.recv(65536):
                self.requests += 1
        except OSError:
            pass

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.sock.close()
        for conn in self.conns:
            conn.close()


def child_env(tmp_path: Path, model_url: str) -> dict[str, str]:
    tmp = tmp_path / "tmp"
    tmp.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    env.update(
        ANTHROPIC_API_KEY="test-key-not-real",  # the stand-in API never checks it
        ANTHROPIC_AUTH_TOKEN="",
        ANTHROPIC_BASE_URL=model_url,
        OPENAI_API_KEY="",
        LLM_PROVIDER="anthropic",
        DEMO_MODE="",
        AUTH_MODE="none",
        BENCHMARK_HEADLESS="true",
        RUNS_DIR=str(tmp_path / "runs"),
        TMPDIR=str(tmp),
        PYTHONUNBUFFERED="1",
    )
    return env


def browsers_of(pid: int) -> list[int]:
    """PIDs of the Chromium processes under ``pid`` (the browser and its helpers)."""
    try:
        procs = psutil.Process(pid).children(recursive=True)
    except psutil.Error:
        return []
    found = []
    for proc in procs:
        try:
            if any(a.startswith("--user-data-dir=") for a in proc.cmdline()) or "--type=" in " ".join(proc.cmdline()):
                found.append(proc.pid)
        except psutil.Error:
            continue
    return found


def wait_for(condition, timeout: float, what: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")


def alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def leftover_temp_dirs(tmp_path: Path) -> list[str]:
    names = ("browseruse-tmp-", "browser_use_agent_", "agent-benchmark-agent-files-")
    return sorted(p.name for p in (tmp_path / "tmp").iterdir() if p.name.startswith(names))


@pytest.fixture
def seen_browsers():
    """Browser PIDs a test saw; any still alive at the end are killed by PID."""
    pids: list[int] = []
    yield pids
    for pid in pids:
        if alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def stop_child(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=10)


def test_ctrl_c_of_an_arena_browseruse_run_leaves_no_browser(tmp_path, seen_browsers):
    with FixtureShop() as shop, SilentModelAPI() as model:
        proc = subprocess.Popen(
            [sys.executable, "arena.py", "--agent", "BROWSERUSE", "--goal", "Find the Iron Chain Belt",
             "--url", shop.base + "/", "--no-judge", "--max-steps", "3", "--log-dir", str(tmp_path / "logs")],
            cwd=SERVER_DIR, env=child_env(tmp_path, model.url),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True,
        )
        try:
            seen_browsers += wait_for(lambda: browsers_of(proc.pid), 60, "the agent's Chromium")
            wait_for(lambda: model.requests, 60, "the agent's first model call")
            seen_browsers += [p for p in browsers_of(proc.pid) if p not in seen_browsers]

            # One Ctrl-C in a terminal under `uv run`: the terminal's SIGINT, then the copy uv forwards.
            os.kill(proc.pid, signal.SIGINT)
            time.sleep(0.2)
            os.kill(proc.pid, signal.SIGINT)
            out, _ = proc.communicate(timeout=60)
        finally:
            stop_child(proc)

    assert proc.returncode == 130, out
    assert "Traceback" not in out, out
    wait_for(lambda: all(not alive(p) for p in seen_browsers), 10, "the browsers to exit")
    assert leftover_temp_dirs(tmp_path) == []


SERVER_LAUNCHER = """
import sys
sys.path.insert(0, sys.argv[2])  # this checkout's server/, whatever else is installed
import uvicorn
import server

async def any_url(url):
    return None

# The fixture shop is on 127.0.0.1, which the real URL guard refuses.
server.check_url = any_url
uvicorn.run(server.app, host="127.0.0.1", port=int(sys.argv[1]), log_level="info")
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server_with_a_run(tmp_path, shop, model, seen_browsers):
    port = free_port()
    launcher = tmp_path / "launch_server.py"
    launcher.write_text(SERVER_LAUNCHER)
    proc = subprocess.Popen(
        [sys.executable, str(launcher), str(port), str(SERVER_DIR)], cwd=SERVER_DIR, env=child_env(tmp_path, model.url),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True,
    )
    base = f"http://127.0.0.1:{port}"

    def healthy():
        try:
            return httpx.get(base + "/health", timeout=1).status_code == 200
        except httpx.HTTPError:
            return proc.poll() is not None and pytest.fail(proc.stdout.read())

    wait_for(healthy, 60, "the server to start")
    run_id = httpx.post(base + "/benchmark/start", json={"url": shop.base + "/", "goal": "Find the Iron Chain Belt"},
                        timeout=10).json()["run_id"]
    seen_browsers += wait_for(lambda: browsers_of(proc.pid), 60, "the run's Chromium")
    wait_for(lambda: model.requests, 60, "the agent's first model call")
    seen_browsers += [p for p in browsers_of(proc.pid) if p not in seen_browsers]
    return proc, run_id


def test_stopping_the_server_mid_run_stops_its_browser_and_saves_the_run(tmp_path, seen_browsers):
    with FixtureShop() as shop, SilentModelAPI() as model:
        proc, run_id = start_server_with_a_run(tmp_path, shop, model, seen_browsers)
        try:
            os.kill(proc.pid, signal.SIGTERM)
            out, _ = proc.communicate(timeout=30)
        finally:
            stop_child(proc)

    wait_for(lambda: all(not alive(p) for p in seen_browsers), 10, "the browsers to exit")
    record = json.loads((tmp_path / "runs" / f"{run_id}.json").read_text())
    assert (record["status"], record["result_state"]) == ("error", "error"), out
    assert record["message"] == "The server stopped before the run finished."
    assert leftover_temp_dirs(tmp_path) == []


def test_ctrl_c_of_the_server_mid_run_stops_its_browser(tmp_path, seen_browsers):
    """`uv run uvicorn ...` and Ctrl-C: two SIGINTs, which uvicorn takes as a forced quit
    that skips the app's shutdown. The browser must still go."""
    with FixtureShop() as shop, SilentModelAPI() as model:
        proc, run_id = start_server_with_a_run(tmp_path, shop, model, seen_browsers)
        try:
            os.kill(proc.pid, signal.SIGINT)
            time.sleep(0.2)
            os.kill(proc.pid, signal.SIGINT)
            out, _ = proc.communicate(timeout=30)
        finally:
            stop_child(proc)

    wait_for(lambda: all(not alive(p) for p in seen_browsers), 10, "the browsers to exit")
    record = json.loads((tmp_path / "runs" / f"{run_id}.json").read_text())
    assert record["status"] == "error", out
    assert leftover_temp_dirs(tmp_path) == []
