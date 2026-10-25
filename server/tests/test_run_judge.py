# tests/test_run_judge.py
"""Tests for the run judge."""
import json

import anthropic
import httpx

import llm
from run_judge import JUDGE_SCHEMA, judge_run, validate_phases
from tests.fakes import install_fake_anthropic, refusal_response, text_response


class TestValidatePhases:
    """Test phase validation logic (no API calls)."""

    def test_valid_phases(self):
        steps = [{"step": i, "description": f"Step {i}", "elapsed_ms": 1000} for i in range(1, 6)]
        phases = [
            {"name": "Phase 1", "steps": [1, 2], "failed": False, "slow": False},
            {"name": "Phase 2", "steps": [3, 4, 5], "failed": False, "slow": True},
        ]
        result = validate_phases(phases, steps)
        assert result is not None
        assert len(result) == 2
        assert result[0]["total_ms"] == 2000
        assert result[1]["total_ms"] == 3000

    def test_missing_step_returns_none(self):
        steps = [{"step": i, "description": f"Step {i}", "elapsed_ms": 1000} for i in range(1, 4)]
        phases = [
            {"name": "Phase 1", "steps": [1, 2, 99], "failed": False, "slow": False},
        ]
        assert validate_phases(phases, steps) is None

    def test_duplicate_step_returns_none(self):
        steps = [{"step": i, "description": f"Step {i}", "elapsed_ms": 1000} for i in range(1, 4)]
        phases = [
            {"name": "Phase 1", "steps": [1, 2], "failed": False, "slow": False},
            {"name": "Phase 2", "steps": [2, 3], "failed": False, "slow": False},
        ]
        assert validate_phases(phases, steps) is None

    def test_gap_in_coverage_returns_none(self):
        steps = [{"step": i, "description": f"Step {i}", "elapsed_ms": 1000} for i in range(1, 5)]
        phases = [
            {"name": "Phase 1", "steps": [1, 2], "failed": False, "slow": False},
            {"name": "Phase 2", "steps": [4], "failed": False, "slow": False},
        ]
        assert validate_phases(phases, steps) is None

    def test_empty_phases_returns_none(self):
        steps = [{"step": 1, "description": "Step 1", "elapsed_ms": 1000}]
        assert validate_phases([], steps) is None

    def test_empty_steps_returns_none(self):
        phases = [{"name": "Phase 1", "steps": [1], "failed": False, "slow": False}]
        assert validate_phases(phases, []) is None


STEPS_3 = [
    {"step": 1, "description": "Go to site", "elapsed_ms": 2000},
    {"step": 2, "description": "Search product", "elapsed_ms": 3000},
    {"step": 3, "description": "Click add to cart", "elapsed_ms": 1000},
]

GOOD_VERDICT = {
    "success": True,
    "summary": "Agent completed the task.",
    "phases": [
        {"name": "Navigate", "steps": [1, 2], "failed": False, "slow": False},
        {"name": "Add to cart", "steps": [3], "failed": False, "slow": False},
    ],
}


class TestJudgeRun:
    """Test judge_run through the real llm layer, with a fake model API."""

    def test_successful_judge(self, monkeypatch):
        install_fake_anthropic(monkeypatch, text_response(GOOD_VERDICT))

        result = judge_run("Add item to cart", STEPS_3)

        assert result["success"] is True
        assert result["summary"] == "Agent completed the task."
        assert len(result["phases"]) == 2
        assert result["phases"][0]["total_ms"] == 5000
        assert result["phases"][1]["total_ms"] == 1000

    def test_request_uses_the_judge_model_and_structured_output(self, monkeypatch):
        calls = install_fake_anthropic(monkeypatch, text_response(GOOD_VERDICT))
        monkeypatch.setenv("BENCHMARK_JUDGE_MODEL", "claude-haiku-5-5")

        judge_run("Add item to cart", STEPS_3, result_state="too_slow")

        (request,) = calls
        assert request["model"] == "claude-haiku-5-5"
        fmt = request["output_config"]["format"]
        assert fmt["type"] == "json_schema"
        assert set(fmt["schema"]["properties"]) == {"success", "summary", "phases"}
        assert not {"temperature", "top_p", "top_k"} & set(request)
        # The unchanged judge prompt, filled in with this run.
        prompt = request["messages"][0]["content"]
        assert "You are a benchmark judge" in prompt
        assert "Add item to cart" in prompt
        assert "RESULT STATE: too_slow" in prompt
        assert "Step #2 (3.0s): Search product" in prompt

    def test_a_run_that_finished_on_its_own_is_not_called_unknown(self, monkeypatch):
        calls = install_fake_anthropic(monkeypatch, text_response(GOOD_VERDICT))

        judge_run("Add item to cart", STEPS_3, result_state="completed")

        prompt = calls[0]["messages"][0]["content"]
        assert "unknown" not in prompt.lower()
        assert "finished on its own within the time limit" in prompt
        assert "Decide pass or fail from the task and the steps" in prompt
        assert "RESULT STATE: completed" in prompt

    def test_the_other_states_keep_their_wording(self, monkeypatch):
        calls = install_fake_anthropic(monkeypatch, text_response(GOOD_VERDICT))

        for state in ("too_slow", "error", "unknown"):
            judge_run("Add item to cart", STEPS_3, result_state=state)

        for call, state in zip(calls, ("too_slow", "error", "unknown")):
            prompt = call["messages"][0]["content"]
            assert f"RESULT STATE: {state}\n" in prompt
            assert (
                '(If "too_slow", the agent hit the timeout and did not finish. '
                'If "fail" or "pass", the agent ran to completion.)'
            ) in prompt
            assert "finished on its own" not in prompt

    def test_default_judge_model_is_sonnet_5_5(self, monkeypatch):
        calls = install_fake_anthropic(monkeypatch, text_response(GOOD_VERDICT))
        judge_run("Add item to cart", STEPS_3)
        assert calls[0]["model"] == "claude-sonnet-5-5"

    def test_no_steps_never_calls_the_model(self, monkeypatch):
        calls = install_fake_anthropic(monkeypatch, text_response(GOOD_VERDICT))
        result = judge_run("Add item to cart", [])
        assert result == {"success": False, "summary": "No steps were completed.", "phases": []}
        assert calls == []

    def test_api_failure_returns_fallback(self, monkeypatch):
        install_fake_anthropic(monkeypatch, Exception("API down"))

        steps = [
            {"step": 1, "description": "Go to site", "elapsed_ms": 2000},
        ]
        result = judge_run("Add item to cart", steps)

        assert result["success"] is False
        assert result["phases"] == []
        assert "Could not analyze" in result["summary"]

    def test_anthropic_api_error_returns_fallback(self, monkeypatch):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        error = anthropic.RateLimitError(
            "rate limited", response=httpx.Response(429, request=request), body=None
        )
        install_fake_anthropic(monkeypatch, error)
        result = judge_run("Do task", STEPS_3)
        assert result["success"] is False
        assert result["phases"] == []
        assert "Could not analyze" in result["summary"]

    def test_refusal_returns_fallback_that_says_so(self, monkeypatch):
        """A refusal is not an agent failure: the verdict stays unknown, and says why."""
        install_fake_anthropic(monkeypatch, refusal_response())
        result = judge_run("Do task", STEPS_3)
        assert result["success"] is False
        assert result["phases"] == []
        assert "Could not analyze" in result["summary"]
        assert "declined" in result["summary"]

    def test_truncated_reply_returns_fallback(self, monkeypatch):
        install_fake_anthropic(monkeypatch, text_response('{"success": tr', stop_reason="max_tokens"))
        result = judge_run("Do task", STEPS_3)
        assert result["success"] is False
        assert "Could not analyze" in result["summary"]

    def test_unparseable_reply_returns_fallback(self, monkeypatch):
        install_fake_anthropic(monkeypatch, text_response("I cannot judge this."))
        result = judge_run("Do task", STEPS_3)
        assert result["success"] is False
        assert result["phases"] == []

    def test_invalid_phases_falls_back(self, monkeypatch):
        # The judge returns phases with invalid step numbers
        verdict = {
            "success": True,
            "summary": "Done.",
            "phases": [
                {"name": "Phase 1", "steps": [1, 99], "failed": False, "slow": False},
            ],
        }
        install_fake_anthropic(monkeypatch, text_response(verdict))

        steps = [{"step": 1, "description": "Step 1", "elapsed_ms": 1000}]
        result = judge_run("Do task", steps)

        assert result["success"] is True
        assert result["phases"] == []  # Fell back due to invalid phases

    def test_long_summary_is_cut_to_500_characters(self, monkeypatch):
        install_fake_anthropic(monkeypatch, text_response({**GOOD_VERDICT, "summary": "x" * 900}))
        assert len(judge_run("Do task", STEPS_3)["summary"]) == 500

    def test_blank_summary_gets_a_default(self, monkeypatch):
        install_fake_anthropic(monkeypatch, text_response({**GOOD_VERDICT, "summary": ""}))
        assert judge_run("Do task", STEPS_3)["summary"] == "Agent completed the task."

    def test_fenced_json_is_accepted(self, monkeypatch):
        install_fake_anthropic(monkeypatch, text_response("```json\n" + json.dumps(GOOD_VERDICT) + "\n```"))
        assert judge_run("Do task", STEPS_3)["success"] is True

    def test_judge_schema_goes_through_the_llm_layer(self):
        schema = llm.strict_schema(JUDGE_SCHEMA)
        assert schema["additionalProperties"] is False
        assert schema["properties"]["phases"]["items"]["additionalProperties"] is False
