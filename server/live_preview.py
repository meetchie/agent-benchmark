"""The live preview of a run: a fresh picture of the agent's page about once a second.

The status reply used to carry one screenshot per finished step, so the preview stayed
empty while Chromium started, the site loaded and the model chose its first step, and
then froze for every model turn. ``LivePreview`` keeps the newest frame of the page the
agent is on, from the moment the browser has a page until the run stops:

    preview = LivePreview(on_frame=..., on_page=...)
    preview.start(agent.browser_session)   # a background task: one capture at a time
    preview.nudge()                         # capture now instead of at the next tick
    await preview.stop()                    # idempotent; always call it in a finally

Each frame is a JPEG of the viewport from CDP ``Page.captureScreenshot``, sent on the
CDP session browser-use already holds for the agent's tab. It never changes what
browser-use does: it never moves the agent's focus, never attaches to a new target and
never triggers browser-use's focus recovery, and nothing the agent does waits for it. A
capture that fails or hangs (the tab just closed, a navigation, a dialog) is dropped
after ``CAPTURE_TIMEOUT_S`` and logged at debug level. A frame identical to the one
before is not passed on, so a page that does not move (a model turn) costs the viewer
nothing.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)

# How often the page is captured while the run is going.
FRAME_INTERVAL_S = 1.0
# How often the loop looks before it has a first frame: for the browser's first tab,
# then for the site on it (the blank tab is not captured).
PAGE_POLL_S = 0.25
# A capture that takes longer than this is given up (the next one is tried on schedule).
CAPTURE_TIMEOUT_S = 5.0
JPEG_QUALITY = 70

# Pages with nothing of the site on them: the blank tab the browser opens with (where
# browser-use draws its own animation) and the browser's own pages.
_NOT_THE_SITE = ("about:", "chrome://", "chrome-error://", "devtools://")


def has_page(browser_session: Any) -> bool:
    """Whether the browser is up and the agent has a tab (any URL, the blank one included)."""
    return (
        browser_session is not None
        and bool(getattr(browser_session, "agent_focus_target_id", None))
        and getattr(browser_session, "session_manager", None) is not None
    )


def _site_tab(browser_session: Any) -> Optional[str]:
    """The target id of the agent's tab when it shows a site, read without side effects."""
    if not has_page(browser_session):
        return None
    target_id = browser_session.agent_focus_target_id
    target = browser_session.session_manager.get_target(target_id)
    url = (getattr(target, "url", "") or "") if target is not None else ""
    if not url or url.startswith(_NOT_THE_SITE):
        return None
    return target_id


async def capture_page(browser_session: Any, quality: int = JPEG_QUALITY) -> Optional[bytes]:
    """One JPEG of the agent's tab, or None while it shows no site or has no live session.

    The session is asked for only after ``validate_session`` said the tab has one, with
    no await in between: asking browser-use for the session of a tab that has just gone
    away makes it reset the agent's focus and start its recovery, which is browser-use's
    own business. ``focus=False`` keeps the agent's focus where it is.
    """
    target_id = _site_tab(browser_session)
    if target_id is None:
        return None
    if not await browser_session.session_manager.validate_session(target_id):
        return None
    cdp = await browser_session.get_or_create_cdp_session(target_id, focus=False)
    result = await cdp.cdp_client.send.Page.captureScreenshot(
        params={"format": "jpeg", "quality": quality, "optimizeForSpeed": True},
        session_id=cdp.session_id,
    )
    data = (result or {}).get("data")
    return base64.b64decode(data) if data else None


class LivePreview:
    """Keeps the newest frame of a browser-use session's page while a run is going.

    ``on_frame(jpeg)`` is called with every new frame (never twice in a row with the same
    bytes); ``on_page()`` once, when the browser first has a tab. An exception from
    either is logged and the loop goes on.
    """

    def __init__(
        self,
        on_frame: Callable[[bytes], None],
        on_page: Optional[Callable[[], None]] = None,
        capture: Callable[[Any], Awaitable[Optional[bytes]]] = capture_page,
    ):
        self._on_frame = on_frame
        self._on_page = on_page
        self._capture = capture
        self._session: Any = None
        self._task: Optional[asyncio.Task] = None
        self._wake = asyncio.Event()
        self._last: Optional[bytes] = None
        self._saw_page = False
        self._stopped = False
        self.captures = 0  # capture attempts
        self.failures = 0  # attempts that raised or timed out

    def start(self, browser_session: Any) -> None:
        """Start the background loop for ``browser_session`` (once; later calls do nothing)."""
        if self._task is not None or self._stopped:
            return
        self._session = browser_session
        self._task = asyncio.create_task(self._loop(), name="live-preview")

    def nudge(self) -> None:
        """Capture as soon as the capture in flight (if any) is done, not at the next tick.

        Never waits, so a step hook can call it without slowing the agent down.
        """
        self._wake.set()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def stop(self) -> None:
        """Stop the loop and wait for it to end. Safe to call more than once."""
        self._stopped = True
        task, self._task = self._task, None
        if task is None or task.done():
            return
        task.cancel()
        # A cancel of our own caller propagates from here; the loop is cancelled anyway.
        await asyncio.wait({task}, timeout=CAPTURE_TIMEOUT_S + 1)

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stopped:
            began = loop.time()
            self._wake.clear()
            if not self._saw_page and has_page(self._session):
                self._saw_page = True
                self._call(self._on_page)
            if self._saw_page:
                await self._capture_once()
            pause = FRAME_INTERVAL_S if self._last is not None else PAGE_POLL_S
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=max(0.02, pause - (loop.time() - began)))
            except asyncio.TimeoutError:
                pass

    async def _capture_once(self) -> None:
        self.captures += 1
        try:
            jpeg = await asyncio.wait_for(self._capture(self._session), timeout=CAPTURE_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001  (a missed frame is never worth a failed run)
            self.failures += 1
            log.debug("Live preview capture failed: %s: %s", type(e).__name__, e)
            return
        if jpeg and jpeg != self._last:
            self._last = jpeg
            self._call(self._on_frame, jpeg)

    @staticmethod
    def _call(fn, *args) -> None:
        if fn is None:
            return
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            log.exception("Live preview callback failed")
