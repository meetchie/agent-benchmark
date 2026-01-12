"""
Stagehand Telemetric Agent - Browserbase Stagehand AI browser automation with telemetry.

This module provides the StagehandTelemetricAgent class which uses Stagehand's
Python SDK for AI browser automation with Browserbase for cloud browser sessions.

Stagehand provides three core primitives:
- act(): Perform actions on the page using natural language
- extract(): Extract structured data from the page
- observe(): Get information about interactive elements

Reference: https://github.com/browserbase/stagehand
Docs: https://docs.stagehand.dev/v2/first-steps/installation#python
"""

import os
import uuid
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List

import sys
# Add project root to path for telemetric_logger import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from telemetric_logger import TelemetricWrapper, TelemetryEvent


class StagehandTelemetricAgent:
    """
    Browser automation agent using Stagehand Python SDK with Browserbase.
    
    Uses the native Python SDK for Stagehand instead of subprocess calls.
    This provides cleaner integration and better error handling.
    """
    
    def __init__(self, run_id: str, goal: str, lane: str = "STAGEHAND"):
        """
        Initialize the StagehandTelemetricAgent.
        
        Args:
            run_id: Unique identifier for this run
            goal: The task/goal for the agent to accomplish
            lane: Lane identifier (default: "STAGEHAND")
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
        
        # API keys from environment
        self._browserbase_api_key = os.getenv("BROWSERBASE_API_KEY")
        self._browserbase_project_id = os.getenv("BROWSERBASE_PROJECT_ID")
        self._browserbase_org_id = os.getenv("BROWSERBASE_ORG_ID")
        self._model_api_key = os.getenv("OPENAI_API_KEY")
        
        # Step tracking
        self._current_step_index = 0
        
        # Session ID for Browserbase replay
        self._session_id: Optional[str] = None
        
        # Stagehand instance
        self._stagehand = None
    
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
        """Log an artifact event."""
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
    
    def _log_step(self, action_type: str, action_data: Dict[str, Any], observation: Dict[str, Any],
                  tokens_input: Optional[int] = None, tokens_output: Optional[int] = None) -> None:
        """Log a step start and end."""
        self._current_step_index += 1
        
        # Log step start
        start_event = self.telemetry.log_step_start(
            step_index=self._current_step_index,
            action_type=action_type,
            action_data=action_data
        )
        self.telemetry_events.append(self._convert_event_to_dict(start_event))
        
        # Log step end
        end_event = self.telemetry.log_step_end(
            step_index=self._current_step_index,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            observation=observation
        )
        
        event_dict = self._convert_event_to_dict(end_event)
        if event_dict['action_type'] is None:
            event_dict['action_type'] = action_type
        
        self.telemetry_events.append(event_dict)
        
        # Log to console
        success_str = "✓" if observation.get("success", True) else "✗"
        print(f"[Step {self._current_step_index}] {success_str} {action_type}")
    
    async def arun(
        self,
        start_url: Optional[str] = None,
        timeout: float = 300.0,
        max_steps: int = 30
    ) -> Dict[str, Any]:
        """
        Run the Stagehand agent asynchronously.
        
        Args:
            start_url: URL to start at
            timeout: Maximum seconds to wait for completion (default: 300.0)
            max_steps: Maximum number of agent steps (default: 30)
            
        Returns:
            Dictionary with run results and telemetry
        """
        from stagehand import Stagehand
        
        if not self._browserbase_api_key:
            raise ValueError("BROWSERBASE_API_KEY not found in environment variables")
        if not self._model_api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        print(f"Starting Stagehand agent run...")
        print(f"Trace ID: {self.trace_id}")
        print(f"Run ID: {self.run_id}")
        print(f"Lane: {self.lane}")
        print(f"Goal: {self.goal}")
        print("-" * 50)
        
        start_time = datetime.now()
        result = {"success": False, "message": "", "steps": 0}
        
        try:
            # Initialize Stagehand with Browserbase
            self._stagehand = Stagehand(
                env="BROWSERBASE",
                api_key=self._browserbase_api_key,
                project_id=self._browserbase_project_id,
                model_api_key=self._model_api_key,
                model_name="gpt-4o",
            )
            
            await self._stagehand.init()
            
            # Get session ID for replay URL
            self._session_id = getattr(self._stagehand, 'session_id', None) or \
                               getattr(self._stagehand, 'browserbase_session_id', None)
            
            if self._session_id:
                # Build correct Browserbase URL with org and project IDs
                if self._browserbase_org_id and self._browserbase_project_id:
                    session_url = f"https://www.browserbase.com/sessions/{self._session_id}"
                else:
                    # Fallback to simpler URL format
                    session_url = f"https://www.browserbase.com/sessions/{self._session_id}"
                
                self.log_artifact("session_replay", session_url)
                print(f"Session ID: {self._session_id}")
                print(f"Session URL: {session_url}")
            
            # Get the page
            page = self._stagehand.page
            
            # Navigate to start URL if provided
            if start_url:
                await page.goto(start_url)
                self._log_step(
                    action_type="navigate",
                    action_data={"url": start_url},
                    observation={"success": True, "url": start_url}
                )
                print(f"Navigated to: {start_url}")
            
            # Wait for page to settle
            await asyncio.sleep(2)
            
            # Break down the goal into steps and execute
            # First, try using page.act() for simpler tasks
            steps_taken = 0
            goal_parts = self._parse_goal_into_steps(self.goal)
            
            for step_instruction in goal_parts:
                if steps_taken >= max_steps:
                    result["message"] = f"Max steps ({max_steps}) reached"
                    break
                
                try:
                    print(f"\n--- Executing: {step_instruction[:100]}...")
                    
                    # Use page.act() for each step
                    act_result = await page.act(step_instruction)
                    steps_taken += 1
                    
                    self._log_step(
                        action_type="act",
                        action_data={"instruction": step_instruction[:200]},
                        observation={"success": True, "result": str(act_result)[:200] if act_result else "completed"}
                    )
                    
                    # Small delay between actions
                    await asyncio.sleep(1)
                    
                except Exception as step_error:
                    print(f"Step failed: {step_error}")
                    self._log_step(
                        action_type="act",
                        action_data={"instruction": step_instruction[:200]},
                        observation={"success": False, "error": str(step_error)[:200]}
                    )
                    # Continue to next step on failure
                    continue
            
            result["success"] = steps_taken > 0
            result["message"] = f"Completed {steps_taken} steps"
            result["steps"] = steps_taken
            
        except asyncio.TimeoutError:
            result["message"] = f"Timeout after {timeout} seconds"
            result["success"] = False
            
        except Exception as e:
            result["message"] = f"Error: {str(e)}"
            result["success"] = False
            print(f"Error: {e}")
            
        finally:
            # Close Stagehand
            if self._stagehand:
                try:
                    await self._stagehand.close()
                except Exception:
                    pass
        
        elapsed = (datetime.now() - start_time).total_seconds()
        result["steps"] = self._current_step_index
        
        print("-" * 50)
        print(f"Agent completed in {elapsed:.2f} seconds")
        print(f"Total steps: {result['steps']}")
        print(f"Success: {result['success']}")
        print(f"Result: {result['message'][:100]}..." if len(str(result['message'])) > 100 else f"Result: {result['message']}")
        
        return result
    
    def _parse_goal_into_steps(self, goal: str) -> List[str]:
        """
        Parse a complex goal into individual action steps.
        
        This is a simple heuristic parser. For complex goals,
        consider using the agent() method instead.
        """
        steps = []
        
        # Split by common delimiters
        lines = goal.replace('\n\n', '\n').split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Skip headers and labels
            if line.endswith(':') or line.startswith('#'):
                continue
            
            # Skip numbered list markers but keep content
            if line[0].isdigit() and '.' in line[:3]:
                line = line.split('.', 1)[1].strip()
            
            # Skip bullet points but keep content
            if line.startswith('-') or line.startswith('*'):
                line = line[1:].strip()
            
            # Skip lines that are just meta-instructions
            skip_phrases = ['IMPORTANT', 'Note:', 'How to verify', 'success indicators']
            if any(phrase.lower() in line.lower() for phrase in skip_phrases):
                continue
            
            if len(line) > 10:  # Only meaningful instructions
                steps.append(line)
        
        return steps if steps else [goal]  # Fall back to full goal if parsing fails
    
    def run(
        self,
        start_url: Optional[str] = None,
        timeout: float = 300.0
    ) -> Dict[str, Any]:
        """
        Run the agent synchronously.
        
        Args:
            start_url: URL to start at
            timeout: Maximum seconds to wait for completion (default: 300.0)
            
        Returns:
            Dictionary with run results and telemetry
        """
        return asyncio.run(self.arun(start_url, timeout))
