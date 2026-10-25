"""browser-use chat model for current Claude models.

browser-use's own ChatAnthropic asks for every agent step ("AgentOutput": thinking,
memory, next goal, a list of actions) through one tool call. On current Claude models:

* A forced tool call (``tool_choice: {"type": "tool"}``) is rejected with HTTP 400 on
  claude-sonnet-5-5 and claude-opus-5-5. browser-use switches to ``auto`` only when
  thinking is configured, which llm.agent_llm() always does for these models.
* With ``tool_choice: auto`` and the one AgentOutput tool, claude-sonnet-5-5 calls the
  action itself (``find_elements``, ``done``, ``click``) as if it were a tool, with only
  that action's parameters and none of the step's thinking/memory/next goal (2 of 2 model
  steps in a smoke run and 27 of 27 in an arena run on 2026-10-24). Stock
  browser-use validates that input as AgentOutput, fails the step, retries it from
  scratch, and never counts the failed call's tokens.
* Structured outputs (``output_config.format``) would guarantee the shape, but the full
  AgentOutput schema (about 17 KB, 15 ``anyOf`` branches) is rejected with HTTP 400
  "The compiled grammar is too large". Small step schemas (the final "done" step, the
  run judge) compile fine.

ClaudeAgentChat keeps everything else from ChatAnthropic (message serialization, client
options, usage accounting, error mapping, refusal-fallback settings) and changes how a
structured step is requested:

1. Small schemas (``fits_structured_outputs``) use structured outputs: the reply always
   parses. If the API still rejects the grammar, that schema is remembered and step 2
   is used for it from then on.
2. Larger schemas use tools, with ``tool_choice: auto``, presented so that the model's
   natural call is a valid step: one tool per available action, named after it, whose
   input is the step model's own top-level fields (evaluation_previous_goal, memory,
   next_goal, ... with the step model's required list) followed by that action's
   parameters. The ``thinking`` field is left out (ACTION_TOOL_OMITTED_FIELDS): asking the
   model to write its reasoning into a field drew a ``reasoning_extraction`` refusal, the
   model already thinks natively (adaptive thinking), and browser-use only logs that field.
   Several actions in one step are several calls, in order. When the actions
   cannot be presented that way (no action list, a parameter type that is not a model,
   a name the API would reject), the single step tool is sent instead. The reply:

   a. A call to the step tool itself (by its name) that validates is returned as is.
   b. A reply whose every tool call names an available action is assembled locally:
      ``action = [{<name>: <params>}, ...]`` in call order, the step fields taken from
      the calls (first non-empty value of each), the reply's visible text as
      ``next_goal`` when none was given. Parameters sent as JSON text (``"5"``,
      ``"true"``, ``"[]"``, ``"null"``) are decoded only where they failed to validate.
      A step-tool call holding one action object instead of a list, or its actions at
      the top level, is reshaped the same way. Nothing is guessed: an unknown name, or
      a result that does not validate as the step model, goes to (c).
   c. Otherwise the model's turn is appended unchanged together with an ``is_error``
      tool result for every call naming what was wrong, and the model is asked again
      (up to ``max_repairs`` times). Every attempt's tokens are summed into the returned
      usage, so repairs are paid for and counted.

   Why per-action tools and not only (b) behind the one AgentOutput tool: offered the one
   tool, the model called a bare action on all 27 step calls of an arena run (vhlistings,
   2026-10-24), so (b) alone gives one request per step but steps with no evaluation,
   memory or next goal, the fields browser-use feeds back to the model as its history.
   With per-action tools a second run filled them on 21 of 27 steps, still one request
   per step, for about 4.9k more prompt tokens per request (mostly cache reads).

Plain-text calls (no output format) go through ChatAnthropic unchanged. Nothing here sends
temperature/top_p/top_k, forces a tool, or prefills an assistant turn.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import re
import typing
from dataclasses import dataclass, field
from typing import Any, ClassVar, TypeVar

import anthropic
from anthropic import APIConnectionError, APIStatusError, BadRequestError, RateLimitError, omit
from pydantic import BaseModel, RootModel, ValidationError

import runtime_env  # noqa: F401  (telemetry off before browser_use loads)
from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.anthropic.serializer import AnthropicMessageSerializer
from browser_use.llm.exceptions import ModelOutputTruncatedError, ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

T = TypeVar("T", bound=BaseModel)

log = logging.getLogger(__name__)

# Largest step schema sent through structured outputs. The 2 KB / 7-anyOf "done" schema
# compiles; the 17 KB / 15-anyOf AgentOutput schema does not. Stay well below the latter.
STRUCTURED_MAX_BYTES = 4000
STRUCTURED_MAX_ANYOF = 8


class ModelRefusalError(ModelProviderError):
    """The model (or its safety classifier) declined the step: stop_reason == "refusal"."""

    def __init__(self, message: str, *, model: str, category: str | None = None):
        super().__init__(message=message, status_code=422, model=model)
        self.category = category


def optimized_schema(output_format: type[BaseModel]) -> dict[str, Any]:
    """browser-use's optimized JSON schema for a step model (refs inlined, no title)."""
    schema = SchemaOptimizer.create_optimized_json_schema(output_format)
    schema.pop("title", None)
    return schema


def step_schema(output_format: type[BaseModel]) -> dict[str, Any]:
    """The step schema in the structured-outputs subset (additionalProperties: false, ...)."""
    return anthropic.transform_schema(optimized_schema(output_format))


def fits_structured_outputs(schema: dict[str, Any]) -> bool:
    text = json.dumps(schema)
    return len(text) <= STRUCTURED_MAX_BYTES and text.count('"anyOf"') <= STRUCTURED_MAX_ANYOF


def _schema_key(schema: dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(schema, sort_keys=True).encode()).hexdigest()


def _add_usage(a: ChatInvokeUsage | None, b: ChatInvokeUsage | None) -> ChatInvokeUsage | None:
    if a is None or b is None:
        return a or b

    def plus(x, y):
        if x is None and y is None:
            return None
        return (x or 0) + (y or 0)

    return ChatInvokeUsage(
        prompt_tokens=a.prompt_tokens + b.prompt_tokens,
        completion_tokens=a.completion_tokens + b.completion_tokens,
        total_tokens=a.total_tokens + b.total_tokens,
        prompt_cached_tokens=plus(a.prompt_cached_tokens, b.prompt_cached_tokens),
        prompt_cache_creation_tokens=plus(a.prompt_cache_creation_tokens, b.prompt_cache_creation_tokens),
        prompt_cache_creation_5m_tokens=plus(a.prompt_cache_creation_5m_tokens, b.prompt_cache_creation_5m_tokens),
        prompt_cache_creation_1h_tokens=plus(a.prompt_cache_creation_1h_tokens, b.prompt_cache_creation_1h_tokens),
        prompt_image_tokens=plus(a.prompt_image_tokens, b.prompt_image_tokens),
        pricing_multiplier=a.pricing_multiplier or b.pricing_multiplier,
    )


def _validation_summary(exc: Exception, limit: int = 1500) -> str:
    if isinstance(exc, ValidationError):
        lines = []
        for err in exc.errors()[:12]:
            loc = ".".join(str(part) for part in err.get("loc", ())) or "(root)"
            lines.append(f"- {loc}: {err.get('msg')}")
        text = "\n".join(lines)
    else:
        text = str(exc)
    return text[:limit]


# -- actions called as tools ---------------------------------------------------


@functools.lru_cache(maxsize=64)
def action_models(output_format: type[BaseModel]) -> dict[str, type[BaseModel]]:
    """Registered action name -> its one-field ActionModel, read off ``output_format.action``.

    browser-use's registry types ``action`` as ``list[X]``, where X is one single-field
    ActionModel (one action registered) or a RootModel over a Union of them. Empty for a
    step model without such a list.
    """
    action = output_format.model_fields.get("action")
    if action is None or typing.get_origin(action.annotation) is not list:
        return {}
    (item,) = typing.get_args(action.annotation) or (None,)
    members: tuple[Any, ...] = (item,)
    if isinstance(item, type) and issubclass(item, RootModel):
        root = item.model_fields["root"].annotation
        members = typing.get_args(root) or (root,)
    found: dict[str, type[BaseModel]] = {}
    for member in members:
        if isinstance(member, type) and issubclass(member, BaseModel) and len(member.model_fields) == 1:
            (name,) = member.model_fields
            found[name] = member
    return found


def _param_fields(model: type[BaseModel], name: str) -> dict[str, Any]:
    params = model.model_fields[name].annotation
    return dict(params.model_fields) if isinstance(params, type) and issubclass(params, BaseModel) else {}


def _accepts_none(annotation: Any) -> bool:
    return annotation is None or annotation is type(None) or type(None) in typing.get_args(annotation)


def _as_object(value: Any, what: str) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        value = json.loads(value) if value.strip() else {}
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be an object, got {type(value).__name__}")
    return dict(value)


def _decode_failed(values: dict[str, Any], keys: set[Any]) -> dict[str, Any]:
    """``values`` with the string values under ``keys`` JSON-decoded where they decode."""
    decoded = dict(values)
    for key in keys:
        value = decoded.get(key)
        if isinstance(value, str):
            try:
                decoded[key] = json.loads(value)
            except ValueError:
                pass
    return decoded


def _action_params(name: str, params: Any, model: type[BaseModel]) -> dict[str, Any]:
    """Parameters for action ``name`` that validate as ``model``; raises when there are none.

    The model often sends an action's parameters as JSON text (``"5"``, ``"true"``, ``"[]"``,
    ``"null"``) when it calls the action as a tool. Pydantic already reads "5" and "true"
    for int/bool fields; "null" becomes None where the field allows None, and any other
    string that failed validation is JSON-decoded once. Valid strings are never touched.
    """
    params = _as_object(params, f"{name} parameters")
    fields = _param_fields(model, name)
    if name not in fields and set(params) == {name} and isinstance(params[name], dict):
        params = dict(params[name])  # {"click": {"index": 3}} as the click input
    for key, value in params.items():
        spec = fields.get(key)
        if spec is not None and isinstance(value, str) and value.strip() == "null" and _accepts_none(spec.annotation):
            params[key] = None
    try:
        model.model_validate({name: params})
        return params
    except ValidationError as exc:
        failed = {err["loc"][1] for err in exc.errors() if len(err["loc"]) > 1 and err["loc"][0] == name}
        decoded = _decode_failed(params, failed)
        if decoded == params:
            raise
        model.model_validate({name: decoded})
        return decoded


def build_step(
    output_format: type[T], step_fields: dict[str, Any], calls: list[tuple[str, Any]], text: str = ""
) -> T:
    """The step model for ``calls`` ((action name, parameters) in order) plus the step's own fields.

    ``text`` (the reply's visible text) becomes ``next_goal`` when the model stated none.
    Step fields are all optional in browser-use's AgentOutput: one that still does not
    validate after JSON decoding is dropped rather than losing the step. Raises ValueError
    or ValidationError when an action is unknown or does not validate.
    """
    models = action_models(output_format)
    if not calls:
        raise ValueError("no action given")
    actions = []
    for name, params in calls:
        model = models.get(name)
        if model is None:
            raise ValueError(f"{name!r} is not an available action")
        actions.append({name: _action_params(name, params, model)})
    values = dict(step_fields)
    if text.strip() and not values.get("next_goal") and "next_goal" in output_format.model_fields:
        values["next_goal"] = text.strip()
    for _ in range(3):
        try:
            return output_format.model_validate({**values, "action": actions})
        except ValidationError as exc:
            bad = {err["loc"][0] for err in exc.errors() if err["loc"] and err["loc"][0] in values}
            if not bad:
                raise
            decoded = _decode_failed(values, bad)
            values = decoded if decoded != values else {k: v for k, v in values.items() if k not in bad}
    return output_format.model_validate({**values, "action": actions})


def step_from_action_calls(calls: list[tuple[str, Any]], output_format: type[T], text: str = "") -> T:
    """The step model for a reply whose tool calls each name an action (see action_tools).

    The step fields in the calls' inputs (memory, next_goal, ...) go to the step, the first
    non-empty value of each winning, unless that action has a parameter of the same name.
    """
    models = action_models(output_format)
    own_fields = set(output_format.model_fields) - {"action"}
    step_fields: dict[str, Any] = {}
    plain: list[tuple[str, Any]] = []
    for name, params in calls:
        if name not in models:
            raise ValueError(f"{name!r} is not an available action")
        params = _as_object(params, f"{name} parameters")
        for key in sorted(own_fields - set(_param_fields(models[name], name))):
            if key in params:
                value = params.pop(key)
                if key not in step_fields and value not in (None, "", [], "null"):
                    step_fields[key] = value
        plain.append((name, params))
    return build_step(output_format, step_fields, plain, text)


_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# Step fields the action tools do not ask for. browser-use's AgentOutput.thinking is a
# written-out reasoning block: in browser-use 0.13.11 nothing reads it beyond logging
# (log_response at DEBUG, the demo-mode overlay, saved-history dumps; agent_history,
# memory compaction and the judge use evaluation/memory/next_goal only). Requiring it in
# every action tool drew a reasoning_extraction refusal on 1 of 27 arena steps
# (2026-10-24), and llm.agent_llm() already runs these models with adaptive thinking. The
# pydantic field is optional, so a step without it validates; a call that still sends it
# is accepted and the value kept. browser-use's own prompt and use_thinking stay as shipped.
ACTION_TOOL_OMITTED_FIELDS = frozenset({"thinking"})

ACTION_TOOL_NOTE = (
    "One call is one step: fill the step fields as your output format describes, then the parameters. "
    "Several actions in one step: one call per action, in order, step fields on the first call only "
    "(null on the rest)."
)


def _compact_nullable(prop: dict[str, Any]) -> dict[str, Any]:
    """``{"anyOf": [X, {"type": "null"}], "default": null}`` as ``X`` with ``"type": [t, "null"]``.

    The same schema in about half the tokens; it is repeated in every action tool.
    """
    any_of = prop.get("anyOf")
    if not (isinstance(any_of, list) and len(any_of) == 2 and {"type": "null"} in any_of):
        return prop
    if not set(prop) <= {"anyOf", "default"} or prop.get("default", None) is not None:
        return prop
    (other,) = [branch for branch in any_of if branch != {"type": "null"}] or [None]
    if not (isinstance(other, dict) and isinstance(other.get("type"), str) and set(other) <= {"type", "items"}):
        return prop
    return {**other, "type": [other["type"], "null"]}


@functools.lru_cache(maxsize=64)
def _action_tools(output_format: type[BaseModel]) -> tuple[str, ...] | None:
    """JSON of one tool per available action (see action_tools), or None when they cannot be built."""
    models = action_models(output_format)
    if not models or not all(_TOOL_NAME.match(name) for name in models):
        return None
    step = optimized_schema(output_format)
    skip = {"action", *ACTION_TOOL_OMITTED_FIELDS}
    step_props = {k: _compact_nullable(v) for k, v in (step.get("properties") or {}).items() if k not in skip}
    step_required = [k for k in step.get("required") or [] if k not in skip]
    tools = []
    for name, model in models.items():
        params = model.model_fields[name].annotation
        if not (isinstance(params, type) and issubclass(params, BaseModel)):
            return None
        param_schema = SchemaOptimizer.create_optimized_json_schema(model)["properties"][name]
        param_props = param_schema.get("properties") or {}
        own = {k: v for k, v in step_props.items() if k not in param_props}
        description = param_schema.get("description") or model.model_fields[name].description or name
        tools.append(json.dumps({
            "name": name,
            "description": f"{description}\n\n{ACTION_TOOL_NOTE}",
            "input_schema": {
                "type": "object",
                "properties": {**own, **param_props},
                "required": [k for k in step_required if k in own] + list(param_schema.get("required") or []),
                "additionalProperties": False,
            },
        }))
    return tuple(tools)


def action_tools(output_format: type[BaseModel]) -> list[dict[str, Any]] | None:
    """One Anthropic tool per available action: the step fields, then the action's parameters.

    claude-sonnet-5-5 calls actions as tools even when offered only the AgentOutput tool, so
    each action gets a tool whose input is a whole step for that action. None when the
    actions cannot be presented this way; callers then send the single step tool.
    """
    built = _action_tools(output_format)
    if built is None:
        return None
    tools = [json.loads(tool) for tool in built]
    tools[-1]["cache_control"] = {"type": "ephemeral"}  # caches every tool definition
    return tools


def step_from_misplaced_actions(tool_input: Any, output_format: type[T]) -> T:
    """The step model for a step-tool input whose actions sit in the wrong place.

    Handles ``action`` given as one object (``{"click": {...}}``) instead of a list, action
    keys at the top level, and action parameters sent as JSON text. Raises ValueError when
    the input holds anything that is neither a step field nor an available action.
    """
    models = action_models(output_format)
    values = _as_object(tool_input, "the step input")
    own_fields = set(output_format.model_fields) - {"action"}
    step_fields: dict[str, Any] = {}
    top: list[tuple[str, Any]] = []
    unknown = []
    for key, value in values.items():
        if key == "action":
            continue
        if key in own_fields:
            step_fields[key] = value
        elif key in models:
            top.append((key, value))
        else:
            unknown.append(key)
    if unknown:
        raise ValueError(f"unexpected top-level keys: {', '.join(map(repr, unknown))}")
    action = values.get("action")
    if isinstance(action, str):
        action = json.loads(action)
    if isinstance(action, dict):
        action = [action]
    listed: list[tuple[str, Any]] = []
    for item in action or []:
        item = _as_object(item, "each `action` item")
        if not item or any(key not in models for key in item):
            raise ValueError(f"`action` item names no available action: {sorted(item)}")
        listed.extend(item.items())
    if listed and top:
        raise ValueError("actions given both inside and outside `action`")
    return build_step(output_format, step_fields, listed or top)


@dataclass
class ClaudeAgentChat(ChatAnthropic):
    """ChatAnthropic with structured outputs for small step schemas and, for large ones, one
    tool per action (each a whole step) assembled locally, with a repair call as the fallback."""

    max_repairs: int = 2
    # Tool inputs that had to be sent back for repair, over this instance's life.
    repairs: int = field(default=0, init=False)
    # Steps assembled locally from action-tool calls or a reshaped step-tool call (one request each).
    conversions: int = field(default=0, init=False)

    # Schemas the API refused to compile, shared by every instance in the process.
    _grammar_too_large: ClassVar[set[str]] = set()

    # -- shared pieces -----------------------------------------------------

    def _base_request(self, messages: list[BaseMessage]) -> tuple[list[Any], Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
        anthropic_messages, system_prompt = AnthropicMessageSerializer.serialize_messages(messages)
        params = self._get_client_params_for_invoke()
        extra_body = dict(params.pop("extra_body", None) or {})
        output_config = dict(extra_body.pop("output_config", None) or {})
        return anthropic_messages, system_prompt, params, extra_body, output_config

    async def _send(self, request: dict[str, Any]) -> Any:
        try:
            response = await self._create_message(**request)
        except APIConnectionError as e:
            raise ModelProviderError(message=e.message, model=self.name) from e
        except RateLimitError as e:
            raise ModelRateLimitError(message=e.message, model=self.name) from e
        except BadRequestError:
            raise  # callers decide (grammar too large is recoverable)
        except APIStatusError as e:
            raise ModelProviderError(message=e.message, status_code=e.status_code, model=self.name) from e
        if not self._is_message_like_response(response):
            raise ModelProviderError(
                message=f"Unexpected response type from Anthropic API: {type(response).__name__}",
                status_code=502,
                model=self.name,
            )
        return response

    def _check_stop(self, response: Any) -> None:
        stop_reason = response.stop_reason
        if stop_reason == "refusal":
            details = self._get_stop_details(response) or {}
            category = details.get("category")
            raise ModelRefusalError(
                f"{self.name} declined this step (stop_reason=refusal, category={category})",
                model=self.name,
                category=category,
            )
        if stop_reason == "max_tokens":
            raise ModelOutputTruncatedError(
                message=(
                    f"Model output was truncated at max_tokens={self.max_tokens}; the structured "
                    "output is incomplete. Increase max_tokens or lower effort."
                ),
                model=self.name,
            )

    def _completion(self, response: Any, completion: Any, usage: ChatInvokeUsage | None) -> ChatInvokeCompletion:
        _, thinking, redacted_thinking = self._extract_content_blocks(response)
        return ChatInvokeCompletion(
            completion=completion,
            thinking=thinking,
            redacted_thinking=redacted_thinking,
            usage=usage,
            stop_reason=response.stop_reason,
            stop_details=self._get_stop_details(response),
        )

    # -- entry point -----------------------------------------------------------

    async def ainvoke(
        self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: Any
    ) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
        if output_format is None:
            return await super().ainvoke(messages, None, **kwargs)

        strict = step_schema(output_format)
        key = _schema_key(strict)
        if fits_structured_outputs(strict) and key not in self._grammar_too_large:
            try:
                return await self._invoke_structured(messages, output_format, strict)
            except BadRequestError as e:
                if "grammar" not in (e.message or "").lower():
                    raise ModelProviderError(message=e.message, status_code=e.status_code, model=self.name) from e
                self._grammar_too_large.add(key)
        return await self._invoke_tool(messages, output_format)

    # -- 1. structured outputs -----------------------------------------------

    async def _invoke_structured(
        self, messages: list[BaseMessage], output_format: type[T], strict: dict[str, Any]
    ) -> ChatInvokeCompletion[T]:
        anthropic_messages, system_prompt, params, extra_body, output_config = self._base_request(messages)
        output_config["format"] = {"type": "json_schema", "schema": strict}
        request: dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_messages,
            "system": system_prompt or omit,
            "output_config": output_config,
            **params,
        }
        if extra_body:
            request["extra_body"] = extra_body
        response = await self._send(request)
        usage = self._get_usage(response)
        self._check_stop(response)

        text, _, _ = self._extract_content_blocks(response)
        try:
            return self._completion(response, output_format.model_validate_json(text), usage)
        except Exception as exc:
            # Schema-valid JSON can still miss a constraint the schema could not express
            # (min_items, ...): try browser-use's own repairs before giving up.
            recovered = self._completion_from_text_response(response, output_format, usage)
            if recovered is not None:
                return recovered
            raise ModelProviderError(
                message=f"Structured output did not validate as {output_format.__name__}: {exc}",
                model=self.name,
            ) from exc

    # -- 2. tool call with repair --------------------------------------------

    def _tool_for(self, output_format: type[BaseModel]) -> dict[str, Any]:
        name = output_format.__name__
        return {
            "name": name,
            "description": (
                f"Output your next step in the {name} format. Include every required top-level field. "
                "Put each action inside the `action` list as an object with exactly one key, the action "
                "name, whose value holds that action's parameters. Never put action parameters at the top level."
            ),
            "input_schema": optimized_schema(output_format),
            "cache_control": {"type": "ephemeral"},
        }

    def _validate_tool_input(self, tool_input: Any, output_format: type[T], response: Any, usage) -> tuple[Any, bool]:
        """(validated step model, whether its actions had to be moved) from a step-tool input.

        Applies browser-use's own repairs first, then step_from_misplaced_actions. Raises the
        first validation error when nothing validates.
        """
        try:
            return output_format.model_validate(tool_input), False
        except Exception as first_error:
            candidate = tool_input
            if isinstance(candidate, str):
                try:
                    candidate = json.loads(candidate)
                except ValueError:
                    raise first_error
            if isinstance(candidate, dict):
                candidate = self._repair_serialized_fields(dict(candidate))
                try:
                    return output_format.model_validate(candidate), False
                except Exception:
                    recovered = self._completion_from_serialized_tool_input(candidate, output_format, usage, response)
                    if recovered is not None:
                        return recovered.completion, False
                    try:
                        return step_from_misplaced_actions(candidate, output_format), True
                    except Exception:
                        pass
            raise first_error

    def _converted(self, response: Any, completion: Any, usage, what: str) -> ChatInvokeCompletion:
        self.conversions += 1
        log.info("%s: took %s from %s's reply as the step (no repair call)", type(self).__name__, what, self.name)
        return self._completion(response, completion, usage)

    async def _invoke_tool(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]:
        anthropic_messages, system_prompt, params, extra_body, output_config = self._base_request(messages)
        name = output_format.__name__
        per_action = action_tools(output_format)
        tools = per_action or [self._tool_for(output_format)]
        how = (
            "Call the tool named after the action, with the step fields and the action's parameters."
            if per_action else f"Call {name} with the action inside `action`."
        )
        conversation: list[Any] = list(anthropic_messages)
        total_usage: ChatInvokeUsage | None = None
        last_problem = "no attempt made"

        attempts = 1 + max(0, self.max_repairs)
        for attempt in range(attempts):
            request: dict[str, Any] = {
                "model": self.model,
                "messages": conversation,
                "tools": tools,
                "tool_choice": {"type": "auto"},
                "system": system_prompt or omit,
                **params,
            }
            if output_config:
                request["output_config"] = output_config
            if extra_body:
                request["extra_body"] = extra_body
            try:
                response = await self._send(request)
            except BadRequestError as e:
                raise ModelProviderError(message=e.message, status_code=e.status_code, model=self.name) from e
            total_usage = _add_usage(total_usage, self._get_usage(response))
            self._check_stop(response)

            tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]

            # (a) the step tool, as asked.
            step_problems: dict[str, str] = {}
            for block in tool_uses:
                if block.name != name:
                    continue
                try:
                    completion, moved = self._validate_tool_input(block.input, output_format, response, total_usage)
                except Exception as exc:
                    step_problems[block.id] = last_problem = _validation_summary(exc)
                    continue
                if moved:
                    return self._converted(response, completion, total_usage, f"the misplaced actions in its {name} call")
                return self._completion(response, completion, total_usage)

            # (b) every call names an action instead of the step tool: one step, actions in order.
            actions = action_models(output_format)
            conversion_problem = None
            if tool_uses and all(block.name in actions for block in tool_uses):
                text = "\n".join(b.text for b in response.content if getattr(b, "type", None) == "text" and b.text)
                try:
                    completion = step_from_action_calls([(b.name, b.input) for b in tool_uses], output_format, text)
                except Exception as exc:
                    conversion_problem = _validation_summary(exc)
                else:
                    called = ", ".join(block.name for block in tool_uses)
                    return self._converted(response, completion, total_usage, f"the action call(s) {called}")

            # (c) send every call back with what was wrong, and ask again.
            feedback: list[dict[str, Any]] = []
            for block in tool_uses:
                if block.name == name:
                    retry = how if per_action else (
                        f"Call {name} again with every required top-level field, and each action "
                        "inside `action` as {\"<action_name>\": {<parameters>}}."
                    )
                    content = f"The {name} input did not match the schema:\n{step_problems[block.id]}\n{retry}"
                elif block.name in actions and conversion_problem:
                    last_problem = f"action call {block.name!r} did not validate: {conversion_problem}"
                    lead = (
                        "This step did not validate" if per_action
                        else f"{block.name!r} is an action, not a tool, and the step did not validate"
                    )
                    content = f"{lead}:\n{conversion_problem}\n{how}"
                elif block.name in actions:
                    last_problem = f"action call {block.name!r} next to a broken {name} call"
                    content = f"Not run: this reply also had a {name} call that did not validate. {how}"
                else:
                    last_problem = f"called unknown tool {block.name!r}"
                    content = f"Unknown tool {block.name!r}. {how}"
                feedback.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True, "content": content})

            if not tool_uses:
                recovered = self._completion_from_text_response(response, output_format, total_usage)
                if recovered is not None:
                    return recovered
                last_problem = "the reply did not call the tool"
                ask = "one of the action tools" if per_action else f"the {name} tool"
                feedback.append({"type": "text", "text": f"Reply by calling {ask} with your next step."})

            if attempt + 1 < attempts:
                self.repairs += 1
                log.warning(
                    "%s: asking %s to repair its %s step (%s)",
                    type(self).__name__, self.name, name, last_problem.splitlines()[0][:200],
                )
                # Append-only: the model's turn exactly as returned, then the feedback.
                conversation = [
                    *conversation,
                    {"role": "assistant", "content": response.content},
                    {"role": "user", "content": feedback},
                ]

        raise ModelProviderError(
            message=f"{self.name} did not produce a valid {name} after {attempts} attempts: {last_problem}",
            model=self.name,
        )
