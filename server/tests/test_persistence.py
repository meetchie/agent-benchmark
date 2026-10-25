"""Tests for the local run files (persistence.py). No network, temp dirs only."""

import json
from pathlib import Path

import pytest

import persistence
from persistence import (
    persist_phases,
    persist_run_completion,
    persist_run_start,
    persist_steps,
    persist_tasks,
    read_run,
    runs_dir,
)


def _files(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


class TestRunsDir:
    def test_default_is_server_runs(self, monkeypatch):
        monkeypatch.delenv("RUNS_DIR")
        assert runs_dir() == persistence.SERVER_DIR / "runs"

    def test_env_var_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("RUNS_DIR", str(tmp_path / "elsewhere"))
        assert runs_dir() == tmp_path / "elsewhere"

    def test_relative_path_is_relative_to_the_server_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("RUNS_DIR", "my-runs")
        monkeypatch.chdir(tmp_path)
        assert runs_dir() == persistence.SERVER_DIR / "my-runs"

    def test_runs_dir_is_gitignored(self):
        ignore = (persistence.SERVER_DIR / ".gitignore").read_text().split()
        assert "/runs/" in ignore


class TestRunLifecycle:
    async def test_start_creates_the_record_and_returns_the_id(self, tmp_path):
        run_id = await persist_run_start(
            run_id="r1",
            clerk_user_id="local",
            url="https://www.Books.ToScrape.com/catalogue",
            task_label="Add a book",
            task_goal="Add any book to the basket.",
            agent_model="claude-sonnet-5-5",
        )
        assert run_id == "r1"
        record = read_run("r1")
        assert record["id"] == "r1"
        assert record["user_id"] == "local"
        assert record["site_domain"] == "books.toscrape.com"
        assert record["start_url"] == "https://www.Books.ToScrape.com/catalogue"
        assert record["task_label"] == "Add a book"
        assert record["task_goal"] == "Add any book to the basket."
        assert record["agent_type"] == "browseruse"
        assert record["agent_model"] == "claude-sonnet-5-5"
        assert record["status"] == "running"
        assert record["steps"] == [] and record["phases"] == []
        assert record["created_at"] and record["updated_at"]
        assert _files(tmp_path / "runs") == ["r1.json"]

    async def test_full_lifecycle_in_one_file(self):
        await persist_run_start("r2", "local", "https://shop.example.com", "L", "G", agent_model="m")
        await persist_steps("r2", [
            {"step": 1, "description": "Open the site", "elapsed_ms": 1200},
            {"step": 2, "description": "Add to basket", "elapsed_ms": 3400},
        ])
        await persist_run_completion(
            run_id="r2",
            status="complete",
            result_state="pass",
            success=True,
            total_ms=4600,
            input_tokens=1000,
            output_tokens=200,
            total_tokens=1200,
            estimated_cost_usd=0.004,
            summary="Added the book.",
            cache_read_tokens=300,
            cache_write_tokens=50,
        )
        await persist_phases("r2", [
            {"name": "Open", "steps": [1], "total_ms": 1200, "failed": False, "slow": False},
            {"name": "Add", "steps": [2], "total_ms": 3400, "failed": False, "slow": True},
        ])

        record = read_run("r2")
        assert record["status"] == "complete"
        assert record["result_state"] == "pass"
        assert record["success"] is True
        assert record["total_ms"] == 4600
        assert (record["input_tokens"], record["output_tokens"], record["total_tokens"]) == (1000, 200, 1200)
        assert (record["cache_read_tokens"], record["cache_write_tokens"]) == (300, 50)
        assert record["estimated_cost_usd"] == 0.004
        assert record["summary"] == "Added the book."
        assert record["steps"] == [
            {"step_number": 1, "description": "Open the site", "elapsed_ms": 1200},
            {"step_number": 2, "description": "Add to basket", "elapsed_ms": 3400},
        ]
        assert record["phases"][1] == {
            "name": "Add", "step_numbers": [2], "total_ms": 3400, "failed": False, "slow": True,
        }
        # Identity fields from the start call survive the later updates.
        assert record["task_goal"] == "G" and record["agent_model"] == "m"

    async def test_unknown_cost_is_stored_as_null(self):
        await persist_run_start("r3", "local", "https://x.example.com", "L", "G")
        await persist_run_completion("r3", "complete", "fail", False, 1, 1, 1, 2, None, "s")
        assert read_run("r3")["estimated_cost_usd"] is None

    async def test_the_agents_final_report_is_kept(self):
        await persist_run_start("r7", "local", "https://x.example.com", "L", "G")
        assert read_run("r7")["final_report"] is None
        await persist_run_completion(
            "r7", "complete", "pass", True, 1, 1, 1, 2, None, "s", final_report="Cart: 4 x Rs. 799 = Rs. 3196"
        )
        assert read_run("r7")["final_report"] == "Cart: 4 x Rs. 799 = Rs. 3196"

    async def test_error_message_is_kept(self):
        await persist_run_start("r4", "local", "https://x.example.com", "L", "G")
        await persist_run_completion(
            "r4", "error", "error", False, 1, 0, 0, 0, None, "", message="Run cancelled by user."
        )
        assert read_run("r4")["message"] == "Run cancelled by user."

    async def test_update_without_a_start_creates_a_bare_record(self):
        await persist_steps("orphan", [{"step": 1, "description": "x", "elapsed_ms": 5}])
        record = read_run("orphan")
        assert record["id"] == "orphan"
        assert record["steps"][0]["description"] == "x"

    async def test_empty_steps_and_phases_write_nothing(self, tmp_path):
        await persist_steps("r5", [])
        await persist_phases("r5", [])
        assert not (tmp_path / "runs").exists()

    async def test_no_temp_files_are_left_behind(self, tmp_path):
        await persist_run_start("r6", "local", "https://x.example.com", "L", "G")
        await persist_steps("r6", [{"step": 1, "description": "x", "elapsed_ms": 5}])
        assert _files(tmp_path / "runs") == ["r6.json"]


class TestFailuresNeverRaise:
    @pytest.mark.parametrize("bad_id", ["../escape", "a/b", "", ".hidden", "x" * 200, "with space"])
    async def test_unsafe_run_ids_are_refused(self, tmp_path, bad_id):
        assert await persist_run_start(bad_id, "local", "https://x.example.com", "L", "G") is None
        await persist_steps(bad_id, [{"step": 1, "description": "x", "elapsed_ms": 1}])
        assert not (tmp_path / "runs").exists()
        assert not (tmp_path / "escape.json").exists()

    async def test_unwritable_runs_dir_returns_none(self, monkeypatch, tmp_path):
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("a file where the directory should be")
        monkeypatch.setenv("RUNS_DIR", str(blocker / "runs"))
        assert await persist_run_start("r7", "local", "https://x.example.com", "L", "G") is None
        await persist_steps("r7", [{"step": 1, "description": "x", "elapsed_ms": 1}])  # no raise
        await persist_run_completion("r7", "complete", "pass", True, 1, 1, 1, 2, 0.1, "s")
        await persist_tasks("local", "https://x.example.com", [{"label": "a", "goal": "b"}])

    def test_corrupt_file_reads_as_none(self, tmp_path):
        directory = tmp_path / "runs"
        directory.mkdir()
        (directory / "bad.json").write_text("{not json")
        assert read_run("bad") is None
        (directory / "list.json").write_text("[1, 2]")
        assert read_run("list") is None

    def test_missing_run_reads_as_none(self):
        assert read_run("nope") is None
        assert read_run("../etc/passwd") is None


class TestTasks:
    async def test_tasks_are_appended_as_json_lines(self, tmp_path):
        tasks = [{"label": "A", "goal": "Do A."}, {"label": "B", "goal": "Do B."}]
        await persist_tasks("local", "https://www.shop.example.com/x", tasks)
        await persist_tasks("local", "https://other.example.com", [{"label": "C", "goal": "Do C."}])
        lines = (tmp_path / "runs" / persistence.TASKS_FILE).read_text().splitlines()
        rows = [json.loads(line) for line in lines]
        assert [r["label"] for r in rows] == ["A", "B", "C"]
        assert rows[0]["site_domain"] == "shop.example.com"
        assert rows[0]["user_id"] == "local"

    async def test_no_tasks_writes_nothing(self, tmp_path):
        await persist_tasks("local", "https://x.example.com", [])
        assert not (tmp_path / "runs").exists()


class TestUnfinishedRuns:
    async def test_runs_left_running_are_marked_as_errors(self, tmp_path):
        for run_id in ("run-a", "run-b", "run-c"):
            await persist_run_start(run_id, "local", "https://shop.example.com", "L", "G")
        await persist_run_completion(
            "run-b", "complete", "pass", True, 1000, 10, 5, 15, 0.01, "Done",
        )
        persistence._update("run-c", {"status": "analyzing", "total_tokens": 900})

        assert persistence.mark_unfinished_runs("The server stopped.") == 2

        a, b, c = (persistence.read_run(r) for r in ("run-a", "run-b", "run-c"))
        assert (a["status"], a["result_state"], a["message"]) == ("error", "error", "The server stopped.")
        assert (b["status"], b["result_state"]) == ("complete", "pass")  # finished runs are left alone
        assert "message" not in b
        assert (c["status"], c["total_tokens"]) == ("error", 900)  # what it had recorded stays

    def test_nothing_to_mark(self, tmp_path):
        assert persistence.mark_unfinished_runs("x") == 0  # no runs dir yet
        (tmp_path / "runs").mkdir()
        (tmp_path / "runs" / ".quota_data.json").write_text("{}")
        (tmp_path / "runs" / "broken.json").write_text("{not json")
        assert persistence.mark_unfinished_runs("x") == 0


def test_the_go_server_is_gone():
    source = Path(persistence.__file__).read_text()
    assert "GO_SERVER_URL" not in source
    assert "aiohttp" not in source
    assert "INTERNAL_API_KEY" not in source
    assert not hasattr(persistence, "_get_go_server_url")


def test_signatures_match_the_go_client():
    """Callers written against the Go client keep working."""
    import inspect

    assert list(inspect.signature(persist_run_start).parameters)[:7] == [
        "run_id", "clerk_user_id", "url", "task_label", "task_goal", "agent_type", "agent_model",
    ]
    assert list(inspect.signature(persist_run_completion).parameters)[:10] == [
        "run_id", "status", "result_state", "success", "total_ms",
        "input_tokens", "output_tokens", "total_tokens", "estimated_cost_usd", "summary",
    ]
    assert list(inspect.signature(persist_steps).parameters) == ["run_id", "steps"]
    assert list(inspect.signature(persist_phases).parameters) == ["run_id", "phases"]
    assert list(inspect.signature(persist_tasks).parameters) == ["clerk_user_id", "url", "tasks"]
