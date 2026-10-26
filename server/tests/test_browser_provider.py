"""Tests for browser provider selection logic."""
import os
import pytest
from unittest.mock import patch

from benchmark_runner import _get_browser_provider, _validate_browser_config


def test_default_provider_is_local():
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("BENCHMARK_BROWSER_PROVIDER", None)
        assert _get_browser_provider() == "local"


def test_browserbase_provider_from_env():
    with patch.dict(os.environ, {"BENCHMARK_BROWSER_PROVIDER": "browserbase"}):
        assert _get_browser_provider() == "browserbase"


def test_browserbase_requires_api_key():
    with patch.dict(os.environ, {"BENCHMARK_BROWSER_PROVIDER": "browserbase"}, clear=True):
        os.environ.pop("BROWSERBASE_API_KEY", None)
        os.environ.pop("BROWSERBASE_PROJECT_ID", None)
        with pytest.raises(ValueError, match="BROWSERBASE_API_KEY"):
            _validate_browser_config()


def test_browserbase_config_valid():
    env = {
        "BENCHMARK_BROWSER_PROVIDER": "browserbase",
        "BROWSERBASE_API_KEY": "test-key",
        "BROWSERBASE_PROJECT_ID": "test-project",
    }
    with patch.dict(os.environ, env):
        _validate_browser_config()


def test_invalid_provider_falls_back_to_local():
    with patch.dict(os.environ, {"BENCHMARK_BROWSER_PROVIDER": "nonsense"}):
        assert _get_browser_provider() == "local"
