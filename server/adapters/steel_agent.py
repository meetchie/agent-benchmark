"""
Steel Telemetric Agent - Manual Playwright on Steel with LangChain orchestration.

This module provides the SteelTelemetricAgent class which uses Steel SDK for
browser sessions and LangChain's ChatOpenAI to drive Playwright interactions,
with telemetry logging via TelemetricWrapper.
"""

import os
import uuid
import asyncio
import json
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable

from playwright.async_api import async_playwright, Page, Browser
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.callbacks import BaseCallbackHandler

import sys
# Add project root to path for telemetric_logger import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from telemetric_logger import TelemetricWrapper, TelemetryEvent


class TelemetryCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler for telemetry logging."""
    
    def __init__(self, agent: "SteelTelemetricAgent"):
        self.agent = agent
        self._current_step_start_time: Optional[datetime] = None
        self._current_tokens_input: int = 0
        self._current_tokens_output: int = 0
    
    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs) -> None:
        """Called when LLM starts processing."""
        self._current_step_start_time = datetime.now()
        self.agent._current_step_index += 1
        
        event = self.agent.telemetry.log_step_start(
            step_index=self.agent._current_step_index,
            action_type="llm_call",
            action_data={"prompts": prompts[:1] if prompts else None}  # Truncate for hash
        )
        self.agent.telemetry_events.append(self.agent._convert_event_to_dict(event))
        print(f"[Step {self.agent._current_step_index}] START - LLM Call")
    
    def on_llm_end(self, response, **kwargs) -> None:
        """Called when LLM finishes processing."""
        # Extract token usage from response
        tokens_input = None
        tokens_output = None
        
        try:
            if hasattr(response, 'llm_output') and response.llm_output:
                token_usage = response.llm_output.get('token_usage', {})
                tokens_input = token_usage.get('prompt_tokens')
                tokens_output = token_usage.get('completion_tokens')
        except Exception:
            pass
        
        # Extract response text for observation
        observation = None
        try:
            if response.generations and response.generations[0]:
                gen = response.generations[0][0]
                observation = {"response": gen.text[:500] if hasattr(gen, 'text') else str(gen)[:500]}
        except Exception:
            pass
        
        event = self.agent.telemetry.log_step_end(
            step_index=self.agent._current_step_index,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            observation=observation
        )
        
        event_dict = self.agent._convert_event_to_dict(event)
        self.agent.telemetry_events.append(event_dict)
        
        duration_str = f"{event.duration_ms:.2f}ms" if event.duration_ms else "N/A"
        print(f"[Step {self.agent._current_step_index}] END   - Duration: {duration_str}, Tokens: {tokens_input or 0}/{tokens_output or 0}")


class SteelTelemetricAgent:
    """
    Browser automation agent using Steel SDK with LangChain orchestration.
    
    Uses Steel for cloud browser sessions, Playwright for browser control,
    and LangChain ChatOpenAI for intelligent navigation decisions.
    """
    
    SYSTEM_PROMPT = """You are a browser automation assistant. You are given a goal and the current state of a webpage.
Your job is to decide what action to take next to accomplish the goal.

Available actions:
- click(selector): Click on an element matching the CSS selector
- type(selector, text): Type text into an element
- goto(url): Navigate to a URL
- scroll(direction): Scroll the page ("up" or "down")
- wait(seconds): Wait for a specified number of seconds
- done(result): Indicate the task is complete with a result message

Respond with a JSON object containing:
- "thought": Your reasoning about what to do next
- "action": The action name
- "params": Object with action parameters

Example response:
{"thought": "I need to search for the product", "action": "type", "params": {"selector": "input[type='search']", "text": "laptop"}}
{"thought": "Task is complete", "action": "done", "params": {"result": "Successfully found the product"}}
"""

    def __init__(self, run_id: str, goal: str, lane: str = "STEEL"):
        """
        Initialize the SteelTelemetricAgent.
        
        Args:
            run_id: Unique identifier for this run
            goal: The task/goal for the agent to accomplish
            lane: Lane identifier (default: "STEEL")
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
        
        # Browser components (initialized in run)
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self._session = None
        
        # LangChain LLM with callback
        self._callback_handler = TelemetryCallbackHandler(self)
        self._llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0,
            callbacks=[self._callback_handler]
        )
        
        # Conversation history for context
        self._messages: List = []
    
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
        """Log an artifact event (e.g., session URL)."""
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
    
    async def _get_page_state(self) -> str:
        """Get current page state for LLM context."""
        if not self._page:
            return "No page loaded"
        
        try:
            url = self._page.url
            title = await self._page.title()
            
            # Get visible text content (truncated)
            body_text = await self._page.evaluate("""
                () => {
                    const body = document.body;
                    return body ? body.innerText.substring(0, 3000) : '';
                }
            """)
            
            # Get interactive elements
            interactive = await self._page.evaluate("""
                () => {
                    const elements = [];
                    document.querySelectorAll('a, button, input, select, textarea, [onclick], [role="button"]').forEach((el, i) => {
                        if (i < 30) {
                            const tag = el.tagName.toLowerCase();
                            const text = (el.innerText || el.value || el.placeholder || '').substring(0, 50);
                            const id = el.id ? `#${el.id}` : '';
                            const cls = el.className ? `.${el.className.split(' ')[0]}` : '';
                            elements.push(`${tag}${id}${cls}: "${text}"`);
                        }
                    });
                    return elements.join('\\n');
                }
            """)
            
            return f"""URL: {url}
Title: {title}

Page Content (truncated):
{body_text[:2000]}

Interactive Elements:
{interactive}"""
        except Exception as e:
            return f"Error getting page state: {e}"
    
    async def _execute_action(self, action: str, params: Dict[str, Any]) -> str:
        """Execute a browser action and return the result."""
        if not self._page:
            return "Error: No page available"
        
        try:
            if action == "click":
                selector = params.get("selector", "")
                await self._page.click(selector, timeout=10000)
                await self._page.wait_for_load_state("domcontentloaded")
                return f"Clicked on {selector}"
            
            elif action == "type":
                selector = params.get("selector", "")
                text = params.get("text", "")
                await self._page.fill(selector, text)
                return f"Typed '{text}' into {selector}"
            
            elif action == "goto":
                url = params.get("url", "")
                await self._page.goto(url, wait_until="domcontentloaded")
                return f"Navigated to {url}"
            
            elif action == "scroll":
                direction = params.get("direction", "down")
                delta = -500 if direction == "up" else 500
                await self._page.mouse.wheel(0, delta)
                return f"Scrolled {direction}"
            
            elif action == "wait":
                seconds = params.get("seconds", 1)
                await asyncio.sleep(seconds)
                return f"Waited {seconds} seconds"
            
            elif action == "done":
                result = params.get("result", "Task completed")
                return f"DONE: {result}"
            
            else:
                return f"Unknown action: {action}"
        
        except Exception as e:
            return f"Action failed: {e}"
    
    async def run(self, max_steps: int = 20, start_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Run the agent with Steel browser session.
        
        Args:
            max_steps: Maximum number of steps before stopping
            start_url: Optional URL to start at
            
        Returns:
            Dictionary with run results and telemetry
        """
        from steel import Steel
        
        steel_api_key = os.getenv("STEEL_API_KEY")
        if not steel_api_key:
            raise ValueError("STEEL_API_KEY not found in environment variables")
        
        # Initialize Steel client
        client = Steel(steel_api_key=steel_api_key)
        
        print(f"Starting Steel agent run...")
        print(f"Trace ID: {self.trace_id}")
        print(f"Run ID: {self.run_id}")
        print(f"Lane: {self.lane}")
        print(f"Goal: {self.goal}")
        print("-" * 50)
        
        start_time = datetime.now()
        result = {"success": False, "message": "", "steps": 0}
        
        try:
            # Create Steel session
            self._session = client.sessions.create()
            session_id = self._session.id
            websocket_url = self._session.websocket_url
            
            print(f"Steel Session ID: {session_id}")
            
            # Log session as artifact
            session_url = f"https://app.steel.dev/sessions/{session_id}"
            self.log_artifact("steel_session", session_url)
            
            # Connect Playwright via CDP
            async with async_playwright() as p:
                self._browser = await p.chromium.connect_over_cdp(websocket_url)
                
                # Get default context and page
                context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
                self._page = context.pages[0] if context.pages else await context.new_page()
                
                # Navigate to start URL if provided
                if start_url:
                    await self._page.goto(start_url, wait_until="domcontentloaded")
                
                # Initialize conversation
                self._messages = [
                    SystemMessage(content=self.SYSTEM_PROMPT),
                    HumanMessage(content=f"Goal: {self.goal}\n\nCurrent page state:\n{await self._get_page_state()}")
                ]
                
                # Main agent loop
                for step in range(max_steps):
                    # Get LLM decision (telemetry logged via callback)
                    response = await self._llm.ainvoke(self._messages)
                    response_text = response.content
                    
                    # Parse action from response
                    try:
                        # Handle markdown code blocks
                        if "```json" in response_text:
                            json_str = response_text.split("```json")[1].split("```")[0].strip()
                        elif "```" in response_text:
                            json_str = response_text.split("```")[1].split("```")[0].strip()
                        else:
                            json_str = response_text.strip()
                        
                        action_data = json.loads(json_str)
                        action = action_data.get("action", "")
                        params = action_data.get("params", {})
                        thought = action_data.get("thought", "")
                        
                        print(f"  Thought: {thought}")
                        print(f"  Action: {action} {params}")
                        
                    except json.JSONDecodeError as e:
                        print(f"  Failed to parse response: {e}")
                        self._messages.append(AIMessage(content=response_text))
                        self._messages.append(HumanMessage(content="Please respond with valid JSON."))
                        continue
                    
                    # Execute action
                    action_result = await self._execute_action(action, params)
                    print(f"  Result: {action_result}")
                    
                    # Check if done
                    if action == "done":
                        result["success"] = True
                        result["message"] = params.get("result", "Task completed")
                        result["steps"] = step + 1
                        break
                    
                    # Update conversation with result and new page state
                    self._messages.append(AIMessage(content=response_text))
                    page_state = await self._get_page_state()
                    self._messages.append(HumanMessage(content=f"Action result: {action_result}\n\nCurrent page state:\n{page_state}"))
                
                else:
                    result["message"] = f"Reached maximum steps ({max_steps})"
                    result["steps"] = max_steps
            
            elapsed = (datetime.now() - start_time).total_seconds()
            print("-" * 50)
            print(f"Agent completed in {elapsed:.2f} seconds")
            print(f"Result: {result['message']}")
            
        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            result["message"] = f"Error: {e}"
            print(f"Error after {elapsed:.2f} seconds: {e}")
            raise
        
        finally:
            # Release Steel session
            if self._session:
                try:
                    client.sessions.release(self._session.id)
                    print("Steel session released")
                except Exception as e:
                    print(f"Failed to release session: {e}")
        
        return result

