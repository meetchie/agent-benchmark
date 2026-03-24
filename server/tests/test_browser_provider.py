"""Tests for browser provider selection logic."""
import os
import pytest
from unittest.mock import patch

from benchmark_runner import _get_browser_provider, _validate_browser_config


def test_default_provider_is_local():
    """With no env var, provider should be 'local'."""
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("BROWSER_PROVIDER", None)
        assert _get_browser_provider() == "local"


def test_browserbase_provider_from_env():
    """BROWSER_PROVIDER=browserbase should select browserbase."""
    with patch.dict(os.environ, {"BROWSER_PROVIDER": "browserbase"}):
        assert _get_browser_provider() == "browserbase"


def test_browserbase_requires_api_key():
    """Browserbase provider should raise if BROWSERBASE_API_KEY is missing."""
    with patch.dict(os.environ, {"BROWSER_PROVIDER": "browserbase"}, clear=True):
        os.environ.pop("BROWSERBASE_API_KEY", None)
        os.environ.pop("BROWSERBASE_PROJECT_ID", None)
        with pytest.raises(ValueError, match="BROWSERBASE_API_KEY"):
            _validate_browser_config()


def test_browserbase_config_valid():
    """Browserbase provider should pass validation with required env vars."""
    env = {
        "BROWSER_PROVIDER": "browserbase",
        "BROWSERBASE_API_KEY": "test-key",
        "BROWSERBASE_PROJECT_ID": "test-project",
    }
    with patch.dict(os.environ, env):
        _validate_browser_config()  # Should not raise


def test_invalid_provider_falls_back_to_local():
    """Unknown provider value should fall back to 'local'."""
    with patch.dict(os.environ, {"BROWSER_PROVIDER": "nonsense"}):
        assert _get_browser_provider() == "local"
