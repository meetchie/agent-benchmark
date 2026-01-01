"""
Skyvern Telemetric Agent - Skyvern AI browser automation with polling telemetry.

This module provides the SkyvernTelemetricAgent class which uses Skyvern's
cloud API with polling-based telemetry logging. The agent submits tasks to
Skyvern and polls for status/steps until completion.

Reference: https://github.com/skyvern-ai/skyvern
API Docs: https://www.skyvern.com/docs/api-reference/api-reference/agent/run-task
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
    
    API Endpoints:
    - POST /v1/run/tasks - Create and run a task
    - GET /v1/runs/:run_id - Get task status by run_id
    """
    
    BASE_URL = "https://api.skyvern.com/v1"
    
    # Default timeout for cloud tasks (15 minutes)
    DEFAULT_TIMEOUT = 900.0
    
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
        
        # Skyvern task ID (run_id from API response)
        self._task_id: Optional[str] = None
        
        # Store last status data for debugging
        self._last_status_data: Optional[Dict[str, Any]] = None
    
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
    
    def _capture_skyvern_telemetry(self, status_data: Dict[str, Any]) -> None:
        """
        Capture all available telemetry from Skyvern's API response.
        
        Skyvern returns: run_id, status, output, recording_url, screenshot_urls,
        failure_reason, created_at, modified_at, started_at, finished_at, app_url
        """
        # Log recording URL as artifact
        recording_url = status_data.get("recording_url")
        if recording_url:
            self.log_artifact("skyvern_recording", recording_url)
            print(f"📹 Recording URL: {recording_url}")
        
        # Log app URL as artifact
        app_url = status_data.get("app_url")
        if app_url:
            self.log_artifact("skyvern_app_url", app_url)
        
        # Log screenshots
        screenshot_urls = status_data.get("screenshot_urls") or []
        for i, url in enumerate(screenshot_urls[:5]):  # Limit to first 5
            self.log_artifact(f"skyvern_screenshot_{i}", url)
        if screenshot_urls:
            print(f"📸 Screenshots: {len(screenshot_urls)} captured")
        
        # Log timing information
        timing_event = {
            'trace_id': self.trace_id,
            'run_id': self.run_id,
            'lane': self.lane,
            'event_type': 'skyvern_timing',
            'status': status_data.get('status'),
            'created_at': status_data.get('created_at'),
            'started_at': status_data.get('started_at'),
            'finished_at': status_data.get('finished_at'),
            'queued_at': status_data.get('queued_at'),
            'timestamp': datetime.now().isoformat()
        }
        self.telemetry_events.append(timing_event)
        
        # Log output/extracted data
        output = status_data.get("output")
        if output:
            output_event = {
                'trace_id': self.trace_id,
                'run_id': self.run_id,
                'lane': self.lane,
                'event_type': 'skyvern_output',
                'output': str(output)[:2000],  # Limit size
                'timestamp': datetime.now().isoformat()
            }
            self.telemetry_events.append(output_event)
        
        # Log failure reason if present
        failure_reason = status_data.get("failure_reason")
        if failure_reason:
            failure_event = {
                'trace_id': self.trace_id,
                'run_id': self.run_id,
                'lane': self.lane,
                'event_type': 'skyvern_failure',
                'failure_reason': failure_reason,
                'timestamp': datetime.now().isoformat()
            }
            self.telemetry_events.append(failure_event)
            print(f"❌ Failure reason: {failure_reason}")
        
        # Store raw response for debugging
        self._last_status_data = status_data
    
    def _print_summary(self, result: Dict[str, Any], elapsed: float) -> None:
        """Print a summary of the Skyvern task execution."""
        print()
        print("-" * 50)
        print(f"Agent completed in {elapsed:.2f} seconds")
        print(f"Total steps logged: {result['steps']}")
        
        # Show status
        status = "✅ SUCCESS" if result.get("success") else "❌ FAILED/TIMEOUT"
        print(f"Status: {status}")
        
        # Show result message
        msg = str(result.get('message', ''))
        if msg:
            if len(msg) > 200:
                print(f"Result: {msg[:200]}...")
            else:
                print(f"Result: {msg}")
        
        # Show where to view details
        if self._task_id:
            print()
            print(f"🔗 View full details: https://app.skyvern.com/tasks/{self._task_id}")
        
        print("-" * 50)
    
    @classmethod
    def get_task_status(cls, task_id: str, api_key: Optional[str] = None) -> Dict[str, Any]:
        """
        Check the status of any Skyvern task by ID.
        
        This is a class method so you can check on tasks without creating an agent instance.
        
        Args:
            task_id: The Skyvern task/run ID (e.g., "tsk_v2_...")
            api_key: Optional API key (defaults to SKYVERN_API_KEY env var)
            
        Returns:
            Full status data from Skyvern API
        """
        key = api_key or os.getenv("SKYVERN_API_KEY")
        if not key:
            raise ValueError("SKYVERN_API_KEY not found")
        
        headers = {
            "x-api-key": key,
            "Content-Type": "application/json"
        }
        
        response = requests.get(
            f"{cls.BASE_URL}/runs/{task_id}",
            headers=headers
        )
        response.raise_for_status()
        return response.json()
    
    async def submit_task(self, start_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Submit a task to Skyvern and return immediately (fire-and-forget).
        
        Use this when you don't want to wait for completion. You can check
        status later with get_task_status() or await_completion().
        
        Args:
            start_url: Optional URL to start at
            
        Returns:
            Dict with task_id and watch_url
        """
        if not self._api_key:
            raise ValueError("SKYVERN_API_KEY not found in environment variables")
        
        payload = {
            "prompt": self.goal,
            "engine": "skyvern-2.0"
        }
        if start_url:
            payload["url"] = start_url
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.BASE_URL}/run/tasks",
                headers=self._get_headers(),
                json=payload
            ) as response:
                response.raise_for_status()
                data = await response.json()
                self._task_id = data.get("run_id") or data.get("task_id") or data.get("id")
        
        task_url = f"https://app.skyvern.com/tasks/{self._task_id}"
        self.log_artifact("skyvern_task", task_url)
        
        print(f"🚀 Task submitted: {self._task_id}")
        print(f"🔗 Watch at: {task_url}")
        print(f"💡 Check status with: SkyvernTelemetricAgent.get_task_status('{self._task_id}')")
        
        return {
            "task_id": self._task_id,
            "watch_url": task_url,
            "status": "submitted"
        }
    
    async def await_completion(
        self,
        task_id: Optional[str] = None,
        poll_interval: float = 5.0,
        timeout: float = DEFAULT_TIMEOUT
    ) -> Dict[str, Any]:
        """
        Wait for a previously submitted task to complete.
        
        Args:
            task_id: Task ID to wait for (defaults to self._task_id)
            poll_interval: Seconds between polls
            timeout: Max seconds to wait
            
        Returns:
            Final result dict
        """
        task_id = task_id or self._task_id
        if not task_id:
            raise ValueError("No task_id provided or submitted")
        
        start_time = datetime.now()
        result = {"success": False, "message": "", "steps": 0}
        
        async with aiohttp.ClientSession() as session:
            while (datetime.now() - start_time).total_seconds() < timeout:
                async with session.get(
                    f"{self.BASE_URL}/runs/{task_id}",
                    headers=self._get_headers()
                ) as response:
                    response.raise_for_status()
                    status_data = await response.json()
                
                run_status = status_data.get("status", "unknown")
                print(f"Status: {run_status}", end="\r")
                
                if run_status.lower() in ["completed", "done", "success", "finished"]:
                    result["success"] = True
                    result["message"] = status_data.get("output") or "Task completed"
                    self._capture_skyvern_telemetry(status_data)
                    break
                
                if run_status.lower() in ["failed", "error", "cancelled", "timeout", "terminated"]:
                    result["message"] = status_data.get("failure_reason") or f"Task {run_status}"
                    self._capture_skyvern_telemetry(status_data)
                    break
                
                await asyncio.sleep(poll_interval)
            else:
                result["message"] = f"Timeout after {timeout} seconds"
        
        print()  # Clear the \r line
        return result
    
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
            # Create task via POST /v1/run/tasks
            # Ref: https://www.skyvern.com/docs/api-reference/api-reference/agent/run-task
            payload = {
                "prompt": self.goal,
                "engine": "skyvern-2.0"
            }
            
            if start_url:
                payload["url"] = start_url
            
            response = requests.post(
                f"{self.BASE_URL}/run/tasks",
                headers=self._get_headers(),
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            
            # Extract run_id from response (starts with "tsk_" for task runs)
            self._task_id = data.get("run_id") or data.get("task_id") or data.get("id")
            if not self._task_id:
                raise ValueError(f"No run_id in response: {data}")
            
            print(f"Skyvern Task ID: {self._task_id}")
            
            # Log Skyvern task as artifact
            task_url = f"https://app.skyvern.com/tasks/{self._task_id}"
            self.log_artifact("skyvern_task", task_url)
            
            # Polling loop
            elapsed = 0.0
            last_status = None
            
            while elapsed < timeout:
                # Get current status via GET /v1/runs/:run_id
                # Ref: https://www.skyvern.com/docs/api-reference/api-reference/agent/get-run
                status_response = requests.get(
                    f"{self.BASE_URL}/runs/{self._task_id}",
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
                
                # Process any new steps
                self._process_new_steps(steps)
                
                # Check if completed
                if run_status.lower() in ["completed", "done", "success", "finished"]:
                    result["success"] = True
                    result["message"] = status_data.get("output") or status_data.get("extracted_information") or "Task completed"
                    result["steps"] = self._logged_step_count
                    self._capture_skyvern_telemetry(status_data)
                    break
                
                # Check if failed
                if run_status.lower() in ["failed", "error", "cancelled", "timeout", "terminated"]:
                    result["message"] = status_data.get("failure_reason") or f"Task {run_status}"
                    result["steps"] = self._logged_step_count
                    self._capture_skyvern_telemetry(status_data)
                    break
                
                # Wait before next poll
                time.sleep(poll_interval)
                elapsed = (datetime.now() - start_time).total_seconds()
            
            else:
                # Timeout - do one final fetch to get latest state
                try:
                    status_response = requests.get(
                        f"{self.BASE_URL}/runs/{self._task_id}",
                        headers=self._get_headers()
                    )
                    if status_response.status_code == 200:
                        status_data = status_response.json()
                        self._capture_skyvern_telemetry(status_data)
                except Exception:
                    pass
                
                result["message"] = f"Timeout after {timeout} seconds (task may still be running on Skyvern)"
                result["steps"] = self._logged_step_count
            
            elapsed = (datetime.now() - start_time).total_seconds()
            self._print_summary(result, elapsed)
            
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
        poll_interval: float = 5.0,
        timeout: Optional[float] = None,
        wait: bool = True
    ) -> Dict[str, Any]:
        """
        Async version of run() using aiohttp.
        
        Args:
            start_url: Optional URL to start at
            poll_interval: Seconds between status polls (default: 5.0)
            timeout: Maximum seconds to wait (default: 15 minutes for cloud tasks)
            wait: If False, submit task and return immediately (fire-and-forget)
            
        Returns:
            Dictionary with run results and telemetry
        """
        if not self._api_key:
            raise ValueError("SKYVERN_API_KEY not found in environment variables")
        
        # Use default timeout for cloud tasks (15 minutes)
        if timeout is None:
            timeout = self.DEFAULT_TIMEOUT
        
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
                # Create task via POST /v1/run/tasks
                payload = {
                    "prompt": self.goal,
                    "engine": "skyvern-2.0"
                }
                if start_url:
                    payload["url"] = start_url
                
                async with session.post(
                    f"{self.BASE_URL}/run/tasks",
                    headers=self._get_headers(),
                    json=payload
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    self._task_id = data.get("run_id") or data.get("task_id") or data.get("id")
                
                print(f"Skyvern Task ID: {self._task_id}")
                
                # Log task as artifact
                task_url = f"https://app.skyvern.com/tasks/{self._task_id}"
                self.log_artifact("skyvern_task", task_url)
                
                print()
                print("=" * 50)
                print("🎬 SKYVERN CLOUD TASK")
                print("=" * 50)
                print(f"Watch live: {task_url}")
                print("(Skyvern runs in the cloud, not locally)")
                print("=" * 50)
                print()
                
                # Fire-and-forget mode: return immediately without waiting
                if not wait:
                    print("🚀 Task submitted! (wait=False, not polling for completion)")
                    print(f"💡 Check status later with: SkyvernTelemetricAgent.get_task_status('{self._task_id}')")
                    return {
                        "success": True,
                        "message": "Task submitted (fire-and-forget mode)",
                        "steps": 0,
                        "task_id": self._task_id,
                        "watch_url": task_url
                    }
                
                print(f"⏳ Waiting for completion (timeout: {int(timeout)}s)...")
                print()
                
                # Polling loop
                elapsed = 0.0
                last_status = None
                poll_count = 0
                
                while elapsed < timeout:
                    # Get current status via GET /v1/runs/:run_id
                    async with session.get(
                        f"{self.BASE_URL}/runs/{self._task_id}",
                        headers=self._get_headers()
                    ) as response:
                        response.raise_for_status()
                        status_data = await response.json()
                    
                    run_status = status_data.get("status") or "running"
                    poll_count += 1
                    
                    # Show recording URL if available
                    if poll_count == 1:
                        recording_url = status_data.get("recording_url")
                        app_url = status_data.get("app_url")
                        if recording_url:
                            print(f"📹 Recording: {recording_url}")
                        if app_url:
                            print(f"🔗 App URL: {app_url}")
                    
                    if run_status != last_status:
                        print(f"Status: {run_status}")
                        last_status = run_status
                        
                        # Debug: show what fields are in the response
                        if run_status == "running":
                            print(f"  (polling every {poll_interval}s, timeout in {int(timeout - elapsed)}s)")
                    
                    # Get steps
                    steps = status_data.get("steps") or []
                    self._process_new_steps(steps)
                    
                    # Check completion
                    if run_status.lower() in ["completed", "done", "success", "finished"]:
                        result["success"] = True
                        result["message"] = status_data.get("output") or status_data.get("extracted_information") or "Task completed"
                        result["steps"] = self._logged_step_count
                        
                        # Capture all Skyvern telemetry
                        self._capture_skyvern_telemetry(status_data)
                        break
                    
                    if run_status.lower() in ["failed", "error", "cancelled", "timeout", "terminated"]:
                        result["message"] = status_data.get("failure_reason") or f"Task {run_status}"
                        result["steps"] = self._logged_step_count
                        
                        # Still capture telemetry on failure
                        self._capture_skyvern_telemetry(status_data)
                        break
                    
                    await asyncio.sleep(poll_interval)
                    elapsed = (datetime.now() - start_time).total_seconds()
                
                else:
                    # Timeout - do one final fetch to get latest state
                    async with session.get(
                        f"{self.BASE_URL}/runs/{self._task_id}",
                        headers=self._get_headers()
                    ) as response:
                        if response.status == 200:
                            status_data = await response.json()
                            self._capture_skyvern_telemetry(status_data)
                    
                    result["message"] = f"Timeout after {timeout} seconds (task may still be running on Skyvern)"
                    result["steps"] = self._logged_step_count
            
            elapsed = (datetime.now() - start_time).total_seconds()
            self._print_summary(result, elapsed)
            
        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            result["message"] = f"Error: {e}"
            print(f"Error after {elapsed:.2f} seconds: {e}")
            raise
        
        return result
