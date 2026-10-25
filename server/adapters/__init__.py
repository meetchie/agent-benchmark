"""
Adapters - the two arena arms, each wrapped with the shared telemetry in BaseAgent.

- BrowserUseTelemetricAgent (BROWSERUSE): browser-use driving a browser on its own.
- RindlerTelemetricAgent (RINDLER): a tool-calling model driving the site through a
  Rindler site mapping.
"""

from .base_agent import BaseAgent
from .browseruse_agent import BrowserUseTelemetricAgent, TelemetricAgent
from .rindler_agent import RindlerTelemetricAgent

# Agent registry for lookup by name
AGENTS = {
    "BROWSERUSE": BrowserUseTelemetricAgent,
    "RINDLER": RindlerTelemetricAgent,
}


def get_agent_class(name: str):
    """Agent class by name (case-insensitive). Raises KeyError for an unknown name."""
    name_upper = name.upper()
    if name_upper not in AGENTS:
        raise KeyError(f"Agent '{name}' not found. Available: {list(AGENTS.keys())}")
    return AGENTS[name_upper]


__all__ = [
    "BaseAgent",
    "BrowserUseTelemetricAgent",
    "TelemetricAgent",  # Backwards compatibility alias
    "RindlerTelemetricAgent",
    "AGENTS",
    "get_agent_class",
]
