# run_judge.py
"""LLM judge for benchmark runs.

Analyzes agent steps and produces:
- pass/fail judgment
- human-readable summary
- phase groupings with failed/slow flags

The judge model is ``BENCHMARK_JUDGE_MODEL`` (see ``llm.py``). It sees only the
step text and timings, never screenshots.
"""
import logging

import llm

logger = logging.getLogger(__name__)

# The shape the judge must answer in. With Anthropic it is enforced through
# structured outputs, so the reply always parses; validate_phases still checks that
# the phases cover the real steps.
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "success": {"type": "boolean"},
        "summary": {"type": "string"},
        "phases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "steps": {"type": "array", "items": {"type": "integer"}},
                    "failed": {"type": "boolean"},
                    "slow": {"type": "boolean"},
                },
                "required": ["name", "steps", "failed", "slow"],
            },
        },
    },
    "required": ["success", "summary", "phases"],
}

# A judge call is a few hundred output tokens; this is generous headroom.
_JUDGE_MAX_TOKENS = 8000

JUDGE_PROMPT = """You are a benchmark judge analyzing an AI browser agent's performance on a task.

TASK THE AGENT WAS GIVEN:
{goal}

RESULT STATE: {result_state}
(If "too_slow", the agent hit the timeout and did not finish. If "fail" or "pass", the agent ran to completion.)

STEPS THE AGENT TOOK (with timing):
{steps_text}

Analyze the agent's performance and respond with a JSON object:

{{
  "success": true/false,
  "summary": "2-3 sentence summary of what happened and why it succeeded or failed",
  "phases": [
    {{
      "name": "Descriptive phase name describing user intent (e.g. 'Find the right yoga mat', 'Set delivery address')",
      "steps": [1, 2, 3],
      "failed": false,
      "slow": false
    }}
  ]
}}

RULES:

SUCCESS:
- "success": true only if the agent fully completed the task as described, including verification.
- "summary": Be specific about what went right/wrong. Name the actual products/actions.

PHASE GROUPING:
- Group steps into 3-6 high-level phases. Each step number must appear in exactly one phase. Steps within a phase must be consecutive.
- Phase names should describe the USER INTENT, not technical actions. Good: "Find the right yoga mat", "Verify cart contents". Bad: "Search and click results", "Step 7-10".
- For very short runs (1-3 steps), 1-2 phases are fine. Do not create phases with 0 steps.

SLOW FLAG — absolute 45-second threshold:
- Set "slow" to true on ANY phase where the total step time exceeds 45 seconds, regardless of how other phases performed.
- Also set "slow" to true on phases where the agent made unnecessary retries or seemed confused, even if the phase completed in under 45 seconds.
- Every run should have SOME highlighting. If no phase exceeds 45 seconds and the agent did not make obvious mistakes, still flag the single slowest phase as "slow" so the user always sees useful performance data.
- When in doubt about whether to flag, flag it — it is better to over-highlight than under-highlight.

FAILED FLAG — only on actual mistakes:
- Only set "failed" on a phase if the result state is "fail" AND you can specifically identify the phase where the agent did the wrong thing (selected wrong product, entered wrong info, clicked wrong element, etc.).
- Do NOT default to marking the last phase as failed just because it was the last one. Identify the actual phase where the mistake occurred.
- If the result state is "too_slow" (the agent timed out), do NOT set any phase as "failed". The agent did not do anything wrong — it just ran out of time.
- At most one phase should have failed=true.

Respond with ONLY the JSON object. No markdown, no explanation."""


def _format_steps_for_prompt(steps: list[dict]) -> str:
    """Format step data into a readable string for the prompt."""
    lines = []
    for s in steps:
        ms = s.get("elapsed_ms", 0)
        sec = ms / 1000
        lines.append(f"Step #{s['step']} ({sec:.1f}s): {s['description']}")
    return "\n".join(lines)


def validate_phases(phases: list[dict], steps: list[dict]) -> list[dict] | None:
    """Validate the judge's phase groupings against actual steps.

    Returns enriched phases (with total_ms computed) if valid, None if invalid.
    Validation rules:
    - phases must be non-empty
    - steps must be non-empty
    - every step number must exist in the actual step list
    - every step must appear in exactly one phase (no gaps, no overlaps)
    """
    if not phases or not steps:
        return None

    step_map = {s["step"]: s for s in steps}
    all_step_nums = set(step_map.keys())
    seen = set()

    enriched = []
    for phase in phases:
        phase_steps = phase.get("steps", [])
        if not phase_steps:
            return None

        for num in phase_steps:
            if num not in all_step_nums:
                return None
            if num in seen:
                return None
            seen.add(num)

        total_ms = sum(step_map[num]["elapsed_ms"] for num in phase_steps)
        enriched.append({
            "name": phase.get("name", "Phase"),
            "steps": phase_steps,
            "total_ms": total_ms,
            "failed": bool(phase.get("failed", False)),
            "slow": bool(phase.get("slow", False)),
        })

    # Check all steps are covered
    if seen != all_step_nums:
        return None

    return enriched


def judge_run(goal: str, steps: list[dict], result_state: str = "unknown") -> dict:
    """Ask the judge model to judge a benchmark run.

    Args:
        goal: The task goal the agent was given.
        steps: List of step dicts with keys: step, description, elapsed_ms.
        result_state: One of "pass", "fail", "too_slow", "error", or "unknown".
            Tells the judge whether the agent timed out so it can avoid
            marking phases as failed on timeout runs.

    Returns:
        Dict with keys: success, summary, phases.
        On any model failure (API error, refusal, truncated or unparseable reply)
        returns a safe fallback with success False and empty phases.
    """
    if not steps:
        return {
            "success": False,
            "summary": "No steps were completed.",
            "phases": [],
        }

    steps_text = _format_steps_for_prompt(steps)
    prompt = JUDGE_PROMPT.format(goal=goal, steps_text=steps_text, result_state=result_state)

    try:
        data = llm.complete_json(
            None, prompt, JUDGE_SCHEMA, role="judge", max_tokens=_JUDGE_MAX_TOKENS
        )

        success = bool(data.get("success", False))
        summary = str(data.get("summary", ""))[:500]

        raw_phases = data.get("phases", [])
        validated = validate_phases(raw_phases, steps)
        logger.info(
            "judge ok: model=%s success=%s phases=%d cost=%s summary=%s",
            getattr(data, "model", "?"), success, len(validated or []),
            _fmt_cost(getattr(data, "cost_usd", None)), summary[:80],
        )

        return {
            "success": success,
            "summary": summary or ("Agent completed the task." if success else "Agent did not complete the task."),
            "phases": validated or [],
        }

    except llm.LLMError as e:
        logger.warning("judge failed (%s): %s", e.kind, e)
        if e.kind == "refusal":
            summary = (
                "Could not analyze the run: the judge model declined to review it. "
                "The agent may have completed the task, but results are unavailable."
            )
        else:
            summary = "Could not analyze the run. The agent may have completed the task, but results are unavailable."
        return {"success": False, "summary": summary, "phases": []}

    except Exception as e:
        logger.exception("judge failed: %s: %s", type(e).__name__, e)
        return {
            "success": False,
            "summary": "Could not analyze the run. The agent may have completed the task, but results are unavailable.",
            "phases": [],
        }


def _fmt_cost(cost: float | None) -> str:
    return "n/a" if cost is None else f"${cost:.4f}"
