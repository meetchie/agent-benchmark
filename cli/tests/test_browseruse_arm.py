"""The BrowserUse arm with a fake browser-use Agent (no browser, no network)."""

import asyncio
import base64

import pytest

import browser_env
import llm
from benchcli import browseruse_arm, sites
from cli_helpers import TASK

PNG = b"\x89PNG\r\n\x1a\n" + b"fake image bytes"


class FakeSummary:
    def __init__(self, prompt=0, cached=0, completion=0):
        self.total_prompt_tokens = prompt
        self.total_prompt_cached_tokens = cached
        self.total_prompt_cache_creation_tokens = 0
        self.total_completion_tokens = completion


class FakeHistory:
    def __init__(self, done=True, success=True, final="Cart: Hair Towel x1 $35.00"):
        self.actions = []
        self.done, self.success, self.final = done, success, final

    def model_actions(self):
        return self.actions

    def extracted_content(self):
        return [f"page text {len(self.actions)}"] if self.actions else []

    def is_done(self):
        return self.done

    def is_successful(self):
        return self.success if self.done else None

    def final_result(self):
        return self.final if self.done else None

    def screenshots(self, n_last=None, return_none_if_not_screenshot=True):
        return [base64.b64encode(PNG).decode()]


class FakeAgent:
    """Calls the step hooks the way browser-use does and grows a token counter."""

    instances = []
    steps = 3
    done = True
    success = True
    after_last_step = (0, 0, 0)  # tokens used after the last on_step_end (the end-of-run judge call etc.)
    raise_after = None
    hang = False

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.history = FakeHistory(done=self.done, success=self.success)
        self.usage = FakeSummary()
        self.token_cost_service = self
        FakeAgent.instances.append(self)

    async def get_usage_summary(self):
        return self.usage

    async def run(self, max_steps, on_step_start, on_step_end):
        self.max_steps = max_steps
        for i in range(min(self.steps, max_steps)):
            await on_step_start(self)
            self.history.actions.append({["navigate", "click", "done"][i % 3]: {"index": i}, "interacted_element": object()})
            u = self.usage
            self.usage = FakeSummary(u.total_prompt_tokens + 1000, u.total_prompt_cached_tokens + 400,
                                     u.total_completion_tokens + 100)
            await on_step_end(self)
            if self.raise_after == i + 1:
                raise RuntimeError("browser died")
            if self.hang and i == 0:
                await asyncio.sleep(30)
        p, c, o = self.after_last_step
        u = self.usage
        self.usage = FakeSummary(u.total_prompt_tokens + p, u.total_prompt_cached_tokens + c, u.total_completion_tokens + o)
        return self.history


@pytest.fixture(autouse=True)
def fake_browser(monkeypatch):
    cleaned = []
    FakeAgent.instances.clear()
    for name, value in dict(steps=3, done=True, success=True, after_last_step=(0, 0, 0), raise_after=None, hang=False).items():
        setattr(FakeAgent, name, value)
    monkeypatch.setattr(browser_env, "browser_profile", lambda **kw: object())
    monkeypatch.setattr(browser_env, "agent_files_dir", lambda profile: "/nonexistent/agent-files")
    monkeypatch.setattr(browser_env, "cleanup_profile", lambda profile: cleaned.append(profile))
    monkeypatch.setattr(llm, "agent_llm", lambda model=None, **kw: f"chat:{model}")
    return cleaned


def run(tmp_path, **kw):
    params = dict(model="claude-sonnet-5-5", max_steps=12, results_dir=tmp_path, site="prose", timeout_s=None,
                  agent_factory=lambda **k: FakeAgent(**k))
    params.update(kw)
    return browseruse_arm.run_browseruse_task(TASK, **params)


async def test_agent_is_built_like_the_arena_arm_and_gets_the_goal_verbatim(tmp_path, fake_browser):
    record = await run(tmp_path)
    kwargs = FakeAgent.instances[0].kwargs
    assert kwargs["task"] == TASK["goal"]  # no wrapper, no extra instructions
    assert kwargs["llm"] == "chat:claude-sonnet-5-5"
    assert kwargs["initial_actions"] == [{"navigate": {"url": TASK["start_url"], "new_tab": False}}]
    assert kwargs["use_judge"] is False and kwargs["calculate_cost"] is False
    # browser-use's own Ctrl-C handler would os._exit() on a second SIGINT, leaving Chromium up.
    assert kwargs["enable_signal_handler"] is False
    assert kwargs["file_system_path"] == "/nonexistent/agent-files"
    assert FakeAgent.instances[0].max_steps == 12 == record["meta"]["max_steps"]
    assert len(fake_browser) == 1  # the throwaway profile was cleaned up


async def test_the_goal_text_contains_no_rindler_tool_names():
    """The same check run.py makes before starting: the shipped goals are safe to hand over verbatim."""
    for name in ("prose", "prose-hard"):
        site = sites.load_site(name)
        assert sites.task_text_leaks(site.tasks, site.mapping) == {}


async def test_success_and_final_report_come_from_browser_use_itself(tmp_path):
    record = await run(tmp_path)
    assert record["result"]["success"] is True
    assert record["result"]["final_report"] == "Cart: Hair Towel x1 $35.00"
    assert record["error"] is None and record["failure_screenshots"] == []
    assert [s["action"] for s in record["steps"]] == ["navigate", "click", "done"]
    assert [s["step"] for s in record["steps"]] == [1, 2, 3]
    assert record["steps"][0]["observation"] == "page text 1"
    assert record["steps"][0]["action_args"] == {"navigate": {"index": 0}}  # the element object is dropped
    assert record["meta"]["agent"] == "browseruse"


async def test_per_step_tokens_are_the_counter_deltas_and_add_up(tmp_path):
    record = await run(tmp_path)
    per_step = llm.Usage(input_tokens=600, output_tokens=100, cache_read_input_tokens=400).cost_usd("claude-sonnet-5-5")
    for step in record["steps"]:
        # browser-use's prompt total includes cache reads: 1000 prompt = 600 fresh + 400 cached
        assert (step["tokens_input"], step["tokens_output"], step["tokens_cache_read"]) == (1000, 100, 400)
        assert step["cost_usd"] == pytest.approx(per_step, abs=1e-6)
    assert record["stats"]["total_tokens_input"] == 3000 and record["stats"]["total_tokens_output"] == 300
    assert record["stats"]["total_cost_usd"] == pytest.approx(3 * per_step, abs=1e-5)


async def test_tokens_spent_after_the_last_step_are_not_lost(tmp_path):
    FakeAgent.after_last_step = (500, 0, 50)
    record = await run(tmp_path)
    assert record["steps"][-1]["tokens_input"] == 1500 and record["steps"][-1]["tokens_output"] == 150
    assert record["stats"]["total_tokens_input"] == 3500
    total = llm.Usage(input_tokens=3500 - 1200, output_tokens=350, cache_read_input_tokens=1200).cost_usd("claude-sonnet-5-5")
    assert record["stats"]["total_cost_usd"] == pytest.approx(total, abs=1e-5)


async def test_a_run_that_ends_without_done_reports_the_budget_and_keeps_a_screenshot(tmp_path):
    FakeAgent.steps, FakeAgent.done = 5, False
    record = await run(tmp_path, max_steps=2)
    assert FakeAgent.instances[0].max_steps == 2 and record["stats"]["total_steps"] == 2
    assert record["result"]["success"] is False and record["result"]["final_report"] is None
    assert record["error"] == "did not finish within 2 steps"
    shot = tmp_path / "browseruse" / record["failure_screenshots"][0]
    assert shot.read_bytes() == PNG and shot.suffix == ".png"
    assert record["steps"][-1]["screenshot_path"] == record["failure_screenshots"][0]


async def test_done_with_a_failure_report_is_not_an_error(tmp_path):
    FakeAgent.success = False
    record = await run(tmp_path)
    assert record["result"]["success"] is False and record["error"] is None
    assert record["result"]["final_report"] == "Cart: Hair Towel x1 $35.00"


async def test_a_crash_keeps_the_steps_and_tokens_so_far(tmp_path, fake_browser):
    FakeAgent.raise_after = 2
    record = await run(tmp_path)
    assert record["error"] == "RuntimeError: browser died"
    assert record["stats"]["total_steps"] == 2 and record["stats"]["total_tokens_input"] == 2000
    assert record["result"]["success"] is False and len(fake_browser) == 1


async def test_the_time_limit_stops_the_run(tmp_path, fake_browser):
    FakeAgent.hang = True
    record = await run(tmp_path, timeout_s=1)
    assert record["error"] == "stopped after the 1s time limit"
    assert record["stats"]["total_steps"] == 1 and len(fake_browser) == 1
    assert record["result"]["success"] is False


async def test_a_model_configuration_error_is_a_failed_run_not_a_crash(tmp_path, monkeypatch, fake_browser):
    def broken(model=None, **kw):
        raise llm.LLMError("LLM_PROVIDER='bogus' is not supported", kind="config")

    monkeypatch.setattr(llm, "agent_llm", broken)
    record = await run(tmp_path)
    assert record["error"].startswith("LLMError: LLM_PROVIDER='bogus'")
    assert record["stats"]["total_steps"] == 0 and len(fake_browser) == 1


async def test_ctrl_c_during_a_run_still_cleans_up(tmp_path, fake_browser):
    """Ctrl-C cancels the run (entrypoint.run_cli); the browser and dirs still go."""
    FakeAgent.hang = True
    task = asyncio.create_task(run(tmp_path))
    while not FakeAgent.instances or not FakeAgent.instances[0].history.actions:
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(fake_browser) == 1


async def test_the_failure_screenshot_is_saved_before_the_agent_dir_is_removed(tmp_path, monkeypatch):
    """browser-use keeps its screenshots as files in the agent's dir, which cleanup removes."""
    FakeAgent.steps, FakeAgent.done = 2, False
    at_cleanup = []
    monkeypatch.setattr(browser_env, "cleanup_profile",
                        lambda profile: at_cleanup.append(sorted(p.name for p in tmp_path.rglob("*.png"))))
    record = await run(tmp_path)
    assert at_cleanup == [[record["failure_screenshots"][0].split("/")[-1]]]


async def test_a_successful_run_saves_no_screenshot(tmp_path):
    record = await run(tmp_path)
    assert record["failure_screenshots"] == [] and not list(tmp_path.rglob("*.png"))
