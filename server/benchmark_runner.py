"""
Benchmark Runner - Runs BrowserUse agent with live step tracking and screenshots.

Manages in-memory run state, captures screenshots after each agent action,
and provides step descriptions for the benchmark UI.

Configuration (environment, see ``llm.py`` and ``browser_env.py`` for the rest):
  BENCHMARK_TIMEOUT_S         hard limit for the agent, in seconds (default 180)
  BENCHMARK_AGENT_MODEL       model the agent runs on (default claude-sonnet-5-5)
  BENCHMARK_HEADLESS          run Chromium headless (default true)
  BENCHMARK_BROWSER_PROVIDER  "local" (default) or "browserbase"
"""

import runtime_env  # noqa: F401  (first: loads .env and turns browser-use telemetry off)

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging
import math
import os

import llm

DEFAULT_TIMEOUT_S = 180.0
# The judge is one short model call; a hung connection must not leave the run "analyzing".
_JUDGE_TIMEOUT_S = 120.0
# Reading the token counters of a stopped agent is local bookkeeping; this only guards a hang.
_USAGE_READ_TIMEOUT_S = 5.0


def get_agent_timeout() -> float:
    """BENCHMARK_TIMEOUT_S: the agent's hard time limit in seconds (default 180).

    Raises ValueError for anything that is not a positive number.
    """
    raw = os.getenv("BENCHMARK_TIMEOUT_S", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"BENCHMARK_TIMEOUT_S={raw!r} must be a positive number of seconds")
    return value


_VALID_PROVIDERS = {"local", "browserbase"}


def _get_browser_provider() -> str:
    """Return the configured browser provider ('local' or 'browserbase').

    Reads BENCHMARK_BROWSER_PROVIDER env var. Defaults to 'local'.
    """
    provider = os.getenv("BENCHMARK_BROWSER_PROVIDER", "local").lower().strip()
    if provider not in _VALID_PROVIDERS:
        logging.warning(
            "Unknown BENCHMARK_BROWSER_PROVIDER=%r, falling back to 'local'. "
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
                "BROWSERBASE_API_KEY is required when BENCHMARK_BROWSER_PROVIDER=browserbase"
            )
        if not os.getenv("BROWSERBASE_PROJECT_ID"):
            raise ValueError(
                "BROWSERBASE_PROJECT_ID is required when BENCHMARK_BROWSER_PROVIDER=browserbase"
            )


@dataclass
class StepRecord:
    step: int
    description: str
    elapsed_ms: int
    screenshot_b64: Optional[str] = None
    # For the judge only (not in the status payload): the agent's verdict on the step
    # before this one, and what each of this step's browser actions returned.
    evaluation: str = ""
    results: list[str] = field(default_factory=list)

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
    # Token counts of the agent run. input_tokens is browser-use's prompt total (cache
    # reads included, cache writes not), output_tokens its completion total, and
    # total_tokens everything billed: input_tokens + cache_write_tokens + output_tokens.
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    phases: list[dict] = field(default_factory=list)
    goal: str = ""  # Stored so the judge can access it
    persisted_run_id: str | None = None  # Id of the saved run file, None if it could not be written
    agent_model: str = field(default_factory=lambda: _default_agent_model())  # Model the agent runs on
    cost_usd: float | None = None  # Agent tokens at agent_model's rates; None when unknown
    cache_read_tokens: int = 0  # Part of input_tokens that came from the prompt cache
    cache_write_tokens: int = 0  # Tokens written to the prompt cache (billed on top of input_tokens)
    final_report: str | None = None  # The agent's closing report, None unless it finished on its own
    agent_reported_success: bool | None = None  # The success flag the agent set when it finished
    stopped_at: datetime | None = None  # When a cancel was asked for (the run's time ends there)

    def record_usage(self, summary) -> None:
        """Take the agent's token usage from a browser-use UsageSummary.

        ``input_tokens`` keeps browser-use's meaning (all prompt tokens, cache reads
        included, cache writes not) and ``output_tokens`` is its completion total.
        ``total_tokens`` counts every token that was billed: ``input_tokens`` plus the
        cache writes plus ``output_tokens`` (browser-use's own ``total_tokens`` leaves the
        cache writes out). ``cost_usd`` prices the cached parts at the cache rates and is
        None when ``agent_model`` has no known price or there is no usage to price.
        """
        if summary is None:
            return
        usage = llm.usage_from_browser_use(summary)
        self.input_tokens = getattr(summary, "total_prompt_tokens", 0) or 0
        self.output_tokens = getattr(summary, "total_completion_tokens", 0) or 0
        self.cache_read_tokens = usage.cache_read_input_tokens
        self.cache_write_tokens = usage.cache_creation_input_tokens
        self.total_tokens = usage.total_tokens
        self.cost_usd = usage.cost_usd(self.agent_model)

    def to_dict(self) -> dict:
        """Serialize for the status API. Only the latest step includes screenshot_b64.

        Once the agent has finished (``analyzing`` and ``complete``) the payload carries
        the token counts plus ``cost_usd`` (US dollars for the agent's tokens at
        ``agent_model``'s rates, null when unknown) and ``agent_model`` (model id). An
        ``error`` payload carries the same fields when the agent had already used tokens
        (a cancelled run), and none when it had not.

        A run that ended as an error after some steps is still judged, so it is
        ``complete`` with ``result_state`` "error"; its payload also carries ``message``,
        the reason it is an error (the model refused, the run crashed). A ``complete``
        payload also carries the agent's closing report and the success flag it set with
        it (``final_report`` and ``agent_reported_success``, both null when the agent did
        not finish on its own), so the user can read what the judge read.
        """
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
                "cost_usd": self.cost_usd,
                "agent_model": self.agent_model,
            }
        elif self.status == "complete":
            payload = {
                "status": "complete",
                "steps": steps_data,
                "success": self.success,
                "summary": self.summary,
                "result_state": self.result_state,
                "total_ms": self.total_ms,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "cost_usd": self.cost_usd,
                "agent_model": self.agent_model,
                "phases": self.phases,
                "final_report": self.final_report,
                "agent_reported_success": self.agent_reported_success,
            }
            if self.message:
                payload["message"] = self.message
            return payload
        else:
            payload = {
                "status": "error",
                "message": self.message,
                "steps": steps_data,
            }
            if self.total_tokens or self.cost_usd is not None:
                # The agent ran (and was billed) before the run ended, for example a
                # cancelled run: report what it used.
                payload.update(
                    total_ms=self.total_ms,
                    input_tokens=self.input_tokens,
                    output_tokens=self.output_tokens,
                    total_tokens=self.total_tokens,
                    cost_usd=self.cost_usd,
                    agent_model=self.agent_model,
                )
            return payload

    # Older name for to_dict(), kept for callers that still use it.
    to_response = to_dict


def _default_agent_model() -> str:
    """The agent model from the environment (BENCHMARK_AGENT_MODEL or the provider default)."""
    try:
        return llm.model_for("agent")
    except llm.LLMError:  # bad LLM_PROVIDER; startup validation reports it properly
        return ""


_MAX_DESCRIPTION_CHARS = 200


def _clip(text: object, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _element_label(element) -> str:
    """A human label for the page element an action touched (aria-label, placeholder, ...)."""
    attrs = getattr(element, "attributes", None) or {}
    if not isinstance(attrs, dict):
        return ""
    for key in ("aria-label", "placeholder", "title", "alt", "name"):
        value = attrs.get(key)
        if value:
            return _clip(value, 60)
    return ""


def _field_name(index, element) -> str:
    """'the search box', 'the "Email" field', or 'element 12' for a field the agent typed into."""
    attrs = (getattr(element, "attributes", None) or {}) if element is not None else {}
    label = _element_label(element)
    if (isinstance(attrs, dict) and str(attrs.get("type", "")).lower() == "search") or "search" in label.lower():
        return "the search box"
    if label:
        return f'the "{label}" field'
    return f"element {index}" if index is not None else "the field"


def _describe_action(name: str, params, element=None) -> str:
    """One browser-use action in plain words, for a step whose model gave no goal text."""
    p = params if isinstance(params, dict) else {}
    index = p.get("index")
    if name == "navigate":
        where = _clip(p.get("url", ""), 80)
        return f"Open {where} in a new tab" if p.get("new_tab") else f"Open {where}"
    if name == "search":
        return f'Search {p.get("engine") or "the web"} for "{_clip(p.get("query", ""), 60)}"'
    if name == "go_back":
        return "Go back"
    if name == "wait":
        return f'Wait {p.get("seconds", 3)} seconds'
    if name == "click":
        if index is not None:
            label = _element_label(element)
            return f'Click element {index} ("{label}")' if label else f"Click element {index}"
        if p.get("coordinate_x") is not None and p.get("coordinate_y") is not None:
            return f'Click at ({p["coordinate_x"]}, {p["coordinate_y"]})'
        return "Click an element"
    if name == "input":
        text = p.get("text", "")
        if text == "":
            return f"Clear {_field_name(index, element)}"
        return f"Type '{_clip(text, 50)}' into {_field_name(index, element)}"
    if name == "upload_file":
        return "Upload a file"
    if name == "switch":
        return "Switch to another tab"
    if name == "close":
        return "Close a tab"
    if name == "extract":
        query = _clip(p.get("query", ""), 60)
        return f"Read the page for: {query}" if query else "Read the page content"
    if name == "search_page":
        return f'Search the page for "{_clip(p.get("pattern", ""), 60)}"'
    if name == "find_elements":
        return f'Look for elements matching {_clip(p.get("selector", ""), 60)}'
    if name == "scroll":
        direction = "down" if p.get("down", True) else "up"
        pages = p.get("pages", 1.0)
        where = f" in element {index}" if index is not None else ""
        if isinstance(pages, (int, float)) and pages >= 10:
            return f"Scroll to the {'bottom' if direction == 'down' else 'top'}{where}"
        if pages == 0.5:
            return f"Scroll {direction} half a page{where}"
        return f"Scroll {direction}{where}"
    if name == "send_keys":
        return f"Press {_clip(p.get('keys', ''), 40)}"
    if name == "find_text":
        return f'Scroll to the text "{_clip(p.get("text", ""), 60)}"'
    if name == "screenshot":
        return "Take a screenshot"
    if name == "save_as_pdf":
        return "Save the page as a PDF"
    if name == "dropdown_options":
        return f"Read the options of dropdown element {index}"
    if name == "select_dropdown":
        return f'Select "{_clip(p.get("text", ""), 60)}" in dropdown element {index}'
    if name == "write_file":
        return "Write a file"
    if name == "replace_file":
        return "Edit a file"
    if name == "read_file":
        return "Read a file"
    if name == "evaluate":
        return "Run a script on the page"
    if name == "done":
        text = p.get("text", "") if isinstance(params, dict) else params
        return f"Done: {_clip(text, 80)}"
    return name.replace("_", " ").capitalize()


def _step_actions(history_item) -> list[tuple[str, object, object]]:
    """(action name, parameters, touched element) for each action of one history step."""
    mo = getattr(history_item, "model_output", None)
    actions = list(getattr(mo, "action", None) or [])
    state = getattr(history_item, "state", None)
    elements = list(getattr(state, "interacted_element", None) or [])
    steps = []
    for i, action in enumerate(actions):
        dumped = action.model_dump(exclude_none=True, mode="json") if hasattr(action, "model_dump") else action
        if not isinstance(dumped, dict) or not dumped:
            continue
        name = next(iter(dumped))
        steps.append((name, dumped[name], elements[i] if i < len(elements) else None))
    return steps


def _format_action(agent) -> str:
    """Describe the step the agent just finished, in a few plain words.

    The agent's own 'next_goal' ("Click on the Menu link") is the best description. Some
    steps have none (the model left it empty and only chose actions); those are described
    from their actions instead, for example "Run a script on the page" or
    "Type 'top' into the search box".
    """
    try:
        if agent.history.history:
            last_item = agent.history.history[-1]
            mo = getattr(last_item, "model_output", None)
            goal = getattr(mo, "next_goal", "") if mo else ""
            if goal and str(goal).strip():
                return str(goal)
            parts = [_describe_action(*a) for a in _step_actions(last_item)]
            if parts:
                # "Click element 3, then press Enter"
                text = ", then ".join([parts[0]] + [p[:1].lower() + p[1:] for p in parts[1:]])
                return _clip(text, _MAX_DESCRIPTION_CHARS)
    except Exception as e:
        logging.debug(f"_format_action failed: {e}")
    return "Processing..."


# What the judge gets besides each step's description: enough to see what the agent
# read on the page (a cart row, a price) without sending it whole pages.
_MAX_EVALUATION_CHARS = 300
_MAX_RESULT_CHARS = 600
_MAX_ERROR_CHARS = 300


def _step_evidence(agent) -> tuple[str, list[str]]:
    """The agent's evaluation and its action results for the step it just finished.

    ``evaluation`` is the model's own verdict on the step before ("Success - the cart
    shows ..."); ``results`` is what each browser action returned: page text the agent
    read, a short note such as "Clicked button 'View Cart'", or an error. The done
    action's text is left out here, it is the run's final report.
    """
    try:
        item = agent.history.history[-1]
    except Exception:
        return "", []
    mo = getattr(item, "model_output", None)
    evaluation = getattr(mo, "evaluation_previous_goal", "") if mo else ""
    return (_clip(evaluation, _MAX_EVALUATION_CHARS) if evaluation else ""), _result_lines(getattr(item, "result", None))


def _result_lines(action_results) -> list[str]:
    """What each browser action returned, for the judge: page text, a short note or an error."""
    lines = []
    for result in action_results or []:
        if getattr(result, "error", None):
            lines.append("error: " + _clip(result.error, _MAX_ERROR_CHARS))
        elif getattr(result, "extracted_content", None) and not getattr(result, "is_done", False):
            lines.append(_clip(result.extracted_content, _MAX_RESULT_CHARS))
    return lines


def _history_length(agent) -> int:
    try:
        return len(agent.history.history)
    except Exception:
        return 0


async def _take_screenshot(agent) -> Optional[str]:
    """Capture a JPEG screenshot (quality 80) of the current page.

    The size is the browser viewport (1280x720 unless the run asked for another),
    about 50-150 KB per screenshot.
    """
    try:
        # browser_use ≥0.11 uses browser_session; older versions used browser_context
        session = getattr(agent, 'browser_session', None) or agent.browser_context
        img_bytes = await session.take_screenshot(format="jpeg", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode()
    except Exception as e:
        logging.error(f"_take_screenshot failed: {type(e).__name__}: {e}")
        return None


def _one_line(text: object, limit: int = 300) -> str:
    return " ".join(str(text).split())[:limit]


def _is_initial_actions(history_item) -> bool:
    """Whether a history item is browser-use's step 0: the actions it runs before the model.

    browser-use opens the URL it finds in the task itself (``directly_open_url``) and
    records that as step number 0. It succeeds without any model call, so it says
    nothing about whether the model works.
    """
    metadata = getattr(history_item, "metadata", None)
    return getattr(metadata, "step_number", None) == 0


def _agent_failure(history) -> tuple[str, bool] | None:
    """Why a finished agent run counts as an error rather than a pass/fail, if it does.

    browser-use swallows model and browser errors as failed steps, so a run that never
    got going (bad API key, model unavailable) or one the model refused part-way comes
    back as a normal history. Returns ``(message, judge)`` for the two cases that are
    reported as errors, or None. ``judge`` says whether the steps taken so far are
    worth sending to the judge:

    * the model declined to continue (``stop_reason=refusal``) and the task is not
      done: the steps before the refusal are real, so they are judged;
    * every step the model drove failed (for example an invalid API key): there is
      nothing to judge, and the first error is shown. browser-use's own opening
      navigation (step 0) is not one of the model's steps.
    """
    try:
        errors = list(history.errors())
        items = list(history.history)
        done = history.is_done()
    except Exception:
        return None
    if len(items) == len(errors):
        errors = [e for item, e in zip(items, errors) if not _is_initial_actions(item)]
    failed = [e for e in errors if e]
    if not failed or done:
        return None
    if any("stop_reason=refusal" in e for e in failed):
        return "The agent model declined to continue this task (safety refusal).", True
    if len(failed) == len(errors):
        first = _one_line(failed[0])
        if llm.key_rejected(first):
            return (
                f"The agent could not complete a single step: the API key was rejected "
                f"(check {llm.api_key_name()}). {first}"
            ), False
        return "The agent could not complete a single step: " + first, False
    return None


def _final_report(history) -> tuple[str | None, bool | None]:
    """The agent's closing report and the success flag it set, if it finished on its own.

    browser-use's ``final_result()`` is the output of the last action, which is the
    agent's report only when that action was ``done``. A run that stopped any other
    way (out of steps, say) may end on page text it extracted, which is no report.
    """
    try:
        if history is None or not history.is_done():
            return None, None
        report = history.final_result()
        report = str(report).strip() if report else ""
        return report or None, history.is_successful()
    except Exception as e:
        logging.debug(f"Final report extraction failed: {type(e).__name__}: {e}")
        return None, None


_AGENT_SAID_NO = "Counted as a fail: the agent itself reported that it did not complete the task."


async def _judge(state: "RunState", result_state_hint: str) -> dict:
    """Run the judge on the steps taken so far, off the event loop and with a time limit."""
    from run_judge import judge_run

    steps_for_judge = [
        {
            "step": s.step,
            "description": s.description,
            "elapsed_ms": s.elapsed_ms,
            "evaluation": s.evaluation,
            "results": s.results,
        }
        for s in state.steps
    ]
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                judge_run, state.goal, steps_for_judge, result_state_hint,
                final_report=state.final_report,
                agent_reported_success=state.agent_reported_success,
            ),
            timeout=_JUDGE_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logging.warning("Judge timed out after %ds", _JUDGE_TIMEOUT_S)
        return {
            "success": False,
            "summary": "Could not analyze the run: the judge took too long. The agent may have completed the task, but results are unavailable.",
            "phases": [],
            "judge_error": "Could not judge the run: the judge took too long.",
        }


async def _finish_with_error(
    state: "RunState", overall_start: datetime, message: str, judge: bool = True
) -> None:
    """End the run as an error. If steps exist the judge still groups them into phases."""
    state.message = message
    if judge and state.steps:
        try:
            state.total_ms = int((datetime.now() - overall_start).total_seconds() * 1000)
            state.status = "analyzing"
            judgment = await _judge(state, "unknown")
            state.success = False
            state.summary = judgment["summary"]
            state.phases = judgment["phases"]
            state.result_state = "error"
            state.status = "complete"
            return
        except Exception:
            logging.exception("Judging the failed run failed")
    state.status = "error"
    state.result_state = "error"


def _error_message(exc: BaseException) -> str:
    """What to tell the user about an exception that ended the run.

    Our own configuration errors carry a message written for the user (for example
    where to install Chromium); anything else stays generic and goes to the log.
    """
    from browser_env import ChromiumNotFoundError

    if isinstance(exc, (llm.LLMError, ChromiumNotFoundError, ValueError)):
        return f"The run encountered an error: {_one_line(exc)}"
    return "The run encountered an error."


async def _record_agent_usage(state: "RunState", agent, shielded: bool = False) -> None:
    """Put the agent's token usage so far on the run state (after a timeout or a cancel).

    The usage comes from the agent's token cost service, which counts every model call
    the agent has made, finished or not. ``shielded`` keeps the read going when the
    surrounding task is being cancelled. Never raises: a run without usage is better
    than a run that cannot be saved.
    """
    try:
        read = agent.token_cost_service.get_usage_summary()
        if shielded:
            read = asyncio.wait_for(asyncio.shield(asyncio.ensure_future(read)), timeout=_USAGE_READ_TIMEOUT_S)
        state.record_usage(await read)
    except Exception as e:
        logging.debug(f"Token usage extraction failed: {type(e).__name__}: {e}")


async def _persist_result(state: "RunState") -> None:
    """Write the run's final state to its run file (see persistence.py)."""
    if not state.persisted_run_id:
        return
    from persistence import persist_steps, persist_run_completion, persist_phases

    try:
        await persist_steps(state.persisted_run_id, [
            {"step_number": s.step, "description": s.description, "elapsed_ms": s.elapsed_ms}
            for s in state.steps
        ])
        await persist_run_completion(
            run_id=state.persisted_run_id,
            status=state.status,
            result_state=state.result_state,
            success=state.success,
            total_ms=state.total_ms,
            input_tokens=state.input_tokens,
            output_tokens=state.output_tokens,
            total_tokens=state.total_tokens,
            estimated_cost_usd=state.cost_usd,
            summary=state.summary,
            cache_read_tokens=state.cache_read_tokens,
            cache_write_tokens=state.cache_write_tokens,
            message=state.message,
            final_report=state.final_report,
            agent_reported_success=state.agent_reported_success,
        )
        await persist_phases(state.persisted_run_id, state.phases)
    except Exception:
        logging.warning("Could not persist run %s", state.run_id, exc_info=True)


async def run_benchmark(state: RunState, url: str, goal: str, viewport: dict | None = None) -> None:
    """
    Run a BrowserUse agent for the benchmark and update state with each step.

    The agent runs on ``llm.agent_llm()`` (BENCHMARK_AGENT_MODEL, claude-sonnet-5-5 by
    default) in a throwaway local headless Chromium, or in a Browserbase session when
    BENCHMARK_BROWSER_PROVIDER=browserbase. It is stopped after BENCHMARK_TIMEOUT_S
    seconds (default 180); the run is then reported as "too_slow". The judge always
    runs on whatever steps exist, plus the agent's final report when it finished on its
    own, and the result is written to the run file. A run is a "pass" only when the
    judge says so and the agent did not itself report that it failed.
    """
    # Deferred import: keeps the server startable even if browser_use is not installed,
    # and avoids import-time side effects (Playwright browser launch).
    from browser_use import Agent
    from browser_env import agent_files_dir, browser_profile, cleanup_profile, track_agent_dir

    overall_start = datetime.now()
    step_start_time: datetime = overall_start
    prev_step_end_time: datetime = overall_start
    history_seen = 0  # browser-use history items already turned into steps

    async def on_step_start(agent):
        nonlocal step_start_time, prev_step_end_time
        step_start_time = datetime.now()
        # For the very first step, align the wall-clock anchor to when it actually started
        if not state.steps:
            prev_step_end_time = step_start_time

    async def on_step_end(agent):
        nonlocal prev_step_end_time, history_seen
        now = datetime.now()
        # Step-to-step wall-clock time: includes LLM reasoning + action execution.
        # For step 1 this equals the action time; for subsequent steps it also
        # captures the inter-step thinking so that sum(elapsed_ms) ≈ total_ms.
        elapsed_ms = int((now - prev_step_end_time).total_seconds() * 1000)
        prev_step_end_time = now
        if _history_length(agent) > history_seen:
            description = _format_action(agent)
            evaluation, results = _step_evidence(agent)
        else:
            # browser-use stored no history item for this step (it timed out inside the
            # agent, say). The newest item is the previous step's, so it describes nothing
            # here; what went wrong is in the agent's last result.
            description = "Step did not complete"
            evaluation = ""
            results = _result_lines(getattr(getattr(agent, "state", None), "last_result", None))
        history_seen = _history_length(agent)
        screenshot_b64 = await _take_screenshot(agent)

        state.steps.append(
            StepRecord(
                step=len(state.steps) + 1,
                description=description,
                elapsed_ms=elapsed_ms,
                screenshot_b64=screenshot_b64,
                evaluation=evaluation,
                results=results,
            )
        )

    timed_out = False
    agent = None     # The browser-use Agent, once it exists (its token usage is read on cancel)
    bb = None        # Browserbase client (for session cleanup in finally)
    bb_session = None
    profile = None   # Browser profile (its temp dirs are removed in finally)
    try:
        agent_timeout = get_agent_timeout()
        agent_chat = llm.agent_llm(state.agent_model or None)
        logging.info("Run %s: agent=%s timeout=%ss url=%s", state.run_id, state.agent_model, agent_timeout, url)

        # Prepend the target URL to the goal so the agent navigates there first
        full_goal = f"Go to {url}\n\n{goal}"

        provider = _get_browser_provider()

        if provider == "browserbase":
            _validate_browser_config()
            from browserbase import Browserbase
            from browserbase._exceptions import RateLimitError

            bb = Browserbase(api_key=os.getenv("BROWSERBASE_API_KEY"))
            bb_project = os.getenv("BROWSERBASE_PROJECT_ID")

            try:
                bb_session = bb.sessions.create(
                    project_id=bb_project,
                    browser_settings={"record_session": True},
                )
            except RateLimitError:
                # Hit concurrent session limit — release stale sessions and retry
                logging.warning("Browserbase concurrent session limit hit, releasing stale sessions")
                try:
                    for s in bb.sessions.list():
                        bb.sessions.update(id=s.id, project_id=bb_project, status="REQUEST_RELEASE")
                    await asyncio.sleep(2)
                except Exception:
                    pass
                bb_session = bb.sessions.create(
                    project_id=bb_project,
                    browser_settings={"record_session": True},
                )

            logging.info("Browserbase session: %s", bb_session.id)

            # Connect via CDP directly — avoids triggering the local browser watchdog
            from browser_use.browser.profile import BrowserProfile
            api_key = os.getenv("BROWSERBASE_API_KEY")
            cdp_url = f"wss://connect.browserbase.com?apiKey={api_key}&sessionId={bb_session.id}"
            profile = BrowserProfile(cdp_url=cdp_url)
        else:
            # Local Chromium: headless unless BENCHMARK_HEADLESS says otherwise, clean
            # throwaway profile, macOS keychain prompts disabled (see browser_env.py).
            profile = browser_profile(viewport=viewport)

        # use_judge=False: browser-use's own end-of-run judge would be a second,
        # unrequested model call; the benchmark has its own judge (run_judge.py).
        # enable_signal_handler=False: this runs inside a server, whose Ctrl-C is not
        # the agent's to pause on.
        agent = Agent(
            task=full_goal,
            llm=agent_chat,
            browser_profile=profile,
            file_system_path=agent_files_dir(profile),
            use_judge=False,
            enable_signal_handler=False,
        )
        if profile is not None and provider != "browserbase":
            track_agent_dir(profile, agent)  # its step screenshots go with the profile

        history = None
        try:
            history = await asyncio.wait_for(
                agent.run(
                    on_step_start=on_step_start,
                    on_step_end=on_step_end,
                ),
                timeout=agent_timeout,
            )

            # Extract token usage from completed run
            try:
                state.record_usage(history.usage)
            except Exception as e:
                logging.debug(f"Token usage extraction failed: {e}")
            state.final_report, state.agent_reported_success = _final_report(history)

        except asyncio.TimeoutError:
            timed_out = True
            logging.info("Agent timed out after %ss", agent_timeout)
            await _record_agent_usage(state, agent)

        # --- Agent finished or timed out — always run the judge ---
        state.total_ms = int((datetime.now() - overall_start).total_seconds() * 1000)

        failure = None if timed_out else _agent_failure(history)
        if failure:
            await _finish_with_error(state, overall_start, failure[0], judge=failure[1])
            return

        state.status = "analyzing"

        # Pass result_state hint so judge knows whether agent timed out
        rs_hint = "too_slow" if timed_out else "completed"
        judgment = await _judge(state, rs_hint)

        state.success = judgment["success"]
        state.summary = judgment["summary"]
        state.phases = judgment["phases"]

        if timed_out:
            # The clock decided this one; the judge only adds the summary and phases.
            state.result_state = "too_slow"
            state.summary = judgment["summary"] or "The agent ran out of time before completing the task."
        elif judgment.get("judge_error"):
            # No verdict: the agent may well have done the task, so this is no fail.
            state.success = False
            state.message = judgment["judge_error"]
            state.status = "error"
            state.result_state = "error"
            return
        elif judgment["success"] and state.agent_reported_success is False:
            # The agent itself said it did not do the task (a product that does not
            # exist, say). However its steps read, that is not "completed as written".
            state.result_state = "fail"
            state.success = False
            state.summary = f"{_AGENT_SAID_NO} {judgment['summary']}"
        else:
            state.result_state = "pass" if judgment["success"] else "fail"

        state.status = "complete"

    except asyncio.CancelledError:
        # POST /benchmark/cancel/<id>: the run ends here, whatever phase it was in.
        state.status = "error"
        state.message = state.message or "Run cancelled by user."
        state.result_state = "error"
        # The agent's calls so far were billed, so the run keeps its time and usage. The
        # agent has stopped by now; reading its counters must not be cut short by the
        # cancellation that brought us here. The time is up to the cancel, not up to now:
        # closing the browser in between is not part of the run.
        state.total_ms = int(((state.stopped_at or datetime.now()) - overall_start).total_seconds() * 1000)
        if agent is not None:
            await _record_agent_usage(state, agent, shielded=True)
        raise
    except Exception as e:
        logging.error("Benchmark run failed: %s: %s", type(e).__name__, e, exc_info=True)
        # The model calls made before the error were billed: keep their usage.
        if agent is not None:
            await _record_agent_usage(state, agent)
        # Still try to run judge if we have steps
        await _finish_with_error(state, overall_start, _error_message(e))
    finally:
        # Release Browserbase session to free quota
        if bb and bb_session:
            try:
                bb.sessions.update(
                    id=bb_session.id,
                    project_id=os.getenv("BROWSERBASE_PROJECT_ID"),
                    status="REQUEST_RELEASE",
                )
            except Exception as e:
                logging.debug("Browserbase session release failed: %s", e)
        logging.info(
            "Run %s finished: status=%s result=%s steps=%d tokens=%d cost=%s",
            state.run_id, state.status, state.result_state, len(state.steps),
            state.total_tokens, "n/a" if state.cost_usd is None else f"${state.cost_usd:.4f}",
        )
        # Saved first: it has no await inside, so nothing can cut it short.
        await _persist_result(state)
        # Stop the run's Chromium if it is somehow still running (by PID, off the event
        # loop: it may wait a few seconds for the browser to exit), then remove the
        # profile, agent-files and screenshot dirs this run created.
        if profile is not None:
            await asyncio.to_thread(cleanup_profile, profile)
