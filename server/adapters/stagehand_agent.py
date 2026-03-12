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
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List

from .base_agent import BaseAgent


class StagehandTelemetricAgent(BaseAgent):
    """
    Browser automation agent using Stagehand Python SDK with Browserbase.
    
    Uses the native Python SDK for Stagehand for AI-driven browser automation.
    """
    
    def __init__(self, run_id: str, goal: str, lane: str = "STAGEHAND"):
        """
        Initialize the StagehandTelemetricAgent.
        
        Args:
            run_id: Unique identifier for this run
            goal: The task/goal for the agent to accomplish
            lane: Lane identifier (default: "STAGEHAND")
        """
        super().__init__(run_id=run_id, goal=goal, lane=lane)
        
        # API keys from environment
        self._browserbase_api_key = os.getenv("BROWSERBASE_API_KEY")
        self._browserbase_project_id = os.getenv("BROWSERBASE_PROJECT_ID")
        self._browserbase_org_id = os.getenv("BROWSERBASE_ORG_ID")
        self._model_api_key = os.getenv("OPENAI_API_KEY")
        
        # Session ID for Browserbase replay
        self._session_id: Optional[str] = None
        
        # Stagehand instance
        self._stagehand = None
    
    def _parse_goal_into_steps(self, goal: str) -> List[str]:
        """
        Parse a complex goal into individual action steps.
        
        This is a simple heuristic parser. For complex goals,
        consider using the agent() method instead.
        """
        steps = []
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
        
        return steps if steps else [goal]
    
    async def run(
        self,
        start_url: Optional[str] = None,
        timeout: float = 300.0,
        max_steps: int = 30,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run the Stagehand agent asynchronously.
        
        Args:
            start_url: URL to start at
            timeout: Maximum seconds to wait for completion (default: 300.0)
            max_steps: Maximum number of agent steps (default: 30)
            **kwargs: Additional arguments (unused)
            
        Returns:
            Dictionary with run results and telemetry
        """
        from stagehand import Stagehand
        
        if not self._browserbase_api_key:
            raise ValueError("BROWSERBASE_API_KEY not found in environment variables")
        if not self._model_api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        self.print_run_header(start_url)
        
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
                if self._browserbase_org_id and self._browserbase_project_id:
                    session_url = f"https://www.browserbase.com/sessions/{self._session_id}"
                else:
                    session_url = f"https://www.browserbase.com/sessions/{self._session_id}"
                
                self.log_artifact("session_replay", session_url)
                print(f"Session ID: {self._session_id}")
                print(f"Session URL: {session_url}")
            
            page = self._stagehand.page
            
            # Navigate to start URL if provided
            if start_url:
                await page.goto(start_url)
                self.log_step(
                    action_type="navigate",
                    action_data={"url": start_url},
                    observation={"success": True, "url": start_url}
                )
                print(f"Navigated to: {start_url}")
            
            await asyncio.sleep(2)
            
            # Execute steps
            steps_taken = 0
            goal_parts = self._parse_goal_into_steps(self.goal)
            
            for step_instruction in goal_parts:
                if steps_taken >= max_steps:
                    result["message"] = f"Max steps ({max_steps}) reached"
                    break
                
                try:
                    print(f"\n--- Executing: {step_instruction[:100]}...")
                    
                    act_result = await page.act(step_instruction)
                    steps_taken += 1
                    
                    self.log_step(
                        action_type="act",
                        action_data={"instruction": step_instruction[:200]},
                        observation={"success": True, "result": str(act_result)[:200] if act_result else "completed"}
                    )
                    
                    await asyncio.sleep(1)
                    
                except Exception as step_error:
                    print(f"Step failed: {step_error}")
                    self.log_step(
                        action_type="act",
                        action_data={"instruction": step_instruction[:200]},
                        observation={"success": False, "error": str(step_error)[:200]}
                    )
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
            if self._stagehand:
                try:
                    await self._stagehand.close()
                except Exception:
                    pass
        
        elapsed = (datetime.now() - start_time).total_seconds()
        result["steps"] = self._current_step_index
        
        self.print_run_footer(elapsed, result["success"], result["message"])
        
        return result
    
