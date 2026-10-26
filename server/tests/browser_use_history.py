"""Real browser-use history items for tests, built from browser-use's own classes.

An Agent keeps one AgentHistory per step: model_output.action holds every action the model
planned, and result holds one ActionResult per action browser-use actually ran. It runs them
in order and stops early (after a failed action, a navigation, or a page change), so a step
can have fewer results than actions. Code that reads the history is tested on these objects
rather than on look-alikes, so the shapes cannot drift from what browser-use produces.
"""

from __future__ import annotations

from browser_use.agent.views import ActionResult, AgentHistory, AgentOutput
from browser_use.browser.views import BrowserStateHistory
from browser_use.dom.views import DOMInteractedElement, NodeType

__all__ = ["ActionResult", "action", "element", "history_item"]

_ACTION_MODEL = None


def _action_model():
    global _ACTION_MODEL
    if _ACTION_MODEL is None:
        from browser_use.tools.service import Tools

        _ACTION_MODEL = Tools().registry.create_action_model()
    return _ACTION_MODEL


def action(**kwargs):
    """A real browser-use action, e.g. action(click={"index": 9})."""
    return _action_model()(**kwargs)


def element(ax_name: str | None = None, **attributes) -> DOMInteractedElement:
    """The page element an action targeted, as browser-use stores it in the step's state."""
    return DOMInteractedElement(
        node_id=1, backend_node_id=1, frame_id=None, node_type=NodeType.ELEMENT_NODE, node_value="",
        node_name="BUTTON", attributes=dict(attributes), bounds=None, x_path="/html/body/button",
        element_hash=1, ax_name=ax_name,
    )


def history_item(planned, results, elements=None, next_goal="", evaluation="") -> AgentHistory:
    """One step: the actions the model planned (none: its model call failed) and the results
    of the ones browser-use ran."""
    planned = list(planned)
    output = None
    if planned:
        output = AgentOutput.type_with_custom_actions(_action_model())(
            evaluation_previous_goal=evaluation, memory="", next_goal=next_goal, action=planned,
        )
    state = BrowserStateHistory(
        url="https://shop.example/", title="Shop", tabs=[],
        interacted_element=list(elements) if elements is not None else [None] * max(len(planned), 1),
    )
    return AgentHistory(model_output=output, result=list(results), state=state)
