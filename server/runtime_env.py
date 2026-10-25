"""Process environment defaults that must be in place before browser_use is imported.

Import this module before anything that imports browser_use:

    import runtime_env  # noqa: F401  (keep above any browser_use import)

On import it

1. loads ``server/.env`` and then the repo-root ``.env`` (variables already set in
   the environment always win, so a shell export overrides a file), and
2. turns browser-use's anonymous telemetry and cloud sync off unless the user set
   them explicitly.

browser-use reads ``ANONYMIZED_TELEMETRY`` and ``BROWSER_USE_CLOUD_SYNC`` lazily, so
setting them here, before the first Agent or BrowserSession is created, is enough.
Importing this module twice is harmless.
"""

from __future__ import annotations

import os
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
REPO_DIR = SERVER_DIR.parent

# Off by construction. A user who wants either one on can export it as "true".
TELEMETRY_DEFAULTS: dict[str, str] = {
    "ANONYMIZED_TELEMETRY": "false",
    "BROWSER_USE_CLOUD_SYNC": "false",
}


def load_env_files() -> None:
    """Load server/.env and the repo-root .env without overriding the environment."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv is a declared dependency; stay importable without it
        return
    for path in (SERVER_DIR / ".env", REPO_DIR / ".env"):
        if path.is_file():
            load_dotenv(path, override=False)


def apply_telemetry_defaults() -> None:
    for key, value in TELEMETRY_DEFAULTS.items():
        os.environ.setdefault(key, value)


def apply() -> None:
    load_env_files()
    apply_telemetry_defaults()


apply()
