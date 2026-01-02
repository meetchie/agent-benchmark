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
        
        # Skyvern app URL (correct dashboard link)
        self._app_url: Optional[str] = None
        
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
        
        # Show status - distinguish local timeout from actual failure
        if result.get("success"):
            status = "✅ SUCCESS"
        elif result.get("local_timeout"):
            status = f"⏱️ LOCAL TIMEOUT (Skyvern: {result.get('skyvern_status', 'unknown')})"
        else:
            status = "❌ FAILED"
        print(f"Status: {status}")
        
        # Show result message
        msg = str(result.get('message', ''))
        if msg:
            if len(msg) > 200:
                print(f"Result: {msg[:200]}...")
            else:
                print(f"Result: {msg}")
        
        # Show where to view details
        if self._app_url:
            print()
            print(f"🔗 View full details: {self._app_url}")
        elif self._task_id:
            print()
            print(f"🔗 Task ID: {self._task_id}")
        
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
    
    @classmethod
    def get_run_billing(cls, task_id: str, api_key: Optional[str] = None, verbose: bool = True) -> Dict[str, Any]:
        """
        Get detailed billing information for a Skyvern run.
        
        This fetches the run details and aggregates step counts across all tasks.
        Billing is approximately $0.05 per step.
        Can be called retroactively on completed tasks.
        
        Args:
            task_id: The Skyvern task/run ID (e.g., "tsk_v2_...")
            api_key: Optional API key (defaults to SKYVERN_API_KEY env var)
            verbose: If True, print billing summary to console
            
        Returns:
            Dict with aggregated billing info and per-task/step breakdown
        """
        COST_PER_STEP = 0.05  # Skyvern pricing: ~$0.05 per step
        
        key = api_key or os.getenv("SKYVERN_API_KEY")
        if not key:
            raise ValueError("SKYVERN_API_KEY not found")
        
        headers = {
            "x-api-key": key,
            "Content-Type": "application/json"
        }
        
        # Fetch main run data (using /v1/runs endpoint)
        response = requests.get(
            f"{cls.BASE_URL}/runs/{task_id}",
            headers=headers
        )
        response.raise_for_status()
        run_data = response.json()
        
        # Extract workflow_run_id from app_url (format: https://app.skyvern.com/runs/wr_xxx)
        app_url = run_data.get("app_url", "")
        workflow_run_id = None
        if "/runs/wr_" in app_url:
            # Extract wr_xxx from the URL
            workflow_run_id = app_url.split("/runs/")[-1].split("/")[0]
        
        # Fallback: if task_id is already a workflow_run_id
        if not workflow_run_id and task_id.startswith("wr_"):
            workflow_run_id = task_id
        
        # Fetch all tasks to find ones belonging to this run
        # Use page_size param to get more historical tasks
        tasks_response = requests.get(
            "https://api.skyvern.com/api/v1/tasks",
            headers=headers,
            params={"page_size": 100}
        )
        all_tasks = tasks_response.json() if tasks_response.status_code == 200 else []
        
        # Filter tasks for this workflow run
        run_tasks = []
        if workflow_run_id:
            run_tasks = [t for t in all_tasks if t.get("workflow_run_id") == workflow_run_id]
        
        # Initialize billing structure
        billing = {
            "task_id": task_id,
            "workflow_run_id": workflow_run_id,
            "status": run_data.get("status"),
            "app_url": run_data.get("app_url"),
            "created_at": run_data.get("created_at"),
            "finished_at": run_data.get("finished_at"),
            "total_tasks": len(run_tasks),
            "total_steps": 0,
            "tasks": [],
            "totals": {
                "steps": 0,
                "cost_usd": 0.0,
            }
        }
        
        # Fetch steps for each task
        for task in run_tasks:
            tid = task.get("task_id")
            task_info = {
                "task_id": tid,
                "status": task.get("status"),
                "created_at": task.get("created_at"),
                "steps": [],
                "step_count": 0,
            }
            
            # Fetch steps for this task
            try:
                steps_response = requests.get(
                    f"https://api.skyvern.com/api/v1/tasks/{tid}/steps",
                    headers=headers
                )
                if steps_response.status_code == 200:
                    steps = steps_response.json()
                    if isinstance(steps, list):
                        task_info["step_count"] = len(steps)
                        task_info["steps"] = [
                            {
                                "step_id": s.get("step_id"),
                                "status": s.get("status"),
                                "created_at": s.get("created_at"),
                            }
                            for s in steps
                        ]
            except Exception:
                pass
            
            billing["tasks"].append(task_info)
            billing["total_steps"] += task_info["step_count"]
        
        # Calculate estimated cost
        billing["totals"]["steps"] = billing["total_steps"]
        billing["totals"]["cost_usd"] = billing["total_steps"] * COST_PER_STEP
        
        # Store raw response for debugging
        billing["_raw_run_data"] = run_data
        
        if verbose:
            cls._print_billing_summary(billing)
        
        return billing
    
    @classmethod
    def _print_billing_summary(cls, billing: Dict[str, Any]) -> None:
        """Print a formatted billing summary."""
        print()
        print("=" * 60)
        print("  SKYVERN RUN SUMMARY")
        print("=" * 60)
        print(f"  Run ID:     {billing['task_id']}")
        print(f"  Status:     {billing['status']}")
        
        # Show timing info from raw data
        raw = billing.get("_raw_run_data", {})
        if raw.get("created_at"):
            print(f"  Created:    {raw['created_at']}")
        if raw.get("started_at"):
            print(f"  Started:    {raw['started_at']}")
        if raw.get("finished_at"):
            print(f"  Finished:   {raw['finished_at']}")
        
        # Show task/step breakdown
        total_steps = billing.get("total_steps", 0)
        total_tasks = billing.get("total_tasks", 0)
        totals = billing.get("totals", {})
        
        print()
        print("  BILLING BREAKDOWN")
        print("  " + "-" * 56)
        print(f"  Total tasks:  {total_tasks}")
        print(f"  Total steps:  {total_steps}")
        print(f"  Cost/step:    $0.05")
        print()
        print(f"  💰 ESTIMATED COST: ${totals.get('cost_usd', 0):.2f}")
        
        # Show per-task breakdown
        tasks = billing.get("tasks", [])
        if tasks:
            print()
            print("  PER-TASK BREAKDOWN")
            print("  " + "-" * 56)
            for i, task in enumerate(tasks, 1):
                tid = task.get("task_id", "unknown")[:30]
                status = task.get("status", "?")
                steps = task.get("step_count", 0)
                cost = steps * 0.05
                status_icon = "✓" if status == "completed" else "○" if status == "running" else "✗"
                print(f"  {i:2d}. {status_icon} {tid}...")
                print(f"      {steps} steps | ${cost:.2f} | {status}")
        
        # Show artifacts
        if raw.get("recording_url"):
            print()
            print("  📹 RECORDING")
            url = raw['recording_url']
            print(f"  {url[:80]}...")
        
        screenshots = raw.get("screenshot_urls", [])
        if screenshots:
            print()
            print(f"  📸 SCREENSHOTS: {len(screenshots)} captured")
        
        print()
        if billing.get("app_url"):
            app_url = billing["app_url"]
            if not app_url.endswith("/overview"):
                app_url = f"{app_url}/overview"
            print(f"  🔗 View details: {app_url}")
        print("=" * 60)
    
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
            "engine": "skyvern-2.0",
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
                "engine": "skyvern-2.0",
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
            
            # First poll to get app_url
            status_response = requests.get(
                f"{self.BASE_URL}/runs/{self._task_id}",
                headers=self._get_headers()
            )
            status_response.raise_for_status()
            initial_data = status_response.json()
            
            # Get correct app URL from API response
            app_url = initial_data.get("app_url")
            if app_url:
                if not app_url.endswith("/overview"):
                    app_url = f"{app_url}/overview"
                self._app_url = app_url
                self.log_artifact("skyvern_app_url", app_url)
                print(f"🔗 Watch live: {app_url}")
            
            # Polling loop
            elapsed = 0.0
            last_status = None
            
            while elapsed < timeout:
                # Get current status via GET /v1/runs/:run_id
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
                # Local timeout reached - task is likely still running on Skyvern
                current_status = "unknown"
                try:
                    status_response = requests.get(
                        f"{self.BASE_URL}/runs/{self._task_id}",
                        headers=self._get_headers()
                    )
                    if status_response.status_code == 200:
                        status_data = status_response.json()
                        self._capture_skyvern_telemetry(status_data)
                        current_status = status_data.get("status", "unknown")
                except Exception:
                    pass
                
                # Mark as local timeout, not failure
                result["local_timeout"] = True
                result["skyvern_status"] = current_status
                result["message"] = f"Local polling timeout after {int(timeout)}s - task is still {current_status} on Skyvern"
                result["steps"] = self._logged_step_count
                
                print()
                print("⚠️  LOCAL TIMEOUT - Task continues running on Skyvern!")
                print(f"   Current Skyvern status: {current_status}")
                if self._app_url:
                    print(f"   Check progress at: {self._app_url}")
            
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
                    "engine": "skyvern-2.0",
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
                
                print()
                print("=" * 50)
                print("🎬 SKYVERN CLOUD TASK")
                print("=" * 50)
                print("(Skyvern runs in the cloud, not locally)")
                print("=" * 50)
                print()
                
                # First poll to get the app_url (correct watch URL)
                async with session.get(
                    f"{self.BASE_URL}/runs/{self._task_id}",
                    headers=self._get_headers()
                ) as response:
                    response.raise_for_status()
                    initial_data = await response.json()
                
                # Get the correct app URL from API response
                app_url = initial_data.get("app_url")
                if app_url:
                    # Ensure URL ends with /overview for the correct page
                    if not app_url.endswith("/overview"):
                        app_url = f"{app_url}/overview"
                    self._app_url = app_url
                    self.log_artifact("skyvern_app_url", app_url)
                    print(f"🔗 Watch live: {app_url}")
                else:
                    # Fallback if no app_url provided
                    self._app_url = f"https://app.skyvern.com/tasks/{self._task_id}"
                    print(f"🔗 Task ID: {self._task_id}")
                
                # Fire-and-forget mode: return immediately without waiting
                if not wait:
                    print()
                    print("🚀 Task submitted! (wait=False, not polling for completion)")
                    print(f"💡 Check status later with: SkyvernTelemetricAgent.get_task_status('{self._task_id}')")
                    return {
                        "success": True,
                        "message": "Task submitted (fire-and-forget mode)",
                        "steps": 0,
                        "task_id": self._task_id,
                        "watch_url": self._app_url
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
                    
                    # Show recording URL on first poll
                    if poll_count == 1:
                        recording_url = status_data.get("recording_url")
                        if recording_url:
                            print(f"📹 Recording: {recording_url}")
                    
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
                    # Local timeout reached - task is likely still running on Skyvern
                    async with session.get(
                        f"{self.BASE_URL}/runs/{self._task_id}",
                        headers=self._get_headers()
                    ) as response:
                        if response.status == 200:
                            status_data = await response.json()
                            self._capture_skyvern_telemetry(status_data)
                            current_status = status_data.get("status", "unknown")
                        else:
                            current_status = "unknown"
                    
                    # Mark as local timeout, not failure
                    result["local_timeout"] = True
                    result["skyvern_status"] = current_status
                    result["message"] = f"Local polling timeout after {int(timeout)}s - task is still {current_status} on Skyvern"
                    result["steps"] = self._logged_step_count
                    
                    print()
                    print("⚠️  LOCAL TIMEOUT - Task continues running on Skyvern!")
                    print(f"   Current Skyvern status: {current_status}")
                    if self._app_url:
                        print(f"   Check progress at: {self._app_url}")
            
            elapsed = (datetime.now() - start_time).total_seconds()
            self._print_summary(result, elapsed)
            
        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            result["message"] = f"Error: {e}"
            print(f"Error after {elapsed:.2f} seconds: {e}")
            raise
        
        return result
