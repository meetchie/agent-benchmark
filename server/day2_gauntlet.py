#!/usr/bin/env python3
"""
Day 2 Gauntlet - Unified test runner for all telemetric agents.

Usage:
    python day2_gauntlet.py --lane BROWSERUSE
    python day2_gauntlet.py --lane STEEL
    python day2_gauntlet.py --lane SKYVERN
    python day2_gauntlet.py --lane STAGEHAND
"""

import os
import sys
import json
import uuid
import asyncio
import argparse
from datetime import datetime
from dotenv import load_dotenv

# Add clean-room directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adapters import (
    BrowserUseTelemetricAgent,
    SteelTelemetricAgent,
    SkyvernTelemetricAgent,
    StagehandTelemetricAgent,
)

# Load environment variables
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    root_env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    load_dotenv(root_env_path if os.path.exists(root_env_path) else None)

# Lane to agent class mapping
LANE_AGENTS = {
    "BROWSERUSE": BrowserUseTelemetricAgent,
    "STEEL": SteelTelemetricAgent,
    "SKYVERN": SkyvernTelemetricAgent,
    "STAGEHAND": StagehandTelemetricAgent,
}

# The goal
GOAL = """Go to shipt.com.

First, you need to set a delivery address before you can search for products.
Find the address input field (it says "Find stores near you") and enter: 1 Main St, Springfield, IL 62701
Wait for the autocomplete dropdown and click the first suggestion.

Once on the main shopping page, search for "Organic Bananas" and add the first result to your cart.

IMPORTANT - How to verify success:
After clicking the add-to-cart button, look for ANY of these success indicators:
1. The product card shows "X in cart" (e.g., "1 in cart") with a checkmark
2. The cart icon in the top-right shows a number badge (like "1")
3. A toast/notification appears saying the item was added
"""


def calculate_totals(telemetry_events: list) -> dict:
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


async def run_agent(lane: str, run_id: str, wait: bool = True) -> dict:
    """Instantiate and run the correct agent based on lane."""
    AgentClass = LANE_AGENTS[lane]
    
    agent = AgentClass(
        run_id=run_id,
        goal=GOAL,
        lane=lane,
    )
    
    # Run the agent (different agents have different run methods)
    if lane == "BROWSERUSE":
        result = await agent.run()
    elif lane == "STEEL":
        result = await agent.run(start_url="https://shipt.com")
    elif lane == "SKYVERN":
        # Skyvern is a cloud service - default to fire-and-forget
        # Pass --wait flag to poll for completion (can take 15-30+ mins)
        result = await agent.arun(start_url="https://shipt.com", wait=wait)
    elif lane == "STAGEHAND":
        result = await agent.arun(start_url="https://shipt.com")
    else:
        raise ValueError(f"Unknown lane: {lane}")
    
    return {"agent": agent, "result": result}


async def main():
    parser = argparse.ArgumentParser(description="Run telemetric agents against a test goal")
    parser.add_argument(
        "--lane", "-l",
        type=str,
        choices=list(LANE_AGENTS.keys()),
        required=True,
        help="Which agent to use: BROWSERUSE, STEEL, SKYVERN, or STAGEHAND"
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="For SKYVERN: wait for completion instead of fire-and-forget (can take 15-30+ mins)"
    )
    args = parser.parse_args()
    
    lane = args.lane.upper()
    wait_for_completion = args.wait
    run_id = str(uuid.uuid4())
    
    # For Skyvern, default to fire-and-forget mode unless --wait is passed
    skyvern_wait = wait_for_completion if lane == "SKYVERN" else True
    
    print("\n" + "=" * 60)
    print("  GAUNTLET TEST RUNNER")
    print("=" * 60)
    print(f"  Lane:   {lane}")
    print(f"  Run ID: {run_id}")
    if lane == "SKYVERN" and not skyvern_wait:
        print(f"  Mode:   Fire-and-forget (use --wait to poll for completion)")
    print(f"  Goal:   {GOAL}")
    print("=" * 60 + "\n")
    
    start_time = datetime.now()
    
    try:
        result = await run_agent(lane, run_id, wait=skyvern_wait)
        agent = result["agent"]
        run_result = result["result"]
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        # Handle Skyvern fire-and-forget mode
        if lane == "SKYVERN" and not skyvern_wait:
            task_id = run_result.get("task_id") or getattr(agent, "_task_id", None)
            watch_url = run_result.get("watch_url") or getattr(agent, "_app_url", None)
            
            print("\n" + "=" * 60)
            print("  🚀 SKYVERN TASK SUBMITTED")
            print("=" * 60)
            print(f"  Task ID:     {task_id}")
            print(f"  Run ID:      {run_id}")
            print(f"  Trace ID:    {agent.trace_id}")
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
            print("     The task continues running in the cloud.")
            print("=" * 60)
            
            # Save minimal log with task info for later reference
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_dir = os.path.join(os.path.dirname(__file__), "gauntlet_logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, f"gauntlet_{lane.lower()}_{timestamp}.log")
            
            with open(log_path, 'w') as f:
                f.write(f"Lane: {lane}\n")
                f.write(f"Run ID: {run_id}\n")
                f.write(f"Trace ID: {agent.trace_id}\n")
                f.write(f"Skyvern Task ID: {task_id}\n")
                f.write(f"Watch URL: {watch_url}\n")
                f.write(f"Goal: {GOAL}\n")
                f.write(f"Status: submitted (fire-and-forget)\n")
                f.write(f"Submitted at: {datetime.now().isoformat()}\n")
                f.write(f"\nTo get results later:\n")
                f.write(f"  python check_skyvern_billing.py {task_id}\n")
                f.write(f"\nTelemetry Events:\n")
                f.write(json.dumps(agent.telemetry_events, indent=2, default=str))
            
            print(f"\n  Log saved: {log_path}\n")
            return
        
        # Standard flow for other lanes or Skyvern with --wait
        totals = calculate_totals(agent.telemetry_events)
        
        # For Skyvern with --wait, try to fetch billing data from their API
        skyvern_billing = None
        if lane == "SKYVERN" and hasattr(agent, '_task_id') and agent._task_id:
            try:
                print("\n  Fetching Skyvern billing data...")
                skyvern_billing = SkyvernTelemetricAgent.get_run_billing(
                    agent._task_id,
                    verbose=False
                )
                # Update totals with Skyvern billing if available
                if skyvern_billing and skyvern_billing["totals"]["tokens_total"] > 0:
                    totals["tokens_input"] = skyvern_billing["totals"]["tokens_input"]
                    totals["tokens_output"] = skyvern_billing["totals"]["tokens_output"]
                    totals["tokens_total"] = skyvern_billing["totals"]["tokens_total"]
                    totals["cost_usd"] = skyvern_billing["totals"]["cost_usd"]
            except Exception as e:
                print(f"  (Could not fetch Skyvern billing: {e})")
        
        # Print final summary
        print("\n" + "=" * 60)
        print("  FINAL SUMMARY")
        print("=" * 60)
        print(f"  Lane:        {lane}")
        print(f"  Run ID:      {run_id}")
        print(f"  Trace ID:    {agent.trace_id}")
        print(f"  Duration:    {elapsed:.2f}s")
        print(f"  Steps:       {run_result.get('steps', 0)}")
        print(f"  Success:     {run_result.get('success', False)}")
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
        if skyvern_billing and skyvern_billing["steps"]:
            print()
            print("  SKYVERN STEPS")
            print("  -------------")
            for step in skyvern_billing["steps"]:
                action = step.get("action_type") or "action"
                tokens = step.get("tokens_total", 0)
                cost = step.get("cost_usd", 0)
                print(f"  Step {step['step_index']}: {action} | {tokens:,} tokens | ${cost:.4f}")
        
        print("=" * 60)
        
        # Save log file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = os.path.join(os.path.dirname(__file__), "gauntlet_logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"gauntlet_{lane.lower()}_{timestamp}.log")
        
        with open(log_path, 'w') as f:
            f.write(f"Lane: {lane}\n")
            f.write(f"Run ID: {run_id}\n")
            f.write(f"Trace ID: {agent.trace_id}\n")
            f.write(f"Goal: {GOAL}\n")
            f.write(f"Duration: {elapsed:.2f}s\n")
            f.write(f"Token Burn: {totals['tokens_total']:,} ({totals['tokens_input']:,} in / {totals['tokens_output']:,} out)\n")
            f.write(f"Cost: ${totals['cost_usd']:.4f}\n")
            
            # Include Skyvern billing if available
            if skyvern_billing:
                f.write(f"\nSkyvern Task ID: {agent._task_id}\n")
                if agent._app_url:
                    f.write(f"Skyvern URL: {agent._app_url}\n")
                f.write(f"\nSkyvern Billing:\n")
                # Remove raw data before saving
                billing_to_save = {k: v for k, v in skyvern_billing.items() if k != "_raw_run_data"}
                f.write(json.dumps(billing_to_save, indent=2, default=str))
                f.write("\n")
            
            f.write(f"\nTelemetry Events:\n")
            f.write(json.dumps(agent.telemetry_events, indent=2, default=str))
        
        print(f"\n  Log saved: {log_path}\n")
        
    except Exception as e:
        print(f"\n❌ Error running {lane} agent: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
