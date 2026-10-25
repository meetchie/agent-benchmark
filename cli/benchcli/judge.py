"""The judge: one LLM call per run, graded against the task's success criteria.

Like the March judge it reads only the agent's own report and its step trace, never the
site, so it can reject a claim the trace contradicts but cannot confirm a price on the
page. Unlike March it also sees the agent's final report (the tasks ask the agent to
"report" names, prices and cart contents, and that report is the evidence).

The model is BENCHMARK_JUDGE_MODEL / --judge-model (default claude-sonnet-5-5), called
through llm.acomplete_json with a JSON schema, so the verdict always parses.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import llm

from .results import FAILURE_CATEGORIES

MAX_ATTEMPTS = 3
MAX_REPORT_CHARS = 4000
MAX_TRACE_FIELD_CHARS = 160

JUDGE_SYSTEM = """You are a strict evaluator of browser automation agents. You are given a task, its success criteria, what the agent reported as its final answer, and the trace of the steps it took. Decide whether the agent met every success criterion.

Rules:
- You cannot see the website. Judge from the agent's final report and the trace only. A claim in the report that the trace contradicts, or that nothing in the trace could have produced, does not count as met.
- Be strict: every success criterion must be demonstrably met. A report that is missing, vague or only partly answers the task is a fail.
- If the agent stopped early, got stuck repeating an action, hit its step limit or ended on an error, that is a fail.
- For a fail, pick the single best failure_category. For a pass, use "none"."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "reasoning": {"type": "string"},
        "failure_category": {"type": "string", "enum": ["none", *FAILURE_CATEGORIES]},
    },
    "required": ["verdict", "reasoning", "failure_category"],
}


def _clip(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + "..."


def build_trace(steps: list[dict[str, Any]]) -> str:
    lines = []
    for s in steps:
        error = f" [ERROR: {_clip(s['error'], MAX_TRACE_FIELD_CHARS)}]" if s.get("error") else ""
        lines.append(
            f"Step {s['step']}: {s.get('action')}({_clip(s.get('action_args') or {}, 100)}) "
            f"-> {_clip(s.get('observation') or 'N/A', MAX_TRACE_FIELD_CHARS)}{error}"
        )
    return "\n".join(lines) or "(no steps were taken)"


def build_prompt(task: dict[str, Any], result: dict[str, Any]) -> str:
    report = result["result"].get("final_report")
    return f"""Task:
{task['goal']}

Success criteria:
{task['success_criteria']}

Agent: {result['meta']['agent']}
Agent reported success: {result['result']['success']}
Steps taken: {result['stats']['total_steps']} of {result['meta'].get('max_steps', '?')} allowed
Run error: {result.get('error') or 'none'}

Agent's final report:
{_clip(report, MAX_REPORT_CHARS) if report else '(the agent gave no final report)'}

Step trace:
{build_trace(result['steps'])}

Did the agent meet the success criteria?"""


def apply_verdict(result: dict[str, Any], verdict: dict[str, Any]) -> None:
    category = verdict.get("failure_category")
    passed = verdict.get("verdict") == "pass"
    if passed or category in (None, "none"):
        category = None
    elif category not in FAILURE_CATEGORIES:
        category = "unknown"
    result["result"]["verdict"] = "pass" if passed else "fail"
    result["result"]["judge_reasoning"] = verdict.get("reasoning", "")
    result["result"]["failure_category"] = None if passed else (category or "unknown")


def set_error(result: dict[str, Any], reason: str, category: str = "unknown") -> None:
    result["result"]["verdict"] = "error"
    result["result"]["judge_reasoning"] = reason
    result["result"]["failure_category"] = category


async def judge_task(
    task: dict[str, Any],
    result: dict[str, Any],
    *,
    model: str | None = None,
    sleep=asyncio.sleep,
) -> dict[str, Any]:
    """Grade one run in place and return it.

    A run that never started (a start error and no steps) is an "error" without a model
    call. Transient API errors are retried (MAX_ATTEMPTS in all); a refusal, a truncated
    reply or a rejected request (400, 401, 403, 404) is not, because asking again cannot change it.
    """
    judge_model = model or llm.model_for("judge")
    if result.get("error") and result["stats"]["total_steps"] == 0:
        set_error(result, f"The agent never got going: {result['error']}", "site_error")
        return result

    prompt = build_prompt(task, result)
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            verdict = await llm.acomplete_json(JUDGE_SYSTEM, prompt, JUDGE_SCHEMA, model=judge_model, role="judge")
        except llm.LLMError as exc:
            last_error = exc
            retryable = exc.kind == "bad_json" or (exc.kind == "api" and exc.status_code not in (400, 401, 403, 404))
            if not retryable or attempt == MAX_ATTEMPTS - 1:
                break
            await sleep(2 ** attempt)
            continue
        apply_verdict(result, verdict)
        result["judge"] = {
            "model": getattr(verdict, "model", judge_model),
            "cost_usd": getattr(verdict, "cost_usd", None),
            "usage": verdict.usage.to_dict() if getattr(verdict, "usage", None) else None,
            "attempts": attempt + 1,
        }
        return result

    set_error(result, f"Judge failed after {attempt + 1} attempt(s): {last_error}")
    result["judge"] = {"model": judge_model, "cost_usd": None, "usage": None, "attempts": attempt + 1}
    return result
