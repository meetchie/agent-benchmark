"""Unit tests for llm.py. No network: the SDK clients are replaced with fakes."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from anthropic.types import RefusalStopDetails, TextBlock, ThinkingBlock, ToolUseBlock

import llm

SERVER_DIR = Path(__file__).resolve().parents[1]
SAMPLING_PARAMS = {"temperature", "top_p", "top_k"}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in (
        "LLM_PROVIDER",
        "LLM_FALLBACKS",
        *llm.ROLE_MODEL_ENV.values(),
        *llm.ROLE_EFFORT_ENV.values(),
    ):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def usage(input_tokens=100, output_tokens=20, cache_read=None, cache_write=None):
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )


def response(content, stop_reason="end_turn", model="claude-sonnet-5-5", stop_details=None, **usage_kw):
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        stop_details=stop_details,
        model=model,
        usage=usage(**usage_kw),
    )


class FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class AsyncFakeMessages(FakeMessages):
    async def create(self, **kwargs):  # type: ignore[override]
        return FakeMessages.create(self, **kwargs)


class FakeAnthropic:
    """Records which endpoint (messages vs beta.messages) each call used."""

    def __init__(self, responses, messages_cls=FakeMessages):
        self.messages = messages_cls(responses)
        self.beta = SimpleNamespace(messages=self.messages)
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def fake_anthropic(monkeypatch):
    """Install a fake sync + async Anthropic client; returns a setter for the responses."""
    holder = {}

    def install(*responses):
        sync_client = FakeAnthropic(responses)
        async_client = FakeAnthropic(responses, AsyncFakeMessages)
        holder["sync"], holder["async"] = sync_client, async_client
        monkeypatch.setattr(llm, "_anthropic_client", lambda: sync_client)
        monkeypatch.setattr(llm, "_anthropic_async_client", lambda: async_client)
        return holder

    return install


def all_calls(holder):
    return holder["sync"].messages.calls + holder["async"].messages.calls


def assert_no_sampling(kwargs):
    assert not (SAMPLING_PARAMS & set(kwargs)), f"sampling params sent: {SAMPLING_PARAMS & set(kwargs)}"
    for nested in ("extra_body", "output_config"):
        assert not (SAMPLING_PARAMS & set(kwargs.get(nested) or {}))


def text_block(text):
    return TextBlock(type="text", text=text, citations=None)


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "success": {"type": "boolean"},
        "summary": {"type": "string", "maxLength": 500},
    },
    "required": ["success", "summary"],
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_defaults_are_anthropic_sonnet():
    assert llm.provider() == "anthropic"
    assert {role: llm.model_for(role) for role in llm.ROLES} == {
        "agent": "claude-sonnet-5-5",
        "judge": "claude-sonnet-5-5",
        "taskgen": "claude-sonnet-5-5",
    }


def test_role_env_overrides(monkeypatch):
    monkeypatch.setenv("BENCHMARK_JUDGE_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("BENCHMARK_AGENT_MODEL", " claude-opus-5-5 ")
    assert llm.model_for("judge") == "claude-haiku-5-5"
    assert llm.model_for("agent") == "claude-opus-5-5"
    assert llm.model_for("taskgen") == "claude-sonnet-5-5"


def test_openai_provider_defaults_to_gpt4o(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "OpenAI")
    assert llm.provider() == "openai"
    assert llm.model_for("agent") == "gpt-4o"


def test_unknown_provider_and_role_rejected(monkeypatch):
    with pytest.raises(ValueError):
        llm.model_for("planner")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(llm.LLMError) as err:
        llm.provider()
    assert err.value.kind == "config"


def test_effort_defaults_and_overrides(monkeypatch):
    assert llm.effort_for("agent", "claude-sonnet-5-5") == "medium"
    assert llm.effort_for("agent", "claude-haiku-4-5") is None  # older model: no effort param
    assert llm.effort_for("judge", "claude-sonnet-5-5") is None
    monkeypatch.setenv("BENCHMARK_JUDGE_EFFORT", "LOW")
    assert llm.effort_for("judge", "claude-sonnet-5-5") == "low"
    monkeypatch.setenv("BENCHMARK_AGENT_EFFORT", "default")
    assert llm.effort_for("agent", "claude-sonnet-5-5") is None
    monkeypatch.setenv("BENCHMARK_AGENT_EFFORT", "turbo")
    with pytest.raises(llm.LLMError):
        llm.effort_for("agent", "claude-sonnet-5-5")


def test_current_claude_detection():
    for model in ("claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5", "claude-opus-5",
                  "claude-sonnet-5", "claude-fable-5-1", "claude-sonnet-4-6", "anthropic.claude-sonnet-5-5"):
        assert llm.is_current_claude(model), model
    for model in ("claude-haiku-4-5", "claude-sonnet-4-5", "gpt-4o", ""):
        assert not llm.is_current_claude(model), model


def test_describe_never_includes_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    info = llm.describe()
    assert info["provider"] == "anthropic" and info["key_present"] is True
    assert "sk-test-not-real" not in json.dumps(info)


def test_provider_key_present(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert llm.provider_key_present() is False
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert llm.provider_key_present() is True


# ---------------------------------------------------------------------------
# complete_json
# ---------------------------------------------------------------------------


def test_complete_json_structured_output_request(fake_anthropic):
    holder = fake_anthropic(response([text_block('{"success": true, "summary": "ok"}')]))
    result = llm.complete_json("be a judge", "judge this", JUDGE_SCHEMA, role="judge")

    assert result == {"success": True, "summary": "ok"}
    assert isinstance(result, dict) and json.loads(json.dumps(result)) == result
    (call,) = all_calls(holder)
    assert_no_sampling(call)
    assert call["model"] == "claude-sonnet-5-5"
    assert call["system"] == "be a judge"
    assert call["messages"] == [{"role": "user", "content": "judge this"}]  # no assistant prefill
    fmt = call["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False
    assert "maxLength" not in fmt["schema"]["properties"]["summary"]  # unsupported constraint moved out
    assert "tool_choice" not in call and "tools" not in call
    assert holder["sync"].closed


def test_complete_json_usage_and_cost(fake_anthropic):
    fake_anthropic(response([text_block('{"a": 1}')], input_tokens=1_000_000, output_tokens=100_000))
    result = llm.complete_json(None, "p", {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]})
    assert result.usage.input_tokens == 1_000_000 and result.usage.output_tokens == 100_000
    assert result.model == "claude-sonnet-5-5"
    assert result.stop_reason == "end_turn"
    assert result.cost_usd == pytest.approx(2.00 + 1.00)


def test_complete_json_without_schema_parses_fenced_text(fake_anthropic):
    holder = fake_anthropic(response([text_block('Here you go:\n```json\n{"tasks": []}\n```')]))
    result = llm.complete_json(None, "make tasks", None, role="taskgen")
    assert result == {"tasks": []}
    (call,) = all_calls(holder)
    assert "output_config" not in call and "system" not in call


def test_complete_json_reads_text_after_thinking_blocks(fake_anthropic):
    fake_anthropic(response([ThinkingBlock(type="thinking", thinking="", signature="sig"), text_block('{"ok": true}')]))
    assert llm.complete_json(None, "p") == {"ok": True}


def test_complete_json_effort_from_env(fake_anthropic, monkeypatch):
    monkeypatch.setenv("BENCHMARK_TASKGEN_EFFORT", "low")
    holder = fake_anthropic(response([text_block("{}")]))
    llm.complete_json(None, "p", None, role="taskgen")
    assert all_calls(holder)[0]["output_config"] == {"effort": "low"}


def test_refusal_raises(fake_anthropic):
    fake_anthropic(response(
        [], stop_reason="refusal",
        stop_details=RefusalStopDetails(type="refusal", category="cyber", explanation=None),
    ))
    with pytest.raises(llm.LLMError) as err:
        llm.complete_json(None, "p", JUDGE_SCHEMA)
    assert err.value.kind == "refusal"
    assert err.value.category == "cyber"
    assert err.value.usage is not None


def test_max_tokens_raises(fake_anthropic):
    fake_anthropic(response([text_block('{"success": tr')], stop_reason="max_tokens"))
    with pytest.raises(llm.LLMError) as err:
        llm.complete_json(None, "p", JUDGE_SCHEMA)
    assert err.value.kind == "max_tokens"


def test_bad_json_raises_with_raw_text(fake_anthropic):
    fake_anthropic(response([text_block("I cannot produce JSON today")]))
    with pytest.raises(llm.LLMError) as err:
        llm.complete_json(None, "p")
    assert err.value.kind == "bad_json"
    assert "cannot produce" in err.value.raw_text


def test_api_error_is_wrapped(fake_anthropic):
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.BadRequestError(
        "temperature is not supported", response=httpx2.Response(400, request=request), body=None
    )
    fake_anthropic(error)
    with pytest.raises(llm.LLMError) as err:
        llm.complete_json(None, "p")
    assert err.value.kind == "api" and err.value.status_code == 400


async def test_acomplete_json(fake_anthropic):
    holder = fake_anthropic(response([text_block('{"success": false, "summary": "no"}')]))
    result = await llm.acomplete_json(None, "p", JUDGE_SCHEMA)
    assert result == {"success": False, "summary": "no"}
    assert holder["async"].messages.calls and not holder["sync"].messages.calls
    assert_no_sampling(holder["async"].messages.calls[0])


async def test_acomplete_json_refusal_raises(fake_anthropic):
    fake_anthropic(response([], stop_reason="refusal"))
    with pytest.raises(llm.LLMError) as err:
        await llm.acomplete_json(None, "p")
    assert err.value.kind == "refusal"


# ---------------------------------------------------------------------------
# Refusal fallback routing
# ---------------------------------------------------------------------------


class SplitAnthropic(FakeAnthropic):
    """Separate recorders for messages.create and beta.messages.create."""

    def __init__(self, responses):
        super().__init__(responses)
        self.beta = SimpleNamespace(messages=FakeMessages(list(responses)))


def test_sonnet_uses_beta_endpoint_with_default_fallback(monkeypatch):
    client = SplitAnthropic([response([text_block("{}")])])
    monkeypatch.setattr(llm, "_anthropic_client", lambda: client)
    llm.complete_json(None, "p", model="claude-sonnet-5-5")
    assert not client.messages.calls
    (call,) = client.beta.messages.calls
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["fallbacks"] == "default"


def test_haiku_has_no_fallback(monkeypatch):
    client = SplitAnthropic([response([text_block("{}")], model="claude-haiku-5-5")])
    monkeypatch.setattr(llm, "_anthropic_client", lambda: client)
    result = llm.complete_json(None, "p", model="claude-haiku-5-5")
    assert result.model == "claude-haiku-5-5"
    assert not client.beta.messages.calls
    (call,) = client.messages.calls
    assert "fallbacks" not in call and "betas" not in call


def test_fallbacks_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACKS", "off")
    client = SplitAnthropic([response([text_block("{}")])])
    monkeypatch.setattr(llm, "_anthropic_client", lambda: client)
    llm.complete_json(None, "p")
    assert client.messages.calls and not client.beta.messages.calls


def test_cost_uses_the_model_that_answered(fake_anthropic):
    # After a server-side fallback, response.model names the fallback model.
    fake_anthropic(response([text_block("{}")], model="claude-opus-5-5", input_tokens=1_000_000, output_tokens=0))
    result = llm.complete_json(None, "p")
    assert result.model == "claude-opus-5-5"
    assert result.cost_usd == pytest.approx(4.00)


# ---------------------------------------------------------------------------
# chat_tools
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "click",
        "description": "Click an element",
        "input_schema": {"type": "object", "properties": {"selector": {"type": "string"}}, "required": ["selector"]},
    },
    {"name": "done", "description": "Finish", "input_schema": {"type": "object", "properties": {"success": {"type": "boolean"}}}},
]


def tool_turn_response():
    return response(
        [
            {"type": "fallback", "from": {"model": "claude-sonnet-5-5"}, "to": {"model": "claude-sonnet-5"}},
            ThinkingBlock(type="thinking", thinking="", signature="sig-abc"),
            text_block("Clicking the cart."),
            ToolUseBlock(type="tool_use", id="toolu_1", name="click", input={"selector": "#cart"}),
            ToolUseBlock(type="tool_use", id="toolu_2", name="click", input={"selector": "#checkout"}),
        ],
        stop_reason="tool_use",
        input_tokens=500,
        output_tokens=50,
        cache_read=1000,
    )


def test_chat_tools_request_shape(fake_anthropic):
    holder = fake_anthropic(tool_turn_response())
    messages = [llm.user_message("Goal: buy socks")]
    llm.chat_tools("You drive a store.", messages, TOOLS, parallel_tool_calls=False)
    (call,) = all_calls(holder)
    assert_no_sampling(call)
    assert call["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert call["tools"] == TOOLS
    assert call["system"] == "You drive a store."
    assert call["output_config"] == {"effort": "medium"}  # agent role default on current Claude
    assert call["messages"] == messages and call["messages"] is not messages


def test_chat_tools_parallel_default_is_plain_auto(fake_anthropic):
    holder = fake_anthropic(tool_turn_response())
    llm.chat_tools(None, [llm.user_message("go")], TOOLS)
    assert all_calls(holder)[0]["tool_choice"] == {"type": "auto"}


def test_chat_tools_without_tools_sends_no_tool_choice(fake_anthropic):
    holder = fake_anthropic(response([text_block("hello")]))
    turn = llm.chat_tools(None, [llm.user_message("hi")], [])
    assert "tool_choice" not in all_calls(holder)[0] and "tools" not in all_calls(holder)[0]
    assert turn["text"] == "hello" and turn["tool_calls"] == []


def test_chat_tools_normalization(fake_anthropic):
    fake_anthropic(tool_turn_response())
    turn = llm.chat_tools(None, [llm.user_message("go")], TOOLS)

    assert turn["text"] == "Clicking the cart."
    assert turn["tool_calls"] == [
        {"id": "toolu_1", "name": "click", "input": {"selector": "#cart"}},
        {"id": "toolu_2", "name": "click", "input": {"selector": "#checkout"}},
    ]
    assert turn["stop_reason"] == "tool_use"
    assert turn["provider"] == "anthropic"
    assert turn["usage"] == {
        "input_tokens": 500, "output_tokens": 50, "cache_read_input_tokens": 1000,
        "cache_creation_input_tokens": 0, "total_tokens": 1550,
    }
    assert turn["cost_usd"] == pytest.approx((500 * 2.00 + 50 * 10.00 + 1000 * 0.20) / 1e6)
    content = turn["assistant_message"]["content"]
    assert turn["assistant_message"]["role"] == "assistant"
    # Thinking kept verbatim (current models need it sent back); fallback marker dropped.
    assert content[0] == {"type": "thinking", "thinking": "", "signature": "sig-abc"}
    assert [b["type"] for b in content] == ["thinking", "text", "tool_use", "tool_use"]
    json.dumps(turn)  # the whole turn is JSON-serializable (context logs)


def test_append_tool_results_anthropic(fake_anthropic):
    fake_anthropic(tool_turn_response())
    messages = [llm.user_message("go")]
    turn = llm.chat_tools(None, messages, TOOLS)
    results = [
        llm.tool_result("toolu_2", {"ok": True}),
        llm.tool_result("toolu_1", "element not found", is_error=True),
    ]
    out = llm.append_tool_results(messages, turn, results, extra_text="Keep going.")

    assert len(messages) == 1  # input not modified
    assert out[0] == messages[0]
    assert out[1] == turn["assistant_message"]
    user = out[2]
    assert user["role"] == "user"
    assert user["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "element not found", "is_error": True},
        {"type": "tool_result", "tool_use_id": "toolu_2", "content": '{"ok": true}'},
        {"type": "text", "text": "Keep going."},
    ]


def test_append_tool_results_requires_every_call(fake_anthropic):
    fake_anthropic(tool_turn_response())
    turn = llm.chat_tools(None, [llm.user_message("go")], TOOLS)
    with pytest.raises(ValueError, match="toolu_2"):
        llm.append_tool_results([], turn, [llm.tool_result("toolu_1", "ok")])
    with pytest.raises(ValueError, match="toolu_9"):
        llm.append_tool_results([], turn, [
            llm.tool_result("toolu_1", "ok"), llm.tool_result("toolu_2", "ok"), llm.tool_result("toolu_9", "ok"),
        ])


def test_append_assistant(fake_anthropic):
    fake_anthropic(response([text_block("All done.")]))
    turn = llm.chat_tools(None, [llm.user_message("go")], TOOLS)
    out = llm.append_assistant([llm.user_message("go")], turn)
    assert out[-1] == {"role": "assistant", "content": [{"type": "text", "text": "All done."}]}


@pytest.mark.parametrize("stop, kind", [("refusal", "refusal"), ("max_tokens", "max_tokens")])
def test_chat_tools_bad_stop_raises(fake_anthropic, stop, kind):
    fake_anthropic(response([ToolUseBlock(type="tool_use", id="t", name="click", input={})], stop_reason=stop))
    with pytest.raises(llm.LLMError) as err:
        llm.chat_tools(None, [llm.user_message("go")], TOOLS)
    assert err.value.kind == kind


async def test_achat_tools(fake_anthropic):
    holder = fake_anthropic(tool_turn_response())
    turn = await llm.achat_tools(None, [llm.user_message("go")], TOOLS)
    assert [c["id"] for c in turn["tool_calls"]] == ["toolu_1", "toolu_2"]
    assert holder["async"].messages.calls and not holder["sync"].messages.calls
    assert_no_sampling(holder["async"].messages.calls[0])


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------


def openai_response(content=None, tool_calls=None, finish="stop", model="gpt-4o-2024-08-06", refusal=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls, refusal=refusal)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=100_000),
        model=model,
    )


class FakeOpenAI:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeMessages(responses))


def test_openai_complete_json_keeps_json_mode(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    client = FakeOpenAI([openai_response('{"success": true}')])
    monkeypatch.setattr(llm, "_openai_client", lambda: client)
    result = llm.complete_json("sys", "judge", JUDGE_SCHEMA)
    (call,) = client.chat.completions.calls
    assert call["model"] == "gpt-4o"
    assert call["response_format"] == {"type": "json_object"}
    assert call["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "judge"}]
    assert_no_sampling(call)
    assert result == {"success": True}
    assert result.usage.input_tokens == 1_000_000
    assert result.cost_usd is None  # dated model id has no price entry


def test_openai_chat_tools_normalization(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="click", arguments='{"selector": "#a"}'))
    client = FakeOpenAI([openai_response(None, tool_calls=[call], finish="tool_calls", model="gpt-4o")])
    monkeypatch.setattr(llm, "_openai_client", lambda: client)
    turn = llm.chat_tools("sys", [llm.user_message("go")], TOOLS, parallel_tool_calls=False)

    sent = client.chat.completions.calls[0]
    assert sent["tools"][0] == {"type": "function", "function": {
        "name": "click", "description": "Click an element", "parameters": TOOLS[0]["input_schema"]}}
    assert sent["parallel_tool_calls"] is False
    assert turn["tool_calls"] == [{"id": "call_1", "name": "click", "input": {"selector": "#a"}}]
    assert turn["stop_reason"] == "tool_use" and turn["provider"] == "openai"
    assert turn["cost_usd"] == pytest.approx(2.50 + 1.00)

    out = llm.append_tool_results([llm.user_message("go")], turn, [llm.tool_result("call_1", "boom", is_error=True)])
    assert out[1]["tool_calls"][0]["function"]["name"] == "click"
    assert out[2] == {"role": "tool", "tool_call_id": "call_1", "content": "ERROR: boom"}


def test_openai_refusal_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setattr(llm, "_openai_client", lambda: FakeOpenAI([openai_response(None, refusal="no")]))
    with pytest.raises(llm.LLMError) as err:
        llm.complete_json(None, "p")
    assert err.value.kind == "refusal"


def test_openai_missing_package_is_a_config_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setitem(sys.modules, "openai", None)  # makes `import openai` raise ImportError
    with pytest.raises(llm.LLMError) as err:
        llm.complete_json(None, "p")
    assert err.value.kind == "config" and "--extra openai" in str(err.value)


def test_anthropic_mode_never_needs_openai(monkeypatch, fake_anthropic):
    monkeypatch.setitem(sys.modules, "openai", None)  # any `import openai` would now fail
    fake_anthropic(response([text_block("{}")]), tool_turn_response())
    assert llm.complete_json(None, "p") == {}
    assert llm.chat_tools(None, [llm.user_message("go")], TOOLS)["tool_calls"]


def test_importing_the_layer_does_not_import_openai():
    code = (
        "import sys; import llm, browser_env, constants, runtime_env; "
        "llm.describe(); llm.agent_llm(); "
        "print('openai' in sys.modules)"
    )
    env = {k: v for k, v in __import__("os").environ.items() if k not in ("LLM_PROVIDER",)}
    out = subprocess.run([sys.executable, "-c", code], cwd=SERVER_DIR, capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "False"


# ---------------------------------------------------------------------------
# agent_llm (browser-use chat model)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"])
def test_agent_llm_current_claude(model):
    from browser_use import ChatAnthropic

    chat = llm.agent_llm(model)
    assert type(chat).__name__ == "ClaudeAgentChat"  # the agent_llm.py adapter
    assert isinstance(chat, ChatAnthropic)
    assert chat.model == model
    assert chat.temperature is None and chat.top_p is None and chat.seed is None
    assert chat.thinking == {"type": "adaptive"}
    # adaptive thinking is what makes browser-use send tool_choice auto, not a forced tool
    assert chat._requires_auto_tool_choice() is True
    params = chat._get_client_params_for_invoke()
    assert_no_sampling(params)
    assert params["extra_body"]["output_config"] == {"effort": "medium"}


def test_agent_llm_fallback_only_where_accepted():
    sonnet = llm.agent_llm("claude-sonnet-5-5")
    assert sonnet.fallbacks == "default"
    assert sonnet._get_betas_for_invoke() == ["server-side-fallback-2026-07-01"]
    haiku = llm.agent_llm("claude-haiku-5-5")
    assert haiku.fallbacks is None
    assert haiku._get_betas_for_invoke() is None


def test_agent_llm_uses_role_model_and_effort_env(monkeypatch):
    monkeypatch.setenv("BENCHMARK_AGENT_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("BENCHMARK_AGENT_EFFORT", "low")
    chat = llm.agent_llm()
    assert chat.model == "claude-haiku-5-5"
    assert chat.output_config == {"effort": "low"}


def test_agent_llm_older_claude_gets_no_thinking_or_effort():
    chat = llm.agent_llm("claude-haiku-4-5")
    assert chat.thinking is None and chat.output_config is None


def test_agent_llm_without_structured_outputs_uses_builtin():
    # claude-sonnet-4-6 has adaptive thinking but is not on the structured-outputs list.
    chat = llm.agent_llm("claude-sonnet-4-6")
    assert type(chat).__name__ == "ChatAnthropic"
    assert chat.thinking == {"type": "adaptive"} and chat._requires_auto_tool_choice()


def test_agent_llm_openai(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    chat = llm.agent_llm()
    assert type(chat).__name__ == "ChatOpenAI" and chat.model == "gpt-4o"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_parse_json_object_variants():
    assert llm.parse_json_object('{"a": 1}') == {"a": 1}
    assert llm.parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.parse_json_object('Sure! {"a": {"b": 2}} Hope that helps.') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        llm.parse_json_object("[1, 2]")


def test_strict_schema_accepts_pydantic_models():
    from pydantic import BaseModel

    class Verdict(BaseModel):
        verdict: str
        reasoning: str

    schema = llm.strict_schema(Verdict)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"verdict", "reasoning"}


def test_usage_from_browser_use_summary():
    # numbers from the 2026-10-24 sonnet smoke run (history.usage)
    summary = SimpleNamespace(
        total_prompt_tokens=57696, total_prompt_cached_tokens=43599,
        total_prompt_cache_creation_tokens=14533, total_completion_tokens=987,
    )
    usage = llm.usage_from_browser_use(summary)
    assert usage == llm.Usage(input_tokens=14097, output_tokens=987,
                              cache_read_input_tokens=43599, cache_creation_input_tokens=14533)
    expected = (14097 * 2.00 + 987 * 10.00 + 43599 * 0.20 + 14533 * 2.50) / 1e6
    assert usage.cost_usd("claude-sonnet-5-5") == pytest.approx(expected)
    assert llm.usage_from_browser_use(None) == llm.Usage()


def test_usage_addition():
    total = llm.Usage(1, 2, 3, 4) + llm.Usage(10, 20, 30, 40)
    assert total == llm.Usage(11, 22, 33, 44)
    assert total.total_tokens == 110
