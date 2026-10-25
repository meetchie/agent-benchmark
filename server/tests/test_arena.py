"""arena.py: judge prompt and verdict handling (mocked model), log writing, analyze_runs,
and the BrowserUse arm's bookkeeping with a fake browser-use Agent. No network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import analyze_runs
import arena
import llm
from adapters import AGENTS
from adapters.base_agent import BaseAgent
from adapters.browseruse_agent import BrowserUseTelemetricAgent
from scenarios import get_scenario

ARCHIVE = Path(__file__).resolve().parent.parent / "arena_logs"


def sample_events(agent: BaseAgent):
    agent.log_step_start(action_type="search_products", action_data={"query": "chain belt"})
    end = agent.log_step_end(tokens_input=1000, tokens_output=50, observation={"ok": 1})
    end["cost_usd"] = 0.0025
    agent.log_step_start(action_type="navigate")
    end = agent.log_step_end(tokens_input=1200, tokens_output=40)
    end["cost_usd"] = 0.0028


class DummyAgent(BaseAgent):
    async def run(self, start_url=None, **kwargs):
        return {}


def test_only_the_two_arms_remain():
    assert set(AGENTS) == {"BROWSERUSE", "RINDLER"}


def test_judge_prompt_carries_goal_criteria_actions_and_report():
    scenario = get_scenario("vhlistings_product_attribute_search")
    agent = DummyAgent(run_id="r", goal=scenario.goal, lane="RINDLER")
    sample_events(agent)
    result = {"success": True, "steps": 2, "final_extraction": "Iron Chain Belt $29.00",
              "errors_detected": ["Reached max_steps (30) without calling done"]}
    prompt = arena.build_judge_prompt(scenario, result, agent.telemetry_events)
    assert scenario.goal in prompt and scenario.success_criteria in prompt
    assert "## VERIFICATION FOCUS\n" + scenario.verification_hint in prompt
    assert "Agent reported success: True" in prompt and "Total steps taken: 2" in prompt
    assert "Actions taken: Step 1: search_products, Step 2: navigation" in prompt
    assert "Errors detected: Reached max_steps" in prompt
    assert prompt.rstrip().endswith("Return your verdict as JSON.")
    assert "## FINAL EXTRACTION / RESULT\nIron Chain Belt $29.00" in prompt


def test_judge_uses_structured_output_and_reports_cost(monkeypatch):
    seen = {}

    def fake_complete_json(system, prompt, schema=None, **kwargs):
        seen.update(system=system, prompt=prompt, schema=schema, **kwargs)
        usage = llm.Usage(input_tokens=900, output_tokens=120)
        return llm.JSONResult(
            {"verdict": "PASS", "reason": "all met", "details": {"criteria_met": ["1"], "criteria_failed": [], "errors_observed": []}},
            usage=usage, model="claude-sonnet-5-5", stop_reason="end_turn",
        )

    monkeypatch.setattr(llm, "complete_json", fake_complete_json)
    scenario = get_scenario("vhlistings_add_to_cart")
    verdict = arena.run_judge(scenario, {"success": True, "steps": 3}, [], model=None)
    assert verdict["verdict"] == "PASS" and verdict["reason"] == "all met"
    assert verdict["judge_model"] == "claude-sonnet-5-5"
    assert verdict["judge_cost_usd"] == pytest.approx(llm.Usage(900, 120).cost_usd("claude-sonnet-5-5"))
    assert seen["system"] == arena.JUDGE_SYSTEM_PROMPT and seen["role"] == "judge"
    assert seen["schema"]["properties"]["verdict"]["enum"] == ["PASS", "FAIL"]
    assert seen["model"] == llm.model_for("judge")


def test_judge_error_and_odd_verdicts(monkeypatch):
    def failing(*a, **k):
        raise llm.LLMError("overloaded", kind="api", status_code=529)

    monkeypatch.setattr(llm, "complete_json", failing)
    scenario = get_scenario("vhlistings_add_to_cart")
    verdict = arena.run_judge(scenario, {}, [])
    assert verdict["verdict"] == "ERROR" and "overloaded" in verdict["reason"]

    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: llm.JSONResult(
        {"verdict": "MAYBE"}, usage=llm.Usage(), model="m", stop_reason="end_turn"))
    verdict = arena.run_judge(scenario, {}, [], model="m")
    assert verdict["verdict"] == "FAIL" and verdict["reason"]


def test_save_log_round_trips_through_analyze_runs(tmp_path):
    scenario = get_scenario("vhlistings_product_attribute_search")
    agent = DummyAgent(run_id="r1", goal=scenario.goal, lane="RINDLER")
    sample_events(agent)
    totals = arena.calculate_totals(agent.telemetry_events)
    assert totals == {"tokens_input": 2200, "tokens_output": 90, "tokens_total": 2290, "cost_usd": pytest.approx(0.0053)}
    judge = {"verdict": "PASS", "reason": "ok", "details": {"criteria_met": ["a", "b"]},
             "judge_model": "claude-sonnet-5-5", "judge_cost_usd": 0.004}
    path = arena.save_log(agent, {"success": True, "final_extraction": "Iron Chain Belt"}, 42.5, scenario, totals,
                          judge_result=judge, log_dir=str(tmp_path),
                          run_info={"model": "claude-sonnet-5-5", "max_steps": 30, "mapping": "vhlistings"})
    text = Path(path).read_text()
    assert Path(path).name.startswith("arena_rindler_vhlistings_")
    for line in ("Agent: RINDLER", "Agent Model: claude-sonnet-5-5", "Max Steps: 30", "Mapping: vhlistings",
                 "Duration: 42.50s", "Judge Verdict: PASS", "Criteria Met: a, b", "Judge Cost: $0.0040",
                 "Token Burn: 2,290 (2,200 in / 90 out)", "Cost: $0.0053", 'Final Report: "Iron Chain Belt"'):
        assert line in text.splitlines(), line
    events = json.loads(text.split("Telemetry Events:\n", 1)[1])
    assert len(events) == 4

    run = analyze_runs.parse_log_file(Path(path))
    assert run["agent"] == "RINDLER" and run["judge_verdict"] == "PASS" and run["model"] == "claude-sonnet-5-5"
    assert run["steps"] == 2 and run["tokens_input"] == 2200 and run["cost_usd"] == pytest.approx(0.0053)
    assert run["duration_s"] == pytest.approx(42.5)


def test_analyze_runs_reads_the_march_archive_and_new_runs_side_by_side(tmp_path, capsys):
    archived = analyze_runs.parse_log_file(ARCHIVE / "arena_rindler_vhlistings_20260331_002827.log")
    assert archived["agent"] == "RINDLER" and archived["scenario"] == "vhlistings_bundle_promo"
    assert archived["judge_verdict"] == "PASS" and archived["model"] is None and archived["steps"] > 0

    scenario = get_scenario("vhlistings_bundle_promo")
    agent = DummyAgent(run_id="r2", goal=scenario.goal, lane="RINDLER")
    sample_events(agent)
    arena.save_log(agent, {"success": False}, 10.0, scenario, arena.calculate_totals(agent.telemetry_events),
                   judge_result={"verdict": "FAIL", "reason": "promo rejected"}, log_dir=str(tmp_path),
                   run_info={"model": "claude-sonnet-5-5", "max_steps": 30})
    analyze_runs.main(["--log-dir", str(ARCHIVE), "--log-dir", str(tmp_path), "--scenarios", "vhlistings_bundle_promo",
                       "--agents", "RINDLER"])
    out = capsys.readouterr().out
    rows = [l for l in out.splitlines() if l.startswith("| vhlistings_bundle_promo")]
    assert len(rows) == 2  # March (model "-") and the new run are separate rows
    assert any("| -" in r and "| 66" in r for r in rows)
    assert any("claude-sonnet-5-5" in r and "| 1 " in r and "0%" in r for r in rows)


def test_arena_cli_lists_and_validates(capsys):
    import asyncio

    assert asyncio.run(arena.main(["--list-agents"])) == 0
    out = capsys.readouterr().out
    assert "BROWSERUSE" in out and "RINDLER" in out and "STEEL" not in out
    with pytest.raises(SystemExit):
        asyncio.run(arena.main(["--agent", "STEEL", "--scenario", "google_search"]))
    args = arena.build_parser().parse_args(["--agent", "rindler", "--scenario", "x"])
    assert args.agent == "RINDLER" and args.max_steps == 30 and args.model is None
    assert arena.build_parser().parse_args(["--llm", "claude-haiku-5-5"]).model == "claude-haiku-5-5"


# ---------------------------------------------------------------------------
# BrowserUse arm with a fake browser-use Agent
# ---------------------------------------------------------------------------


class FakeSummary:
    def __init__(self, prompt, cached, completion):
        self.total_prompt_tokens = prompt
        self.total_prompt_cached_tokens = cached
        self.total_prompt_cache_creation_tokens = 0
        self.total_completion_tokens = completion


class FakeHistory:
    def __init__(self, done=True, success=True, final="Iron Chain Belt, $29.00"):
        self._actions = []
        self._done, self._success, self._final = done, success, final

    def model_actions(self):
        return self._actions

    def extracted_content(self):
        return ["page text"] if self._actions else []

    def is_done(self):
        return self._done

    def is_successful(self):
        return self._success

    def final_result(self):
        return self._final if self._done else None


class FakeTokenService:
    def __init__(self):
        self.summary = FakeSummary(0, 0, 0)

    async def get_usage_summary(self):
        return self.summary


class FakeAgent:
    """Calls the step hooks the way browser-use does and grows a token counter."""

    instances = []

    def __init__(self, *, steps=3, done=True, **kwargs):
        self.kwargs = kwargs
        self.history = FakeHistory(done=done)
        self.token_cost_service = FakeTokenService()
        self.steps = steps
        FakeAgent.instances.append(self)

    async def run(self, max_steps, on_step_start, on_step_end):
        self.max_steps = max_steps
        for i in range(min(self.steps, max_steps)):
            await on_step_start(self)
            self.history._actions.append({["navigate", "click", "done"][i % 3]: {"index": i}})
            s = self.token_cost_service.summary
            self.token_cost_service.summary = FakeSummary(s.total_prompt_tokens + 1000, s.total_prompt_cached_tokens + 400,
                                                          s.total_completion_tokens + 100)
            await on_step_end(self)
        return self.history


@pytest.fixture
def no_browser(monkeypatch, tmp_path):
    import adapters.browseruse_agent as bua

    monkeypatch.setattr(bua, "browser_profile", lambda viewport=None: object())
    monkeypatch.setattr(bua, "agent_files_dir", lambda profile: str(tmp_path))
    monkeypatch.setattr(bua, "cleanup_profile", lambda profile: None)
    monkeypatch.setattr(llm, "agent_llm", lambda model=None, **k: f"chat:{model}")
    FakeAgent.instances.clear()


async def test_browseruse_arm_logs_real_per_step_tokens(no_browser):
    agent = BrowserUseTelemetricAgent(run_id="r", goal="Find a chain belt", max_steps=30,
                                      agent_factory=lambda **kw: FakeAgent(**kw))
    result = await agent.run(start_url="https://vhlistings.com")
    fake = FakeAgent.instances[0]
    assert fake.kwargs["initial_actions"] == [{"navigate": {"url": "https://vhlistings.com", "new_tab": False}}]
    assert fake.kwargs["use_judge"] is False and fake.kwargs["llm"] == "chat:claude-sonnet-5-5"
    assert fake.kwargs["task"] == "Find a chain belt" and fake.max_steps == 30
    assert result["success"] is True and result["final_extraction"] == "Iron Chain Belt, $29.00"
    assert result["steps"] == 3 and result["errors_detected"] == []

    ends = [e for e in agent.telemetry_events if e["event_type"] == "step_end"]
    starts = [e for e in agent.telemetry_events if e["event_type"] == "step_start"]
    assert [e["action_type"] for e in ends] == ["navigate", "click", "done"]
    assert [e["action_type"] for e in starts] == ["navigate", "click", "done"]
    # browser-use's prompt total includes cache reads; each step used 1000 prompt + 100 output.
    assert all(e["tokens_input"] == 1000 and e["tokens_output"] == 100 for e in ends)
    assert all(e["tokens_cache_read"] == 400 for e in ends)
    per_step = llm.Usage(input_tokens=600, output_tokens=100, cache_read_input_tokens=400).cost_usd("claude-sonnet-5-5")
    assert sum(e["cost_usd"] for e in ends) == pytest.approx(3 * per_step)


async def test_browseruse_arm_reports_running_out_of_steps(no_browser):
    agent = BrowserUseTelemetricAgent(run_id="r", goal="g", max_steps=2,
                                      agent_factory=lambda **kw: FakeAgent(steps=5, done=False, **kw))
    result = await agent.run(start_url=None)
    assert FakeAgent.instances[0].kwargs["initial_actions"] is None
    assert result["success"] is False and result["steps"] == 2
    assert "Reached max_steps (2) without calling done" in result["errors_detected"]
