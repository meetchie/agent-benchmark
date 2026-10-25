"""browser-use chat model for current Claude models.

browser-use's own ChatAnthropic asks for every agent step ("AgentOutput": thinking,
memory, next goal, a list of actions) through one tool call. On current Claude models:

* A forced tool call (``tool_choice: {"type": "tool"}``) is rejected with HTTP 400 on
  claude-sonnet-5-5 and claude-opus-5-5. browser-use switches to ``auto`` only when
  thinking is configured, which llm.agent_llm() always does for these models.
* With ``tool_choice: auto``, claude-sonnet-5-5 sometimes calls the AgentOutput tool with
  one action's parameters at the top level instead of inside ``action`` (2 of 4 steps in
  a smoke run on 2026-10-24). browser-use then fails the step, retries it from scratch,
  and never counts the failed call's tokens, so step counts and cost both come out wrong.
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
2. Larger schemas use the tool, with ``tool_choice: auto``. When the tool input does not
   validate, or the model answers without calling the tool, the model's turn is appended
   unchanged together with an ``is_error`` tool result naming the validation errors, and
   the model is asked again (up to ``max_repairs`` times). Every attempt's tokens are
   summed into the returned usage, so repairs are paid for and counted.

Plain-text calls (no output format) go through ChatAnthropic unchanged. Nothing here sends
temperature/top_p/top_k, forces a tool, or prefills an assistant turn.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, ClassVar, TypeVar

import anthropic
from anthropic import APIConnectionError, APIStatusError, BadRequestError, RateLimitError, omit
from pydantic import BaseModel, ValidationError

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


@dataclass
class ClaudeAgentChat(ChatAnthropic):
    """ChatAnthropic with structured outputs for small step schemas and repaired tool calls for large ones."""

    max_repairs: int = 2
    # Tool inputs that had to be sent back for repair, over this instance's life.
    repairs: int = field(default=0, init=False)

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

    def _validate_tool_input(self, tool_input: Any, output_format: type[T], response: Any, usage) -> Any:
        """Validated step model from a tool input, applying browser-use's repairs. Raises on failure."""
        try:
            return output_format.model_validate(tool_input)
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
                    return output_format.model_validate(candidate)
                except Exception:
                    recovered = self._completion_from_serialized_tool_input(candidate, output_format, usage, response)
                    if recovered is not None:
                        return recovered.completion
            raise first_error

    async def _invoke_tool(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]:
        anthropic_messages, system_prompt, params, extra_body, output_config = self._base_request(messages)
        tool = self._tool_for(output_format)
        name = tool["name"]
        conversation: list[Any] = list(anthropic_messages)
        total_usage: ChatInvokeUsage | None = None
        last_problem = "no attempt made"

        attempts = 1 + max(0, self.max_repairs)
        for attempt in range(attempts):
            request: dict[str, Any] = {
                "model": self.model,
                "messages": conversation,
                "tools": [tool],
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
            feedback: list[dict[str, Any]] = []
            for block in tool_uses:
                if block.name != name:
                    last_problem = f"called unknown tool {block.name!r}"
                    feedback.append({
                        "type": "tool_result", "tool_use_id": block.id, "is_error": True,
                        "content": f"Unknown tool {block.name!r}. Call {name} with the action inside `action`.",
                    })
                    continue
                try:
                    completion = self._validate_tool_input(block.input, output_format, response, total_usage)
                except Exception as exc:
                    last_problem = _validation_summary(exc)
                    feedback.append({
                        "type": "tool_result", "tool_use_id": block.id, "is_error": True,
                        "content": (
                            f"The {name} input did not match the schema:\n{last_problem}\n"
                            f"Call {name} again with every required top-level field, and each action "
                            "inside `action` as {\"<action_name>\": {<parameters>}}."
                        ),
                    })
                    continue
                return self._completion(response, completion, total_usage)

            if not tool_uses:
                recovered = self._completion_from_text_response(response, output_format, total_usage)
                if recovered is not None:
                    return recovered
                last_problem = "the reply did not call the tool"
                feedback.append({"type": "text", "text": f"Reply by calling the {name} tool with your next step."})

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
