"""
Day 1 Test Script

This script demonstrates the integration of TelemetricWrapper with browser-use Agent.
It loads API keys from .env, initializes telemetry for LANE_A, and runs an agent
that visits Google and searches for 'Rindler AI'.
"""

import os
import sys
import json
import uuid
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from browser_use import Agent
from browser_use.llm.models import get_llm_by_name

# Add parent directory to path to import telemetric_logger from root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from telemetric_logger import TelemetricWrapper, TelemetryEvent

# Load environment variables from .env file
# Try loading from clean-room/.env first, then fall back to root .env
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    # Fall back to root .env if clean-room/.env doesn't exist
    root_env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    if os.path.exists(root_env_path):
        load_dotenv(root_env_path)
    else:
        load_dotenv()  # Try current directory or default .env location

# Retrieve API keys from environment variables
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
BROWSERBASE_API_KEY = os.getenv('BROWSERBASE_API_KEY')
BROWSERBASE_PROJECT_ID = os.getenv('BROWSERBASE_PROJECT_ID')

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in .env file")
if not BROWSERBASE_API_KEY:
    raise ValueError("BROWSERBASE_API_KEY not found in .env file")
# BROWSERBASE_PROJECT_ID is optional, but warn if not set
if not BROWSERBASE_PROJECT_ID or BROWSERBASE_PROJECT_ID == '...':
    print("Warning: BROWSERBASE_PROJECT_ID not set or is a placeholder. Some features may not work.")

# Generate unique IDs for trace and run
trace_id = str(uuid.uuid4())
run_id = str(uuid.uuid4())

# Initialize TelemetricWrapper for 'LANE_A'
telemetry = TelemetricWrapper(
    trace_id=trace_id,
    run_id=run_id,
    lane='LANE_A'
)

# Store all telemetry events for final output
telemetry_events: list[Dict[str, Any]] = []


def convert_event_to_dict(event: TelemetryEvent) -> Dict[str, Any]:
    """Convert TelemetryEvent dataclass to dictionary for JSON serialization."""
    return {
        'trace_id': event.trace_id,
        'run_id': event.run_id,
        'lane': event.lane,
        'step_index': event.step_index,
        'event_type': event.event_type,
        'timestamp': event.timestamp.isoformat(),
        'duration_ms': event.duration_ms,
        'tokens_input': event.tokens_input,
        'tokens_output': event.tokens_output,
        'cost_usd': event.cost_usd,
        'action_type': event.action_type,
        'observation_hash': event.observation_hash
    }


# Track current step index
current_step_index = 0


def on_step_start(*args, **kwargs):
    """
    Callback function called when a step starts.
    Handles different possible callback signatures from browser-use Agent.
    """
    global current_step_index
    
    # Extract step_index from args or kwargs
    step_index = kwargs.get('step_index', current_step_index)
    if args and isinstance(args[0], int):
        step_index = args[0]
    
    # Extract action_type from kwargs
    action_type = kwargs.get('action_type') or kwargs.get('action') or None
    
    # Extract action_data from kwargs if available
    action_data = {k: v for k, v in kwargs.items() 
                   if k not in ['step_index', 'action_type', 'action']}
    
    event = telemetry.log_step_start(
        step_index=step_index,
        action_type=action_type,
        action_data=action_data if action_data else None
    )
    
    # Store the event
    telemetry_events.append(convert_event_to_dict(event))
    
    current_step_index = step_index
    print(f"[Step {step_index} START] Action: {action_type or 'N/A'}")


def on_step_end(*args, **kwargs):
    """
    Callback function called when a step ends.
    Handles different possible callback signatures from browser-use Agent.
    """
    global current_step_index
    
    # Extract step_index from args or kwargs
    step_index = kwargs.get('step_index', current_step_index)
    if args and isinstance(args[0], int):
        step_index = args[0]
    
    # Extract token information from kwargs
    tokens_input = kwargs.get('tokens_input') or kwargs.get('input_tokens')
    tokens_output = kwargs.get('tokens_output') or kwargs.get('output_tokens')
    
    # Extract observation from kwargs
    observation = kwargs.get('observation') or kwargs.get('obs')
    
    event = telemetry.log_step_end(
        step_index=step_index,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        observation=observation
    )
    
    # Store the event
    telemetry_events.append(convert_event_to_dict(event))
    
    cost_str = f", Cost: ${event.cost_usd:.6f}" if event.cost_usd else ""
    duration_str = f"{event.duration_ms:.2f}ms" if event.duration_ms else "N/A"
    print(f"[Step {step_index} END] Duration: {duration_str}{cost_str}")


async def main():
    """Main function to run the browser-use agent."""
    print(f"Starting agent run...")
    print(f"Trace ID: {trace_id}")
    print(f"Run ID: {run_id}")
    print(f"Lane: LANE_A")
    print("-" * 50)
    
    # Set API keys in environment (browser-use may read from env)
    os.environ['OPENAI_API_KEY'] = OPENAI_API_KEY
    os.environ['BROWSERBASE_API_KEY'] = BROWSERBASE_API_KEY
    if BROWSERBASE_PROJECT_ID and BROWSERBASE_PROJECT_ID != '...':
        os.environ['BROWSERBASE_PROJECT_ID'] = BROWSERBASE_PROJECT_ID
    
    # Set up browser-use Agent with gpt-4o
    llm = get_llm_by_name("openai_gpt-4o")
    
    agent_kwargs = {
        'task': "Visit https://google.com and search for 'Rindler AI'",
        'llm': llm,
        'browserbase_api_key': BROWSERBASE_API_KEY,
        'on_step_start': on_step_start,
        'on_step_end': on_step_end,
    }
    # Add project_id if available
    if BROWSERBASE_PROJECT_ID and BROWSERBASE_PROJECT_ID != '...':
        agent_kwargs['browserbase_project_id'] = BROWSERBASE_PROJECT_ID
    
    agent = Agent(**agent_kwargs)
    
    # Run the agent
    try:
        result = await agent.run()
        print("-" * 50)
        print("Agent completed successfully!")
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error running agent: {e}")
        raise
    
    # Print final JSON log output
    print("\n" + "=" * 50)
    print("FINAL TELEMETRY LOG OUTPUT (JSON):")
    print("=" * 50)
    print(json.dumps(telemetry_events, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())

