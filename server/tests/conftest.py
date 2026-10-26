"""Test isolation shared by every test module.

No test may read a developer's .env settings, write into the real ``server/runs/``
directory, or reach a real model API.

.env loading is off for the whole test process and every process a test starts
(``PYTHON_DOTENV_DISABLED``, set before ``llm`` imports runtime_env). Unsetting the
settings before each test is not enough on its own: browser-use calls ``load_dotenv()``
when its modules are first imported, often inside a test, and that would fill them in
again from the repo's .env.

This fixture runs before each test:

* the server and model settings the tests care about are unset (a test that wants
  one sets it with ``monkeypatch.setenv``),
* ``RUNS_DIR`` points at a fresh temp dir,
* both SDK base URLs point at a closed local port, so a call that slips past a fake
  fails at once with a connection error instead of spending money.
"""

import os

import pytest

os.environ["PYTHON_DOTENV_DISABLED"] = "1"

import llm  # noqa: E402  (after the line above: importing llm loads .env through runtime_env)

_SETTINGS = (
    "AUTH_MODE",
    "DAILY_RUN_QUOTA",
    "MAX_CONCURRENT_RUNS",
    "DEMO_MODE",
    "BENCHMARK_TIMEOUT_S",
    "LLM_PROVIDER",
    "LLM_FALLBACKS",
    *llm.ROLE_MODEL_ENV.values(),
    *llm.ROLE_EFFORT_ENV.values(),
)

DEAD_URL = "http://127.0.0.1:9"


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    for name in _SETTINGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("ANTHROPIC_BASE_URL", DEAD_URL)
    monkeypatch.setenv("OPENAI_BASE_URL", DEAD_URL)
