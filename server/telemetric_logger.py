"""Telemetry logging for arena agents.

Provides TelemetryEvent (immutable step records) and TelemetricWrapper
(stateful logger that tracks step start times for duration computation).
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class TelemetryEvent:
    """A single telemetry event from an agent step."""
    trace_id: str
    run_id: str
    lane: str
    step_index: int
    event_type: str  # "step_start", "step_end", "artifact"
    timestamp: datetime
    duration_ms: Optional[float] = None
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    cost_usd: Optional[float] = None
    action_type: Optional[str] = None
    action_data: Any = None
    observation_hash: Optional[str] = None


class TelemetricWrapper:
    """Stateful telemetry logger that tracks step timings and computes hashes."""

    def __init__(self, trace_id: str, run_id: str, lane: str):
        self.trace_id = trace_id
        self.run_id = run_id
        self.lane = lane
        self._step_start_times: Dict[int, datetime] = {}

    def log_step_start(self, step_index: int, action_type: str,
                       action_data: Any = None) -> TelemetryEvent:
        """Record the start of a step. Stores timestamp for duration computation."""
        now = datetime.now()
        self._step_start_times[step_index] = now
        return TelemetryEvent(
            trace_id=self.trace_id,
            run_id=self.run_id,
            lane=self.lane,
            step_index=step_index,
            event_type="step_start",
            timestamp=now,
            action_type=action_type,
            action_data=action_data,
        )

    def log_step_end(self, step_index: int,
                     tokens_input: Optional[int] = None,
                     tokens_output: Optional[int] = None,
                     observation: Any = None) -> TelemetryEvent:
        """Record the end of a step. Computes duration from step_start and observation hash."""
        now = datetime.now()

        # Compute duration from corresponding step_start
        duration_ms = None
        start_time = self._step_start_times.get(step_index)
        if start_time is not None:
            duration_ms = (now - start_time).total_seconds() * 1000

        # Compute observation hash
        obs_hash = None
        if observation is not None:
            serialized = json.dumps(observation, sort_keys=True, default=str)
            obs_hash = hashlib.sha256(serialized.encode()).hexdigest()

        return TelemetryEvent(
            trace_id=self.trace_id,
            run_id=self.run_id,
            lane=self.lane,
            step_index=step_index,
            event_type="step_end",
            timestamp=now,
            duration_ms=duration_ms,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            observation_hash=obs_hash,
        )
