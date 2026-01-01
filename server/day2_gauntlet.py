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


async def run_agent(lane: str, run_id: str) -> dict:
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
        # Skyvern is a cloud service - uses 15 min default timeout
        # Pass wait=False for fire-and-forget mode
        result = await agent.arun(start_url="https://shipt.com")
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
    args = parser.parse_args()
    
    lane = args.lane.upper()
    run_id = str(uuid.uuid4())
    
    print("\n" + "=" * 60)
    print("  GAUNTLET TEST RUNNER")
    print("=" * 60)
    print(f"  Lane:   {lane}")
    print(f"  Run ID: {run_id}")
    print(f"  Goal:   {GOAL}")
    print("=" * 60 + "\n")
    
    start_time = datetime.now()
    
    try:
        result = await run_agent(lane, run_id)
        agent = result["agent"]
        run_result = result["result"]
        
        elapsed = (datetime.now() - start_time).total_seconds()
        totals = calculate_totals(agent.telemetry_events)
        
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
        print("=" * 60)
        
        # Save log file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = os.path.join(os.path.dirname(__file__), "browser_use_logs")
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
