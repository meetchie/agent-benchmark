"""The CLI tests never read a developer's .env, even when a library loads it mid-test.

browser-use calls ``load_dotenv()`` when its modules are first imported, which for the
arms happens inside a test, after conftest.py has unset the settings.
"""

import os
import runpy
import subprocess
import sys

import llm


def library_that_loads_dotenv(tmp_path):
    """Like a browser-use module: load_dotenv() on import finds a .env above the module."""
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
        assert llm.model_for("agent") == "claude-sonnet-5-5"
    finally:
        os.environ.pop("BENCHMARK_AGENT_MODEL", None)


def test_a_process_a_test_starts_reads_no_dotenv_either(tmp_path):
    module = library_that_loads_dotenv(tmp_path)
    out = subprocess.run([sys.executable, str(module)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "None"
