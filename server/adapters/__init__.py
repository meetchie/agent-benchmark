"""
Adapters - Telemetric agent adapters for various browser automation providers.

This package provides adapter classes that wrap different browser automation
tools with unified telemetry logging via TelemetricWrapper.

Available Adapters:
- BrowserUseTelemetricAgent: Uses browser-use library with Browserbase
- SteelTelemetricAgent: Uses Steel SDK with LangChain orchestration  
- SkyvernTelemetricAgent: Uses Skyvern cloud API for autonomous tasks
- StagehandTelemetricAgent: Uses Browserbase Stagehand for AI-driven automation
"""

from .browseruse_agent import BrowserUseTelemetricAgent, TelemetricAgent
from .steel_agent import SteelTelemetricAgent
from .skyvern_agent import SkyvernTelemetricAgent
from .stagehand_agent import StagehandTelemetricAgent

__all__ = [
    "BrowserUseTelemetricAgent",
    "TelemetricAgent",  # Backwards compatibility alias
    "SteelTelemetricAgent",
    "SkyvernTelemetricAgent",
    "StagehandTelemetricAgent",
]
