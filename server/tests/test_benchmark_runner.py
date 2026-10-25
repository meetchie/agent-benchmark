import os

import pytest
from benchmark_runner import StepRecord, RunState


def make_step(n: int, has_screenshot: bool = True) -> StepRecord:
    return StepRecord(
        step=n,
        description=f"Step {n}",
        elapsed_ms=500,
        screenshot_b64="data:image/jpeg;base64,abc" if has_screenshot else None,
    )


def test_running_response_omits_screenshots_except_latest():
    state = RunState(run_id="test-1")
    state.steps = [make_step(1), make_step(2), make_step(3)]

    resp = state.to_response()

    assert resp["status"] == "running"
    assert len(resp["steps"]) == 3
    # Only last step has screenshot
    assert "screenshot_b64" not in resp["steps"][0]
    assert "screenshot_b64" not in resp["steps"][1]
    assert "screenshot_b64" in resp["steps"][2]


def test_complete_response_includes_summary():
    state = RunState(run_id="test-2", status="complete", success=True,
                     summary="Added item to cart.", total_ms=12000)
    state.steps = [make_step(1)]

    resp = state.to_response()

    assert resp["status"] == "complete"
    assert resp["success"] is True
    assert resp["summary"] == "Added item to cart."
    assert resp["total_ms"] == 12000


def test_error_response():
    state = RunState(run_id="test-3", status="error", message="Container error")
    resp = state.to_response()
    assert resp["status"] == "error"
    assert resp["message"] == "Container error"


def test_complete_response_with_failure():
    state = RunState(run_id="test-4", status="complete", success=False,
                     summary="Agent did not complete the task.", total_ms=5000)
    state.steps = [make_step(1)]
    resp = state.to_response()
    assert resp["status"] == "complete"
    assert resp["success"] is False
    assert "Agent did not complete" in resp["summary"]


# ---------------------------------------------------------------------------
# Status payload: cost_usd and agent_model
# ---------------------------------------------------------------------------

import asyncio
from types import SimpleNamespace

import browser_env
import browser_use
import llm
import persistence
from benchmark_runner import _format_action, get_agent_timeout, run_benchmark
from constants import COST_RATES
from tests.fakes import install_fake_anthropic, text_response


def usage_summary(prompt=57696, cached=43599, completion=987, cache_write=14533):
    """What browser-use reports. total_prompt_tokens includes the cache reads."""
    return SimpleNamespace(
        total_prompt_tokens=prompt,
        total_prompt_cached_tokens=cached,
        total_completion_tokens=completion,
        total_prompt_cache_creation_tokens=cache_write,
        total_tokens=prompt + completion,
    )


def expected_sonnet_cost(uncached, completion, cache_read, cache_write):
    rates = COST_RATES["claude-sonnet-5-5"]
    return (
        uncached * rates["input"]
        + completion * rates["output"]
        + cache_read * rates["cache_read"]
        + cache_write * rates["cache_write"]
    ) / 1_000_000


def test_default_agent_model_is_sonnet_5_5():
    assert RunState(run_id="m").agent_model == "claude-sonnet-5-5"


def test_agent_model_follows_the_environment(monkeypatch):
    monkeypatch.setenv("BENCHMARK_AGENT_MODEL", "claude-haiku-5-5")
    assert RunState(run_id="m").agent_model == "claude-haiku-5-5"


def test_record_usage_prices_tokens_at_the_agent_models_rates():
    state = RunState(run_id="u1")
    state.record_usage(usage_summary())

    # input_tokens keeps browser-use's meaning (the prompt total includes cache reads);
    # total_tokens counts everything billed, the 14533 cache-write tokens included.
    assert (state.input_tokens, state.output_tokens, state.total_tokens) == (57696, 987, 73216)
    assert (state.cache_read_tokens, state.cache_write_tokens) == (43599, 14533)
    # 14097 uncached + 43599 cache-read + 14533 cache-write input, 987 output.
    assert state.cost_usd == pytest.approx(expected_sonnet_cost(14097, 987, 43599, 14533))
    assert state.cost_usd == pytest.approx(0.0831, abs=5e-5)


def test_record_usage_uses_the_rates_of_whatever_model_the_agent_runs_on():
    state = RunState(run_id="u2", agent_model="claude-opus-5-5")
    state.record_usage(SimpleNamespace(
        total_prompt_tokens=1_000_000, total_prompt_cached_tokens=0,
        total_completion_tokens=1_000_000, total_prompt_cache_creation_tokens=0, total_tokens=2_000_000,
    ))
    assert state.cost_usd == pytest.approx(4.00 + 20.00)


def test_record_usage_for_an_unpriced_model_leaves_cost_unknown():
    state = RunState(run_id="u3", agent_model="some-future-model")
    state.record_usage(usage_summary())
    assert state.cost_usd is None
    assert state.total_tokens == 73216  # tokens are still reported


def test_record_usage_without_a_summary_changes_nothing():
    state = RunState(run_id="u4")
    state.record_usage(None)
    assert (state.input_tokens, state.cost_usd) == (0, None)


def test_record_usage_tolerates_missing_cache_fields():
    state = RunState(run_id="u5")
    state.record_usage(SimpleNamespace(
        total_prompt_tokens=1000, total_completion_tokens=500, total_tokens=1500,
    ))
    assert state.cost_usd == pytest.approx((1000 * 2.0 + 500 * 10.0) / 1_000_000)


def test_total_tokens_counts_every_billed_token():
    state = RunState(run_id="u6")
    state.record_usage(usage_summary(prompt=1000, cached=600, completion=50, cache_write=300))
    assert state.input_tokens == 1000  # prompt tokens, cache reads included
    assert state.output_tokens == 50
    assert state.cache_read_tokens == 600 and state.cache_write_tokens == 300
    # uncached 400 + cache reads 600 + cache writes 300 + output 50
    assert state.total_tokens == 400 + 600 + 300 + 50
    assert state.total_tokens == state.input_tokens + state.cache_write_tokens + state.output_tokens


def test_total_tokens_ignores_browser_uses_own_total():
    """browser-use's total_tokens leaves the cache writes out; ours must not copy it."""
    summary = usage_summary(prompt=1000, cached=0, completion=50, cache_write=300)
    summary.total_tokens = 1050
    state = RunState(run_id="u7")
    state.record_usage(summary)
    assert state.total_tokens == 1350


def test_complete_status_carries_cost_usd_and_agent_model():
    state = RunState(run_id="c1", status="complete", success=True, summary="ok", total_ms=900,
                     input_tokens=100, output_tokens=20, total_tokens=120, cost_usd=0.0004)
    resp = state.to_dict()
    assert resp["cost_usd"] == 0.0004
    assert resp["agent_model"] == "claude-sonnet-5-5"
    # Every pre-existing field keeps its name and meaning.
    assert {"status", "steps", "success", "summary", "result_state", "total_ms",
            "input_tokens", "output_tokens", "total_tokens", "phases"} <= set(resp)
    assert resp["input_tokens"] == 100 and resp["output_tokens"] == 20 and resp["total_tokens"] == 120


def test_analyzing_status_carries_cost_usd_and_agent_model():
    state = RunState(run_id="c2", status="analyzing", total_ms=900,
                     input_tokens=100, output_tokens=20, total_tokens=120, cost_usd=0.01,
                     agent_model="claude-haiku-5-5")
    resp = state.to_dict()
    assert resp["status"] == "analyzing"
    assert resp["cost_usd"] == 0.01
    assert resp["agent_model"] == "claude-haiku-5-5"


def test_unknown_cost_is_null_in_the_payload():
    state = RunState(run_id="c3", status="complete", agent_model="mystery")
    resp = state.to_dict()
    assert "cost_usd" in resp and resp["cost_usd"] is None
    assert resp["agent_model"] == "mystery"


def test_running_and_error_status_have_no_token_fields():
    running = RunState(run_id="c4").to_dict()
    errored = RunState(run_id="c5", status="error", message="x").to_dict()
    for resp in (running, errored):
        assert "cost_usd" not in resp and "agent_model" not in resp


def test_an_error_status_carries_the_usage_when_the_agent_had_used_tokens():
    state = RunState(run_id="c7", status="error", message="Run cancelled by user.", total_ms=4200)
    state.record_usage(usage_summary(prompt=2000, cached=1000, completion=100, cache_write=500))
    resp = state.to_dict()
    assert resp["status"] == "error" and resp["message"] == "Run cancelled by user."
    assert resp["total_ms"] == 4200
    assert (resp["input_tokens"], resp["output_tokens"], resp["total_tokens"]) == (2000, 100, 2600)
    assert resp["cost_usd"] == pytest.approx(expected_sonnet_cost(1000, 100, 1000, 500))
    assert resp["agent_model"] == "claude-sonnet-5-5"


def test_to_response_is_the_same_as_to_dict():
    state = RunState(run_id="c6", status="complete", cost_usd=0.5)
    assert state.to_response() == state.to_dict()


# ---------------------------------------------------------------------------
# BENCHMARK_TIMEOUT_S
# ---------------------------------------------------------------------------


def test_timeout_defaults_to_180_seconds():
    assert get_agent_timeout() == 180


@pytest.mark.parametrize("raw,expected", [("60", 60.0), ("0.25", 0.25), (" 300 ", 300.0)])
def test_timeout_from_env(monkeypatch, raw, expected):
    monkeypatch.setenv("BENCHMARK_TIMEOUT_S", raw)
    assert get_agent_timeout() == expected


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "nan", "inf"])
def test_bad_timeout_is_rejected(monkeypatch, raw):
    monkeypatch.setenv("BENCHMARK_TIMEOUT_S", raw)
    with pytest.raises(ValueError, match="BENCHMARK_TIMEOUT_S"):
        get_agent_timeout()


# ---------------------------------------------------------------------------
# Step descriptions: the model's goal, or the actions in plain words
# ---------------------------------------------------------------------------

_ACTION_MODEL = None


def action(**kwargs):
    """A real browser-use action (the same objects an agent's model output holds)."""
    global _ACTION_MODEL
    if _ACTION_MODEL is None:
        from browser_use.tools.service import Tools

        _ACTION_MODEL = Tools().registry.create_action_model()
    return _ACTION_MODEL(**kwargs)


def agent_after_step(next_goal, *actions, elements=None):
    """The part of a browser-use Agent that _format_action reads, one step in."""
    output = SimpleNamespace(next_goal=next_goal, action=list(actions))
    state = SimpleNamespace(interacted_element=elements)
    return SimpleNamespace(history=SimpleNamespace(history=[SimpleNamespace(model_output=output, state=state)]))


def element(**attributes):
    return SimpleNamespace(node_name="INPUT", attributes=attributes)


def test_the_models_own_goal_is_the_description():
    agent = agent_after_step("Click on the Menu link", action(click={"index": 4}))
    assert _format_action(agent) == "Click on the Menu link"


@pytest.mark.parametrize("empty_goal", ["", "   ", None])
def test_an_empty_goal_is_described_from_the_action(empty_goal):
    agent = agent_after_step(empty_goal, action(evaluate={"code": "(function(){return 1})()"}))
    assert _format_action(agent) == "Run a script on the page"


@pytest.mark.parametrize("kwargs,expected", [
    (dict(evaluate={"code": "document.title"}), "Run a script on the page"),
    (dict(click={"index": 12}), "Click element 12"),
    (dict(input={"index": 3, "text": "top"}), "Type 'top' into element 3"),
    (dict(input={"index": 3, "text": ""}), "Clear element 3"),
    (dict(scroll={"down": True, "pages": 1.0}), "Scroll down"),
    (dict(scroll={"down": False, "pages": 0.5}), "Scroll up half a page"),
    (dict(scroll={"down": True, "pages": 10.0}), "Scroll to the bottom"),
    (dict(scroll={"down": True, "pages": 1.0, "index": 7}), "Scroll down in element 7"),
    (dict(navigate={"url": "https://books.toscrape.com/"}), "Open https://books.toscrape.com/"),
    (dict(navigate={"url": "https://x.example/", "new_tab": True}), "Open https://x.example/ in a new tab"),
    (dict(search={"query": "chain belt", "engine": "google"}), 'Search google for "chain belt"'),
    (dict(go_back={}), "Go back"),
    (dict(wait={"seconds": 2}), "Wait 2 seconds"),
    (dict(extract={"query": "the price of the first book"}), "Read the page for: the price of the first book"),
    (dict(send_keys={"keys": "Enter"}), "Press Enter"),
    (dict(done={"text": "Added the book.", "success": True}), "Done: Added the book."),
])
def test_actions_in_plain_words(kwargs, expected):
    assert _format_action(agent_after_step("", action(**kwargs))) == expected


def test_a_click_by_coordinates_is_described_too():
    """browser-use only offers coordinate clicks to some models, so the action is faked here."""
    fake = SimpleNamespace(model_dump=lambda **kwargs: {"click": {"coordinate_x": 40, "coordinate_y": 90}})
    assert _format_action(agent_after_step("", fake)) == "Click at (40, 90)"


def test_typing_into_a_search_field_says_search_box():
    typed = action(input={"index": 3, "text": "top"})
    by_type = agent_after_step("", typed, elements=[element(type="search")])
    by_label = agent_after_step("", typed, elements=[element(placeholder="Search products")])
    assert _format_action(by_type) == "Type 'top' into the search box"
    assert _format_action(by_label) == "Type 'top' into the search box"


def test_typing_into_a_labelled_field_names_it():
    agent = agent_after_step("", action(input={"index": 5, "text": "a@b.co"}), elements=[element(**{"aria-label": "Email"})])
    assert _format_action(agent) == 'Type \'a@b.co\' into the "Email" field'


def test_a_click_names_the_element_when_it_has_a_label():
    agent = agent_after_step("", action(click={"index": 12}), elements=[element(**{"aria-label": "Add to basket"})])
    assert _format_action(agent) == 'Click element 12 ("Add to basket")'


def test_a_step_with_several_actions_lists_them_all():
    agent = agent_after_step(
        "", action(input={"index": 3, "text": "top"}), action(send_keys={"keys": "Enter"}),
        elements=[element(type="search"), None],
    )
    assert _format_action(agent) == "Type 'top' into the search box, then press Enter"


def test_a_long_description_is_cut():
    agent = agent_after_step("", action(extract={"query": "word " * 100}))
    text = _format_action(agent)
    assert len(text) <= 200 and text.endswith("...")


def test_a_step_without_anything_to_describe_says_processing():
    assert _format_action(SimpleNamespace(history=SimpleNamespace(history=[]))) == "Processing..."
    no_output = SimpleNamespace(history=SimpleNamespace(history=[SimpleNamespace(model_output=None)]))
    assert _format_action(no_output) == "Processing..."
    assert _format_action(agent_after_step("", )) == "Processing..."
    assert _format_action(object()) == "Processing..."


# ---------------------------------------------------------------------------
# run_benchmark with a fake browser-use Agent (no browser, no network)
# ---------------------------------------------------------------------------

VERDICT_PASS = {
    "success": True,
    "summary": "Added the book to the basket.",
    "phases": [
        {"name": "Open the site", "steps": [1], "failed": False, "slow": False},
        {"name": "Add to basket", "steps": [2, 3], "failed": False, "slow": True},
    ],
}


def history_item(goal, evaluation=None, results=()):
    """One browser-use history step: the model's output and what its actions returned."""
    return SimpleNamespace(
        model_output=SimpleNamespace(next_goal=goal, evaluation_previous_goal=evaluation),
        result=list(results),
    )


def action_result(text=None, error=None, is_done=False):
    return SimpleNamespace(extracted_content=text, error=error, is_done=is_done)


class FakeHistory:
    def __init__(self, items, errors=None, done=True, usage=None, final=None, successful=None):
        self.history = list(items)
        self._errors = errors if errors is not None else [None] * len(items)
        self._done = done
        self._final = final
        self._successful = successful
        self.usage = usage

    def errors(self):
        return list(self._errors)

    def is_done(self):
        return self._done

    def final_result(self):
        # Like browser-use: the last action's output, whether or not it was "done".
        return self._final

    def is_successful(self):
        return self._successful if self._done else None


class FakeAgent:
    """Stands in for browser_use.Agent. Class attributes script the run."""

    goals = ["Open the site", "Search for a book", "Click add to basket"]
    evaluations = None  # per step: the model's verdict on the step before
    results = None  # per step: the ActionResults its actions returned
    errors = None
    done = True
    usage = None
    final = None  # what final_result() returns: the last action's output, "done" or not
    successful = None
    sleep = 0.0
    raises = None
    raises_after = None  # raise ``raises`` after this many steps instead of before the first
    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.history = FakeHistory([])
        self.browser_session = SimpleNamespace(take_screenshot=self._screenshot)
        self.token_cost_service = SimpleNamespace(get_usage_summary=self._usage)
        type(self).instances.append(self)

    async def _screenshot(self, format="png", quality=None):
        assert (format, quality) == ("jpeg", 80)
        return b"\xff\xd8fake-jpeg"

    async def _usage(self):
        return type(self).usage

    def _items(self):
        cls = type(self)
        evaluations = cls.evaluations or [None] * len(cls.goals)
        results = cls.results or [()] * len(cls.goals)
        return [history_item(g, e, r) for g, e, r in zip(cls.goals, evaluations, results)]

    async def run(self, on_step_start=None, on_step_end=None):
        cls = type(self)
        if cls.raises and cls.raises_after is None:
            raise cls.raises
        items = self._items()
        for i in range(len(items)):
            if cls.raises and i == cls.raises_after:
                raise cls.raises
            await on_step_start(self)
            if cls.sleep:
                await asyncio.sleep(cls.sleep)
            self.history = FakeHistory(items[: i + 1])
            await on_step_end(self)
        self.history = FakeHistory(items, cls.errors, cls.done, cls.usage, cls.final, cls.successful)
        return self.history


@pytest.fixture
def fake_run(monkeypatch, tmp_path):
    """Patch everything run_benchmark touches outside this process; returns a recorder."""
    sentinel_llm = object()
    seen = SimpleNamespace(profile_calls=[], profiles=[], llm_models=[], sentinel_llm=sentinel_llm)

    class FakeAgentForTest(FakeAgent):
        pass

    FakeAgentForTest.instances = []
    seen.agent_cls = FakeAgentForTest

    def fake_profile(**kwargs):
        seen.profile_calls.append(kwargs)
        profile_dir = tmp_path / f"profile-{len(seen.profiles)}"
        profile_dir.mkdir()
        profile = SimpleNamespace(user_data_dir=str(profile_dir))
        seen.profiles.append(profile)
        return profile

    def fake_agent_llm(model=None, **kwargs):
        seen.llm_models.append(model)
        return sentinel_llm

    monkeypatch.setattr(browser_use, "Agent", FakeAgentForTest)
    monkeypatch.setattr(browser_env, "browser_profile", fake_profile)
    monkeypatch.setattr(llm, "agent_llm", fake_agent_llm)
    return seen


def make_state(**kwargs):
    return RunState(run_id="run-1", goal="Add any book to the basket.", persisted_run_id="run-1", **kwargs)


async def test_successful_run_end_to_end(fake_run, monkeypatch):
    fake_run.agent_cls.usage = usage_summary()
    calls = install_fake_anthropic(monkeypatch, text_response(VERDICT_PASS))
    await persistence.persist_run_start("run-1", "local", "https://books.toscrape.com", "Add", "G", agent_model="claude-sonnet-5-5")
    state = make_state()

    await run_benchmark(state, "https://books.toscrape.com", "Add any book to the basket.")

    assert state.status == "complete"
    assert state.result_state == "pass"
    assert state.success is True
    assert [s.description for s in state.steps] == fake_run.agent_cls.goals
    assert state.steps[0].screenshot_b64.startswith("data:image/jpeg;base64,")
    assert state.summary == "Added the book to the basket."
    assert [p["steps"] for p in state.phases] == [[1], [2, 3]]
    assert state.agent_model == "claude-sonnet-5-5"
    assert state.cost_usd == pytest.approx(expected_sonnet_cost(14097, 987, 43599, 14533))

    # What the API serves.
    payload = state.to_dict()
    assert payload["cost_usd"] == pytest.approx(0.0831, abs=5e-5)
    assert payload["agent_model"] == "claude-sonnet-5-5"
    assert payload["input_tokens"] == 57696

    # One judge call, on the judge model, and it saw the steps.
    assert len(calls) == 1
    prompt = calls[0]["messages"][0]["content"]
    assert "Step #2" in prompt
    # A run that finished on its own is not described to the judge as "unknown".
    assert "unknown" not in prompt.lower()
    assert "RESULT STATE: completed" in prompt


async def test_the_judge_reads_the_agents_final_report(fake_run, monkeypatch):
    """The verification a task asks for is often only in the agent's closing report."""
    fake_run.agent_cls.final = "Basket: 1 item, A Light in the Attic, £51.77."
    fake_run.agent_cls.successful = True
    calls = install_fake_anthropic(monkeypatch, text_response(VERDICT_PASS))
    await persistence.persist_run_start("run-1", "local", "https://books.toscrape.com", "Add", "G")
    state = make_state()

    await run_benchmark(state, "https://books.toscrape.com", "Goal")

    prompt = calls[0]["messages"][0]["content"]
    assert "Agent reported success: yes" in prompt
    assert "<agent_report>\nBasket: 1 item, A Light in the Attic, £51.77.\n</agent_report>" in prompt
    # What the judge read is kept with the run, so a verdict can be checked later.
    assert state.final_report == "Basket: 1 item, A Light in the Attic, £51.77."
    assert persistence.read_run("run-1")["final_report"] == state.final_report


async def test_a_last_output_that_is_not_a_done_report_is_not_sent_as_one(fake_run, monkeypatch):
    """browser-use's final_result() is the last action's output even when the agent never
    called done (for example page text it extracted), which is no report at all."""
    fake_run.agent_cls.done = False
    fake_run.agent_cls.final = "Page text: Add to basket ... In stock ..."
    calls = install_fake_anthropic(monkeypatch, text_response({**VERDICT_PASS, "success": False}))
    await persistence.persist_run_start("run-1", "local", "https://books.toscrape.com", "Add", "G")
    state = make_state()

    await run_benchmark(state, "https://books.toscrape.com", "Goal")

    prompt = calls[0]["messages"][0]["content"]
    assert "(The agent gave no final report.)" in prompt
    assert "Page text" not in prompt
    assert state.final_report is None
    assert persistence.read_run("run-1")["final_report"] is None


async def test_agent_is_built_from_the_llm_layer_and_the_shared_browser_profile(fake_run, monkeypatch):
    install_fake_anthropic(monkeypatch, text_response(VERDICT_PASS))
    state = make_state()

    await run_benchmark(state, "https://books.toscrape.com", "Goal", viewport={"width": 390, "height": 844})

    (agent,) = fake_run.agent_cls.instances
    assert agent.kwargs["llm"] is fake_run.sentinel_llm
    assert fake_run.llm_models == [state.agent_model]
    assert agent.kwargs["browser_profile"] is fake_run.profiles[0]
    assert fake_run.profile_calls == [{"viewport": {"width": 390, "height": 844}}]
    assert agent.kwargs["task"] == "Go to https://books.toscrape.com\n\nGoal"
    assert agent.kwargs["use_judge"] is False
    assert agent.kwargs["enable_signal_handler"] is False
    assert agent.kwargs["file_system_path"]


async def test_the_run_cleans_up_its_temp_dirs(fake_run, monkeypatch):
    install_fake_anthropic(monkeypatch, text_response(VERDICT_PASS))
    await run_benchmark(make_state(), "https://books.toscrape.com", "Goal")
    (agent,) = fake_run.agent_cls.instances
    # browser_env.cleanup_profile only deletes dirs it made itself; the agent-files dir is one.
    assert not os.path.exists(agent.kwargs["file_system_path"])


async def test_the_run_is_saved_to_its_run_file(fake_run, monkeypatch):
    fake_run.agent_cls.usage = usage_summary()
    install_fake_anthropic(monkeypatch, text_response(VERDICT_PASS))
    await persistence.persist_run_start("run-1", "local", "https://books.toscrape.com", "Add", "G", agent_model="claude-sonnet-5-5")
    state = make_state()

    await run_benchmark(state, "https://books.toscrape.com", "Goal")

    record = persistence.read_run("run-1")
    assert record["status"] == "complete"
    assert record["result_state"] == "pass"
    assert record["success"] is True
    assert record["summary"] == "Added the book to the basket."
    assert [s["description"] for s in record["steps"]] == fake_run.agent_cls.goals
    assert len(record["phases"]) == 2
    assert record["input_tokens"] == 57696 and record["output_tokens"] == 987
    assert (record["cache_read_tokens"], record["cache_write_tokens"]) == (43599, 14533)
    assert record["estimated_cost_usd"] == pytest.approx(state.cost_usd)
    assert record["agent_model"] == "claude-sonnet-5-5"


async def test_a_run_without_a_run_file_still_works(fake_run, monkeypatch, tmp_path):
    install_fake_anthropic(monkeypatch, text_response(VERDICT_PASS))
    state = RunState(run_id="run-x", goal="G")  # persisted_run_id is None
    await run_benchmark(state, "https://books.toscrape.com", "Goal")
    assert state.status == "complete"
    assert not (tmp_path / "runs").exists()


async def test_timeout_reports_too_slow_with_the_tokens_so_far(fake_run, monkeypatch):
    monkeypatch.setenv("BENCHMARK_TIMEOUT_S", "0.3")
    fake_run.agent_cls.sleep = 0.2  # second step runs past the limit
    fake_run.agent_cls.usage = usage_summary(prompt=2000, cached=0, completion=100, cache_write=0)
    calls = install_fake_anthropic(monkeypatch, text_response({
        "success": False, "summary": "Ran out of time.",
        "phases": [{"name": "Start", "steps": [1], "failed": False, "slow": True}],
    }))
    state = make_state()

    await run_benchmark(state, "https://books.toscrape.com", "Goal")

    assert state.result_state == "too_slow"
    assert state.status == "complete"
    assert state.success is False
    assert len(state.steps) == 1
    assert state.input_tokens == 2000 and state.output_tokens == 100
    assert state.cost_usd == pytest.approx((2000 * 2.0 + 100 * 10.0) / 1_000_000)
    assert "RESULT STATE: too_slow" in calls[0]["messages"][0]["content"]
    assert "(The agent gave no final report.)" in calls[0]["messages"][0]["content"]


async def test_judge_failure_still_ends_the_run(fake_run, monkeypatch):
    install_fake_anthropic(monkeypatch, Exception("API down"))
    state = make_state()
    await run_benchmark(state, "https://books.toscrape.com", "Goal")
    assert state.status == "complete"
    assert state.result_state == "fail"
    assert state.phases == []
    assert "Could not analyze" in state.summary


async def test_refusal_mid_run_is_reported_as_an_error_not_a_failure(fake_run, monkeypatch):
    fake_run.agent_cls.errors = [None, "claude-sonnet-5-5 declined this step (stop_reason=refusal, category=cyber)", None]
    fake_run.agent_cls.done = False
    calls = install_fake_anthropic(monkeypatch, text_response(VERDICT_PASS))
    state = make_state()

    await run_benchmark(state, "https://books.toscrape.com", "Goal")

    assert state.result_state == "error"
    assert state.success is False  # whatever the judge says
    assert "declined" in state.message
    assert state.status == "complete"  # the steps taken are still judged and shown
    assert len(state.steps) == 3
    assert len(calls) == 1
    assert "RESULT STATE: unknown" in calls[0]["messages"][0]["content"]  # an errored run keeps its wording


async def test_a_judged_error_tells_the_ui_why_it_is_an_error(fake_run, monkeypatch):
    """A refusal part-way is judged (status complete), and the status still carries the reason."""
    fake_run.agent_cls.errors = [None, "claude-sonnet-5-5 declined this step (stop_reason=refusal, category=cyber)", None]
    fake_run.agent_cls.done = False
    fake_run.agent_cls.usage = usage_summary()
    install_fake_anthropic(monkeypatch, text_response(VERDICT_PASS))
    state = make_state()

    await run_benchmark(state, "https://books.toscrape.com", "Goal")

    payload = state.to_dict()
    assert (payload["status"], payload["result_state"]) == ("complete", "error")
    assert payload["message"] == "The agent model declined to continue this task (safety refusal)."
    assert payload["summary"] == "Added the book to the basket."
    assert [p["steps"] for p in payload["phases"]] == [[1], [2, 3]]
    assert payload["total_tokens"] == 73216


def test_a_pass_or_fail_has_no_message_in_the_status():
    for result_state in ("pass", "fail", "too_slow"):
        state = RunState(run_id="m1", status="complete", result_state=result_state, summary="ok")
        assert "message" not in state.to_dict()


async def test_an_exception_after_some_steps_is_judged_and_keeps_the_usage(fake_run, monkeypatch):
    """The steps before the crash were billed and are judged; the status says what went wrong."""
    fake_run.agent_cls.raises = RuntimeError("browser crashed")
    fake_run.agent_cls.raises_after = 2
    fake_run.agent_cls.usage = usage_summary()
    calls = install_fake_anthropic(monkeypatch, text_response({
        "success": True, "summary": "Opened the site and searched.",
        "phases": [{"name": "Start", "steps": [1, 2], "failed": False, "slow": False}],
    }))
    await persistence.persist_run_start("run-1", "local", "https://books.toscrape.com", "Add", "G", agent_model="claude-sonnet-5-5")
    state = make_state()

    await run_benchmark(state, "https://books.toscrape.com", "Goal")

    assert len(calls) == 1
    payload = state.to_dict()
    assert (payload["status"], payload["result_state"], payload["success"]) == ("complete", "error", False)
    assert payload["message"] == "The run encountered an error."
    assert payload["total_tokens"] == 73216
    assert payload["cost_usd"] == pytest.approx(expected_sonnet_cost(14097, 987, 43599, 14533))
    record = persistence.read_run("run-1")
    assert record["total_tokens"] == 73216 and record["message"] == "The run encountered an error."


async def test_the_judge_reads_what_the_agent_saw_and_its_final_report(fake_run, monkeypatch):
    """The step goals alone ("Finish") cannot show a verification; the evidence goes to the judge."""
    fake_run.agent_cls.goals = ["Open the cart", "Read the cart row", "Finish"]
    fake_run.agent_cls.evaluations = [
        None,
        "Success - the cart page is open.",
        "Success - the row shows Blue Top, quantity 4, total Rs. 2000.",
    ]
    fake_run.agent_cls.results = [
        [action_result("Clicked button 'View Cart'")],
        [action_result("<url>\nhttps://shop.example/view_cart\n</url>\n<structured_result>\n"
                       '{"rows": [{"name": "Blue Top", "price": "Rs. 500", "quantity": 4, "total": "Rs. 2000"}]}'
                       "\n</structured_result>")],
        [action_result("Cart holds Blue Top x4 at Rs. 500, total Rs. 2000.", is_done=True)],
    ]
    fake_run.agent_cls.final = "Cart holds Blue Top x4 at Rs. 500, total Rs. 2000."
    calls = install_fake_anthropic(monkeypatch, text_response(VERDICT_PASS))
    await persistence.persist_run_start("run-1", "local", "https://shop.example", "Add", "G")
    state = make_state()

    await run_benchmark(state, "https://shop.example", "Goal")

    prompt = calls[0]["messages"][0]["content"]
    assert "Step #3 (" in prompt and "): Finish" in prompt
    assert "evaluation of the step before: Success - the row shows Blue Top, quantity 4, total Rs. 2000." in prompt
    assert "result: Clicked button 'View Cart'" in prompt
    assert '"quantity": 4, "total": "Rs. 2000"' in prompt
    assert "THE AGENT'S FINAL REPORT" in prompt
    assert prompt.count("Cart holds Blue Top x4 at Rs. 500, total Rs. 2000.") == 1  # the done text only once
    assert state.final_report == "Cart holds Blue Top x4 at Rs. 500, total Rs. 2000."
    assert persistence.read_run("run-1")["final_report"] == state.final_report
    # None of it goes to the UI's status payload.
    assert all(set(s) == {"step", "description", "elapsed_ms"} for s in state.to_dict()["steps"][:-1])


async def test_long_page_text_and_errors_reach_the_judge_cut_short(fake_run, monkeypatch):
    fake_run.agent_cls.goals = ["Read the page", "Click buy"]
    fake_run.agent_cls.results = [
        [action_result("cart " * 2000)],
        [action_result(error="Element 12 not found\n" + "trace " * 500)],
    ]
    fake_run.agent_cls.done = False
    fake_run.agent_cls.errors = [None, "Element 12 not found"]
    calls = install_fake_anthropic(monkeypatch, text_response({**VERDICT_PASS, "success": False}))
    state = make_state()

    await run_benchmark(state, "https://shop.example", "Goal")

    prompt = calls[0]["messages"][0]["content"]
    page_line = next((line for line in prompt.splitlines() if line.strip().startswith("result: cart cart")), "")
    assert len(page_line.strip()) < 700 and page_line.endswith("...")
    error_line = next((line for line in prompt.splitlines() if "error: Element 12" in line), "")
    assert error_line.strip().startswith("result: error: Element 12 not found") and len(error_line.strip()) < 400
    assert "(The agent gave no final report.)" in prompt
    assert state.final_report is None


async def test_a_refusal_the_agent_recovered_from_is_not_an_error(fake_run, monkeypatch):
    fake_run.agent_cls.errors = [None, "declined this step (stop_reason=refusal)", None]
    fake_run.agent_cls.done = True
    install_fake_anthropic(monkeypatch, text_response(VERDICT_PASS))
    state = make_state()
    await run_benchmark(state, "https://books.toscrape.com", "Goal")
    assert state.result_state == "pass"


async def test_every_step_failing_is_an_error_with_the_reason(fake_run, monkeypatch):
    """E.g. an invalid API key: browser-use turns each call's error into a failed step."""
    fake_run.agent_cls.errors = ["Error code: 401 - invalid x-api-key"] * 3
    fake_run.agent_cls.done = False
    calls = install_fake_anthropic(monkeypatch, text_response(VERDICT_PASS))
    state = make_state()

    await run_benchmark(state, "https://books.toscrape.com", "Goal")

    assert state.status == "error"
    assert state.result_state == "error"
    assert "could not complete a single step" in state.message
    assert "invalid x-api-key" in state.message
    assert calls == []  # nothing worth judging


async def test_some_failed_steps_among_good_ones_are_just_a_normal_run(fake_run, monkeypatch):
    fake_run.agent_cls.errors = [None, "Element not found", None]
    fake_run.agent_cls.done = False  # ran out of steps, say
    install_fake_anthropic(monkeypatch, text_response({**VERDICT_PASS, "success": False}))
    state = make_state()
    await run_benchmark(state, "https://books.toscrape.com", "Goal")
    assert state.result_state == "fail"
    assert state.message == ""


async def test_chromium_missing_gives_the_install_hint(fake_run, monkeypatch):
    def no_chromium(**kwargs):
        raise browser_env.ChromiumNotFoundError("No local Chromium found. Install it with: cd server && uv run playwright install chromium")

    monkeypatch.setattr(browser_env, "browser_profile", no_chromium)
    state = make_state()
    await run_benchmark(state, "https://books.toscrape.com", "Goal")
    assert state.status == "error"
    assert state.result_state == "error"
    assert "playwright install chromium" in state.message
    assert fake_run.agent_cls.instances == []
    assert persistence.read_run("run-1")["status"] == "error"


async def test_unexpected_errors_stay_generic(fake_run, monkeypatch):
    fake_run.agent_cls.raises = RuntimeError("secret internal path /Users/someone/x")
    state = make_state()
    await run_benchmark(state, "https://books.toscrape.com", "Goal")
    assert state.status == "error"
    assert state.message == "The run encountered an error."


async def test_a_bad_timeout_setting_is_reported(fake_run, monkeypatch):
    monkeypatch.setenv("BENCHMARK_TIMEOUT_S", "soon")
    state = make_state()
    await run_benchmark(state, "https://books.toscrape.com", "Goal")
    assert state.status == "error"
    assert "BENCHMARK_TIMEOUT_S" in state.message


async def test_cancelling_a_run_ends_it_as_an_error_and_saves_it(fake_run, monkeypatch):
    fake_run.agent_cls.sleep = 5.0
    install_fake_anthropic(monkeypatch, text_response(VERDICT_PASS))
    await persistence.persist_run_start("run-1", "local", "https://books.toscrape.com", "Add", "G")
    state = make_state()

    task = asyncio.create_task(run_benchmark(state, "https://books.toscrape.com", "Goal"))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert state.status == "error"
    assert state.message == "Run cancelled by user."
    assert state.result_state == "error"
    assert persistence.read_run("run-1")["status"] == "error"
    assert persistence.read_run("run-1")["message"] == "Run cancelled by user."


async def test_a_cancelled_run_keeps_the_usage_and_time_of_the_calls_already_made(fake_run, monkeypatch):
    """The agent's model calls were billed, so the run file and the status must say so."""
    fake_run.agent_cls.sleep = 5.0
    fake_run.agent_cls.usage = usage_summary()
    install_fake_anthropic(monkeypatch, text_response(VERDICT_PASS))
    await persistence.persist_run_start("run-1", "local", "https://books.toscrape.com", "Add", "G")
    state = make_state()

    task = asyncio.create_task(run_benchmark(state, "https://books.toscrape.com", "Goal"))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    cost = expected_sonnet_cost(14097, 987, 43599, 14533)
    assert (state.input_tokens, state.output_tokens, state.total_tokens) == (57696, 987, 73216)
    assert state.cost_usd == pytest.approx(cost)
    assert state.total_ms >= 250

    record = persistence.read_run("run-1")
    assert record["status"] == "error" and record["message"] == "Run cancelled by user."
    assert (record["input_tokens"], record["output_tokens"], record["total_tokens"]) == (57696, 987, 73216)
    assert (record["cache_read_tokens"], record["cache_write_tokens"]) == (43599, 14533)
    assert record["estimated_cost_usd"] == pytest.approx(cost)
    assert record["total_ms"] >= 250

    payload = state.to_dict()
    assert payload["status"] == "error"
    assert payload["total_tokens"] == 73216
    assert payload["cost_usd"] == pytest.approx(cost)
    assert payload["total_ms"] >= 250


async def test_the_usage_read_after_a_cancel_is_shielded_from_a_second_cancel(fake_run, monkeypatch):
    """A second cancel arriving during the read must not abort the agent's bookkeeping."""
    fake_run.agent_cls.sleep = 5.0
    read_started = asyncio.Event()
    read_finished = []

    async def slow_usage(self):
        read_started.set()
        await asyncio.sleep(0.2)
        read_finished.append(True)
        return None

    monkeypatch.setattr(fake_run.agent_cls, "_usage", slow_usage)
    state = make_state()

    task = asyncio.create_task(run_benchmark(state, "https://books.toscrape.com", "Goal"))
    await asyncio.sleep(0.2)
    task.cancel()
    await asyncio.wait_for(read_started.wait(), timeout=3)  # fails fast if the cancel path never reads usage
    task.cancel()  # a second cancel while the usage is being read
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=3)
    await asyncio.sleep(0.4)

    assert read_finished == [True]  # not cancelled half way
    assert state.status == "error" and state.message == "Run cancelled by user."


async def test_a_cancelled_run_does_not_hang_on_a_usage_read_that_never_returns(fake_run, monkeypatch):
    import benchmark_runner

    fake_run.agent_cls.sleep = 5.0

    async def stuck_usage(self):
        await asyncio.sleep(60)

    monkeypatch.setattr(fake_run.agent_cls, "_usage", stuck_usage)
    monkeypatch.setattr(benchmark_runner, "_USAGE_READ_TIMEOUT_S", 0.2)
    await persistence.persist_run_start("run-1", "local", "https://books.toscrape.com", "Add", "G")
    state = make_state()

    task = asyncio.create_task(run_benchmark(state, "https://books.toscrape.com", "Goal"))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=3)

    assert state.total_tokens == 0 and state.cost_usd is None
    record = persistence.read_run("run-1")
    assert record["status"] == "error"  # still saved
    assert record["total_ms"] > 0


async def test_the_judge_does_not_block_the_event_loop(fake_run, monkeypatch):
    """A slow judge call must leave the loop free (status polls, other runs)."""
    import time

    def slow_judge(goal, steps, result_state="unknown", **report):
        time.sleep(0.4)
        return {"success": True, "summary": "ok", "phases": []}

    monkeypatch.setattr("run_judge.judge_run", slow_judge)
    state = make_state()
    ticks = []

    async def ticker():
        while True:
            ticks.append(1)
            await asyncio.sleep(0.02)

    watcher = asyncio.create_task(ticker())
    await run_benchmark(state, "https://books.toscrape.com", "Goal")
    watcher.cancel()
    assert state.result_state == "pass"
    assert len(ticks) > 10  # ~0.4 s of judging at 20 ms ticks
