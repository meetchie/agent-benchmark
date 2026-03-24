"""
Benchmark Runner - Runs BrowserUse agent with live step tracking and screenshots.

Manages in-memory run state, captures screenshots after each agent action,
and provides step descriptions for the benchmark UI.
"""

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging
import os

from dotenv import load_dotenv

# Load env (OPENAI_API_KEY needed for LLM)
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=False)


_VALID_PROVIDERS = {"local", "browserbase"}


def _get_browser_provider() -> str:
    """Return the configured browser provider ('local' or 'browserbase').

    Reads BROWSER_PROVIDER env var. Defaults to 'local'.
    Warns and falls back to 'local' for unrecognized values.
    """
    provider = os.getenv("BROWSER_PROVIDER", "local").lower().strip()
    if provider not in _VALID_PROVIDERS:
        logging.warning(
            "Unknown BROWSER_PROVIDER=%r, falling back to 'local'. "
            "Valid options: %s", provider, ", ".join(sorted(_VALID_PROVIDERS))
        )
        return "local"
    return provider


def _validate_browser_config() -> None:
    """Validate that required env vars are set for the configured provider.

    Raises ValueError if Browserbase is selected but keys are missing.
    """
    provider = _get_browser_provider()
    if provider == "browserbase":
        if not os.getenv("BROWSERBASE_API_KEY"):
            raise ValueError(
                "BROWSERBASE_API_KEY is required when BROWSER_PROVIDER=browserbase"
            )
        if not os.getenv("BROWSERBASE_PROJECT_ID"):
            raise ValueError(
                "BROWSERBASE_PROJECT_ID is required when BROWSER_PROVIDER=browserbase"
            )


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
    user_id: str = ""
    status: str = "running"  # "running" | "analyzing" | "complete" | "error"
    steps: list[StepRecord] = field(default_factory=list)
    success: bool = False
    summary: str = ""
    result_state: str = ""  # "pass" | "fail" | "too_slow" | "error"
    total_ms: int = 0
    message: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    phases: list[dict] = field(default_factory=list)
    goal: str = ""  # Stored so the judge can access it

    def to_response(self) -> dict:
        """Serialize for API response. Only latest step includes screenshot_b64."""
        steps_data = []
        for i, step in enumerate(self.steps):
            is_latest = i == len(self.steps) - 1
            steps_data.append(step.to_dict(include_screenshot=is_latest))

        if self.status == "running":
            return {"status": "running", "steps": steps_data}
        elif self.status == "analyzing":
            return {
                "status": "analyzing",
                "steps": steps_data,
                "total_ms": self.total_ms,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
            }
        elif self.status == "complete":
            return {
                "status": "complete",
                "steps": steps_data,
                "success": self.success,
                "summary": self.summary,
                "result_state": self.result_state,
                "total_ms": self.total_ms,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "phases": self.phases,
            }
        else:
            return {
                "status": "error",
                "message": self.message,
                "steps": steps_data,
            }


def _format_action(agent) -> str:
    """Extract a human-readable description of the last agent action.

    Uses the agent's own 'next_goal' from its model output for rich descriptions
    like 'Click on the Menu link' instead of just 'Clicking element'.
    Falls back to action type if model output isn't available.
    """
    try:
        # Try to get the rich description from the agent's model output
        if agent.history.history:
            last_item = agent.history.history[-1]
            if hasattr(last_item, 'model_output') and last_item.model_output:
                mo = last_item.model_output
                # next_goal is the best description of what the agent is doing
                goal = getattr(mo, 'next_goal', '')
                if goal:
                    return str(goal)

        # Fallback: format from raw action data
        actions = agent.history.model_actions()
        if not actions:
            return "Processing..."
        last = actions[-1]
        if isinstance(last, dict):
            action_type = list(last.keys())[0] if last else "action"
            action_data = last.get(action_type, {})
            el = last.get("interacted_element")

            if action_type in ("go_to_url", "navigate"):
                url = action_data.get("url", "") if isinstance(action_data, dict) else str(action_data)
                return f"Navigating to {url[:80]}"
            elif action_type in ("click_element", "click"):
                # Try to get element info
                if el and hasattr(el, 'node_name'):
                    tag = getattr(el, 'node_name', '').lower()
                    attrs = getattr(el, 'attributes', {}) or {}
                    label = attrs.get('aria-label', '') or attrs.get('title', '') or attrs.get('alt', '')
                    if label:
                        return f"Clicking {tag} \"{label[:60]}\""
                    return f"Clicking <{tag}> element"
                return "Clicking element"
            elif action_type in ("input_text", "type"):
                text = action_data.get("text", "") if isinstance(action_data, dict) else str(action_data)
                return f"Typing: \"{str(text)[:50]}\""
            elif action_type == "scroll":
                direction = action_data.get("direction", "down") if isinstance(action_data, dict) else "down"
                return f"Scrolling {direction}"
            elif action_type == "extract_content":
                return "Reading page content"
            elif action_type == "done":
                result = action_data.get("text", "") if isinstance(action_data, dict) else str(action_data)
                return f"Done: {str(result)[:80]}"
            else:
                return f"{action_type.replace('_', ' ').capitalize()}"
    except Exception as e:
        logging.debug(f"_format_action failed: {e}")
    return "Processing..."


async def _take_screenshot(agent) -> Optional[str]:
    """Capture a JPEG screenshot from the current browser page.

    Caps width at 1280px, JPEG quality 80 — ~50-150 KB per screenshot.
    """
    try:
        # browser_use ≥0.11 uses browser_session; older versions used browser_context
        session = getattr(agent, 'browser_session', None) or agent.browser_context
        img_bytes = await session.take_screenshot(format="jpeg", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode()
    except Exception as e:
        logging.error(f"_take_screenshot failed: {type(e).__name__}: {e}")
        return None


async def run_benchmark(state: RunState, url: str, goal: str, viewport: dict | None = None) -> None:
    """
    Run a BrowserUse agent for the benchmark and update state with each step.

    Uses a local Playwright browser (no Browserbase required).
    Requires OPENAI_API_KEY in environment.
    """
    # Deferred import: keeps the server startable even if browser_use is not installed,
    # and avoids import-time side effects (Playwright browser launch).
    from browser_use import Agent
    from browser_use.llm.models import get_llm_by_name

    step_start_time: datetime = datetime.now()
    overall_start = datetime.now()

    async def on_step_start(agent):
        nonlocal step_start_time
        step_start_time = datetime.now()

    async def on_step_end(agent):
        elapsed_ms = int((datetime.now() - step_start_time).total_seconds() * 1000)
        description = _format_action(agent)
        screenshot_b64 = await _take_screenshot(agent)

        state.steps.append(
            StepRecord(
                step=len(state.steps) + 1,
                description=description,
                elapsed_ms=elapsed_ms,
                screenshot_b64=screenshot_b64,
            )
        )

    _AGENT_TIMEOUT = 180  # 3 minutes

    timed_out = False
    try:
        from browser_use.browser.profile import BrowserProfile

        llm = get_llm_by_name("openai_gpt-4o")

        # Prepend the target URL to the goal so the agent navigates there first
        full_goal = f"Go to {url}\n\n{goal}"

        # Clean browser profile — no saved cookies, location, or login state
        # Viewport matches the viewer's screenshot container size
        browser_profile = BrowserProfile(
            user_data_dir=None,
            headless=False,
            keep_alive=False,
            permissions=[],
            viewport=viewport or {"width": 1280, "height": 720},
        )

        agent = Agent(
            task=full_goal,
            llm=llm,
            browser_profile=browser_profile,
        )

        try:
            history = await asyncio.wait_for(
                agent.run(
                    on_step_start=on_step_start,
                    on_step_end=on_step_end,
                ),
                timeout=_AGENT_TIMEOUT,
            )

            # Extract token usage from completed run
            try:
                usage = history.usage
                state.input_tokens = getattr(usage, 'total_prompt_tokens', 0)
                state.output_tokens = getattr(usage, 'total_completion_tokens', 0)
                state.total_tokens = getattr(usage, 'total_tokens', 0)
            except Exception as e:
                logging.debug(f"Token usage extraction failed: {e}")

        except asyncio.TimeoutError:
            timed_out = True
            logging.info("Agent timed out after %ds", _AGENT_TIMEOUT)
            # Extract token usage from the agent's token cost service
            try:
                usage = await agent.token_cost_service.get_usage_summary()
                state.input_tokens = getattr(usage, 'total_prompt_tokens', 0)
                state.output_tokens = getattr(usage, 'total_completion_tokens', 0)
                state.total_tokens = getattr(usage, 'total_tokens', 0)
            except Exception as e:
                logging.debug(f"Token usage extraction on timeout failed: {e}")

        # --- Agent finished or timed out — always run the judge ---
        total_ms = int((datetime.now() - overall_start).total_seconds() * 1000)
        state.total_ms = total_ms
        state.status = "analyzing"

        # Call GPT-4o judge on whatever steps we have
        from run_judge import judge_run
        steps_for_judge = [
            {"step": s.step, "description": s.description, "elapsed_ms": s.elapsed_ms}
            for s in state.steps
        ]
        # Pass result_state hint so judge knows whether agent timed out
        rs_hint = "too_slow" if timed_out else "unknown"
        judgment = judge_run(state.goal, steps_for_judge, result_state=rs_hint)

        state.success = judgment["success"]
        state.summary = judgment["summary"]
        state.phases = judgment["phases"]

        if timed_out:
            state.result_state = "too_slow"
            state.summary = judgment["summary"] or "The agent ran out of time before completing the task."
        else:
            state.result_state = "pass" if judgment["success"] else "fail"

        state.status = "complete"

    except Exception as e:
        # Still try to run judge if we have steps
        if state.steps:
            try:
                state.total_ms = int((datetime.now() - overall_start).total_seconds() * 1000)
                state.status = "analyzing"
                from run_judge import judge_run
                steps_for_judge = [
                    {"step": s.step, "description": s.description, "elapsed_ms": s.elapsed_ms}
                    for s in state.steps
                ]
                judgment = judge_run(state.goal, steps_for_judge)
                state.success = False
                state.summary = judgment["summary"]
                state.phases = judgment["phases"]
                state.result_state = "error"
                state.message = str(e)[:200]
                state.status = "complete"
                return
            except Exception:
                pass
        state.status = "error"
        state.message = str(e)[:200]
        state.result_state = "error"
