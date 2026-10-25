"""Scenario text: no Rindler tool vocabulary in task text, one placeholder address throughout,
and the mapped scenarios resolve to a mapping."""

from __future__ import annotations

import re

import pytest

from rindler_local import find_mapping_for_url, load_mapping, mapping_paths
from scenarios import SCENARIOS

TOOL_NAMES = {"start_session", "close_session"}
for _path in mapping_paths():
    TOOL_NAMES |= set(load_mapping(_path).actions)
# Plain words that are also action names; only the snake_case names are tool vocabulary.
TOOL_NAMES = {n for n in TOOL_NAMES if "_" in n}

# The places the March scenarios used before they all moved to one placeholder address. Cities and
# ZIPs are kept as they are. Streets are not named here at all: every street address a scenario
# contains must be the placeholder, which rules out any old one without spelling it.
OLD_PLACES = ("San Mateo", "94403", "Cambridge", "02139")
PLACEHOLDER_STREET = "1 Main St"
STREET_ADDRESS = re.compile(
    r"\b\d{1,6}\s+(?:[NSEW]\.?\s+)?(?:[A-Z][A-Za-z]*\s+){1,3}"
    r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|Way|Pl|Place|Ct|Court)\b"
)


def street_addresses(text: str) -> list[str]:
    """Every "<number> <Name> <St|Ave|...>" street address in ``text``."""
    return [m.group(0) for m in STREET_ADDRESS.finditer(text)]


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_goal_has_no_rindler_tool_names(name):
    goal = SCENARIOS[name].goal
    found = sorted(t for t in TOOL_NAMES if re.search(rf"\b{re.escape(t)}\b", goal))
    assert not found, f"{name}: the BrowserUse task text mentions Rindler tools {found}"
    assert "start a session" not in goal.lower()


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_one_placeholder_address_everywhere(name):
    scenario = SCENARIOS[name]
    text = "\n".join(filter(None, [scenario.goal, scenario.success_criteria, scenario.verification_hint]))
    for place in OLD_PLACES:
        assert place not in text, f"{name} still mentions {place!r}"
    others = [a for a in street_addresses(text) if a != PLACEHOLDER_STREET]
    assert not others, f"{name} mentions a street address other than the placeholder: {others}"
    criteria = scenario.success_criteria or ""
    if "1 Main St" in scenario.goal and "address" in criteria.lower():
        assert "1 Main St, Springfield, IL 62701" in criteria, f"{name}: criteria check a different address"


def test_the_street_check_finds_street_addresses_and_only_those():
    text = "Ship to 1 Main St, Springfield, IL 62701, or to 42 N Elm Street; 3 items, 2 days."
    assert street_addresses(text) == ["1 Main St", "42 N Elm Street"]
    assert street_addresses("Order 3 Grey Jackets in size M") == []
    assert street_addresses("Deliver to 1 Main St.") == ["1 Main St"]


def test_mapped_scenarios_have_a_mapping():
    mapped = [s for s in SCENARIOS.values() if s.name.startswith(("shipt_", "vhlistings_"))]
    assert len(mapped) == 6
    for scenario in mapped:
        mapping = find_mapping_for_url(scenario.start_url)
        assert mapping is not None and scenario.name.startswith(mapping.site_id + "_")
