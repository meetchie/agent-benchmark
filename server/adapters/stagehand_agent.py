"""
Stagehand Telemetric Agent - Browserbase Stagehand AI browser automation with telemetry.

This module provides the StagehandTelemetricAgent class which uses Stagehand's
AI browser automation framework with Browserbase for cloud browser sessions.

Stagehand provides three core primitives:
- act(): Perform actions on the page using natural language
- extract(): Extract structured data from the page
- observe(): Get information about interactive elements

Reference: https://github.com/browserbase/stagehand
Docs: https://docs.stagehand.dev/
"""

import os
import uuid
import asyncio
import subprocess
import json
from datetime import datetime
from typing import Dict, Any, Optional, List

import sys
# Add project root to path for telemetric_logger import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from telemetric_logger import TelemetricWrapper, TelemetryEvent


class StagehandTelemetricAgent:
    """
    Browser automation agent using Stagehand with Browserbase.
    
    Stagehand is a TypeScript/JavaScript library, so this adapter runs it
    via a Node.js subprocess that executes Stagehand commands and reports
    telemetry back. This allows Python orchestration of the JS-based agent.
    
    For full native integration, consider using the JavaScript SDK directly.
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
        self._openai_api_key = os.getenv("OPENAI_API_KEY")
        
        # Step tracking
        self._current_step_index = 0
        
        # Session ID for Browserbase replay
        self._session_id: Optional[str] = None
    
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
    
    def _generate_stagehand_script(self, start_url: str) -> str:
        """
        Generate a Node.js script that runs Stagehand with the goal.
        
        This creates a temporary script that:
        1. Initializes Stagehand with Browserbase
        2. Uses the agent() method for autonomous task completion
        3. Outputs telemetry as JSON lines
        """
        # Escape the goal for JavaScript string
        escaped_goal = self.goal.replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$')
        
        script = f"""
const {{ Stagehand }} = require("@browserbasehq/stagehand");

async function main() {{
    const stagehand = new Stagehand({{
        env: "BROWSERBASE",
        apiKey: process.env.BROWSERBASE_API_KEY,
        projectId: process.env.BROWSERBASE_PROJECT_ID,
        modelName: "gpt-4o",
        modelClientOptions: {{
            apiKey: process.env.OPENAI_API_KEY,
        }},
        enableCaching: false,
        verbose: 1,
    }});

    try {{
        await stagehand.init();
        
        // Output session ID for replay URL
        const sessionId = stagehand.browserbaseSessionID;
        console.log(JSON.stringify({{ type: "session", sessionId }}));
        
        // Navigate to start URL
        await stagehand.page.goto("{start_url}");
        console.log(JSON.stringify({{ type: "step", action: "navigate", url: "{start_url}", success: true }}));
        
        // Use the agent() method for autonomous task completion
        const result = await stagehand.agent({{
            instruction: `{escaped_goal}`,
            maxSteps: 30,
            onStep: (step) => {{
                console.log(JSON.stringify({{
                    type: "step",
                    action: step.action || "agent_step",
                    thought: step.thought || "",
                    result: step.result || "",
                    success: step.success !== false,
                    tokensUsed: step.tokensUsed || null
                }}));
            }}
        }});
        
        console.log(JSON.stringify({{
            type: "complete",
            success: true,
            result: result?.message || "Task completed"
        }}));
        
    }} catch (error) {{
        console.log(JSON.stringify({{
            type: "error",
            message: error.message,
            success: false
        }}));
    }} finally {{
        await stagehand.close();
    }}
}}

main();
"""
        return script
    
    def _run_stagehand_subprocess(self, start_url: str, timeout: float) -> Dict[str, Any]:
        """
        Run Stagehand via Node.js subprocess.
        
        Args:
            start_url: URL to start at
            timeout: Maximum seconds to wait
            
        Returns:
            Dictionary with results
        """
        import tempfile
        
        result = {"success": False, "message": "", "steps": 0}
        
        # Generate script
        script = self._generate_stagehand_script(start_url)
        
        # Write to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
            f.write(script)
            script_path = f.name
        
        try:
            # Set up environment
            env = os.environ.copy()
            env["BROWSERBASE_API_KEY"] = self._browserbase_api_key or ""
            env["BROWSERBASE_PROJECT_ID"] = self._browserbase_project_id or ""
            env["OPENAI_API_KEY"] = self._openai_api_key or ""
            
            # Run the script
            process = subprocess.Popen(
                ["node", script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                result["message"] = f"Timeout after {timeout} seconds"
                return result
            
            # Parse output lines
            for line in stdout.strip().split('\n'):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    
                    if data.get("type") == "session":
                        self._session_id = data.get("sessionId")
                        if self._session_id:
                            replay_url = f"https://www.browserbase.com/sessions/{self._session_id}/replay"
                            self.log_artifact("session_replay", replay_url)
                            print(f"Session ID: {self._session_id}")
                    
                    elif data.get("type") == "step":
                        action = data.get("action", "unknown")
                        thought = data.get("thought", "")
                        step_result = data.get("result", "")
                        success = data.get("success", True)
                        tokens = data.get("tokensUsed") or {}
                        
                        self._log_step(
                            action_type=action,
                            action_data={"thought": thought[:200] if thought else None},
                            observation={"result": step_result[:200] if step_result else None, "success": success},
                            tokens_input=tokens.get("input"),
                            tokens_output=tokens.get("output")
                        )
                    
                    elif data.get("type") == "complete":
                        result["success"] = data.get("success", True)
                        result["message"] = data.get("result", "Task completed")
                    
                    elif data.get("type") == "error":
                        result["message"] = data.get("message", "Unknown error")
                        result["success"] = False
                        
                except json.JSONDecodeError:
                    # Non-JSON output, might be verbose logging
                    pass
            
            result["steps"] = self._current_step_index
            
            if stderr and not result["message"]:
                result["message"] = f"stderr: {stderr[:200]}"
                
        finally:
            # Clean up temp file
            try:
                os.unlink(script_path)
            except Exception:
                pass
        
        return result
    
    def run(
        self,
        start_url: Optional[str] = None,
        timeout: float = 300.0
    ) -> Dict[str, Any]:
        """
        Run the Stagehand agent.
        
        Args:
            start_url: URL to start at
            timeout: Maximum seconds to wait for completion (default: 300.0)
            
        Returns:
            Dictionary with run results and telemetry
        """
        if not self._browserbase_api_key:
            raise ValueError("BROWSERBASE_API_KEY not found in environment variables")
        if not self._openai_api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        print(f"Starting Stagehand agent run...")
        print(f"Trace ID: {self.trace_id}")
        print(f"Run ID: {self.run_id}")
        print(f"Lane: {self.lane}")
        print(f"Goal: {self.goal}")
        print("-" * 50)
        
        start_time = datetime.now()
        
        url = start_url or "https://www.google.com"
        result = self._run_stagehand_subprocess(url, timeout)
        
        elapsed = (datetime.now() - start_time).total_seconds()
        print("-" * 50)
        print(f"Agent completed in {elapsed:.2f} seconds")
        print(f"Total steps: {result['steps']}")
        print(f"Success: {result['success']}")
        print(f"Result: {result['message'][:100]}..." if len(str(result['message'])) > 100 else f"Result: {result['message']}")
        
        return result
    
    async def arun(
        self,
        start_url: Optional[str] = None,
        timeout: float = 300.0
    ) -> Dict[str, Any]:
        """
        Async wrapper for run() method.
        
        Args:
            start_url: URL to start at
            timeout: Maximum seconds to wait for completion (default: 300.0)
            
        Returns:
            Dictionary with run results and telemetry
        """
        # Run synchronous code in executor
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.run(start_url, timeout))

