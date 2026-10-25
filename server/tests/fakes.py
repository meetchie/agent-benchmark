"""Fakes for the model API, shared by the backend tests.

``install_fake_anthropic(monkeypatch, response_or_error, ...)`` replaces the Anthropic
client factory in ``llm.py`` so ``complete_json`` runs for real (schema, stop_reason
handling, usage and cost) without a network. It returns the list of request kwargs.
"""

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
