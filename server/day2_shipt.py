"""
Day 2 Shipt Test Script

This script runs TelemetricAgent to automate shopping on shipt.com.
It handles location setup and adds Organic Bananas to the cart.
"""

import os
import sys
import json
import uuid
import asyncio
from dotenv import load_dotenv

# Add parent directory to path to import telemetric_logger from root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from telemetric_agent import TelemetricAgent

# Load environment variables from .env file
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    root_env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    if os.path.exists(root_env_path):
        load_dotenv(root_env_path)
    else:
        load_dotenv()

# Verify required environment variables
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
BROWSERBASE_API_KEY = os.getenv('BROWSERBASE_API_KEY')
BROWSERBASE_PROJECT_ID = os.getenv('BROWSERBASE_PROJECT_ID')

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in .env file")
if not BROWSERBASE_API_KEY:
    raise ValueError("BROWSERBASE_API_KEY not found in .env file")
if not BROWSERBASE_PROJECT_ID or BROWSERBASE_PROJECT_ID == '...':
    print("Warning: BROWSERBASE_PROJECT_ID not set or is a placeholder. Some features may not work.")

# Set API keys in environment
os.environ['OPENAI_API_KEY'] = OPENAI_API_KEY
os.environ['BROWSERBASE_API_KEY'] = BROWSERBASE_API_KEY
if BROWSERBASE_PROJECT_ID and BROWSERBASE_PROJECT_ID != '...':
    os.environ['BROWSERBASE_PROJECT_ID'] = BROWSERBASE_PROJECT_ID

# Goal prompt for Shipt shopping automation
GOAL_PROMPT = """
Go to shipt.com.

PHASE 1: HANDLE LOCATION (If needed)
Check if the search bar is missing. If you need to set a location:

IMPORTANT: Look for an INPUT FIELD or a BUTTON that contains text like "Find stores near you" or has aria-label="Find stores near you - address input". This is typically a large text input field at the top of the page.

DO NOT click any link or button that says "Enter address manually" or "enter your address manually" - this will break the flow!

1. Click directly on the address input field (it may look like a search box with placeholder text about finding stores).
2. Type "1 Main St, Springfield, IL 62701" into the input.
3. Wait 2-3 seconds for the autocomplete dropdown to appear with address suggestions.
4. Click on the first address suggestion in the dropdown (it should show the full address with zip code like "02139").
5. If a store selection page appears, click on the first available store (like "Target" or "Star Market"), then click "Continue" or "Get Started" or "Shop this store".

PHASE 2: SHOPPING
Once you see the main shopping page with a search bar (look for input with name="product-search" or placeholder text about searching products):

1. Click on the search input field.
2. Type "Organic Bananas" and press Enter or click the search button.
3. Wait for search results to load.
4. Find the first product result for bananas.
5. Click the "Add" button on that product. Look for a button with text "Add" or "+" or data-dtname="product-quantity-quick-add".
6. If any popup appears (like "Choose a substitute" or similar), click "Don't substitute" or "No thanks" or close/dismiss it.

The task is complete when you have successfully added Organic Bananas to the cart.
"""


async def main():
    """Main function to run the TelemetricAgent for Shipt shopping."""
    # Generate a unique run_id
    run_id = str(uuid.uuid4())
    
    # Instantiate TelemetricAgent
    agent = TelemetricAgent(
        run_id=run_id,
        lane="LANE_A",
        goal=GOAL_PROMPT
    )
    
    # Run the agent
    await agent.run_lane_a()
    
    # Print the JSON logs at the end
    print("\n" + "=" * 50)
    print("FINAL TELEMETRY LOG OUTPUT (JSON):")
    print("=" * 50)
    print(json.dumps(agent.telemetry_events, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())

