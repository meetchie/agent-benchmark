"""
BrowserUse Telemetric Agent - Browser automation agent with Browserbase and telemetry.

This module provides the BrowserUseTelemetricAgent class which wraps browser-use Agent
with Browserbase session recording and telemetry logging via the BaseAgent class.
"""

import os
import asyncio
import re
from datetime import datetime
from typing import Dict, Any, Optional, List

from browser_use import Agent
from browser_use.llm.models import get_llm_by_name
from browserbase import Browserbase
from browserbase._exceptions import RateLimitError

from .base_agent import BaseAgent


# Patterns that indicate the agent failed even if no exception was thrown
FAILURE_PATTERNS = [
    r"Error code: 429",  # Rate limit
    r"insufficient_quota",
    r"Rate limit",
    r"❌ Result failed \d+/\d+ times",
    r"❌ Stopping due to .* consecutive failures",
]


class BrowserUseTelemetricAgent(BaseAgent):
    """
    Browser automation agent using browser-use library with Browserbase.
    
    Wraps browser-use Agent with Browserbase session recording and
    telemetry logging via BaseAgent.
    """
    
    def __init__(self, run_id: str, goal: str, lane: str = "BROWSERUSE"):
        """
        Initialize the BrowserUseTelemetricAgent.
        
        Args:
            run_id: Unique identifier for this run
            goal: The task/goal for the agent to accomplish
            lane: Lane identifier (default: "BROWSERUSE")
        """
        super().__init__(run_id=run_id, goal=goal, lane=lane)
        
        # Browserbase credentials
        self._browserbase_api_key = os.getenv('BROWSERBASE_API_KEY')
        self._browserbase_project_id = os.getenv('BROWSERBASE_PROJECT_ID')
        self._browserbase_org_id = os.getenv('BROWSERBASE_ORG_ID')
    
    async def _create_browserbase_session(self, bb: Browserbase):
        """Create a Browserbase session, handling rate limits."""
        try:
            session = bb.sessions.create(
                project_id=self._browserbase_project_id,
                browser_settings={'record_session': True}
            )
            return session
        except RateLimitError as e:
            if "concurrent sessions limit" not in str(e).lower():
                raise
            
            print("⚠️  Hit concurrent sessions limit. Closing existing sessions...")
            try:
                active_sessions = bb.sessions.list()
                if active_sessions:
                    for active_session in active_sessions:
                        try:
                            bb.sessions.update(
                                id=active_session.id,
                                project_id=self._browserbase_project_id,
                                status='REQUEST_RELEASE'
                            )
                            print(f"  ✅ Closed session: {active_session.id}")
                        except Exception as close_error:
                            print(f"  ⚠️  Could not close session {active_session.id}: {close_error}")
                    await asyncio.sleep(2)
            except Exception as list_error:
                print(f"  ⚠️  Could not list sessions: {list_error}")
            
            print("🔄 Retrying session creation...")
            return bb.sessions.create(
                project_id=self._browserbase_project_id,
                browser_settings={'record_session': True}
            )
    
    async def run(self, start_url: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """
        Run the agent with Browserbase session recording.
        
        Args:
            start_url: Optional URL to navigate to before running (not used by browser-use,
                      as it extracts URLs from the goal)
            **kwargs: Additional arguments (unused)
        
        Returns:
            Dictionary with run results including history and telemetry
        """
        if not self._browserbase_api_key:
            raise ValueError("BROWSERBASE_API_KEY not found in environment variables")
        
        bb = Browserbase(api_key=self._browserbase_api_key)
        session = await self._create_browserbase_session(bb)
        
        self.print_run_header(start_url)
        print(f"Session ID: {session.id}")
        
        # Define hooks
        async def on_step_start(agent):
            """Hook function called at the beginning of each agent step."""
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
            
            self.log_step_start(action_type=action_type, action_data=action_data)
            print(f"[Step {self._current_step_index}] START - Action: {action_type or 'N/A'}")
        
        async def on_step_end(agent):
            """Hook function called at the end of each agent step."""
            observation = None
            try:
                if hasattr(agent.history, 'extracted_content'):
                    extracted = agent.history.extracted_content()
                    if extracted:
                        observation = {'extracted_content': extracted[-1] if isinstance(extracted, list) else extracted}
            except:
                pass
            
            event_dict = self.log_step_end(observation=observation)
            duration_str = f"{event_dict.get('duration_ms', 0):.2f}ms"
            print(f"[Step {self._current_step_index}] END   - Duration: {duration_str}")
        
        # Set up LLM
        llm = get_llm_by_name("openai_gpt-4o")
        
        # Initialize browser-use Agent
        agent = Agent(
            task=self.goal,
            llm=llm,
            browserbase_api_key=self._browserbase_api_key,
            browserbase_project_id=self._browserbase_project_id,
            browserbase_session_id=session.id,
        )
        
        # Run the agent
        history = None
        start_time = datetime.now()
        result = {"success": False, "message": "", "steps": 0, "history": None, "judge_result": None, 
                  "errors_detected": [], "final_extraction": None}
        
        # Capture stdout/stderr to detect failure patterns
        captured_output: List[str] = []
        
        try:
            history = await agent.run(
                on_step_start=on_step_start,
                on_step_end=on_step_end
            )
            
            elapsed = (datetime.now() - start_time).total_seconds()
            result["steps"] = self._current_step_index
            result["history"] = history
            
            # Tentatively mark as success - will be re-evaluated after token check
            result["success"] = True
            result["message"] = "Agent completed successfully"
            
            # Try to extract final content/extraction from history for judge evaluation
            try:
                if history is not None:
                    # Get extracted content for judge to evaluate
                    if hasattr(history, 'extracted_content'):
                        extracted = history.extracted_content()
                        if extracted:
                            result["final_extraction"] = extracted[-1] if isinstance(extracted, list) else extracted
                    
                    # Also try to get final result/output
                    if hasattr(history, 'final_result') and history.final_result:
                        result["final_extraction"] = str(history.final_result)
            except Exception as extract_err:
                print(f"(Could not extract final content: {extract_err})")
            
        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            result["message"] = f"Error: {e}"
            result["errors_detected"].append(str(e))
            raise
        
        # Get token usage from browser-use history
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
        
        # Distribute tokens across step_end events
        self._distribute_tokens(total_input_tokens, total_output_tokens)
        
        # Re-check for failure patterns now that we have token info
        total_tokens = total_input_tokens + total_output_tokens
        additional_errors = self._detect_failure_patterns(total_tokens=total_tokens)
        
        # Merge any new errors found
        for err in additional_errors:
            if err not in result["errors_detected"]:
                result["errors_detected"].append(err)
        
        # Update success status if new errors were found
        if result["errors_detected"] and result["success"]:
            result["success"] = False
            result["message"] = f"Agent completed but encountered errors: {'; '.join(result['errors_detected'])}"
        
        # Log session replay URL as artifact
        # Use the full Browserbase URL format with org and project IDs
        if self._browserbase_org_id and self._browserbase_project_id:
            replay_url = f"https://www.browserbase.com/sessions/{session.id}"
        else:
            # Fallback if org_id not configured
            replay_url = f"https://www.browserbase.com/sessions/{session.id}"
        
        self.log_artifact("session_replay", replay_url)
        print(f"\nSession Replay URL: {replay_url}")
        
        self.print_run_footer(elapsed, result["success"], result["message"])
        
        return result
    
    def _distribute_tokens(self, total_input: int, total_output: int) -> None:
        """Distribute total tokens proportionally across step_end events."""
        step_end_events = [e for e in self.telemetry_events if e.get('event_type') == 'step_end']
        num_steps = len(step_end_events)
        
        if num_steps == 0 or (total_input == 0 and total_output == 0):
            return
        
        tokens_per_step_input = total_input // num_steps
        tokens_per_step_output = total_output // num_steps
        remainder_input = total_input % num_steps
        remainder_output = total_output % num_steps
        
        step_count = 0
        for event in self.telemetry_events:
            if event['event_type'] == 'step_end':
                extra_in = remainder_input if step_count == 0 else 0
                extra_out = remainder_output if step_count == 0 else 0
                
                event['tokens_input'] = tokens_per_step_input + extra_in
                event['tokens_output'] = tokens_per_step_output + extra_out
                
                # Calculate cost ($5/M in, $15/M out)
                input_cost = (event['tokens_input'] / 1_000_000) * 5.00
                output_cost = (event['tokens_output'] / 1_000_000) * 15.00
                event['cost_usd'] = input_cost + output_cost
                
                step_count += 1
    
    def _detect_failure_patterns(self, total_tokens: int = 0) -> List[str]:
        """
        Scan telemetry events for failure patterns that indicate the agent 
        didn't actually succeed even if no exception was thrown.
        
        Args:
            total_tokens: Total tokens used in the run (0 suggests early termination)
        
        Returns:
            List of error descriptions found
        """
        errors = []
        
        # Collect observation hashes from step_end events
        observations = []
        for event in self.telemetry_events:
            if event.get('event_type') == 'step_end':
                obs = event.get('observation_hash')
                if obs:
                    observations.append(obs)
        
        num_steps = len(observations)
        
        # Check 1: If we have 3+ observations and they're ALL identical = stuck
        if num_steps >= 3:
            if len(set(observations)) == 1:
                errors.append(f"Agent stuck: all {num_steps} steps had identical observations")
        
        # Check 2: If the last 3+ observations are identical = stuck in a loop
        if num_steps >= 3:
            last_three = observations[-3:]
            if len(set(last_three)) == 1:
                # Only add if not already caught by check 1
                if len(set(observations)) > 1:
                    errors.append("Agent stuck in loop: last 3 observations were identical")
        
        # Check 3: Very few steps for what should be a complex task
        # Complex goals have multiple numbered steps, so < 10 steps is suspicious
        goal_has_numbered_steps = any(f"{i}." in self.goal for i in range(1, 6))
        if goal_has_numbered_steps and num_steps < 10:
            errors.append(f"Incomplete run: only {num_steps} steps for a multi-step task")
        
        # Check 4: Zero tokens = LLM never responded (rate limited from the start)
        if total_tokens == 0 and num_steps > 0:
            errors.append("Zero tokens recorded: LLM likely rate-limited")
        
        # Check 5: Look for rate limit patterns in any string representation
        event_str = str(self.telemetry_events)
        for pattern in FAILURE_PATTERNS:
            if re.search(pattern, event_str):
                errors.append(f"Detected failure pattern: {pattern}")
                break  # Don't duplicate rate limit errors
        
        return errors


# Backwards compatibility alias
TelemetricAgent = BrowserUseTelemetricAgent
