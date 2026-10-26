"""LocalRindlerHost: the Rindler arm's tools, served in-process from a mapping.

It stands in for the retired Rindler stack (MCP server, job queue, databases, OAuth):
a headless Chromium driven by Playwright runs the mapping's steps, and every tool call
returns the same JSON envelope the Rindler server returned:

    {
      "screen": "search_results",
      "context": {...},                 # values kept across calls (context extractors, sets_context)
      "data": {"page_url": ..., "products": [...] | "cart_items": [...], "page_info": ...},
      "available_actions": [...],       # actions valid on this screen
      "global_actions": [...]           # always valid
    }

Failures come back as ``{"error": {"code", "message"}, "screen", "context",
"available_actions", "global_actions"}`` with ``isError: true``.

Interface (MCP-shaped, so agent loops written against an MCP client need few changes):

    host = LocalRindlerHost(load_mapping("vhlistings"))
    tools = await host.list_tools()                 # [{"name", "description", "inputSchema"}]
    result = await host.call_tool("start_session", {"url": "https://vhlistings.com"})
    envelope = json.loads(result["content"][0]["text"])
    ...
    await host.close()                              # or: async with LocalRindlerHost(...) as host
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from .extract import extract_cart_items, extract_products
from .interpreter import (
    InterruptState,
    ScreenMatcher,
    StepFailed,
    check_navigation_url,
    run_steps,
)
from .mapping import Mapping, host_of, interpolate, stringify
from .tools import build_tools, param_defaults

log = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_VIEWPORT = {"width": 1280, "height": 800}
EXTRA_CHROMIUM_ARGS = ["--disable-blink-features=AutomationControlled"]
START_NAVIGATE_TIMEOUT_MS = 15000
CONTEXT_EXTRACT_TIMEOUT_MS = 1500
DEFAULT_CALL_TIMEOUT_S = 120.0


def _keychain_args() -> list[str]:
    try:
        from browser_env import chromium_args
    except ImportError:  # used outside the server package
        return ["--use-mock-keychain", "--password-store=basic"]
    return chromium_args()


def _chromium_executable() -> str | None:
    try:
        from browser_env import chromium_path
    except ImportError:
        return None
    return chromium_path()


def _check_chromium_starts(executable: str) -> None:
    """Raise ChromiumNotFoundError, with the fix, when this Chromium cannot start."""
    try:
        from browser_env import ChromiumNotFoundError, chromium_start_problem
    except ImportError:  # used outside the server package: Playwright's launch error has to do
        return
    problem = chromium_start_problem(executable)
    if problem:
        raise ChromiumNotFoundError(problem)


def _fit_tmpdir_for_chromium() -> None:
    """On Linux, a TMPDIR short enough for Chromium to start (see browser_env)."""
    try:
        from browser_env import fit_tmpdir_for_chromium
    except ImportError:
        return
    fit_tmpdir_for_chromium()


def _headless_default() -> bool:
    try:
        from browser_env import headless
    except ImportError:
        return True
    return headless()


def text_result(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}], "isError": is_error}


def parse_result(result: dict[str, Any]) -> dict[str, Any]:
    """The envelope inside a call_tool result (a dict; errors keep their "error" key)."""
    content = result.get("content") or []
    if not content:
        return {"error": {"code": "empty_response", "message": "tool returned no content"}}
    text = content[0].get("text", "")
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {"error": {"code": "non_json_response", "message": str(text)[:500]}}
    if result.get("isError") and "error" not in data:
        data = {"error": {"code": "tool_error", "message": str(text)[:500]}}
    return data


class LocalRindlerHost:
    """One browser session at a time, driven by one site mapping."""

    def __init__(
        self,
        mapping: Mapping,
        *,
        headless: bool | None = None,
        viewport: dict[str, int] | None = None,
        user_agent: str | None = DEFAULT_USER_AGENT,
        executable_path: str | None = None,
        extra_args: list[str] | None = None,
        call_timeout_s: float = DEFAULT_CALL_TIMEOUT_S,
        allow_any_domain: bool = False,
    ):
        self.mapping = mapping
        self.headless = _headless_default() if headless is None else headless
        self.viewport = dict(viewport or DEFAULT_VIEWPORT)
        self.user_agent = user_agent
        self.executable_path = executable_path
        self.extra_args = list(EXTRA_CHROMIUM_ARGS) + list(extra_args or [])
        self.call_timeout_s = call_timeout_s
        self.allow_any_domain = allow_any_domain
        self.screens = ScreenMatcher(mapping.screens)

        self.session_id: str | None = None
        self.screen: str = "unknown"
        self.context: dict[str, Any] = {}
        self.interrupts = InterruptState(mapping.interrupt_handlers)
        self.calls: int = 0

        self._lock = asyncio.Lock()
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    # -- lifecycle -----------------------------------------------------------------

    async def __aenter__(self) -> "LocalRindlerHost":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    @property
    def page(self):
        return self._page

    async def _ensure_browser(self) -> None:
        if self._browser is not None:
            return
        from playwright.async_api import async_playwright

        executable = self.executable_path or _chromium_executable()
        if executable:
            _check_chromium_starts(executable)
        _fit_tmpdir_for_chromium()  # before Playwright starts: its browsers get its environment
        self._pw = await async_playwright().start()
        args = _keychain_args()
        for arg in self.extra_args:
            if arg not in args:
                args.append(arg)
        launch: dict[str, Any] = {"headless": self.headless, "args": args}
        if executable:
            launch["executable_path"] = executable
        self._browser = await self._pw.chromium.launch(**launch)

    async def _close_session(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
        self._context = None
        self._page = None
        self.session_id = None
        self.screen = "unknown"
        self.context = {}
        self.interrupts = InterruptState(self.mapping.interrupt_handlers)

    async def close(self) -> None:
        """Close the session, the browser and Playwright. Safe to call more than once."""
        await self._close_session()
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
        self._browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._pw = None

    # -- MCP-shaped interface -------------------------------------------------------

    async def list_tools(self) -> list[dict[str, Any]]:
        return build_tools(self.mapping)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run one tool; always returns ``{"content": [{"type": "text", "text": json}], "isError": bool}``."""
        args = dict(arguments or {})
        async with self._lock:
            self.calls += 1
            try:
                payload = await asyncio.wait_for(self._dispatch(name, args), timeout=self.call_timeout_s)
            except asyncio.TimeoutError:
                payload = self._error("timeout", f"{name} did not finish within {self.call_timeout_s:.0f}s")
            except Exception as exc:  # never let a browser error escape as an exception
                log.exception("tool %s crashed", name)
                payload = self._error("internal_error", f"{type(exc).__name__}: {exc}")
        return text_result(payload, is_error="error" in payload)

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """call_tool, returning the parsed envelope."""
        return parse_result(await self.call_tool(name, arguments))

    # -- envelope helpers -------------------------------------------------------------

    def available_actions(self, screen: str | None = None) -> list[str]:
        screen = screen or self.screen
        config = self.mapping.screens.get(screen)
        if config is None:
            return sorted(self.mapping.actions)  # unknown screen: everything is allowed
        return list(config.get("available_actions") or [])

    def _envelope(self, data: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "screen": self.screen,
            "context": dict(self.context),
            "data": data or {},
            "available_actions": self.available_actions(),
            "global_actions": self.mapping.global_actions(),
        }

    def _error(self, code: str, message: str) -> dict[str, Any]:
        return {
            "error": {"code": code, "message": message},
            "screen": self.screen,
            "context": dict(self.context),
            "available_actions": self.available_actions() if self.session_id else [],
            "global_actions": self.mapping.global_actions(),
        }

    def _action_allowed(self, name: str) -> bool:
        if name in self.mapping.global_actions():
            return True
        if self.screen not in self.mapping.screens:
            return True
        return name in self.available_actions()

    # -- dispatch -------------------------------------------------------------------

    async def _dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "start_session":
            return await self._start_session(str(args.get("url") or ""))
        if name == "close_session":
            had = self.session_id is not None
            await self._close_session()
            return {"screen": "closed", "context": {}, "data": {"closed": had}, "available_actions": [],
                    "global_actions": ["start_session"]}
        if name not in self.mapping.actions:
            return self._error("unknown_action", f"{name!r} is not an action of the {self.mapping.domain} mapping")
        if self._page is None:
            return self._error("no_session", "No browser session. Call start_session first.")
        if not self._action_allowed(name):
            return self._error(
                "invalid_action",
                f"{name!r} is not available on screen {self.screen!r}. "
                f"Available: {self.available_actions()}; global: {self.mapping.global_actions()}",
            )
        return await self._run_action(name, args)

    async def _start_session(self, url: str) -> dict[str, Any]:
        if not url:
            return self._error("invalid_url", "url is required")
        try:
            check_navigation_url(url)
        except StepFailed as exc:
            return self._error("invalid_url", str(exc))
        if not self.allow_any_domain and not self.mapping.matches_url(url):
            return self._error(
                "no_site_config",
                f"this host only has the {self.mapping.domain} mapping; {host_of(url) or url!r} is not covered",
            )

        await self._close_session()
        await self._ensure_browser()
        options: dict[str, Any] = {"viewport": self.viewport}
        if self.user_agent:
            options["user_agent"] = self.user_agent
        self._context = await self._browser.new_context(**options)
        self._page = await self._context.new_page()
        self.session_id = str(uuid.uuid4())

        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=START_NAVIGATE_TIMEOUT_MS)
        except Exception as exc:
            message = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            await self._close_session()
            return self._error("navigation_error", f"failed to open {url}: {message[:300]}")
        try:  # give client-rendered sites a moment to put their main content up
            await self._page.locator("main").first.wait_for(state="visible", timeout=2000)
        except Exception:
            pass

        self.screen = self.screens.detect(self._page.url, fallback="unknown")
        await self._run_context_extractors()
        data = await self._page_data()
        data = {"session_id": self.session_id, **data}
        return self._envelope(data)

    def _values(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        values: dict[str, Any] = dict(self.mapping.defaults)
        values.update({k: v for k, v in self.context.items() if isinstance(v, (str, int, float, bool))})
        values.update(param_defaults(self.mapping, name))
        values.update({k: v for k, v in args.items() if k != "session_id"})
        return values

    async def _run_action(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        action = self.mapping.actions[name]
        steps = action.get("steps") or []

        # Steps-free actions can return data pre-written into the screen's static_data.
        if not steps:
            static = (self.mapping.screens.get(self.screen) or {}).get("static_data") or {}
            if name in static:
                if action.get("target_screen"):
                    self.screen = action["target_screen"]
                return self._envelope(static[name] if isinstance(static[name], dict) else {"content": static[name]})

        values = self._values(name, args)
        run = await run_steps(self._page, steps, values, interrupts=self.interrupts)
        if not run.ok:
            return self._error("execution_failed", run.error or f"{name} failed")

        if action.get("stays_on_screen"):
            pass
        elif action.get("target_screen"):
            self.screen = action["target_screen"]
        else:
            self.screen = self.screens.detect(self._page.url, fallback=self.screen)

        for key, template in self.mapping.sets_context(name).items():
            self.context[key] = interpolate(template, {k: stringify(v) for k, v in values.items()})

        await self._run_context_extractors()
        data = await self._page_data()
        if run.extracted:
            data["extracted"] = dict(run.extracted)
        return self._envelope(data)

    async def _run_context_extractors(self) -> None:
        for name, extractor in self.mapping.context_extractors.items():
            steps = []
            for step in extractor.get("steps") or []:
                step = dict(step)
                if step.get("action") in ("extract", "wait") and not step.get("timeout"):
                    step["timeout"] = CONTEXT_EXTRACT_TIMEOUT_MS
                steps.append(step)
            try:
                run = await run_steps(self._page, steps, self._values(name, {}), interrupts=None)
            except Exception:
                continue
            for result in run.steps:
                if result.ok and result.content:
                    self.context[name] = result.content[:300]
                    break

    async def _page_data(self) -> dict[str, Any]:
        page = self._page
        data: dict[str, Any] = {"page_url": page.url}
        try:
            snapshot = await page.locator("body").aria_snapshot(timeout=5000)
        except Exception:
            snapshot = ""
        if self.screen == "cart":
            items = extract_cart_items(snapshot)
            if items:
                data["cart_items"] = items
        else:
            products = extract_products(snapshot)
            if products:
                data["products"] = products
        if self.mapping.page_extractor:
            try:
                info = await page.evaluate(self.mapping.page_extractor)
            except Exception as exc:
                log.debug("page_extractor failed: %s", exc)
                info = None
            if info is not None:
                data["page_info"] = info
        return data
