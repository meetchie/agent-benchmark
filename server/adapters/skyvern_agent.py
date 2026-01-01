"""
Skyvern Telemetric Agent - Skyvern AI browser automation with polling telemetry.

This module provides the SkyvernTelemetricAgent class which uses Skyvern's
cloud API with polling-based telemetry logging. The agent submits tasks to
Skyvern and polls for status/steps until completion.

Reference: https://github.com/skyvern-ai/skyvern
API Docs: https://docs.skyvern.com/running-tasks/api-spec
"""

import os
import uuid
import time
import asyncio
import aiohttp
import requests
from datetime import datetime
from typing import Dict, Any, Optional, List

import sys
# Add project root to path for telemetric_logger import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from telemetric_logger import TelemetricWrapper, TelemetryEvent


class SkyvernTelemetricAgent:
    """
    Browser automation agent using Skyvern's cloud API.
    
    Skyvern is an AI-driven browser automation service that automates
    web-based workflows. This adapter submits tasks via POST, then polls
    GET to track progress, logging steps to telemetry as they appear.
    """
    
    BASE_URL = "https://api.skyvern.com/v1"
    
    def __init__(self, run_id: str, goal: str, lane: str = "SKYVERN"):
        """
        Initialize the SkyvernTelemetricAgent.
        
        Args:
            run_id: Unique identifier for this run
            goal: The task/goal for the agent to accomplish
            lane: Lane identifier (default: "SKYVERN")
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
        
        # API key from environment
        self._api_key = os.getenv("SKYVERN_API_KEY")
        
        # Track logged steps to detect new ones
        self._logged_step_count = 0
        
        # Skyvern task ID
        self._task_id: Optional[str] = None
    
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
    
    def _get_headers(self) -> Dict[str, str]:
        """Get API request headers."""
        return {
            "x-api-key": self._api_key,
            "Content-Type": "application/json"
        }
    
    def _process_new_steps(self, steps: List[Dict[str, Any]]) -> int:
        """
        Process any new steps and log them to telemetry.
        
        Args:
            steps: Array of step objects from Skyvern API
            
        Returns:
            Number of new steps processed
        """
        new_steps = 0
        
        for idx, step in enumerate(steps):
            step_index = idx + 1
            
            # Skip already logged steps
            if step_index <= self._logged_step_count:
                continue
            
            new_steps += 1
            
            # Extract step information from Skyvern response
            # Skyvern step structure includes: order, status, output, actions, etc.
            step_type = step.get("step_type") or step.get("type") or "action"
            status = step.get("status") or "completed"
            output = step.get("output") or step.get("result") or {}
            actions = step.get("actions") or []
            
            # Determine action type from step
            action_type = step_type
            if actions and len(actions) > 0:
                first_action = actions[0]
                action_type = first_action.get("action_type") or step_type
            
            # Build action data
            action_data = {
                "step_type": step_type,
                "actions_count": len(actions)
            }
            
            # Log step start
            start_event = self.telemetry.log_step_start(
                step_index=step_index,
                action_type=action_type,
                action_data=action_data
            )
            self.telemetry_events.append(self._convert_event_to_dict(start_event))
            
            # Build observation
            observation = {
                "status": status,
                "output": str(output)[:500] if output else None
            }
            
            # Log step end
            # Note: Skyvern doesn't expose per-step token usage
            end_event = self.telemetry.log_step_end(
                step_index=step_index,
                tokens_input=None,
                tokens_output=None,
                observation=observation
            )
            
            event_dict = self._convert_event_to_dict(end_event)
            if event_dict['action_type'] is None:
                event_dict['action_type'] = action_type
            
            self.telemetry_events.append(event_dict)
            
            # Log to console
            success_str = "✓" if status in ["completed", "success"] else "○"
            print(f"[Step {step_index}] {success_str} {action_type}")
            
            self._logged_step_count = step_index
        
        return new_steps
    
    def run(
        self,
        start_url: Optional[str] = None,
        poll_interval: float = 3.0,
        timeout: float = 300.0
    ) -> Dict[str, Any]:
        """
        Run the Skyvern agent with polling.
        
        Args:
            start_url: Optional URL to start at
            poll_interval: Seconds between status polls (default: 3.0)
            timeout: Maximum seconds to wait for completion (default: 300.0)
            
        Returns:
            Dictionary with run results and telemetry
        """
        if not self._api_key:
            raise ValueError("SKYVERN_API_KEY not found in environment variables")
        
        print(f"Starting Skyvern agent run...")
        print(f"Trace ID: {self.trace_id}")
        print(f"Run ID: {self.run_id}")
        print(f"Lane: {self.lane}")
        print(f"Goal: {self.goal}")
        print("-" * 50)
        
        start_time = datetime.now()
        result = {"success": False, "message": "", "steps": 0}
        
        try:
            # Create task via POST to /run/task (new API)
            payload = {
                "prompt": self.goal,
                "engine": "skyvern-2.0"
            }
            
            if start_url:
                payload["url"] = start_url
            
            response = requests.post(
                f"{self.BASE_URL}/run/task",
                headers=self._get_headers(),
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            
            # Extract task ID from response
            self._task_id = data.get("task_id") or data.get("id")
            if not self._task_id:
                raise ValueError(f"No task ID in response: {data}")
            
            print(f"Skyvern Task ID: {self._task_id}")
            
            # Log Skyvern task as artifact
            task_url = f"https://app.skyvern.com/tasks/{self._task_id}"
            self.log_artifact("skyvern_task", task_url)
            
            # Polling loop
            elapsed = 0.0
            last_status = None
            
            while elapsed < timeout:
                # Get current status
                status_response = requests.get(
                    f"{self.BASE_URL}/tasks/{self._task_id}",
                    headers=self._get_headers()
                )
                status_response.raise_for_status()
                status_data = status_response.json()
                
                # Extract run status
                run_status = status_data.get("status") or "running"
                
                # Log status change
                if run_status != last_status:
                    print(f"Status: {run_status}")
                    last_status = run_status
                
                # Get steps if available
                steps = status_data.get("steps") or []
                
                # Try to get steps from separate endpoint if not in main response
                if not steps:
                    try:
                        steps_response = requests.get(
                            f"{self.BASE_URL}/tasks/{self._task_id}/steps",
                            headers=self._get_headers()
                        )
                        if steps_response.status_code == 200:
                            steps_data = steps_response.json()
                            steps = steps_data if isinstance(steps_data, list) else steps_data.get("steps", [])
                    except Exception:
                        pass
                
                # Process any new steps
                self._process_new_steps(steps)
                
                # Check if completed
                if run_status.lower() in ["completed", "done", "success", "finished"]:
                    result["success"] = True
                    result["message"] = status_data.get("extracted_information") or "Task completed"
                    result["steps"] = self._logged_step_count
                    break
                
                # Check if failed
                if run_status.lower() in ["failed", "error", "cancelled", "timeout", "terminated"]:
                    result["message"] = status_data.get("failure_reason") or f"Task {run_status}"
                    result["steps"] = self._logged_step_count
                    break
                
                # Wait before next poll
                time.sleep(poll_interval)
                elapsed = (datetime.now() - start_time).total_seconds()
            
            else:
                # Timeout reached
                result["message"] = f"Timeout after {timeout} seconds"
                result["steps"] = self._logged_step_count
            
            elapsed = (datetime.now() - start_time).total_seconds()
            print("-" * 50)
            print(f"Agent completed in {elapsed:.2f} seconds")
            print(f"Total steps: {result['steps']}")
            print(f"Result: {result['message'][:100]}..." if len(str(result['message'])) > 100 else f"Result: {result['message']}")
            
        except requests.exceptions.HTTPError as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            result["message"] = f"API Error: {e.response.status_code} - {e.response.text}"
            print(f"HTTP Error after {elapsed:.2f} seconds: {e}")
            raise
        
        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            result["message"] = f"Error: {e}"
            print(f"Error after {elapsed:.2f} seconds: {e}")
            raise
        
        return result
    
    async def arun(
        self,
        start_url: Optional[str] = None,
        poll_interval: float = 3.0,
        timeout: float = 300.0
    ) -> Dict[str, Any]:
        """
        Async version of run() using aiohttp.
        
        Args:
            start_url: Optional URL to start at
            poll_interval: Seconds between status polls (default: 3.0)
            timeout: Maximum seconds to wait for completion (default: 300.0)
            
        Returns:
            Dictionary with run results and telemetry
        """
        if not self._api_key:
            raise ValueError("SKYVERN_API_KEY not found in environment variables")
        
        print(f"Starting Skyvern agent run (async)...")
        print(f"Trace ID: {self.trace_id}")
        print(f"Run ID: {self.run_id}")
        print(f"Lane: {self.lane}")
        print(f"Goal: {self.goal}")
        print("-" * 50)
        
        start_time = datetime.now()
        result = {"success": False, "message": "", "steps": 0}
        
        try:
            async with aiohttp.ClientSession() as session:
                # Create task via POST
                payload = {
                    "prompt": self.goal,
                    "engine": "skyvern-2.0"
                }
                if start_url:
                    payload["url"] = start_url
                
                async with session.post(
                    f"{self.BASE_URL}/run/task",
                    headers=self._get_headers(),
                    json=payload
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    self._task_id = data.get("task_id") or data.get("id")
                
                print(f"Skyvern Task ID: {self._task_id}")
                
                # Log task as artifact
                task_url = f"https://app.skyvern.com/tasks/{self._task_id}"
                self.log_artifact("skyvern_task", task_url)
                
                # Polling loop
                elapsed = 0.0
                last_status = None
                
                while elapsed < timeout:
                    # Get current status
                    async with session.get(
                        f"{self.BASE_URL}/tasks/{self._task_id}",
                        headers=self._get_headers()
                    ) as response:
                        response.raise_for_status()
                        status_data = await response.json()
                    
                    run_status = status_data.get("status") or "running"
                    
                    if run_status != last_status:
                        print(f"Status: {run_status}")
                        last_status = run_status
                    
                    # Get steps
                    steps = status_data.get("steps") or []
                    if not steps:
                        try:
                            async with session.get(
                                f"{self.BASE_URL}/tasks/{self._task_id}/steps",
                                headers=self._get_headers()
                            ) as steps_response:
                                if steps_response.status == 200:
                                    steps_data = await steps_response.json()
                                    steps = steps_data if isinstance(steps_data, list) else steps_data.get("steps", [])
                        except Exception:
                            pass
                    
                    self._process_new_steps(steps)
                    
                    # Check completion
                    if run_status.lower() in ["completed", "done", "success", "finished"]:
                        result["success"] = True
                        result["message"] = status_data.get("extracted_information") or "Task completed"
                        result["steps"] = self._logged_step_count
                        break
                    
                    if run_status.lower() in ["failed", "error", "cancelled", "timeout", "terminated"]:
                        result["message"] = status_data.get("failure_reason") or f"Task {run_status}"
                        result["steps"] = self._logged_step_count
                        break
                    
                    await asyncio.sleep(poll_interval)
                    elapsed = (datetime.now() - start_time).total_seconds()
                
                else:
                    result["message"] = f"Timeout after {timeout} seconds"
                    result["steps"] = self._logged_step_count
            
            elapsed = (datetime.now() - start_time).total_seconds()
            print("-" * 50)
            print(f"Agent completed in {elapsed:.2f} seconds")
            print(f"Total steps: {result['steps']}")
            print(f"Result: {result['message'][:100]}..." if len(str(result['message'])) > 100 else f"Result: {result['message']}")
            
        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            result["message"] = f"Error: {e}"
            print(f"Error after {elapsed:.2f} seconds: {e}")
            raise
        
        return result

