"""Running mapping steps on a Playwright page.

Step semantics, as in the March 2026 Rindler server but on Playwright's async Python API:

    navigate   page.goto(url), waits for DOMContentLoaded (timeout 15 s or the step's).
    click      the step's selector, then each fallback in order; every attempt gets
               ``timeout`` ms (default 2000). Fallback types: css, xpath, text,
               text_exact, role, label, placeholder. After a click, waits up to 2 s
               for the network to go idle.
    type       fill() the selector (5 s per attempt), fallbacks as for click; Enter
               afterwards when ``press_enter`` is true.
    select     select_option by value, then by label.
    extract    visible text of the first element matching ``selector`` (default body),
               whitespace collapsed; stored under ``field`` when given.
    wait       ``selector_visible`` (first match visible, default 10 s), ``delay``
               (sleep ``timeout`` ms, default 1000), ``network_idle`` (up to 2 s).
    press_key  keyboard.press(value).
    script     page.evaluate(script).

``{{param}}`` placeholders are filled in selector, value, url, strategy, field and
fallback selectors (not in scripts). A step with ``"optional": true`` may fail without
failing the action. Locators are strict like Playwright's: a click whose selector
matches several elements fails over to the next fallback.

Interrupt handlers (popups such as a newsletter dialog) are checked before every click
(at most 1 s per handler) and after every successful navigate (the handler's
``detect_timeout_ms``, default 300 ms). A handler that fired once is not checked again
in the same session, unless it says ``"repeat": true`` (a page that can come back).

Bot checks (the mapping's ``bot_checks`` selectors) are looked for, without waiting, after
every navigate, before every click and interrupt handler and after a handler fired, every
quarter second during a ``selector_visible`` wait, after a failed step and at the end of the
action. When one is visible the action fails with "blocked by a bot check", even from an
optional step or an interrupt handler's dismiss steps. Nothing on that page is clicked, typed
into or waited out.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Mapping as MappingType, Sequence
from urllib.parse import urlsplit

from .mapping import interpolate

NAVIGATE_TIMEOUT_MS = 15000
CLICK_TIMEOUT_MS = 2000
TYPE_TIMEOUT_MS = 5000
SELECT_TIMEOUT_MS = 5000
EXTRACT_TIMEOUT_MS = 5000
SELECTOR_VISIBLE_TIMEOUT_MS = 10000
DEFAULT_DELAY_MS = 1000
SETTLE_TIMEOUT_MS = 2000
INTERRUPT_DEFAULT_TIMEOUT_MS = 300
INTERRUPT_PRECLICK_CAP_MS = 1000
MAX_EXTRACT_CHARS = 2000
BOT_CHECK_MESSAGE = "blocked by a bot check"
# How many matches of one bot-check selector are tested for visibility.
BOT_CHECK_MAX_MATCHES = 5
# A selector_visible wait looks for bot checks this often (ms) while it waits.
BOT_CHECK_POLL_MS = 250


class StepFailed(Exception):
    """One step could not be carried out."""


class BotCheckBlocked(StepFailed):
    """A human-verification page is showing. The action fails and the page is left alone."""

    def __init__(self, selector: str = ""):
        super().__init__(BOT_CHECK_MESSAGE)
        self.selector = selector


@dataclass
class StepResult:
    index: int
    action: str
    ok: bool
    optional: bool = False
    strategy: str | None = None
    content: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {"index": self.index, "action": self.action, "ok": self.ok}
        for key in ("optional", "strategy", "content", "error"):
            value = getattr(self, key)
            if value not in (None, False):
                out[key] = value
        return out


@dataclass
class RunResult:
    ok: bool
    steps: list[StepResult] = field(default_factory=list)
    error: str | None = None
    failed_index: int | None = None
    extracted: dict[str, str] = field(default_factory=dict)
    blocked: bool = False  # a bot check was showing; error is BOT_CHECK_MESSAGE
    blocked_by: str | None = None  # the bot-check selector that matched


@dataclass
class InterruptState:
    """Interrupt handlers of one session and which of them already fired."""

    handlers: list[dict[str, Any]]
    dismissed: set[str] = field(default_factory=set)

    @property
    def active(self) -> bool:
        return any(h.get("repeat") or h.get("detect") not in self.dismissed for h in self.handlers)


def resolve_step(step: MappingType[str, Any], values: MappingType[str, Any]) -> dict[str, Any]:
    """A copy of the step with placeholders filled in."""
    out = dict(step)
    for key in ("selector", "value", "url", "strategy", "field"):
        if isinstance(out.get(key), str):
            out[key] = interpolate(out[key], values)
    if out.get("fallbacks"):
        out["fallbacks"] = [
            {"type": fb.get("type"), "selector": interpolate(str(fb.get("selector", "")), values)}
            for fb in out["fallbacks"]
        ]
    return out


def _locator(page: Any, kind: str, selector: str):
    if kind == "css":
        return page.locator(selector)
    if kind == "xpath":
        return page.locator(selector if selector.startswith("xpath=") else "xpath=" + selector)
    if kind == "text":
        return page.get_by_text(selector)
    if kind == "text_exact":
        return page.get_by_text(selector, exact=True)
    if kind == "role":
        return page.get_by_role(selector)
    if kind == "label":
        return page.get_by_label(selector)
    if kind == "placeholder":
        return page.get_by_placeholder(selector)
    raise StepFailed(f"unknown fallback type {kind!r}")


def _short(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    first = text[0] if text else type(exc).__name__
    return first[:300]


def check_navigation_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise StepFailed(f"refusing to navigate to {url!r}: only http(s) URLs are allowed")


async def _attempts(page: Any, step: dict[str, Any], run) -> str:
    """Try the primary selector then each fallback with ``run(locator)``; return the winner."""
    errors = []
    candidates = [("primary", "css", step["selector"])]
    candidates += [("fallback", fb["type"], fb["selector"]) for fb in step.get("fallbacks") or []]
    for origin, kind, selector in candidates:
        try:
            locator = _locator(page, kind, selector) if origin == "fallback" else page.locator(selector)
            await run(locator)
            return f"{origin}:{kind}:{selector}" if origin == "fallback" else f"primary:{selector}"
        except StepFailed:
            raise
        except Exception as exc:  # Playwright TimeoutError, strict-mode violation, bad selector
            errors.append(f"{origin} {kind} {selector!r}: {_short(exc)}")
    raise StepFailed("all selectors exhausted: " + " | ".join(errors))


async def bot_check_on_page(page: Any, selectors: Sequence[str]) -> str | None:
    """The first bot-check selector with a visible match on the page, or None. Never waits."""
    for selector in selectors:
        try:
            matches = page.locator(selector)
            count = await matches.count()
            for i in range(min(count, BOT_CHECK_MAX_MATCHES)):
                if await matches.nth(i).is_visible():
                    return selector
        except Exception:  # a selector this page cannot evaluate is not a match
            continue
    return None


async def _refuse_bot_check(page: Any, selectors: Sequence[str]) -> None:
    if selectors:
        found = await bot_check_on_page(page, selectors)
        if found:
            raise BotCheckBlocked(found)


async def _wait_visible(page: Any, selector: str, timeout_ms: int, bot_checks: Sequence[str]) -> None:
    """Wait for the first match of ``selector`` to be visible. With bot checks, wait in short
    slices and stop as soon as one shows, instead of waiting on a human-verification page."""
    target = page.locator(selector).first
    if not bot_checks:
        try:
            await target.wait_for(state="visible", timeout=timeout_ms)
        except Exception as exc:
            raise StepFailed(f"{selector!r} did not become visible: {_short(exc)}") from exc
        return
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_ms / 1000
    while True:
        await _refuse_bot_check(page, bot_checks)
        left_ms = int((deadline - loop.time()) * 1000)
        try:
            await target.wait_for(state="visible", timeout=max(1, min(BOT_CHECK_POLL_MS, left_ms)))
            return
        except Exception as exc:
            if type(exc).__name__ != "TimeoutError" or loop.time() >= deadline:
                await _refuse_bot_check(page, bot_checks)
                raise StepFailed(f"{selector!r} did not become visible: {_short(exc)}") from exc


async def _settle(page: Any) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
    except Exception:
        pass


async def run_interrupts(
    page: Any,
    state: InterruptState | None,
    cap_ms: int | None = None,
    bot_checks: Sequence[str] = (),
) -> list[str]:
    """Dismiss any visible interrupt (popup); returns the detect selectors that fired.

    Dismiss steps are best effort, except that a bot check met on the way (BotCheckBlocked) is
    raised at once."""
    if state is None:
        return []
    fired = []
    for handler in state.handlers:
        detect = handler.get("detect")
        if not detect or detect in state.dismissed:
            continue
        timeout = handler.get("detect_timeout_ms") or INTERRUPT_DEFAULT_TIMEOUT_MS
        if cap_ms is not None:
            timeout = min(timeout, cap_ms)
        try:
            await page.locator(detect).first.wait_for(state="visible", timeout=timeout)
        except Exception:
            continue  # not there
        if not handler.get("repeat"):
            state.dismissed.add(detect)
        fired.append(detect)
        for step in handler.get("dismiss") or []:
            try:
                await execute_step(page, resolve_step(step, {}), interrupts=None, bot_checks=bot_checks)
            except BotCheckBlocked:
                raise
            except Exception:
                pass  # dismiss steps are best effort
    return fired


async def execute_step(
    page: Any,
    step: dict[str, Any],
    *,
    interrupts: InterruptState | None,
    bot_checks: Sequence[str] = (),
) -> StepResult:
    """Run one already-interpolated step. Raises StepFailed on failure, BotCheckBlocked when a
    bot check is showing after a navigate or before a click."""
    action = step.get("action")
    timeout = step.get("timeout") or None
    result = StepResult(index=-1, action=str(action), ok=True)

    if action == "navigate":
        url = step["url"]
        check_navigation_url(url)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout or NAVIGATE_TIMEOUT_MS)
        except Exception as exc:
            raise StepFailed(f"navigation to {url} failed: {_short(exc)}") from exc
        await _refuse_bot_check(page, bot_checks)
        if await run_interrupts(page, interrupts, bot_checks=bot_checks):
            await _refuse_bot_check(page, bot_checks)

    elif action == "click":
        await _refuse_bot_check(page, bot_checks)
        if interrupts is not None and interrupts.active:
            if await run_interrupts(page, interrupts, cap_ms=INTERRUPT_PRECLICK_CAP_MS, bot_checks=bot_checks):
                await _refuse_bot_check(page, bot_checks)
        per_try = timeout or CLICK_TIMEOUT_MS
        result.strategy = await _attempts(page, step, lambda loc: loc.click(timeout=per_try))
        await _settle(page)

    elif action == "type":
        text = step.get("value", "")
        press_enter = bool(step.get("press_enter"))

        async def fill(loc):
            await loc.fill(text, timeout=timeout or TYPE_TIMEOUT_MS)
            if press_enter:
                await loc.press("Enter")

        result.strategy = await _attempts(page, step, fill)

    elif action == "select":
        value = step.get("value", "")
        loc = page.locator(step["selector"])
        try:
            await loc.select_option(value=value, timeout=timeout or SELECT_TIMEOUT_MS)
        except Exception:
            try:
                await loc.select_option(label=value, timeout=timeout or SELECT_TIMEOUT_MS)
            except Exception as exc:
                raise StepFailed(f"select {value!r} in {step['selector']!r} failed: {_short(exc)}") from exc

    elif action == "extract":
        selector = step.get("selector") or "body"
        try:
            # innerText keeps the visible word breaks ("Cart 1 item"); textContent would run
            # adjacent elements together ("Cart11 item").
            text = await page.locator(selector).first.inner_text(timeout=timeout or EXTRACT_TIMEOUT_MS)
        except Exception as exc:
            raise StepFailed(f"extract {selector!r} failed: {_short(exc)}") from exc
        text = re.sub(r"\s+", " ", text or "").strip()
        result.content = text[:MAX_EXTRACT_CHARS]

    elif action == "wait":
        strategy = step.get("strategy") or ""
        if strategy == "selector_visible":
            await _wait_visible(page, step["selector"], timeout or SELECTOR_VISIBLE_TIMEOUT_MS, bot_checks)
        elif strategy == "network_idle":
            await _settle(page)
        else:
            await asyncio.sleep((timeout or DEFAULT_DELAY_MS) / 1000)

    elif action == "press_key":
        key = step.get("value") or ""
        try:
            await page.keyboard.press(key)
        except Exception as exc:
            raise StepFailed(f"press {key!r} failed: {_short(exc)}") from exc

    elif action == "script":
        try:
            await page.evaluate(step["script"])
        except Exception as exc:
            raise StepFailed(f"script failed: {_short(exc)}") from exc

    else:
        raise StepFailed(f"unknown step action {action!r}")
    return result


def _blocked(run: RunResult, index: int | None, selector: str | None) -> RunResult:
    run.ok = False
    run.blocked = True
    run.blocked_by = selector
    run.failed_index = index
    run.error = BOT_CHECK_MESSAGE
    return run


async def run_steps(
    page: Any,
    steps: list[dict[str, Any]],
    values: MappingType[str, Any],
    *,
    interrupts: InterruptState | None = None,
    bot_checks: Sequence[str] = (),
) -> RunResult:
    """Run a mapping action's steps in order; stop at the first failing non-optional step.

    With ``bot_checks``, a visible bot check fails the run (``blocked``), whichever step met it.
    """
    run = RunResult(ok=True)
    for index, raw_step in enumerate(steps):
        step = resolve_step(raw_step, values)
        optional = bool(step.get("optional"))
        try:
            result = await execute_step(page, step, interrupts=interrupts, bot_checks=bot_checks)
        except BotCheckBlocked as exc:
            run.steps.append(StepResult(index=index, action=str(step.get("action")), ok=False, optional=optional,
                                        error=str(exc)))
            return _blocked(run, index, exc.selector)
        except StepFailed as exc:
            result = StepResult(index=index, action=str(step.get("action")), ok=False, optional=optional, error=str(exc))
            run.steps.append(result)
            found = await bot_check_on_page(page, bot_checks) if bot_checks else None
            if found:
                return _blocked(run, index, found)
            if optional:
                continue
            run.ok = False
            run.failed_index = index
            run.error = f"step {index} ({result.action}) failed: {exc}"
            return run
        result.index = index
        result.optional = optional
        run.steps.append(result)
        if result.content is not None and step.get("field"):
            run.extracted[step["field"]] = result.content
    found = await bot_check_on_page(page, bot_checks) if bot_checks else None
    if found:
        return _blocked(run, None, found)
    return run


class ScreenMatcher:
    """URL -> screen name. Longer url_patterns are tried first, so /shop/cart beats /shop."""

    def __init__(self, screens: MappingType[str, MappingType[str, Any]]):
        compiled = []
        for name, screen in screens.items():
            pattern = (screen or {}).get("url_pattern")
            if not pattern:
                continue
            compiled.append((len(pattern), name, re.compile(pattern)))
        # Longest pattern first; ties broken by name so the order never depends on dict order.
        compiled.sort(key=lambda item: (-item[0], item[1]))
        self._patterns = [(name, regex) for _, name, regex in compiled]

    def detect(self, url: str, fallback: str = "unknown") -> str:
        for name, regex in self._patterns:
            if regex.search(url or ""):
                return name
        return fallback or "unknown"
