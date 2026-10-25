"""Tests for browser_env (profile construction only; no browser is launched)."""

import os
import stat
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


def make_exe(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


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


def test_browser_profile_defaults(monkeypatch):
    monkeypatch.setenv("BENCHMARK_CHROMIUM_PATH", "/opt/chromium/chrome")
    profile = browser_env.browser_profile()
    assert profile.headless is True
    assert str(profile.executable_path) == "/opt/chromium/chrome"
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


def test_each_profile_gets_its_own_dir_and_exit_cleanup(monkeypatch):
    monkeypatch.setenv("BENCHMARK_CHROMIUM_PATH", "/opt/chromium/chrome")
    a, b = browser_env.browser_profile(), browser_env.browser_profile()
    assert a.user_data_dir != b.user_data_dir
    browser_env.cleanup_all_profiles()
    assert not os.path.exists(a.user_data_dir) and not os.path.exists(b.user_data_dir)


def test_profile_leaves_no_temp_dirs_behind(private_tempdir, monkeypatch):
    # browser-use's BrowserProfile copies a profile dir into a fresh
    # browser-use-user-data-dir-* temp dir unless the name says it is one already, and
    # makes a browser-use-downloads-* dir; it deletes neither. Ours must avoid both.
    monkeypatch.setenv("BENCHMARK_CHROMIUM_PATH", "/opt/chromium/Google Chrome for Testing")
    profile = browser_env.browser_profile()
    profile_dir = str(profile.user_data_dir)
    assert [p.name for p in private_tempdir.iterdir()] == [os.path.basename(profile_dir)]
    assert str(profile.downloads_path).startswith(profile_dir)
    browser_env.cleanup_profile(profile)
    assert list(private_tempdir.iterdir()) == []


def test_agent_files_dir_is_removed_with_its_profile(private_tempdir, monkeypatch):
    monkeypatch.setenv("BENCHMARK_CHROMIUM_PATH", "/opt/chromium/chrome")
    profile = browser_env.browser_profile()
    files = browser_env.agent_files_dir(profile)
    assert os.path.isdir(files) and os.path.basename(files).startswith(browser_env.AGENT_FILES_PREFIX)
    browser_env.cleanup_profile(profile)
    assert list(private_tempdir.iterdir()) == []


def test_agent_dir_with_a_caller_profile_never_deletes_the_callers_dir(tmp_path, private_tempdir, monkeypatch):
    monkeypatch.setenv("BENCHMARK_CHROMIUM_PATH", "/opt/chromium/chrome")
    mine = private_tempdir / "callers-profile"  # even when it lives under the temp root
    mine.mkdir()
    profile = SimpleNamespace(user_data_dir=str(mine))
    files = browser_env.agent_files_dir(profile)
    browser_env.cleanup_profile(profile)
    assert mine.exists() and not os.path.exists(files)


def test_cleanup_never_touches_dirs_it_did_not_create(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCHMARK_CHROMIUM_PATH", "/opt/chromium/chrome")
    mine = tmp_path / "my-profile"
    mine.mkdir()
    profile = browser_env.browser_profile(user_data_dir=str(mine))
    browser_env.cleanup_profile(profile)
    assert mine.exists()


def test_browser_profile_overrides_keep_keychain_flags(monkeypatch):
    monkeypatch.setenv("BENCHMARK_CHROMIUM_PATH", "/opt/chromium/chrome")
    monkeypatch.setenv("BENCHMARK_HEADLESS", "false")
    profile = browser_env.browser_profile(
        viewport={"width": 390, "height": 844}, args=["--lang=en-US"], extra_args=["--mute-audio"],
    )
    assert profile.headless is False
    assert profile.args == ["--use-mock-keychain", "--password-store=basic", "--mute-audio", "--lang=en-US"]
    assert profile.window_size.width == 390
    browser_env.cleanup_profile(profile)


def test_browser_profile_refuses_remote_browsers(monkeypatch):
    monkeypatch.setenv("BENCHMARK_CHROMIUM_PATH", "/opt/chromium/chrome")
    with pytest.raises(ValueError, match="local browser"):
        browser_env.browser_profile(cdp_url="wss://connect.example.com")


def test_playwright_revision_is_read_from_the_package():
    revision = browser_env._playwright_chromium_revision()
    assert revision and revision.isdigit()
