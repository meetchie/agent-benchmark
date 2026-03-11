"""Tests for the arena log analysis script."""

import os
import sys
import json
import pytest
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analyze_runs import parse_log_file, aggregate_runs, format_table, parse_timestamp_from_filename


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "arena_logs"


class TestParseLogFile:

    def test_parse_rindler_shipt_log(self):
        log_path = FIXTURE_DIR / "arena_rindler_shipt_20260311_120000.log"
        result = parse_log_file(log_path)
        assert result["agent"] == "RINDLER"
        assert result["scenario"] == "shipt_add_to_cart"
        assert result["success"] is True
        assert result["judge_verdict"] == "PASS"
        assert result["steps"] == 2  # count of step_end events
        assert result["tokens_input"] == 1100
        assert result["tokens_output"] == 100
        assert result["cost_usd"] == pytest.approx(0.015)

    def test_parse_browseruse_shipt_log(self):
        log_path = FIXTURE_DIR / "arena_browseruse_shipt_20260311_130000.log"
        result = parse_log_file(log_path)
        assert result["agent"] == "BROWSERUSE"
        assert result["scenario"] == "shipt_add_to_cart"
        assert result["success"] is False
        assert result["judge_verdict"] == "FAIL"
        assert result["steps"] == 5
        assert result["tokens_input"] == 4500
        assert result["tokens_output"] == 500
        assert result["cost_usd"] == pytest.approx(0.045)

    def test_parse_success_fail_variant(self):
        """Agent Reported Success: Fail should parse as False."""
        import tempfile
        content = "Agent: RINDLER\nScenario: test\nAgent Reported Success: Fail\nToken Burn: 100 (90 in / 10 out)\nCost: $0.01\n\nTelemetry Events:\n[]"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(content)
            tmp_path = Path(f.name)
        result = parse_log_file(tmp_path)
        assert result["success"] is False
        tmp_path.unlink()

    def test_parse_old_success_format(self):
        """Older logs use 'Success:' instead of 'Agent Reported Success:'."""
        import tempfile
        content = "Agent: BROWSERUSE\nScenario: test\nSuccess: True\nToken Burn: 100 (90 in / 10 out)\nCost: $0.01\n\nTelemetry Events:\n[]"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(content)
            tmp_path = Path(f.name)
        result = parse_log_file(tmp_path)
        assert result["success"] is True
        tmp_path.unlink()

    def test_parse_no_judge_verdict(self):
        """Logs without judge sections should have judge_verdict=None."""
        import tempfile
        content = "Agent: RINDLER\nScenario: test\nAgent Reported Success: True\nToken Burn: 100 (90 in / 10 out)\nCost: $0.01\n\nTelemetry Events:\n[]"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(content)
            tmp_path = Path(f.name)
        result = parse_log_file(tmp_path)
        assert result["judge_verdict"] is None
        tmp_path.unlink()

    def test_parse_judge_error_verdict(self):
        """Judge Verdict: ERROR should be parsed correctly from fixture."""
        log_path = FIXTURE_DIR / "arena_rindler_shipt_20260311_150000.log"
        result = parse_log_file(log_path)
        assert result["agent"] == "RINDLER"
        assert result["judge_verdict"] == "ERROR"
        assert result["success"] is True
        assert result["steps"] == 2


class TestParseTimestamp:

    def test_parse_from_filename(self):
        ts = parse_timestamp_from_filename("arena_rindler_shipt_20260311_120000.log")
        assert ts == datetime(2026, 3, 11, 12, 0, 0)

    def test_parse_from_path(self):
        ts = parse_timestamp_from_filename(Path("/some/path/arena_browseruse_shipt_20260311_130000.log"))
        assert ts == datetime(2026, 3, 11, 13, 0, 0)


class TestAggregateRuns:

    def test_aggregate_groups_by_scenario_and_agent(self):
        runs = [
            {"agent": "RINDLER", "scenario": "shipt_add_to_cart", "success": True, "judge_verdict": "PASS", "steps": 2, "cost_usd": 0.015},
            {"agent": "BROWSERUSE", "scenario": "shipt_add_to_cart", "success": False, "judge_verdict": "FAIL", "steps": 5, "cost_usd": 0.045},
        ]
        table = aggregate_runs(runs)
        assert len(table) == 2
        rindler_row = [r for r in table if r["agent"] == "RINDLER"][0]
        assert rindler_row["runs"] == 1
        assert rindler_row["success_rate"] == pytest.approx(1.0)
        assert rindler_row["judge_pass_rate"] == pytest.approx(1.0)
        assert rindler_row["avg_steps"] == pytest.approx(2.0)
        assert rindler_row["avg_cost"] == pytest.approx(0.015)

    def test_aggregate_multiple_runs_same_group(self):
        runs = [
            {"agent": "RINDLER", "scenario": "shipt_add_to_cart", "success": True, "judge_verdict": "PASS", "steps": 2, "cost_usd": 0.01},
            {"agent": "RINDLER", "scenario": "shipt_add_to_cart", "success": False, "judge_verdict": "FAIL", "steps": 8, "cost_usd": 0.02},
        ]
        table = aggregate_runs(runs)
        assert len(table) == 1
        row = table[0]
        assert row["runs"] == 2
        assert row["success_rate"] == pytest.approx(0.5)
        assert row["judge_pass_rate"] == pytest.approx(0.5)
        assert row["avg_steps"] == pytest.approx(5.0)
        assert row["avg_cost"] == pytest.approx(0.015)

    def test_aggregate_judge_error_excluded_from_pass_rate(self):
        runs = [
            {"agent": "RINDLER", "scenario": "s1", "success": True, "judge_verdict": "PASS", "steps": 2, "cost_usd": 0.01},
            {"agent": "RINDLER", "scenario": "s1", "success": True, "judge_verdict": "ERROR", "steps": 3, "cost_usd": 0.02},
        ]
        table = aggregate_runs(runs)
        row = table[0]
        assert row["runs"] == 2
        assert row["judge_pass_rate"] == pytest.approx(1.0)  # 1/1 (ERROR excluded)

    def test_aggregate_no_judge_verdict(self):
        """Runs with judge_verdict=None should be excluded from judge pass rate."""
        runs = [
            {"agent": "RINDLER", "scenario": "s1", "success": True, "judge_verdict": None, "steps": 2, "cost_usd": 0.01},
            {"agent": "RINDLER", "scenario": "s1", "success": True, "judge_verdict": "PASS", "steps": 3, "cost_usd": 0.02},
        ]
        table = aggregate_runs(runs)
        row = table[0]
        assert row["runs"] == 2
        assert row["judge_pass_rate"] == pytest.approx(1.0)  # 1/1 (None excluded)


class TestFiltering:

    def _parse_all_fixtures(self):
        """Parse all fixture files into run dicts."""
        runs = []
        for path in sorted(FIXTURE_DIR.glob("arena_*.log")):
            runs.append(parse_log_file(path))
        return runs

    def test_filter_by_agent(self):
        runs = self._parse_all_fixtures()
        filtered = [r for r in runs if r["agent"].upper() in {"RINDLER"}]
        assert all(r["agent"] == "RINDLER" for r in filtered)
        assert len(filtered) >= 3  # At least the 3 RINDLER fixtures

    def test_filter_by_scenario(self):
        runs = self._parse_all_fixtures()
        filtered = [r for r in runs if r["scenario"] == "amazon_search"]
        assert len(filtered) == 1
        assert filtered[0]["agent"] == "RINDLER"

    def test_filter_by_since_date(self):
        runs = self._parse_all_fixtures()
        since = datetime(2026, 3, 11, 13, 30, 0)
        filtered = [r for r in runs if r["timestamp"] and r["timestamp"] >= since]
        # Only arena_rindler_amazon_20260311_140000 and arena_rindler_shipt_20260311_150000 are after 13:30
        assert all(r["timestamp"] >= since for r in filtered)
        assert len(filtered) == 2


class TestFormatTable:

    def test_markdown_output(self):
        rows = [
            {"scenario": "shipt_add_to_cart", "agent": "RINDLER", "runs": 3,
             "success_rate": 0.667, "judge_pass_rate": 0.667, "avg_steps": 8.3, "avg_cost": 0.012},
        ]
        output = format_table(rows)
        assert "| Scenario" in output
        assert "shipt_add_to_cart" in output
        assert "RINDLER" in output
        assert "67%" in output
