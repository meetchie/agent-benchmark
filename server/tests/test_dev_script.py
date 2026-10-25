"""scripts/dev.sh (make dev): what it starts, it stops, including a browser whose parent died.

The script runs for real, with stand-ins for uv (a tiny backend that starts a "browser"
child and, like a server killed mid-run, exits without stopping it) and for Vite. They
are small Python programs on 127.0.0.1; no real server, browser or network is used.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

REPO = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(not shutil.which("curl") or not shutil.which("bash"), reason="dev.sh needs bash and curl")

# Stand-in for `uv run uvicorn ... --port N`: answers /health on port N, starts a
# "browser" child, records the signals it gets, and on SIGTERM or SIGINT exits at once
# without stopping the child.
FAKE_UV = """#!{python}
import http.server, os, signal, subprocess, sys, threading
state = os.environ["FAKE_STATE"]
port = int(sys.argv[sys.argv.index("--port") + 1])
browser = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", "--user-data-dir=/tmp/fake"])
open(os.path.join(state, "browser.pid"), "w").write(str(browser.pid))
open(os.path.join(state, "backend.pid"), "w").write(str(os.getpid()))

def on_signal(signum, frame):
    with open(os.path.join(state, "signals"), "a") as f:
        f.write(signal.Signals(signum).name + "\\n")
    os._exit(0)

signal.signal(signal.SIGTERM, on_signal)
signal.signal(signal.SIGINT, on_signal)

class Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{{"ok": true}}')
    def log_message(self, *args):
        pass

http.server.HTTPServer(("127.0.0.1", port), Health).serve_forever()
"""

# Stand-in for Vite: serves / on BENCHMARK_WEB_PORT.
FAKE_VITE = """#!{python}
import http.server, os
port = int(os.environ["BENCHMARK_WEB_PORT"])

class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<html></html>")
    def log_message(self, *args):
        pass

http.server.HTTPServer(("127.0.0.1", port), Page).serve_forever()
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def wait_for(condition, timeout, what):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")


@pytest.fixture
def checkout(tmp_path):
    """A copy of dev.sh in a minimal checkout, stand-ins installed, plus a cleanup of
    anything the stand-ins started (by PID) in case a test fails half way."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "dev.sh", root / "scripts" / "dev.sh")
    (root / "server").mkdir()
    executable(root / "web" / "node_modules" / ".bin" / "vite", FAKE_VITE)
    executable(tmp_path / "bin" / "uv", FAKE_UV)
    state = tmp_path / "state"
    state.mkdir()
    api_port, web_port = free_port(), free_port()
    env = {
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(tmp_path),
        "FAKE_STATE": str(state),
        "BENCHMARK_API_URL": f"http://127.0.0.1:{api_port}",
        "BENCHMARK_WEB_PORT": str(web_port),
    }
    started: list[subprocess.Popen] = []

    def start():
        proc = subprocess.Popen(["bash", str(root / "scripts" / "dev.sh")], env=env, cwd=root,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                start_new_session=True)  # its own group, like a terminal's foreground job
        started.append(proc)
        return proc

    yield start, state, env
    for name in ("browser.pid", "backend.pid"):
        f = state / name
        if f.exists() and alive(int(f.read_text())):
            os.kill(int(f.read_text()), signal.SIGKILL)
    for proc in started:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=10)


def wait_until_ready(proc, state):
    lines = []
    for line in proc.stdout:
        lines.append(line)
        if "Press Ctrl-C to stop." in line:
            return int((state / "browser.pid").read_text())
    raise AssertionError("dev.sh did not start: " + "".join(lines))


def test_ctrl_c_stops_both_servers_and_the_browser_the_backend_left(checkout):
    start, state, _ = checkout
    proc = start()
    browser = wait_until_ready(proc, state)
    assert alive(browser)

    os.killpg(proc.pid, signal.SIGINT)  # what Ctrl-C in the terminal does
    proc.communicate(timeout=40)

    # The backend got one TERM from dev.sh, not the terminal's SIGINT.
    assert (state / "signals").read_text().split() == ["SIGTERM"]
    wait_for(lambda: not alive(browser), 10, "the orphaned browser to be stopped")


def test_a_backend_that_dies_takes_its_browser_with_it(checkout):
    start, state, _ = checkout
    proc = start()
    browser = wait_until_ready(proc, state)

    os.kill(int((state / "backend.pid").read_text()), signal.SIGKILL)  # the backend crashes mid-run
    out, _ = proc.communicate(timeout=40)

    assert proc.returncode != 0
    assert "a server exited unexpectedly" in out
    wait_for(lambda: not alive(browser), 10, "the orphaned browser to be stopped")


@pytest.mark.parametrize("name, value, words", [
    ("BENCHMARK_WEB_PORT", "99999", "BENCHMARK_WEB_PORT=99999 is not a port number"),
    ("BENCHMARK_WEB_PORT", "0", "BENCHMARK_WEB_PORT=0 is not a port number"),
    ("BENCHMARK_API_URL", "http://127.0.0.1:70000", "has no usable port"),
])
def test_a_port_out_of_range_is_refused_before_anything_starts(checkout, name, value, words):
    start, state, env = checkout
    env[name] = value
    proc = start()
    out, _ = proc.communicate(timeout=20)
    assert proc.returncode == 1
    assert words in out
    assert not (state / "backend.pid").exists()
