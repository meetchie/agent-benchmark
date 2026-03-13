"""Tests for benchmark_runner — verifies wiring to arena agent + judge."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from benchmark_runner import RunState, StepRecord, run_benchmark


class TestStepRecord:
    """StepRecord serialization."""

    def test_to_dict_without_screenshot(self):
        rec = StepRecord(step=1, description="Clicking element", elapsed_ms=500)
        d = rec.to_dict(include_screenshot=False)
        assert d == {"step": 1, "description": "Clicking element", "elapsed_ms": 500}
        assert "screenshot_b64" not in d

    def test_to_dict_with_screenshot(self):
        rec = StepRecord(step=1, description="Clicking", elapsed_ms=500, screenshot_b64="data:image/jpeg;base64,abc")
        d = rec.to_dict(include_screenshot=True)
        assert d["screenshot_b64"] == "data:image/jpeg;base64,abc"

    def test_to_dict_with_screenshot_flag_false_omits(self):
        rec = StepRecord(step=1, description="Clicking", elapsed_ms=500, screenshot_b64="data:image/jpeg;base64,abc")
        d = rec.to_dict(include_screenshot=False)
        assert "screenshot_b64" not in d


class TestRunState:
    """RunState serialization for API responses."""

    def test_running_response(self):
        state = RunState(run_id="test-123")
        resp = state.to_response()
        assert resp == {"status": "running", "steps": []}

    def test_complete_response(self):
        state = RunState(run_id="test-123", status="complete", success=True,
                         summary="Task passed", total_ms=5000)
        resp = state.to_response()
        assert resp["status"] == "complete"
        assert resp["success"] is True
        assert resp["summary"] == "Task passed"

    def test_error_response(self):
        state = RunState(run_id="test-123", status="error", message="Connection failed")
        resp = state.to_response()
        assert resp == {"status": "error", "message": "Connection failed"}

    def test_only_latest_step_includes_screenshot(self):
        state = RunState(run_id="test-123")
        state.steps.append(StepRecord(step=1, description="Step 1", elapsed_ms=100, screenshot_b64="old"))
        state.steps.append(StepRecord(step=2, description="Step 2", elapsed_ms=200, screenshot_b64="new"))
        resp = state.to_response()
        assert "screenshot_b64" not in resp["steps"][0]
        assert resp["steps"][1]["screenshot_b64"] == "new"


class TestRunBenchmark:
    """Integration test for run_benchmark wiring."""

    @pytest.mark.asyncio
    @patch("benchmark_runner.run_judge")
    @patch("benchmark_runner._BenchmarkAgent")
    async def test_successful_run(self, MockAgent, mock_judge):
        """Verify run_benchmark wires agent + judge and updates RunState."""
        mock_instance = MagicMock()
        mock_instance.telemetry_events = [
            {"event_type": "step_start", "action_type": "click_element", "step_index": 1}
        ]
        mock_instance.run = AsyncMock(return_value={
            "success": True,
            "message": "Agent completed",
            "steps": 3,
            "errors_detected": [],
            "final_extraction": "Found item in cart",
        })
        MockAgent.return_value = mock_instance

        mock_judge.return_value = {
            "verdict": "PASS",
            "reason": "All criteria met",
        }

        state = RunState(run_id="test-run")
        await run_benchmark(state, "https://example.com", "Add item to cart")

        # Agent was created with correct params
        MockAgent.assert_called_once()
        call_kwargs = MockAgent.call_args[1]
        assert call_kwargs["run_id"] == "test-run"
        assert "Add item to cart" in call_kwargs["goal"]

        # Agent.run() was called
        mock_instance.run.assert_awaited_once()

        # Judge was called
        mock_judge.assert_called_once()

        # State was updated
        assert state.status == "complete"
        assert state.success is True
        assert "All criteria met" in state.summary
        assert state.total_ms >= 0

    @pytest.mark.asyncio
    @patch("benchmark_runner._BenchmarkAgent")
    async def test_agent_exception_sets_error(self, MockAgent):
        """Verify agent exceptions are caught and set error state."""
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(side_effect=ValueError("BROWSERBASE_API_KEY not found"))
        mock_instance.telemetry_events = []
        MockAgent.return_value = mock_instance

        state = RunState(run_id="test-run")
        await run_benchmark(state, "https://example.com", "Do something")

        assert state.status == "error"
        assert "BROWSERBASE_API_KEY" in state.message

    @pytest.mark.asyncio
    @patch("benchmark_runner.run_judge")
    @patch("benchmark_runner._BenchmarkAgent")
    async def test_judge_fail_sets_success_false(self, MockAgent, mock_judge):
        """Verify judge FAIL verdict maps to success=False."""
        mock_instance = MagicMock()
        mock_instance.telemetry_events = []
        mock_instance.run = AsyncMock(return_value={
            "success": True, "message": "Done", "steps": 5,
            "errors_detected": [], "final_extraction": None,
        })
        MockAgent.return_value = mock_instance

        mock_judge.return_value = {
            "verdict": "FAIL",
            "reason": "Cart was empty",
        }

        state = RunState(run_id="test-run")
        await run_benchmark(state, "https://example.com", "Add item to cart")

        assert state.status == "complete"
        assert state.success is False
        assert "Cart was empty" in state.summary
