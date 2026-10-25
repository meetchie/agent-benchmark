"""The judge, with the model API replaced by a scripted client."""

import pytest

import cli_fakes
import llm
from benchcli import judge
from cli_helpers import TASK, make_record


def verdict_json(verdict="pass", reasoning="All criteria met.", category="none"):
    return {"verdict": verdict, "reasoning": reasoning, "failure_category": category}


async def test_pass_verdict_is_parsed_and_costed(monkeypatch):
    calls = cli_fakes.install(monkeypatch, cli_fakes.text_response(verdict_json(), input_tokens=2000, output_tokens=100))
    record = make_record(agent="rindler")
    await judge.judge_task(TASK, record)

    assert record["result"]["verdict"] == "pass"
    assert record["result"]["judge_reasoning"] == "All criteria met."
    assert record["result"]["failure_category"] is None
    assert record["judge"]["model"] == "claude-sonnet-5-5" and record["judge"]["attempts"] == 1
    assert record["judge"]["cost_usd"] == pytest.approx(2000 * 2 / 1e6 + 100 * 10 / 1e6)

    # What was sent: the judge model, the schema as structured output, no sampling parameters.
    request = calls[0]
    assert request["model"] == "claude-sonnet-5-5"
    schema = request["output_config"]["format"]["schema"]
    assert schema["properties"]["verdict"]["enum"] == ["pass", "fail"]
    assert "none" in schema["properties"]["failure_category"]["enum"]
    assert not {"temperature", "top_p", "top_k"} & set(request)
    user = request["messages"][0]["content"]
    assert TASK["success_criteria"] in user and "Cart: Hair Towel Wrap x1 $35.00" in user  # the final report is evidence


async def test_fail_verdict_keeps_its_category(monkeypatch):
    cli_fakes.install(monkeypatch, cli_fakes.text_response(verdict_json("fail", "Never opened the cart.", "wrong_action")))
    record = make_record(agent="browseruse", success=False)
    await judge.judge_task(TASK, record, model="claude-haiku-5-5")
    assert (record["result"]["verdict"], record["result"]["failure_category"]) == ("fail", "wrong_action")
    assert record["judge"]["model"] == "claude-sonnet-5-5"  # whatever the reply says answered


async def test_an_unknown_category_becomes_unknown_and_a_pass_has_none(monkeypatch):
    record = make_record()
    judge.apply_verdict(record, {"verdict": "fail", "reasoning": "r", "failure_category": "cosmic_rays"})
    assert record["result"]["failure_category"] == "unknown"
    judge.apply_verdict(record, {"verdict": "pass", "reasoning": "r", "failure_category": "wrong_action"})
    assert (record["result"]["verdict"], record["result"]["failure_category"]) == ("pass", None)
    judge.apply_verdict(record, {"verdict": "fail", "reasoning": "r", "failure_category": "none"})
    assert record["result"]["failure_category"] == "unknown"  # a fail always carries a category


async def test_judge_model_defaults_to_the_judge_role(monkeypatch):
    monkeypatch.setenv("BENCHMARK_JUDGE_MODEL", "claude-haiku-5-5")
    calls = cli_fakes.install(monkeypatch, cli_fakes.text_response(verdict_json(), model="claude-haiku-5-5"))
    await judge.judge_task(TASK, make_record())
    assert calls[0]["model"] == "claude-haiku-5-5"


async def test_transient_api_errors_are_retried_then_succeed(monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    boom = llm.LLMError("overloaded", kind="api", status_code=529)
    calls = cli_fakes.install(monkeypatch, _api_error(529), _api_error(500), cli_fakes.text_response(verdict_json()))
    record = make_record()
    await judge.judge_task(TASK, record, sleep=fake_sleep)
    assert record["result"]["verdict"] == "pass" and record["judge"]["attempts"] == 3
    assert sleeps == [1, 2] and len(calls) == 3
    assert boom.kind == "api"


def _api_error(status):
    import anthropic
    import httpx

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status, request=request, json={"error": {"type": "api_error", "message": "x"}})
    return anthropic.APIStatusError("boom", response=response, body=None)


async def test_three_failures_give_an_error_verdict(monkeypatch):
    async def no_sleep(_):
        return None

    calls = cli_fakes.install(monkeypatch, _api_error(500))
    record = make_record()
    await judge.judge_task(TASK, record, sleep=no_sleep)
    assert record["result"]["verdict"] == "error"
    assert "after 3 attempt" in record["result"]["judge_reasoning"]
    assert record["result"]["failure_category"] == "unknown"
    assert len(calls) == 3


async def test_a_rejected_request_is_not_retried(monkeypatch):
    calls = cli_fakes.install(monkeypatch, _api_error(401))
    record = make_record()
    await judge.judge_task(TASK, record)
    assert record["result"]["verdict"] == "error" and len(calls) == 1


async def test_a_refusal_is_not_retried(monkeypatch):
    calls = cli_fakes.install(monkeypatch, cli_fakes.text_response("", stop_reason="refusal"))
    record = make_record()
    await judge.judge_task(TASK, record)
    assert record["result"]["verdict"] == "error" and len(calls) == 1


async def test_unparseable_output_is_retried_as_bad_json(monkeypatch):
    async def no_sleep(_):
        return None

    calls = cli_fakes.install(monkeypatch, cli_fakes.text_response("I think it passed."),
                              cli_fakes.text_response(verdict_json("fail", "no", "unknown")))
    record = make_record()
    await judge.judge_task(TASK, record, sleep=no_sleep)
    assert record["result"]["verdict"] == "fail" and len(calls) == 2


async def test_a_run_that_never_started_is_an_error_without_a_model_call(monkeypatch):
    calls = cli_fakes.install(monkeypatch, cli_fakes.text_response(verdict_json()))
    record = make_record(steps=0, success=False, final_report=None)
    record["error"] = "start_session failed: [navigation_error] failed to open https://shop.example.com"
    await judge.judge_task(TASK, record)
    assert record["result"]["verdict"] == "error" and record["result"]["failure_category"] == "site_error"
    assert "never got going" in record["result"]["judge_reasoning"]
    assert calls == []


def test_the_trace_and_prompt_carry_the_evidence():
    record = make_record(agent="rindler", success=False, steps=2, final_report=None)
    record["steps"][1]["error"] = "[execution_failed] step 3 failed"
    record["steps"][1]["observation"] = "x" * 500
    record["error"] = "did not call done within 12 steps"
    prompt = judge.build_prompt(TASK, record)
    assert "Steps taken: 2 of 12 allowed" in prompt
    assert "(the agent gave no final report)" in prompt
    assert "Run error: did not call done within 12 steps" in prompt
    assert "[ERROR: [execution_failed] step 3 failed]" in prompt
    assert "x" * 200 not in prompt  # observations are clipped
    assert judge.build_trace([]) == "(no steps were taken)"
