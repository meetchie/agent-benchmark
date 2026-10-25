"""Result records, the cache and the summary math (no network, no browser)."""

import json
import subprocess
import sys
from datetime import date

import pytest

from benchcli import results
from cli_helpers import TASK, make_record

TASKS = [dict(TASK, id="a", name="A"), dict(TASK, id="b", name="B")]


def pair(task, bu_kwargs, ri_kwargs):
    return (make_record(task, agent="browseruse", **bu_kwargs), make_record(task, agent="rindler", **ri_kwargs))


def test_record_stats_count_only_numbered_steps():
    from datetime import datetime, timedelta, timezone

    start = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    steps = [
        results.make_step(0, "start_session", duration_ms=500),  # the session start is not a model step
        results.make_step(1, "view_cart", tokens_input=800, tokens_output=40, tokens_cache_read=300, cost_usd=0.004),
        results.make_step(2, "done", tokens_input=900, tokens_output=60, tokens_cache_read=700, cost_usd=0.005),
    ]
    rec = results.new_result(TASK, agent="rindler", model="m", site="shop", max_steps=12, started_at=start,
                             finished_at=start + timedelta(seconds=20), steps=steps, success=True)
    assert rec["stats"] == {
        "total_steps": 2,
        "total_tokens_input": 1700,
        "total_tokens_output": 100,
        "total_tokens_cache_read": 1000,
        "total_tokens_cache_write": 0,
        "total_cost_usd": 0.009,
        "avg_step_duration_ms": 10000.0,
    }
    assert rec["meta"]["started_at"] == "2026-10-24T12:00:00Z"  # not '+00:00Z'
    assert rec["meta"]["max_steps"] == 12 and rec["meta"]["duration_ms"] == 20000.0


def test_agent_stats_totals_and_rates():
    recs = [
        make_record(TASKS[0], verdict="pass", steps=4, cost=0.02, duration_s=10, judge_cost=0.003),
        make_record(TASKS[1], verdict="fail", steps=6, cost=0.04, duration_s=30, category="wrong_action"),
        make_record(TASKS[1], verdict="error", steps=0, cost=0.0, duration_s=0, category="unknown"),
    ]
    stats = results.agent_stats(recs)
    assert (stats["pass"], stats["fail"], stats["error"]) == (1, 2, 1)
    assert stats["success_rate"] == pytest.approx(0.3333)
    assert stats["total_steps"] == 10 and stats["avg_steps_per_task"] == pytest.approx(3.33)
    assert stats["total_cost_usd"] == pytest.approx(0.06, abs=1e-5) and stats["judge_cost_usd"] == pytest.approx(0.003)
    assert stats["avg_duration_ms"] == pytest.approx(13333.33)
    assert stats["failure_categories"] == {"wrong_action": 1, "unknown": 1}
    assert stats["ran"] is True


def test_winner_rules():
    def winner(bu, ri):
        return results.pick_winner(make_record(agent="browseruse", **bu), make_record(agent="rindler", **ri))

    assert winner(dict(verdict="pass"), dict(verdict="fail")) == "browseruse"
    assert winner(dict(verdict="fail"), dict(verdict="pass", steps=30)) == "rindler"
    # both passed: fewer steps, then lower cost, then a tie
    assert winner(dict(verdict="pass", steps=5), dict(verdict="pass", steps=3)) == "rindler"
    assert winner(dict(verdict="pass", steps=3, cost=0.5), dict(verdict="pass", steps=3, cost=0.1)) == "rindler"
    assert winner(dict(verdict="pass", steps=3, cost=0.1), dict(verdict="pass", steps=3, cost=0.5)) == "browseruse"
    assert winner(dict(verdict="pass", steps=3, cost=0.1), dict(verdict="pass", steps=3, cost=0.1)) == "tie"
    # both failed: giving up early is not a win
    assert winner(dict(verdict="fail", steps=2), dict(verdict="fail", steps=9)) == "tie"
    assert winner(dict(verdict="error", steps=0), dict(verdict="fail", steps=9)) == "tie"


def test_comparison_deltas_are_rindler_relative_to_browseruse():
    bu = {"success_rate": 0.5, "avg_steps_per_task": 20.0, "avg_duration_ms": 100000.0, "avg_cost_per_task_usd": 0.5}
    ri = {"success_rate": 0.75, "avg_steps_per_task": 5.0, "avg_duration_ms": 25000.0, "avg_cost_per_task_usd": 0.05}
    assert results.compare_arms(bu, ri) == {
        "success_rate_delta": 0.25,
        "avg_steps_reduction": 0.75,
        "avg_duration_reduction": 0.75,
        "avg_cost_reduction": 0.9,
    }
    # an arm that used more shows a negative reduction; a zero baseline is left out
    worse = dict(ri, avg_steps_per_task=40.0)
    assert results.compare_arms(bu, worse)["avg_steps_reduction"] == -1.0
    assert "avg_cost_reduction" not in results.compare_arms(dict(bu, avg_cost_per_task_usd=0), ri)


def test_summary_with_both_arms():
    bu = [make_record(TASKS[0], agent="browseruse", verdict="fail", steps=9, cost=0.4, category="max_steps_exceeded"),
          make_record(TASKS[1], agent="browseruse", verdict="pass", steps=7, cost=0.3)]
    ri = [make_record(TASKS[0], agent="rindler", verdict="pass", steps=3, cost=0.04),
          make_record(TASKS[1], agent="rindler", verdict="pass", steps=7, cost=0.05)]
    summary = results.build_summary("shop", "shop.example.com", TASKS, bu, ri, model="claude-sonnet-5-5",
                                    judge_model="claude-sonnet-5-5", day=date(2026, 10, 24))
    assert summary["benchmark"] == {
        "site": "shop", "domain": "shop.example.com", "date": "2026-10-24", "model": "claude-sonnet-5-5",
        "judge_model": "claude-sonnet-5-5", "total_tasks": 2, "arms_run": {"browseruse": True, "rindler": True},
    }
    assert summary["browseruse"]["success_rate"] == 0.5 and summary["rindler"]["success_rate"] == 1.0
    assert [(t["task_id"], t["winner"]) for t in summary["per_task"]] == [("a", "rindler"), ("b", "rindler")]
    assert summary["comparison"]["success_rate_delta"] == 0.5
    assert summary["comparison"]["winner_by_task"] == {"a": "rindler", "b": "rindler"}
    assert summary["comparison"]["avg_cost_reduction"] == pytest.approx(1 - 0.045 / 0.35, abs=1e-3)
    assert set(summary["per_task"][0]["rindler"]) == {"verdict", "steps", "duration_ms", "cost_usd"}


def test_summary_with_one_arm_not_run_has_no_comparison():
    bu = [make_record(t, agent="browseruse", verdict="pass") for t in TASKS]
    ri = [results.skipped_result(t, agent="rindler", model="m", site="shop", max_steps=12, reason="not run")
          for t in TASKS]
    summary = results.build_summary("shop", "d", TASKS, bu, ri, model="m", judge_model="m")
    assert summary["benchmark"]["arms_run"] == {"browseruse": True, "rindler": False}
    assert summary["rindler"]["ran"] is False and summary["rindler"]["total_steps"] == 0
    assert summary["comparison"] == {}
    assert [t["winner"] for t in summary["per_task"]] == [None, None]
    assert "not run" in results.format_summary(summary)


def test_cache_requires_the_same_model_and_step_budget(tmp_path):
    rdir = results.results_dir_for(tmp_path, "shop", date(2026, 10, 24))
    assert rdir.name == "shop-2026-10-24" and (rdir / "rindler" / "screenshots").is_dir()
    rec = make_record(TASK, agent="rindler", verdict="pass", max_steps=12)
    path = results.save_result(rdir, rec)
    assert path == rdir / "rindler" / "task-t1.json"
    assert results.load_cached(rdir, "rindler", "t1", model="claude-sonnet-5-5", max_steps=12)["result"]["verdict"] == "pass"
    assert results.load_cached(rdir, "rindler", "t1", model="claude-haiku-5-5", max_steps=12) is None
    assert results.load_cached(rdir, "rindler", "t1", model="claude-sonnet-5-5", max_steps=30) is None
    assert results.load_cached(rdir, "rindler", "nope", model="claude-sonnet-5-5", max_steps=12) is None
    path.write_text("{not json")
    assert results.load_cached(rdir, "rindler", "t1", model="claude-sonnet-5-5", max_steps=12) is None


def test_a_skipped_stand_in_is_never_loaded_as_a_cached_result(tmp_path):
    rdir = results.results_dir_for(tmp_path, "shop")
    stand_in = results.skipped_result(TASK, agent="browseruse", model="m", site="shop", max_steps=12, reason="r")
    results.save_result(rdir, stand_in)
    assert results.load_cached(rdir, "browseruse", "t1", model="m", max_steps=12) is None


def test_visualize_draws_every_chart_from_the_new_summary(tmp_path):
    """visualize.py reads summary.json; run it for real on a two-arm and a one-arm summary."""
    from pathlib import Path

    cli = Path(__file__).resolve().parent.parent
    bu = [make_record(t, agent="browseruse", verdict="fail", steps=9, cost=0.4, category="max_steps_exceeded") for t in TASKS]
    ri = [make_record(t, agent="rindler", verdict="pass", steps=3, cost=0.04) for t in TASKS]
    both = results.build_summary("shop", "d", TASKS, bu, ri, model="m", judge_model="m")
    one_arm = results.build_summary(
        "shop", "d", TASKS, bu,
        [results.skipped_result(t, agent="rindler", model="m", site="shop", max_steps=12, reason="r") for t in TASKS],
        model="m", judge_model="m")

    for name, summary, expected in (
        ("both", both, {"success_rate.png", "steps_per_task.png", "duration_per_task.png", "cost_per_task.png",
                        "radar_comparison.png", "token_usage.png", "failure_categories_browseruse.png"}),
        ("one", one_arm, {"success_rate.png", "token_usage.png", "failure_categories_browseruse.png"}),
    ):
        rdir = tmp_path / name
        rdir.mkdir()
        results.write_summary(rdir, summary)
        proc = subprocess.run([sys.executable, str(cli / "visualize.py"), str(rdir)], capture_output=True, text=True,
                              timeout=120)
        assert proc.returncode == 0, proc.stderr
        assert {p.name for p in (rdir / "charts").glob("*.png")} == expected
