"""Fakes for the model API and the browser, shared by the backend tests.

``install_fake_anthropic(monkeypatch, response_or_error, ...)`` replaces the Anthropic
client factory in ``llm.py`` so ``complete_json`` runs for real (schema, stop_reason
handling, usage and cost) without a network. It returns the list of request kwargs.

``FakeBrowserSession`` stands in for the parts of browser-use's BrowserSession the live
preview uses: the agent's focused tab, browser-use's session pool and CDP
``Page.captureScreenshot``.
"""

import asyncio
import base64
import json
from types import SimpleNamespace

from anthropic.types import RefusalStopDetails, TextBlock

import llm


def text_response(
    payload,
    *,
    stop_reason="end_turn",
    model="claude-sonnet-5-5",
    input_tokens=100,
    output_tokens=20,
    stop_details=None,
):
    """A Messages API response carrying ``payload`` (a dict, dumped to JSON, or raw text)."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        content=[TextBlock(type="text", text=text, citations=None)],
        stop_reason=stop_reason,
        stop_details=stop_details,
        model=model,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


def refusal_response(category="cyber", model="claude-sonnet-5-5"):
    """A response the safety classifier stopped (stop_reason == "refusal")."""
    return SimpleNamespace(
        content=[],
        stop_reason="refusal",
        stop_details=RefusalStopDetails(type="refusal", category=category, explanation=None),
        model=model,
        usage=SimpleNamespace(
            input_tokens=50,
            output_tokens=0,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


class _Messages:
    def __init__(self, results, calls):
        self._results = list(results)
        self.calls = calls

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._results.pop(0) if len(self._results) > 1 else self._results[0]
        if isinstance(item, BaseException):
            raise item
        return item


def install_fake_anthropic(monkeypatch, *results):
    """Make every ``llm`` model call return/raise ``results`` in order (the last repeats).

    Returns the list that collects each request's keyword arguments.
    """
    calls: list[dict] = []
    messages = _Messages(results, calls)
    client = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages), close=lambda: None)
    monkeypatch.setattr(llm, "_anthropic_client", lambda: client)
    return calls


class FakeBrowserSession:
    """The agent's browser as the live preview sees it.

    No tab until ``open_tab()``; ``show(url, picture)`` is a navigation. Every capture is
    recorded (``captures``, ``session_requests``) and can be made to fail (``fail_next``),
    hang (``hang_next``) or be slow (``delay``). ``attached`` False is a tab whose CDP
    session has gone (it just closed).
    """

    TARGET = "TARGET-1"

    def __init__(self):
        self.agent_focus_target_id = None
        self.url = "about:blank"
        self.picture = b"\xff\xd8blank"
        self.attached = True
        self.captures = 0
        self.params = []
        self.session_requests = []  # (target_id, focus) for every get_or_create_cdp_session
        self.fail_next = 0
        self.hang_next = 0
        self.delay = 0.0
        self.in_flight = 0
        self.max_in_flight = 0
        self.session_manager = SimpleNamespace(get_target=self._get_target, validate_session=self._validate_session)

    def open_tab(self):
        self.agent_focus_target_id = self.TARGET

    def show(self, url, picture):
        self.url = url
        self.picture = picture

    def _get_target(self, target_id):
        if target_id != self.agent_focus_target_id:
            return None
        return SimpleNamespace(target_id=target_id, target_type="page", url=self.url)

    async def _validate_session(self, target_id):
        return self.attached and target_id == self.agent_focus_target_id

    async def get_or_create_cdp_session(self, target_id=None, focus=True):
        self.session_requests.append((target_id, focus))
        page = SimpleNamespace(captureScreenshot=self._capture)
        return SimpleNamespace(session_id="SESSION-1", cdp_client=SimpleNamespace(send=SimpleNamespace(Page=page)))

    async def _capture(self, params=None, session_id=None):
        self.captures += 1
        self.params.append(params)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.hang_next:
                self.hang_next -= 1
                await asyncio.Event().wait()
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail_next:
                self.fail_next -= 1
                raise RuntimeError("Target closed")
            return {"data": base64.b64encode(self.picture).decode()}
        finally:
            self.in_flight -= 1
