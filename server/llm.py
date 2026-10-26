"""LLM provider layer shared by the benchmark API, the arena and the comparison CLI.

``LLM_PROVIDER`` is ``anthropic`` (default) or ``openai``. The openai package is an optional extra,
imported only when that provider is used.

Models per role (``agent``, ``judge``, ``taskgen``): ``BENCHMARK_AGENT_MODEL``,
``BENCHMARK_JUDGE_MODEL``, ``BENCHMARK_TASKGEN_MODEL``. Defaults are ``claude-sonnet-5-5``
(anthropic) and ``gpt-4o`` (openai).

Effort per role (Anthropic only): ``BENCHMARK_AGENT_EFFORT`` / ``BENCHMARK_JUDGE_EFFORT`` /
``BENCHMARK_TASKGEN_EFFORT`` take low | medium | high | xhigh | max, or ``default`` to send none. The
agent defaults to ``medium`` on current Claude models. Judge and taskgen use the model's own default.

``LLM_FALLBACKS=default`` (the default, Anthropic only) sends the server-side ``fallbacks:
"default"`` parameter for models that accept it, so a safety-classifier decline is retried on
Anthropic's recommended fallback inside the same call. ``off`` disables it.

Every request, whatever the caller passes:

* has no ``temperature`` / ``top_p`` / ``top_k`` (current Sonnet and Haiku reject them)
* has no forced ``tool_choice``, tool calls use ``{"type": "auto"}``
* has no assistant prefill, JSON comes from structured outputs (``output_config.format``)
* has ``stop_reason`` checked: ``refusal`` and ``max_tokens`` raise ``LLMError`` instead of
  returning partial output
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

import anthropic

import runtime_env  # noqa: F401  (loads .env; telemetry off before browser_use loads)
from constants import cost_usd

log = logging.getLogger(__name__)

ANTHROPIC = "anthropic"
OPENAI = "openai"
PROVIDERS = (ANTHROPIC, OPENAI)

ROLES = ("agent", "judge", "taskgen")
ROLE_MODEL_ENV = {
    "agent": "BENCHMARK_AGENT_MODEL",
    "judge": "BENCHMARK_JUDGE_MODEL",
    "taskgen": "BENCHMARK_TASKGEN_MODEL",
}
ROLE_EFFORT_ENV = {
    "agent": "BENCHMARK_AGENT_EFFORT",
    "judge": "BENCHMARK_JUDGE_EFFORT",
    "taskgen": "BENCHMARK_TASKGEN_EFFORT",
}
DEFAULT_MODELS = {ANTHROPIC: "claude-sonnet-5-5", OPENAI: "gpt-4o"}
DEFAULT_EFFORT = {"agent": "medium", "judge": None, "taskgen": None}
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

# Non-streaming requests: the SDK refuses non-streaming calls whose max_tokens implies
# more than ten minutes of generation, and thinking counts toward max_tokens.
DEFAULT_MAX_TOKENS = 16000

# Server-side refusal fallback, "default" form (Anthropic picks the model by refusal category).
# Claude Haiku 5.5 has none, so it is not listed.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = frozenset({"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"})

# Claude models with adaptive thinking and the effort parameter. Older models (Haiku 4.5,
# Sonnet 4.5 and earlier) reject both, and still accept forced tool_choice.
_CURRENT_CLAUDE = re.compile(
    r"^(anthropic\.)?claude-("
    r"(sonnet|opus|haiku|fable|mythos)-5(-\d+)?"
    r"|opus-4-[678]|sonnet-4-6"
    r")$"
)
_STRUCTURED_OUTPUT_CLAUDE = re.compile(
    r"^(anthropic\.)?claude-("
    r"(sonnet|opus|haiku|fable|mythos)-5(-\d+)?"
    r"|opus-4-[158]|haiku-4-5"
    r")$"
)


class LLMError(RuntimeError):
    """A model call that produced no usable result.

    ``kind`` is "refusal", "max_tokens", "bad_json", "api" or "config". ``category`` is the refusal
    category when the API gave one, ``status_code`` the HTTP status for "api" errors, ``usage`` what
    the failed call still billed.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        model: str | None = None,
        stop_reason: str | None = None,
        category: str | None = None,
        status_code: int | None = None,
        usage: "Usage | None" = None,
        raw_text: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.model = model
        self.stop_reason = stop_reason
        self.category = category
        self.status_code = status_code
        self.usage = usage
        self.raw_text = raw_text


@dataclass
class Usage:
    """Token usage. ``input_tokens`` excludes cache reads and writes (Anthropic semantics)."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_input_tokens + other.cache_read_input_tokens,
            self.cache_creation_input_tokens + other.cache_creation_input_tokens,
        )

    def cost_usd(self, model: str | None) -> float | None:
        return cost_usd(
            model,
            self.input_tokens,
            self.output_tokens,
            self.cache_read_input_tokens,
            self.cache_creation_input_tokens,
        )

    def to_dict(self) -> dict[str, int]:
        data = asdict(self)
        data["total_tokens"] = self.total_tokens
        return data


class JSONResult(dict):
    """The parsed JSON object, plus what the call cost.

    A plain dict for existing uses (``result["success"]``, ``json.dumps``) with three extra
    attributes: ``usage``, ``model`` (the model that answered, which can differ from the requested
    one after a refusal fallback) and ``stop_reason``. ``cost_usd`` is derived from them and is None
    for unpriced models.
    """

    usage: Usage
    model: str
    stop_reason: str | None

    def __init__(self, data: Mapping[str, Any], *, usage: Usage, model: str, stop_reason: str | None):
        super().__init__(data)
        self.usage = usage
        self.model = model
        self.stop_reason = stop_reason

    @property
    def cost_usd(self) -> float | None:
        return self.usage.cost_usd(self.model)



def provider() -> str:
    value = (os.getenv("LLM_PROVIDER") or ANTHROPIC).strip().lower()
    if value not in PROVIDERS:
        raise LLMError(
            f"LLM_PROVIDER={value!r} is not supported; use one of {', '.join(PROVIDERS)}",
            kind="config",
        )
    return value


def model_for(role: str) -> str:
    """Model id for a role: its BENCHMARK_*_MODEL env var, else the provider default."""
    if role not in ROLE_MODEL_ENV:
        raise ValueError(f"unknown role {role!r}; expected one of {', '.join(ROLES)}")
    explicit = (os.getenv(ROLE_MODEL_ENV[role]) or "").strip()
    return explicit or DEFAULT_MODELS[provider()]


def is_current_claude(model: str) -> bool:
    """True for Claude models with adaptive thinking and effort (4.6 and later)."""
    return bool(_CURRENT_CLAUDE.match(model or ""))


def supports_structured_outputs(model: str) -> bool:
    return bool(_STRUCTURED_OUTPUT_CLAUDE.match(model or ""))


def effort_for(role: str, model: str) -> str | None:
    """Effort level to send for this role and model, or None to send none."""
    raw = (os.getenv(ROLE_EFFORT_ENV.get(role, ""), "") or "").strip().lower()
    if raw == "default":
        return None
    if raw:
        if raw not in EFFORT_LEVELS:
            raise LLMError(
                f"{ROLE_EFFORT_ENV[role]}={raw!r} is not one of {', '.join(EFFORT_LEVELS)} or 'default'",
                kind="config",
            )
        return raw
    default = DEFAULT_EFFORT.get(role)
    return default if default and is_current_claude(model) else None


def fallbacks_enabled(model: str) -> bool:
    if (os.getenv("LLM_FALLBACKS") or "default").strip().lower() in {"off", "0", "false", "no", "none"}:
        return False
    return model in FALLBACK_MODELS


def provider_key_present() -> bool:
    """Whether the active provider has a credential in the environment."""
    if provider() == OPENAI:
        return bool(os.getenv("OPENAI_API_KEY"))
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def api_key_name() -> str:
    """The setting that holds the active provider's key, for messages (never its value)."""
    try:
        return "OPENAI_API_KEY" if provider() == OPENAI else "ANTHROPIC_API_KEY"
    except LLMError:
        return "ANTHROPIC_API_KEY"


_KEY_REJECTED = re.compile(
    r"authentication_error|invalid x-api-key|invalid api key|incorrect api key|invalid_api_key"
    r"|error code: 401|401 unauthorized"
)


def key_rejected(error: object) -> bool:
    """Whether an error (an exception, or the text browser-use keeps of one) says the API key was refused."""
    if isinstance(error, LLMError) and error.kind == "api" and error.status_code in (401, 403):
        return True
    if getattr(error, "status_code", None) == 401:
        return True
    return bool(_KEY_REJECTED.search(str(error).lower()))


def describe() -> dict[str, Any]:
    """Provider and per-role models, for /health and logs. Never includes secrets."""
    prov = provider()
    return {
        "provider": prov,
        "models": {role: model_for(role) for role in ROLES},
        "key_present": provider_key_present(),
    }



def _anthropic_client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def _anthropic_async_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic()


def _import_openai():
    try:
        import openai
    except ImportError as exc:  # optional extra
        raise LLMError(
            "LLM_PROVIDER=openai needs the openai package: cd server && uv sync --extra openai",
            kind="config",
        ) from exc
    return openai


def _openai_client():
    return _import_openai().OpenAI()


def _openai_async_client():
    return _import_openai().AsyncOpenAI()



def strict_schema(schema: Mapping[str, Any] | type) -> dict[str, Any]:
    """A JSON schema (dict or pydantic model class) in the subset structured outputs accept.

    Adds ``additionalProperties: false`` to every object and moves unsupported
    constraints (minLength, minimum, ...) into descriptions, via the SDK's own helper.
    """
    return anthropic.transform_schema(schema if isinstance(schema, type) else dict(schema))


_FENCE_START = re.compile(r"^```(?:json)?\s*")
_FENCE_END = re.compile(r"\s*```$")


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from model text, tolerating code fences and surrounding prose."""
    raw = _FENCE_END.sub("", _FENCE_START.sub("", (text or "").strip()))
    candidates = [raw]
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        candidates.append(raw[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    raise ValueError("no JSON object in model output")


def _usage_from_anthropic(usage: Any) -> Usage:
    if usage is None:
        return Usage()
    return Usage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
    )


def usage_from_browser_use(summary: Any) -> Usage:
    """Usage from a browser-use UsageSummary (``history.usage`` or
    ``await agent.token_cost_service.get_usage_summary()``).

    browser-use's ``total_prompt_tokens`` already includes cache reads
    (``total_prompt_cached_tokens``); cache writes are reported separately. Price the
    result with ``usage.cost_usd(model)``.
    """
    if summary is None:
        return Usage()
    prompt = getattr(summary, "total_prompt_tokens", 0) or 0
    cached = getattr(summary, "total_prompt_cached_tokens", 0) or 0
    return Usage(
        input_tokens=max(prompt - cached, 0),
        output_tokens=getattr(summary, "total_completion_tokens", 0) or 0,
        cache_read_input_tokens=cached,
        cache_creation_input_tokens=getattr(summary, "total_prompt_cache_creation_tokens", 0) or 0,
    )


def _usage_from_openai(usage: Any) -> Usage:
    if usage is None:
        return Usage()
    return Usage(
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
    )


def _check_anthropic_stop(response: Any, model: str) -> None:
    stop = getattr(response, "stop_reason", None)
    if stop == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) if details is not None else None
        raise LLMError(
            f"{model} declined the request (stop_reason=refusal, category={category})",
            kind="refusal",
            model=getattr(response, "model", None) or model,
            stop_reason=stop,
            category=category,
            usage=_usage_from_anthropic(getattr(response, "usage", None)),
        )
    if stop == "max_tokens":
        raise LLMError(
            f"{model} hit max_tokens before finishing; raise max_tokens or lower effort",
            kind="max_tokens",
            model=getattr(response, "model", None) or model,
            stop_reason=stop,
            usage=_usage_from_anthropic(getattr(response, "usage", None)),
        )


def _anthropic_text(response: Any) -> str:
    return "".join(
        getattr(block, "text", "") or ""
        for block in getattr(response, "content", None) or []
        if getattr(block, "type", None) == "text"
    )


def _api_error(exc: Exception, model: str) -> LLMError:
    status = getattr(exc, "status_code", None)
    message = getattr(exc, "message", None) or str(exc)
    return LLMError(f"{type(exc).__name__} from {model}: {message}", kind="api", model=model, status_code=status)


def _anthropic_errors() -> tuple[type[BaseException], ...]:
    return (anthropic.APIError,)


def _openai_errors() -> tuple[type[BaseException], ...]:
    try:
        import openai
    except ImportError:
        return ()
    return (openai.APIError,)


def _anthropic_call_kwargs(model: str) -> dict[str, Any]:
    """Extra kwargs that route a call through the beta endpoint with refusal fallback."""
    if fallbacks_enabled(model):
        return {"betas": [FALLBACK_BETA], "fallbacks": "default"}
    return {}


def _create(client: Any, kwargs: dict[str, Any]) -> Any:
    extra = _anthropic_call_kwargs(kwargs["model"])
    if extra:
        return client.beta.messages.create(**kwargs, **extra)
    return client.messages.create(**kwargs)


async def _acreate(client: Any, kwargs: dict[str, Any]) -> Any:
    extra = _anthropic_call_kwargs(kwargs["model"])
    if extra:
        return await client.beta.messages.create(**kwargs, **extra)
    return await client.messages.create(**kwargs)


def _resolve(role: str, model: str | None) -> str:
    return (model or "").strip() or model_for(role)



def _json_request(
    system: str | None,
    prompt: str,
    schema: Mapping[str, Any] | type | None,
    model: str,
    max_tokens: int,
    effort: str | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    output_config: dict[str, Any] = {}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": strict_schema(schema)}
    if effort:
        output_config["effort"] = effort
    if output_config:
        kwargs["output_config"] = output_config
    return kwargs


def _json_result_from_anthropic(response: Any, model: str) -> JSONResult:
    _check_anthropic_stop(response, model)
    usage = _usage_from_anthropic(getattr(response, "usage", None))
    served_by = getattr(response, "model", None) or model
    text = _anthropic_text(response)
    try:
        data = parse_json_object(text)
    except ValueError as exc:
        raise LLMError(
            f"{served_by} returned no parseable JSON object",
            kind="bad_json",
            model=served_by,
            stop_reason=getattr(response, "stop_reason", None),
            usage=usage,
            raw_text=text[:2000],
        ) from exc
    return JSONResult(data, usage=usage, model=served_by, stop_reason=getattr(response, "stop_reason", None))


def _openai_json_messages(system: str | None, prompt: str) -> list[dict[str, str]]:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def _json_result_from_openai(response: Any, model: str) -> JSONResult:
    choice = response.choices[0]
    usage = _usage_from_openai(getattr(response, "usage", None))
    served_by = getattr(response, "model", None) or model
    finish = getattr(choice, "finish_reason", None)
    message = choice.message
    if getattr(message, "refusal", None) or finish == "content_filter":
        raise LLMError(f"{served_by} declined the request", kind="refusal", model=served_by, stop_reason=finish, usage=usage)
    if finish == "length":
        raise LLMError(f"{served_by} hit its token limit before finishing", kind="max_tokens", model=served_by, stop_reason=finish, usage=usage)
    text = message.content or ""
    try:
        data = parse_json_object(text)
    except ValueError as exc:
        raise LLMError(
            f"{served_by} returned no parseable JSON object",
            kind="bad_json", model=served_by, stop_reason=finish, usage=usage, raw_text=text[:2000],
        ) from exc
    return JSONResult(data, usage=usage, model=served_by, stop_reason=finish)


def complete_json(
    system: str | None,
    prompt: str,
    schema: Mapping[str, Any] | type | None = None,
    *,
    model: str | None = None,
    role: str = "judge",
    max_tokens: int = DEFAULT_MAX_TOKENS,
    effort: str | None = None,
) -> JSONResult:
    """One model call that must return a JSON object.

    ``schema`` is a JSON schema dict or a pydantic model class. With Anthropic it is enforced
    through structured outputs; pass None to rely on the prompt alone. ``model`` overrides
    ``model_for(role)``, ``effort`` overrides ``effort_for(role, model)``.

    Raises LLMError on refusal, truncation, unparseable output or an API error. OpenAI uses chat
    completions in JSON mode (``response_format={"type": "json_object"}``) and does not enforce the
    schema.
    """
    if provider() == OPENAI:
        model = _resolve(role, model)
        client = _openai_client()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=_openai_json_messages(system, prompt),
                response_format={"type": "json_object"},
            )
        except _openai_errors() as exc:
            raise _api_error(exc, model) from exc
        return _json_result_from_openai(response, model)

    model = _resolve(role, model)
    kwargs = _json_request(system, prompt, schema, model, max_tokens, effort or effort_for(role, model))
    client = _anthropic_client()
    try:
        response = _create(client, kwargs)
    except _anthropic_errors() as exc:
        raise _api_error(exc, model) from exc
    finally:
        _close(client)
    return _json_result_from_anthropic(response, model)


async def acomplete_json(
    system: str | None,
    prompt: str,
    schema: Mapping[str, Any] | type | None = None,
    *,
    model: str | None = None,
    role: str = "judge",
    max_tokens: int = DEFAULT_MAX_TOKENS,
    effort: str | None = None,
) -> JSONResult:
    """Async twin of complete_json."""
    if provider() == OPENAI:
        model = _resolve(role, model)
        client = _openai_async_client()
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=_openai_json_messages(system, prompt),
                response_format={"type": "json_object"},
            )
        except _openai_errors() as exc:
            raise _api_error(exc, model) from exc
        return _json_result_from_openai(response, model)

    model = _resolve(role, model)
    kwargs = _json_request(system, prompt, schema, model, max_tokens, effort or effort_for(role, model))
    client = _anthropic_async_client()
    try:
        response = await _acreate(client, kwargs)
    except _anthropic_errors() as exc:
        raise _api_error(exc, model) from exc
    finally:
        await _aclose(client)
    return _json_result_from_anthropic(response, model)


def _close(client: Any) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:  # closing must never mask the real result
            pass


async def _aclose(client: Any) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        try:
            result = close()
            if hasattr(result, "__await__"):
                await result
        except Exception:
            pass


# chat_tools: one turn of a hand-written tool-calling loop.
# Tools are given in Anthropic's shape: {"name", "description", "input_schema"} (an optional
# "strict": True is passed through). The transcript starts with user_message(...). Grow it only with
# append_assistant() and append_tool_results(), which keep it in the active provider's wire format
# and keep each assistant turn exactly as the model returned it. Current Claude models need the
# thinking blocks sent back unchanged.
# The returned turn is a dict with:
#   text                str, the turn's visible text ("" if none)
#   tool_calls          [{"id", "name", "input": dict}], in the order the model made them
#   stop_reason         "tool_use" | "end_turn" | "stop_sequence" | "pause_turn" | ...
#   usage               Usage.to_dict() for this call
#   model               the model that answered
#   cost_usd            float | None
#   provider            "anthropic" | "openai"
#   assistant_message   the assistant turn to append (use the append_* helpers)


def user_message(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}


def tool_result(tool_use_id: str, content: Any, *, is_error: bool = False) -> dict[str, Any]:
    """A provider-neutral tool result for append_tool_results.

    ``content`` is a string (dicts and lists are JSON-encoded).
    """
    if not isinstance(content, str):
        content = json.dumps(content, default=str)
    return {"tool_use_id": tool_use_id, "content": content, "is_error": bool(is_error)}


def append_assistant(messages: Sequence[dict[str, Any]], turn: Mapping[str, Any]) -> list[dict[str, Any]]:
    """New transcript: messages plus the turn's assistant message (for turns without tool calls)."""
    return [*messages, turn["assistant_message"]]


def append_tool_results(
    messages: Sequence[dict[str, Any]],
    turn: Mapping[str, Any],
    results: Iterable[Mapping[str, Any]],
    *,
    extra_text: str | None = None,
) -> list[dict[str, Any]]:
    """New transcript: messages, the assistant turn and every tool result.

    ``results`` holds one tool_result(...) per tool call in the turn (any order); a
    missing one raises ValueError because the API rejects unanswered tool calls.
    ``extra_text`` (optional) is a user note placed after the results, e.g. a nudge
    to keep going. The input list is not modified.
    """
    by_id = {r["tool_use_id"]: r for r in results}
    calls = list(turn.get("tool_calls") or [])
    missing = [c["id"] for c in calls if c["id"] not in by_id]
    if missing:
        raise ValueError(f"missing tool results for tool call ids: {', '.join(missing)}")
    unknown = sorted(set(by_id) - {c["id"] for c in calls})
    if unknown:
        raise ValueError(f"tool results for ids the turn did not call: {', '.join(unknown)}")

    out = [*messages, turn["assistant_message"]]
    if turn.get("provider") == OPENAI:
        for call in calls:
            result = by_id[call["id"]]
            content = result["content"]
            if result.get("is_error"):
                content = f"ERROR: {content}"
            out.append({"role": "tool", "tool_call_id": call["id"], "content": content})
        if extra_text:
            out.append({"role": "user", "content": extra_text})
        return out

    blocks: list[dict[str, Any]] = []
    for call in calls:
        result = by_id[call["id"]]
        block: dict[str, Any] = {"type": "tool_result", "tool_use_id": call["id"], "content": result["content"]}
        if result.get("is_error"):
            block["is_error"] = True
        blocks.append(block)
    if extra_text:
        blocks.append({"type": "text", "text": extra_text})
    out.append({"role": "user", "content": blocks})
    return out


def _tool_choice(tools: Sequence[Any] | None, parallel_tool_calls: bool) -> dict[str, Any] | None:
    if not tools:
        return None
    choice: dict[str, Any] = {"type": "auto"}
    if not parallel_tool_calls:
        choice["disable_parallel_tool_use"] = True
    return choice


def _chat_request(
    system: str | None,
    messages: Sequence[dict[str, Any]],
    tools: Sequence[dict[str, Any]] | None,
    model: str,
    max_tokens: int,
    effort: str | None,
    parallel_tool_calls: bool,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": list(messages)}
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = list(tools)
        kwargs["tool_choice"] = _tool_choice(tools, parallel_tool_calls)
    if effort:
        kwargs["output_config"] = {"effort": effort}
    return kwargs


def _block_to_param(block: Any) -> dict[str, Any] | None:
    """Content block as returned -> dict that can be sent back. Fallback markers are dropped."""
    if isinstance(block, Mapping):
        data = dict(block)
    elif hasattr(block, "model_dump"):
        data = block.model_dump(mode="json", exclude_none=True)
    else:
        data = dict(vars(block))
    if data.get("type") == "fallback":
        return None
    return data


def _turn_from_anthropic(response: Any, model: str) -> dict[str, Any]:
    _check_anthropic_stop(response, model)
    usage = _usage_from_anthropic(getattr(response, "usage", None))
    served_by = getattr(response, "model", None) or model
    content = [p for p in (_block_to_param(b) for b in getattr(response, "content", None) or []) if p is not None]
    tool_calls = [
        {"id": b["id"], "name": b["name"], "input": b.get("input") or {}}
        for b in content
        if b.get("type") == "tool_use"
    ]
    text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    return {
        "text": text,
        "tool_calls": tool_calls,
        "stop_reason": getattr(response, "stop_reason", None),
        "usage": usage.to_dict(),
        "model": served_by,
        "cost_usd": usage.cost_usd(served_by),
        "provider": ANTHROPIC,
        "assistant_message": {"role": "assistant", "content": content},
    }


def _openai_tools(tools: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out = []
    for tool in tools or []:
        if tool.get("type") == "function":
            out.append(tool)
            continue
        out.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
            },
        })
    return out


def _openai_chat_kwargs(system, messages, tools, model, parallel_tool_calls) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": model, "messages": ([{"role": "system", "content": system}] if system else []) + list(messages)}
    if tools:
        kwargs["tools"] = _openai_tools(tools)
        kwargs["parallel_tool_calls"] = parallel_tool_calls
    return kwargs


def _turn_from_openai(response: Any, model: str) -> dict[str, Any]:
    choice = response.choices[0]
    usage = _usage_from_openai(getattr(response, "usage", None))
    served_by = getattr(response, "model", None) or model
    finish = getattr(choice, "finish_reason", None)
    message = choice.message
    if getattr(message, "refusal", None) or finish == "content_filter":
        raise LLMError(f"{served_by} declined the request", kind="refusal", model=served_by, stop_reason=finish, usage=usage)
    if finish == "length":
        raise LLMError(f"{served_by} hit its token limit before finishing", kind="max_tokens", model=served_by, stop_reason=finish, usage=usage)
    raw_calls = getattr(message, "tool_calls", None) or []
    tool_calls = []
    for call in raw_calls:
        try:
            args = json.loads(call.function.arguments or "{}")
        except ValueError:
            args = {"_raw_arguments": call.function.arguments}
        tool_calls.append({"id": call.id, "name": call.function.name, "input": args})
    assistant: dict[str, Any] = {"role": "assistant", "content": message.content}
    if raw_calls:
        assistant["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
            for c in raw_calls
        ]
    stop = {"tool_calls": "tool_use", "stop": "end_turn"}.get(finish, finish)
    return {
        "text": message.content or "",
        "tool_calls": tool_calls,
        "stop_reason": stop,
        "usage": usage.to_dict(),
        "model": served_by,
        "cost_usd": usage.cost_usd(served_by),
        "provider": OPENAI,
        "assistant_message": assistant,
    }


def chat_tools(
    system: str | None,
    messages: Sequence[dict[str, Any]],
    tools: Sequence[dict[str, Any]] | None,
    *,
    model: str | None = None,
    role: str = "agent",
    max_tokens: int = DEFAULT_MAX_TOKENS,
    effort: str | None = None,
    parallel_tool_calls: bool = True,
) -> dict[str, Any]:
    """One model turn with tools (tool_choice auto). See the block comment above for the shape.

    ``parallel_tool_calls=False`` asks for at most one tool call per turn.
    Raises LLMError on refusal, max_tokens or an API error.
    """
    if provider() == OPENAI:
        model = _resolve(role, model)
        client = _openai_client()
        try:
            response = client.chat.completions.create(**_openai_chat_kwargs(system, messages, tools, model, parallel_tool_calls))
        except _openai_errors() as exc:
            raise _api_error(exc, model) from exc
        return _turn_from_openai(response, model)

    model = _resolve(role, model)
    kwargs = _chat_request(system, messages, tools, model, max_tokens, effort or effort_for(role, model), parallel_tool_calls)
    client = _anthropic_client()
    try:
        response = _create(client, kwargs)
    except _anthropic_errors() as exc:
        raise _api_error(exc, model) from exc
    finally:
        _close(client)
    return _turn_from_anthropic(response, model)


async def achat_tools(
    system: str | None,
    messages: Sequence[dict[str, Any]],
    tools: Sequence[dict[str, Any]] | None,
    *,
    model: str | None = None,
    role: str = "agent",
    max_tokens: int = DEFAULT_MAX_TOKENS,
    effort: str | None = None,
    parallel_tool_calls: bool = True,
) -> dict[str, Any]:
    """Async twin of chat_tools."""
    if provider() == OPENAI:
        model = _resolve(role, model)
        client = _openai_async_client()
        try:
            response = await client.chat.completions.create(**_openai_chat_kwargs(system, messages, tools, model, parallel_tool_calls))
        except _openai_errors() as exc:
            raise _api_error(exc, model) from exc
        return _turn_from_openai(response, model)

    model = _resolve(role, model)
    kwargs = _chat_request(system, messages, tools, model, max_tokens, effort or effort_for(role, model), parallel_tool_calls)
    client = _anthropic_async_client()
    try:
        response = await _acreate(client, kwargs)
    except _anthropic_errors() as exc:
        raise _api_error(exc, model) from exc
    finally:
        await _aclose(client)
    return _turn_from_anthropic(response, model)



def agent_llm(model: str | None = None, *, max_tokens: int = DEFAULT_MAX_TOKENS, effort: str | None = None):
    """Chat model object for ``browser_use.Agent(llm=...)``.

    Anthropic models with structured outputs (all current Claude models) get the
    ``agent_llm.ClaudeAgentChat`` adapter. It uses structured outputs for small step schemas and
    validates and repairs the tool call for the full one, counting every attempt's tokens (see that
    module). Other Claude models get browser-use's own ChatAnthropic. Either way there are no
    sampling params, adaptive thinking on current models (which also makes browser-use use
    tool_choice auto), effort from effort_for("agent", model), and the server-side refusal fallback
    where accepted. OpenAI gets browser-use's ChatOpenAI.
    """
    model = _resolve("agent", model)
    if provider() == OPENAI:
        from browser_use import ChatOpenAI

        return ChatOpenAI(model=model)

    if supports_structured_outputs(model):
        from agent_llm import ClaudeAgentChat as ChatAnthropic
    else:
        from browser_use import ChatAnthropic

    settings: dict[str, Any] = {"model": model, "max_tokens": max_tokens}
    if is_current_claude(model):
        settings["thinking"] = {"type": "adaptive"}
        level = effort or effort_for("agent", model)
        if level:
            settings["output_config"] = {"effort": level}
    if fallbacks_enabled(model):
        # browser-use adds the older array-form beta unless a fallback beta is present.
        settings["betas"] = [FALLBACK_BETA]
        settings["fallbacks"] = "default"
    return ChatAnthropic(**settings)
