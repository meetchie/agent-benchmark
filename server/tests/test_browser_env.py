"""Tests for browser_env. No browser is launched: small shell scripts stand in for Chromium in
the start check, and stand-in processes play a browser that is still running."""

import os
import signal
import stat
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

import browser_env


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("BENCHMARK_HEADLESS", "BENCHMARK_CHROMIUM_PATH"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def private_tempdir(tmp_path, monkeypatch):
    """Every temp dir made here (ours and browser-use's) lands in a private folder."""
    sys_tmp = tmp_path / "sys-tmp"
    sys_tmp.mkdir()
    monkeypatch.setattr(browser_env.tempfile, "tempdir", str(sys_tmp))
    return sys_tmp


@pytest.fixture(autouse=True)
def fresh_start_check(monkeypatch):
    """No executable counts as started before the test starts it."""
    monkeypatch.setattr(browser_env, "_started", {})


def make_exe(path, body=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


# What the dynamic loader prints when Chromium runs on a Linux without its libraries.
LIBS_MISSING = "error while loading shared libraries: libnspr4.so: cannot open shared object file: No such file or directory"


def failing_exe(path, message=LIBS_MISSING, code=127):
    return make_exe(path, f'echo "$0: {message}" >&2\nexit {code}\n')


@pytest.fixture
def fake_chrome(tmp_path, monkeypatch):
    """BENCHMARK_CHROMIUM_PATH pointing at an executable that starts."""
    exe = make_exe(tmp_path / "opt" / "chromium" / "chrome", 'echo "Chromium 1.0"\n')
    monkeypatch.setenv("BENCHMARK_CHROMIUM_PATH", str(exe))
    return str(exe)


def make_revision(root, revision, system, app="Google Chrome for Testing", complete=True):
    rev_dir = root / f"chromium-{revision}"
    if system == "Darwin":
        exe = make_exe(rev_dir / "chrome-mac-arm64" / f"{app}.app" / "Contents" / "MacOS" / app)
        make_exe(rev_dir / "chrome-mac-arm64" / f"{app}.app" / "Contents" / "MacOS" / "helper-not-me")
    else:
        exe = make_exe(rev_dir / "chrome-linux64" / "chrome")
    if complete:
        (rev_dir / "INSTALLATION_COMPLETE").write_text("")
    return str(exe)


@pytest.fixture
def fake_cache(tmp_path, monkeypatch):
    """Point PLAYWRIGHT_BROWSERS_PATH at an empty dir and pin the expected revision."""
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    monkeypatch.setattr(browser_env, "_playwright_chromium_revision", lambda: "1248")
    return tmp_path


@pytest.mark.parametrize("value, expected", [
    (None, True), ("", True), ("true", True), ("1", True), ("yes", True),
    ("false", False), ("0", False), ("No", False), ("off", False),
])
def test_headless_env(monkeypatch, value, expected):
    if value is not None:
        monkeypatch.setenv("BENCHMARK_HEADLESS", value)
    assert browser_env.headless() is expected


def test_chromium_args_always_carry_keychain_flags():
    assert browser_env.chromium_args() == ["--use-mock-keychain", "--password-store=basic"]
    assert browser_env.chromium_args(["--lang=en-US", "--use-mock-keychain"]) == [
        "--use-mock-keychain", "--password-store=basic", "--lang=en-US",
    ]


@pytest.mark.parametrize("length, changed", [(61, False), (62, True), (120, True)])
def test_on_linux_a_tmpdir_too_long_for_chromiums_socket_becomes_tmp(monkeypatch, length, changed):
    # Chromium's socket goes to $TMPDIR/.org.chromium.Chromium.XXXXXX/SingletonSocket, at most 107 bytes.
    monkeypatch.setattr(browser_env.platform, "system", lambda: "Linux")
    long_dir = "/" + "t" * (length - 1)
    monkeypatch.setenv("TMPDIR", long_dir + "/")  # a trailing slash adds nothing to the socket path
    assert browser_env.fit_tmpdir_for_chromium() is changed
    assert os.environ["TMPDIR"] == ("/tmp" if changed else long_dir + "/")


def test_the_process_keeps_its_own_temp_dir_when_browsers_get_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_env.platform, "system", lambda: "Linux")
    long_dir = tmp_path / ("t" * max(1, 100 - len(str(tmp_path))))
    long_dir.mkdir()
    monkeypatch.setenv("TMPDIR", str(long_dir))
    monkeypatch.setattr(browser_env.tempfile, "tempdir", None)  # not settled yet
    assert browser_env.fit_tmpdir_for_chromium() is True
    assert os.environ["TMPDIR"] == "/tmp"
    assert browser_env.tempfile.gettempdir() == str(long_dir)


def test_tmpdir_is_left_alone_off_linux_or_when_tmp_cannot_be_written(tmp_path, monkeypatch):
    long_dir = "/" + "t" * 120
    monkeypatch.setenv("TMPDIR", long_dir)
    monkeypatch.setattr(browser_env.platform, "system", lambda: "Darwin")
    assert browser_env.fit_tmpdir_for_chromium() is False
    monkeypatch.setattr(browser_env.platform, "system", lambda: "Linux")
    monkeypatch.setattr(browser_env, "SHORT_TMPDIR", str(tmp_path / "missing"))
    assert browser_env.fit_tmpdir_for_chromium() is False
    assert os.environ["TMPDIR"] == long_dir


def test_browser_profile_gives_the_browser_a_tmpdir_it_can_start_with(fake_chrome, monkeypatch):
    monkeypatch.setattr(browser_env.platform, "system", lambda: "Linux")
    monkeypatch.setenv("TMPDIR", "/" + "t" * 120)
    profile = browser_env.browser_profile()
    assert os.environ["TMPDIR"] == "/tmp"
    browser_env.cleanup_profile(profile)


@pytest.mark.parametrize("system", ["Darwin", "Linux"])
def test_prefers_the_revision_playwright_expects(fake_cache, monkeypatch, system):
    monkeypatch.setattr(browser_env.platform, "system", lambda: system)
    make_revision(fake_cache, 1300, system)  # newer, but not what playwright wants
    wanted = make_revision(fake_cache, 1248, system)
    assert browser_env.chromium_path() == wanted


def test_falls_back_to_newest_complete_revision(fake_cache, monkeypatch):
    monkeypatch.setattr(browser_env.platform, "system", lambda: "Darwin")
    make_revision(fake_cache, 1200, "Darwin", app="Chromium")  # older layout name
    newest = make_revision(fake_cache, 1234, "Darwin")
    make_revision(fake_cache, 1240, "Darwin", complete=False)  # half-installed: skipped
    assert browser_env.chromium_path() == newest


def test_explicit_path_wins(fake_cache, monkeypatch):
    make_revision(fake_cache, 1248, "Linux")
    monkeypatch.setenv("BENCHMARK_CHROMIUM_PATH", "/opt/chromium/chrome")
    assert browser_env.chromium_path() == "/opt/chromium/chrome"


def test_no_chromium_raises_with_install_hint(fake_cache):
    assert browser_env.chromium_path() is None
    with pytest.raises(browser_env.ChromiumNotFoundError, match="playwright install chromium"):
        browser_env.browser_profile()


def test_browser_profile_defaults(fake_chrome):
    profile = browser_env.browser_profile()
    assert profile.headless is True
    assert str(profile.executable_path) == fake_chrome
    assert "--use-mock-keychain" in profile.args and "--password-store=basic" in profile.args
    assert profile.cdp_url is None and profile.use_cloud is False
    assert profile.enable_default_extensions is False
    assert profile.keep_alive is False
    assert profile.viewport.width == 1280 and profile.viewport.height == 720
    # our own throwaway dir: browser-use deletes it on kill and does not copy it elsewhere
    profile_dir = str(profile.user_data_dir)
    assert os.path.basename(profile_dir).startswith(browser_env.PROFILE_DIR_PREFIX)
    assert os.path.isdir(profile_dir)
    assert "--use-mock-keychain" in profile.get_args() and "--headless=new" in profile.get_args()
    browser_env.cleanup_profile(profile)
    assert not os.path.exists(profile_dir)
    browser_env.cleanup_profile(profile)  # idempotent


def test_each_profile_gets_its_own_dir_and_exit_cleanup(fake_chrome):
    a, b = browser_env.browser_profile(), browser_env.browser_profile()
    assert a.user_data_dir != b.user_data_dir
    browser_env.cleanup_all_profiles()
    assert not os.path.exists(a.user_data_dir) and not os.path.exists(b.user_data_dir)


def test_profile_leaves_no_temp_dirs_behind(tmp_path, private_tempdir, monkeypatch):
    # browser-use's BrowserProfile copies a profile dir into a fresh
    # browser-use-user-data-dir-* temp dir unless the name says it is one already, and
    # makes a browser-use-downloads-* dir; it deletes neither. Ours must avoid both.
    exe = make_exe(tmp_path / "opt" / "chromium" / "Google Chrome for Testing")
    monkeypatch.setenv("BENCHMARK_CHROMIUM_PATH", str(exe))
    profile = browser_env.browser_profile()
    profile_dir = str(profile.user_data_dir)
    assert [p.name for p in private_tempdir.iterdir()] == [os.path.basename(profile_dir)]
    assert str(profile.downloads_path).startswith(profile_dir)
    browser_env.cleanup_profile(profile)
    assert list(private_tempdir.iterdir()) == []


def test_agent_files_dir_is_removed_with_its_profile(private_tempdir, fake_chrome):
    profile = browser_env.browser_profile()
    files = browser_env.agent_files_dir(profile)
    assert os.path.isdir(files) and os.path.basename(files).startswith(browser_env.AGENT_FILES_PREFIX)
    browser_env.cleanup_profile(profile)
    assert list(private_tempdir.iterdir()) == []


def test_agent_dir_with_a_caller_profile_never_deletes_the_callers_dir(tmp_path, private_tempdir, fake_chrome):
    mine = private_tempdir / "callers-profile"  # even when it lives under the temp root
    mine.mkdir()
    profile = SimpleNamespace(user_data_dir=str(mine))
    files = browser_env.agent_files_dir(profile)
    browser_env.cleanup_profile(profile)
    assert mine.exists() and not os.path.exists(files)


def test_cleanup_never_touches_dirs_it_did_not_create(tmp_path, fake_chrome):
    mine = tmp_path / "my-profile"
    mine.mkdir()
    profile = browser_env.browser_profile(user_data_dir=str(mine))
    browser_env.cleanup_profile(profile)
    assert mine.exists()


def test_browser_profile_overrides_keep_keychain_flags(fake_chrome, monkeypatch):
    monkeypatch.setenv("BENCHMARK_HEADLESS", "false")
    profile = browser_env.browser_profile(
        viewport={"width": 390, "height": 844}, args=["--lang=en-US"], extra_args=["--mute-audio"],
    )
    assert profile.headless is False
    assert profile.args == ["--use-mock-keychain", "--password-store=basic", "--mute-audio", "--lang=en-US"]
    assert profile.window_size.width == 390
    browser_env.cleanup_profile(profile)


def test_browser_profile_refuses_remote_browsers(fake_chrome):
    with pytest.raises(ValueError, match="local browser"):
        browser_env.browser_profile(cdp_url="wss://connect.example.com")


def test_playwright_revision_is_read_from_the_package():
    revision = browser_env._playwright_chromium_revision()
    assert revision and revision.isdigit()


# -- the start check -------------------------------------------------------------------


def test_a_chromium_without_its_libraries_names_the_library_and_the_fix(tmp_path, monkeypatch):
    # Linux without libnspr4 and friends: the file is there, it just cannot run.
    exe = failing_exe(tmp_path / "chrome-linux" / "chrome")
    monkeypatch.setenv("BENCHMARK_CHROMIUM_PATH", str(exe))
    with pytest.raises(browser_env.ChromiumNotFoundError) as excinfo:
        browser_env.browser_profile()
    message = str(excinfo.value)
    assert "cannot start" in message and "libnspr4.so" in message
    assert "uv run playwright install-deps chromium" in message
    assert str(tmp_path) not in message
    assert len(message) <= 300  # a run's error message keeps the first 300 characters
    assert browser_env._created_profile_dirs == {}  # no profile dir for a browser that cannot start


def test_a_chromium_that_fails_another_way_quotes_its_first_line(tmp_path, monkeypatch):
    exe = failing_exe(tmp_path / "chrome", message="Trace/breakpoint trap", code=133)
    monkeypatch.setattr(browser_env.platform, "system", lambda: "Darwin")
    problem = browser_env.chromium_start_problem(str(exe))
    assert problem.startswith("Chromium cannot start (exit 133: chrome: Trace/breakpoint trap)")
    assert "playwright install chromium" in problem
    monkeypatch.setattr(browser_env.platform, "system", lambda: "Linux")
    assert "playwright install-deps chromium" in browser_env.chromium_start_problem(str(exe))


def test_a_chromium_path_that_does_not_exist_cannot_be_run(monkeypatch, tmp_path):
    monkeypatch.setenv("BENCHMARK_CHROMIUM_PATH", str(tmp_path / "no-such-chrome"))
    with pytest.raises(browser_env.ChromiumNotFoundError, match="cannot be run.*BENCHMARK_CHROMIUM_PATH"):
        browser_env.browser_profile()


def test_the_start_check_runs_version_with_the_keychain_flags(tmp_path):
    argv = tmp_path / "argv"
    exe = make_exe(tmp_path / "chrome", f'echo "$@" >> "{argv}"\necho "Chromium 1.0"\n')
    assert browser_env.chromium_start_problem(str(exe)) is None
    assert argv.read_text().split() == ["--version", "--use-mock-keychain", "--password-store=basic"]


def test_a_chromium_that_started_is_not_started_again(tmp_path):
    argv = tmp_path / "argv"
    exe = make_exe(tmp_path / "chrome", f'echo "$@" >> "{argv}"\n')
    assert browser_env.chromium_start_problem(str(exe)) is None
    assert browser_env.chromium_start_problem(str(exe)) is None
    assert len(argv.read_text().splitlines()) == 1


def test_a_failed_start_is_checked_again_so_installing_the_libraries_needs_no_restart(tmp_path):
    exe = failing_exe(tmp_path / "chrome")
    assert "libnspr4.so" in browser_env.chromium_start_problem(str(exe))
    make_exe(exe, 'echo "Chromium 1.0"\n')
    assert browser_env.chromium_start_problem(str(exe)) is None


def test_a_hanging_start_check_gives_up_without_blocking_runs(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(browser_env, "START_CHECK_TIMEOUT_S", 0.3)
    exe = make_exe(tmp_path / "chrome", "exec sleep 5\n")
    with caplog.at_level("WARNING"):
        assert browser_env.chromium_start_problem(str(exe)) is None
    assert "took over" in caplog.text
    monkeypatch.setattr(browser_env, "START_CHECK_TIMEOUT_S", 60)
    assert browser_env.chromium_start_problem(str(exe)) is None  # at once: it does not wait again


def test_windows_is_not_start_checked(monkeypatch):
    # chrome.exe --version opens a window there instead of printing a version.
    monkeypatch.setattr(browser_env.platform, "system", lambda: "Windows")
    assert browser_env.chromium_start_problem(r"C:\no\such\chrome.exe") is None


def test_chromium_problem_covers_missing_broken_and_working(fake_cache, monkeypatch, tmp_path):
    assert "playwright install chromium" in browser_env.chromium_problem()
    broken = failing_exe(tmp_path / "broken" / "chrome")
    monkeypatch.setenv("BENCHMARK_CHROMIUM_PATH", str(broken))
    assert "install-deps" in browser_env.chromium_problem()
    working = make_exe(tmp_path / "working" / "chrome", 'echo "Chromium 1.0"\n')
    monkeypatch.setenv("BENCHMARK_CHROMIUM_PATH", str(working))
    assert browser_env.chromium_problem() is None


def test_the_check_command_prints_the_version_or_the_problem(fake_chrome, monkeypatch, tmp_path, capsys):
    assert browser_env.main() == 0
    assert capsys.readouterr().out.strip() == f"Chromium starts: Chromium 1.0 ({fake_chrome})"
    monkeypatch.setenv("BENCHMARK_CHROMIUM_PATH", str(failing_exe(tmp_path / "broken" / "chrome")))
    assert browser_env.main() == 1
    assert "install-deps" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The Agent's own dir (where browser-use writes its step screenshots)
# ---------------------------------------------------------------------------


def test_the_agents_own_dir_is_removed_with_its_profile(fake_chrome, private_tempdir):
    profile = browser_env.browser_profile()
    agent_dir = private_tempdir / "browser_use_agent_0123_1700000000"
    (agent_dir / "screenshots").mkdir(parents=True)
    (agent_dir / "screenshots" / "step_1.png").write_bytes(b"png")
    browser_env.track_agent_dir(profile, SimpleNamespace(agent_directory=agent_dir))
    browser_env.cleanup_profile(profile)
    assert list(private_tempdir.iterdir()) == []


def test_the_agents_own_dir_goes_at_exit_too(fake_chrome, private_tempdir):
    profile = browser_env.browser_profile()
    agent_dir = private_tempdir / "browser_use_agent_4567_1700000000"
    agent_dir.mkdir()
    browser_env.track_agent_dir(profile, SimpleNamespace(agent_directory=str(agent_dir)))
    browser_env.cleanup_all_profiles()
    assert list(private_tempdir.iterdir()) == []


@pytest.mark.parametrize("where", ["elsewhere", "wrong-name"])
def test_track_agent_dir_only_takes_browser_uses_own_temp_dirs(fake_chrome, where, tmp_path, private_tempdir):
    profile = browser_env.browser_profile()
    if where == "elsewhere":
        target = tmp_path / "browser_use_agent_0_0"  # right name, not in the temp dir
    else:
        target = private_tempdir / "my-project"
    target.mkdir()
    browser_env.track_agent_dir(profile, SimpleNamespace(agent_directory=target))
    browser_env.track_agent_dir(profile, SimpleNamespace())  # no agent_directory at all
    browser_env.cleanup_profile(profile)
    assert target.exists()


# ---------------------------------------------------------------------------
# No browser outlives its run (stand-in processes, no real browser)
# ---------------------------------------------------------------------------

# A stand-in "browser": started with --user-data-dir like Chromium, it starts a helper
# child (like Chromium's renderer) and can be told to ignore SIGTERM.
FAKE_BROWSER = r"""
import signal, subprocess, sys, time
if "--ignore-term" in sys.argv:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
helper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "--type=renderer"])
print(helper.pid, flush=True)
time.sleep(60)
"""


def start_fake_browser(user_data_dir, *extra):
    proc = subprocess.Popen(
        [sys.executable, "-c", FAKE_BROWSER, f"--user-data-dir={user_data_dir}", *extra],
        stdout=subprocess.PIPE, text=True,
    )
    helper_pid = int(proc.stdout.readline())
    return proc, helper_pid


def gone(pid, timeout=5.0):
    import psutil

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def fake_browsers():
    """Started stand-ins; any still alive at the end are killed by PID."""
    started = []
    yield started
    for proc, helper_pid in started:
        for pid in (proc.pid, helper_pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        proc.wait(timeout=5)


def test_cleanup_profile_stops_a_browser_still_running_on_it(fake_chrome, fake_browsers):
    profile = browser_env.browser_profile()
    other = browser_env.browser_profile()
    fake_browsers.append(start_fake_browser(profile.user_data_dir))
    fake_browsers.append(start_fake_browser(other.user_data_dir))
    (browser, helper), (bystander, bystander_helper) = fake_browsers

    found = sorted(p.pid for p in browser_env.browser_processes(str(profile.user_data_dir)))
    assert found == sorted([browser.pid, helper])

    browser_env.cleanup_profile(profile)

    assert gone(browser.pid) and gone(helper)
    assert not os.path.exists(profile.user_data_dir)
    # A browser on another profile is not touched.
    assert bystander.poll() is None and not gone(bystander_helper, timeout=0.2)
    browser_env.cleanup_profile(other)
    assert gone(bystander.pid) and gone(bystander_helper)


def test_a_browser_that_ignores_sigterm_is_killed(fake_chrome, monkeypatch, fake_browsers):
    monkeypatch.setattr(browser_env, "BROWSER_STOP_TIMEOUT_S", 0.5)
    profile = browser_env.browser_profile()
    fake_browsers.append(start_fake_browser(profile.user_data_dir, "--ignore-term"))
    (browser, helper), = fake_browsers
    time.sleep(0.3)  # let it install the handler

    started = time.monotonic()
    stopped = browser_env.stop_browser(str(profile.user_data_dir), timeout=0.5)

    assert sorted(stopped) == sorted([browser.pid, helper])
    assert gone(browser.pid) and gone(helper)
    assert time.monotonic() - started < 3


def test_the_exit_hook_stops_every_browser_still_running(fake_chrome, fake_browsers):
    a, b = browser_env.browser_profile(), browser_env.browser_profile()
    fake_browsers.append(start_fake_browser(a.user_data_dir))
    fake_browsers.append(start_fake_browser(b.user_data_dir))
    browser_env.cleanup_all_profiles()
    for proc, helper in fake_browsers:
        assert gone(proc.pid) and gone(helper)
    assert not os.path.exists(a.user_data_dir) and not os.path.exists(b.user_data_dir)


def test_stop_browser_with_nothing_running_returns_at_once(tmp_path):
    started = time.monotonic()
    assert browser_env.stop_browser(str(tmp_path)) == []
    assert browser_env.stop_browser("") == []
    assert time.monotonic() - started < 1


@pytest.mark.parametrize("asked, given", [
    ({"width": 1339, "height": 460}, {"width": 1339, "height": 753}),   # a wide, short preview pane
    ({"width": 1280, "height": 720}, {"width": 1280, "height": 720}),   # a usable size is kept
    ({"width": 1440, "height": 900}, {"width": 1440, "height": 900}),
    ({"width": 358, "height": 380}, {"width": 1024, "height": 768}),    # a phone: 4:3, scaled up
    ({"width": 1024, "height": 1400}, {"width": 1024, "height": 768}),  # tall: held to 4:3
    ({"width": 3840, "height": 2160}, {"width": 1920, "height": 1080}), # huge: scaled down, shape kept
    ({"width": 800, "height": 450}, {"width": 1280, "height": 720}),    # small: scaled up, shape kept
    ({"width": 1600, "height": 1600}, {"width": 1600, "height": 1200}),
    ({"width": 1920, "height": 400}, {"width": 1920, "height": 1080}),
    ({"width": 2400, "height": 1200}, {"width": 1920, "height": 1080}),
])
def test_fit_viewport_gives_a_desktop_size_between_4_3_and_16_9(asked, given):
    fitted = browser_env.fit_viewport(asked)
    assert fitted == given
    assert 1024 <= fitted["width"] <= 1920 and 720 <= fitted["height"] <= 1200
    assert 4 / 3 - 0.01 <= fitted["width"] / fitted["height"] <= 16 / 9 + 0.01


@pytest.mark.parametrize("asked", [
    None, {}, {"width": 0, "height": 700}, {"width": -5, "height": -5}, {"width": "wide", "height": 700},
    {"width": float("inf"), "height": 700}, {"width": float("nan"), "height": 700}, {"width": True, "height": 700},
    {"width": 1300},
])
def test_fit_viewport_without_a_usable_size_gives_the_default(asked):
    assert browser_env.fit_viewport(asked) == {"width": 1280, "height": 720}
