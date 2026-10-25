"""The one local-browser configuration every browser-use caller shares.

    import runtime_env  # noqa: F401  (telemetry off before browser_use loads)
    from browser_env import agent_files_dir, browser_profile, cleanup_profile

    profile = browser_profile(viewport=...)
    try:
        agent = Agent(task=..., llm=llm.agent_llm(), browser_profile=profile,
                      file_system_path=agent_files_dir(profile))
        history = await agent.run(...)
    finally:
        cleanup_profile(profile)

What every profile gets:

* Local Chromium only. No cloud browser, no CDP URL.
* Headless unless ``BENCHMARK_HEADLESS`` is false (``0``/``false``/``no``/``off``).
* ``--use-mock-keychain`` and ``--password-store=basic``, so Chromium never asks
  the macOS keychain for anything (no system dialogs during a run).
* A fresh throwaway profile per call, in a new temp dir (``PROFILE_DIR_PREFIX``).
  browser-use deletes it when it kills the browser; ``cleanup_profile(profile)`` (call
  it in a ``finally``) and an exit hook remove any that remain. Downloads go inside it.
  (Left to itself, browser-use 0.13 makes a ``browser-use-user-data-dir-*`` and a
  ``browser-use-downloads-*`` dir per profile and never deletes either; the profile one
  is about 9 MB per run.) Pass ``file_system_path=agent_files_dir(profile)`` to Agent so
  its scratch files go away too. Nothing persists between runs. (One leak remains that
  this module cannot stop: importing browser_use builds a module-level default profile,
  which makes one empty ``browser-use-downloads-*`` dir per process.)
* browser-use's default extensions off (no uBlock / cookie-consent auto-clicker),
  so sites show their real popups and nothing is downloaded on first launch.

How Chromium is found (``chromium_path()``), first match wins:

1. ``BENCHMARK_CHROMIUM_PATH``: an explicit executable (any Chromium-based browser).
2. Playwright's Chromium for the installed ``playwright`` package, under
   ``PLAYWRIGHT_BROWSERS_PATH`` (default ``~/Library/Caches/ms-playwright`` on macOS,
   ``~/.cache/ms-playwright`` on Linux, ``%LOCALAPPDATA%\\ms-playwright`` on Windows).
   Install it with ``uv run playwright install chromium`` from ``server/``.
3. The newest other Playwright Chromium revision in that folder (browser-use talks
   CDP, so any recent revision works; the Playwright API itself needs step 2).

If none exists, ``browser_profile()`` raises ``ChromiumNotFoundError`` with the
install command, instead of letting browser-use fall back to a system Chrome
(which on macOS would be the user's own Google Chrome app).

Before a profile is handed out, the executable is started once with ``--version``
(``chromium_start_problem()``). A Chromium that is on disk but cannot run, typically
on Linux without its system libraries (``libnspr4.so``, ``libnss3.so``, ...), raises
``ChromiumNotFoundError`` naming the missing library and the fix
(``LINUX_DEPS_HINT``), instead of browser-use failing later with "process not found".
``chromium_problem()`` answers the same question for whatever Chromium would be used,
and ``python browser_env.py`` (the last step of ``make setup``) prints it.
"""

from __future__ import annotations

import atexit
import glob
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import runtime_env  # noqa: F401  (must run before browser_use is imported)

log = logging.getLogger(__name__)

KEYCHAIN_ARGS: tuple[str, ...] = ("--use-mock-keychain", "--password-store=basic")
DEFAULT_VIEWPORT: dict[str, int] = {"width": 1280, "height": 720}
INSTALL_HINT = "cd server && uv run playwright install chromium"
LINUX_DEPS_HINT = "cd server && uv run playwright install-deps chromium"
# How long `chromium --version` may take before the start check gives up on it.
START_CHECK_TIMEOUT_S = 15.0
# The temp profile dir name carries two browser-use markers on purpose:
# - "browseruse-tmp-": LocalBrowserWatchdog deletes such a dir when it kills the browser.
# - "browser-use-user-data-dir-": BrowserProfile then skips _copy_profile(), which would
#   otherwise copy the dir into another temp dir that nothing ever deletes.
PROFILE_DIR_PREFIX = "browseruse-tmp-agent-benchmark-browser-use-user-data-dir-"

AGENT_FILES_PREFIX = "agent-benchmark-agent-files-"

# profile dir -> extra dirs to delete with it (agent_files_dir)
_created_profile_dirs: dict[str, list[str]] = {}


def new_profile_dir() -> str:
    """A new empty temp dir for one browser profile, tracked for cleanup."""
    # Resolved, because BrowserProfile resolves it too (/var -> /private/var on macOS).
    path = str(Path(tempfile.mkdtemp(prefix=PROFILE_DIR_PREFIX)).resolve())
    _created_profile_dirs[path] = []
    return path


def agent_files_dir(profile: Any) -> str:
    """A temp dir for the Agent's own files (``Agent(file_system_path=...)``).

    Left unset, browser-use creates ``$TMPDIR/browser_use_agent_<id>_<ts>`` per Agent and
    never deletes it. This one is removed by ``cleanup_profile(profile)``.
    """
    path = str(Path(tempfile.mkdtemp(prefix=AGENT_FILES_PREFIX)).resolve())
    _created_profile_dirs.setdefault(str(getattr(profile, "user_data_dir", "") or ""), []).append(path)
    return path


def cleanup_profile(profile: Any) -> None:
    """Delete the temp dirs browser_profile()/agent_files_dir() made for ``profile``.

    Never touches a user_data_dir the caller supplied. Safe to call twice.
    """
    path = str(getattr(profile, "user_data_dir", "") or "")
    extras = _created_profile_dirs.pop(path, None)
    if extras is None:
        return
    for extra in extras:
        shutil.rmtree(extra, ignore_errors=True)
    if Path(path).name.startswith(PROFILE_DIR_PREFIX):  # only dirs new_profile_dir() made
        shutil.rmtree(path, ignore_errors=True)


@atexit.register
def cleanup_all_profiles() -> None:
    """Delete every temp dir this process created that still exists."""
    for path, extras in list(_created_profile_dirs.items()):
        for extra in extras:
            shutil.rmtree(extra, ignore_errors=True)
        if Path(path).name.startswith(PROFILE_DIR_PREFIX):
            shutil.rmtree(path, ignore_errors=True)
        _created_profile_dirs.pop(path, None)

_FALSE_WORDS = {"0", "false", "no", "off"}


class ChromiumNotFoundError(RuntimeError):
    """No local Chromium that can start: none is installed, or the one found fails to run."""


def headless() -> bool:
    """BENCHMARK_HEADLESS, default true."""
    value = os.getenv("BENCHMARK_HEADLESS", "").strip().lower()
    if not value:
        return True
    return value not in _FALSE_WORDS


def chromium_args(extra: list[str] | tuple[str, ...] | None = None) -> list[str]:
    """Launch args added on top of browser-use's defaults. Keychain args always included."""
    args = list(KEYCHAIN_ARGS)
    for arg in extra or ():
        if arg not in args:
            args.append(arg)
    return args


def playwright_browsers_path() -> Path:
    env = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if env and env != "0":
        return Path(env).expanduser()
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if system == "Windows":
        return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def _playwright_chromium_revision() -> str | None:
    """Chromium revision the installed playwright package expects, from its browsers.json."""
    try:
        import playwright
    except ImportError:
        return None
    browsers_json = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
    try:
        data = json.loads(browsers_json.read_text())
    except (OSError, ValueError):
        return None
    for browser in data.get("browsers", []):
        if browser.get("name") == "chromium":
            return str(browser.get("revision"))
    return None


def _executable_in(revision_dir: Path) -> str | None:
    """The Chromium binary inside one ms-playwright/chromium-<rev> folder, if complete."""
    if not (revision_dir / "INSTALLATION_COMPLETE").exists():
        return None
    system = platform.system()
    if system == "Darwin":
        # "Chromium.app" in older builds, "Google Chrome for Testing.app" in newer ones.
        patterns = ["chrome-mac*/*.app/Contents/MacOS/*"]
    elif system == "Windows":
        patterns = ["chrome-win*/chrome.exe"]
    else:
        patterns = ["chrome-linux*/chrome"]
    for pattern in patterns:
        for candidate in sorted(glob.glob(str(revision_dir / pattern))):
            path = Path(candidate)
            if system == "Darwin" and path.name != path.parents[2].name.removesuffix(".app"):
                continue  # only the app's main binary, never a helper
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
    return None


def chromium_path() -> str | None:
    """Path to the Chromium executable to launch, or None if none is installed."""
    explicit = os.getenv("BENCHMARK_CHROMIUM_PATH", "").strip()
    if explicit:
        return explicit

    root = playwright_browsers_path()
    wanted = _playwright_chromium_revision()
    if wanted:
        exe = _executable_in(root / f"chromium-{wanted}")
        if exe:
            return exe

    revisions = []
    for entry in glob.glob(str(root / "chromium-*")):
        match = re.fullmatch(r"chromium-(\d+)", Path(entry).name)
        if match:
            revisions.append((int(match.group(1)), Path(entry)))
    for _, revision_dir in sorted(revisions, reverse=True):
        exe = _executable_in(revision_dir)
        if exe:
            if wanted:
                log.info(
                    "Playwright chromium-%s is not installed; using %s for browser-use. "
                    "Run `%s` to get the matching build.", wanted, revision_dir.name, INSTALL_HINT,
                )
            return exe
    return None


def _not_found_message() -> str:
    return (
        f"No local Chromium found under {playwright_browsers_path()}. Install it with: {INSTALL_HINT} "
        "(or point BENCHMARK_CHROMIUM_PATH at a Chromium-based browser)."
    )


# executable -> its --version output, for every executable that has started once.
_started: dict[str, str] = {}

_MISSING_LIBRARY = re.compile(r"error while loading shared libraries: ([^:\s]+)")


def chromium_start_problem(executable: str) -> str | None:
    """Why ``executable`` cannot start, with the fix, or None when it can.

    Runs ``<executable> --version`` (with the keychain args, like every launch). A
    success is remembered for the life of the process; a failure is checked again next
    time, so installing the missing libraries needs no restart. Not run on Windows,
    where ``chrome.exe --version`` opens a browser window instead of printing.
    """
    if executable in _started:
        return None
    if platform.system() == "Windows":
        return None
    try:
        done = subprocess.run(
            [executable, "--version", *KEYCHAIN_ARGS],
            capture_output=True, text=True, errors="replace", timeout=START_CHECK_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        log.warning("`%s --version` took over %.0f s; not checking it further.", executable, START_CHECK_TIMEOUT_S)
        _started[executable] = ""
        return None
    except OSError as exc:
        return (
            f"Chromium cannot be run ({exc.strerror or exc}). Install it with: {INSTALL_HINT}, "
            f"or point BENCHMARK_CHROMIUM_PATH at a Chromium-based browser. Path: {executable}"
        )
    if done.returncode == 0:
        _started[executable] = (done.stdout or "").strip()
        return None

    output = f"{done.stderr or ''}\n{done.stdout or ''}"
    missing = _MISSING_LIBRARY.search(output)
    if missing:
        return (
            f"Chromium cannot start: the system library {missing.group(1)} is missing. "
            f"Install Chromium's libraries with: {LINUX_DEPS_HINT} "
            "(Debian or Ubuntu; it asks for sudo unless you are root), or with your package manager."
        )
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    detail = lines[0].replace(executable, Path(executable).name)[:150] if lines else "no output"
    fix = (
        f"It may need its system libraries: {LINUX_DEPS_HINT}"
        if platform.system() == "Linux"
        else f"Reinstall it with: {INSTALL_HINT}"
    )
    return f"Chromium cannot start (exit {done.returncode}: {detail}). {fix}"


def chromium_problem() -> str | None:
    """Why runs here have no Chromium that starts (with the fix), or None when they have one."""
    executable = chromium_path()
    if not executable:
        return _not_found_message()
    return chromium_start_problem(executable)


def browser_profile(
    *,
    viewport: dict[str, int] | None = None,
    headless: bool | None = None,
    extra_args: list[str] | None = None,
    **overrides: Any,
):
    """Return the browser-use BrowserProfile every caller should use.

    ``viewport`` defaults to 1280x720. ``headless`` defaults to BENCHMARK_HEADLESS.
    ``extra_args`` (or an ``args`` keyword) are appended after the keychain args,
    which are always kept. Any other BrowserProfile field can be overridden by
    keyword, except ``cdp_url`` (local browser only).
    """
    if overrides.get("cdp_url"):
        raise ValueError("browser_env.browser_profile() is for a local browser; cdp_url is not allowed")

    from browser_use.browser.profile import BrowserProfile

    executable = overrides.pop("executable_path", None) or chromium_path()
    if not executable:
        raise ChromiumNotFoundError(_not_found_message())
    problem = chromium_start_problem(str(executable))
    if problem:
        raise ChromiumNotFoundError(problem)

    use_headless = _headless_default() if headless is None else headless
    size = dict(viewport or DEFAULT_VIEWPORT)
    # An "args" override is merged, never allowed to drop the keychain args.
    merged_extra = list(extra_args or []) + list(overrides.pop("args", None) or [])
    settings: dict[str, Any] = {
        "executable_path": executable,
        "headless": use_headless,
        "args": chromium_args(merged_extra),
        "user_data_dir": None,  # replaced below unless overridden
        "keep_alive": False,
        "permissions": [],
        "viewport": size,
        "enable_default_extensions": False,
    }
    if not use_headless:
        settings["window_size"] = size
    settings.update(overrides)
    if settings["user_data_dir"] is None:
        settings["user_data_dir"] = new_profile_dir()
        # Downloads inside the profile dir, so one cleanup removes both (browser-use's
        # default is another browser-use-downloads-* temp dir that is never deleted).
        settings.setdefault("downloads_path", str(Path(settings["user_data_dir"]) / "downloads"))
    return BrowserProfile(**settings)


# Module-level alias so browser_profile(headless=...) can shadow the function name.
_headless_default = headless


def main() -> int:
    """``python browser_env.py``: say whether the Chromium runs would use can start (exit 1 if not)."""
    problem = chromium_problem()
    if problem:
        print(problem, file=sys.stderr)
        return 1
    executable = chromium_path()
    version = _started.get(str(executable)) or "version unknown"
    print(f"Chromium starts: {version} ({executable})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
