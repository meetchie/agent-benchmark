#!/usr/bin/env python3
"""
Arena - head-to-head runner for the two browser-agent arms.

    BROWSERUSE  browser-use on a local headless Chromium, no site knowledge.
    RINDLER     a tool-calling model driving the site through its Rindler site mapping
                (server/mappings/*.json), run in-process by rindler_local.

Both arms use the same model (BENCHMARK_AGENT_MODEL, default claude-sonnet-5-5) and the
same step budget (--max-steps, default 30). An LLM judge (BENCHMARK_JUDGE_MODEL) grades
every run against the scenario's success criteria, and the run log is written to
arena_runs/ (gitignored) in the same format as the archived March logs in arena_logs/.

Usage:
    uv run python arena.py --agent RINDLER --scenario vhlistings_product_attribute_search
    uv run python arena.py --agent BROWSERUSE --scenario vhlistings_product_attribute_search
    uv run python arena.py --list-agents
    uv run python arena.py --list-scenarios --tag e-commerce
    uv run python arena.py --agent BROWSERUSE --goal "Go to google.com and search for cats" --url https://google.com
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import runtime_env  # noqa: F401,E402  (loads .env and turns browser-use telemetry off first)
import llm  # noqa: E402
from adapters import AGENTS, BaseAgent, get_agent_class  # noqa: E402
from scenarios import Scenario, create_custom_scenario, get_scenario, list_scenarios  # noqa: E402

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RUNS_DIR = os.path.join(SERVER_DIR, "arena_runs")
ARCHIVE_DIR = os.path.join(SERVER_DIR, "arena_logs")


# =============================================================================
# LLM JUDGE
# =============================================================================

JUDGE_SYSTEM_PROMPT = """You are a strict evaluator for browser automation agents. Your job is to determine if an agent successfully completed its assigned task.

You will be given:
1. The original GOAL the agent was supposed to accomplish
2. SUCCESS CRITERIA that define what counts as success
3. A LOG of what the agent actually did (including any errors)
4. The FINAL EXTRACTION (if any) showing what the agent found/accomplished

Based on this information, you must return a JSON verdict:
{
  "verdict": "PASS" or "FAIL",
  "reason": "Brief explanation of why the task passed or failed",
  "details": {
    "criteria_met": ["list of success criteria that were met"],
    "criteria_failed": ["list of success criteria that were NOT met"],
    "errors_observed": ["any errors or issues observed in the log"]
  }
}

IMPORTANT RULES:
- Be STRICT. If the task asked for 3 items and only 1 was verified, that's a FAIL.
- Rate limit errors (429) or "consecutive failures" mean the agent could NOT complete the task = FAIL.
- If the agent got stuck repeating the same action = FAIL.
- If final extraction is missing or incomplete vs what was required = FAIL.
- Only return PASS if ALL success criteria are demonstrably met.

PRODUCT ATTRIBUTE REASONING:
- When a criterion says "NOT Organic" or "NOT [attribute]", a product PASSES if its name does NOT contain that attribute. Absence of "Organic" in a product name means it is conventional (non-organic). Do not require explicit "non-organic" labeling.
- When a criterion says a product should be a specific type (e.g., "tablet/caplet form"), check that the product name matches that type. It does NOT need to explicitly say "not liquid gel" — just verify the name says "Tablets" or "Caplet".
- A "3lb Bag" at quantity 1 satisfies "approximately 3 lbs". Do not require quantity 6 for a 3lb bag.

Return ONLY valid JSON, no markdown formatting."""

# The verdict shape above, enforced through structured outputs.
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "FAIL"]},
        "reason": {"type": "string"},
        "details": {
            "type": "object",
            "properties": {
                "criteria_met": {"type": "array", "items": {"type": "string"}},
                "criteria_failed": {"type": "array", "items": {"type": "string"}},
                "errors_observed": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["criteria_met", "criteria_failed", "errors_observed"],
        },
    },
    "required": ["verdict", "reason", "details"],
}

# Map agent-specific action names to common vocabulary for the judge.
# Anything not in this map passes through as-is.
ACTION_NORMALIZE = {
    "llm_call": "browser_action",
    "act": "browser_action",
    "action": "browser_action",
    "navigate": "navigation",
}

# How much of one action the judge reads: the name, its arguments and, for browser-use, the
# element it targeted. Long arguments (a done message, extracted text) are cut.
ACTION_TEXT_LIMIT = 120


def describe_call(name: Optional[str], args: Any = None, element: Optional[str] = None) -> str:
    """One action as the judge reads it: search_products(query="belt"),
    navigation(url="https://vhlistings.com/search?q=belt", new_tab=false), click(index=9) on "Add to cart".
    An action logged without arguments (the March logs) is its name alone."""
    name = ACTION_NORMALIZE.get(name, name) or "?"
    text = name
    if isinstance(args, dict):
        text += "(" + ", ".join(f"{k}={json.dumps(v, ensure_ascii=False, default=str)}"
                                for k, v in args.items() if v is not None) + ")"
    if element:
        text += f" on {json.dumps(element, ensure_ascii=False)}"
    return text if len(text) <= ACTION_TEXT_LIMIT else text[:ACTION_TEXT_LIMIT - 1] + "…"


def describe_step(event: Dict[str, Any]) -> str:
    """A step_start event as the judge reads it. A Rindler step is one tool call (action_type
    with its input as action_data); a browser-use step lists every action it ran."""
    data = event.get("action_data")
    if isinstance(data, list):
        calls = [describe_call(a.get("action"), a.get("params"), a.get("element"))
                 for a in data if isinstance(a, dict) and a.get("action")]
        if calls:
            return "; ".join(calls)
    if not event.get("action_type"):
        return "no action recorded"
    return describe_call(event["action_type"], data if isinstance(data, dict) else None)


def build_judge_prompt(scenario: Scenario, result: Dict[str, Any], telemetry_events: list) -> str:
    """The judge's user prompt: goal, criteria, a log summary and the agent's final report."""
    if scenario.success_criteria:
        criteria = scenario.success_criteria
    else:
        criteria = """The agent should have completed all steps described in the goal.
Look for evidence that each action was performed and verified."""

    errors_in_log = result.get("errors_detected", [])
    final_extraction = result.get("final_extraction") or "No final extraction available"
    agent_reported_success = result.get("success", False)
    step_count = result.get("steps", 0)

    log_summary_parts = [
        f"Agent reported success: {agent_reported_success}",
        f"Total steps taken: {step_count}",
    ]
    if errors_in_log:
        log_summary_parts.append(f"Errors detected: {'; '.join(errors_in_log)}")

    # Each step as the action it ran with its arguments, for both arms: a search done by
    # opening the site's search URL reads as one, like a search_products(query=...) call.
    actions_taken = [f"Step {event.get('step_index')}: {describe_step(event)}"
                     for event in telemetry_events if event.get("event_type") == "step_start"]
    if actions_taken:
        # Only show first 10 and last 5 to keep context manageable
        if len(actions_taken) > 15:
            shown_actions = actions_taken[:10] + ["..."] + actions_taken[-5:]
        else:
            shown_actions = actions_taken
        log_summary_parts.append("Actions taken:\n" + "\n".join(shown_actions))
    log_summary = "\n".join(log_summary_parts)

    verification_section = ""
    if scenario.verification_hint:
        verification_section = f"""
## VERIFICATION FOCUS
{scenario.verification_hint}
"""

    return f"""## GOAL
{scenario.goal}

## SUCCESS CRITERIA
{criteria}
{verification_section}
## AGENT LOG SUMMARY
{log_summary}

## FINAL EXTRACTION / RESULT
{final_extraction}

## YOUR VERDICT
Evaluate whether this agent run should PASS or FAIL based on the criteria above.
Return your verdict as JSON."""


def run_judge(scenario: Scenario, result: Dict[str, Any], telemetry_events: list,
              model: Optional[str] = None) -> Dict[str, Any]:
    """Grade one run. Returns {verdict, reason, details, judge_model, judge_cost_usd, judge_usage}.

    The judge reads only the agent's own report and its steps' actions with their
    arguments; it never looks at the site. verdict is PASS or FAIL, or ERROR when the
    judge call itself failed.
    """
    model = (model or "").strip() or llm.model_for("judge")
    prompt = build_judge_prompt(scenario, result, telemetry_events)
    try:
        verdict = llm.complete_json(JUDGE_SYSTEM_PROMPT, prompt, VERDICT_SCHEMA, model=model, role="judge")
    except llm.LLMError as e:
        print(f"  ⚠️  Judge evaluation failed: {e}")
        return {
            "verdict": "ERROR",
            "reason": f"Judge evaluation failed: {e}",
            "details": {"error": str(e)},
            "judge_model": model,
        }
    out = dict(verdict)
    if out.get("verdict") not in ("PASS", "FAIL"):
        out["verdict"] = "FAIL"
        out["reason"] = out.get("reason") or "Judge did not return a verdict"
    out["judge_model"] = getattr(verdict, "model", model)
    out["judge_cost_usd"] = getattr(verdict, "cost_usd", None)
    usage = getattr(verdict, "usage", None)
    if usage is not None:
        out["judge_usage"] = usage.to_dict()
    return out


# =============================================================================
# RUN HELPERS
# =============================================================================


def get_company_from_scenario(scenario_name: str) -> str:
    """Extract company/site name from scenario name (first part before underscore)."""
    return scenario_name.split("_")[0]


def calculate_totals(telemetry_events: list) -> Dict[str, Any]:
    """Calculate total token burn and cost from telemetry events."""
    total_tokens_input = 0
    total_tokens_output = 0
    total_cost = 0.0

    for event in telemetry_events:
        if event.get("event_type") == "step_end":
            total_tokens_input += event.get("tokens_input") or 0
            total_tokens_output += event.get("tokens_output") or 0
            total_cost += event.get("cost_usd") or 0.0

    return {
        "tokens_input": total_tokens_input,
        "tokens_output": total_tokens_output,
        "tokens_total": total_tokens_input + total_tokens_output,
        "cost_usd": total_cost,
    }


def print_banner(agent_name: str, scenario: Scenario, run_id: str, model: str, max_steps: int):
    print()
    print("=" * 60)
    print("  ARENA - Agent Test Runner")
    print("=" * 60)
    print(f"  Agent:     {agent_name}")
    print(f"  Model:     {model}")
    print(f"  Max steps: {max_steps}")
    print(f"  Scenario:  {scenario.name}")
    print(f"  Run ID:    {run_id}")
    if scenario.start_url:
        print(f"  URL:       {scenario.start_url}")
    print(f"  Goal:      {scenario.description}")
    print("=" * 60)
    print()


def print_summary(agent: BaseAgent, result: Dict[str, Any], elapsed: float,
                  scenario: Scenario, judge_result: Optional[Dict[str, Any]] = None):
    """Print the final run summary."""
    totals = calculate_totals(agent.telemetry_events)

    print()
    print("=" * 60)
    print("  FINAL SUMMARY")
    print("=" * 60)
    print(f"  Agent:       {agent.lane}")
    print(f"  Scenario:    {scenario.name}")
    print(f"  Run ID:      {agent.run_id}")
    print(f"  Trace ID:    {agent.trace_id}")
    print(f"  Duration:    {elapsed:.2f}s")
    print(f"  Steps:       {result.get('steps', agent._current_step_index)}")
    print(f"  Agent Success: {result.get('success', False)}")

    if judge_result:
        verdict = judge_result.get("verdict", "N/A")
        verdict_icon = "✅" if verdict == "PASS" else "❌"
        print(f"  Judge Verdict: {verdict_icon} {verdict}")
        reason = judge_result.get("reason") or ""
        if reason:
            print(f"  Judge Reason:  {reason[:80] + '...' if len(reason) > 80 else reason}")

    print()
    print("  TOKEN BURN")
    print("  ----------")
    print(f"  Input:       {totals['tokens_input']:,} tokens")
    print(f"  Output:      {totals['tokens_output']:,} tokens")
    print(f"  Total:       {totals['tokens_total']:,} tokens")
    print()
    print("  COST")
    print("  ----")
    print(f"  Agent:       ${totals['cost_usd']:.4f}")
    if judge_result and judge_result.get("judge_cost_usd") is not None:
        print(f"  Judge:       ${judge_result['judge_cost_usd']:.4f}")
    print("=" * 60)
    return totals


def save_log(agent: BaseAgent, result: Dict[str, Any], elapsed: float,
             scenario: Scenario, totals: Dict[str, Any],
             error: Optional[Exception] = None,
             judge_result: Optional[Dict[str, Any]] = None,
             log_dir: Optional[str] = None,
             run_info: Optional[Dict[str, Any]] = None) -> str:
    """Write the run log: header lines, the judge block, totals, then the telemetry JSON.

    The layout is the one the March logs in arena_logs/ use, so analyze_runs.py and the
    viewer read both. Lines added since March ("Agent Model:", "Max Steps:", "Judge
    Model:", "Judge Cost:") sit after "Start URL:" and are ignored by older readers.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    company = get_company_from_scenario(scenario.name)
    log_dir = log_dir or DEFAULT_RUNS_DIR
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"arena_{agent.lane.lower()}_{company}_{timestamp}.log")
    run_info = run_info or {}

    with open(log_path, "w") as f:
        f.write(f"Agent: {agent.lane}\n")
        f.write(f"Scenario: {scenario.name}\n")
        f.write(f"Run ID: {agent.run_id}\n")
        f.write(f"Trace ID: {agent.trace_id}\n")
        f.write(f"Goal: {scenario.goal}\n")
        f.write(f"Start URL: {scenario.start_url or 'N/A'}\n")
        if run_info.get("model"):
            f.write(f"Agent Model: {run_info['model']}\n")
        if run_info.get("max_steps"):
            f.write(f"Max Steps: {run_info['max_steps']}\n")
        if run_info.get("mapping"):
            f.write(f"Mapping: {run_info['mapping']}\n")
        f.write(f"Duration: {elapsed:.2f}s\n")
        f.write(f"Agent Reported Success: {result.get('success', False)}\n")

        errors_detected = result.get("errors_detected", [])
        if errors_detected:
            f.write(f"Errors Detected: {'; '.join(errors_detected)}\n")

        if judge_result:
            f.write("\n--- JUDGE EVALUATION ---\n")
            f.write(f"Judge Verdict: {judge_result.get('verdict', 'N/A')}\n")
            if judge_result.get("reason"):
                f.write(f"Judge Reason: {judge_result.get('reason')}\n")
            details = judge_result.get("details", {})
            if isinstance(details, dict):
                if details.get("criteria_met"):
                    f.write(f"Criteria Met: {', '.join(details['criteria_met'])}\n")
                if details.get("criteria_failed"):
                    f.write(f"Criteria Failed: {', '.join(details['criteria_failed'])}\n")
                if details.get("errors_observed"):
                    f.write(f"Errors Observed by Judge: {', '.join(details['errors_observed'])}\n")
            if judge_result.get("judge_model"):
                f.write(f"Judge Model: {judge_result['judge_model']}\n")
            if judge_result.get("judge_cost_usd") is not None:
                f.write(f"Judge Cost: ${judge_result['judge_cost_usd']:.4f}\n")
            f.write("--- END JUDGE EVALUATION ---\n")

        if error:
            f.write(f"Error: {error}\n")

        f.write(f"Token Burn: {totals['tokens_total']:,} ({totals['tokens_input']:,} in / {totals['tokens_output']:,} out)\n")
        f.write(f"Cost: ${totals['cost_usd']:.4f}\n")
        if result.get("final_extraction"):
            f.write(f"Final Report: {json.dumps(str(result['final_extraction']))}\n")

        f.write("\nTelemetry Events:\n")
        f.write(json.dumps(agent.telemetry_events, indent=2, default=str))

    print(f"\n  Log saved: {log_path}\n")
    return log_path


async def run_agent(agent: BaseAgent, scenario: Scenario) -> Dict[str, Any]:
    """Run an agent on a scenario."""
    return await agent.run(start_url=scenario.start_url)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Arena - run BROWSERUSE or RINDLER on a scenario and judge the result",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python arena.py --agent RINDLER --scenario vhlistings_product_attribute_search
  uv run python arena.py --agent BROWSERUSE --scenario vhlistings_product_attribute_search --max-steps 20
  uv run python arena.py --list-scenarios --tag e-commerce
  uv run python arena.py --agent BROWSERUSE --goal "Search for cats" --url https://google.com

Logs go to arena_runs/ (gitignored). arena_logs/ holds the archived March 2026 runs.
""",
    )
    parser.add_argument("--agent", "-a", type=str.upper, choices=list(AGENTS.keys()),
                        help="Which arm to run: BROWSERUSE or RINDLER")
    parser.add_argument("--scenario", "-s", type=str, help="Scenario name (see --list-scenarios)")
    parser.add_argument("--goal", "-g", type=str, help="Custom goal (instead of a scenario)")
    parser.add_argument("--url", "-u", type=str, help="Start URL for a custom --goal")
    parser.add_argument("--list-agents", action="store_true", help="List the arms and exit")
    parser.add_argument("--list-scenarios", action="store_true", help="List scenarios and exit")
    parser.add_argument("--tag", "-t", type=str, help="Filter --list-scenarios by tag")
    parser.add_argument("--model", "--llm", dest="model", type=str, default=None,
                        help="Agent model for either arm (default: BENCHMARK_AGENT_MODEL, else claude-sonnet-5-5)")
    parser.add_argument("--judge-model", type=str, default=None,
                        help="Judge model (default: BENCHMARK_JUDGE_MODEL, else claude-sonnet-5-5)")
    parser.add_argument("--max-steps", type=int, default=30,
                        help="Step budget, the same for both arms: browser-use steps or Rindler model turns (default 30)")
    parser.add_argument("--timeout", type=float, default=1200.0,
                        help="Stop a run after this many seconds (default 1200; 0 = no limit)")
    parser.add_argument("--mapping", type=str, default=None,
                        help="RINDLER: mapping name or JSON path (default: the mapping whose domain matches the start URL)")
    parser.add_argument("--context-log", action="store_true", default=False,
                        help="RINDLER: also write context_rindler_<ts>.log with every message sent to the model")
    parser.add_argument("--log-dir", type=str, default=None,
                        help=f"Where run logs go (default: {os.path.relpath(DEFAULT_RUNS_DIR, os.getcwd())})")
    parser.add_argument("--no-judge", action="store_true", help="Skip the judge call (verdict N/A)")
    return parser


async def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_agents:
        print("\nAvailable Agents:")
        print("-" * 40)
        for name, cls in AGENTS.items():
            doc = (cls.__doc__ or "").strip().splitlines()
            print(f"  {name:12} - {doc[0] if doc else 'No description'}")
        print()
        return 0

    if args.list_scenarios:
        scenarios = list_scenarios(tag=args.tag)
        tag_str = f" (tag: {args.tag})" if args.tag else ""
        print(f"\nAvailable Scenarios{tag_str}:")
        print("-" * 60)
        for s in scenarios:
            print(f"  {s.name}")
            print(f"    {s.description}")
            print(f"    Tags: {', '.join(s.tags) if s.tags else 'none'}")
            if s.start_url:
                print(f"    URL: {s.start_url}")
            print()
        return 0

    if not args.agent:
        parser.error("--agent is required (use --list-agents to see options)")
    if not args.scenario and not args.goal:
        parser.error("Either --scenario or --goal is required")
    if args.max_steps < 1:
        parser.error("--max-steps must be at least 1")

    if args.scenario:
        try:
            scenario = get_scenario(args.scenario)
        except KeyError as e:
            print(f"Error: {e}")
            print("Use --list-scenarios to see available scenarios")
            return 1
    else:
        scenario = create_custom_scenario(goal=args.goal, start_url=args.url, name="custom")

    if not llm.provider_key_present():
        print("Error: no model API key. Set ANTHROPIC_API_KEY (or OPENAI_API_KEY with LLM_PROVIDER=openai) "
              "in the environment or in a .env file.")
        return 2

    agent_name = args.agent
    agent_cls = get_agent_class(agent_name)
    run_id = str(uuid.uuid4())
    log_dir = args.log_dir or DEFAULT_RUNS_DIR
    model = (args.model or "").strip() or llm.model_for("agent")

    extra: Dict[str, Any] = {"model": model, "max_steps": args.max_steps, "timeout_s": args.timeout or None}
    if agent_name == "RINDLER":
        extra.update(mapping=args.mapping, context_log=args.context_log, log_dir=log_dir)
    agent = agent_cls(run_id=run_id, goal=scenario.goal, lane=agent_name, **extra)

    print_banner(agent_name, scenario, run_id, model, args.max_steps)

    start_time = datetime.now()
    error = None
    try:
        result = await run_agent(agent, scenario)
    except Exception as e:
        error = e
        result = {
            "success": False,
            "message": f"Error: {e}",
            "steps": agent._current_step_index,
            "errors_detected": [f"{type(e).__name__}: {e}"],
        }
        print(f"\n⚠️  Agent encountered error: {e}")
        print(f"   Saving partial telemetry ({len(agent.telemetry_events)} events)...")
    elapsed = (datetime.now() - start_time).total_seconds()

    judge_result: Dict[str, Any] = {}
    if args.no_judge:
        judge_result = {"verdict": "N/A", "reason": "judge skipped (--no-judge)"}
    else:
        print("\n  🧑‍⚖️  Running judge evaluation...")
        judge_result = await asyncio.to_thread(run_judge, scenario, result, agent.telemetry_events, args.judge_model)
        print(f"  Judge verdict: {judge_result.get('verdict', 'N/A')}")

    totals = print_summary(agent, result, elapsed, scenario, judge_result)
    mapping_name = getattr(agent, "mapping_name", None)
    save_log(agent, result, elapsed, scenario, totals, error, judge_result, log_dir=log_dir,
             run_info={"model": model, "max_steps": args.max_steps, "mapping": mapping_name})
    return 1 if error else 0


if __name__ == "__main__":
    import entrypoint

    sys.exit(entrypoint.run_cli(main()))
