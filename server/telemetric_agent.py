"""
Telemetric Agent - Browser automation agent with telemetry tracking.

This module provides the TelemetricAgent class which wraps browser-use Agent
with Browserbase session recording and telemetry logging.
"""

import os
import uuid
import asyncio
import json
from datetime import datetime
from typing import Dict, Any, Optional, List

from browser_use import Agent
from browser_use.llm.models import get_llm_by_name
from browserbase import Browserbase
from telemetric_logger import TelemetricWrapper, TelemetryEvent


class TelemetricAgent:
    """
    Browser automation agent with integrated telemetry tracking.
    
    Wraps browser-use Agent with Browserbase session recording and
    TelemetricWrapper for step-by-step telemetry logging.
    """
    
    def __init__(self, run_id: str, lane: str, goal: str):
        """
        Initialize the TelemetricAgent.
        
        Args:
            run_id: Unique identifier for this run
            lane: Lane identifier (e.g., "LANE_A", "LANE_B")
            goal: The task/goal for the agent to accomplish
        """
        self.run_id = run_id
        self.lane = lane
        self.goal = goal
        
        # Generate trace_id for telemetry
        self.trace_id = str(uuid.uuid4())
        
        # Initialize telemetry wrapper
        self.telemetry = TelemetricWrapper(
            trace_id=self.trace_id,
            run_id=self.run_id,
            lane=self.lane
        )
        
        # Store telemetry events
        self.telemetry_events: List[Dict[str, Any]] = []
        
        # Step tracking
        self._current_step_index = 0
        self._current_action_type: Optional[str] = None
    
    def _convert_event_to_dict(self, event: TelemetryEvent) -> Dict[str, Any]:
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
    
    def log_artifact(self, artifact_type: str, artifact_url: str) -> Dict[str, Any]:
        """
        Log an artifact event (e.g., session replay URL).
        
        Args:
            artifact_type: Type of artifact (e.g., "session_replay")
            artifact_url: URL or path to the artifact
            
        Returns:
            Dictionary representing the artifact event
        """
        event = {
            'trace_id': self.trace_id,
            'run_id': self.run_id,
            'lane': self.lane,
            'event_type': 'artifact',
            'artifact_type': artifact_type,
            'artifact_url': artifact_url,
            'timestamp': datetime.now().isoformat()
        }
        self.telemetry_events.append(event)
        return event
    
    async def run_lane_a(self):
        """
        Run the agent on Lane A with Browserbase session recording.
        
        Initializes a Browserbase session with recording enabled,
        runs the browser-use Agent with telemetry hooks, and logs
        the session replay URL as an artifact.
        
        Returns:
            The agent run history
        """
        # Initialize Browserbase with API key and Project ID from environment
        browserbase_api_key = os.getenv('BROWSERBASE_API_KEY')
        browserbase_project_id = os.getenv('BROWSERBASE_PROJECT_ID')
        
        if not browserbase_api_key:
            raise ValueError("BROWSERBASE_API_KEY not found in environment variables")
        
        # Initialize Browserbase client
        bb = Browserbase(api_key=browserbase_api_key)
        
        # Create a Browserbase session with recording enabled for video URL
        session = bb.sessions.create(
            project_id=browserbase_project_id,
            browser_settings={
                'record_session': True
            }
        )
        
        print(f"Starting agent run...")
        print(f"Trace ID: {self.trace_id}")
        print(f"Run ID: {self.run_id}")
        print(f"Lane: {self.lane}")
        print(f"Goal: {self.goal}")
        print(f"Session ID: {session.id}")
        print("-" * 50)
        
        # Define on_step_start hook
        async def on_step_start(agent):
            """Hook function called at the beginning of each agent step."""
            self._current_step_index += 1
            
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
            
            self._current_action_type = action_type
            
            event = self.telemetry.log_step_start(
                step_index=self._current_step_index,
                action_type=action_type,
                action_data=action_data
            )
            
            self.telemetry_events.append(self._convert_event_to_dict(event))
            print(f"[Step {self._current_step_index}] START - Action: {action_type or 'N/A'}")
        
        # Define on_step_end hook
        async def on_step_end(agent):
            """Hook function called at the end of each agent step."""
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
            event = self.telemetry.log_step_end(
                step_index=self._current_step_index,
                tokens_input=None,  # Will be distributed after run
                tokens_output=None,  # Will be distributed after run
                observation=observation
            )
            
            # Preserve action_type from step_start in the dict
            event_dict = self._convert_event_to_dict(event)
            if event_dict['action_type'] is None and self._current_action_type:
                event_dict['action_type'] = self._current_action_type
            
            self.telemetry_events.append(event_dict)
            
            # Build output string
            duration_str = f"{event.duration_ms:.2f}ms" if event.duration_ms else "N/A"
            print(f"[Step {self._current_step_index}] END   - Duration: {duration_str}")
        
        # Set up LLM using browser-use's helper
        llm = get_llm_by_name("openai_gpt-4o")
        
        # Initialize the browser-use Agent with the task
        agent = Agent(
            task=self.goal,
            llm=llm,
            browserbase_api_key=browserbase_api_key,
            browserbase_project_id=browserbase_project_id,
            browserbase_session_id=session.id,
        )
        
        # Run the agent with hooks
        history = None
        start_time = datetime.now()
        
        try:
            history = await agent.run(
                on_step_start=on_step_start,
                on_step_end=on_step_end
            )
            
            elapsed = (datetime.now() - start_time).total_seconds()
            print("-" * 50)
            print(f"Agent completed successfully in {elapsed:.2f} seconds!")
            
        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            print(f"Error after {elapsed:.2f} seconds: {e}")
            raise
        
        # Get token usage from browser-use's history if available
        total_input_tokens = 0
        total_output_tokens = 0
        
        try:
            if history is not None and hasattr(history, 'usage') and history.usage is not None:
                usage = history.usage
                total_input_tokens = getattr(usage, 'total_prompt_tokens', 0) or 0
                total_output_tokens = getattr(usage, 'total_completion_tokens', 0) or 0
                
                print(f"\nToken Usage: {total_input_tokens} in / {total_output_tokens} out")
        except Exception as e:
            print(f"Could not get token usage: {e}")
        
        # Distribute tokens proportionally across step_end events
        step_end_events = [e for e in self.telemetry_events if e['event_type'] == 'step_end']
        num_steps = len(step_end_events)
        
        if num_steps > 0 and (total_input_tokens > 0 or total_output_tokens > 0):
            tokens_per_step_input = total_input_tokens // num_steps
            tokens_per_step_output = total_output_tokens // num_steps
            remainder_input = total_input_tokens % num_steps
            remainder_output = total_output_tokens % num_steps
            
            step_end_count = 0
            for event in self.telemetry_events:
                if event['event_type'] == 'step_end':
                    extra_in = remainder_input if step_end_count == 0 else 0
                    extra_out = remainder_output if step_end_count == 0 else 0
                    
                    event['tokens_input'] = tokens_per_step_input + extra_in
                    event['tokens_output'] = tokens_per_step_output + extra_out
                    
                    # Calculate cost using TelemetricWrapper's rates ($5/M in, $15/M out)
                    input_cost = (event['tokens_input'] / 1_000_000) * 5.00
                    output_cost = (event['tokens_output'] / 1_000_000) * 15.00
                    event['cost_usd'] = input_cost + output_cost
                    
                    step_end_count += 1
        
        # Log session replay URL as artifact
        # Browserbase session replay URL format
        replay_url = getattr(session, 'replay_url', None)
        if replay_url is None:
            # Construct replay URL if not directly available
            replay_url = f"https://www.browserbase.com/sessions/{session.id}/replay"
        
        artifact_event = self.log_artifact("session_replay", replay_url)
        print(f"\nSession Replay URL: {replay_url}")
        
        return history

