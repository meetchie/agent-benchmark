"""
Telemetric Agent - Backwards compatibility shim.

This module re-exports TelemetricAgent from the adapters package
for backwards compatibility with existing code.

For new code, import directly from adapters:
    from adapters import BrowserUseTelemetricAgent
"""

from adapters.browseruse_agent import BrowserUseTelemetricAgent, TelemetricAgent

__all__ = ["TelemetricAgent", "BrowserUseTelemetricAgent"]
