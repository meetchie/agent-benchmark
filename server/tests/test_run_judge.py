# tests/test_run_judge.py
"""Tests for the GPT-4o run judge."""
import json
import pytest
from unittest.mock import patch, MagicMock
from run_judge import judge_run, validate_phases


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


class TestJudgeRun:
    """Test the judge_run function with mocked OpenAI."""

    @patch("run_judge.OpenAI")
    def test_successful_judge(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        gpt_response = {
            "success": True,
            "summary": "Agent completed the task.",
            "phases": [
                {"name": "Navigate", "steps": [1, 2], "failed": False, "slow": False},
                {"name": "Add to cart", "steps": [3], "failed": False, "slow": False},
            ],
        }
        mock_msg = MagicMock()
        mock_msg.content = json.dumps(gpt_response)
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=mock_msg)]
        )

        steps = [
            {"step": 1, "description": "Go to site", "elapsed_ms": 2000},
            {"step": 2, "description": "Search product", "elapsed_ms": 3000},
            {"step": 3, "description": "Click add to cart", "elapsed_ms": 1000},
        ]
        result = judge_run("Add item to cart", steps)

        assert result["success"] is True
        assert result["summary"] == "Agent completed the task."
        assert len(result["phases"]) == 2
        assert result["phases"][0]["total_ms"] == 5000
        assert result["phases"][1]["total_ms"] == 1000

    @patch("run_judge.OpenAI")
    def test_api_failure_returns_fallback(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API down")

        steps = [
            {"step": 1, "description": "Go to site", "elapsed_ms": 2000},
        ]
        result = judge_run("Add item to cart", steps)

        assert result["success"] is False
        assert result["phases"] == []
        assert "Could not analyze" in result["summary"]

    @patch("run_judge.OpenAI")
    def test_invalid_phases_falls_back(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        # GPT returns phases with invalid step numbers
        gpt_response = {
            "success": True,
            "summary": "Done.",
            "phases": [
                {"name": "Phase 1", "steps": [1, 99], "failed": False, "slow": False},
            ],
        }
        mock_msg = MagicMock()
        mock_msg.content = json.dumps(gpt_response)
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=mock_msg)]
        )

        steps = [{"step": 1, "description": "Step 1", "elapsed_ms": 1000}]
        result = judge_run("Do task", steps)

        assert result["success"] is True
        assert result["phases"] == []  # Fell back due to invalid phases
