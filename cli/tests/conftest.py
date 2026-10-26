"""Test isolation for the CLI tests.

Run them from the repo with the server project's environment:

    uv run --project server pytest cli

No test may read a developer's settings, write into the real cli/results/, or reach a
model API: both SDK base URLs point at a closed local port, so a call that slips past a
fake fails at once with a connection error instead of spending money.

.env loading is off for the whole test process and every process a test starts
(``PYTHON_DOTENV_DISABLED``, set before ``llm`` imports runtime_env): browser-use calls
``load_dotenv()`` when its modules are first imported, often inside a test, and that
would put back the settings unset below from the repo's .env.
"""

import os
import sys
from pathlib import Path

import pytest

os.environ["PYTHON_DOTENV_DISABLED"] = "1"

CLI_DIR = Path(__file__).resolve().parent.parent
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))

import llm  # noqa: E402  (server/ is importable through the editable install; loads .env through runtime_env)

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
