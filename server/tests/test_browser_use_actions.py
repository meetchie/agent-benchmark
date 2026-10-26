"""browser_use_actions: what a browser-use step ran, read from browser-use's own history items.

The arena's BrowserUse arm and the comparison CLI's both read a step through ran_actions, so
these tests cover both judges' traces.
"""

import inspect
import re

from browser_use_actions import ran_actions
from tests import browser_use_history as bu

GONE = "Element index 9 not available - page may have changed. Try refreshing browser state."

# browser-use's own lines for an element index that is no longer on the page.
BROWSER_USE_GONE = re.compile(
    r"msg = f'(Element index \{params\.index\} not available - page may have changed\. Try refreshing browser state\.)'"
    r"\s+logger\.warning\(f'⚠️ \{msg\}'\)"
    r"\s+return ActionResult\(extracted_content=msg\)"
)


def one(planned, result, element=None):
    return ran_actions([bu.history_item([planned], [result], elements=[element])])


def test_only_the_actions_browser_use_ran_are_kept():
    """One result per action that ran: done planned after a scroll never ran (browser-use runs
    done only as a step's single action)."""
    item = bu.history_item([bu.action(scroll={"down": True, "pages": 1.0}), bu.action(done={"text": "ok", "success": True})],
                           [bu.ActionResult(extracted_content="Scrolled down the page by 1.0 pages")])
    assert ran_actions([item]) == [{"action": "scroll", "params": {"down": True, "pages": 1.0}}]


def test_browser_use_still_answers_a_missing_element_with_a_plain_result():
    """The not-run mark matches browser-use's own wording. If an upgrade changes the wording or
    makes it an error, this fails, instead of the trace quietly reading such a click as made."""
    from browser_use.tools import service

    found = BROWSER_USE_GONE.findall(inspect.getsource(service))
    assert len(found) == 4  # click, input, dropdown_options, select_dropdown
    message = found[0].replace("{params.index}", "9")
    assert message == GONE
    assert one(bu.action(click={"index": 9}), bu.ActionResult(extracted_content=message), bu.element("Add to cart")) == [
        {"action": "click", "params": {"index": 9}, "element": "Add to cart", "not_run": "element 9 was not available"}]


def test_every_action_browser_use_answers_this_way_is_marked():
    for planned in (bu.action(click={"index": 9}), bu.action(input={"index": 9, "text": "belt", "clear": True}),
                    bu.action(dropdown_options={"index": 9}), bu.action(select_dropdown={"index": 9, "text": "Large"})):
        (action,) = one(planned, bu.ActionResult(extracted_content=GONE))
        assert action["not_run"] == "element 9 was not available", action


def test_the_not_run_mark_is_narrow():
    def marked(planned, result):
        return [a for a in one(planned, result) if "not_run" in a]

    # Another element's index, or the words somewhere other than the start of the result.
    assert not marked(bu.action(click={"index": 12}), bu.ActionResult(extracted_content=GONE))
    assert not marked(bu.action(click={"index": 9}), bu.ActionResult(extracted_content="The page says: " + GONE))
    # An action with no element index (page text it read can say anything).
    assert not marked(bu.action(extract={"query": "errors"}), bu.ActionResult(extracted_content=GONE))
    # A click that happened.
    assert not marked(bu.action(click={"index": 9}), bu.ActionResult(extracted_content="Clicked button 'Add to cart'"))
    # A result that is an error stays an error, whatever text comes with it.
    (failed,) = one(bu.action(click={"index": 9}), bu.ActionResult(error=GONE))
    assert failed == {"action": "click", "params": {"index": 9}, "error": GONE}
    (failed,) = one(bu.action(click={"index": 9}), bu.ActionResult(error="Failed to click element 9", extracted_content=GONE))
    assert failed == {"action": "click", "params": {"index": 9}, "error": "Failed to click element 9"}
