"""The live preview's frame loop, on a stand-in browser session (no browser, no network)."""

import asyncio
import logging

import pytest

import live_preview
from live_preview import LivePreview, capture_page
from tests.fakes import FakeBrowserSession

SITE = "https://shop.example/"


@pytest.fixture(autouse=True)
def fast_loop(monkeypatch):
    monkeypatch.setattr(live_preview, "FRAME_INTERVAL_S", 0.02)
    monkeypatch.setattr(live_preview, "PAGE_POLL_S", 0.01)
    monkeypatch.setattr(live_preview, "CAPTURE_TIMEOUT_S", 0.2)


class Recorder:
    def __init__(self):
        self.frames = []
        self.pages = 0

    def frame(self, jpeg):
        self.frames.append(jpeg)

    def page(self):
        self.pages += 1


async def until(condition, timeout=2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        if loop.time() > deadline:
            raise AssertionError("timed out")
        await asyncio.sleep(0.005)


def preview_tasks():
    return [t for t in asyncio.all_tasks() if t.get_name() == "live-preview" and not t.done()]


async def test_no_frame_until_the_site_shows_then_a_frame_at_once():
    session, seen = FakeBrowserSession(), Recorder()
    preview = LivePreview(on_frame=seen.frame, on_page=seen.page)
    preview.start(session)
    try:
        await asyncio.sleep(0.05)
        assert (seen.pages, seen.frames, session.captures) == (0, [], 0)  # the browser is still starting

        session.open_tab()  # a blank tab: the browser is up, the site not open yet
        await until(lambda: seen.pages == 1)
        await asyncio.sleep(0.05)
        assert seen.frames == []

        session.show(SITE, b"\xff\xd8site")
        await until(lambda: seen.frames)
        assert seen.frames == [b"\xff\xd8site"]
        assert seen.pages == 1
    finally:
        await preview.stop()


async def test_until_the_first_frame_it_looks_more_often(monkeypatch):
    """The first picture matters most: the loop does not wait a whole interval for it."""
    monkeypatch.setattr(live_preview, "FRAME_INTERVAL_S", 30.0)
    session, seen = FakeBrowserSession(), Recorder()
    session.open_tab()  # blank: nothing to capture yet
    preview = LivePreview(on_frame=seen.frame)
    preview.start(session)
    try:
        await until(lambda: preview.captures >= 2)  # looked twice already, found no site
        session.show(SITE, b"\xff\xd8site")
        await until(lambda: seen.frames, timeout=1.0)
        captures = preview.captures
        await asyncio.sleep(0.2)
        assert preview.captures == captures  # then at FRAME_INTERVAL_S
    finally:
        await preview.stop()


async def test_frames_keep_coming_while_nothing_else_happens():
    """A model turn: the agent sends nothing to the browser, the preview still updates."""
    session, seen = FakeBrowserSession(), Recorder()
    session.open_tab()
    session.show(SITE, b"\xff\xd8frame-0")
    preview = LivePreview(on_frame=seen.frame)
    preview.start(session)
    try:
        for i in range(1, 4):
            await until(lambda: seen.frames and seen.frames[-1] == session.picture)
            session.picture = b"\xff\xd8frame-%d" % i  # an animation on the page
        await until(lambda: len(seen.frames) == 4)
        assert seen.frames == [b"\xff\xd8frame-%d" % i for i in range(4)]
    finally:
        await preview.stop()


async def test_a_page_that_does_not_change_is_passed_on_once():
    session, seen = FakeBrowserSession(), Recorder()
    session.open_tab()
    session.show(SITE, b"\xff\xd8still")
    preview = LivePreview(on_frame=seen.frame)
    preview.start(session)
    try:
        await until(lambda: session.captures >= 5)
        assert seen.frames == [b"\xff\xd8still"]
    finally:
        await preview.stop()


async def test_it_never_moves_the_agents_focus_or_asks_for_a_tab_that_went_away():
    session, seen = FakeBrowserSession(), Recorder()
    session.open_tab()
    session.show(SITE, b"\xff\xd8a")
    preview = LivePreview(on_frame=seen.frame)
    preview.start(session)
    try:
        await until(lambda: session.captures >= 3)
        # A tab whose session is gone: browser-use would reset the focus and start its
        # recovery if asked for that session, so the preview does not ask.
        session.attached = False
        asked = len(session.session_requests)
        await asyncio.sleep(0.1)
        assert len(session.session_requests) == asked
    finally:
        await preview.stop()
    assert session.session_requests
    assert set(session.session_requests) == {(FakeBrowserSession.TARGET, False)}
    assert session.agent_focus_target_id == FakeBrowserSession.TARGET


async def test_failed_captures_are_skipped_quietly_and_the_loop_goes_on(caplog):
    caplog.set_level(logging.DEBUG, logger="live_preview")
    session, seen = FakeBrowserSession(), Recorder()
    session.open_tab()
    session.show(SITE, b"\xff\xd8after")
    session.fail_next = 3
    preview = LivePreview(on_frame=seen.frame)
    preview.start(session)
    try:
        await until(lambda: seen.frames)
    finally:
        await preview.stop()
    assert seen.frames == [b"\xff\xd8after"]
    assert preview.failures == 3
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_a_capture_that_hangs_is_given_up_and_the_next_one_runs():
    session, seen = FakeBrowserSession(), Recorder()
    session.open_tab()
    session.show(SITE, b"\xff\xd8later")
    session.hang_next = 1
    preview = LivePreview(on_frame=seen.frame)
    preview.start(session)
    try:
        await until(lambda: seen.frames, timeout=2.0)
    finally:
        await preview.stop()
    assert preview.failures == 1
    assert session.in_flight == 0


async def test_one_capture_at_a_time_however_often_it_is_nudged():
    session, seen = FakeBrowserSession(), Recorder()
    session.open_tab()
    session.show(SITE, b"\xff\xd8x")
    session.delay = 0.03
    preview = LivePreview(on_frame=seen.frame)
    preview.start(session)
    try:
        for _ in range(50):
            preview.nudge()
            await asyncio.sleep(0.002)
        await until(lambda: session.captures >= 3)
    finally:
        await preview.stop()
    assert session.max_in_flight == 1


async def test_a_nudge_captures_without_waiting_for_the_next_tick(monkeypatch):
    monkeypatch.setattr(live_preview, "FRAME_INTERVAL_S", 30.0)
    session, seen = FakeBrowserSession(), Recorder()
    session.open_tab()
    session.show(SITE, b"\xff\xd8before")
    preview = LivePreview(on_frame=seen.frame)
    preview.start(session)
    try:
        await until(lambda: seen.frames)
        session.picture = b"\xff\xd8after-the-step"
        preview.nudge()
        await until(lambda: len(seen.frames) == 2, timeout=1.0)
    finally:
        await preview.stop()
    assert seen.frames[-1] == b"\xff\xd8after-the-step"


async def test_stop_ends_the_loop_for_good():
    session, seen = FakeBrowserSession(), Recorder()
    session.open_tab()
    session.show(SITE, b"\xff\xd8x")
    session.delay = 0.05  # stopped in the middle of a capture
    preview = LivePreview(on_frame=seen.frame)
    preview.start(session)
    await until(lambda: session.in_flight == 1)
    await preview.stop()
    assert not preview.running
    assert preview_tasks() == []
    captures = session.captures
    await asyncio.sleep(0.1)
    assert session.captures == captures
    await preview.stop()  # twice is fine
    preview.start(session)  # and a stopped preview never starts again
    assert not preview.running


async def test_a_failing_callback_does_not_stop_the_loop(caplog):
    session = FakeBrowserSession()
    session.open_tab()
    session.show(SITE, b"\xff\xd8one")
    calls = []

    def on_frame(jpeg):
        calls.append(jpeg)
        if len(calls) == 1:
            raise RuntimeError("boom")

    preview = LivePreview(on_frame=on_frame)
    preview.start(session)
    try:
        await until(lambda: calls)
        session.picture = b"\xff\xd8two"
        await until(lambda: len(calls) == 2)
    finally:
        await preview.stop()


async def test_capture_page_asks_cdp_for_a_jpeg_of_the_viewport():
    session = FakeBrowserSession()
    session.open_tab()
    session.show(SITE, b"\xff\xd8jpeg")
    assert await capture_page(session) == b"\xff\xd8jpeg"
    assert session.params == [{"format": "jpeg", "quality": live_preview.JPEG_QUALITY, "optimizeForSpeed": True}]


@pytest.mark.parametrize("url", ["about:blank", "chrome://newtab/", "chrome-error://chromewebdata/", ""])
async def test_capture_page_skips_pages_that_are_not_the_site(url):
    session = FakeBrowserSession()
    session.open_tab()
    session.show(url, b"\xff\xd8blank")
    assert await capture_page(session) is None
    assert session.captures == 0


async def test_capture_page_without_a_browser_is_none():
    assert await capture_page(None) is None
    assert await capture_page(FakeBrowserSession()) is None  # not started: no tab
