"""The Rindler arm: the loop with a scripted host and model, then against a local copy of prose."""

import asyncio
import json
from pathlib import Path

import pytest

import cli_fakes
import llm
from benchcli import rindler_arm, sites
from cli_helpers import TASK
from rindler_local import build_tools, text_result

# -- a host that answers from a script, so the loop can be tested without a browser ------


class FakeHost:
    """Stands in for LocalRindlerHost: same list_tools / call_tool / close surface."""

    instances = []

    def __init__(self, mapping, script=None):
        self.mapping = mapping
        self.script = script or {}
        self.calls = []
        self.closed = False
        self.page = None
        FakeHost.instances.append(self)

    async def list_tools(self):
        return build_tools(self.mapping)

    async def call_tool(self, name, args=None):
        self.calls.append((name, dict(args or {})))
        reply = self.script.get(name) or self.script.get("*") or default_envelope(name)
        envelope = reply(args) if callable(reply) else reply
        return text_result(envelope, is_error="error" in envelope)

    async def close(self):
        self.closed = True


def default_envelope(name):
    data = {"page_url": "https://shop.example.com/", "page_info": {"title": "Accessories"}}
    if name == "start_session":
        data["session_id"] = "abc"
    return {"screen": "accessories", "context": {}, "data": data,
            "available_actions": ["view_cart", "view_product", "start_session"], "global_actions": ["start_session"]}


def error_envelope(code, message):
    return {"error": {"code": code, "message": message}, "screen": "accessories", "context": {},
            "available_actions": ["view_cart"], "global_actions": ["start_session"]}


@pytest.fixture(scope="module")
def prose():
    return sites.load_site("prose")


@pytest.fixture(autouse=True)
def reset_hosts():
    FakeHost.instances.clear()


def run(prose, tmp_path, *, max_steps=6, script=None, timeout_s=None, task=None):
    def factory(mapping):
        return FakeHost(mapping, script)

    return rindler_arm.run_rindler_task(
        task or dict(TASK, start_url="https://www.prose.com"), mapping=prose.mapping, model="claude-sonnet-5-5",
        max_steps=max_steps, results_dir=tmp_path, site="prose", timeout_s=timeout_s, host_factory=factory,
    )


# -- tools and prompt ------------------------------------------------------------------


async def test_the_model_gets_the_mapping_actions_and_done_only(prose, tmp_path, monkeypatch):
    calls = cli_fakes.install(monkeypatch, cli_fakes.tool_response("done", {"success": True, "message": "ok"}))
    record = await run(prose, tmp_path)

    sent = [t["name"] for t in calls[0]["tools"]]
    assert sent == sorted(prose.mapping.actions) + ["done"]
    assert "view_accessories" in sent and "view_gift_cards" in sent
    assert "start_session" not in sent and "close_session" not in sent
    assert record["tools"] == sorted(prose.mapping.actions)
    assert all("input_schema" in t for t in calls[0]["tools"])


async def test_request_shape_one_call_per_turn_no_sampling_cache_breakpoint(prose, tmp_path, monkeypatch):
    calls = cli_fakes.install(monkeypatch, cli_fakes.tool_response("view_cart"),
                              cli_fakes.tool_response("done", {"success": True, "message": "ok"}))
    await run(prose, tmp_path)
    first, second = calls
    assert first["system"] == rindler_arm.SYSTEM_PROMPT
    assert first["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert not {"temperature", "top_p", "top_k"} & set(first)
    # the goal goes in verbatim, and the model is not pointed at start_session
    opening = first["messages"][0]["content"]
    opening = opening[0]["text"] if isinstance(opening, list) else opening
    assert TASK["goal"] in opening
    assert "start_session" not in opening and "Available actions: view_cart, view_product" in opening
    # only the request copy carries the cache marker, on the newest user block
    assert second["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}


async def test_the_prompt_names_every_field_the_host_returns():
    """tests/test_rindler_arm_host.py runs the real host; this pins the documented field list."""
    for field in ("screen", "available_actions", "global_actions", "context", "data", "page_url", "page_info",
                  "products", "cart_items", "extracted", "error", "code", "message"):
        assert f'"{field}"' in rindler_arm.SYSTEM_PROMPT, field
    # fields from the March CLI prompt that the host never returned
    assert "page_summary" not in rindler_arm.SYSTEM_PROMPT and "session_id" not in rindler_arm.SYSTEM_PROMPT


def test_model_view_hides_tools_the_model_does_not_have():
    env = {"screen": "cart", "available_actions": ["view_cart", "ghost"], "global_actions": ["start_session"]}
    view = rindler_arm.model_view(env, {"view_cart"})
    assert view["available_actions"] == ["view_cart"] and view["global_actions"] == []
    assert env["global_actions"] == ["start_session"]  # the original is untouched


def test_describe_digests_a_cart_for_the_judge_trace():
    env = {"screen": "cart", "data": {"page_info": {
        "title": "Your cart(1)", "cart_items": [{"name": "Hair Towel", "price": "$35.00", "quantity": "1"}],
        "order_summary": {"total": "Today’s total (pre-tax) $41.95"}}}}
    text = rindler_arm.describe(env)
    assert "screen=cart" in text and "Hair Towel x1 $35.00" in text and "$41.95" in text
    assert rindler_arm.describe(error_envelope("invalid_action", "no")) .startswith("screen=accessories error invalid_action")


# -- the loop ---------------------------------------------------------------------------


async def test_a_finished_run_logs_steps_tokens_and_cost(prose, tmp_path, monkeypatch):
    cli_fakes.install(
        monkeypatch,
        cli_fakes.tool_response("view_accessories", input_tokens=1000, output_tokens=50),
        cli_fakes.tool_response("view_cart", input_tokens=200, output_tokens=40, cache_read=900, cache_write=300),
        cli_fakes.tool_response("done", {"success": True, "message": "Cart: Hair Towel x1 $35.00"},
                                input_tokens=100, output_tokens=60, cache_read=1200),
    )
    record = await run(prose, tmp_path, max_steps=10)

    assert [s["step"] for s in record["steps"]] == [0, 1, 2, 3]
    assert [s["action"] for s in record["steps"]] == ["start_session", "view_accessories", "view_cart", "done"]
    assert record["stats"]["total_steps"] == 3  # the session start is not a model step
    assert record["result"]["success"] is True
    assert record["result"]["final_report"] == "Cart: Hair Towel x1 $35.00"
    assert record["error"] is None and record["meta"]["max_steps"] == 10

    # every prompt token counts, cache reads and writes included
    assert [s["tokens_input"] for s in record["steps"]] == [0, 1000, 1400, 1300]
    assert record["steps"][2]["tokens_cache_read"] == 900 and record["steps"][2]["tokens_cache_write"] == 300
    expected = sum(llm.Usage(*u).cost_usd("claude-sonnet-5-5") for u in
                   [(1000, 50, 0, 0), (200, 40, 900, 300), (100, 60, 1200, 0)])
    assert record["stats"]["total_cost_usd"] == pytest.approx(expected, abs=1e-5)
    assert record["stats"]["total_tokens_output"] == 150
    assert FakeHost.instances[0].closed
    assert [c[0] for c in FakeHost.instances[0].calls] == ["start_session", "view_accessories", "view_cart"]


async def test_a_run_that_never_calls_done_stops_at_the_budget(prose, tmp_path, monkeypatch):
    calls = cli_fakes.install(monkeypatch, cli_fakes.tool_response("view_cart"))
    record = await run(prose, tmp_path, max_steps=4)
    assert len(calls) == 4  # exactly the budget, no more model calls
    assert record["stats"]["total_steps"] == 4
    assert record["result"]["success"] is False and record["result"]["final_report"] is None
    assert record["error"] == "did not call done within 4 steps"


async def test_done_with_success_false_is_a_reported_failure_not_an_error(prose, tmp_path, monkeypatch):
    cli_fakes.install(monkeypatch, cli_fakes.tool_response("done", {"success": False, "message": "No such towel."}))
    record = await run(prose, tmp_path)
    assert record["result"]["success"] is False and record["result"]["final_report"] == "No such towel."
    assert record["error"] is None


async def test_a_turn_without_a_tool_call_is_nudged_and_counted(prose, tmp_path, monkeypatch):
    calls = cli_fakes.install(monkeypatch, cli_fakes.no_tool_response("Hmm.", input_tokens=500, output_tokens=5),
                              cli_fakes.tool_response("done", {"success": True, "message": "ok"}))
    record = await run(prose, tmp_path)
    assert [s["action"] for s in record["steps"]] == ["start_session", "no_tool_call", "done"]
    assert record["stats"]["total_steps"] == 2 and record["steps"][1]["tokens_input"] == 500
    last = calls[1]["messages"][-1]
    assert last["role"] == "user" and rindler_arm.NUDGE in json.dumps(last)


async def test_tool_errors_go_back_to_the_model_marked_as_errors(prose, tmp_path, monkeypatch):
    script = {"view_product": error_envelope("execution_failed", "step 3 (click) failed: all selectors exhausted")}
    calls = cli_fakes.install(monkeypatch, cli_fakes.tool_response("view_product", {"item": "Ghost"}),
                              cli_fakes.tool_response("done", {"success": False, "message": "could not open it"}))
    record = await run(prose, tmp_path, script=script)
    assert record["steps"][1]["error"] == "[execution_failed] step 3 (click) failed: all selectors exhausted"
    assert record["steps"][1]["action_args"] == {"item": "Ghost"}
    result = calls[1]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and result["is_error"] is True
    assert "all selectors exhausted" in json.dumps(result["content"])


async def test_extra_tool_calls_in_one_turn_are_answered_not_run(prose, tmp_path, monkeypatch):
    calls = cli_fakes.install(
        monkeypatch,
        cli_fakes.tool_response("view_cart", extra_calls=[("view_accessories", {})]),
        cli_fakes.tool_response("done", {"success": True, "message": "ok"}),
    )
    await run(prose, tmp_path)
    assert [c[0] for c in FakeHost.instances[0].calls] == ["start_session", "view_cart"]
    results = calls[1]["messages"][-1]["content"]
    assert [r["type"] for r in results] == ["tool_result", "tool_result"]
    assert results[1]["is_error"] is True


async def test_a_failed_session_start_is_reported_without_asking_the_model(prose, tmp_path, monkeypatch):
    calls = cli_fakes.install(monkeypatch, cli_fakes.tool_response("done", {"success": True, "message": "x"}))
    script = {"start_session": error_envelope("navigation_error", "failed to open https://www.prose.com: net::ERR")}
    record = await run(prose, tmp_path, script=script)
    assert calls == []
    assert record["stats"]["total_steps"] == 0 and record["steps"][0]["action"] == "start_session"
    assert record["error"].startswith("start_session failed: [navigation_error]")
    assert FakeHost.instances[0].closed


async def test_a_model_api_failure_keeps_the_steps_so_far(prose, tmp_path, monkeypatch):
    cli_fakes.install(monkeypatch, cli_fakes.tool_response("view_cart", input_tokens=700, output_tokens=30),
                      cli_fakes.text_response("", stop_reason="refusal"))
    record = await run(prose, tmp_path)
    assert record["stats"]["total_steps"] == 1 and record["stats"]["total_tokens_input"] == 700
    assert record["error"].startswith("model call failed (refusal)")
    assert record["result"]["success"] is False and FakeHost.instances[0].closed


async def test_the_time_limit_stops_the_run_and_closes_the_browser(prose, tmp_path, monkeypatch):
    async def slow(_request):
        await asyncio.sleep(30)

    calls = cli_fakes.install(monkeypatch, slow)
    record = await run(prose, tmp_path, timeout_s=1)
    assert record["error"] == "stopped after the 1s time limit"
    assert len(calls) == 1 and FakeHost.instances[0].closed


async def test_an_unexpected_exception_ends_only_this_run(prose, tmp_path, monkeypatch):
    script = {"view_cart": lambda args: (_ for _ in ()).throw(RuntimeError("browser crashed"))}
    cli_fakes.install(monkeypatch, cli_fakes.tool_response("view_cart"))
    record = await run(prose, tmp_path, script=script)
    assert record["error"] == "RuntimeError: browser crashed" and FakeHost.instances[0].closed
