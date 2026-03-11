"""Tests for the Rindler MCP adapter."""

import json
import sys
import importlib.util
import pytest
from unittest.mock import MagicMock

# Import directly from the module file to avoid triggering adapters/__init__.py
# which loads other adapters with heavy external dependencies.
_spec = importlib.util.spec_from_file_location(
    "adapters.rindler_agent",
    __file__.replace("tests/test_rindler_agent.py", "adapters/rindler_agent.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
MCPToolBridge = _mod.MCPToolBridge
parse_tool_result = _mod.parse_tool_result


class FakeTool:
    """Mimics mcp.Tool for testing without MCP SDK dependency."""
    def __init__(self, name, description, inputSchema):
        self.name = name
        self.description = description
        self.inputSchema = inputSchema


class TestMCPToolBridge:

    def _sample_tool(self):
        return FakeTool(
            name="browse_to_url",
            description="Navigate a browser to a URL",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL"},
                    "session_id": {"type": "string", "description": "Session ID"},
                },
                "required": ["url"],
            },
        )

    def test_to_openai_format(self):
        tools = MCPToolBridge.mcp_tools_to_llm_tools([self._sample_tool()], "openai")
        assert len(tools) == 1
        t = tools[0]
        assert t["type"] == "function"
        assert t["function"]["name"] == "browse_to_url"
        assert t["function"]["description"] == "Navigate a browser to a URL"
        assert t["function"]["parameters"]["type"] == "object"
        assert "url" in t["function"]["parameters"]["properties"]

    def test_to_anthropic_format(self):
        tools = MCPToolBridge.mcp_tools_to_llm_tools([self._sample_tool()], "anthropic")
        assert len(tools) == 1
        t = tools[0]
        assert t["name"] == "browse_to_url"
        assert t["description"] == "Navigate a browser to a URL"
        assert t["input_schema"]["type"] == "object"
        assert "url" in t["input_schema"]["properties"]

    def test_inject_done_tool_openai(self):
        tools = MCPToolBridge.inject_done_tool([], "openai")
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "done"
        assert "success" in tools[0]["function"]["parameters"]["properties"]
        assert "message" in tools[0]["function"]["parameters"]["properties"]

    def test_inject_done_tool_anthropic(self):
        tools = MCPToolBridge.inject_done_tool([], "anthropic")
        assert len(tools) == 1
        assert tools[0]["name"] == "done"
        assert "success" in tools[0]["input_schema"]["properties"]

    def test_inject_auth_token(self):
        args = {"url": "https://example.com", "session_id": "abc"}
        result = MCPToolBridge.inject_auth_token(args, "my-jwt-token")
        assert result["url"] == "https://example.com"
        assert result["_meta"]["authorization"] == "Bearer my-jwt-token"
        # Original should not be mutated
        assert "_meta" not in args

    def test_inject_auth_token_preserves_existing_meta(self):
        args = {"url": "https://example.com", "_meta": {"other": "value"}}
        result = MCPToolBridge.inject_auth_token(args, "tok")
        assert result["_meta"]["authorization"] == "Bearer tok"
        assert result["_meta"]["other"] == "value"


class TestParseToolResult:

    def test_parse_json_result(self):
        mock_result = MagicMock()
        mock_content = MagicMock()
        mock_content.text = json.dumps({"session_id": "abc", "success": True})
        mock_result.content = [mock_content]
        parsed = parse_tool_result(mock_result)
        assert parsed["session_id"] == "abc"
        assert parsed["success"] is True

    def test_parse_empty_content(self):
        mock_result = MagicMock()
        mock_result.content = []
        parsed = parse_tool_result(mock_result)
        assert "error" in parsed

    def test_parse_non_json(self):
        mock_result = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "not json"
        mock_result.content = [mock_content]
        with pytest.raises(json.JSONDecodeError):
            parse_tool_result(mock_result)
