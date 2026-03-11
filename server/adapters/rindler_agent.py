"""
Rindler MCP Adapter - Connects to the Go MCP server over SSE for browser automation.

This module provides the RindlerTelemetricAgent which uses LLM tool-calling
to drive browser actions on the Go server, integrated with arena telemetry.
"""

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


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
