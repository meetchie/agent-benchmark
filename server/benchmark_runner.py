"""
Benchmark Runner - Thin UI harness around arena's BrowserUseTelemetricAgent.

Coordinates agent execution and LLM judge evaluation, feeding live screenshots
and step descriptions to the benchmark UI via RunState polling.
"""

import base64
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging
import os
import sys

from dotenv import load_dotenv

# Load env
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=False)

# Ensure clean-room root is on path for adapter imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adapters.browseruse_agent import BrowserUseTelemetricAgent
from scenarios import create_custom_scenario
from arena import run_judge


@dataclass
class StepRecord:
    step: int
    description: str
    elapsed_ms: int
    screenshot_b64: Optional[str] = None

    def to_dict(self, include_screenshot: bool = False) -> dict:
        d = {
            "step": self.step,
            "description": self.description,
            "elapsed_ms": self.elapsed_ms,
        }
        if include_screenshot and self.screenshot_b64:
            d["screenshot_b64"] = self.screenshot_b64
        return d


@dataclass
class RunState:
    run_id: str
    status: str = "running"  # "running" | "complete" | "error"
    steps: list[StepRecord] = field(default_factory=list)
    success: bool = False
    summary: str = ""
    total_ms: int = 0
    message: str = ""

    def to_response(self) -> dict:
        """Serialize for API response. Only latest step includes screenshot_b64."""
        steps_data = []
        for i, step in enumerate(self.steps):
            is_latest = i == len(self.steps) - 1
            steps_data.append(step.to_dict(include_screenshot=is_latest))

        if self.status == "running":
            return {"status": "running", "steps": steps_data}
        elif self.status == "complete":
            return {
                "status": "complete",
                "steps": steps_data,
                "success": self.success,
                "summary": self.summary,
                "total_ms": self.total_ms,
            }
        else:
            return {"status": "error", "message": self.message}


def _format_action(agent) -> str:
    """Extract a human-readable description of the last agent action."""
    try:
        actions = agent.history.model_actions()
        if not actions:
            return "Processing..."
        last = actions[-1]
        if isinstance(last, dict):
            action_type = list(last.keys())[0] if last else "action"
            action_data = last.get(action_type, {})
            if action_type == "go_to_url":
                url = action_data.get("url", "") if isinstance(action_data, dict) else str(action_data)
                return f"Navigating to {url[:60]}"
            elif action_type == "click":
                return "Clicking element"
            elif action_type in ("input_text", "type"):
                text = action_data.get("text", "") if isinstance(action_data, dict) else str(action_data)
                return f"Typing: {str(text)[:40]}"
            elif action_type == "scroll":
                return "Scrolling page"
            elif action_type in ("extract_content",):
                # extract_content kept for backward compatibility with old telemetry data
                return "Extracting page content"
            elif action_type == "done":
                result = action_data.get("text", "") if isinstance(action_data, dict) else str(action_data)
                return f"Done: {str(result)[:60]}"
            else:
                return f"{action_type.replace('_', ' ').capitalize()}"
    except Exception as e:
        logging.debug(f"_format_action failed: {e}")
    return "Processing..."


async def _take_screenshot(agent) -> Optional[str]:
    """Capture a JPEG screenshot via BrowserSession.take_screenshot().

    Uses browser-use's CDP-based screenshot (not Playwright Page.screenshot).
    JPEG quality 80 — ~50-150 KB per screenshot.
    """
    try:
        if hasattr(agent, "browser_session") and agent.browser_session:
            img_bytes = await agent.browser_session.take_screenshot(
                format="jpeg", quality=80, full_page=False,
            )
        else:
            return None
        return "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode()
    except Exception as e:
        logging.warning(f"_take_screenshot failed: {type(e).__name__}: {e}")
        return None


class _BenchmarkAgent(BrowserUseTelemetricAgent):
    """Thin subclass that adds screenshot capture for the benchmark UI.

    Wraps the parent's step callbacks to also capture screenshots and
    update RunState for live polling.
    """

    def __init__(self, state: RunState, **kwargs):
        super().__init__(**kwargs)
        self._bench_state = state
        self._step_start_time = datetime.now()

    async def run(self, start_url: Optional[str] = None, **kwargs) -> dict:
        """Override to inject screenshot capture into step callbacks."""
        import browser_use
        import adapters.browseruse_agent as ba_mod

        _OriginalAgent = ba_mod.Agent
        bench_state = self._bench_state
        step_start_ref = [datetime.now()]

        class _ScreenshotAgent(_OriginalAgent):
            """Intercepts browser-use Agent to add screenshot capture."""

            async def run(inner_self, **run_kwargs):
                original_on_step_start = run_kwargs.get("on_step_start")
                original_on_step_end = run_kwargs.get("on_step_end")

                async def wrapped_on_step_start(agent):
                    step_start_ref[0] = datetime.now()
                    if original_on_step_start:
                        await original_on_step_start(agent)

                async def wrapped_on_step_end(agent):
                    if original_on_step_end:
                        await original_on_step_end(agent)

                    # Capture screenshot and description for UI
                    elapsed_ms = int((datetime.now() - step_start_ref[0]).total_seconds() * 1000)
                    description = _format_action(agent)
                    screenshot_b64 = await _take_screenshot(agent)

                    bench_state.steps.append(StepRecord(
                        step=len(bench_state.steps) + 1,
                        description=description,
                        elapsed_ms=elapsed_ms,
                        screenshot_b64=screenshot_b64,
                    ))

                run_kwargs["on_step_start"] = wrapped_on_step_start
                run_kwargs["on_step_end"] = wrapped_on_step_end

                return await super().run(**run_kwargs)

        # Patch Agent in both places it's imported
        ba_mod.Agent = _ScreenshotAgent
        try:
            result = await super().run(start_url=start_url, **kwargs)
        finally:
            ba_mod.Agent = _OriginalAgent

        return result


async def run_benchmark(state: RunState, url: str, goal: str) -> None:
    """
    Run a benchmark using arena's BrowserUseTelemetricAgent + LLM judge.

    Creates the agent, captures live screenshots for the UI, then evaluates
    with the LLM judge for a reliable pass/fail verdict.
    """
    overall_start = datetime.now()

    # Prepend target URL to the goal
    full_goal = f"Go to {url}\n\n{goal}"

    # Create arena agent with live screenshot support
    agent = _BenchmarkAgent(
        state=state,
        run_id=state.run_id,
        goal=full_goal,
        lane="BENCHMARK",
    )

    try:
        result = await agent.run()

        total_ms = int((datetime.now() - overall_start).total_seconds() * 1000)

        # Run LLM judge for reliable pass/fail
        scenario = create_custom_scenario(
            goal=full_goal,
            start_url=url,
            name=f"benchmark-{state.run_id[:8]}",
        )

        judge_result = run_judge(
            scenario=scenario,
            result=result,
            telemetry_events=agent.telemetry_events,
        )

        verdict = judge_result.get("verdict", "ERROR")
        reason = judge_result.get("reason", "No reason provided")

        state.status = "complete"
        state.success = verdict == "PASS"
        state.summary = reason
        state.total_ms = total_ms

    except Exception as e:
        state.status = "error"
        state.message = str(e)[:200]
