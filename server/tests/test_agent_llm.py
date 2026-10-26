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


# Structured outputs path (small schemas)


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


# Tool path (large schemas)


async def test_large_schema_uses_auto_tool_call(chat_with, large_schemas):
    chat, calls = chat_with(tool_response(GOOD))
    result = await chat.ainvoke(MESSAGES, Step)
    assert result.completion == Step(**GOOD)
    assert chat.repairs == 0
    (params,) = calls
    assert_clean(params)
    assert params["tool_choice"] == {"type": "auto"}
    # Step's action parameter is a plain str, so it cannot be offered per action: one step tool.
    assert [t["name"] for t in params["tools"]] == ["Step"]
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


# Actions called as tools (browser-use's real AgentOutput)


@pytest.fixture(scope="module")
def agent_output():
    """browser-use 0.13's AgentOutput over its default actions, as Agent builds it."""
    from browser_use.agent.views import AgentOutput
    from browser_use.tools.service import Tools

    return AgentOutput.type_with_custom_actions(Tools().registry.create_action_model())


def reply(*blocks, stop_reason="tool_use", output_tokens=80):
    return SimpleNamespace(
        content=[ThinkingBlock(type="thinking", thinking="", signature="sig"), *blocks],
        stop_reason=stop_reason, stop_details=None, model="claude-sonnet-5-5", usage=usage_ns(output_tokens=output_tokens),
    )


def call(name, tool_input, tool_id="toolu_1"):
    return ToolUseBlock(type="tool_use", id=tool_id, name=name, input=tool_input)


def actions_of(step):
    return [a.model_dump(exclude_none=True) for a in step.action]


# The exact inputs claude-sonnet-5-5 sent when offered only the AgentOutput tool (recorded from a
# live call): the action as the tool, no step fields, JSON as text.
FIND_H1 = {"selector": "h1", "attributes": "[]", "max_results": "5", "include_text": "true"}
DONE_H1 = {"text": "The page's H1 heading reads: \"Quarterly Lantern Report 7F3A\".", "success": "true",
           "files_to_display": "[]"}
STEP = {"thinking": "Check the heading.", "evaluation_previous_goal": "Page loaded. Verdict: Success",
        "memory": "On the report page.", "next_goal": "Read the h1.", "current_plan_item": None, "plan_update": None}


def test_action_models_come_from_the_step_model(agent_output):
    actions = agent_llm.action_models(agent_output)
    assert {"navigate", "click", "input", "find_elements", "done", "extract"} <= set(actions)
    assert set(agent_llm.action_models(Step)) == {"navigate"}
    assert agent_llm.action_models(Action) == {}  # no action list
    assert all(len(model.model_fields) == 1 for model in actions.values())


def test_each_action_is_offered_as_a_tool_that_carries_the_step(agent_output):
    tools = agent_llm.action_tools(agent_output)
    assert [t["name"] for t in tools] == list(agent_llm.action_models(agent_output))
    step = agent_llm.optimized_schema(agent_output)
    assert "thinking" in step["properties"] and "thinking" in step["required"]  # browser-use asks for it...
    step_fields = [k for k in step["properties"] if k not in ("action", "thinking")]
    for tool in tools:
        schema = tool["input_schema"]
        params = agent_llm.optimized_schema(agent_llm.action_models(agent_output)[tool["name"]])["properties"][tool["name"]]
        assert list(schema["properties"]) == step_fields + list(params.get("properties") or {})  # step fields first
        assert schema["required"] == [k for k in step["required"] if k not in ("action", "thinking")] + list(
            params.get("required") or [])
        assert "thinking" not in schema["properties"]  # ...the action tools do not
        assert schema["additionalProperties"] is False
        # browser-use's nullable step fields, written compactly (same schema, fewer tokens)
        assert step["properties"]["memory"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
        assert schema["properties"]["memory"] == {"type": ["string", "null"]}
        assert schema["properties"]["plan_update"] == {"items": {"type": "string"}, "type": ["array", "null"]}
        assert agent_llm.ACTION_TOOL_NOTE in tool["description"]
    click = next(t for t in tools if t["name"] == "click")
    assert click["description"].startswith("Click element by index.")
    assert [("cache_control" in t) for t in tools] == [False] * (len(tools) - 1) + [True]
    assert agent_llm.action_tools(Step) is None  # str parameters: the single step tool is used


def test_compact_nullable_only_rewrites_the_plain_nullable_shape():
    c = agent_llm._compact_nullable
    assert c({"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None}) == {"type": ["integer", "null"]}
    kept = [
        {"anyOf": [{"type": "string"}, {"type": "null"}], "default": "x"},  # a real default
        {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "d"},  # extra keys
        {"anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}]},  # constrained branch
        {"anyOf": [{"type": "string"}, {"type": "integer"}]},  # not nullable
        {"type": "string"},
    ]
    for prop in kept:
        assert c(prop) is prop


def test_action_tools_follow_the_step_model_variant(agent_output):
    from browser_use.agent.views import AgentOutput
    from browser_use.tools.service import Tools

    no_thinking = AgentOutput.type_with_custom_actions_no_thinking(Tools().registry.create_action_model())
    (click,) = [t for t in agent_llm.action_tools(no_thinking) if t["name"] == "click"]
    assert "thinking" not in click["input_schema"]["properties"]
    assert "memory" in click["input_schema"]["required"]
    # With browser-use's default use_thinking=True the action tools are the same.
    assert agent_llm.action_tools(no_thinking) == agent_llm.action_tools(agent_output)


def test_no_action_tool_asks_for_written_reasoning(agent_output):
    assert agent_llm.ACTION_TOOL_OMITTED_FIELDS == {"thinking"}
    for tool in agent_llm.action_tools(agent_output):
        props, required = tool["input_schema"]["properties"], tool["input_schema"]["required"]
        assert "thinking" not in props and "thinking" not in required
        assert {"evaluation_previous_goal", "memory", "next_goal"} <= set(required)  # the fed-back fields stay
        assert "thinking" not in tool["description"]
    assert agent_output.model_fields["thinking"].is_required() is False  # a step without it validates


async def test_step_without_thinking_is_one_request(chat_with, agent_output):
    step_only = {k: v for k, v in STEP.items() if k != "thinking"}
    chat, calls = chat_with(reply(call("click", {**step_only, "index": 4})))
    result = await chat.ainvoke(MESSAGES, agent_output)
    assert len(calls) == 1 and chat.repairs == 0
    assert result.completion.thinking is None
    assert (result.completion.memory, result.completion.next_goal) == (STEP["memory"], STEP["next_goal"])
    assert all("thinking" not in t["input_schema"]["properties"] for t in calls[0]["tools"])


async def test_action_tool_call_is_one_request_with_the_step_fields(chat_with, agent_output):
    # STEP still carries "thinking" (browser-use's prompt asks for it): it is accepted and kept.
    chat, calls = chat_with(reply(call("find_elements", {**STEP, "selector": "h1", "attributes": None,
                                                         "max_results": 5, "include_text": True})))
    result = await chat.ainvoke(MESSAGES, agent_output)

    assert len(calls) == 1
    assert chat.repairs == 0 and chat.conversions == 1
    step = result.completion
    assert actions_of(step) == [{"find_elements": {"selector": "h1", "max_results": 5, "include_text": True}}]
    assert (step.thinking, step.evaluation_previous_goal, step.memory, step.next_goal) == (
        STEP["thinking"], STEP["evaluation_previous_goal"], STEP["memory"], STEP["next_goal"])
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (1200, 80)  # counted once
    (params,) = calls
    assert_clean(params)
    assert [t["name"] for t in params["tools"]] == list(agent_llm.action_models(agent_output))
    assert "AgentOutput" not in {t["name"] for t in params["tools"]}
    assert params["tool_choice"] == {"type": "auto"}


async def test_bare_action_call_as_observed_is_still_one_request(chat_with, agent_output):
    chat, calls = chat_with(reply(call("find_elements", FIND_H1)))
    result = await chat.ainvoke(MESSAGES, agent_output)
    assert len(calls) == 1 and chat.repairs == 0 and chat.conversions == 1
    assert actions_of(result.completion) == [
        {"find_elements": {"selector": "h1", "attributes": [], "max_results": 5, "include_text": True}}
    ]
    assert result.completion.memory is None and result.completion.next_goal is None  # nothing invented


async def test_done_called_as_a_tool_finishes_the_step(chat_with, agent_output):
    chat, calls = chat_with(reply(call("done", DONE_H1)))
    result = await chat.ainvoke(MESSAGES, agent_output)
    assert len(calls) == 1 and chat.repairs == 0
    (done,) = actions_of(result.completion)
    assert done == {"done": {"text": DONE_H1["text"], "success": True, "files_to_display": []}}


async def test_several_action_calls_become_one_step_in_order(chat_with, agent_output):
    nulls = dict.fromkeys(STEP)
    chat, calls = chat_with(reply(
        call("input", {**STEP, "index": "4", "text": "5", "clear": "true"}, "t1"),
        call("click", {**nulls, "index": 9}, "t2"),
    ))
    result = await chat.ainvoke(MESSAGES, agent_output)

    assert len(calls) == 1 and chat.conversions == 1
    assert actions_of(result.completion) == [
        {"input": {"index": 4, "text": "5", "clear": True}},  # the text "5" stays a string
        {"click": {"index": 9}},
    ]
    assert result.completion.memory == STEP["memory"]  # the nulls on the second call do not win


async def test_step_fields_come_from_whichever_call_has_them(chat_with, agent_output):
    text = TextBlock(type="text", text="Search for the blue lamp, then open the first result.", citations=None)
    chat, _ = chat_with(reply(
        text,
        call("input", {"index": 4, "text": "blue lamp", "memory": None}, "t1"),
        call("click", {"index": 9, "memory": "Search box is element 4."}, "t2"),
    ))
    result = await chat.ainvoke(MESSAGES, agent_output)
    assert result.completion.memory == "Search box is element 4."
    assert result.completion.next_goal == text.text  # no next_goal given: the reply's own words


async def test_action_call_that_does_not_validate_falls_back_to_repair(chat_with, agent_output):
    good = {"evaluation_previous_goal": "ok", "memory": "m", "next_goal": "g",
            "action": [{"click": {"index": 3}}]}
    chat, calls = chat_with(
        reply(call("click", {"index": "the blue button"}, "toolu_bad"), output_tokens=70),
        reply(call("AgentOutput", good, "toolu_good"), output_tokens=90),
    )
    result = await chat.ainvoke(MESSAGES, agent_output)

    assert actions_of(result.completion) == [{"click": {"index": 3}}]
    assert len(calls) == 2 and chat.repairs == 1 and chat.conversions == 0
    assert result.usage.completion_tokens == 70 + 90 and result.usage.prompt_tokens == 2400
    first, second = calls
    assert second["messages"][: len(first["messages"])] == first["messages"]  # append-only
    assistant, feedback = second["messages"][-2:]
    assert [b.type for b in assistant["content"]] == ["thinking", "tool_use"]  # turn kept verbatim
    (block,) = feedback["content"]
    assert block["tool_use_id"] == "toolu_bad" and block["is_error"] is True
    assert block["content"].startswith("This step did not validate") and "index" in block["content"]
    assert "Call the tool named after the action" in block["content"]
    assert_clean(second)


async def test_unknown_tool_name_still_gets_a_repair(chat_with, agent_output):
    chat, calls = chat_with(
        reply(call("open_page", {"url": "https://example.com"}, "toolu_x")),
        reply(call("AgentOutput", {"action": [{"navigate": {"url": "https://example.com"}}]}, "toolu_y")),
    )
    result = await chat.ainvoke(MESSAGES, agent_output)
    assert actions_of(result.completion) == [{"navigate": {"url": "https://example.com", "new_tab": False}}]
    assert len(calls) == 2 and chat.repairs == 1 and chat.conversions == 0
    (block,) = calls[1]["messages"][-1]["content"]
    assert block["content"].startswith("Unknown tool 'open_page'. Call the tool named after the action")


async def test_action_call_next_to_a_broken_step_call_is_repaired(chat_with, agent_output):
    """Mixed replies are not guessed at, and every tool call gets its own tool_result."""
    chat, calls = chat_with(
        reply(call("AgentOutput", {"memory": "m", "url": "https://example.com"}, "t1"), call("click", {"index": 2}, "t2")),
        reply(call("AgentOutput", {"action": [{"click": {"index": 2}}]}, "t3")),
    )
    await chat.ainvoke(MESSAGES, agent_output)
    assert len(calls) == 2 and chat.repairs == 1
    results = calls[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert "did not match" in results[0]["content"] and results[1]["content"].startswith("Not run")


async def test_step_call_with_one_action_object_instead_of_a_list_is_converted(chat_with, agent_output):
    chat, calls = chat_with(reply(call("AgentOutput", {"memory": "m", "next_goal": "g", "action": {"click": {"index": 3}}})))
    result = await chat.ainvoke(MESSAGES, agent_output)
    assert len(calls) == 1 and chat.repairs == 0 and chat.conversions == 1
    assert actions_of(result.completion) == [{"click": {"index": 3}}]
    assert result.completion.memory == "m"


async def test_valid_step_call_is_not_counted_as_a_conversion(chat_with, agent_output):
    chat, calls = chat_with(reply(call("AgentOutput", {"memory": "m", "action": [{"click": {"index": 3}}]})))
    await chat.ainvoke(MESSAGES, agent_output)
    assert len(calls) == 1 and chat.repairs == 0 and chat.conversions == 0


async def test_reply_without_a_call_is_nudged_toward_the_action_tools(chat_with, agent_output):
    chat, calls = chat_with(
        reply(TextBlock(type="text", text="Let me look at the page first.", citations=None), stop_reason="end_turn"),
        reply(call("click", {**STEP, "index": 2})),
    )
    result = await chat.ainvoke(MESSAGES, agent_output)
    assert actions_of(result.completion) == [{"click": {"index": 2}}]
    assert len(calls) == 2 and chat.repairs == 1
    nudge = calls[1]["messages"][-1]["content"][0]
    assert nudge == {"type": "text", "text": "Reply by calling one of the action tools with your next step."}


async def test_refusal_on_an_action_call_still_raises(chat_with, agent_output):
    refused = reply(call("click", {"index": 1}), stop_reason="refusal")
    refused.stop_details = RefusalStopDetails(type="refusal", category="cyber", explanation=None)
    chat, _ = chat_with(refused)
    with pytest.raises(ModelRefusalError):
        await chat.ainvoke(MESSAGES, agent_output)
    assert chat.conversions == 0


def test_conversion_decodes_only_what_failed(agent_output):
    step = agent_llm.step_from_action_calls(
        [("scroll", {"down": "true", "pages": "2", "index": "null"}), ("send_keys", {"keys": "null"})], agent_output
    )
    # "null" becomes None only where None is allowed; a plain string field keeps the text.
    assert actions_of(step) == [{"scroll": {"down": True, "pages": 2.0}}, {"send_keys": {"keys": "null"}}]


def test_conversion_keeps_the_action_when_a_step_field_is_unusable(agent_output):
    step = agent_llm.step_from_action_calls(
        [("click", {"index": 1, "plan_update": "first this; then that", "current_plan_item": "1"})], agent_output
    )
    assert actions_of(step) == [{"click": {"index": 1}}]
    assert step.plan_update is None and step.current_plan_item == 1


def test_conversion_refuses_what_it_cannot_map(agent_output):
    with pytest.raises(ValueError, match="not an available action"):
        agent_llm.step_from_action_calls([("frobnicate", {})], agent_output)
    with pytest.raises(Exception):
        agent_llm.step_from_action_calls([("click", {})], agent_output)  # required index missing
    with pytest.raises(ValueError, match="unexpected top-level keys"):
        agent_llm.step_from_misplaced_actions({"next_goal": "g", "url": "https://example.com"}, agent_output)
    with pytest.raises(ValueError, match="both inside and outside"):
        agent_llm.step_from_misplaced_actions(
            {"action": [{"click": {"index": 1}}], "navigate": {"url": "https://example.com"}}, agent_output
        )
    with pytest.raises(ValueError, match="no action"):
        agent_llm.step_from_misplaced_actions({"memory": "m", "action": []}, agent_output)
