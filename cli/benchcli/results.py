"""The per-task result record, the on-disk cache and summary.json.

Layout of one run (a day's results for one site are reused, so a run can be resumed and
the two arms can be run in separate commands):

    cli/results/<site>-<date>/
        browseruse/task-<id>.json     one record per task (see ``new_result``)
        rindler/task-<id>.json
        browseruse/screenshots/       last page of a run that did not succeed
        rindler/screenshots/
        summary.json                  per-arm totals, per-task rows and the comparison
        charts/                       written by visualize.py

A record keeps the March shape (meta, result, stats, steps, failure_screenshots) plus
``meta.max_steps``, ``result.final_report``, cache-token counts in ``stats``, ``judge`` (who graded
it and what that cost), ``error`` (why a run stopped early) and, on a BrowserUse step, ``actions``
(every action browser-use ran in it, see browseruse_arm).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

AGENTS = ("browseruse", "rindler")

FAILURE_CATEGORIES = [
    "timeout", "wrong_action", "stuck_in_loop", "site_error",
    "auth_failure", "element_not_found", "navigation_failure",
    "max_steps_exceeded", "rate_limited", "unknown",
]


def utc_iso(moment: datetime | None = None) -> str:
    """UTC as YYYY-MM-DDTHH:MM:SSZ. The March logs wrote '+00:00Z', which is not a timestamp."""
    moment = moment or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def make_step(
    step: int,
    action: str | None,
    *,
    action_args: dict[str, Any] | None = None,
    started_at: str | None = None,
    duration_ms: float = 0.0,
    tokens_input: int = 0,
    tokens_output: int = 0,
    tokens_cache_read: int = 0,
    tokens_cache_write: int = 0,
    cost_usd: float = 0.0,
    observation: str | None = None,
    error: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """One row of a run's step log. ``tokens_input`` counts every prompt token, cache reads included."""
    row = {
        "step": step,
        "action": action,
        "action_args": action_args or {},
        "started_at": started_at or utc_iso(),
        "duration_ms": round(float(duration_ms), 2),
        "tokens_input": int(tokens_input),
        "tokens_output": int(tokens_output),
        "tokens_cache_read": int(tokens_cache_read),
        "tokens_cache_write": int(tokens_cache_write),
        "cost_usd": round(float(cost_usd), 6),
        "observation": observation,
        "screenshot_path": None,
        "error": error,
    }
    row.update(extra)
    return row


def new_result(
    task: dict[str, Any],
    *,
    agent: str,
    model: str,
    site: str,
    max_steps: int,
    started_at: datetime,
    finished_at: datetime,
    steps: list[dict[str, Any]],
    success: bool,
    final_report: str | None = None,
    error: str | None = None,
    failure_screenshots: list[str] | None = None,
) -> dict[str, Any]:
    """The record for one finished (or stopped) run. ``steps`` may start with a step 0
    (the session start); only steps numbered 1 and up count towards ``total_steps``."""
    duration_ms = (finished_at - started_at).total_seconds() * 1000
    counted = [s for s in steps if s["step"] >= 1]
    return {
        "meta": {
            "task_id": task["id"],
            "task_name": task["name"],
            "agent": agent,
            "model": model,
            "site": site,
            "start_url": task["start_url"],
            "goal": task["goal"],
            "success_criteria": task["success_criteria"],
            "max_steps": max_steps,
            "started_at": utc_iso(started_at),
            "finished_at": utc_iso(finished_at),
            "duration_ms": round(duration_ms, 2),
        },
        "result": {
            "success": bool(success),
            "verdict": None,  # set by the judge
            "judge_reasoning": None,
            "failure_category": None,
            "final_report": final_report,
        },
        "stats": {
            "total_steps": len(counted),
            "total_tokens_input": sum(s["tokens_input"] for s in steps),
            "total_tokens_output": sum(s["tokens_output"] for s in steps),
            "total_tokens_cache_read": sum(s.get("tokens_cache_read", 0) for s in steps),
            "total_tokens_cache_write": sum(s.get("tokens_cache_write", 0) for s in steps),
            "total_cost_usd": round(sum(s["cost_usd"] for s in steps), 6),
            "avg_step_duration_ms": round(duration_ms / len(counted), 2) if counted else 0,
        },
        "steps": steps,
        "failure_screenshots": failure_screenshots or [],
        "error": error,
    }


def skipped_result(task: dict[str, Any], *, agent: str, model: str, site: str, max_steps: int, reason: str) -> dict[str, Any]:
    """Stand-in for an arm that was not run (--rindler-only / --browseruse-only) and has no cache."""
    now = datetime.now(timezone.utc)
    record = new_result(task, agent=agent, model=model, site=site, max_steps=max_steps,
                        started_at=now, finished_at=now, steps=[], success=False)
    record["result"]["verdict"] = "skipped"
    record["result"]["judge_reasoning"] = reason
    return record


def is_skipped(record: dict[str, Any]) -> bool:
    return record["result"].get("verdict") == "skipped"


# Results directory and cache


def results_dir_for(results_root: Path, site: str, day: date | None = None) -> Path:
    path = results_root / f"{site}-{(day or date.today()).isoformat()}"
    for sub in ("browseruse/screenshots", "rindler/screenshots", "charts"):
        (path / sub).mkdir(parents=True, exist_ok=True)
    return path


def task_path(results_dir: Path, agent: str, task_id: str) -> Path:
    return results_dir / agent / f"task-{task_id}.json"


def save_result(results_dir: Path, record: dict[str, Any]) -> Path:
    path = task_path(results_dir, record["meta"]["agent"], record["meta"]["task_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, default=str))
    return path


def load_cached(results_dir: Path, agent: str, task_id: str, *, model: str, max_steps: int) -> dict[str, Any] | None:
    """A saved record for this task if it was produced with the same model and step budget.

    A record from another model or budget answers a different question, so it is ignored
    (and will be overwritten) rather than mixed into this run's summary.
    """
    path = task_path(results_dir, agent, task_id)
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    meta = record.get("meta") or {}
    if is_skipped(record) or meta.get("model") != model or meta.get("max_steps") != max_steps:
        return None
    return record


# Summary


def agent_stats(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals and averages over one arm's per-task records (every task counts, run or not)."""
    n = len(results)
    ran = [r for r in results if not is_skipped(r)]
    passes = sum(1 for r in results if r["result"].get("verdict") == "pass")
    errors = sum(1 for r in results if r["result"].get("verdict") == "error")
    total_steps = sum(r["stats"]["total_steps"] for r in results)
    total_dur = sum(r["meta"]["duration_ms"] for r in results)
    total_cost = sum(r["stats"]["total_cost_usd"] for r in results)
    judge_cost = sum((r.get("judge") or {}).get("cost_usd") or 0.0 for r in results)

    fail_cats: dict[str, int] = {}
    for r in results:
        cat = r["result"].get("failure_category")
        if cat:
            fail_cats[cat] = fail_cats.get(cat, 0) + 1

    return {
        "ran": bool(ran),
        "pass": passes,
        "fail": n - passes,  # everything that is not a pass, errors and skipped included
        "error": errors,
        "success_rate": round(passes / n, 4) if n else 0,
        "total_steps": total_steps,
        "avg_steps_per_task": round(total_steps / n, 2) if n else 0,
        "total_duration_ms": round(total_dur, 2),
        "avg_duration_ms": round(total_dur / n, 2) if n else 0,
        "total_cost_usd": round(total_cost, 6),
        "avg_cost_per_task_usd": round(total_cost / n, 6) if n else 0,
        "judge_cost_usd": round(judge_cost, 6),
        "total_tokens_input": sum(r["stats"]["total_tokens_input"] for r in results),
        "total_tokens_output": sum(r["stats"]["total_tokens_output"] for r in results),
        "failure_categories": fail_cats,
    }


def pick_winner(bu: dict[str, Any], ri: dict[str, Any]) -> str:
    """Per-task winner: the run that passed; if both passed, fewer steps, then lower cost.

    Two failures are a tie: March picked the one with fewer steps, which rewards giving up early.
    """
    bu_v, ri_v = bu["result"].get("verdict"), ri["result"].get("verdict")
    if bu_v == "pass" and ri_v != "pass":
        return "browseruse"
    if ri_v == "pass" and bu_v != "pass":
        return "rindler"
    if bu_v != "pass":
        return "tie"
    bu_steps, ri_steps = bu["stats"]["total_steps"], ri["stats"]["total_steps"]
    if bu_steps != ri_steps:
        return "browseruse" if bu_steps < ri_steps else "rindler"
    bu_cost, ri_cost = bu["stats"]["total_cost_usd"], ri["stats"]["total_cost_usd"]
    if bu_cost != ri_cost:
        return "browseruse" if bu_cost < ri_cost else "rindler"
    return "tie"


def compare_arms(bu_stats: dict[str, Any], ri_stats: dict[str, Any]) -> dict[str, Any]:
    """Rindler relative to BrowserUse. Positive reductions mean Rindler used less."""
    comparison = {"success_rate_delta": round(ri_stats["success_rate"] - bu_stats["success_rate"], 4)}
    for key, field in (("avg_steps_reduction", "avg_steps_per_task"),
                       ("avg_duration_reduction", "avg_duration_ms"),
                       ("avg_cost_reduction", "avg_cost_per_task_usd")):
        if bu_stats[field] > 0:
            comparison[key] = round(1 - ri_stats[field] / bu_stats[field], 4)
    return comparison


def build_summary(
    site: str,
    domain: str,
    tasks: list[dict[str, Any]],
    bu_results: list[dict[str, Any]],
    ri_results: list[dict[str, Any]],
    *,
    model: str,
    judge_model: str,
    day: date | None = None,
) -> dict[str, Any]:
    bu_stats, ri_stats = agent_stats(bu_results), agent_stats(ri_results)
    both = bu_stats["ran"] and ri_stats["ran"]

    per_task = []
    winners = {}
    for task, bu, ri in zip(tasks, bu_results, ri_results):
        winner = pick_winner(bu, ri) if both else None
        per_task.append({
            "task_id": task["id"],
            "browseruse": _task_row(bu),
            "rindler": _task_row(ri),
            "winner": winner,
        })
        if winner:
            winners[task["id"]] = winner

    comparison = compare_arms(bu_stats, ri_stats) if both else {}
    if both:
        comparison["winner_by_task"] = winners

    return {
        "benchmark": {
            "site": site,
            "domain": domain,
            "date": (day or date.today()).isoformat(),
            "model": model,
            "judge_model": judge_model,
            "total_tasks": len(tasks),
            "arms_run": {"browseruse": bu_stats["ran"], "rindler": ri_stats["ran"]},
        },
        "browseruse": bu_stats,
        "rindler": ri_stats,
        "comparison": comparison,
        "per_task": per_task,
    }


def _task_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": record["result"].get("verdict") or "error",
        "steps": record["stats"]["total_steps"],
        "duration_ms": record["meta"]["duration_ms"],
        "cost_usd": record["stats"]["total_cost_usd"],
    }


def write_summary(results_dir: Path, summary: dict[str, Any]) -> Path:
    path = results_dir / "summary.json"
    path.write_text(json.dumps(summary, indent=2))
    return path


def format_summary(summary: dict[str, Any]) -> str:
    bu, ri = summary["browseruse"], summary["rindler"]
    arms = summary["benchmark"]["arms_run"]
    lines = [
        "=" * 60,
        "  SUMMARY",
        "=" * 60,
        f"  {'Metric':<25} {'BrowserUse':>12} {'Rindler':>12}",
        f"  {'-' * 49}",
    ]

    def cell(arm: str, value: str) -> str:
        return value if arms[arm] else "not run"

    rows = [
        ("Success Rate", f"{bu['success_rate']:.0%}", f"{ri['success_rate']:.0%}"),
        ("Avg Steps", f"{bu['avg_steps_per_task']:.1f}", f"{ri['avg_steps_per_task']:.1f}"),
        ("Avg Duration (s)", f"{bu['avg_duration_ms'] / 1000:.1f}", f"{ri['avg_duration_ms'] / 1000:.1f}"),
        ("Avg Cost ($)", f"{bu['avg_cost_per_task_usd']:.4f}", f"{ri['avg_cost_per_task_usd']:.4f}"),
        ("Total Cost ($)", f"{bu['total_cost_usd']:.4f}", f"{ri['total_cost_usd']:.4f}"),
        ("Judge Cost ($)", f"{bu['judge_cost_usd']:.4f}", f"{ri['judge_cost_usd']:.4f}"),
    ]
    for label, b, r in rows:
        lines.append(f"  {label:<25} {cell('browseruse', b):>12} {cell('rindler', r):>12}")
    lines.append("=" * 60)
    return "\n".join(lines)
