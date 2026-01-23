"""
Scenarios - Test scenario definitions for arena runs.

This package provides scenario definitions that can be used with any agent.
Each scenario defines a goal/prompt and optional start URL for browser automation tasks.
"""

from .definitions import Scenario, SCENARIOS, get_scenario, list_scenarios, create_custom_scenario

__all__ = [
    "Scenario",
    "SCENARIOS",
    "get_scenario",
    "list_scenarios",
    "create_custom_scenario",
]
