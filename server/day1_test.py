"""
Day 1 Test Script

This script demonstrates the integration of TelemetricWrapper with browser-use Agent.
It loads API keys from .env, initializes telemetry for LANE_A, and runs an agent
that visits Google and searches for 'Rindler AI'.

Token tracking: browser-use wraps LLM methods internally and bypasses LangChain callbacks.
We use browser-use's built-in TokenCost service via history.usage for totals, then
distribute tokens proportionally across steps after the run completes.
"""

import os
import sys
import json
import uuid
import asyncio
import traceback
import logging
from datetime import datetime
from typing import Dict, Any, List
from dotenv import load_dotenv
from browser_use import Agent
from browser_use.llm.models import get_llm_by_name

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

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

# Screenshot configuration - disable by default for Rindler (uses accessibility tree instead)
# Set ENABLE_SCREENSHOTS=true in .env to enable screenshots if needed
ENABLE_SCREENSHOTS = os.getenv('ENABLE_SCREENSHOTS', 'false').lower() in ('true', '1', 'yes')

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


# Track current step using a simple counter (browser-use history timing is unreliable)
current_step_index = 0
current_action_type = None


async def on_step_start(agent):
    """
    Hook function called at the beginning of each agent step.
    Reference: https://docs.browser-use.com/customize/hooks
    """
    global current_step_index, current_action_type
    
    # Increment step counter
    current_step_index += 1
    
    # Extract action information from latest action in history
    action_type = None
    action_data = None
    try:
        if hasattr(agent.history, 'model_actions') and agent.history.model_actions():
            latest_action = agent.history.model_actions()[-1]
            if isinstance(latest_action, dict):
                action_type = list(latest_action.keys())[0] if latest_action else None
                action_data = latest_action
    except:
        pass
    
    current_action_type = action_type
    
    event = telemetry.log_step_start(
        step_index=current_step_index,
        action_type=action_type,
        action_data=action_data
    )
    
    telemetry_events.append(convert_event_to_dict(event))
    print(f"[Step {current_step_index}] START - Action: {action_type or 'N/A'}")


async def on_step_end(agent):
    """
    Hook function called at the end of each agent step.
    Reference: https://docs.browser-use.com/customize/hooks
    
    Note: Per-step token tracking is not possible with browser-use as it wraps
    the LLM internally and bypasses LangChain callbacks. Tokens will be distributed
    proportionally after the run completes using history.usage totals.
    """
    global current_step_index, current_action_type
    
    # Extract observation from extracted content
    observation = None
    try:
        if hasattr(agent.history, 'extracted_content'):
            extracted = agent.history.extracted_content()
            if extracted:
                observation = {'extracted_content': extracted[-1] if isinstance(extracted, list) else extracted}
    except:
        pass
    
    # Log step end using the SAME step_index from step_start
    event = telemetry.log_step_end(
        step_index=current_step_index,
        tokens_input=None,  # Will be distributed after run
        tokens_output=None,  # Will be distributed after run
        observation=observation
    )
    
    # Preserve action_type from step_start in the dict
    event_dict = convert_event_to_dict(event)
    if event_dict['action_type'] is None and current_action_type:
        event_dict['action_type'] = current_action_type
    
    telemetry_events.append(event_dict)
    
    # Build output string
    duration_str = f"{event.duration_ms:.2f}ms" if event.duration_ms else "N/A"
    print(f"[Step {current_step_index}] END   - Duration: {duration_str}")


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
    
    logger.info(f"Screenshots: {'ENABLED' if ENABLE_SCREENSHOTS else 'DISABLED'} (Rindler uses accessibility tree)")
    
    # Set up LLM using browser-use's helper
    llm = get_llm_by_name("openai_gpt-4o")
    logger.info(f"LLM created (type: {type(llm).__name__})")
    
    # Configure agent
    # Note: on_step_start/on_step_end hooks are passed to agent.run(), not Agent()
    agent_kwargs = {
        'task': "Visit https://google.com and search for 'Rindler AI'",
        'llm': llm,
        'browserbase_api_key': BROWSERBASE_API_KEY,
    }
    
    # Add project_id if available
    if BROWSERBASE_PROJECT_ID and BROWSERBASE_PROJECT_ID != '...':
        agent_kwargs['browserbase_project_id'] = BROWSERBASE_PROJECT_ID
    
    # Configure Browserbase browserSettings to disable screenshots
    # Reference: https://docs.browserbase.com/fundamentals/create-browser-session
    if not ENABLE_SCREENSHOTS:
        agent_kwargs['browserbase_browser_settings'] = {
            'recording': False,
            'logging': False,
        }
    
    agent = Agent(**agent_kwargs)
    
    # Run the agent with hooks
    # Reference: https://docs.browser-use.com/customize/hooks
    timeout_seconds = 300.0
    start_time = datetime.now()
    
    history = None
    try:
        history = await asyncio.wait_for(
            agent.run(on_step_start=on_step_start, on_step_end=on_step_end),
            timeout=timeout_seconds
        )
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Agent completed successfully in {elapsed:.2f} seconds")
        print("-" * 50)
        print("Agent completed successfully!")
    except asyncio.TimeoutError:
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.error(f"Agent run timed out after {elapsed:.2f} seconds")
        raise
    except Exception as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.error(f"Error after {elapsed:.2f} seconds: {e}")
        logger.error(traceback.format_exc())
        raise
    
    # Get token usage from browser-use's TokenCost service
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    
    print("\n" + "=" * 50)
    print("TOKEN USAGE SUMMARY (from browser-use):")
    print("=" * 50)
    
    try:
        if history is not None and hasattr(history, 'usage') and history.usage is not None:
            usage = history.usage
            total_input_tokens = getattr(usage, 'total_prompt_tokens', 0) or 0
            total_output_tokens = getattr(usage, 'total_completion_tokens', 0) or 0
            total_cost = getattr(usage, 'total_cost', 0.0) or 0.0
            
            print(f"Total Input Tokens:  {total_input_tokens}")
            print(f"Total Output Tokens: {total_output_tokens}")
            print(f"Total Tokens:        {total_input_tokens + total_output_tokens}")
            print(f"Total Cost:          ${total_cost:.6f}")
        else:
            print("Token usage data not available from history")
    except Exception as e:
        logger.warning(f"Could not get token usage: {e}")
    
    # Distribute tokens proportionally across step_end events
    step_end_events = [e for e in telemetry_events if e['event_type'] == 'step_end']
    num_steps = len(step_end_events)
    
    if num_steps > 0 and (total_input_tokens > 0 or total_output_tokens > 0):
        # Simple even distribution (could be weighted by duration if desired)
        tokens_per_step_input = total_input_tokens // num_steps
        tokens_per_step_output = total_output_tokens // num_steps
        remainder_input = total_input_tokens % num_steps
        remainder_output = total_output_tokens % num_steps
        
        print(f"\nDistributing tokens across {num_steps} steps (~{tokens_per_step_input} in / ~{tokens_per_step_output} out per step)")
        
        step_end_count = 0
        for event in telemetry_events:
            if event['event_type'] == 'step_end':
                # Add remainder to first step_end event
                extra_in = remainder_input if step_end_count == 0 else 0
                extra_out = remainder_output if step_end_count == 0 else 0
                
                event['tokens_input'] = tokens_per_step_input + extra_in
                event['tokens_output'] = tokens_per_step_output + extra_out
                
                # Calculate cost using TelemetricWrapper's rates ($5/M in, $15/M out)
                input_cost = (event['tokens_input'] / 1_000_000) * 5.00
                output_cost = (event['tokens_output'] / 1_000_000) * 15.00
                event['cost_usd'] = input_cost + output_cost
                
                step_end_count += 1
    
    # Print final JSON log output
    print("\n" + "=" * 50)
    print("FINAL TELEMETRY LOG OUTPUT (JSON):")
    print("=" * 50)
    print(json.dumps(telemetry_events, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())

