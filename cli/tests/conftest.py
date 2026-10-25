"""Test isolation for the CLI tests.

Run them from the repo with the server project's environment:

    uv run --project server pytest cli

No test may read a developer's settings, write into the real cli/results/, or reach a
model API: both SDK base URLs point at a closed local port, so a call that slips past a
fake fails at once with a connection error instead of spending money.
"""

import sys
from pathlib import Path

import pytest

CLI_DIR = Path(__file__).resolve().parent.parent
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))

import llm  # noqa: E402  (server/ is importable through the editable install)

_SETTINGS = (
    "LLM_PROVIDER",
    "LLM_FALLBACKS",
    "BENCHMARK_HEADLESS",
    *llm.ROLE_MODEL_ENV.values(),
    *llm.ROLE_EFFORT_ENV.values(),
)

DEAD_URL = "http://127.0.0.1:9"


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    for name in _SETTINGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", DEAD_URL)
    monkeypatch.setenv("OPENAI_BASE_URL", DEAD_URL)
