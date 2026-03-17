#!/usr/bin/env python3
"""
Arena - Unified test runner for browser automation agents.

A clean, composable test runner that separates agent selection from scenario selection.

Usage:
    # Run with specific agent and scenario
    python arena.py --agent BROWSERUSE --scenario shipt_add_to_cart
    python arena.py --agent STEEL --scenario google_search
    python arena.py --agent SKYVERN --scenario amazon_search
    python arena.py --agent STAGEHAND --scenario hacker_news_browse
    
    # List available agents and scenarios
    python arena.py --list-agents
    python arena.py --list-scenarios
    python arena.py --list-scenarios --tag e-commerce
    
    # Custom goal (inline)
    python arena.py --agent STEEL --goal "Go to google.com and search for cats" --url https://google.com
    
    # Skyvern fire-and-forget mode
    python arena.py --agent SKYVERN --scenario shipt_add_to_cart --no-wait
"""

import os
import sys
import json
import uuid
import asyncio
import argparse
from datetime import datetime
from typing import Dict, Any, Optional

# Add clean-room directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
from openai import OpenAI

from adapters import AGENTS, get_agent_class, BaseAgent
from scenarios import SCENARIOS, get_scenario, list_scenarios, Scenario, create_custom_scenario


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

Return ONLY valid JSON, no markdown formatting."""

# Map agent-specific action names to common vocabulary for the judge.
# Anything not in this map passes through as-is.
ACTION_NORMALIZE = {
    "llm_call": "browser_action",
    "act": "browser_action",
    "action": "browser_action",
    "navigate": "navigation",
}


def run_judge(scenario: Scenario, result: Dict[str, Any], telemetry_events: list) -> Dict[str, Any]:
    """
    Run an LLM judge to evaluate whether the agent succeeded.
    
    Args:
        scenario: The scenario that was run
        result: The result dictionary from the agent
        telemetry_events: List of telemetry events from the run
        
    Returns:
        Dictionary with verdict, reason, and details
    """
    client = OpenAI()  # Uses OPENAI_API_KEY from env
    
    # Build the success criteria
    if scenario.success_criteria:
        criteria = scenario.success_criteria
    else:
        # Generate generic criteria from the goal
        criteria = f"""The agent should have completed all steps described in the goal.
Look for evidence that each action was performed and verified."""
    
    # Extract relevant info from telemetry for the judge
    errors_in_log = result.get("errors_detected", [])
    final_extraction = result.get("final_extraction", "No final extraction available")
    agent_reported_success = result.get("success", False)
    step_count = result.get("steps", 0)
    
    # Build a summary of what happened
    log_summary_parts = [
        f"Agent reported success: {agent_reported_success}",
        f"Total steps taken: {step_count}",
    ]
    
    if errors_in_log:
        log_summary_parts.append(f"Errors detected: {'; '.join(errors_in_log)}")
    
    # Add key events from telemetry (actions taken, with normalized names)
    actions_taken = []
    for event in telemetry_events:
        if event.get('event_type') == 'step_start' and event.get('action_type'):
            raw_action = event.get('action_type')
            normalized = ACTION_NORMALIZE.get(raw_action, raw_action)
            actions_taken.append(f"Step {event.get('step_index')}: {normalized}")
    
    if actions_taken:
        # Only show first 10 and last 5 to keep context manageable
        if len(actions_taken) > 15:
            shown_actions = actions_taken[:10] + ["..."] + actions_taken[-5:]
        else:
            shown_actions = actions_taken
        log_summary_parts.append(f"Actions taken: {', '.join(shown_actions)}")
    
    log_summary = "\n".join(log_summary_parts)
    
    # Build the prompt for the judge
    verification_section = ""
    if scenario.verification_hint:
        verification_section = f"""
## VERIFICATION FOCUS
{scenario.verification_hint}
"""

    user_prompt = f"""## GOAL
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
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Use mini for cost efficiency on judge calls
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        
        verdict_json = json.loads(response.choices[0].message.content)
        
        # Ensure required fields exist
        if "verdict" not in verdict_json:
            verdict_json["verdict"] = "FAIL"
            verdict_json["reason"] = "Judge did not return a verdict"
        
        return verdict_json
        
    except Exception as e:
        print(f"  ⚠️  Judge evaluation failed: {e}")
        return {
            "verdict": "ERROR",
            "reason": f"Judge evaluation failed: {e}",
            "details": {"error": str(e)}
        }


# Load environment variables
def load_env():
    """Load environment variables from .env files."""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
    else:
        root_env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
        if os.path.exists(root_env_path):
            load_dotenv(root_env_path)


def get_company_from_scenario(scenario_name: str) -> str:
    """Extract company/site name from scenario name (first part before underscore)."""
    return scenario_name.split("_")[0]


def calculate_totals(telemetry_events: list) -> Dict[str, Any]:
    """Calculate total token burn and cost from telemetry events."""
    total_tokens_input = 0
    total_tokens_output = 0
    total_cost = 0.0
    
    for event in telemetry_events:
        if event.get('event_type') == 'step_end':
            total_tokens_input += event.get('tokens_input') or 0
            total_tokens_output += event.get('tokens_output') or 0
            total_cost += event.get('cost_usd') or 0.0
    
    return {
        'tokens_input': total_tokens_input,
        'tokens_output': total_tokens_output,
        'tokens_total': total_tokens_input + total_tokens_output,
        'cost_usd': total_cost,
    }


def print_banner(agent_name: str, scenario: Scenario, run_id: str):
    """Print the run banner."""
    print()
    print("=" * 60)
    print("  ARENA - Agent Test Runner")
    print("=" * 60)
    print(f"  Agent:    {agent_name}")
    print(f"  Scenario: {scenario.name}")
    print(f"  Run ID:   {run_id}")
    if scenario.start_url:
        print(f"  URL:      {scenario.start_url}")
    print(f"  Goal:     {scenario.description}")
    print("=" * 60)
    print()


def print_summary(agent: BaseAgent, result: Dict[str, Any], elapsed: float, 
                  scenario: Scenario, skyvern_billing: Optional[Dict] = None,
                  judge_result: Optional[Dict[str, Any]] = None):
    """Print the final run summary."""
    totals = calculate_totals(agent.telemetry_events)
    
    # Update totals with Skyvern billing if available
    if skyvern_billing and skyvern_billing.get("totals", {}).get("cost_usd", 0) > 0:
        totals["cost_usd"] = skyvern_billing["totals"]["cost_usd"]
    
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
    
    # Show agent's self-reported success and judge verdict separately
    agent_success = result.get('success', False)
    print(f"  Agent Success: {agent_success}")
    
    if judge_result:
        verdict = judge_result.get('verdict', 'N/A')
        verdict_icon = "✅" if verdict == "PASS" else "❌"
        print(f"  Judge Verdict: {verdict_icon} {verdict}")
        if judge_result.get('reason'):
            reason_preview = judge_result['reason'][:80] + "..." if len(judge_result.get('reason', '')) > 80 else judge_result.get('reason', '')
            print(f"  Judge Reason:  {reason_preview}")
    
    print()
    print("  TOKEN BURN")
    print("  ----------")
    print(f"  Input:       {totals['tokens_input']:,} tokens")
    print(f"  Output:      {totals['tokens_output']:,} tokens")
    print(f"  Total:       {totals['tokens_total']:,} tokens")
    print()
    print("  COST")
    print("  ----")
    print(f"  Total:       ${totals['cost_usd']:.4f}")
    
    # Show Skyvern step breakdown if available
    if skyvern_billing and skyvern_billing.get("steps"):
        print()
        print("  SKYVERN STEPS")
        print("  -------------")
        for step in skyvern_billing["steps"]:
            action = step.get("action_type") or "action"
            cost = step.get("cost_usd", 0)
            print(f"  Step {step['step_index']}: {action} | ${cost:.4f}")
    
    print("=" * 60)
    
    return totals


def save_log(agent: BaseAgent, result: Dict[str, Any], elapsed: float,
             scenario: Scenario, totals: Dict[str, Any], 
             skyvern_billing: Optional[Dict] = None, error: Optional[Exception] = None,
             judge_result: Optional[Dict[str, Any]] = None):
    """Save the run log to a file.
    
    Args:
        agent: The agent that was run
        result: Result dictionary from the agent
        elapsed: Time elapsed in seconds
        scenario: The scenario that was run
        totals: Token/cost totals
        skyvern_billing: Optional Skyvern billing data
        error: Optional exception if one occurred
        judge_result: Optional judge verdict dictionary with keys:
            - verdict: "PASS" or "FAIL"
            - reason: Explanation string
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    company = get_company_from_scenario(scenario.name)
    log_dir = os.path.join(os.path.dirname(__file__), "arena_logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"arena_{agent.lane.lower()}_{company}_{timestamp}.log")
    
    with open(log_path, 'w') as f:
        f.write(f"Agent: {agent.lane}\n")
        f.write(f"Scenario: {scenario.name}\n")
        f.write(f"Run ID: {agent.run_id}\n")
        f.write(f"Trace ID: {agent.trace_id}\n")
        f.write(f"Goal: {scenario.goal}\n")
        f.write(f"Start URL: {scenario.start_url or 'N/A'}\n")
        f.write(f"Duration: {elapsed:.2f}s\n")
        
        # Agent's self-reported success
        agent_success = result.get('success', False)
        f.write(f"Agent Reported Success: {agent_success}\n")
        
        # Errors detected by agent
        errors_detected = result.get('errors_detected', [])
        if errors_detected:
            f.write(f"Errors Detected: {'; '.join(errors_detected)}\n")
        
        # Judge verdict (if available)
        if judge_result:
            f.write(f"\n--- JUDGE EVALUATION ---\n")
            f.write(f"Judge Verdict: {judge_result.get('verdict', 'N/A')}\n")
            if judge_result.get('reason'):
                f.write(f"Judge Reason: {judge_result.get('reason')}\n")
            
            # Include judge details if present
            details = judge_result.get('details', {})
            if details:
                if details.get('criteria_met'):
                    f.write(f"Criteria Met: {', '.join(details['criteria_met'])}\n")
                if details.get('criteria_failed'):
                    f.write(f"Criteria Failed: {', '.join(details['criteria_failed'])}\n")
                if details.get('errors_observed'):
                    f.write(f"Errors Observed by Judge: {', '.join(details['errors_observed'])}\n")
            f.write(f"--- END JUDGE EVALUATION ---\n")
        
        if error:
            f.write(f"Error: {error}\n")
        
        f.write(f"Token Burn: {totals['tokens_total']:,} ({totals['tokens_input']:,} in / {totals['tokens_output']:,} out)\n")
        f.write(f"Cost: ${totals['cost_usd']:.4f}\n")
        
        # Include Skyvern billing if available
        if skyvern_billing:
            task_id = getattr(agent, '_task_id', None)
            app_url = getattr(agent, '_app_url', None)
            if task_id:
                f.write(f"\nSkyvern Task ID: {task_id}\n")
            if app_url:
                f.write(f"Skyvern URL: {app_url}\n")
            f.write(f"\nSkyvern Billing:\n")
            billing_to_save = {k: v for k, v in skyvern_billing.items() if k != "_raw_run_data"}
            f.write(json.dumps(billing_to_save, indent=2, default=str))
            f.write("\n")
        
        f.write(f"\nTelemetry Events:\n")
        f.write(json.dumps(agent.telemetry_events, indent=2, default=str))
    
    print(f"\n  Log saved: {log_path}\n")
    return log_path


async def run_agent(agent: BaseAgent, scenario: Scenario, wait: bool = True) -> Dict[str, Any]:
    """
    Run an agent with a scenario.
    
    Args:
        agent: The agent instance to run
        scenario: The scenario to execute
        wait: For Skyvern, whether to wait for completion
        
    Returns:
        Result dictionary from the agent
    """
    # Build kwargs based on agent type
    kwargs = {}
    
    if agent.lane == "SKYVERN":
        kwargs["wait"] = wait
    
    # Run the agent
    return await agent.run(start_url=scenario.start_url, **kwargs)


def handle_skyvern_fire_and_forget(agent, result: Dict[str, Any], scenario: Scenario):
    """Handle Skyvern fire-and-forget mode output."""
    task_id = result.get("task_id") or getattr(agent, "_task_id", None)
    watch_url = result.get("watch_url") or getattr(agent, "_app_url", None)
    
    print()
    print("=" * 60)
    print("  🚀 SKYVERN TASK SUBMITTED")
    print("=" * 60)
    print(f"  Task ID:     {task_id}")
    print(f"  Run ID:      {agent.run_id}")
    print(f"  Trace ID:    {agent.trace_id}")
    print(f"  Scenario:    {scenario.name}")
    print()
    print("  📺 WATCH PROGRESS")
    print("  -----------------")
    if watch_url:
        print(f"  {watch_url}")
    print()
    print("  ⏳ CHECK STATUS LATER")
    print("  --------------------")
    print(f"  python check_skyvern_billing.py {task_id} --status-only")
    print()
    print("  📊 GET FULL BILLING (when complete)")
    print("  -----------------------------------")
    print(f"  python check_skyvern_billing.py {task_id}")
    print()
    print("  💡 TIP: Skyvern tasks typically take 15-30 minutes.")
    print("=" * 60)
    
    # Save minimal log
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    company = get_company_from_scenario(scenario.name)
    log_dir = os.path.join(os.path.dirname(__file__), "arena_logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"arena_skyvern_{company}_{timestamp}.log")
    
    with open(log_path, 'w') as f:
        f.write(f"Agent: SKYVERN\n")
        f.write(f"Scenario: {scenario.name}\n")
        f.write(f"Run ID: {agent.run_id}\n")
        f.write(f"Trace ID: {agent.trace_id}\n")
        f.write(f"Skyvern Task ID: {task_id}\n")
        f.write(f"Watch URL: {watch_url}\n")
        f.write(f"Goal: {scenario.goal}\n")
        f.write(f"Agent Reported Success: submitted\n")
        f.write(f"Status: submitted (fire-and-forget)\n")
        f.write(f"Submitted at: {datetime.now().isoformat()}\n")
        f.write(f"\nTo get results later:\n")
        f.write(f"  python check_skyvern_billing.py {task_id}\n")
        f.write(f"\nTelemetry Events:\n")
        f.write(json.dumps(agent.telemetry_events, indent=2, default=str))
    
    print(f"\n  Log saved: {log_path}\n")


async def main():
    load_env()
    
    parser = argparse.ArgumentParser(
        description="Arena - Test browser automation agents against scenarios",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python arena.py --agent BROWSERUSE --scenario shipt_add_to_cart
  python arena.py --agent STEEL --scenario google_search
  python arena.py --agent SKYVERN --scenario amazon_search --no-wait
  python arena.py --list-scenarios --tag e-commerce
  python arena.py --agent STEEL --goal "Search for cats" --url https://google.com
"""
    )
    
    # Agent selection
    parser.add_argument(
        "--agent", "-a",
        type=str,
        choices=list(AGENTS.keys()),
        help="Which agent to use: BROWSERUSE, STEEL, SKYVERN, or STAGEHAND"
    )
    
    # Scenario selection
    parser.add_argument(
        "--scenario", "-s",
        type=str,
        help="Scenario name to run (use --list-scenarios to see options)"
    )
    
    # Custom goal (alternative to scenario)
    parser.add_argument(
        "--goal", "-g",
        type=str,
        help="Custom goal/prompt (alternative to using a predefined scenario)"
    )
    
    parser.add_argument(
        "--url", "-u",
        type=str,
        help="Starting URL (used with --goal for custom scenarios)"
    )
    
    # Skyvern-specific
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="For SKYVERN: submit task and return immediately (fire-and-forget)"
    )
    
    # Listing options
    parser.add_argument(
        "--list-agents",
        action="store_true",
        help="List available agents and exit"
    )
    
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List available scenarios and exit"
    )
    
    parser.add_argument(
        "--tag", "-t",
        type=str,
        help="Filter scenarios by tag (use with --list-scenarios)"
    )

    # Rindler-specific
    parser.add_argument(
        "--llm",
        type=str,
        default="gpt-4o",
        help="LLM model for RINDLER agent (e.g., gpt-4o, gpt-4o-mini, claude-sonnet)"
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=25,
        help="Max action steps for RINDLER agent"
    )

    args = parser.parse_args()
    
    # Handle listing options
    if args.list_agents:
        print("\nAvailable Agents:")
        print("-" * 40)
        for name, cls in AGENTS.items():
            print(f"  {name:12} - {cls.__doc__.split(chr(10))[1].strip() if cls.__doc__ else 'No description'}")
        print()
        return
    
    if args.list_scenarios:
        scenarios = list_scenarios(tag=args.tag)
        tag_str = f" (tag: {args.tag})" if args.tag else ""
        print(f"\nAvailable Scenarios{tag_str}:")
        print("-" * 60)
        for s in scenarios:
            tags_str = ", ".join(s.tags) if s.tags else "none"
            print(f"  {s.name}")
            print(f"    {s.description}")
            print(f"    Tags: {tags_str}")
            if s.start_url:
                print(f"    URL: {s.start_url}")
            print()
        return
    
    # Validate required arguments
    if not args.agent:
        parser.error("--agent is required (use --list-agents to see options)")
    
    if not args.scenario and not args.goal:
        parser.error("Either --scenario or --goal is required")
    
    # Get or create scenario
    if args.scenario:
        try:
            scenario = get_scenario(args.scenario)
        except KeyError as e:
            print(f"Error: {e}")
            print("Use --list-scenarios to see available scenarios")
            sys.exit(1)
    else:
        # Custom scenario from --goal
        scenario = create_custom_scenario(
            goal=args.goal,
            start_url=args.url,
            name="custom"
        )
    
    # Get agent class and create instance
    agent_name = args.agent.upper()
    AgentClass = get_agent_class(agent_name)
    run_id = str(uuid.uuid4())
    
    extra_kwargs = {}
    if agent_name == "RINDLER":
        extra_kwargs["llm"] = args.llm
        extra_kwargs["max_steps"] = args.max_steps

    agent = AgentClass(
        run_id=run_id,
        goal=scenario.goal,
        lane=agent_name,
        **extra_kwargs,
    )
    
    # Determine if we should wait (Skyvern-specific)
    should_wait = not args.no_wait
    
    print_banner(agent_name, scenario, run_id)
    
    start_time = datetime.now()
    result = None
    error = None
    
    try:
        result = await run_agent(agent, scenario, wait=should_wait)
        
        # Handle Skyvern fire-and-forget
        if agent_name == "SKYVERN" and not should_wait:
            handle_skyvern_fire_and_forget(agent, result, scenario)
            return
        
    except Exception as e:
        error = e
        result = {
            "success": False,
            "message": f"Error: {e}",
            "steps": agent._current_step_index
        }
        print(f"\n⚠️  Agent encountered error: {e}")
        print(f"   Saving partial telemetry ({len(agent.telemetry_events)} events)...")
    
    elapsed = (datetime.now() - start_time).total_seconds()
    
    # Fetch Skyvern billing if applicable
    skyvern_billing = None
    if agent_name == "SKYVERN" and hasattr(agent, '_task_id') and agent._task_id:
        try:
            from adapters import SkyvernTelemetricAgent
            print("\n  Fetching Skyvern billing data...")
            skyvern_billing = await asyncio.to_thread(
                SkyvernTelemetricAgent.get_run_billing,
                agent._task_id,
                verbose=False
            )
        except Exception as e:
            print(f"  (Could not fetch Skyvern billing: {e})")
    
    # Run LLM judge to evaluate success
    judge_result = {}
    try:
        print("\n  🧑‍⚖️  Running judge evaluation...")
        judge_result = run_judge(scenario, result, agent.telemetry_events)
        print(f"  Judge verdict: {judge_result.get('verdict', 'N/A')}")
    except Exception as judge_err:
        print(f"  ⚠️  Judge evaluation failed: {judge_err}")
        judge_result = {"verdict": "error", "error": str(judge_err)}
    
    # Print summary and save log
    totals = print_summary(agent, result, elapsed, scenario, skyvern_billing, judge_result)
    save_log(agent, result, elapsed, scenario, totals, skyvern_billing, error, judge_result)
    
    # Exit with error code if there was a failure
    if error:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
