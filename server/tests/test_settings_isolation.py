"""The suite never reads a developer's .env, whenever and wherever it is loaded.

conftest.py unsets the settings before each test, but that is not enough: browser-use calls
``load_dotenv()`` when its modules are first imported, often inside a test, which puts the settings
back from the repo's .env. A test asserting a default (BENCHMARK_AGENT_MODEL) would then fail, and
so would most of the server tests with INTERNAL_API_KEY or DEMO_MODE set.
"""

import os
import runpy
import subprocess
import sys

import llm

DEFAULT_AGENT_MODEL = "claude-sonnet-5-5"


def library_that_loads_dotenv(tmp_path):
    """A stand-in for a browser-use module: it calls load_dotenv() when it is imported,
    which looks for a .env from the module's own folder upwards."""
    (tmp_path / ".env").write_text("BENCHMARK_AGENT_MODEL=claude-haiku-5-5\n")
    package = tmp_path / "site-packages" / "somelib"
    package.mkdir(parents=True)
    module = package / "config.py"
    module.write_text(
        "import os\n"
        "from dotenv import load_dotenv\n\n"
        "load_dotenv()\n\n"
        "if __name__ == '__main__':\n"
        "    print(os.environ.get('BENCHMARK_AGENT_MODEL'))\n"
    )
    return module


def test_a_library_loading_dotenv_inside_a_test_changes_no_setting(tmp_path):
    try:
        runpy.run_path(str(library_that_loads_dotenv(tmp_path)))
        loaded = os.environ.get("BENCHMARK_AGENT_MODEL")  # a bare os.environ in the assert would print every variable
        assert loaded is None
        assert llm.model_for("agent") == DEFAULT_AGENT_MODEL
    finally:
        os.environ.pop("BENCHMARK_AGENT_MODEL", None)


def test_a_process_a_test_starts_reads_no_dotenv_either(tmp_path):
    module = library_that_loads_dotenv(tmp_path)
    out = subprocess.run([sys.executable, str(module)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "None"

