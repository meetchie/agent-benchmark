"""The live preview with a real headless Chromium, on the local fixture shop.

The model API here accepts the agent's request and never answers, so the agent sits in its first
model turn. Nothing leaves 127.0.0.1 and no model is billed. Every browser the test saw is killed by
PID at the end whatever happens.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import httpx
import pytest

from tests.fixture_shop import FixtureShop
from tests.test_interrupts import (
    _NO_CHROMIUM,
    SERVER_DIR,
    SERVER_LAUNCHER,
    SilentModelAPI,
    alive,
    browsers_of,
    child_env,
    free_port,
    stop_child,
    wait_for,
)

pytestmark = pytest.mark.skipif(_NO_CHROMIUM is not None, reason=f"no Chromium that starts: {_NO_CHROMIUM}")


def jpeg_size(data: bytes) -> tuple[int, int]:
    """(width, height) from a JPEG's start-of-frame segment."""
    assert data[:2] == b"\xff\xd8", "not a JPEG"
    i = 2
    while i < len(data):
        marker, length = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + length
    raise AssertionError("no start-of-frame segment")


def test_the_preview_shows_the_site_while_the_model_is_still_deciding_step_one(tmp_path):
    browsers: list[int] = []
    log_path = tmp_path / "server.log"
    with FixtureShop() as shop, SilentModelAPI() as model, open(log_path, "w") as log:
        port = free_port()
        launcher = tmp_path / "launch_server.py"
        launcher.write_text(SERVER_LAUNCHER)
        proc = subprocess.Popen(
            [sys.executable, str(launcher), str(port), str(SERVER_DIR)], cwd=SERVER_DIR,
            env=child_env(tmp_path, model.url), stdout=log, stderr=subprocess.STDOUT, text=True,
            start_new_session=True,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            def healthy():
                try:
                    return httpx.get(base + "/health", timeout=1).status_code == 200
                except httpx.HTTPError:
                    return proc.poll() is not None and pytest.fail(log_path.read_text())

            wait_for(healthy, 60, "the server to start")
            started = httpx.post(base + "/benchmark/start", timeout=10, json={
                "url": shop.base + "/", "goal": "Find the Iron Chain Belt",
                "viewport_width": 1339, "viewport_height": 460,  # a short preview pane
            })
            assert started.status_code == 200, started.text
            run_id = started.json()["run_id"]

            phases: list[str] = []

            def deciding_with_a_frame():
                browsers.extend(p for p in browsers_of(proc.pid) if p not in browsers)
                body = httpx.get(f"{base}/benchmark/status/{run_id}", timeout=5).json()
                name = (body.get("run_phase") or {}).get("name")
                if name and (not phases or phases[-1] != name):
                    phases.append(name)
                if body["run_phase"] == {"name": "deciding", "step": 1} and body["frame"] and model.requests:
                    return body
                return None

            body = wait_for(deciding_with_a_frame, 90, "a frame while the model decides step 1")
            assert body["status"] == "running" and body["steps"] == []
            assert phases[-1] == "deciding"
            assert phases == [p for p in ("starting_browser", "opening_site", "deciding") if p in phases]

            frame = httpx.get(f"{base}/benchmark/frame/{run_id}", timeout=5)
            assert frame.status_code == 200
            assert frame.headers["content-type"] == "image/jpeg"
            assert jpeg_size(frame.content) == (1339, 753)  # fit_viewport of the pane, whole
            assert int(frame.headers["x-frame-seq"]) >= body["frame"]["seq"]

            # The model still has not answered: the agent never moved past step 1.
            time.sleep(1.5)
            later = httpx.get(f"{base}/benchmark/status/{run_id}", timeout=5).json()
            assert later["run_phase"] == {"name": "deciding", "step": 1} and later["steps"] == []

            assert httpx.post(f"{base}/benchmark/cancel/{run_id}", timeout=30).json() == {"ok": True}
            ended = httpx.get(f"{base}/benchmark/status/{run_id}", timeout=5).json()
            assert ended["status"] == "error" and "run_phase" not in ended
            assert ended["frame"] is not None  # the last picture stays with the run
            assert httpx.get(f"{base}/benchmark/frame/{run_id}", timeout=5).status_code == 200
            wait_for(lambda: all(not alive(p) for p in browsers), 15, "the browser to exit")

            os.kill(proc.pid, signal.SIGTERM)
            proc.wait(timeout=30)
        finally:
            stop_child(proc)
            for pid in browsers:
                if alive(pid):
                    os.kill(pid, signal.SIGKILL)

    out = log_path.read_text()
    assert browsers, "the run never started a browser"
    assert "Traceback" not in out, out
    assert "stale focused target" not in out, out  # the preview never set off browser-use's focus recovery
    assert "Live preview callback failed" not in out, out
