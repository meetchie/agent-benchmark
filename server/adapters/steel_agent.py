"""
Steel Telemetric Agent - Manual Playwright on Steel with LangChain orchestration.

This module provides the SteelTelemetricAgent class which uses Steel SDK for
browser sessions and LangChain's ChatOpenAI to drive Playwright interactions,
with telemetry logging via BaseAgent.
"""

import os
import asyncio
import json
from datetime import datetime
from typing import Dict, Any, Optional, List

from playwright.async_api import async_playwright, Page, Browser
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.callbacks import BaseCallbackHandler

from .base_agent import BaseAgent


class TelemetryCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler for telemetry logging."""
    
    def __init__(self, agent: "SteelTelemetricAgent"):
        self.agent = agent
        self._current_step_start_time: Optional[datetime] = None
    
    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs) -> None:
        """Called when LLM starts processing."""
        self._current_step_start_time = datetime.now()
        self.agent.log_step_start(
            action_type="llm_call",
            action_data={"prompts": prompts[:1] if prompts else None}
        )
        print(f"[Step {self.agent._current_step_index}] START - LLM Call")
    
    def on_llm_end(self, response, **kwargs) -> None:
        """Called when LLM finishes processing."""
        tokens_input = None
        tokens_output = None
        
        try:
            if hasattr(response, 'llm_output') and response.llm_output:
                token_usage = response.llm_output.get('token_usage', {})
                tokens_input = token_usage.get('prompt_tokens')
                tokens_output = token_usage.get('completion_tokens')
        except Exception:
            pass
        
        observation = None
        try:
            if response.generations and response.generations[0]:
                gen = response.generations[0][0]
                observation = {"response": gen.text[:500] if hasattr(gen, 'text') else str(gen)[:500]}
        except Exception:
            pass
        
        event_dict = self.agent.log_step_end(
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            observation=observation
        )
        
        duration_str = f"{event_dict.get('duration_ms', 0):.2f}ms"
        print(f"[Step {self.agent._current_step_index}] END   - Duration: {duration_str}, Tokens: {tokens_input or 0}/{tokens_output or 0}")


class SteelTelemetricAgent(BaseAgent):
    """
    Browser automation agent using Steel SDK with LangChain orchestration.
    
    Uses Steel for cloud browser sessions, Playwright for browser control,
    and LangChain ChatOpenAI for intelligent navigation decisions.
    """
    
    SYSTEM_PROMPT = """You are a browser automation assistant. You are given a goal and the current state of a webpage.
Your job is to decide what action to take next to accomplish the goal.

Available actions:
- click(selector): Click on an element matching the selector
- type(selector, text): Type text into an element
- goto(url): Navigate to a URL
- scroll(direction): Scroll the page ("up" or "down")
- wait(seconds): Wait for a specified number of seconds
- done(result): Indicate the task is complete with a result message

IMPORTANT - Selector syntax (Playwright-compatible):
- CSS selectors: "button.submit", "#login-form", "input[type='email']"
- Text selectors: "text=Sign In", "text=Add to cart" (finds element containing text)
- Chained: "button >> text=Submit" (button containing "Submit")
- DO NOT use jQuery syntax like :contains() - it is not supported!

Respond with a JSON object containing:
- "thought": Your reasoning about what to do next
- "action": The action name
- "params": Object with action parameters

Example responses:
{"thought": "I need to click the login button", "action": "click", "params": {"selector": "text=Sign In"}}
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
        super().__init__(run_id=run_id, goal=goal, lane=lane)
        
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
        
        # Conversation history
        self._messages: List = []
    
    async def _get_page_state(self) -> str:
        """Get current page state for LLM context."""
        if not self._page:
            return "No page loaded"
        
        try:
            url = self._page.url
            title = await self._page.title()
            
            body_text = await self._page.evaluate("""
                () => {
                    const body = document.body;
                    return body ? body.innerText.substring(0, 3000) : '';
                }
            """)
            
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
    
    async def run(self, start_url: Optional[str] = None, max_steps: int = 20, **kwargs) -> Dict[str, Any]:
        """
        Run the agent with Steel browser session.
        
        Args:
            start_url: Optional URL to start at
            max_steps: Maximum number of steps before stopping
            **kwargs: Additional arguments (unused)
            
        Returns:
            Dictionary with run results and telemetry
        """
        from steel import Steel
        
        steel_api_key = os.getenv("STEEL_API_KEY")
        if not steel_api_key:
            raise ValueError("STEEL_API_KEY not found in environment variables")
        
        client = Steel(steel_api_key=steel_api_key)
        
        self.print_run_header(start_url)
        
        start_time = datetime.now()
        result = {"success": False, "message": "", "steps": 0}
        
        try:
            # Create Steel session
            self._session = client.sessions.create()
            session_id = self._session.id
            websocket_url = f"wss://connect.steel.dev?apiKey={steel_api_key}&sessionId={session_id}"
            
            print(f"Steel Session ID: {session_id}")
            
            session_url = getattr(self._session, 'session_viewer_url', None) or f"https://app.steel.dev/sessions/{session_id}"
            print(f"View live session at: {session_url}")
            self.log_artifact("steel_session", session_url)
            
            async with async_playwright() as p:
                self._browser = await p.chromium.connect_over_cdp(websocket_url)
                context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
                self._page = await context.new_page()
                
                if start_url:
                    await self._page.goto(start_url, wait_until="domcontentloaded")
                
                self._messages = [
                    SystemMessage(content=self.SYSTEM_PROMPT),
                    HumanMessage(content=f"Goal: {self.goal}\n\nCurrent page state:\n{await self._get_page_state()}")
                ]
                
                # Main agent loop
                for step in range(max_steps):
                    response = await self._llm.ainvoke(self._messages)
                    response_text = response.content
                    
                    try:
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
                    
                    action_result = await self._execute_action(action, params)
                    print(f"  Result: {action_result}")
                    
                    if action == "done":
                        result["success"] = True
                        result["message"] = params.get("result", "Task completed")
                        result["steps"] = step + 1
                        break
                    
                    self._messages.append(AIMessage(content=response_text))
                    page_state = await self._get_page_state()
                    self._messages.append(HumanMessage(content=f"Action result: {action_result}\n\nCurrent page state:\n{page_state}"))
                
                else:
                    result["message"] = f"Reached maximum steps ({max_steps})"
                    result["steps"] = max_steps
            
            elapsed = (datetime.now() - start_time).total_seconds()
            self.print_run_footer(elapsed, result["success"], result["message"])
            
        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            result["message"] = f"Error: {e}"
            print(f"Error after {elapsed:.2f} seconds: {e}")
            raise
        
        finally:
            if self._session:
                try:
                    client.sessions.release(self._session.id)
                    print("Steel session released")
                except Exception as e:
                    print(f"Failed to release session: {e}")
        
        return result
