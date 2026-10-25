"""Unit tests for agent_llm.ClaudeAgentChat (the browser-use adapter). No network."""

from types import SimpleNamespace

import httpx2
import pytest
from anthropic import BadRequestError
from anthropic.types import RefusalStopDetails, TextBlock, ThinkingBlock, ToolUseBlock
from pydantic import BaseModel

import agent_llm
import llm
from agent_llm import ClaudeAgentChat, ModelRefusalError, fits_structured_outputs, step_schema
from browser_use.llm.exceptions import ModelOutputTruncatedError, ModelProviderError
from browser_use.llm.messages import SystemMessage, UserMessage

SAMPLING = {"temperature", "top_p", "top_k", "seed"}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("LLM_PROVIDER", "LLM_FALLBACKS", *llm.ROLE_MODEL_ENV.values(), *llm.ROLE_EFFORT_ENV.values()):
        monkeypatch.delenv(key, raising=False)
    ClaudeAgentChat._grammar_too_large.clear()
    yield
    ClaudeAgentChat._grammar_too_large.clear()


class Action(BaseModel):
    navigate: str


class Step(BaseModel):
    next_goal: str
    action: list[Action]


GOOD = {"next_goal": "open it", "action": [{"navigate": "https://example.com"}]}
FLATTENED = {"next_goal": "open it", "url": "https://example.com"}  # the observed failure mode


def usage_ns(input_tokens=1200, output_tokens=80):
    return SimpleNamespace(
        input_tokens=input_tokens, output_tokens=output_tokens, cache_read_input_tokens=0,
        cache_creation_input_tokens=0, cache_creation=None,
    )


def text_response(text, stop_reason="end_turn", stop_details=None):
    return SimpleNamespace(
        content=[ThinkingBlock(type="thinking", thinking="", signature="s"), TextBlock(type="text", text=text, citations=None)],
        stop_reason=stop_reason, stop_details=stop_details, model="claude-sonnet-5-5", usage=usage_ns(),
    )


def tool_response(tool_input, tool_id="toolu_1", name="Step", stop_reason="tool_use", output_tokens=80):
    return SimpleNamespace(
        content=[
            ThinkingBlock(type="thinking", thinking="", signature="sig-" + tool_id),
            ToolUseBlock(type="tool_use", id=tool_id, name=name, input=tool_input),
        ],
        stop_reason=stop_reason, stop_details=None, model="claude-sonnet-5-5", usage=usage_ns(output_tokens=output_tokens),
    )


def grammar_error():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return BadRequestError(
        "The compiled grammar is too large, which would cause performance issues.",
        response=httpx2.Response(400, request=request), body=None,
    )


@pytest.fixture
def chat_with(monkeypatch):
    def make(*responses, model="claude-sonnet-5-5"):
        chat = llm.agent_llm(model)
        assert isinstance(chat, ClaudeAgentChat)
        calls = []
        queue = list(responses)

        async def create(**params):
            calls.append(params)
            item = queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        monkeypatch.setattr(chat, "_create_message", create)
        return chat, calls

    return make


@pytest.fixture
def large_schemas(monkeypatch):
    """Treat every schema as too large for structured outputs (like the real AgentOutput)."""
    monkeypatch.setattr(agent_llm, "STRUCTURED_MAX_BYTES", 10)


MESSAGES = [SystemMessage(content="You are a browser agent."), UserMessage(content="Open example.com")]


def assert_clean(params):
    assert not (SAMPLING & set(params))
    assert "tool_choice" not in params or params["tool_choice"] == {"type": "auto"}
    assert params["messages"][-1]["role"] == "user"  # never an assistant prefill


# -- structured outputs path (small schemas) -----------------------------------


async def test_small_schema_uses_structured_outputs(chat_with):
    chat, calls = chat_with(text_response('{"next_goal": "open it", "action": [{"navigate": "https://example.com"}]}'))
    result = await chat.ainvoke(MESSAGES, Step)

    assert result.completion == Step(**GOOD)
    assert result.usage.completion_tokens == 80
    (params,) = calls
    assert_clean(params)
    assert "tools" not in params and "tool_choice" not in params
    fmt = params["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
    assert params["output_config"]["effort"] == "medium"
    assert "output_config" not in (params.get("extra_body") or {})  # sent once, as the typed param
    assert params["extra_body"]["fallbacks"] == "default"
    assert params["betas"] == ["server-side-fallback-2026-07-01"]
    assert params["thinking"] == {"type": "adaptive"}


async def test_haiku_has_no_fallback(chat_with):
    chat, calls = chat_with(text_response('{"next_goal": "g", "action": []}'), model="claude-haiku-5-5")
    await chat.ainvoke(MESSAGES, Step)
    assert "betas" not in calls[0]
    assert "fallbacks" not in (calls[0].get("extra_body") or {})


async def test_grammar_too_large_falls_back_to_tool_and_is_remembered(chat_with):
    chat, calls = chat_with(grammar_error(), tool_response(GOOD), tool_response(GOOD, tool_id="toolu_2"))
    first = await chat.ainvoke(MESSAGES, Step)
    assert first.completion == Step(**GOOD)
    assert "output_config" in calls[0] and "format" in calls[0]["output_config"]
    assert calls[1]["tools"][0]["name"] == "Step"
    second = await chat.ainvoke(MESSAGES, Step)  # goes straight to the tool path now
    assert second.completion == Step(**GOOD)
    assert len(calls) == 3 and "tools" in calls[2]


async def test_other_bad_request_is_a_provider_error(chat_with):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    err = BadRequestError("max_tokens: too large", response=httpx2.Response(400, request=request), body=None)
    chat, _ = chat_with(err)
    with pytest.raises(ModelProviderError):
        await chat.ainvoke(MESSAGES, Step)


@pytest.mark.parametrize("path", ["structured", "tool"])
async def test_refusal_raises(chat_with, monkeypatch, path):
    if path == "tool":
        monkeypatch.setattr(agent_llm, "STRUCTURED_MAX_BYTES", 10)
    resp = text_response("", stop_reason="refusal",
                         stop_details=RefusalStopDetails(type="refusal", category="cyber", explanation=None))
    chat, _ = chat_with(resp)
    with pytest.raises(ModelRefusalError) as err:
        await chat.ainvoke(MESSAGES, Step)
    assert err.value.category == "cyber"


@pytest.mark.parametrize("path", ["structured", "tool"])
async def test_max_tokens_raises(chat_with, monkeypatch, path):
    if path == "tool":
        monkeypatch.setattr(agent_llm, "STRUCTURED_MAX_BYTES", 10)
    chat, _ = chat_with(text_response('{"next_goal": "ope', stop_reason="max_tokens"))
    with pytest.raises(ModelOutputTruncatedError):
        await chat.ainvoke(MESSAGES, Step)


async def test_structured_output_that_fails_validation_raises(chat_with):
    chat, _ = chat_with(text_response('{"next_goal": 5}'))
    with pytest.raises(ModelProviderError, match="did not validate"):
        await chat.ainvoke(MESSAGES, Step)


# -- tool path (large schemas) --------------------------------------------------


async def test_large_schema_uses_auto_tool_call(chat_with, large_schemas):
    chat, calls = chat_with(tool_response(GOOD))
    result = await chat.ainvoke(MESSAGES, Step)
    assert result.completion == Step(**GOOD)
    assert chat.repairs == 0
    (params,) = calls
    assert_clean(params)
    assert params["tool_choice"] == {"type": "auto"}
    assert params["tools"][0]["name"] == "Step"
    assert "Never put action parameters at the top level" in params["tools"][0]["description"]
    assert params["output_config"] == {"effort": "medium"}  # effort, but no output format
    assert "format" not in params["output_config"]


async def test_malformed_tool_input_is_repaired_and_both_calls_are_counted(chat_with, large_schemas):
    chat, calls = chat_with(
        tool_response(FLATTENED, tool_id="toolu_bad", output_tokens=70),
        tool_response(GOOD, tool_id="toolu_good", output_tokens=90),
    )
    result = await chat.ainvoke(MESSAGES, Step)

    assert result.completion == Step(**GOOD)
    assert chat.repairs == 1
    assert result.usage.completion_tokens == 70 + 90
    assert result.usage.prompt_tokens == 1200 * 2
    assert len(calls) == 2
    first, second = calls
    assert len(second["messages"]) == len(first["messages"]) + 2  # append-only
    assert second["messages"][: len(first["messages"])] == first["messages"]
    assistant, feedback = second["messages"][-2:]
    assert assistant["role"] == "assistant"
    assert [b.type for b in assistant["content"]] == ["thinking", "tool_use"]  # turn kept verbatim
    assert feedback["role"] == "user"
    (block,) = feedback["content"]
    assert block["type"] == "tool_result" and block["tool_use_id"] == "toolu_bad" and block["is_error"] is True
    assert "action" in block["content"] and "did not match" in block["content"]
    assert_clean(second)


async def test_text_reply_without_tool_call_is_parsed(chat_with, large_schemas):
    chat, calls = chat_with(text_response('{"next_goal": "open it", "action": [{"navigate": "https://example.com"}]}'))
    result = await chat.ainvoke(MESSAGES, Step)
    assert result.completion == Step(**GOOD) and len(calls) == 1


async def test_text_reply_without_json_gets_a_nudge(chat_with, large_schemas):
    chat, calls = chat_with(text_response("Let me think about the page first."), tool_response(GOOD))
    result = await chat.ainvoke(MESSAGES, Step)
    assert result.completion == Step(**GOOD)
    nudge = calls[1]["messages"][-1]
    assert nudge["role"] == "user" and nudge["content"][0]["type"] == "text"
    assert "Step tool" in nudge["content"][0]["text"]


async def test_gives_up_after_max_repairs(chat_with, large_schemas):
    chat, calls = chat_with(*(tool_response(FLATTENED, tool_id=f"t{i}") for i in range(3)))
    with pytest.raises(ModelProviderError, match="after 3 attempts"):
        await chat.ainvoke(MESSAGES, Step)
    assert len(calls) == 1 + chat.max_repairs
    assert chat.repairs == chat.max_repairs  # the last failure is not sent back


async def test_plain_text_calls_use_the_parent_path(chat_with):
    chat, calls = chat_with(text_response("just text"))
    result = await chat.ainvoke(MESSAGES)
    assert result.completion == "just text"
    assert "output_config" not in calls[0]  # parent sends effort via extra_body
    assert calls[0]["extra_body"]["output_config"] == {"effort": "medium"}


def test_schema_helpers():
    schema = step_schema(Step)
    assert schema["additionalProperties"] is False and "title" not in schema
    assert fits_structured_outputs(schema)
    assert not fits_structured_outputs({"description": "x" * 5000})
