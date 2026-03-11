"""Tests for the telemetric_logger module."""

import json
import hashlib
import time
from datetime import datetime
from unittest.mock import patch

import pytest
import sys
import os

# Add the clean-room root to sys.path so we can import telemetric_logger
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from telemetric_logger import TelemetryEvent, TelemetricWrapper


class TestTelemetryEvent:

    def test_create_event_with_required_fields(self):
        now = datetime.now()
        event = TelemetryEvent(
            trace_id="trace-1",
            run_id="run-1",
            lane="RINDLER",
            step_index=1,
            event_type="step_start",
            timestamp=now,
        )
        assert event.trace_id == "trace-1"
        assert event.run_id == "run-1"
        assert event.lane == "RINDLER"
        assert event.step_index == 1
        assert event.event_type == "step_start"
        assert event.timestamp == now

    def test_default_optional_fields_are_none(self):
        event = TelemetryEvent(
            trace_id="t", run_id="r", lane="L",
            step_index=0, event_type="step_start",
            timestamp=datetime.now(),
        )
        assert event.duration_ms is None
        assert event.tokens_input is None
        assert event.tokens_output is None
        assert event.cost_usd is None
        assert event.action_type is None
        assert event.action_data is None
        assert event.observation_hash is None

    def test_timestamp_is_datetime_not_string(self):
        """base_agent.py calls event.timestamp.isoformat() — must be datetime."""
        event = TelemetryEvent(
            trace_id="t", run_id="r", lane="L",
            step_index=0, event_type="step_start",
            timestamp=datetime.now(),
        )
        assert isinstance(event.timestamp, datetime)
        # Must support .isoformat() without raising
        iso = event.timestamp.isoformat()
        assert isinstance(iso, str)

    def test_all_fields_populated(self):
        now = datetime.now()
        event = TelemetryEvent(
            trace_id="trace-1",
            run_id="run-1",
            lane="BROWSERUSE",
            step_index=3,
            event_type="step_end",
            timestamp=now,
            duration_ms=1234.5,
            tokens_input=500,
            tokens_output=50,
            cost_usd=0.025,
            action_type="click",
            action_data={"selector": "#btn"},
            observation_hash="abc123",
        )
        assert event.duration_ms == 1234.5
        assert event.tokens_input == 500
        assert event.tokens_output == 50
        assert event.cost_usd == 0.025
        assert event.action_type == "click"
        assert event.action_data == {"selector": "#btn"}
        assert event.observation_hash == "abc123"


class TestTelemetricWrapper:

    def test_init_stores_identifiers(self):
        wrapper = TelemetricWrapper(trace_id="t1", run_id="r1", lane="RINDLER")
        assert wrapper.trace_id == "t1"
        assert wrapper.run_id == "r1"
        assert wrapper.lane == "RINDLER"

    def test_log_step_start_returns_event(self):
        wrapper = TelemetricWrapper(trace_id="t1", run_id="r1", lane="RINDLER")
        event = wrapper.log_step_start(
            step_index=1,
            action_type="navigate",
            action_data={"url": "https://shipt.com"},
        )
        assert isinstance(event, TelemetryEvent)
        assert event.event_type == "step_start"
        assert event.step_index == 1
        assert event.action_type == "navigate"
        assert event.action_data == {"url": "https://shipt.com"}
        assert event.trace_id == "t1"
        assert event.run_id == "r1"
        assert event.lane == "RINDLER"
        assert isinstance(event.timestamp, datetime)
        assert event.duration_ms is None  # No duration on step_start

    def test_log_step_end_returns_event(self):
        wrapper = TelemetricWrapper(trace_id="t1", run_id="r1", lane="RINDLER")
        wrapper.log_step_start(step_index=1, action_type="navigate")
        event = wrapper.log_step_end(
            step_index=1,
            tokens_input=100,
            tokens_output=20,
            observation={"page_url": "https://shipt.com"},
        )
        assert isinstance(event, TelemetryEvent)
        assert event.event_type == "step_end"
        assert event.step_index == 1
        assert event.tokens_input == 100
        assert event.tokens_output == 20
        assert event.duration_ms is not None
        assert event.duration_ms >= 0
        assert event.cost_usd is None  # cost_usd is not computed by the wrapper

    def test_duration_ms_computed_from_start(self):
        wrapper = TelemetricWrapper(trace_id="t1", run_id="r1", lane="RINDLER")
        wrapper.log_step_start(step_index=1, action_type="click")
        time.sleep(0.05)  # 50ms
        event = wrapper.log_step_end(step_index=1, tokens_input=0, tokens_output=0)
        assert event.duration_ms is not None
        assert event.duration_ms >= 40  # At least ~40ms (allowing for timing jitter)

    def test_observation_hash_computed(self):
        wrapper = TelemetricWrapper(trace_id="t1", run_id="r1", lane="RINDLER")
        wrapper.log_step_start(step_index=1, action_type="click")
        observation = {"page_url": "https://shipt.com", "title": "Shipt"}
        event = wrapper.log_step_end(
            step_index=1, tokens_input=0, tokens_output=0,
            observation=observation,
        )
        # Hash should be SHA-256 of JSON-serialized observation
        expected = hashlib.sha256(
            json.dumps(observation, sort_keys=True, default=str).encode()
        ).hexdigest()
        assert event.observation_hash == expected

    def test_observation_hash_none_when_no_observation(self):
        wrapper = TelemetricWrapper(trace_id="t1", run_id="r1", lane="RINDLER")
        wrapper.log_step_start(step_index=1, action_type="click")
        event = wrapper.log_step_end(step_index=1, tokens_input=0, tokens_output=0)
        assert event.observation_hash is None

    def test_step_end_without_start_has_no_duration(self):
        wrapper = TelemetricWrapper(trace_id="t1", run_id="r1", lane="RINDLER")
        event = wrapper.log_step_end(step_index=99, tokens_input=0, tokens_output=0)
        assert event.duration_ms is None

    def test_multiple_steps_tracked_independently(self):
        wrapper = TelemetricWrapper(trace_id="t1", run_id="r1", lane="RINDLER")
        wrapper.log_step_start(step_index=1, action_type="navigate")
        wrapper.log_step_start(step_index=2, action_type="click")
        end1 = wrapper.log_step_end(step_index=1, tokens_input=100, tokens_output=10)
        end2 = wrapper.log_step_end(step_index=2, tokens_input=200, tokens_output=20)
        assert end1.duration_ms is not None
        assert end2.duration_ms is not None
        assert end1.tokens_input == 100
        assert end2.tokens_input == 200
