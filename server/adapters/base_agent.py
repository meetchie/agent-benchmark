"""
Base Telemetric Agent - Abstract base class for all browser automation agents.

This module provides the BaseAgent class which encapsulates common telemetry
functionality shared across all agent implementations.
"""

import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, Optional, List

import sys
# Add clean-room root to path for telemetric_logger import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from telemetric_logger import TelemetricWrapper, TelemetryEvent


class BaseAgent(ABC):
    """
    Abstract base class for telemetric browser automation agents.
    
    Provides common functionality for:
    - Telemetry event tracking and logging
    - Artifact logging (session replays, recordings, etc.)
    - Event serialization
    - Step tracking
    
    Subclasses must implement the `run()` method.
    """
    
    def __init__(self, run_id: str, goal: str, lane: str):
        """
        Initialize the base agent with telemetry tracking.
        
        Args:
            run_id: Unique identifier for this run
            goal: The task/goal for the agent to accomplish
            lane: Lane identifier (e.g., "BROWSERUSE", "STEEL", "SKYVERN", "STAGEHAND")
        """
        self.run_id = run_id
        self.lane = lane
        self.goal = goal
        
        # Generate trace_id for telemetry
        self.trace_id = str(uuid.uuid4())
        
        # Initialize telemetry wrapper
        self.telemetry = TelemetricWrapper(
            trace_id=self.trace_id,
            run_id=self.run_id,
            lane=self.lane
        )
        
        # Store telemetry events
        self.telemetry_events: List[Dict[str, Any]] = []
        
        # Step tracking
        self._current_step_index = 0
        self._current_action_type: Optional[str] = None
    
    def _convert_event_to_dict(self, event: TelemetryEvent) -> Dict[str, Any]:
        """Convert TelemetryEvent dataclass to dictionary for JSON serialization."""
        return {
            'trace_id': event.trace_id,
            'run_id': event.run_id,
            'lane': event.lane,
            'step_index': event.step_index,
            'event_type': event.event_type,
            'timestamp': event.timestamp.isoformat(),
            'duration_ms': event.duration_ms,
            'tokens_input': event.tokens_input,
            'tokens_output': event.tokens_output,
            'cost_usd': event.cost_usd,
            'action_type': event.action_type,
            'observation_hash': event.observation_hash
        }
    
    def log_artifact(self, artifact_type: str, artifact_url: str) -> Dict[str, Any]:
        """
        Log an artifact event (e.g., session replay URL, recording, screenshot).
        
        Args:
            artifact_type: Type of artifact (e.g., "session_replay", "recording", "screenshot")
            artifact_url: URL or path to the artifact
            
        Returns:
            Dictionary representing the artifact event
        """
        event = {
            'trace_id': self.trace_id,
            'run_id': self.run_id,
            'lane': self.lane,
            'event_type': 'artifact',
            'artifact_type': artifact_type,
            'artifact_url': artifact_url,
            'timestamp': datetime.now().isoformat()
        }
        self.telemetry_events.append(event)
        return event
    
    def log_step_start(self, action_type: Optional[str] = None, 
                       action_data: Optional[Dict[str, Any]] = None) -> TelemetryEvent:
        """
        Log the start of a step.
        
        Args:
            action_type: Type of action being performed
            action_data: Additional action metadata
            
        Returns:
            The logged TelemetryEvent
        """
        self._current_step_index += 1
        self._current_action_type = action_type
        
        event = self.telemetry.log_step_start(
            step_index=self._current_step_index,
            action_type=action_type,
            action_data=action_data
        )
        self.telemetry_events.append(self._convert_event_to_dict(event))
        return event
    
    def log_step_end(self, tokens_input: Optional[int] = None,
                     tokens_output: Optional[int] = None,
                     observation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Log the end of a step.
        
        Args:
            tokens_input: Number of input tokens used
            tokens_output: Number of output tokens generated
            observation: Observation/result data from the step
            
        Returns:
            Dictionary representing the step_end event
        """
        event = self.telemetry.log_step_end(
            step_index=self._current_step_index,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            observation=observation
        )
        
        event_dict = self._convert_event_to_dict(event)
        
        # Preserve action_type from step_start
        if event_dict['action_type'] is None and self._current_action_type:
            event_dict['action_type'] = self._current_action_type
        
        self.telemetry_events.append(event_dict)
        return event_dict
    
    def log_step(self, action_type: str, action_data: Dict[str, Any],
                 observation: Dict[str, Any], tokens_input: Optional[int] = None,
                 tokens_output: Optional[int] = None) -> None:
        """
        Convenience method to log both step start and end together.
        
        Args:
            action_type: Type of action performed
            action_data: Action metadata
            observation: Result/observation data
            tokens_input: Input tokens used
            tokens_output: Output tokens generated
        """
        self.log_step_start(action_type=action_type, action_data=action_data)
        self.log_step_end(
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            observation=observation
        )
    
    def print_run_header(self, start_url: Optional[str] = None) -> None:
        """Print a standardized run header to console."""
        print(f"Starting {self.lane} agent run...")
        print(f"Trace ID: {self.trace_id}")
        print(f"Run ID: {self.run_id}")
        print(f"Lane: {self.lane}")
        if start_url:
            print(f"Start URL: {start_url}")
        goal_display = self.goal[:100] + "..." if len(self.goal) > 100 else self.goal
        print(f"Goal: {goal_display}")
        print("-" * 50)
    
    def print_run_footer(self, elapsed: float, success: bool, message: str) -> None:
        """Print a standardized run footer to console."""
        print("-" * 50)
        print(f"Agent completed in {elapsed:.2f} seconds")
        print(f"Total steps: {self._current_step_index}")
        print(f"Success: {success}")
        msg_display = message[:100] + "..." if len(str(message)) > 100 else message
        print(f"Result: {msg_display}")
    
    @abstractmethod
    async def run(self, start_url: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """
        Run the agent to accomplish the goal.
        
        Args:
            start_url: Optional URL to start at
            **kwargs: Agent-specific parameters
            
        Returns:
            Dictionary with run results including:
            - success: bool
            - message: str
            - steps: int
            - Any agent-specific fields
        """
        pass
    
    def run_sync(self, start_url: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """
        Synchronous wrapper for run().
        
        Args:
            start_url: Optional URL to start at
            **kwargs: Agent-specific parameters
            
        Returns:
            Dictionary with run results
        """
        import asyncio
        return asyncio.run(self.run(start_url=start_url, **kwargs))
