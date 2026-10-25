"""entrypoint.run_cli: Ctrl-C cancels the program once and lets its cleanup finish."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]

# A program whose cleanup takes a while (like closing a browser) and leaves a marker.
PROGRAM = """
import asyncio, sys
import entrypoint

async def main():
    try:
        print("ready", flush=True)
        await asyncio.sleep(30)
        return 0
    finally:
        await asyncio.sleep(float(sys.argv[2]))
        open(sys.argv[1], "w").write("cleaned up")

sys.exit(entrypoint.run_cli(main()))
"""


def start(tmp_path, cleanup_s):
    script = tmp_path / "program.py"
    script.write_text(PROGRAM)
    marker = tmp_path / "marker"
    proc = subprocess.Popen(
        [sys.executable, str(script), str(marker), str(cleanup_s)],
        cwd=SERVER_DIR, env={**os.environ, "PYTHONPATH": str(SERVER_DIR)},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
    )
    assert proc.stdout.readline().strip() == "ready"
    return proc, marker


def finish(proc, timeout=15):
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        pytest.fail(f"did not exit: {err}")
    return out, err


def test_one_ctrl_c_under_uv_run_cancels_once_and_the_cleanup_finishes(tmp_path):
    """`uv run` forwards its own copy of the terminal's SIGINT: two arrive, 0.2 s apart."""
    proc, marker = start(tmp_path, cleanup_s=0.8)
    os.kill(proc.pid, signal.SIGINT)
    time.sleep(0.2)
    os.kill(proc.pid, signal.SIGINT)
    _, err = finish(proc)
    assert proc.returncode == 130
    assert marker.read_text() == "cleaned up"  # the second SIGINT did not cut the cleanup short
    assert "Stopping" in err and "Traceback" not in err


def test_the_forwarded_copy_is_ignored_even_after_a_quick_cleanup(tmp_path):
    """The cleanup can be over before uv's copy of the SIGINT arrives."""
    proc, marker = start(tmp_path, cleanup_s=0)
    os.kill(proc.pid, signal.SIGINT)
    time.sleep(0.3)  # the program has finished its cleanup by now
    os.kill(proc.pid, signal.SIGINT)
    _, err = finish(proc)
    assert proc.returncode == 130, err
    assert marker.exists() and "Traceback" not in err


def test_sigterm_is_handled_like_ctrl_c(tmp_path):
    proc, marker = start(tmp_path, cleanup_s=0.2)
    os.kill(proc.pid, signal.SIGTERM)
    finish(proc)
    assert proc.returncode == 130 and marker.exists()


def test_a_later_ctrl_c_quits_at_once(tmp_path):
    proc, marker = start(tmp_path, cleanup_s=20)
    os.kill(proc.pid, signal.SIGINT)
    time.sleep(1.5)  # past the window for a forwarded copy: the user pressed it again
    started = time.monotonic()
    os.kill(proc.pid, signal.SIGINT)
    _, err = finish(proc)
    assert time.monotonic() - started < 5
    assert proc.returncode == 130 and not marker.exists()
    assert "Quitting now" in err


def test_the_programs_own_exit_status_passes_through(tmp_path):
    script = tmp_path / "ok.py"
    script.write_text("import sys, entrypoint\nasync def main():\n    return 3\nsys.exit(entrypoint.run_cli(main()))\n")
    done = subprocess.run([sys.executable, str(script)], cwd=SERVER_DIR, env={**os.environ, "PYTHONPATH": str(SERVER_DIR)},
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 3, done.stderr
