"""A scripted stand-in for the async Anthropic client used by llm.py.

``install(monkeypatch, *replies)`` makes every llm.achat_tools / llm.acomplete_json call
take the next reply (the last one repeats). A reply is a response from ``text_response`` or
``tool_response``, an exception to raise, or a function of the request's keyword
arguments returning one of those. ``install`` returns the list that collects each
request's keyword arguments, so a test can look at exactly what would have been sent.
"""

import inspect
import itertools
import json
from types import SimpleNamespace

from anthropic.types import TextBlock, ToolUseBlock

import llm

_ids = itertools.count(1)


def _usage(input_tokens, output_tokens, cache_read, cache_write):
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )


def text_response(payload, *, model="claude-sonnet-5-5", input_tokens=100, output_tokens=20,
                  cache_read=0, cache_write=0, stop_reason="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        content=[TextBlock(type="text", text=text, citations=None)], stop_reason=stop_reason, stop_details=None,
        model=model, usage=_usage(input_tokens, output_tokens, cache_read, cache_write),
    )


def tool_response(name, args=None, *, text="", model="claude-sonnet-5-5", input_tokens=100, output_tokens=20,
                  cache_read=0, cache_write=0, extra_calls=()):
    """One model turn that calls a tool (and, with extra_calls, more tools in the same turn)."""
    content = []
    if text:
        content.append(TextBlock(type="text", text=text, citations=None))
    for call_name, call_args in [(name, args or {}), *extra_calls]:
        content.append(ToolUseBlock(type="tool_use", id=f"toolu_{next(_ids):04d}", name=call_name, input=call_args))
    return SimpleNamespace(
        content=content, stop_reason="tool_use", stop_details=None, model=model,
        usage=_usage(input_tokens, output_tokens, cache_read, cache_write),
    )


def no_tool_response(text="Let me think about that.", **kwargs):
    return text_response(text, **kwargs)


class _Messages:
    def __init__(self, replies, calls):
        self._replies = list(replies)
        self.calls = calls

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        if callable(reply):
            reply = reply(kwargs)
        if inspect.isawaitable(reply):
            reply = await reply
        if isinstance(reply, BaseException):
            raise reply
        return reply


def install(monkeypatch, *replies):
    calls = []
    messages = _Messages(replies, calls)

    async def close():
        return None

    client = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages), close=close)
    monkeypatch.setattr(llm, "_anthropic_async_client", lambda: client)
    return calls
