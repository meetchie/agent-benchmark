"""Tests for the Rindler MCP adapter."""

import json
import sys
import importlib.util
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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
RindlerTelemetricAgent = _mod.RindlerTelemetricAgent


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
        mock_result.isError = False
        parsed = parse_tool_result(mock_result)
        assert parsed["session_id"] == "abc"
        assert parsed["success"] is True

    def test_parse_empty_content(self):
        mock_result = MagicMock()
        mock_result.content = []
        mock_result.isError = False
        parsed = parse_tool_result(mock_result)
        assert "error" in parsed

    def test_parse_non_json_returns_error(self):
        mock_result = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "not json at all"
        mock_result.content = [mock_content]
        mock_result.isError = False
        parsed = parse_tool_result(mock_result)
        assert "error" in parsed
        assert parsed["error"] == "non-JSON response"
        assert "not json" in parsed["raw"]

    def test_parse_is_error_flag(self):
        mock_result = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "401 Unauthorized"
        mock_result.content = [mock_content]
        mock_result.isError = True
        parsed = parse_tool_result(mock_result)
        assert parsed["error"] == "401 Unauthorized"

    def test_parse_is_error_empty_content(self):
        mock_result = MagicMock()
        mock_result.content = []
        mock_result.isError = True
        parsed = parse_tool_result(mock_result)
        assert parsed["error"] == "unknown error"


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


class TestRindlerHelpers:

    def _make_agent(self):
        """Create a partially initialized agent for testing helper methods."""
        agent = object.__new__(RindlerTelemetricAgent)
        agent.goal = "Buy bananas"
        agent.llm_name = "gpt-4o-mini"
        agent.server_url = "http://localhost:8080"
        agent._code_verifier = None
        agent._refresh_token = None
        agent._callback_port = 9999
        return agent

    def test_build_initial_messages_openai(self):
        agent = self._make_agent()
        msgs = agent._build_initial_messages("openai", "<tree>button 'Add'</tree>")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert "Buy bananas" in msgs[0]["content"]
        assert "button 'Add'" in msgs[0]["content"]

    def test_build_initial_messages_truncates(self):
        agent = self._make_agent()
        long_tree = "x" * 5000
        msgs = agent._build_initial_messages("openai", long_tree)
        assert "truncated" in msgs[0]["content"]
        assert len(msgs[0]["content"]) < 5000

    def test_append_tool_exchange_openai(self):
        agent = self._make_agent()
        resp = LLMResponse(tool_name="browse_to_url", tool_args={"url": "https://example.com"},
                          tool_call_id="call_123", text=None, tokens_input=100, tokens_output=25)
        parsed = {"session_id": "s1", "accessibility_tree": "<tree/>"}
        msgs = [{"role": "user", "content": "goal"}]
        result = agent._append_tool_exchange("openai", msgs, resp, parsed)
        assert len(result) == 3
        assert result[1]["role"] == "assistant"
        assert result[1]["tool_calls"][0]["id"] == "call_123"
        assert result[2]["role"] == "tool"
        assert result[2]["tool_call_id"] == "call_123"

    def test_append_tool_exchange_anthropic(self):
        agent = self._make_agent()
        resp = LLMResponse(tool_name="click_element", tool_args={"session_id": "s1", "selector": "#btn"},
                          tool_call_id="toolu_456", text=None, tokens_input=200, tokens_output=50)
        parsed = {"session_id": "s1", "success": True}
        msgs = [{"role": "user", "content": "goal"}]
        result = agent._append_tool_exchange("anthropic", msgs, resp, parsed)
        assert len(result) == 3
        assert result[1]["role"] == "assistant"
        assert result[1]["content"][0]["type"] == "tool_use"
        assert result[2]["role"] == "user"
        assert result[2]["content"][0]["type"] == "tool_result"
        assert result[2]["content"][0]["tool_use_id"] == "toolu_456"

    def test_build_result(self):
        agent = self._make_agent()
        result = agent._build_result({"success": True, "message": "Done!"}, 5)
        assert result["success"] is True
        assert result["message"] == "Done!"
        assert result["steps"] == 5
        assert result["final_extraction"] == "Done!"

    def test_compute_cost_gpt4o_mini(self):
        agent = self._make_agent()
        agent.llm_name = "gpt-4o-mini"
        cost = agent._compute_cost(1_000_000, 1_000_000)
        assert abs(cost - 0.75) < 0.001  # 0.15 + 0.60

    def test_compute_cost_unknown_model_defaults(self):
        agent = self._make_agent()
        agent.llm_name = "unknown-model"
        cost = agent._compute_cost(1_000_000, 1_000_000)
        assert abs(cost - 0.75) < 0.001  # falls back to gpt-4o-mini rates

    def test_is_auth_error_401(self):
        assert RindlerTelemetricAgent._is_auth_error({"error": "401 Unauthorized"}) is True

    def test_is_auth_error_token_expired(self):
        assert RindlerTelemetricAgent._is_auth_error({"error": "Token expired"}) is True

    def test_is_auth_error_not_auth(self):
        assert RindlerTelemetricAgent._is_auth_error({"error": "element not found"}) is False

    def test_is_auth_error_no_error_key(self):
        assert RindlerTelemetricAgent._is_auth_error({"success": True}) is False

    @pytest.mark.asyncio
    async def test_full_oauth_flow(self):
        """Test the full _authenticate() flow: discover → register → authorize → exchange."""
        agent = self._make_agent()
        agent._discover = AsyncMock(return_value={
            "registration_endpoint": "http://localhost:8080/auth/register-client",
            "authorization_endpoint": "http://localhost:8080/auth/authorize",
            "token_endpoint": "http://localhost:8080/auth/token",
        })
        agent._register = AsyncMock(return_value="dyn_test123")
        agent._authorize = AsyncMock(return_value="auth-code-abc")
        agent._exchange = AsyncMock(return_value="eyJ.access.token")

        token = await agent._authenticate()

        assert token == "eyJ.access.token"
        agent._discover.assert_called_once()
        agent._register.assert_called_once()
        agent._authorize.assert_called_once()
        agent._exchange.assert_called_once()


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRindlerIntegration:

    async def test_full_action_loop(self, monkeypatch):
        monkeypatch.setenv("RINDLER_SERVER_URL", "http://localhost:8080")
        monkeypatch.setenv("RINDLER_EMAIL", "test@test.com")
        # RINDLER_PASSWORD removed — server uses email-only auth
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        # Create agent bypassing __init__ (BaseAgent == object in test context)
        agent = object.__new__(RindlerTelemetricAgent)
        agent.run_id = "r1"
        agent.goal = "Click the button"
        agent.lane = "RINDLER"
        agent.server_url = "http://localhost:8080"
        agent.email = "test@test.com"
        # password field removed — server uses email-only auth
        agent.llm_name = "gpt-4o-mini"
        agent.max_steps = 25
        agent._token = None
        agent._session_id = None
        agent.trace_id = "test-trace"
        agent.telemetry_events = []
        agent._current_step_index = 0
        agent._current_action_type = None

        # Stub telemetry methods that would come from BaseAgent
        agent.print_run_header = lambda *a, **kw: None

        def mock_log_step_start(action_type=None, action_data=None):
            agent._current_step_index += 1
            agent._current_action_type = action_type

        def mock_log_step_end(tokens_input=None, tokens_output=None, observation=None):
            event = {
                "event_type": "step_end",
                "action_type": agent._current_action_type,
                "tokens_input": tokens_input,
                "tokens_output": tokens_output,
            }
            agent.telemetry_events.append(event)
            return event

        agent.log_step_start = mock_log_step_start
        agent.log_step_end = mock_log_step_end

        # Mock _login to skip HTTP
        async def mock_login():
            return "jwt-test-token"

        agent._login = mock_login

        # Build mock MCP client
        mock_mcp_client = MagicMock()
        mock_mcp_client.initialize = AsyncMock()

        browse_tool = FakeTool(
            "browse_to_url", "Navigate",
            {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        )
        click_tool = FakeTool(
            "click_element", "Click",
            {"type": "object", "properties": {"selector": {"type": "string"}, "session_id": {"type": "string"}}, "required": ["selector", "session_id"]},
        )
        mock_list_result = MagicMock()
        mock_list_result.tools = [browse_tool, click_tool]
        mock_mcp_client.list_tools = AsyncMock(return_value=mock_list_result)

        def make_result(data):
            r = MagicMock()
            c = MagicMock()
            c.text = json.dumps(data)
            r.content = [c]
            r.isError = False
            return r

        # call_tool is called 3 times:
        #   1) browse_to_url  (initial page load before the loop)
        #   2) click_element  (step 0 in the loop)
        #   3) close_session  (finally block)
        call_results = [
            make_result({"session_id": "s1", "accessibility_tree": "<tree>button 'Submit'</tree>", "page_url": "https://example.com", "page_title": "Test"}),
            make_result({"session_id": "s1", "accessibility_tree": "<tree>text 'Success!'</tree>", "success": True, "strategy_used": "css"}),
            make_result({"success": True}),  # close_session
        ]
        mock_mcp_client.call_tool = AsyncMock(side_effect=call_results)

        # Mock LLM responses: click_element then done
        llm_responses = [
            LLMResponse(
                tool_name="click_element",
                tool_args={"session_id": "s1", "selector": "#submit"},
                tool_call_id="call_1",
                text=None,
                tokens_input=500,
                tokens_output=50,
            ),
            LLMResponse(
                tool_name="done",
                tool_args={"success": True, "message": "Clicked submit"},
                tool_call_id="call_2",
                text=None,
                tokens_input=600,
                tokens_output=30,
            ),
        ]

        mock_llm = MagicMock()
        mock_llm.provider = "openai"
        mock_llm.call = AsyncMock(side_effect=llm_responses)

        # Async context managers for sse_client and ClientSession
        class MockSSEContext:
            async def __aenter__(self):
                return (MagicMock(), MagicMock())

            async def __aexit__(self, *args):
                pass

        class MockClientSessionContext:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return mock_mcp_client

            async def __aexit__(self, *args):
                pass

        import mcp
        import mcp.client.sse

        with patch.object(_mod, "LLMClient", return_value=mock_llm):
            with patch.object(mcp.client.sse, "sse_client", return_value=MockSSEContext()):
                with patch.object(mcp, "ClientSession", MockClientSessionContext):
                    result = await agent.run(start_url="https://example.com")

        assert result["success"] is True
        assert result["message"] == "Clicked submit"
        assert result["steps"] == 2

        # Telemetry: one step_end for click_element (done exits the loop early, before log)
        step_ends = [e for e in agent.telemetry_events if e.get("event_type") == "step_end"]
        assert len(step_ends) == 1
        assert step_ends[0]["action_type"] == "click_element"

        # close_session must have been called in the finally block
        close_calls = [
            c for c in mock_mcp_client.call_tool.call_args_list
            if c[0][0] == "close_session"
        ]
        assert len(close_calls) == 1

    async def test_401_retry_re_logins(self, monkeypatch):
        """When a tool call returns a 401 error, the agent should re-login and retry."""
        monkeypatch.setenv("RINDLER_SERVER_URL", "http://localhost:8080")
        monkeypatch.setenv("RINDLER_EMAIL", "test@test.com")
        # RINDLER_PASSWORD removed — server uses email-only auth
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        agent = object.__new__(RindlerTelemetricAgent)
        agent.run_id = "r2"
        agent.goal = "Click button"
        agent.lane = "RINDLER"
        agent.server_url = "http://localhost:8080"
        agent.email = "test@test.com"
        # password field removed — server uses email-only auth
        agent.llm_name = "gpt-4o-mini"
        agent.max_steps = 25
        agent._token = None
        agent._session_id = None
        agent.trace_id = "test-trace"
        agent.telemetry_events = []
        agent._current_step_index = 0
        agent._current_action_type = None

        agent.print_run_header = lambda *a, **kw: None
        def mock_log_step_start(action_type=None, action_data=None):
            agent._current_step_index += 1
            agent._current_action_type = action_type
        def mock_log_step_end(tokens_input=None, tokens_output=None, observation=None):
            event = {"event_type": "step_end", "action_type": agent._current_action_type,
                     "tokens_input": tokens_input, "tokens_output": tokens_output}
            agent.telemetry_events.append(event)
            return event
        agent.log_step_start = mock_log_step_start
        agent.log_step_end = mock_log_step_end

        login_count = 0
        async def mock_login():
            nonlocal login_count
            login_count += 1
            return f"jwt-token-{login_count}"
        agent._login = mock_login

        mock_mcp_client = MagicMock()
        mock_mcp_client.initialize = AsyncMock()

        browse_tool = FakeTool(
            "browse_to_url", "Navigate",
            {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        )
        mock_list_result = MagicMock()
        mock_list_result.tools = [browse_tool]
        mock_mcp_client.list_tools = AsyncMock(return_value=mock_list_result)

        def make_result(data, is_error=False):
            r = MagicMock()
            c = MagicMock()
            c.text = json.dumps(data) if isinstance(data, dict) else data
            r.content = [c]
            r.isError = is_error
            return r

        # browse_to_url: first returns 401 error, retry succeeds
        call_results = [
            make_result({"error": "401 Unauthorized"}, is_error=True),  # 401 on browse
            make_result({"session_id": "s1", "accessibility_tree": "<tree/>", "page_url": "https://example.com", "page_title": "Test"}),  # retry succeeds
            make_result({"success": True}),  # close_session
        ]
        mock_mcp_client.call_tool = AsyncMock(side_effect=call_results)

        # LLM immediately says done
        llm_responses = [
            LLMResponse(tool_name="done", tool_args={"success": True, "message": "Done"},
                        tool_call_id="call_1", text=None, tokens_input=100, tokens_output=10),
        ]
        mock_llm = MagicMock()
        mock_llm.provider = "openai"
        mock_llm.call = AsyncMock(side_effect=llm_responses)

        class MockSSEContext:
            async def __aenter__(self):
                return (MagicMock(), MagicMock())
            async def __aexit__(self, *args):
                pass

        class MockClientSessionContext:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return mock_mcp_client
            async def __aexit__(self, *args):
                pass

        import mcp
        import mcp.client.sse

        with patch.object(_mod, "LLMClient", return_value=mock_llm):
            with patch.object(mcp.client.sse, "sse_client", return_value=MockSSEContext()):
                with patch.object(mcp, "ClientSession", MockClientSessionContext):
                    result = await agent.run(start_url="https://example.com")

        assert result["success"] is True
        # Login was called twice: initial + retry after 401
        assert login_count == 2
        # browse_to_url was called twice (401 then success), plus close_session
        assert mock_mcp_client.call_tool.call_count == 3
