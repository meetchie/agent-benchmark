"""The tests that drive a real Chromium are skipped, saying why, when it cannot start.

A Chromium can be installed and still unable to start (on Linux without its system libraries it
exits at once). This runs those modules against a Chromium that cannot start and checks that each
skips its browser tests and fails none, so the whole suite on such a machine says what is missing
instead of failing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SERVER_DIR = TESTS_DIR.parent


def real_browser_modules() -> list[str]:
    """The test modules that drive a real Chromium: each one does it on the fixture shop."""
    this = Path(__file__).name
    return sorted(p.name for p in TESTS_DIR.glob("test_*.py") if p.name != this and "FixtureShop()" in p.read_text())


def test_the_rule_finds_the_modules_that_start_a_browser():
    found = real_browser_modules()
    assert {"test_interrupts.py", "test_rindler_local.py"} <= set(found)
    assert Path(__file__).name not in found


def test_with_a_chromium_that_cannot_start_the_browser_tests_skip_and_none_fails(tmp_path):
    chrome = tmp_path / "chrome"
    chrome.write_text('#!/bin/sh\necho "$0: error while loading shared libraries: libnspr4.so: '
                      'cannot open shared object file: No such file or directory" >&2\nexit 127\n')
    chrome.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["BENCHMARK_CHROMIUM_PATH"] = str(chrome)
    modules = real_browser_modules()

    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--basetemp={tmp_path / 'inner'}",
         *(f"tests/{name}" for name in modules)],
        cwd=SERVER_DIR, env=env, capture_output=True, text=True, timeout=240,
    )

    out = done.stdout + done.stderr
    assert done.returncode == 0, out
    summary = out.strip().splitlines()[-1]
    assert "skipped" in summary and "failed" not in summary and "error" not in summary, out
    for name in modules:
        reasons = [line for line in out.splitlines() if line.startswith("SKIPPED") and f"tests/{name}:" in line]
        assert reasons, f"nothing in {name} was skipped:\n{out}"
        assert all("no Chromium that starts" in line and "libnspr4.so" in line for line in reasons), out
