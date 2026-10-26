"""
Rindler arm: a tool-calling model drives a site through its Rindler site mapping.

The tools are the mapping's actions, served in-process by rindler_local.LocalRindlerHost. The model
never sees HTML or selectors, only the JSON envelope each tool returns. The loop is the March one:
one tool call per model turn, a synthetic ``done`` tool to finish, tool results truncated to
MAX_RESULT_CHARS and the same step telemetry.

Model: ``model`` argument, else BENCHMARK_AGENT_MODEL, else claude-sonnet-5-5 (llm.py).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from .base_agent import BaseAgent
except ImportError:  # loaded as a plain module
    from adapters.base_agent import BaseAgent

import llm
from rindler_local import LocalRindlerHost, find_mapping_for_url, load_mapping, parse_result, to_anthropic

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RUNS_DIR = os.path.join(SERVER_DIR, "arena_runs")

SYSTEM_PROMPT = """You are a commerce automation agent. You interact with shopping sites through Rindler's semantic tools. You do NOT have access to raw HTML, CSS selectors, or page elements.

Every tool response returns structured JSON with:
- "screen": which screen you're on (e.g., "landing", "search_results", "cart")
- "context": persistent state (cart summary, delivery address)
- "data": screen-specific information (page_url, products, cart_items, page_info)
- "available_actions": actions valid on the current screen
- "global_actions": actions always available

RULES:
- The session is already started; the first message shows the screen you are on.
- Only call actions listed in available_actions or global_actions.
- Item names for view_product, add_to_cart, remove_from_cart, etc. come from the data field.
- Do NOT try to construct URLs, CSS selectors, or reference page elements.
- Make one tool call at a time and read its result before the next.

When you have completed the goal (or determined it cannot be completed),
call the "done" tool with {success: true/false, message: "explanation"}. Put everything
the goal asks you to report (names, prices, counts, totals) in the message."""

DONE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "success": {"type": "boolean", "description": "Whether the goal was accomplished"},
        "message": {"type": "string", "description": "Brief summary of what was accomplished or why it failed"},
    },
    "required": ["success", "message"],
}

DONE_TOOL = {
    "name": "done",
    "description": (
        "Call this ONLY when you have fully completed every part of the goal. "
        "Do NOT call this if there are remaining items to add, quantities to update, "
        "or steps you haven't tried yet. If a tool returns an error, try an alternative "
        "approach (e.g. navigate to the cart first, then retry). Only report failure "
        "after exhausting all available actions."
    ),
    "input_schema": DONE_TOOL_SCHEMA,
}

NUDGE = "Continue: call one of the tools, or call done if you have finished or cannot go further."

MAX_RESULT_CHARS = 12000

# Semantic tool names mapped to categories for cost analysis. Downstream scripts group by category.
ACTION_CATEGORIES = {
    "start_session": "session",
    "close_session": "session",
    "update_address": "address",
    "search_products": "search",
    "add_to_cart": "cart_add",
    "remove_from_cart": "cart_remove",
    "update_quantity": "cart_update",
    "view_cart": "cart_view",
    "view_product": "product",
    "checkout": "checkout",
    "select_delivery_window": "checkout",
    "apply_promo": "checkout",
    "place_order": "checkout",
    "go_back": "navigation",
    "select_store": "navigation",
    "next_page": "navigation",
    "prev_page": "navigation",
    "done": "finish",
}


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


def with_cache_breakpoint(messages: List[dict]) -> List[dict]:
    """A copy of the transcript whose last user block carries cache_control.

    The stored transcript is never changed; only the request copy gets the marker, so
    each turn reuses the cached prefix of the previous one (browser-use caches the same
    way on the other arm).
    """
    if not messages or llm.provider() != llm.ANTHROPIC:
        return list(messages)
    out = list(messages)
    last = dict(out[-1])
    if last.get("role") != "user":
        return out
    content = last.get("content")
    if isinstance(content, str):
        blocks = [{"type": "text", "text": content}]
    else:
        blocks = [dict(b) for b in content or []]
    if not blocks:
        return out
    blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
    last["content"] = blocks
    out[-1] = last
    return out


def prompt_tokens(usage: Dict[str, Any]) -> int:
    """All prompt tokens of a call: uncached input plus cache reads and writes."""
    return int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0) + int(
        usage.get("cache_creation_input_tokens") or 0
    )


class RindlerTelemetricAgent(BaseAgent):
    """Tool-calling model driving a site through its Rindler site mapping."""

    def __init__(self, run_id: str, goal: str, lane: str = "RINDLER", **kwargs):
        super().__init__(run_id=run_id, goal=goal, lane=lane)
        self.model = (kwargs.get("model") or kwargs.get("llm") or "").strip() or llm.model_for("agent")
        self.max_steps = int(kwargs.get("max_steps") or 30)
        self.timeout_s = float(kwargs.get("timeout_s") or 0) or None
        self.mapping_source = kwargs.get("mapping")
        self.log_dir = kwargs.get("log_dir") or DEFAULT_RUNS_DIR
        self._context_log_enabled = bool(kwargs.get("context_log", False))
        self._host_factory = kwargs.get("host_factory") or LocalRindlerHost
        self.usage = llm.Usage()
        self.llm_calls = 0
        self.mapping_name: Optional[str] = None

    def _resolve_mapping(self, start_url: Optional[str]):
        if self.mapping_source:
            return load_mapping(self.mapping_source)
        mapping = find_mapping_for_url(start_url or "")
        if mapping is None:
            raise ValueError(
                f"No site mapping covers {start_url!r}. The Rindler arm only runs on mapped sites "
                "(server/mappings/*.json); pass --mapping to choose one."
            )
        return mapping

    def _build_initial_messages(self, start_env: dict) -> list:
        data = start_env.get("data") or {}
        shown = {k: v for k, v in data.items() if k != "session_id"}
        content = (
            f"Goal: {self.goal}\n\n"
            f"Session started.\n"
            f"Screen: {start_env.get('screen', 'unknown')}\n"
            f"Context: {json.dumps(start_env.get('context') or {}, indent=2)}\n"
            f"Data: {truncate(json.dumps(shown, default=str), MAX_RESULT_CHARS)}\n"
            f"Available actions: {', '.join(start_env.get('available_actions') or [])}\n"
            f"Global actions: {', '.join(start_env.get('global_actions') or [])}"
        )
        return [llm.user_message(content)]

    def _build_result(self, done_args: dict, steps: int, errors: Optional[List[str]] = None) -> dict:
        return {
            "success": bool(done_args.get("success", False)),
            "message": done_args.get("message", ""),
            "steps": steps,
            "final_extraction": done_args.get("message", ""),
            "errors_detected": list(errors or []),
            "model": self.model,
            "usage": self.usage.to_dict(),
            "llm_calls": self.llm_calls,
        }

    def _record_turn(self, turn: dict) -> dict:
        usage = turn.get("usage") or {}
        self.usage = self.usage + llm.Usage(
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cache_read_input_tokens=int(usage.get("cache_read_input_tokens") or 0),
            cache_creation_input_tokens=int(usage.get("cache_creation_input_tokens") or 0),
        )
        self.llm_calls += 1
        return usage

    def _end_step(self, usage: dict, cost: Optional[float], observation: Any, *, action: str, was_error: bool,
                  served_by: Optional[str]) -> dict:
        event = self.log_step_end(
            tokens_input=prompt_tokens(usage),
            tokens_output=int(usage.get("output_tokens") or 0),
            observation=observation,
        )
        event["cost_usd"] = cost or 0.0
        event["tokens_cache_read"] = int(usage.get("cache_read_input_tokens") or 0)
        event["tokens_cache_write"] = int(usage.get("cache_creation_input_tokens") or 0)
        event["action_category"] = ACTION_CATEGORIES.get(action, "other")
        event["was_error"] = was_error
        if served_by and served_by != self.model:
            event["served_by"] = served_by
        return event

    def _init_context_log(self, start_url: str):
        if not self._context_log_enabled:
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(self.log_dir, exist_ok=True)
        self._context_log_path = os.path.join(self.log_dir, f"context_{self.lane.lower()}_{timestamp}.log")
        with open(self._context_log_path, "w") as f:
            f.write(f"{'=' * 80}\n  RINDLER AGENT — FULL CONTEXT LOG\n{'=' * 80}\n")
            f.write(f"  Timestamp:  {datetime.now().isoformat()}\n")
            f.write(f"  Run ID:     {self.run_id}\n")
            f.write(f"  Trace ID:   {self.trace_id}\n")
            f.write(f"  Goal:       {self.goal}\n")
            f.write(f"  Start URL:  {start_url}\n")
            f.write(f"  LLM:        {self.model}\n")
            f.write(f"  Max Steps:  {self.max_steps}\n")
            f.write(f"{'=' * 80}\n\n{'─' * 80}\n  SYSTEM PROMPT (fed to LLM)\n{'─' * 80}\n")
            f.write(SYSTEM_PROMPT)
            f.write(f"\n{'─' * 80}\n\n")
        print(f"  📝 Context log: {self._context_log_path}")

    def _log_context(self, header: str, content: str):
        if not hasattr(self, "_context_log_path"):
            return
        with open(self._context_log_path, "a") as f:
            f.write(f"\n{'─' * 80}\n  [{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {header}\n{'─' * 80}\n")
            f.write(content)
            f.write("\n")

    def _finalize_context_log(self, total_cost: float, steps: int, result: dict):
        if not hasattr(self, "_context_log_path"):
            return
        with open(self._context_log_path, "a") as f:
            f.write(f"\n{'=' * 80}\n  RUN COMPLETE\n{'=' * 80}\n")
            f.write(f"  Steps:   {steps}\n  Cost:    ${total_cost:.4f}\n")
            f.write(f"  Success: {result.get('success', False)}\n  Message: {result.get('message', '')}\n")
            f.write(f"{'=' * 80}\n")

    @staticmethod
    def _print_state(parsed: dict) -> None:
        data = parsed.get("data") or {}
        line = f"    screen={parsed.get('screen', '?')}"
        if data.get("products"):
            line += f" products={len(data['products'])}"
        if data.get("cart_items"):
            line += f" cart_items={len(data['cart_items'])}"
        if data.get("page_info") is not None:
            line += f" page_info={json.dumps(data['page_info'], default=str)[:120]}"
        if parsed.get("context"):
            line += f" context={json.dumps(parsed['context'], default=str)[:120]}"
        print(line)
        if parsed.get("error"):
            err = parsed["error"]
            print(f"    ⚠️  [{err.get('code', 'error')}] {str(err.get('message', ''))[:300]}")

    async def run(self, start_url=None, **kwargs):
        self.print_run_header(start_url)
        mapping = self._resolve_mapping(start_url)
        self.mapping_name = mapping.site_id
        host = self._host_factory(mapping)
        print(f"  🗺  Mapping: {mapping.site_id} ({mapping.domain}, {len(mapping.actions)} actions)")
        print(f"  🤖 Model: {self.model} ({llm.provider()})")
        self._init_context_log(start_url)
        try:
            if self.timeout_s:
                return await asyncio.wait_for(self._run(host, start_url), timeout=self.timeout_s)
            return await self._run(host, start_url)
        except asyncio.TimeoutError:
            msg = f"run stopped after the {self.timeout_s:.0f}s time limit"
            print(f"\n  ⏱  {msg}")
            self._finalize_context_log(self._total_cost(), self._current_step_index, {"success": False, "message": msg})
            return self._build_result({"success": False, "message": msg}, self._current_step_index, [msg])
        finally:
            await host.close()

    def _total_cost(self) -> float:
        return sum(e.get("cost_usd") or 0.0 for e in self.telemetry_events if e.get("event_type") == "step_end")

    async def _run(self, host, start_url):
        tools = [t for t in await host.list_tools() if t["name"] not in ("start_session", "close_session")]
        llm_tools = to_anthropic(tools) + [DONE_TOOL]
        print(f"  📦 {len(tools)} mapping tools: {', '.join(t['name'] for t in tools)}")
        self._log_context("TOOLS (from the mapping)", json.dumps(
            [{"name": t["name"], "description": t["description"]} for t in tools], indent=2))

        print(f"\n  ▶ START SESSION → {start_url}", flush=True)
        t0 = time.monotonic()
        start_env = parse_result(await host.call_tool("start_session", {"url": start_url}))
        print(f"    ({time.monotonic() - t0:.1f}s)")
        self._print_state(start_env)
        self._log_context("START_SESSION RESPONSE (full JSON)", json.dumps(start_env, indent=2, default=str))
        if start_env.get("error"):
            err = start_env["error"]
            msg = f"start_session failed: [{err.get('code')}] {err.get('message')}"
            return self._build_result({"success": False, "message": msg}, 0, [msg])

        messages = self._build_initial_messages(start_env)
        self._log_context("INITIAL MESSAGE → AGENT", json.dumps(messages, indent=2, default=str))
        errors: List[str] = []
        print(f"\n  🏃 ACTION LOOP (max {self.max_steps} steps)", flush=True)

        for step in range(self.max_steps):
            step_num = step + 1
            print(f"\n  Step {step_num}/{self.max_steps}: thinking...", flush=True)
            try:
                turn = await llm.achat_tools(
                    SYSTEM_PROMPT,
                    with_cache_breakpoint(messages),
                    llm_tools,
                    model=self.model,
                    role="agent",
                    parallel_tool_calls=False,
                )
            except llm.LLMError as exc:
                msg = f"model call failed ({exc.kind}): {exc}"
                print(f"    ❌ {msg}")
                if exc.usage is not None:
                    self.usage = self.usage + exc.usage
                self._log_context(f"STEP {step_num} — LLM ERROR", msg)
                errors.append(msg)
                self._finalize_context_log(self._total_cost(), step_num, {"success": False, "message": msg})
                return self._build_result({"success": False, "message": f"Agent error: {msg}"}, step_num, errors)

            usage = self._record_turn(turn)
            calls = turn.get("tool_calls") or []
            done_call = next((c for c in calls if c["name"] == "done"), None)

            if done_call is not None:
                done_args = done_call.get("input") or {}
                self.log_step_start(action_type="done", action_data=done_args)
                self._end_step(usage, turn.get("cost_usd"), {"done": done_args}, action="done", was_error=False,
                               served_by=turn.get("model"))
                icon = "✅" if done_args.get("success") else "❌"
                print(f"  → done {icon} {str(done_args.get('message', ''))[:300]}")
                self._log_context(f"STEP {step_num} — AGENT CALLED done()", json.dumps(done_args, indent=2, default=str))
                print(f"\n  💰 Total cost: ${self._total_cost():.4f}")
                self._finalize_context_log(self._total_cost(), step_num, done_args)
                return self._build_result(done_args, step_num, errors)

            if not calls:
                # A turn with no tool call: keep it, nudge the model, and count its tokens as a step
                # so the cost is not lost.
                text = (turn.get("text") or "").strip()
                print(f"  → [no tool call] {text[:200]}")
                self.log_step_start(action_type="no_tool_call", action_data={"text": text[:500]})
                self._end_step(usage, turn.get("cost_usd"), {"text": text}, action="no_tool_call", was_error=False,
                               served_by=turn.get("model"))
                self._log_context(f"STEP {step_num} — AGENT TEXT (no tool call)", text or "(empty)")
                messages = llm.append_assistant(messages, turn)
                messages = messages + [llm.user_message(NUDGE)]
                continue

            # parallel_tool_calls=False: one call per turn. Answer any extras with an error.
            call = calls[0]
            name, args = call["name"], dict(call.get("input") or {})
            display = json.dumps(args, default=str) if args else ""
            print(f"  → {name}({display})")
            self._log_context(
                f"STEP {step_num} — AGENT CALLS {name}",
                f"Args: {json.dumps(args, indent=2, default=str)}\n"
                f"Tokens: {prompt_tokens(usage):,} in / {usage.get('output_tokens', 0):,} out",
            )
            self.log_step_start(action_type=name, action_data=args)
            t0 = time.monotonic()
            parsed = parse_result(await host.call_tool(name, args))
            elapsed = time.monotonic() - t0
            was_error = bool(parsed.get("error"))
            event = self._end_step(usage, turn.get("cost_usd"), {"tool_result": parsed}, action=name,
                                   was_error=was_error, served_by=turn.get("model"))
            self._print_state(parsed)
            print(f"    ⏱  {elapsed:.1f}s | tokens: {event['tokens_input']:,} in / {event['tokens_output']:,} out"
                  f" | ${event['cost_usd']:.4f} (total ${self._total_cost():.4f})")
            self._log_context(f"STEP {step_num} — RESPONSE for {name} ({elapsed:.1f}s)",
                              json.dumps(parsed, indent=2, default=str))

            result_text = truncate(json.dumps(parsed, default=str), MAX_RESULT_CHARS)
            results = [llm.tool_result(call["id"], result_text, is_error=was_error)]
            for extra in calls[1:]:
                results.append(llm.tool_result(extra["id"], "Only one tool call per turn is run; call it again.",
                                               is_error=True))
            messages = llm.append_tool_results(messages, turn, results)

        msg = "max steps reached"
        print(f"\n  💰 Total cost: ${self._total_cost():.4f}")
        self._finalize_context_log(self._total_cost(), self.max_steps, {"success": False, "message": msg})
        errors.append(f"Reached max_steps ({self.max_steps}) without calling done")
        return self._build_result({"success": False, "message": msg}, self.max_steps, errors)
