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
import traceback
import logging
from datetime import datetime
from typing import Dict, Any
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


# Track current step index
current_step_index = 0


async def on_step_start(agent):
    """
    Hook function called at the beginning of each agent step.
    Reference: https://docs.browser-use.com/customize/hooks
    """
    global current_step_index
    
    # Get step index from agent history
    try:
        actions = agent.history.model_actions() if hasattr(agent.history, 'model_actions') else []
        step_index = len(actions)
    except:
        step_index = current_step_index
    
    # Extract action information from latest action
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
    
    event = telemetry.log_step_start(
        step_index=step_index,
        action_type=action_type,
        action_data=action_data
    )
    
    telemetry_events.append(convert_event_to_dict(event))
    current_step_index = step_index
    print(f"[Step {step_index} START] Action: {action_type or 'N/A'}")


async def on_step_end(agent):
    """
    Hook function called at the end of each agent step.
    Reference: https://docs.browser-use.com/customize/hooks
    
    Note: Token tracking is not currently implemented as browser-use doesn't expose
    token usage in a straightforward way. Token costs are tracked by OpenAI directly.
    """
    global current_step_index
    
    # Get step index from agent history
    try:
        actions = agent.history.model_actions() if hasattr(agent.history, 'model_actions') else []
        step_index = len(actions) - 1
    except:
        step_index = current_step_index
    
    # Extract observation from extracted content
    observation = None
    try:
        if hasattr(agent.history, 'extracted_content'):
            extracted = agent.history.extracted_content()
            if extracted:
                observation = {'extracted_content': extracted[-1] if isinstance(extracted, list) else extracted}
    except:
        pass
    
    # Token tracking not available - browser-use doesn't expose this easily
    # Costs are tracked by OpenAI directly via API usage dashboard
    event = telemetry.log_step_end(
        step_index=step_index,
        tokens_input=None,  # Not available from browser-use
        tokens_output=None,  # Not available from browser-use
        observation=observation
    )
    
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
    
    logger.info(f"Screenshots: {'ENABLED' if ENABLE_SCREENSHOTS else 'DISABLED'} (Rindler uses accessibility tree)")
    
    # Set up browser-use Agent with gpt-4o
    llm = get_llm_by_name("openai_gpt-4o")
    
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
    
    try:
        result = await asyncio.wait_for(
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
    
    # Print final JSON log output
    print("\n" + "=" * 50)
    print("FINAL TELEMETRY LOG OUTPUT (JSON):")
    print("=" * 50)
    print(json.dumps(telemetry_events, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())

