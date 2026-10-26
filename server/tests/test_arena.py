"""arena.py: judge prompt and verdict handling (mocked model), log writing, analyze_runs,
and the BrowserUse arm's bookkeeping with a fake browser-use Agent. No network."""

from __future__ import annotations

import asyncio
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
from tests import browser_use_history as bu

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
    # A step reads as the call it made, arguments included; one logged without any keeps its name.
    assert 'Actions taken:\nStep 1: search_products(query="chain belt")\nStep 2: navigation\n' in prompt
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
    # The arguments the judge read are in the log too.
    assert events[0]["action_data"] == {"query": "chain belt"} and "action_data" not in events[1]

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
    march = next(r for r in rows if "claude-sonnet-5-5" not in r)
    new_run = next(r for r in rows if "claude-sonnet-5-5" in r)
    assert [c.strip() for c in march.split("|")[3:5]] == ["-", "66"]
    assert march.split("|")[5].strip() == "65/66 (98.5%)"   # Judge Pass, then Reported (the agents' own claims)
    assert march.split("|")[6].strip() == "66/66 (100.0%)"
    assert new_run.split("|")[5].strip() == "0/1 (0.0%)"      # the judge failed the new run


def run_row(agent, verdict="PASS", success=True, when=None, scenario="s", model=None, cost=0.1):
    return {"agent": agent, "scenario": scenario, "model": model, "success": success, "judge_verdict": verdict,
            "steps": 4, "cost_usd": cost, "duration_s": 10.0, "timestamp": when}


def test_table_shows_counts_with_percentages_and_names_the_agents_own_claim_reported(capsys):
    runs = [run_row("RINDLER", "PASS"), run_row("RINDLER", "PASS"), run_row("RINDLER", "FAIL"),
            run_row("RINDLER", "ERROR"), run_row("BROWSERUSE", "FAIL", success=True), run_row("BROWSERUSE", None, success=False)]
    table = analyze_runs.format_table(analyze_runs.aggregate_runs(runs))
    header = table.splitlines()[0]
    assert "Success" not in header
    assert [c.strip() for c in header.split("|")[4:7]] == ["Runs", "Judge Pass", "Reported"]
    rindler = next(l for l in table.splitlines() if "RINDLER" in l)
    assert "2/3 (66.7%)" in rindler and "4/4 (100.0%)" in rindler  # ERROR is not judged, but the run counts
    browseruse = next(l for l in table.splitlines() if "BROWSERUSE" in l)
    assert "0/1 (0.0%)" in browseruse and "1/2 (50.0%)" in browseruse
    notes = analyze_runs.table_notes(analyze_runs.aggregate_runs(runs))
    assert "fewer judged runs than runs" in notes
    assert "fewer judged" not in analyze_runs.table_notes(analyze_runs.aggregate_runs([run_row("RINDLER")]))
    assert "n/a" in analyze_runs.format_table(analyze_runs.aggregate_runs([run_row("RINDLER", None)]))


def test_parse_when_takes_a_date_or_a_date_and_time():
    from datetime import datetime

    assert analyze_runs.parse_when("2026-03-31") == datetime(2026, 3, 31)
    assert analyze_runs.parse_when("2026-03-31", end_of_day=True) > datetime(2026, 3, 31, 23, 59, 59)
    assert analyze_runs.parse_when("2026-03-31 00:28:27") == datetime(2026, 3, 31, 0, 28, 27)
    assert analyze_runs.parse_when("2026-03-31T00:28:27") == datetime(2026, 3, 31, 0, 28, 27)
    assert analyze_runs.parse_when("2026-03-31 00:28") == datetime(2026, 3, 31, 0, 28)
    assert analyze_runs.parse_when("2026-03-31 00:28", end_of_day=True) == datetime(2026, 3, 31, 0, 28)
    for bad in ("2026-3-31 x", "31/03/2026", "yesterday", ""):
        with pytest.raises(ValueError):
            analyze_runs.parse_when(bad)


def test_since_and_until_are_inclusive_and_drop_runs_with_no_time():
    from datetime import datetime

    at = lambda h, m, s: run_row("RINDLER", when=datetime(2026, 3, 31, h, m, s))
    runs = [at(0, 28, 26), at(0, 28, 27), at(1, 0, 0), at(23, 59, 59), run_row("RINDLER", when=None)]
    since = analyze_runs.parse_when("2026-03-31 00:28:27")
    assert len(analyze_runs.filter_runs(runs, since=since)) == 3          # not the 00:28:26 one; time-less run dropped
    assert len(analyze_runs.filter_runs(runs, until=analyze_runs.parse_when("2026-03-31", True))) == 4
    assert len(analyze_runs.filter_runs(runs, until=analyze_runs.parse_when("2026-03-31 01:00:00"))) == 3
    assert len(analyze_runs.filter_runs(runs, since=since, until=analyze_runs.parse_when("2026-03-31 01:00:00"))) == 2
    assert len(analyze_runs.filter_runs(runs)) == 5                       # no time limit, nothing dropped
    assert len(analyze_runs.filter_runs(runs, agents="browseruse")) == 0


def test_since_accepts_a_time_on_the_command_line_and_rejects_nonsense(capsys):
    analyze_runs.main(["--log-dir", str(ARCHIVE), "--scenarios", "vhlistings_bundle_promo", "--agents", "RINDLER",
                       "--since", "2026-03-31 00:28:27", "--until", "2026-03-31"])
    assert "| 60 " in capsys.readouterr().out
    analyze_runs.main(["--log-dir", str(ARCHIVE), "--scenarios", "vhlistings_bundle_promo", "--agents", "RINDLER",
                       "--since", "2026-03-31T00:24:15"])
    assert "| 61 " in capsys.readouterr().out  # the 00:24:15 run is the last of the four earlier ones
    with pytest.raises(SystemExit):
        analyze_runs.main(["--since", "last tuesday"])
    assert "not a date" in capsys.readouterr().err


def test_march_headline_prints_59_of_60_against_1_of_60(tmp_path, capsys):
    analyze_runs.main(["--march-headline"])
    out = capsys.readouterr().out
    rows = {l.split("|")[2].strip(): l for l in out.splitlines() if l.startswith("| vhlistings_bundle_promo")}
    assert set(rows) == {"BROWSERUSE", "RINDLER"}
    assert "| 60 " in rows["RINDLER"] and "59/60 (98.3%)" in rows["RINDLER"]
    assert "| 60 " in rows["BROWSERUSE"] and "1/60 (1.7%)" in rows["BROWSERUSE"]
    assert "$0.1366" in rows["RINDLER"] and "$0.7130" in rows["BROWSERUSE"]       # the README's $0.14 vs $0.71
    assert "Headline (judge pass): BROWSERUSE 1/60 (1.7%) vs RINDLER 59/60 (98.3%)" in out
    assert "120 runs" in out and "Warning" not in out
    # The header gives the first and last log of the selected set, not the filter's bounds.
    # (Rindler's last log is 03:24:05; the last BrowserUse one, 06:10:32, ends the set.)
    assert "logs from 2026-03-31 00:28:27 to 06:10:32, 60 runs per agent expected" in out
    assert "23:59:59" not in out

    # The set is exact: 60 per agent, the first Rindler log is 00:28:27 and the four earlier ones are out.
    runs = [analyze_runs.parse_log_file(p) for p in sorted(ARCHIVE.glob("arena_*.log"))]
    picked = analyze_runs.filter_runs(runs, agents=analyze_runs.MARCH_HEADLINE["agents"],
                                      scenarios=analyze_runs.MARCH_HEADLINE["scenario"],
                                      since=analyze_runs.MARCH_HEADLINE["since"], until=analyze_runs.MARCH_HEADLINE["until"])
    rindler = sorted(Path(r["path"]).name for r in picked if r["agent"] == "RINDLER")
    assert len(rindler) == 60
    assert rindler[0] == "arena_rindler_vhlistings_20260331_002827.log" and rindler[-1].endswith("_20260331_032405.log")
    assert sum(r["agent"] == "BROWSERUSE" for r in picked) == 60

    # Newer runs of the same scenario never leak into the March headline, even from a log dir given with it.
    scenario = get_scenario("vhlistings_bundle_promo")
    agent = DummyAgent(run_id="r3", goal=scenario.goal, lane="RINDLER")
    sample_events(agent)
    arena.save_log(agent, {"success": True}, 10.0, scenario, arena.calculate_totals(agent.telemetry_events),
                   judge_result={"verdict": "PASS", "reason": "ok"}, log_dir=str(tmp_path))
    analyze_runs.main(["--march-headline", "--log-dir", str(ARCHIVE), "--log-dir", str(tmp_path)])
    assert "59/60 (98.3%)" in capsys.readouterr().out


def test_time_span_names_the_first_and_last_log():
    from datetime import datetime
    run = lambda *a: {"timestamp": datetime(*a) if a else None}
    one_night = [run(2026, 3, 31, 3, 24, 5), run(2026, 3, 31, 0, 28, 27), run()]
    assert analyze_runs.time_span(one_night) == "2026-03-31 00:28:27 to 03:24:05"
    assert analyze_runs.time_span([run(2026, 3, 30, 23, 0, 0), run(2026, 3, 31, 1, 2, 3)]) == \
        "2026-03-30 23:00:00 to 2026-03-31 01:02:03"
    assert analyze_runs.time_span([run()]) == "no log times"


def test_march_headline_warns_when_the_archive_is_short(tmp_path, capsys):
    for name in ("arena_rindler_vhlistings_20260331_002827.log", "arena_browseruse_vhlistings_20260331_005641.log"):
        (tmp_path / name).write_text((ARCHIVE / name).read_text())
    analyze_runs.main(["--march-headline", "--log-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert "Warning: RINDLER has 1 runs here, the headline uses 60" in out
    assert "Warning: BROWSERUSE has 1 runs here, the headline uses 60" in out


def test_march_headline_is_not_combined_with_other_filters(capsys):
    for extra in (["--agents", "RINDLER"], ["--scenarios", "x"], ["--since", "2026-03-01"], ["--until", "2026-04-01"]):
        with pytest.raises(SystemExit):
            analyze_runs.main(["--march-headline", *extra])
        assert "--march-headline selects its own runs" in capsys.readouterr().err


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
    """browser-use's AgentHistoryList with real history items (tests/browser_use_history.py); only
    whether the run is done, its success flag and its final result are scripted."""

    def __init__(self, done=True, success=True, final="Iron Chain Belt, $29.00"):
        self.history = []
        self._done, self._success, self._final = done, success, final

    def _real(self):
        from browser_use.agent.views import AgentHistoryList

        return AgentHistoryList(history=self.history)

    def model_actions(self):
        return self._real().model_actions()

    def extracted_content(self):
        return self._real().extracted_content()

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

    def __init__(self, *, steps=3, done=True, hang_at=None, script=None, **kwargs):
        self.kwargs = kwargs
        self.history = FakeHistory(done=done)
        self.token_cost_service = FakeTokenService()
        self.steps = len(script) if script is not None else steps
        self.hang_at = hang_at  # a step that never ends (until the run is cancelled)
        # Per step, the history items browser-use adds for it (none for a step it kept no item for).
        self.script = script
        FakeAgent.instances.append(self)

    @staticmethod
    def default_step(i):
        planned = [
            bu.action(navigate={"url": "https://vhlistings.com/", "new_tab": False}),
            bu.action(click={"index": i + 1}),
            bu.action(done={"text": "Iron Chain Belt, $29.00", "success": True}),
        ][i % 3]
        return [bu.history_item([planned], [bu.ActionResult(extracted_content="page text")])]

    async def run(self, max_steps, on_step_start, on_step_end):
        self.max_steps = max_steps
        for i in range(min(self.steps, max_steps)):
            await on_step_start(self)
            if self.hang_at == i + 1:
                await asyncio.sleep(60)
            self.history.history.extend(self.script[i] if self.script is not None else self.default_step(i))
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
    # browser-use's own Ctrl-C handler would os._exit() on a second SIGINT, leaving Chromium up.
    assert fake.kwargs["enable_signal_handler"] is False
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


def ran(*results):
    return [bu.ActionResult(extracted_content=text) for text in results]


async def test_browseruse_steps_reach_the_judge_with_what_they_did(no_browser):
    """A search done by opening the site's search URL has to read as one to the judge, the way
    the Rindler arm's search_products(query=...) does."""
    script = [
        [bu.history_item([bu.action(navigate={"url": "https://vhlistings.com/search?q=belt", "new_tab": False})],
                         ran("Navigated to https://vhlistings.com/search?q=belt"))],
        # browser-use can run several actions in one step.
        [bu.history_item([bu.action(input={"index": 4, "text": "belt", "clear": True}), bu.action(click={"index": 9})],
                         ran("Typed 'belt'", "Clicked a"),
                         elements=[bu.element(" Search\n "), bu.element("Bullet Studded Belt")])],
        [],  # a step browser-use kept no history item for (it timed out inside the agent, say)
        [bu.history_item([bu.action(done={"text": "Cart: Bullet Studded Belt, $30.00 " + "x" * 300, "success": True})],
                         [bu.ActionResult(is_done=True, success=True, extracted_content="Cart: Bullet Studded Belt")])],
    ]
    agent = BrowserUseTelemetricAgent(run_id="r", goal="g", agent_factory=lambda **kw: FakeAgent(script=script, **kw))
    await agent.run(start_url="https://vhlistings.com")

    starts = [e for e in agent.telemetry_events if e["event_type"] == "step_start"]
    # The empty step is not labelled with the action of the step before it.
    assert [e["action_type"] for e in starts] == ["navigate", "click", None, "done"]
    assert starts[0]["action_data"] == [
        {"action": "navigate", "params": {"url": "https://vhlistings.com/search?q=belt", "new_tab": False}}]
    assert starts[1]["action_data"] == [
        {"action": "input", "params": {"index": 4, "text": "belt", "clear": True}, "element": "Search"},
        {"action": "click", "params": {"index": 9}, "element": "Bullet Studded Belt"}]
    assert "action_data" not in starts[2]

    prompt = arena.build_judge_prompt(get_scenario("vhlistings_add_to_cart"), {"success": True, "steps": 4},
                                      agent.telemetry_events)
    lines = prompt.splitlines()
    assert 'Step 1: navigation(url="https://vhlistings.com/search?q=belt", new_tab=false)' in lines
    assert 'Step 2: input(index=4, text="belt", clear=true) on "Search"; click(index=9) on "Bullet Studded Belt"' in lines
    assert "Step 3: no action recorded" in lines
    done = next(line for line in lines if line.startswith("Step 4: "))
    assert done.startswith('Step 4: done(text="Cart: Bullet Studded Belt, $30.00 xxx')
    assert done.endswith("…") and len(done) == len("Step 4: ") + arena.ACTION_TEXT_LIMIT


async def test_the_judge_reads_only_the_actions_browser_use_ran(no_browser):
    """The model plans several actions per step; browser-use runs them in order and skips the
    rest after a page change, a navigation or a failed action. Only the ones it ran (one result
    each) may reach the judge, a failed one with its error, and the step is named after the
    last one that ran."""
    failed = "Failed to click element 9: Node is detached from document. " + "x" * 200
    script = [
        # Typing and Enter ran; Enter loaded the results page, so the click was skipped.
        [bu.history_item([bu.action(input={"index": 4, "text": "belt", "clear": True}),
                          bu.action(send_keys={"keys": "Enter"}), bu.action(click={"index": 9})],
                         ran("Typed 'belt'", "Sent keys: Enter"),
                         elements=[bu.element("Search"), None, bu.element("Bullet Studded Belt")])],
        # The first click failed, so the second never ran.
        [bu.history_item([bu.action(click={"index": 9}), bu.action(click={"index": 15})],
                         [bu.ActionResult(error=failed)],
                         elements=[bu.element("Add to cart"), bu.element("View cart")])],
        # A navigation ends the step: the extract planned after it was skipped.
        [bu.history_item([bu.action(navigate={"url": "https://vhlistings.com/cart", "new_tab": False}),
                          bu.action(extract={"query": "cart rows"})],
                         ran("Navigated to https://vhlistings.com/cart"))],
    ]
    agent = BrowserUseTelemetricAgent(run_id="r", goal="g", agent_factory=lambda **kw: FakeAgent(script=script, done=False, **kw))
    await agent.run(start_url="https://vhlistings.com")

    starts = [e for e in agent.telemetry_events if e["event_type"] == "step_start"]
    ends = [e for e in agent.telemetry_events if e["event_type"] == "step_end"]
    assert [e["action_type"] for e in starts] == ["send_keys", "click", "navigate"]
    assert [e["action_type"] for e in ends] == ["send_keys", "click", "navigate"]
    assert starts[0]["action_data"] == [
        {"action": "input", "params": {"index": 4, "text": "belt", "clear": True}, "element": "Search"},
        {"action": "send_keys", "params": {"keys": "Enter"}}]
    assert starts[1]["action_data"] == [
        {"action": "click", "params": {"index": 9}, "element": "Add to cart", "error": failed}]
    assert starts[2]["action_data"] == [
        {"action": "navigate", "params": {"url": "https://vhlistings.com/cart", "new_tab": False}}]
    # A step that read nothing new does not carry the page text of the step before it.
    assert ends[1]["observation_hash"] is None and ends[0]["observation_hash"] != ends[2]["observation_hash"]

    prompt = arena.build_judge_prompt(get_scenario("vhlistings_add_to_cart"), {"success": False, "steps": 3},
                                      agent.telemetry_events)
    lines = prompt.splitlines()
    assert 'Step 1: input(index=4, text="belt", clear=true) on "Search"; send_keys(keys="Enter")' in lines
    error = "Failed to click element 9: Node is detached from document. xxxxxxxxxxxxxxxxxxxx…"
    assert len(error) == arena.ACTION_ERROR_LIMIT
    assert f'Step 2: click(index=9) on "Add to cart" -> error: {error}' in lines
    assert 'Step 3: navigation(url="https://vhlistings.com/cart", new_tab=false)' in lines
    for skipped in ("Bullet Studded Belt", "index=15", "View cart", "extract(", "cart rows"):
        assert skipped not in prompt


async def test_an_action_on_an_element_that_was_gone_reads_as_not_run(no_browser):
    """browser-use answers a click or typing on an element index that is no longer on the page
    with a result that is not an error, only a message (browser_use/tools/service.py). The
    judge must not read that click as made."""
    script = [
        # The first click found nothing to click; browser-use went on to the second.
        [bu.history_item([bu.action(click={"index": 9}), bu.action(click={"index": 15})],
                         ran("Element index 9 not available - page may have changed. Try refreshing browser state.",
                             "Clicked button 'View cart'"),
                         elements=[bu.element("Add to cart"), bu.element("View cart")])],
        [bu.history_item([bu.action(input={"index": 4, "text": "belt", "clear": True})],
                         ran("Element index 4 not available - page may have changed. Try refreshing browser state."))],
    ]
    agent = BrowserUseTelemetricAgent(run_id="r", goal="g", agent_factory=lambda **kw: FakeAgent(script=script, done=False, **kw))
    await agent.run(start_url="https://vhlistings.com")

    starts = [e for e in agent.telemetry_events if e["event_type"] == "step_start"]
    assert starts[0]["action_data"] == [
        {"action": "click", "params": {"index": 9}, "element": "Add to cart", "not_run": "element 9 was not available"},
        {"action": "click", "params": {"index": 15}, "element": "View cart"}]
    assert starts[1]["action_data"] == [
        {"action": "input", "params": {"index": 4, "text": "belt", "clear": True}, "not_run": "element 4 was not available"}]

    prompt = arena.build_judge_prompt(get_scenario("vhlistings_add_to_cart"), {"success": False, "steps": 2},
                                      agent.telemetry_events)
    lines = prompt.splitlines()
    assert ('Step 1: click(index=9) on "Add to cart" -> not run: element 9 was not available; '
            'click(index=15) on "View cart"') in lines
    assert 'Step 2: input(index=4, text="belt", clear=true) -> not run: element 4 was not available' in lines


async def test_browseruse_arm_cleans_up_when_the_run_is_cancelled(no_browser, monkeypatch):
    """Ctrl-C cancels the run (entrypoint.run_cli); the profile, and any browser on it, still go."""
    import adapters.browseruse_agent as bua

    cleaned = []
    monkeypatch.setattr(bua, "cleanup_profile", lambda profile: cleaned.append(profile))

    class Hangs(FakeAgent):
        async def run(self, max_steps, on_step_start, on_step_end):
            await on_step_start(self)
            await asyncio.sleep(30)

    agent = BrowserUseTelemetricAgent(run_id="r", goal="g", agent_factory=lambda **kw: Hangs(**kw))
    task = asyncio.create_task(agent.run(start_url=None))
    while not Hangs.instances:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(cleaned) == 1


async def test_browseruse_arm_reports_running_out_of_steps(no_browser):
    agent = BrowserUseTelemetricAgent(run_id="r", goal="g", max_steps=2,
                                      agent_factory=lambda **kw: FakeAgent(steps=5, done=False, **kw))
    result = await agent.run(start_url=None)
    assert FakeAgent.instances[0].kwargs["initial_actions"] is None
    assert result["success"] is False and result["steps"] == 2
    assert "Reached max_steps (2) without calling done" in result["errors_detected"]


async def test_a_timed_out_browseruse_run_is_not_reported_as_out_of_steps(no_browser):
    agent = BrowserUseTelemetricAgent(run_id="r", goal="g", max_steps=30, timeout_s=1,
                                      agent_factory=lambda **kw: FakeAgent(done=False, hang_at=2, **kw))
    result = await agent.run(start_url=None)
    assert result["errors_detected"] == ["run stopped after the 1s time limit"]  # this text reaches the judge
    assert result["message"] == "Agent did not finish within the 1s time limit"
    assert result["success"] is False
