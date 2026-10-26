"""Local Rindler: an in-process interpreter of Rindler site mappings.

Playwright runs the mapping JSON in-process behind an MCP-shaped interface (``list_tools`` /
``call_tool``), in place of the hosted Rindler stack. The arena (server/adapters/rindler_agent.py)
and the comparison CLI both use it.

    from rindler_local import LocalRindlerHost, load_mapping, find_mapping_for_url

    mapping = load_mapping("vhlistings")          # server/mappings/vhlistings.json
    async with LocalRindlerHost(mapping) as host:
        tools = await host.list_tools()
        envelope = await host.call("start_session", {"url": "https://vhlistings.com"})
        envelope = await host.call("search_products", {"query": "belt"})
"""

from .extract import extract_cart_items, extract_products
from .host import LocalRindlerHost, parse_result, text_result
from .interpreter import InterruptState, RunResult, ScreenMatcher, StepFailed, StepResult, run_steps
from .mapping import (
    MAPPINGS_DIR,
    Mapping,
    MappingError,
    domain_matches,
    find_mapping_for_url,
    interpolate,
    load_mapping,
    mapping_paths,
    validate_mapping,
)
from .tools import build_tools, to_anthropic

__all__ = [
    "LocalRindlerHost",
    "Mapping",
    "MappingError",
    "MAPPINGS_DIR",
    "InterruptState",
    "RunResult",
    "ScreenMatcher",
    "StepFailed",
    "StepResult",
    "build_tools",
    "domain_matches",
    "extract_cart_items",
    "extract_products",
    "find_mapping_for_url",
    "interpolate",
    "load_mapping",
    "mapping_paths",
    "parse_result",
    "run_steps",
    "text_result",
    "to_anthropic",
    "validate_mapping",
]
