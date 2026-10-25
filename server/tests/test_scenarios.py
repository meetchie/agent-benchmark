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

OLD_PLACES = ("San Mateo", "94403", "Cambridge", "02139")


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
    criteria = scenario.success_criteria or ""
    if "1 Main St" in scenario.goal and "address" in criteria.lower():
        assert "1 Main St, Springfield, IL 62701" in criteria, f"{name}: criteria check a different address"


def test_mapped_scenarios_have_a_mapping():
    mapped = [s for s in SCENARIOS.values() if s.name.startswith(("shipt_", "vhlistings_"))]
    assert len(mapped) == 6
    for scenario in mapped:
        mapping = find_mapping_for_url(scenario.start_url)
        assert mapping is not None and scenario.name.startswith(mapping.site_id + "_")
