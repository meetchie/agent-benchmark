"""Run a command line program's async main so that Ctrl-C never leaves a browser behind.

    sys.exit(entrypoint.run_cli(main()))

used by arena.py and cli/run.py in place of ``asyncio.run(main())``.

The first Ctrl-C (SIGINT) or SIGTERM cancels ``main``. The cancellation unwinds through
the agent, which closes its browser, and through each ``finally``, where
``browser_env.cleanup_profile`` stops any browser still left by PID and removes the
temp dirs. Then the program exits with status 130.

Signals that arrive within ``DUPLICATE_WINDOW_S`` of the first are ignored: under
``uv run`` one Ctrl-C reaches the program twice, once from the terminal and once as the
copy uv forwards, and Python's default handling would turn the second into a
KeyboardInterrupt in the middle of that cleanup. A later Ctrl-C means "quit now": the
browsers this process started are stopped by PID and the program exits at once.

An interrupted program ends with ``os._exit`` once its cleanup is done, after stopping
any browser left and flushing its output, with SIGINT and SIGTERM ignored from then on.
A normal interpreter exit would put the default signal handling back while it shuts
down, so the forwarded copy of the Ctrl-C, arriving late after a quick cleanup, could
still kill the process; and it would wait for any worker thread still blocked on a
network call.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from typing import Any, Coroutine

DUPLICATE_WINDOW_S = 1.0
INTERRUPTED = 130  # the shell's status for a program stopped by SIGINT
_SIGNALS = (signal.SIGINT, signal.SIGTERM)


def run_cli(main: Coroutine[Any, Any, int]) -> int:
    """Run ``main`` to completion and return its exit status; exit with 130 when interrupted."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    task = loop.create_task(main)
    first_signal: list[float] = []

    def on_signal(signum, frame) -> None:
        now = time.monotonic()
        if not first_signal:
            first_signal.append(now)
            print("\nStopping: closing the browser (Ctrl-C again to quit at once) ...", file=sys.stderr, flush=True)
            loop.call_soon_threadsafe(task.cancel)
            return
        if now - first_signal[0] < DUPLICATE_WINDOW_S:
            return  # the copy `uv run` forwards, or a double press
        print("\nQuitting now.", file=sys.stderr, flush=True)
        _exit_now(INTERRUPTED)

    # A plain signal handler rather than loop.add_signal_handler: it stays in place after
    # the loop is closed, so there is no moment in which a late duplicate is unhandled.
    previous = {}
    try:
        for signum in _SIGNALS:
            previous[signum] = signal.signal(signum, on_signal)
    except ValueError:  # not the main thread: run without special handling
        pass

    code = INTERRUPTED
    try:
        try:
            code = loop.run_until_complete(task)
        except asyncio.CancelledError:
            if not first_signal:
                raise
    finally:
        try:
            _cancel_leftovers(loop)
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            asyncio.set_event_loop(None)
            loop.close()
            if not first_signal:
                for signum, handler in previous.items():
                    signal.signal(signum, handler)
    if first_signal:
        print("Stopped.", file=sys.stderr, flush=True)
        _exit_now(code if isinstance(code, int) and code else INTERRUPTED)
    return code


def _cancel_leftovers(loop: asyncio.AbstractEventLoop) -> None:
    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
    for t in pending:
        t.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))


def _exit_now(code: int) -> None:
    """Stop this process's browsers by PID, remove their dirs, flush, and exit with ``code``."""
    for signum in _SIGNALS:
        try:
            signal.signal(signum, signal.SIG_IGN)
        except ValueError:
            pass
    try:
        import browser_env

        browser_env.cleanup_all_profiles()
    finally:
        logging.shutdown()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)
