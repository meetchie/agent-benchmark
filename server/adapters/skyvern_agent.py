"""
Skyvern Telemetric Agent - Skyvern AI browser automation with polling telemetry.

This module provides the SkyvernTelemetricAgent class which uses Skyvern's
cloud API with polling-based telemetry logging. The agent submits tasks to
Skyvern and polls for status/steps until completion.

Reference: https://github.com/skyvern-ai/skyvern
API Docs: https://www.skyvern.com/docs/api-reference/api-reference/agent/run-task
"""

import os
import asyncio
import aiohttp
import requests
from datetime import datetime
from typing import Dict, Any, Optional, List

from .base_agent import BaseAgent


class SkyvernTelemetricAgent(BaseAgent):
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
    DEFAULT_TIMEOUT = 900.0  # 15 minutes for cloud tasks
    COST_PER_STEP = 0.05  # Skyvern pricing
    
    def __init__(self, run_id: str, goal: str, lane: str = "SKYVERN"):
        """
        Initialize the SkyvernTelemetricAgent.
        
        Args:
            run_id: Unique identifier for this run
            goal: The task/goal for the agent to accomplish
            lane: Lane identifier (default: "SKYVERN")
        """
        super().__init__(run_id=run_id, goal=goal, lane=lane)
        
        self._api_key = os.getenv("SKYVERN_API_KEY")
        self._logged_step_count = 0
        self._task_id: Optional[str] = None
        self._app_url: Optional[str] = None
        self._last_status_data: Optional[Dict[str, Any]] = None
    
    def _get_headers(self) -> Dict[str, str]:
        """Get API request headers."""
        return {
            "x-api-key": self._api_key,
            "Content-Type": "application/json"
        }
    
    def _capture_skyvern_telemetry(self, status_data: Dict[str, Any]) -> None:
        """Capture all available telemetry from Skyvern's API response."""
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
        for i, url in enumerate(screenshot_urls[:5]):
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
        
        # Log output
        output = status_data.get("output")
        if output:
            output_event = {
                'trace_id': self.trace_id,
                'run_id': self.run_id,
                'lane': self.lane,
                'event_type': 'skyvern_output',
                'output': str(output)[:2000],
                'timestamp': datetime.now().isoformat()
            }
            self.telemetry_events.append(output_event)
        
        # Log failure reason
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
        
        self._last_status_data = status_data
    
    def _process_new_steps(self, steps: List[Dict[str, Any]]) -> int:
        """Process any new steps and log them to telemetry."""
        new_steps = 0
        
        for idx, step in enumerate(steps):
            step_index = idx + 1
            
            if step_index <= self._logged_step_count:
                continue
            
            new_steps += 1
            
            step_type = step.get("step_type") or step.get("type") or "action"
            status = step.get("status") or "completed"
            output = step.get("output") or step.get("result") or {}
            actions = step.get("actions") or []
            
            action_type = step_type
            if actions and len(actions) > 0:
                first_action = actions[0]
                action_type = first_action.get("action_type") or step_type
            
            self.log_step(
                action_type=action_type,
                action_data={"step_type": step_type, "actions_count": len(actions)},
                observation={"status": status, "output": str(output)[:500] if output else None}
            )
            
            success_str = "✓" if status in ["completed", "success"] else "○"
            print(f"[Step {step_index}] {success_str} {action_type}")
            
            self._logged_step_count = step_index
        
        return new_steps
    
    def _print_summary(self, result: Dict[str, Any], elapsed: float) -> None:
        """Print a summary of the Skyvern task execution."""
        print()
        print("-" * 50)
        print(f"Agent completed in {elapsed:.2f} seconds")
        print(f"Total steps logged: {result['steps']}")
        
        if result.get("success"):
            status = "✅ SUCCESS"
        elif result.get("local_timeout"):
            status = f"⏱️ LOCAL TIMEOUT (Skyvern: {result.get('skyvern_status', 'unknown')})"
        else:
            status = "❌ FAILED"
        print(f"Status: {status}")
        
        msg = str(result.get('message', ''))
        if msg:
            print(f"Result: {msg[:200]}..." if len(msg) > 200 else f"Result: {msg}")
        
        if self._app_url:
            print()
            print(f"🔗 View full details: {self._app_url}")
        elif self._task_id:
            print()
            print(f"🔗 Task ID: {self._task_id}")
        
        print("-" * 50)
    
    @classmethod
    def get_task_status(cls, task_id: str, api_key: Optional[str] = None) -> Dict[str, Any]:
        """Check the status of any Skyvern task by ID."""
        key = api_key or os.getenv("SKYVERN_API_KEY")
        if not key:
            raise ValueError("SKYVERN_API_KEY not found")
        
        headers = {"x-api-key": key, "Content-Type": "application/json"}
        response = requests.get(f"{cls.BASE_URL}/runs/{task_id}", headers=headers)
        response.raise_for_status()
        return response.json()
    
    @classmethod
    def get_run_billing(cls, task_id: str, api_key: Optional[str] = None, verbose: bool = True) -> Dict[str, Any]:
        """Get detailed billing information for a Skyvern run."""
        key = api_key or os.getenv("SKYVERN_API_KEY")
        if not key:
            raise ValueError("SKYVERN_API_KEY not found")
        
        headers = {"x-api-key": key, "Content-Type": "application/json"}
        
        # Fetch main run data
        response = requests.get(f"{cls.BASE_URL}/runs/{task_id}", headers=headers)
        response.raise_for_status()
        run_data = response.json()
        
        # Extract workflow_run_id from app_url
        app_url = run_data.get("app_url", "")
        workflow_run_id = None
        if "/runs/wr_" in app_url:
            workflow_run_id = app_url.split("/runs/")[-1].split("/")[0]
        
        if not workflow_run_id and task_id.startswith("wr_"):
            workflow_run_id = task_id
        
        # Fetch all tasks
        tasks_response = requests.get(
            "https://api.skyvern.com/api/v1/tasks",
            headers=headers,
            params={"page_size": 100}
        )
        all_tasks = tasks_response.json() if tasks_response.status_code == 200 else []
        
        run_tasks = []
        if workflow_run_id:
            run_tasks = [t for t in all_tasks if t.get("workflow_run_id") == workflow_run_id]
        
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
            "totals": {"steps": 0, "cost_usd": 0.0, "tokens_input": 0, "tokens_output": 0, "tokens_total": 0},
            "steps": [],
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
            
            try:
                steps_response = requests.get(
                    f"https://api.skyvern.com/api/v1/tasks/{tid}/steps",
                    headers=headers
                )
                if steps_response.status_code == 200:
                    steps = steps_response.json()
                    if isinstance(steps, list):
                        task_info["step_count"] = len(steps)
                        for i, s in enumerate(steps):
                            step_info = {
                                "step_index": i + 1,
                                "step_id": s.get("step_id"),
                                "status": s.get("status"),
                                "action_type": s.get("step_type"),
                                "tokens_total": 0,
                                "cost_usd": cls.COST_PER_STEP,
                            }
                            task_info["steps"].append(step_info)
                            billing["steps"].append(step_info)
            except Exception:
                pass
            
            billing["tasks"].append(task_info)
            billing["total_steps"] += task_info["step_count"]
        
        billing["totals"]["steps"] = billing["total_steps"]
        billing["totals"]["cost_usd"] = billing["total_steps"] * cls.COST_PER_STEP
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
        
        raw = billing.get("_raw_run_data", {})
        if raw.get("created_at"):
            print(f"  Created:    {raw['created_at']}")
        if raw.get("started_at"):
            print(f"  Started:    {raw['started_at']}")
        if raw.get("finished_at"):
            print(f"  Finished:   {raw['finished_at']}")
        
        total_steps = billing.get("total_steps", 0)
        total_tasks = billing.get("total_tasks", 0)
        totals = billing.get("totals", {})
        
        print()
        print("  BILLING BREAKDOWN")
        print("  " + "-" * 56)
        print(f"  Total tasks:  {total_tasks}")
        print(f"  Total steps:  {total_steps}")
        print(f"  Cost/step:    ${cls.COST_PER_STEP}")
        print()
        print(f"  💰 ESTIMATED COST: ${totals.get('cost_usd', 0):.2f}")
        
        tasks = billing.get("tasks", [])
        if tasks:
            print()
            print("  PER-TASK BREAKDOWN")
            print("  " + "-" * 56)
            for i, task in enumerate(tasks, 1):
                tid = task.get("task_id", "unknown")[:30]
                status = task.get("status", "?")
                steps = task.get("step_count", 0)
                cost = steps * cls.COST_PER_STEP
                status_icon = "✓" if status == "completed" else "○" if status == "running" else "✗"
                print(f"  {i:2d}. {status_icon} {tid}...")
                print(f"      {steps} steps | ${cost:.2f} | {status}")
        
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
    
    async def run(
        self,
        start_url: Optional[str] = None,
        poll_interval: float = 5.0,
        timeout: Optional[float] = None,
        wait: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run the Skyvern agent.
        
        Args:
            start_url: Optional URL to start at
            poll_interval: Seconds between status polls (default: 5.0)
            timeout: Maximum seconds to wait (default: 15 minutes)
            wait: If False, submit task and return immediately (fire-and-forget)
            **kwargs: Additional arguments (unused)
            
        Returns:
            Dictionary with run results and telemetry
        """
        if not self._api_key:
            raise ValueError("SKYVERN_API_KEY not found in environment variables")
        
        if timeout is None:
            timeout = self.DEFAULT_TIMEOUT
        
        self.print_run_header(start_url)
        
        start_time = datetime.now()
        result = {"success": False, "message": "", "steps": 0}
        
        try:
            async with aiohttp.ClientSession() as session:
                # Create task
                payload = {"prompt": self.goal, "engine": "skyvern-2.0"}
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
                
                # First poll to get app_url
                async with session.get(
                    f"{self.BASE_URL}/runs/{self._task_id}",
                    headers=self._get_headers()
                ) as response:
                    response.raise_for_status()
                    initial_data = await response.json()
                
                app_url = initial_data.get("app_url")
                if app_url:
                    if not app_url.endswith("/overview"):
                        app_url = f"{app_url}/overview"
                    self._app_url = app_url
                    self.log_artifact("skyvern_app_url", app_url)
                    print(f"🔗 Watch live: {app_url}")
                else:
                    self._app_url = f"https://app.skyvern.com/tasks/{self._task_id}"
                
                # Fire-and-forget mode
                if not wait:
                    print()
                    print("🚀 Task submitted! (wait=False)")
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
                
                while elapsed < timeout:
                    async with session.get(
                        f"{self.BASE_URL}/runs/{self._task_id}",
                        headers=self._get_headers()
                    ) as response:
                        response.raise_for_status()
                        status_data = await response.json()
                    
                    run_status = status_data.get("status") or "running"
                    
                    if run_status != last_status:
                        print(f"Status: {run_status}")
                        last_status = run_status
                        if run_status == "running":
                            print(f"  (polling every {poll_interval}s, timeout in {int(timeout - elapsed)}s)")
                    
                    steps = status_data.get("steps") or []
                    self._process_new_steps(steps)
                    
                    if run_status.lower() in ["completed", "done", "success", "finished"]:
                        result["success"] = True
                        result["message"] = status_data.get("output") or status_data.get("extracted_information") or "Task completed"
                        result["steps"] = self._logged_step_count
                        self._capture_skyvern_telemetry(status_data)
                        break
                    
                    if run_status.lower() in ["failed", "error", "cancelled", "timeout", "terminated"]:
                        result["message"] = status_data.get("failure_reason") or f"Task {run_status}"
                        result["steps"] = self._logged_step_count
                        self._capture_skyvern_telemetry(status_data)
                        break
                    
                    await asyncio.sleep(poll_interval)
                    elapsed = (datetime.now() - start_time).total_seconds()
                
                else:
                    # Local timeout
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
                    
                    result["local_timeout"] = True
                    result["skyvern_status"] = current_status
                    result["message"] = f"Local polling timeout after {int(timeout)}s - task is still {current_status} on Skyvern"
                    result["steps"] = self._logged_step_count
                    
                    print()
                    print("⚠️  LOCAL TIMEOUT - Task continues running on Skyvern!")
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
    
