"""
Adapters - Telemetric agent adapters for various browser automation providers.

This package provides adapter classes that wrap different browser automation
tools with unified telemetry logging via BaseAgent.

Available Adapters:
- BrowserUseTelemetricAgent: Uses browser-use library with Browserbase
- SteelTelemetricAgent: Uses Steel SDK with LangChain orchestration  
- SkyvernTelemetricAgent: Uses Skyvern cloud API for autonomous tasks
- StagehandTelemetricAgent: Uses Browserbase Stagehand for AI-driven automation

All agents extend BaseAgent which provides common telemetry functionality.
"""

from .base_agent import BaseAgent
from .browseruse_agent import BrowserUseTelemetricAgent, TelemetricAgent
from .steel_agent import SteelTelemetricAgent
from .skyvern_agent import SkyvernTelemetricAgent
from .stagehand_agent import StagehandTelemetricAgent

# Agent registry for easy lookup by name
AGENTS = {
    "BROWSERUSE": BrowserUseTelemetricAgent,
    "STEEL": SteelTelemetricAgent,
    "SKYVERN": SkyvernTelemetricAgent,
    "STAGEHAND": StagehandTelemetricAgent,
}

def get_agent_class(name: str):
    """
    Get an agent class by name.
    
    Args:
        name: Agent name (case-insensitive)
        
    Returns:
        The agent class
        
    Raises:
        KeyError: If agent not found
    """
    name_upper = name.upper()
    if name_upper not in AGENTS:
        raise KeyError(f"Agent '{name}' not found. Available: {list(AGENTS.keys())}")
    return AGENTS[name_upper]


__all__ = [
    # Base class
    "BaseAgent",
    
    # Agent implementations
    "BrowserUseTelemetricAgent",
    "TelemetricAgent",  # Backwards compatibility alias
    "SteelTelemetricAgent",
    "SkyvernTelemetricAgent",
    "StagehandTelemetricAgent",
    
    # Registry
    "AGENTS",
    "get_agent_class",
]
