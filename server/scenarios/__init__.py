"""Test scenario definitions for arena runs. Each is a goal with an optional start URL, and any
agent can run them.
"""

from .definitions import Scenario, SCENARIOS, get_scenario, list_scenarios, create_custom_scenario

__all__ = [
    "Scenario",
    "SCENARIOS",
    "get_scenario",
    "list_scenarios",
    "create_custom_scenario",
]
