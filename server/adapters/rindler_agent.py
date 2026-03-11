"""
Rindler MCP Adapter - Connects to the Go MCP server over SSE for browser automation.

This module provides the RindlerTelemetricAgent which uses LLM tool-calling
to drive browser actions on the Go server, integrated with arena telemetry.
"""

import json
import os
import aiohttp
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    from .base_agent import BaseAgent
except ImportError:
    BaseAgent = object  # Tests load this module directly; agent class won't be usable but other classes will import fine


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a web automation agent. You interact with websites by calling tools.
After each tool call, you receive the page's accessibility tree showing all
visible elements. Use this to decide your next action.

When you have completed the goal (or determined it cannot be completed),
call the "done" tool with {success: true/false, message: "explanation"}.

Be efficient — prefer site-specific tools (like shipt_fill_address) over
manual element selection when available."""

DONE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "success": {"type": "boolean", "description": "Whether the goal was accomplished"},
        "message": {"type": "string", "description": "Brief summary of what was accomplished or why it failed"},
    },
    "required": ["success", "message"],
}

MAX_TREE_CHARS = 4000
MAX_RESULT_CHARS = 8000

COST_RATES = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "claude-sonnet": {"input": 3.00, "output": 15.00},
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class LLMResponse:
    """Structured response from an LLM tool-calling API."""
    tool_name: Optional[str]
    tool_args: Optional[dict]
    tool_call_id: Optional[str]
    text: Optional[str]
    tokens_input: int
    tokens_output: int


# ---------------------------------------------------------------------------
# MCP Tool Bridge
# ---------------------------------------------------------------------------

class MCPToolBridge:
    """Converts between MCP tool schemas and LLM function definitions."""

    @staticmethod
    def mcp_tools_to_llm_tools(mcp_tools: list, provider: str) -> List[dict]:
        """Convert MCP Tool objects to LLM provider format.

        Args:
            mcp_tools: List of MCP Tool objects (with .name, .description, .inputSchema)
            provider: "openai" or "anthropic"
        """
        result = []
        for tool in mcp_tools:
            if provider == "openai":
                result.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                })
            else:  # anthropic
                result.append({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                })
        return result

    @staticmethod
    def inject_done_tool(tools: List[dict], provider: str) -> List[dict]:
        """Append the synthetic 'done' tool to the tool list."""
        if provider == "openai":
            tools = tools + [{
                "type": "function",
                "function": {
                    "name": "done",
                    "description": "Call this when you have completed the goal or determined it cannot be completed.",
                    "parameters": DONE_TOOL_SCHEMA,
                },
            }]
        else:  # anthropic
            tools = tools + [{
                "name": "done",
                "description": "Call this when you have completed the goal or determined it cannot be completed.",
                "input_schema": DONE_TOOL_SCHEMA,
            }]
        return tools

    @staticmethod
    def inject_auth_token(tool_args: dict, token: str) -> dict:
        """Return a copy of tool_args with _meta.authorization injected."""
        result = dict(tool_args)
        meta = dict(result.get("_meta", {}))
        meta["authorization"] = f"Bearer {token}"
        result["_meta"] = meta
        return result


# ---------------------------------------------------------------------------
# CallToolResult parser
# ---------------------------------------------------------------------------

def parse_tool_result(result) -> dict:
    """Extract JSON dict from MCP CallToolResult."""
    if not result.content:
        return {"error": "empty response"}
    text = result.content[0].text
    return json.loads(text)


def truncate(text: str, max_chars: int) -> str:
    """Truncate text with an informative suffix."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated, use get_page_state for full tree]"


# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------

class LLMClient:
    """Provider-agnostic wrapper for LLM tool-calling APIs."""

    def __init__(self, model_name: str, system_prompt: str):
        self.model = model_name
        self.system_prompt = system_prompt

        if model_name.startswith("gpt"):
            self.provider = "openai"
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI()
        elif model_name.startswith("claude"):
            self.provider = "anthropic"
            from anthropic import AsyncAnthropic
            model_map = {"claude-sonnet": "claude-sonnet-4-6"}
            self.model = model_map.get(model_name, model_name)
            self._client = AsyncAnthropic()
        else:
            raise ValueError(f"Unknown model prefix: {model_name}. Use gpt-* or claude-*")

    async def call(self, messages: List[dict], tools: List[dict]) -> LLMResponse:
        if self.provider == "openai":
            return await self._call_openai(messages, tools)
        else:
            return await self._call_anthropic(messages, tools)

    async def _call_openai(self, messages, tools):
        kwargs = {
            "model": self.model,
            "messages": [{"role": "system", "content": self.system_prompt}] + messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["parallel_tool_calls"] = False

        response = await self._client.chat.completions.create(**kwargs)
        msg = response.choices[0].message
        usage = response.usage

        if msg.tool_calls:
            tc = msg.tool_calls[0]
            return LLMResponse(
                tool_name=tc.function.name,
                tool_args=json.loads(tc.function.arguments),
                tool_call_id=tc.id,
                text=None,
                tokens_input=usage.prompt_tokens,
                tokens_output=usage.completion_tokens,
            )
        return LLMResponse(
            tool_name=None, tool_args=None, tool_call_id=None,
            text=msg.content,
            tokens_input=usage.prompt_tokens,
            tokens_output=usage.completion_tokens,
        )

    async def _call_anthropic(self, messages, tools):
        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "system": self.system_prompt,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self._client.messages.create(**kwargs)
        usage = response.usage

        for block in response.content:
            if block.type == "tool_use":
                return LLMResponse(
                    tool_name=block.name,
                    tool_args=block.input,
                    tool_call_id=block.id,
                    text=None,
                    tokens_input=usage.input_tokens,
                    tokens_output=usage.output_tokens,
                )

        text_parts = [b.text for b in response.content if b.type == "text"]
        return LLMResponse(
            tool_name=None, tool_args=None, tool_call_id=None,
            text="\n".join(text_parts) if text_parts else None,
            tokens_input=usage.input_tokens,
            tokens_output=usage.output_tokens,
        )


# ---------------------------------------------------------------------------
# Rindler Telemetric Agent
# ---------------------------------------------------------------------------

class RindlerTelemetricAgent(BaseAgent):
    """
    MCP-based browser automation agent connecting to the Rindler Go server.
    Uses LLM tool-calling to drive browser actions over SSE.
    """

    def __init__(self, run_id: str, goal: str, lane: str = "RINDLER", **kwargs):
        super().__init__(run_id=run_id, goal=goal, lane=lane)
        self.server_url = os.environ["RINDLER_SERVER_URL"]
        self.email = os.environ["RINDLER_EMAIL"]
        self.password = os.environ["RINDLER_PASSWORD"]
        self.llm_name = kwargs.get("llm", "gpt-4o-mini")
        self.max_steps = kwargs.get("max_steps", 25)
        self._token = None
        self._session_id = None

    async def _login(self) -> str:
        url = f"{self.server_url}/auth/login"
        async with aiohttp.ClientSession() as http:
            async with http.post(url, json={"email": self.email, "password": self.password}) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"Login failed ({resp.status}): {body}")
                data = await resp.json()
                return data["token"]

    def _build_initial_messages(self, provider: str, accessibility_tree: str) -> list:
        tree = truncate(accessibility_tree, MAX_TREE_CHARS)
        content = f"Goal: {self.goal}\n\nCurrent page:\n{tree}"
        return [{"role": "user", "content": content}]

    def _append_tool_exchange(self, provider: str, messages: list, llm_resp: LLMResponse, parsed_result: dict) -> list:
        result_text = truncate(json.dumps(parsed_result), MAX_RESULT_CHARS)
        messages = list(messages)
        if provider == "openai":
            messages.append({
                "role": "assistant",
                "tool_calls": [{"id": llm_resp.tool_call_id, "type": "function",
                    "function": {"name": llm_resp.tool_name, "arguments": json.dumps(llm_resp.tool_args)}}],
            })
            messages.append({"role": "tool", "tool_call_id": llm_resp.tool_call_id, "content": result_text})
        else:
            messages.append({
                "role": "assistant",
                "content": [{"type": "tool_use", "id": llm_resp.tool_call_id,
                    "name": llm_resp.tool_name, "input": llm_resp.tool_args}],
            })
            messages.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": llm_resp.tool_call_id, "content": result_text}],
            })
        return messages

    def _build_result(self, done_args: dict, steps: int) -> dict:
        return {
            "success": done_args.get("success", False),
            "message": done_args.get("message", ""),
            "steps": steps,
            "final_extraction": done_args.get("message", ""),
        }

    def _compute_cost(self, tokens_input: int, tokens_output: int) -> float:
        rates = COST_RATES.get(self.llm_name, COST_RATES["gpt-4o-mini"])
        return (tokens_input / 1_000_000) * rates["input"] + (tokens_output / 1_000_000) * rates["output"]

    async def run(self, start_url=None, **kwargs):
        from mcp.client.sse import sse_client
        from mcp import ClientSession

        self.print_run_header(start_url)
        self._token = await self._login()
        llm = LLMClient(self.llm_name, SYSTEM_PROMPT)

        async with sse_client(self.server_url + "/mcp/") as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                mcp_tools = (await client.list_tools()).tools
                llm_tools = MCPToolBridge.mcp_tools_to_llm_tools(mcp_tools, llm.provider)
                llm_tools = MCPToolBridge.inject_done_tool(llm_tools, llm.provider)

                raw = await client.call_tool("browse_to_url", MCPToolBridge.inject_auth_token({"url": start_url}, self._token))
                parsed = parse_tool_result(raw)
                self._session_id = parsed.get("session_id")
                messages = self._build_initial_messages(llm.provider, parsed.get("accessibility_tree", ""))

                try:
                    for step in range(self.max_steps):
                        llm_response = await llm.call(messages, llm_tools)
                        if llm_response.tool_name == "done":
                            return self._build_result(llm_response.tool_args or {}, step + 1)
                        if llm_response.tool_name:
                            self.log_step_start(action_type=llm_response.tool_name, action_data=llm_response.tool_args)
                            tool_args = MCPToolBridge.inject_auth_token(llm_response.tool_args, self._token)
                            raw = await client.call_tool(llm_response.tool_name, tool_args)
                            parsed = parse_tool_result(raw)
                            event_dict = self.log_step_end(
                                tokens_input=llm_response.tokens_input,
                                tokens_output=llm_response.tokens_output,
                                observation={"tool_result": parsed},
                            )
                            event_dict["cost_usd"] = self._compute_cost(llm_response.tokens_input, llm_response.tokens_output)
                            messages = self._append_tool_exchange(llm.provider, messages, llm_response, parsed)
                        else:
                            messages.append({"role": "assistant", "content": llm_response.text})
                finally:
                    if self._session_id:
                        try:
                            await client.call_tool("close_session", MCPToolBridge.inject_auth_token({"session_id": self._session_id}, self._token))
                        except Exception:
                            pass

        return self._build_result({"success": False, "message": "max steps reached"}, self.max_steps)
