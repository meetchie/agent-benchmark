"""The actions a browser-use step ran, read from browser-use's own history items.

The arena's BrowserUse arm (adapters/browseruse_agent.py) and the comparison CLI's
(cli/benchcli/browseruse_arm.py) both describe a step to their judge from ran_actions, so
the two judges read the same account of what browser-use did.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# How much of a failed action's error is kept (each judge reads less).
ERROR_TEXT_LIMIT = 300

# browser-use 0.13 answers a click, input, dropdown_options or select_dropdown on an element
# index that is no longer on the page with a result that is not an error
# (browser_use/tools/service.py):
#
#     ActionResult(extracted_content='Element index 9 not available - page may have changed. Try refreshing browser state.')
#
# Nothing was clicked, typed or selected, but the action reads as done unless it is marked.
# The mark is kept narrow: the result has no error, it starts with this wording, and the
# index in it is the one the action itself named. (scroll reports a missing element as an
# error, which is shown as one.) tests/test_browser_use_actions.py checks that the installed
# browser-use still words it this way.
ELEMENT_NOT_AVAILABLE = "Element index {index} not available - page may have changed."


def element_not_available(params: Any, result: Any) -> Optional[int]:
    """The element index browser-use could not find for this action, or None if it acted."""
    if getattr(result, "error", None):
        return None
    index = params.get("index") if isinstance(params, dict) else None
    if not isinstance(index, int) or isinstance(index, bool):
        return None
    text = getattr(result, "extracted_content", None)
    if isinstance(text, str) and text.startswith(ELEMENT_NOT_AVAILABLE.format(index=index)):
        return index
    return None


def ran_actions(history_items: list) -> List[Dict[str, Any]]:
    """The actions browser-use ran in some history items, as
    {"action", "params", "element", "error", "not_run"} dicts.

    The model can plan several actions in one step, and browser-use runs them in order but
    stops early: after an action that fails, after a navigation, once the page changes, or at
    a done that is not the step's only action. Each action it ran left one result in
    item.result, in the same order, so pairing the planned actions with the results (as
    browser-use's own AgentHistoryList.action_history() does) keeps the ones that ran and
    drops the ones it skipped. history.model_actions() lists every planned action, skipped or
    not, so it cannot be used for this.

    "element" is the accessible name of the element the action targeted, when it has one: the
    index means nothing outside that page, the name says what was clicked or typed into.
    "error" is there only for an action that failed, as one line of its error. "not_run" is
    there only for an action browser-use answered without doing anything because its element
    was gone ("element 9 was not available", see ELEMENT_NOT_AVAILABLE).
    """
    out: List[Dict[str, Any]] = []
    for item in history_items:
        planned = list(getattr(getattr(item, "model_output", None), "action", None) or [])
        results = list(getattr(item, "result", None) or [])
        elements = list(getattr(getattr(item, "state", None), "interacted_element", None) or [])
        for i, (planned_action, result) in enumerate(zip(planned, results)):
            try:
                dumped = planned_action.model_dump(exclude_none=True, mode="json")
            except Exception:
                continue
            if not isinstance(dumped, dict) or not dumped:
                continue
            name = next(iter(dumped))
            params = dumped[name]
            action: Dict[str, Any] = {"action": name, "params": params if isinstance(params, dict) else {}}
            element = elements[i] if i < len(elements) else None
            label = " ".join(str(getattr(element, "ax_name", None) or "").split())
            if label:
                action["element"] = label
            error = " ".join(str(getattr(result, "error", None) or "").split())
            if error:
                action["error"] = error[:ERROR_TEXT_LIMIT]
            missing = element_not_available(action["params"], result)
            if missing is not None:
                action["not_run"] = f"element {missing} was not available"
            out.append(action)
    return out
