"""Phase 1: browser-use on a local headless Chromium, with no knowledge of the site.

The agent gets the task's goal text verbatim and the same step budget as the Rindler arm. The
browser is the repo's one local profile (browser_env) and the model is llm.agent_llm(model), so it
runs on the Anthropic key alone. A step's tokens are the real difference of browser-use's own token
counter, so per-step costs add up to the run's cost. A step records only the actions browser-use ran
(server/browser_use_actions.py), so the judge never reads an action the model planned and
browser-use skipped.
"""

from __future__ import annotations

import asyncio
import base64
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import llm
import browser_env
from browser_use_actions import ERROR_TEXT_LIMIT, ran_actions

from .results import make_step, new_result, utc_iso

OBSERVATION_CHARS = 300


def usage_delta(now: llm.Usage, before: llm.Usage) -> llm.Usage:
    return llm.Usage(
        input_tokens=max(now.input_tokens - before.input_tokens, 0),
        output_tokens=max(now.output_tokens - before.output_tokens, 0),
        cache_read_input_tokens=max(now.cache_read_input_tokens - before.cache_read_input_tokens, 0),
        cache_creation_input_tokens=max(now.cache_creation_input_tokens - before.cache_creation_input_tokens, 0),
    )


def prompt_tokens(usage: llm.Usage) -> int:
    """Every prompt token of the usage: uncached input plus cache reads and writes."""
    return usage.input_tokens + usage.cache_read_input_tokens + usage.cache_creation_input_tokens


def _history_items(history: Any) -> list:
    try:
        return list(history.history)
    except Exception:
        return []


def _step_fields(items: list) -> dict[str, Any]:
    """The step-log fields of one step, from the history items browser-use added for it.

    ``actions`` lists only the actions browser-use ran (see browser_use_actions.ran_actions), with
    the name of the element each one targeted, a failed one's error, and a not_run mark on one whose
    element was gone from the page. ``action`` and ``action_args`` are the last of them.
    ``observation`` is the last text this step's results returned, never an earlier step's, and
    ``error`` an error with no action behind it (the step's model call failed).
    """
    actions = ran_actions(items)
    last = actions[-1] if actions else None
    observations: list[str] = []
    errors: list[str] = []
    for item in items:
        planned = list(getattr(getattr(item, "model_output", None), "action", None) or [])
        results = list(getattr(item, "result", None) or [])
        observations += [str(r.extracted_content) for r in results if getattr(r, "extracted_content", None)]
        errors += [" ".join(str(r.error).split()) for r in results[len(planned):] if getattr(r, "error", None)]
    return {
        "action": last["action"] if last else None,
        "action_args": {last["action"]: last["params"]} if last else {},
        "actions": actions,
        "observation": observations[-1][:OBSERVATION_CHARS] if observations else None,
        "error": errors[-1][:ERROR_TEXT_LIMIT] if errors else None,
    }


def _save_last_screenshot(history: Any, results_dir: Path, task_id: str) -> str | None:
    """Write the run's last screenshot (browser-use keeps them base64) and return its relative path."""
    try:
        shots = history.screenshots(n_last=1, return_none_if_not_screenshot=False)
        data = base64.b64decode(shots[-1])
    except Exception:
        return None
    ext = "jpg" if data[:3] == b"\xff\xd8\xff" else "png"
    relative = f"screenshots/task-{task_id}-final.{ext}"
    target = results_dir / "browseruse" / relative
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError:
        return None
    return relative


def _succeeded(history: Any, stopped: bool) -> bool:
    """browser-use's own verdict: done and successful, and not cut short."""
    if stopped:
        return False
    try:
        return bool(history.is_done()) and bool(history.is_successful())
    except Exception:
        return False


async def run_browseruse_task(
    task: dict[str, Any],
    *,
    model: str,
    max_steps: int,
    results_dir: Path,
    site: str,
    timeout_s: float | None = None,
    agent_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run one task and return its result record (not yet judged, not yet saved).

    ``agent_factory`` replaces ``browser_use.Agent`` in tests.
    """
    task_id = task["id"]
    print(f"  Task: {task['name']} ({task_id})")
    print(f"  Goal: {task['goal'].strip()[:80]}...")

    started_at = datetime.now(timezone.utc)
    steps: list[dict[str, Any]] = []
    # "recorded": how many history items browser-use had when the current step started.
    state = {"index": 0, "t0": time.monotonic(), "ts": utc_iso(), "counted": llm.Usage(), "recorded": 0}
    error: str | None = None
    agent: Any = None
    profile = None

    async def usage_now() -> llm.Usage:
        try:
            return llm.usage_from_browser_use(await agent.token_cost_service.get_usage_summary())
        except Exception:
            return state["counted"]

    async def on_step_start(_agent) -> None:
        state["index"] += 1
        state["t0"] = time.monotonic()
        state["ts"] = utc_iso()
        state["recorded"] = len(_history_items(agent.history))

    async def on_step_end(_agent) -> None:
        elapsed_ms = (time.monotonic() - state["t0"]) * 1000
        # Only the history item(s) this step added: a step browser-use kept no item for
        # must not be labelled with the step before it.
        fields = _step_fields(_history_items(agent.history)[state["recorded"]:])
        now = await usage_now()
        used = usage_delta(now, state["counted"])
        state["counted"] = now
        steps.append(make_step(
            state["index"], fields["action"], action_args=fields["action_args"], started_at=state["ts"],
            duration_ms=elapsed_ms, tokens_input=prompt_tokens(used), tokens_output=used.output_tokens,
            tokens_cache_read=used.cache_read_input_tokens, tokens_cache_write=used.cache_creation_input_tokens,
            cost_usd=used.cost_usd(model) or 0.0, observation=fields["observation"], error=fields["error"],
            actions=fields["actions"],
        ))
        print(f"    Step {state['index']}: {fields['action'] or 'N/A'} ({elapsed_ms:.0f}ms, ${steps[-1]['cost_usd']:.4f})")

    try:
        try:
            profile = browser_env.browser_profile()
            kwargs = dict(
                task=task["goal"],  # verbatim: the same text the Rindler arm is given
                llm=llm.agent_llm(model),
                browser_profile=profile,
                file_system_path=browser_env.agent_files_dir(profile),
                initial_actions=[{"navigate": {"url": task["start_url"], "new_tab": False}}],
                use_judge=False,  # the CLI has its own judge
                calculate_cost=False,  # prices come from constants.COST_RATES, no download
                # Not browser-use's Ctrl-C handler: on a second SIGINT it calls os._exit()
                # and leaves Chromium running, and one Ctrl-C under `uv run` is two
                # SIGINTs. entrypoint.run_cli cancels the run instead.
                enable_signal_handler=False,
            )
            if agent_factory is not None:
                agent = agent_factory(**kwargs)
            else:
                from browser_use import Agent

                agent = Agent(**kwargs)
            browser_env.track_agent_dir(profile, agent)  # its step screenshots go with the profile
            run = agent.run(max_steps=max_steps, on_step_start=on_step_start, on_step_end=on_step_end)
            try:
                await (asyncio.wait_for(run, timeout=timeout_s) if timeout_s else run)
            except asyncio.TimeoutError:
                error = f"stopped after the {timeout_s:.0f}s time limit"
        except Exception as exc:  # a model or browser failure ends this run, not the whole benchmark
            error = f"{type(exc).__name__}: {exc}"
        history = getattr(agent, "history", None)
        usage_total = await usage_now() if agent is not None else llm.Usage()
        # The screenshots browser-use keeps are files in the agent's dir, which
        # cleanup_profile removes: a run that did not succeed saves its last one first.
        last_shot = None
        if history is not None and not _succeeded(history, stopped=error is not None):
            last_shot = _save_last_screenshot(history, results_dir, task_id)
    finally:
        # Also on Ctrl-C (a cancelled run): stops the browser if it is still up.
        if profile is not None:
            browser_env.cleanup_profile(profile)

    # Tokens spent after the last step ended (or with no step at all) go on the last step.
    leftover = usage_delta(usage_total, state["counted"])
    if prompt_tokens(leftover) or leftover.output_tokens:
        if not steps:
            steps.append(make_step(max(state["index"], 1), "unfinished_step", started_at=state["ts"]))
        last = steps[-1]
        last["tokens_input"] += prompt_tokens(leftover)
        last["tokens_output"] += leftover.output_tokens
        last["tokens_cache_read"] += leftover.cache_read_input_tokens
        last["tokens_cache_write"] += leftover.cache_creation_input_tokens
        last["cost_usd"] = round(last["cost_usd"] + (leftover.cost_usd(model) or 0.0), 6)

    # A run cut short by an error or the time limit is not a success, whatever the history says.
    stopped = error is not None
    success, final_report = False, None
    if history is not None:
        try:
            done = bool(history.is_done())
            success = bool(history.is_successful()) if done and not stopped else False
        except Exception:
            done = False
        try:
            final_report = history.final_result()
        except Exception:
            final_report = None
        if not done and error is None:
            error = f"did not finish within {max_steps} steps"
    elif error is None:
        error = "browser-use returned no history"

    shot = last_shot
    finished_at = datetime.now(timezone.utc)
    record = new_result(
        task, agent="browseruse", model=model, site=site, max_steps=max_steps,
        started_at=started_at, finished_at=finished_at, steps=steps, success=success,
        final_report=final_report, error=error, failure_screenshots=[shot] if shot else None,
    )
    if shot and steps:
        steps[-1]["screenshot_path"] = shot
    if error:
        print(f"    Stopped: {error}")
    print(f"    Done: {len(steps)} steps, ${record['stats']['total_cost_usd']:.4f}")
    return record
