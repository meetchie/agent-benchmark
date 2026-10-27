"""The arena's Rindler arm: model loop over the local host, with a fake host and a scripted model."""

from __future__ import annotations

import json

import pytest

import llm
from adapters import rindler_agent
from adapters.rindler_agent import DONE_TOOL, MAX_RESULT_CHARS, RindlerTelemetricAgent, with_cache_breakpoint
from rindler_local import build_tools, load_mapping, text_result

from tests.fixture_shop import MAPPING_PATH


class FakeHost:
    def __init__(self, mapping, responses=None):
        self.mapping = mapping
        self.calls = []
        self.closed = False
        self.responses = responses or {}

    async def list_tools(self):
        return build_tools(self.mapping)

    async def call_tool(self, name, args):
        self.calls.append((name, dict(args)))
        payload = self.responses.get(name) or {
            "screen": "landing" if name == "start_session" else "search_results",
            "context": {},
            "data": {"page_url": "http://127.0.0.1/", "session_id": "s-1"} if name == "start_session" else {"page_url": "x"},
            "available_actions": ["search_products"],
            "global_actions": ["start_session"],
        }
        return text_result(payload, is_error="error" in payload)

    async def close(self):
        self.closed = True


def turn(*, calls=(), text="", usage=None, model="claude-sonnet-5-5"):
    usage = usage or {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50, "cache_creation_input_tokens": 10}
    content = ([{"type": "text", "text": text}] if text else []) + [
        {"type": "tool_use", "id": c[0], "name": c[1], "input": c[2]} for c in calls
    ]
    u = llm.Usage(**usage)
    return {
        "text": text,
        "tool_calls": [{"id": c[0], "name": c[1], "input": c[2]} for c in calls],
        "stop_reason": "tool_use" if calls else "end_turn",
        "usage": u.to_dict(),
        "model": model,
        "cost_usd": u.cost_usd(model),
        "provider": "anthropic",
        "assistant_message": {"role": "assistant", "content": content},
    }


@pytest.fixture
def mapping():
    return load_mapping(MAPPING_PATH)


def scripted(monkeypatch, turns):
    seen = []

    async def fake_achat_tools(system, messages, tools, **kwargs):
        seen.append({"system": system, "messages": json.loads(json.dumps(messages)), "tools": tools, **kwargs})
        item = turns.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(llm, "achat_tools", fake_achat_tools)
    return seen


def make_agent(mapping, hosts, **kwargs):
    def factory(m):
        host = FakeHost(m, kwargs.pop("responses", None))
        hosts.append(host)
        return host

    return RindlerTelemetricAgent(run_id="r1", goal="Find a chain belt", mapping=mapping, host_factory=factory,
                                  max_steps=kwargs.get("max_steps", 30))


async def test_loop_runs_tools_until_done(monkeypatch, mapping):
    big = "x" * (MAX_RESULT_CHARS + 500)
    turns = [
        turn(calls=[("t1", "search_products", {"query": "chain belt"})]),
        turn(text="Thinking about it."),
        turn(calls=[("t3", "done", {"success": True, "message": "Iron Chain Belt, $29.00"})]),
    ]
    seen = scripted(monkeypatch, turns)
    hosts = []
    agent = make_agent(mapping, hosts)
    hosts_responses = {"search_products": {"screen": "search_results", "context": {}, "data": {"blob": big},
                                           "available_actions": [], "global_actions": []}}

    def factory(m):
        host = FakeHost(m, hosts_responses)
        hosts.append(host)
        return host

    agent._host_factory = factory
    result = await agent.run(start_url="http://127.0.0.1:9/")

    assert result["success"] is True
    assert result["final_extraction"] == "Iron Chain Belt, $29.00"
    assert result["steps"] == 3 and result["llm_calls"] == 3
    host = hosts[0]
    assert host.calls == [("start_session", {"url": "http://127.0.0.1:9/"}), ("search_products", {"query": "chain belt"})]
    assert host.closed

    # What the model was given.
    first = seen[0]
    assert "Rindler" in first["system"]
    names = [t["name"] for t in first["tools"]]
    assert "done" in names and "start_session" not in names and "close_session" not in names
    assert first["tools"][-1] == DONE_TOOL
    assert first["parallel_tool_calls"] is False and first["model"] == agent.model and first["role"] == "agent"
    assert "Goal: Find a chain belt" in first["messages"][0]["content"][0]["text"]
    assert first["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}

    # Turn 2 saw the truncated tool result; only the newest block carries the cache marker.
    second = seen[1]["messages"]
    tool_block = second[-1]["content"][0]
    assert tool_block["type"] == "tool_result" and tool_block["tool_use_id"] == "t1"
    assert tool_block["content"].endswith("... [truncated]")
    assert len(tool_block["content"]) == MAX_RESULT_CHARS + len("\n... [truncated]")
    assert "cache_control" not in json.dumps(second[:-1])
    # Turn 3 saw the text-only turn followed by a nudge.
    third = seen[2]["messages"]
    assert third[-2]["role"] == "assistant" and third[-1]["content"][-1]["text"] == rindler_agent.NUDGE

    # Telemetry: one step per model turn, prompt tokens include cache reads and writes.
    ends = [e for e in agent.telemetry_events if e["event_type"] == "step_end"]
    assert [e["action_type"] for e in ends] == ["search_products", "no_tool_call", "done"]
    # Each call's input is logged with it; the judge reads it (arena.describe_step).
    starts = [e for e in agent.telemetry_events if e["event_type"] == "step_start"]
    assert starts[0]["action_data"] == {"query": "chain belt"}
    assert all(e["tokens_input"] == 160 and e["tokens_output"] == 20 for e in ends)
    assert ends[0]["tokens_cache_read"] == 50 and ends[0]["tokens_cache_write"] == 10
    assert ends[0]["action_category"] == "search" and ends[-1]["action_category"] == "finish"
    expected = llm.Usage(100, 20, 50, 10).cost_usd("claude-sonnet-5-5")
    assert ends[0]["cost_usd"] == pytest.approx(expected)
    assert result["usage"]["input_tokens"] == 300


async def test_max_steps_and_tool_errors(monkeypatch, mapping):
    turns = [turn(calls=[(f"t{i}", "view_cart", {})]) for i in range(3)]
    scripted(monkeypatch, turns)
    hosts = []
    responses = {"view_cart": {"error": {"code": "invalid_action", "message": "nope"}, "screen": "landing",
                               "context": {}, "available_actions": [], "global_actions": []}}

    def factory(m):
        host = FakeHost(m, responses)
        hosts.append(host)
        return host

    agent = RindlerTelemetricAgent(run_id="r", goal="g", mapping=mapping, host_factory=factory, max_steps=3)
    result = await agent.run(start_url="http://127.0.0.1:9/")
    assert result["success"] is False and result["steps"] == 3
    assert any("max_steps (3)" in e for e in result["errors_detected"])
    ends = [e for e in agent.telemetry_events if e["event_type"] == "step_end"]
    assert len(ends) == 3 and all(e["was_error"] for e in ends)
    assert hosts[0].closed


async def test_llm_error_and_failed_start(monkeypatch, mapping):
    scripted(monkeypatch, [llm.LLMError("declined", kind="refusal")])
    hosts = []
    agent = make_agent(mapping, hosts)
    result = await agent.run(start_url="http://127.0.0.1:9/")
    assert result["success"] is False and "refusal" in result["message"]
    assert hosts[0].closed

    seen = scripted(monkeypatch, [])
    responses = {"start_session": {"error": {"code": "navigation_error", "message": "boom"}, "screen": "unknown",
                                   "context": {}, "available_actions": [], "global_actions": []}}

    def factory(m):
        host = FakeHost(m, responses)
        hosts.append(host)
        return host

    agent = RindlerTelemetricAgent(run_id="r", goal="g", mapping=mapping, host_factory=factory)
    result = await agent.run(start_url="http://127.0.0.1:9/")
    assert result["success"] is False and "navigation_error" in result["message"]
    assert seen == []  # the model is never called


async def test_unmapped_site_is_refused():
    agent = RindlerTelemetricAgent(run_id="r", goal="g")
    with pytest.raises(ValueError, match="No site mapping"):
        await agent.run(start_url="https://example.org/")


def test_model_defaults_and_overrides(monkeypatch):
    monkeypatch.delenv("BENCHMARK_AGENT_MODEL", raising=False)
    assert RindlerTelemetricAgent(run_id="r", goal="g").model == "claude-sonnet-5-5"
    assert RindlerTelemetricAgent(run_id="r", goal="g", model="claude-haiku-5-5").model == "claude-haiku-5-5"
    monkeypatch.setenv("BENCHMARK_AGENT_MODEL", "claude-opus-5-5")
    assert RindlerTelemetricAgent(run_id="r", goal="g").model == "claude-opus-5-5"


def test_cache_breakpoint_only_touches_the_request_copy():
    messages = [{"role": "user", "content": "hello"}]
    out = with_cache_breakpoint(messages)
    assert out[-1]["content"] == [{"type": "text", "text": "hello", "cache_control": {"type": "ephemeral"}}]
    assert messages == [{"role": "user", "content": "hello"}]


async def test_a_bot_check_goes_into_the_run_errors_with_its_page(monkeypatch, mapping):
    blocked = {"error": {"code": "bot_check", "message": "blocked by a bot check",
                         "page_url": "https://www.amazon.com/ax/claim?arb=1", "matched": 'form[name="signIn"]'},
               "screen": "unknown", "context": {}, "available_actions": [], "global_actions": ["start_session"]}
    scripted(monkeypatch, [
        turn(calls=[("t1", "search_products", {"query": "cable"})]),
        turn(calls=[("t2", "search_products", {"query": "cable"})]),
        turn(calls=[("t3", "done", {"success": False, "message": "Blocked by a bot check."})]),
    ])
    hosts = []
    agent = make_agent(mapping, hosts, responses={"search_products": blocked})
    result = await agent.run(start_url="http://127.0.0.1:9/")
    assert result["success"] is False
    # Once, however often the model meets it.
    assert result["errors_detected"] == [
        'bot check at https://www.amazon.com/ax/claim?arb=1 (matched form[name="signIn"])'
    ]


async def test_a_bot_check_at_the_start_goes_into_the_run_errors(monkeypatch, mapping):
    blocked = {"error": {"code": "bot_check", "message": "blocked by a bot check",
                         "page_url": "https://www.amazon.com/errors/validateCaptcha", "matched": "#captchacharacters"},
               "screen": "unknown", "context": {}, "available_actions": [], "global_actions": ["start_session"]}
    scripted(monkeypatch, [])
    hosts = []
    agent = make_agent(mapping, hosts, responses={"start_session": blocked})
    result = await agent.run(start_url="http://127.0.0.1:9/")
    assert result["success"] is False and result["steps"] == 0
    assert result["errors_detected"] == [
        "start_session failed: [bot_check] blocked by a bot check",
        "bot check at https://www.amazon.com/errors/validateCaptcha (matched #captchacharacters)",
    ]
