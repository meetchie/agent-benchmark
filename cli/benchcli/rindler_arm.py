"""Phase 2: a tool-calling model working a site through its Rindler mapping.

The tools are the mapping's own actions, served in-process by rindler_local's
LocalRindlerHost (headless Chromium + Playwright running the mapping's steps), plus a
synthetic ``done``. The model never sees HTML or selectors, only the JSON envelope each
tool returns, and it never sees a tool the mapping does not define. One tool call per
model turn; the step budget is the same as the BrowserUse arm's.

SYSTEM_PROMPT describes the envelope the host actually returns (see the arena note in
rindler_local/host.py). tests/test_rindler_arm.py checks every field the host returns
is named in it.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import llm
from rindler_local import LocalRindlerHost, Mapping, parse_result, to_anthropic

from .results import make_step, new_result, utc_iso

# The session is opened for the model; it works with the mapping's actions and done.
HIDDEN_TOOLS = ("start_session", "close_session")
MAX_RESULT_CHARS = 12000
OBSERVATION_CHARS = 240

SYSTEM_PROMPT = """You are a shopping assistant working one website through a small set of site-specific tools. You cannot see the page, run scripts or type a URL. You only see what the tools return.

The browser is already open on the site's start page. Every tool returns one JSON object with these fields:
- "screen": the name of the screen you are on now (for example "accessories" or "cart").
- "available_actions": the tools you can call on this screen. A tool that is not listed is refused with an error.
- "global_actions": tools that work on any screen. It can be empty.
- "context": values the site keeps between calls, such as a cart count. It can be empty.
- "data": what the page shows. It holds some of:
  - "page_url": the address you are on.
  - "page_info": a summary of the page made by the site's own extractor. For this site it usually has "title", "sections" (the page's headings; on a catalog page these are the product names), "prices" (a de-duplicated list, so it does not say which price belongs to which product), "product_cards" (name and price pairs, on catalog pages), "description", "cart_items" (name, price and quantity), "order_summary" and "buttons". Fields that do not apply to the page are left out.
  - "products" and "cart_items": lists read from the page's accessibility tree. They are best effort and can be missing, or list headings that are not products. Where they disagree with "page_info", trust "page_info".
  - "extracted": text that a tool read from the page, when the tool does that.
- On a failure the object has "error": {"code", "message"} and the same screen fields. Read the message; it says what went wrong.

Rules:
- Make one tool call at a time and read its result before the next.
- Take names, prices and counts from the tool results, never from memory. Item names you pass to a tool must match the names the page shows.
- If a tool fails, try a different way (another tool, or the same tool with a name taken from the page). Do not repeat the same failing call.
- When you have done everything the goal asks, or you are sure it cannot be done, call the "done" tool with success true or false and a message that contains everything the goal asks you to report (names, prices, counts, totals)."""

DONE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "success": {"type": "boolean", "description": "Whether the goal was accomplished"},
        "message": {"type": "string", "description": "Everything the goal asked you to report, or why it failed"},
    },
    "required": ["success", "message"],
}

DONE_TOOL = {
    "name": "done",
    "description": (
        "Call this ONLY when you have fully completed every part of the goal, or are sure it cannot be done. "
        "Do NOT call it while items are still to be added or steps are still untried. If a tool returned an "
        "error, try another approach first. Put everything the goal asks you to report in the message."
    ),
    "input_schema": DONE_TOOL_SCHEMA,
}

NUDGE = "Continue: call one of the tools, or call done if you have finished or cannot go further."


def truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[:max_chars] + "\n... [truncated]"


def with_cache_breakpoint(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A copy of the transcript whose last user block carries cache_control.

    Only the request copy gets the marker, so each turn reads the previous turn's prompt
    from the cache (browser-use caches the same way on the other arm).
    """
    out = list(messages)
    if not out or llm.provider() != llm.ANTHROPIC:
        return out
    last = dict(out[-1])
    if last.get("role") != "user":
        return out
    content = last.get("content")
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else [dict(b) for b in content or []]
    if not blocks:
        return out
    blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
    last["content"] = blocks
    out[-1] = last
    return out


def model_view(envelope: dict[str, Any], tool_names: set[str]) -> dict[str, Any]:
    """The envelope as the model sees it: action lists name only tools the model has.

    The host lists start_session as a global action; the CLI has already called it, so
    showing it would point at a tool the model does not have.
    """
    view = dict(envelope)
    for key in ("available_actions", "global_actions"):
        if key in view:
            view[key] = [a for a in view[key] if a in tool_names]
    return view


def describe(envelope: dict[str, Any]) -> str:
    """A one-line digest of a tool result for the step log and the judge's trace."""
    error = envelope.get("error")
    parts = [f"screen={envelope.get('screen', '?')}"]
    if error:
        parts.append(f"error {error.get('code')}: {str(error.get('message', ''))[:120]}")
    data = envelope.get("data") or {}
    info = data.get("page_info") or {}
    if isinstance(info, dict):
        if info.get("title"):
            parts.append(f"title={str(info['title']).splitlines()[0][:60]!r}")
        items = info.get("cart_items") or []
        if items:
            parts.append("cart=[" + "; ".join(
                f"{i.get('name')} x{i.get('quantity')} {i.get('price')}" for i in items[:5]) + "]")
        summary = info.get("order_summary") or {}
        if summary.get("total"):
            parts.append(f"total={summary['total']}")
    return " ".join(parts)[:OBSERVATION_CHARS]


def initial_message(goal: str, envelope: dict[str, Any], tool_names: set[str]) -> dict[str, Any]:
    view = model_view(envelope, tool_names)
    data = {k: v for k, v in (view.get("data") or {}).items() if k != "session_id"}
    return llm.user_message(
        f"Goal: {goal.strip()}\n\n"
        f"The browser is open. Current screen: {view.get('screen', 'unknown')}\n"
        f"Context: {json.dumps(view.get('context') or {})}\n"
        f"Data: {truncate(json.dumps(data, default=str), MAX_RESULT_CHARS)}\n"
        f"Available actions: {', '.join(view.get('available_actions') or [])}\n"
        f"Global actions: {', '.join(view.get('global_actions') or []) or 'none'}"
    )


async def _screenshot(page: Any, results_dir: Path, task_id: str) -> str | None:
    if page is None:
        return None
    relative = f"screenshots/task-{task_id}-final.png"
    target = results_dir / "rindler" / relative
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(target))
    except Exception:
        return None
    return relative


async def run_rindler_task(
    task: dict[str, Any],
    *,
    mapping: Mapping,
    model: str,
    max_steps: int,
    results_dir: Path,
    site: str,
    timeout_s: float | None = None,
    host_factory: Callable[[Mapping], Any] = LocalRindlerHost,
) -> dict[str, Any]:
    """Run one task and return its result record (not yet judged, not yet saved)."""
    task_id = task["id"]
    print(f"  Task: {task['name']} ({task_id})")

    started_at = datetime.now(timezone.utc)
    steps: list[dict[str, Any]] = []
    out: dict[str, Any] = {"success": False, "report": None, "error": None, "tools": []}
    host = host_factory(mapping)

    async def loop() -> None:
        tools = [t for t in await host.list_tools() if t["name"] not in HIDDEN_TOOLS]
        tool_names = {t["name"] for t in tools}
        llm_tools = to_anthropic(tools) + [DONE_TOOL]
        out["tools"] = sorted(tool_names)
        print(f"    Tools from the mapping: {', '.join(sorted(tool_names))}")

        t0 = time.monotonic()
        start = parse_result(await host.call_tool("start_session", {"url": task["start_url"]}))
        steps.append(make_step(
            0, "start_session", action_args={"url": task["start_url"]}, duration_ms=(time.monotonic() - t0) * 1000,
            observation=describe(start), error=_error_text(start), tool="start_session", screen=start.get("screen"),
            available_actions=model_view(start, tool_names).get("available_actions", []),
            response_bytes=len(json.dumps(start, default=str)),
        ))
        if start.get("error"):
            out["error"] = f"start_session failed: {_error_text(start)}"
            return
        print(f"    Session open on screen {start.get('screen')}")

        messages = [initial_message(task["goal"], start, tool_names)]
        for n in range(1, max_steps + 1):
            step_ts, step_t0 = utc_iso(), time.monotonic()
            try:
                turn = await llm.achat_tools(
                    SYSTEM_PROMPT, with_cache_breakpoint(messages), llm_tools,
                    model=model, role="agent", parallel_tool_calls=False,
                )
            except llm.LLMError as exc:
                out["error"] = f"model call failed ({exc.kind}): {exc}"
                print(f"    {out['error']}")
                return
            usage = turn.get("usage") or {}
            tokens = dict(
                tokens_input=int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0)
                + int(usage.get("cache_creation_input_tokens") or 0),
                tokens_output=int(usage.get("output_tokens") or 0),
                tokens_cache_read=int(usage.get("cache_read_input_tokens") or 0),
                tokens_cache_write=int(usage.get("cache_creation_input_tokens") or 0),
                cost_usd=turn.get("cost_usd") or 0.0,
            )
            calls = turn.get("tool_calls") or []
            done_call = next((c for c in calls if c["name"] == "done"), None)

            if done_call is not None:
                args = done_call.get("input") or {}
                out["success"], out["report"] = bool(args.get("success")), str(args.get("message") or "")
                steps.append(make_step(n, "done", action_args=args, started_at=step_ts,
                                       duration_ms=(time.monotonic() - step_t0) * 1000,
                                       observation=out["report"][:OBSERVATION_CHARS], tool="done", **tokens))
                print(f"    Step {n}: done ({'pass' if out['success'] else 'fail'}) {out['report'][:70]}")
                return

            if not calls:
                text = (turn.get("text") or "").strip()
                steps.append(make_step(n, "no_tool_call", started_at=step_ts,
                                       duration_ms=(time.monotonic() - step_t0) * 1000,
                                       observation=text[:OBSERVATION_CHARS], **tokens))
                print(f"    Step {n}: [no tool call] {text[:60]}")
                messages = llm.append_assistant(messages, turn) + [llm.user_message(NUDGE)]
                continue

            call = calls[0]  # parallel_tool_calls=False: one per turn; answer any extra with an error
            name, args = call["name"], dict(call.get("input") or {})
            envelope = parse_result(await host.call_tool(name, args))
            elapsed_ms = (time.monotonic() - step_t0) * 1000
            seen = model_view(envelope, tool_names)
            steps.append(make_step(
                n, name, action_args=args, started_at=step_ts, duration_ms=elapsed_ms,
                observation=describe(envelope), error=_error_text(envelope), tool=name,
                screen=envelope.get("screen"), available_actions=seen.get("available_actions", []),
                response_bytes=len(json.dumps(envelope, default=str)), **tokens,
            ))
            print(f"    Step {n}: {name} -> {envelope.get('screen', '?')} ({elapsed_ms:.0f}ms, ${tokens['cost_usd']:.4f})")

            results = [llm.tool_result(call["id"], truncate(json.dumps(seen, default=str), MAX_RESULT_CHARS),
                                       is_error=bool(envelope.get("error")))]
            results += [llm.tool_result(c["id"], "Only one tool call per turn is run; call it again.", is_error=True)
                        for c in calls[1:]]
            messages = llm.append_tool_results(messages, turn, results)

        out["error"] = f"did not call done within {max_steps} steps"

    try:
        await (asyncio.wait_for(loop(), timeout=timeout_s) if timeout_s else loop())
    except asyncio.TimeoutError:
        out["error"] = f"stopped after the {timeout_s:.0f}s time limit"
    except Exception as exc:  # a browser or SDK failure ends this run, not the whole benchmark
        out["error"] = f"{type(exc).__name__}: {exc}"

    shot = None
    if not out["success"]:
        shot = await _screenshot(getattr(host, "page", None), results_dir, task_id)
        if shot and steps:
            steps[-1]["screenshot_path"] = shot
    try:
        await host.close()
    except Exception:
        pass

    record = new_result(
        task, agent="rindler", model=model, site=site, max_steps=max_steps,
        started_at=started_at, finished_at=datetime.now(timezone.utc), steps=steps, success=out["success"],
        final_report=out["report"], error=out["error"], failure_screenshots=[shot] if shot else None,
    )
    record["tools"] = out["tools"]
    if out["error"]:
        print(f"    Stopped: {out['error']}")
    print(f"    Done: {record['stats']['total_steps']} steps, ${record['stats']['total_cost_usd']:.4f}")
    return record


def _error_text(envelope: dict[str, Any]) -> str | None:
    error = envelope.get("error")
    if not error:
        return None
    return f"[{error.get('code')}] {error.get('message')}"
