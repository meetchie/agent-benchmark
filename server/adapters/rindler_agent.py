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
