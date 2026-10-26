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

Every profile is a local Chromium, headless unless BENCHMARK_HEADLESS is false, started with
``--use-mock-keychain --password-store=basic`` so it never asks the macOS keychain for anything. It
gets a fresh temp dir that ``cleanup_profile`` and an exit hook remove, along with the Agent's
scratch dirs and any browser still running on it. One leak stays: importing browser_use makes an
empty ``browser-use-downloads-*`` dir per process.

``chromium_path()`` looks for Chromium in this order:

1. ``BENCHMARK_CHROMIUM_PATH``, any Chromium-based executable.
2. Playwright's Chromium for the installed ``playwright`` package, under ``PLAYWRIGHT_BROWSERS_PATH``
   (``uv run playwright install chromium`` from ``server/``).
3. The newest other Playwright Chromium revision in that folder. That only suits browser-use, which
   talks CDP to any recent revision. The Playwright API itself needs step 2.

With none, ``browser_profile()`` raises ``ChromiumNotFoundError`` with the install command rather
than letting browser-use fall back to the user's own Chrome. It also runs the executable once with
``--version`` (``chromium_start_problem()``), so one that is on disk but can't start (on Linux,
missing system libraries) fails with the fix. ``python browser_env.py`` prints the same check.
"""

from __future__ import annotations

import atexit
import glob
import json
import logging
import math
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
# The live preview sizes the browser to the viewer's pane, but never below a desktop size or outside
# these shapes. A short or narrow window would make the agent scroll, and pay for, far more than the
# site needs.
MIN_VIEWPORT: dict[str, int] = {"width": 1024, "height": 720}
MAX_VIEWPORT: dict[str, int] = {"width": 1920, "height": 1200}
MIN_ASPECT = 4 / 3   # width / height: no taller than 4:3
MAX_ASPECT = 16 / 9  # no wider than 16:9
INSTALL_HINT = "cd server && uv run playwright install chromium"
LINUX_DEPS_HINT = "cd server && uv run playwright install-deps chromium"
START_CHECK_TIMEOUT_S = 15.0
# The name carries two browser-use markers on purpose.
# "browseruse-tmp-": LocalBrowserWatchdog deletes such a dir when it kills the browser.
# "browser-use-user-data-dir-": BrowserProfile then skips _copy_profile(), which would copy the dir
# somewhere nothing deletes.
PROFILE_DIR_PREFIX = "browseruse-tmp-agent-benchmark-browser-use-user-data-dir-"
# On Linux Chromium puts its single-instance socket at
# $TMPDIR/.org.chromium.Chromium.XXXXXX/SingletonSocket and aborts if that path exceeds a Unix
# socket address (107 bytes), so TMPDIR over 61 bytes stops every launch. The profile dir's length
# does not matter, and macOS does not use TMPDIR for this.
CHROMIUM_SOCKET_IN_TMPDIR = "/.org.chromium.Chromium.XXXXXX/SingletonSocket"
UNIX_SOCKET_PATH_MAX = 107
SHORT_TMPDIR = "/tmp"

AGENT_FILES_PREFIX = "agent-benchmark-agent-files-"
BROWSER_USE_AGENT_DIR_PREFIX = "browser_use_agent_"
BROWSER_STOP_TIMEOUT_S = 3.0

# profile dir -> extra dirs to delete with it
_created_profile_dirs: dict[str, list[str]] = {}


def new_profile_dir() -> str:
    """A new empty temp dir for one browser profile, tracked for cleanup."""
    # Resolved, because BrowserProfile resolves it too (/var -> /private/var on macOS).
    path = str(Path(tempfile.mkdtemp(prefix=PROFILE_DIR_PREFIX)).resolve())
    _created_profile_dirs[path] = []
    return path


def agent_files_dir(profile: Any) -> str:
    """A temp dir for the Agent's own files (``Agent(file_system_path=...)``).

    Left unset, browser-use makes one per Agent and never deletes it. ``cleanup_profile`` removes
    this one.
    """
    path = str(Path(tempfile.mkdtemp(prefix=AGENT_FILES_PREFIX)).resolve())
    _created_profile_dirs.setdefault(str(getattr(profile, "user_data_dir", "") or ""), []).append(path)
    return path


def track_agent_dir(profile: Any, agent: Any) -> None:
    """Remove the browser-use Agent's own temp dir together with ``profile``.

    browser-use 0.13 writes every step's screenshot to ``$TMPDIR/browser_use_agent_<id>_<ts>`` even
    when ``file_system_path`` points elsewhere, so screenshots of every site visited would pile up.
    Only a dir with that name, directly in the temp dir, is taken.
    """
    path = getattr(agent, "agent_directory", None)
    if not path:
        return
    path = Path(path)
    if not path.name.startswith(BROWSER_USE_AGENT_DIR_PREFIX):
        return
    if path.parent.resolve() != Path(tempfile.gettempdir()).resolve():
        return
    _created_profile_dirs.setdefault(str(getattr(profile, "user_data_dir", "") or ""), []).append(str(path))


def _launched_with(proc: Any, user_data_dir: str) -> bool:
    try:
        args = proc.cmdline()
    except Exception:
        return False
    for arg in args:
        if arg.startswith("--user-data-dir="):
            return os.path.realpath(arg.split("=", 1)[1]) == os.path.realpath(user_data_dir)
    return False


def browser_processes(user_data_dir: str) -> list:
    """The browser and its helpers this process started on ``user_data_dir``, as psutil.Process
    objects.

    Only descendants of this process whose command line names this exact profile dir count, so
    another program's browser is never picked. Empty without psutil.
    """
    if not user_data_dir:
        return []
    try:
        import psutil
    except ImportError:  # browser-use depends on psutil; without it there is nothing to stop
        return []
    try:
        descendants = psutil.Process().children(recursive=True)
    except psutil.Error:
        return []
    found: dict[int, Any] = {}
    for proc in descendants:
        if proc.pid in found or not _launched_with(proc, user_data_dir):
            continue
        found[proc.pid] = proc
        try:
            for helper in proc.children(recursive=True):
                found.setdefault(helper.pid, helper)
        except psutil.Error:
            pass
    return list(found.values())


def stop_browser(user_data_dir: str, timeout: float = BROWSER_STOP_TIMEOUT_S) -> list[int]:
    """Stop any browser this process still runs on ``user_data_dir``; returns the PIDs stopped.

    SIGTERM first, SIGKILL for what is still alive after ``timeout`` seconds. Blocks for at most
    about ``timeout`` + 1 s, so call it off the event loop.
    """
    procs = browser_processes(user_data_dir)
    if not procs:
        return []
    import psutil

    pids = sorted(p.pid for p in procs)
    log.warning("Stopping the browser still running on %s (pids %s)", user_data_dir, pids)
    for proc in procs:
        try:
            proc.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(procs, timeout=timeout)
    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(alive, timeout=1.0)
    return pids


def cleanup_profile(profile: Any) -> None:
    """Stop the profile's browser if it still runs, then delete the temp dirs made for it.

    Never touches a user_data_dir the caller supplied. Safe to call twice.
    """
    path = str(getattr(profile, "user_data_dir", "") or "")
    extras = _created_profile_dirs.pop(path, None)
    if extras is None:
        return
    _remove(path, extras)


def _remove(path: str, extras: list[str]) -> None:
    stop_browser(path)  # a running browser keeps writing to the profile dir
    for extra in extras:
        shutil.rmtree(extra, ignore_errors=True)
    if Path(path).name.startswith(PROFILE_DIR_PREFIX):  # only dirs new_profile_dir() made
        shutil.rmtree(path, ignore_errors=True)


@atexit.register
def cleanup_all_profiles() -> None:
    """Stop every browser this process started and delete every temp dir it created. Runs at exit; a
    server also calls it on shutdown in case the process never reaches the exit hooks.
    """
    for path in list(_created_profile_dirs):
        extras = _created_profile_dirs.pop(path, None)
        if extras is not None:
            _remove(path, extras)

_FALSE_WORDS = {"0", "false", "no", "off"}


class ChromiumNotFoundError(RuntimeError):
    """No local Chromium that can start: none is installed, or the one found fails to run."""


def headless() -> bool:
    """BENCHMARK_HEADLESS, default true."""
    value = os.getenv("BENCHMARK_HEADLESS", "").strip().lower()
    if not value:
        return True
    return value not in _FALSE_WORDS


def fit_viewport(requested: dict[str, Any] | None) -> dict[str, int]:
    """The viewport for a live run asked for ``requested`` (the viewer's preview pane).

    The shape is held between 4:3 and 16:9 by changing the height, then the size is scaled, shape
    kept, into MIN_VIEWPORT..MAX_VIEWPORT. A 1339x460 pane gives 1339x753, a 3840x2160 screen
    1920x1080, a phone's 358x380 1024x768. Nothing usable gives 1280x720.
    """
    def number(key: str) -> float | None:
        value = (requested or {}).get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return None
        return float(value)

    width, height = number("width"), number("height")
    if not width or not height or width <= 0 or height <= 0:
        return dict(DEFAULT_VIEWPORT)
    aspect = min(max(width / height, MIN_ASPECT), MAX_ASPECT)
    height = width / aspect
    grow = max(MIN_VIEWPORT["width"] / width, MIN_VIEWPORT["height"] / height, 1.0)
    width, height = width * grow, height * grow
    shrink = min(MAX_VIEWPORT["width"] / width, MAX_VIEWPORT["height"] / height, 1.0)
    width, height = width * shrink, height * shrink

    def held(value: float, key: str) -> int:
        return min(max(round(value), MIN_VIEWPORT[key]), MAX_VIEWPORT[key])

    return {"width": held(width, "width"), "height": held(height, "height")}


def chromium_args(extra: list[str] | tuple[str, ...] | None = None) -> list[str]:
    """Launch args added on top of browser-use's defaults. Keychain args always included."""
    args = list(KEYCHAIN_ARGS)
    for arg in extra or ():
        if arg not in args:
            args.append(arg)
    return args


def fit_tmpdir_for_chromium() -> bool:
    """On Linux, make TMPDIR short enough for the Chromium this process starts; True if changed.

    When TMPDIR leaves no room for Chromium's socket path (``CHROMIUM_SOCKET_IN_TMPDIR``), this
    process keeps its own temp files where TMPDIR says and the processes it starts from now on get
    TMPDIR=/tmp. browser-use gives Chromium this process's environment and no way to pass another.
    Does nothing elsewhere, or when /tmp is not writable.
    """
    if platform.system() != "Linux":
        return False
    current = os.environ.get("TMPDIR", "").rstrip("/")
    if len(os.fsencode(current)) + len(CHROMIUM_SOCKET_IN_TMPDIR) <= UNIX_SOCKET_PATH_MAX:
        return False
    if not os.access(SHORT_TMPDIR, os.W_OK | os.X_OK):
        log.warning("TMPDIR is too long for Chromium to start (%d characters) and %s cannot be written to; "
                    "set TMPDIR to a shorter path.", len(current), SHORT_TMPDIR)
        return False
    tempfile.gettempdir()  # settles this process's own temp dir before TMPDIR changes
    os.environ["TMPDIR"] = SHORT_TMPDIR
    log.info("TMPDIR is %d characters, too long for Chromium on Linux; browsers start with TMPDIR=%s.",
             len(current), SHORT_TMPDIR)
    return True


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

    Runs ``<executable> --version`` with the keychain args. A success is remembered for the process,
    a failure is checked again next time so installing the libraries needs no restart. Skipped on
    Windows, where ``chrome.exe --version`` opens a window.
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
    """The browser-use BrowserProfile every caller should use.

    ``viewport`` defaults to 1280x720, ``headless`` to BENCHMARK_HEADLESS. ``extra_args`` (or an
    ``args`` keyword) go after the keychain args, which are always kept. Any other BrowserProfile
    field can be overridden by keyword except ``cdp_url``.
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
    fit_tmpdir_for_chromium()

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
        # No uBlock or cookie auto-clicker: the agent must face the site's real popups, and nothing
        # downloads on first launch.
        "enable_default_extensions": False,
    }
    if not use_headless:
        settings["window_size"] = size
    settings.update(overrides)
    if settings["user_data_dir"] is None:
        settings["user_data_dir"] = new_profile_dir()
        # Downloads go inside the profile dir so one cleanup removes both. browser-use's default is
        # a separate temp dir that is never deleted.
        settings.setdefault("downloads_path", str(Path(settings["user_data_dir"]) / "downloads"))
    return BrowserProfile(**settings)


# So browser_profile(headless=...) can shadow the function name.
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
