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
LLMResponse = _mod.LLMResponse
LLMClient = _mod.LLMClient


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


class TestLLMClient:

    def _make_openai_client(self):
        """Create an LLMClient for OpenAI without triggering the real constructor."""
        client = LLMClient.__new__(LLMClient)
        client.model = "gpt-4o-mini"
        client.provider = "openai"
        client.system_prompt = "You are a test agent."
        return client

    def _make_anthropic_client(self):
        """Create an LLMClient for Anthropic without triggering the real constructor."""
        client = LLMClient.__new__(LLMClient)
        client.model = "claude-sonnet-4-6"
        client.provider = "anthropic"
        client.system_prompt = "You are a test agent."
        return client

    def test_openai_tool_call_parsing(self):
        import asyncio

        client = self._make_openai_client()

        # Build a mock OpenAI response with a tool call
        tool_call = MagicMock()
        tool_call.id = "call_abc123"
        tool_call.function.name = "browse_to_url"
        tool_call.function.arguments = json.dumps({"url": "https://example.com"})

        message = MagicMock()
        message.tool_calls = [tool_call]
        message.content = None

        usage = MagicMock()
        usage.prompt_tokens = 100
        usage.completion_tokens = 20

        response = MagicMock()
        response.choices = [MagicMock(message=message)]
        response.usage = usage

        async def fake_create(**kwargs):
            return response

        mock_openai = MagicMock()
        mock_openai.chat.completions.create = fake_create
        client._client = mock_openai

        result = asyncio.run(client.call([{"role": "user", "content": "go"}], []))

        assert result.tool_name == "browse_to_url"
        assert result.tool_args == {"url": "https://example.com"}
        assert result.tool_call_id == "call_abc123"
        assert result.text is None
        assert result.tokens_input == 100
        assert result.tokens_output == 20

    def test_openai_text_response(self):
        import asyncio

        client = self._make_openai_client()

        # Build a mock OpenAI response with no tool calls (text only)
        message = MagicMock()
        message.tool_calls = None
        message.content = "Task completed successfully."

        usage = MagicMock()
        usage.prompt_tokens = 50
        usage.completion_tokens = 10

        response = MagicMock()
        response.choices = [MagicMock(message=message)]
        response.usage = usage

        async def fake_create(**kwargs):
            return response

        mock_openai = MagicMock()
        mock_openai.chat.completions.create = fake_create
        client._client = mock_openai

        result = asyncio.run(client.call([{"role": "user", "content": "done?"}], []))

        assert result.tool_name is None
        assert result.tool_args is None
        assert result.tool_call_id is None
        assert result.text == "Task completed successfully."
        assert result.tokens_input == 50
        assert result.tokens_output == 10

    def test_anthropic_tool_call_parsing(self):
        import asyncio

        client = self._make_anthropic_client()

        # Build a mock Anthropic response with a tool_use block
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "toolu_xyz"
        tool_block.name = "click_element"
        tool_block.input = {"selector": "#submit-button"}

        usage = MagicMock()
        usage.input_tokens = 200
        usage.output_tokens = 30

        response = MagicMock()
        response.content = [tool_block]
        response.usage = usage

        async def fake_create(**kwargs):
            return response

        mock_anthropic = MagicMock()
        mock_anthropic.messages.create = fake_create
        client._client = mock_anthropic

        result = asyncio.run(client.call([{"role": "user", "content": "click submit"}], []))

        assert result.tool_name == "click_element"
        assert result.tool_args == {"selector": "#submit-button"}
        assert result.tool_call_id == "toolu_xyz"
        assert result.text is None
        assert result.tokens_input == 200
        assert result.tokens_output == 30
