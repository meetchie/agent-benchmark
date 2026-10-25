"""Phase 1: browser-use on a local headless Chromium, with no knowledge of the site.

The agent gets the task's goal text verbatim and the same step budget as the Rindler arm.
The browser is the repo's one local profile (browser_env: headless, macOS keychain flags
on, a throwaway user-data dir) and the model is llm.agent_llm(model), so it runs on the
Anthropic key alone. Every step's tokens are the real difference of browser-use's own
token counter, so the per-step costs add up to the run's cost.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import llm
import browser_env

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


def _sanitize(action: Any) -> dict[str, Any]:
    """The action as JSON-safe data. browser-use attaches the page element it acted on
    (``interacted_element``, an object); that is dropped, anything else unserializable is stringified."""
    if not isinstance(action, dict):
        return {}
    kept = {k: v for k, v in action.items() if k != "interacted_element"}
    try:
        json.dumps(kept)
        return kept
    except (TypeError, ValueError):
        return {k: str(v) for k, v in kept.items()}


def _latest_action(history: Any) -> tuple[str | None, dict[str, Any]]:
    try:
        actions = history.model_actions()
    except Exception:
        return None, {}
    if not actions or not isinstance(actions[-1], dict):
        return None, {}
    latest = _sanitize(actions[-1])
    return next(iter(latest), None), latest


def _latest_observation(history: Any) -> str | None:
    try:
        extracted = history.extracted_content()
    except Exception:
        return None
    if not extracted:
        return None
    return str(extracted[-1])[:OBSERVATION_CHARS]


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
    state = {"index": 0, "t0": time.monotonic(), "ts": utc_iso(), "counted": llm.Usage()}
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

    async def on_step_end(_agent) -> None:
        elapsed_ms = (time.monotonic() - state["t0"]) * 1000
        action, args = _latest_action(agent.history)
        now = await usage_now()
        used = usage_delta(now, state["counted"])
        state["counted"] = now
        steps.append(make_step(
            state["index"], action, action_args=args, started_at=state["ts"], duration_ms=elapsed_ms,
            tokens_input=prompt_tokens(used), tokens_output=used.output_tokens,
            tokens_cache_read=used.cache_read_input_tokens, tokens_cache_write=used.cache_creation_input_tokens,
            cost_usd=used.cost_usd(model) or 0.0, observation=_latest_observation(agent.history),
        ))
        print(f"    Step {state['index']}: {action or 'N/A'} ({elapsed_ms:.0f}ms, ${steps[-1]['cost_usd']:.4f})")

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
