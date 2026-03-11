"""
Benchmark Runner - Runs BrowserUse agent with live step tracking and screenshots.

Manages in-memory run state, captures screenshots after each agent action,
and provides step descriptions for the benchmark UI.
"""

import base64
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import os

from dotenv import load_dotenv

# Load env (OPENAI_API_KEY needed for LLM)
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=False)


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
            elif action_type in ("click_element", "click"):
                return "Clicking element"
            elif action_type in ("input_text", "type"):
                text = action_data.get("text", "") if isinstance(action_data, dict) else str(action_data)
                return f"Typing: {str(text)[:40]}"
            elif action_type == "scroll":
                return "Scrolling page"
            elif action_type == "extract_content":
                return "Extracting page content"
            elif action_type == "done":
                result = action_data.get("text", "") if isinstance(action_data, dict) else str(action_data)
                return f"Done: {str(result)[:60]}"
            else:
                return f"{action_type.replace('_', ' ').capitalize()}"
    except Exception as e:
        import logging
        logging.debug(f"_format_action failed: {e}")
    return "Processing..."


async def _take_screenshot(agent) -> Optional[str]:
    """Capture a JPEG screenshot from the current browser page.

    Caps width at 1280px, JPEG quality 80 — ~50-150 KB per screenshot.
    """
    try:
        # browser_use exposes the page via agent.browser_context
        page = await agent.browser_context.get_current_page()
        # Set viewport to max 1280px wide before capturing
        await page.set_viewport_size({"width": 1280, "height": 800})
        img_bytes = await page.screenshot(type="jpeg", quality=80, full_page=False)
        return "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode()
    except Exception as e:
        import logging
        logging.debug(f"_take_screenshot failed: {e}")
        return None


async def run_benchmark(state: RunState, url: str, goal: str) -> None:
    """
    Run a BrowserUse agent for the benchmark and update state with each step.

    Uses a local Playwright browser (no Browserbase required).
    Requires OPENAI_API_KEY in environment.
    """
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

    try:
        llm = get_llm_by_name("openai_gpt-4o")

        # Prepend the target URL to the goal so the agent navigates there first
        full_goal = f"Go to {url}\n\n{goal}"

        agent = Agent(
            task=full_goal,
            llm=llm,
            # No Browserbase keys → uses local Playwright browser
        )

        history = await agent.run(
            on_step_start=on_step_start,
            on_step_end=on_step_end,
        )

        total_ms = int((datetime.now() - overall_start).total_seconds() * 1000)

        # Determine success from agent's self-report at run end
        success = False
        summary = ""
        try:
            # Try is_successful() first (available in some browser_use versions)
            if hasattr(history, 'is_successful') and callable(history.is_successful):
                success = bool(history.is_successful())
            else:
                # Fall back: inspect the done action's success field
                actions = history.model_actions() if hasattr(history, 'model_actions') else []
                for action in reversed(actions):
                    if isinstance(action, dict) and 'done' in action:
                        done_data = action['done']
                        if isinstance(done_data, dict):
                            success = bool(done_data.get('success', False))
                        break
                    elif hasattr(action, 'done') and action.done is not None:
                        done_action = action.done
                        success = bool(getattr(done_action, 'success', False))
                        break

            # Get summary from final result
            if hasattr(history, 'final_result') and callable(history.final_result):
                result = history.final_result()
                if result:
                    summary = str(result)[:300]
            elif hasattr(history, 'final_result') and history.final_result:
                summary = str(history.final_result)[:300]

        except Exception as e:
            import logging
            logging.debug(f"Success determination failed: {e}")

        if not summary:
            summary = "Agent completed the task." if success else "Agent did not complete the task."

        state.status = "complete"
        state.success = success
        state.summary = summary
        state.total_ms = total_ms

    except Exception as e:
        state.status = "error"
        state.message = str(e)[:200]
