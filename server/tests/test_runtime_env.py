"""Tests for runtime_env (telemetry defaults) and the cost helper in constants."""

import pytest

import runtime_env
from constants import COST_RATES, cost_usd


def test_telemetry_is_off_by_default(monkeypatch):
    monkeypatch.delenv("ANONYMIZED_TELEMETRY", raising=False)
    monkeypatch.delenv("BROWSER_USE_CLOUD_SYNC", raising=False)
    runtime_env.apply_telemetry_defaults()
    import os

    assert os.environ["ANONYMIZED_TELEMETRY"] == "false"
    assert os.environ["BROWSER_USE_CLOUD_SYNC"] == "false"


def test_explicit_telemetry_setting_is_respected(monkeypatch):
    monkeypatch.setenv("ANONYMIZED_TELEMETRY", "true")
    runtime_env.apply_telemetry_defaults()
    import os

    assert os.environ["ANONYMIZED_TELEMETRY"] == "true"


def test_browser_use_reads_telemetry_off(monkeypatch):
    monkeypatch.delenv("ANONYMIZED_TELEMETRY", raising=False)
    monkeypatch.delenv("BROWSER_USE_CLOUD_SYNC", raising=False)
    runtime_env.apply_telemetry_defaults()
    from browser_use.config import CONFIG

    assert CONFIG.ANONYMIZED_TELEMETRY is False
    assert CONFIG.BROWSER_USE_CLOUD_SYNC is False


@pytest.mark.parametrize("model, expected", [
    ("claude-sonnet-5-5", 2.00 + 10.00),
    ("claude-haiku-5-5", 0.10 + 0.50),
    ("claude-opus-5-5", 4.00 + 20.00),
    ("gpt-4o", 2.50 + 10.00),
    ("gpt-4o-mini", 0.15 + 0.60),
    ("anthropic.claude-sonnet-5-5", 2.00 + 10.00),
])
def test_cost_per_million_in_and_out(model, expected):
    assert cost_usd(model, 1_000_000, 1_000_000) == pytest.approx(expected)


def test_cost_small_run():
    # 9,048 input + 641 output on sonnet-5-5
    assert cost_usd("claude-sonnet-5-5", 9048, 641) == pytest.approx((9048 * 2 + 641 * 10) / 1e6)


def test_cache_tokens_use_cache_rates():
    assert cost_usd("claude-sonnet-5-5", 0, 0, cache_read_tokens=1_000_000) == pytest.approx(0.20)
    assert cost_usd("claude-sonnet-5-5", 0, 0, cache_write_tokens=1_000_000) == pytest.approx(2.50)
    # no cache rates listed -> input rate
    assert cost_usd("gpt-4o", 0, 0, cache_read_tokens=1_000_000) == pytest.approx(2.50)


def test_unknown_model_and_none_tokens():
    assert cost_usd("claude-unknown-9", 100, 100) is None
    assert cost_usd(None, 100, 100) is None
    assert cost_usd("claude-sonnet-5-5", None, None) == 0.0


def test_rates_keep_the_shape_existing_callers_read():
    for model, rates in COST_RATES.items():
        assert {"input", "output"} <= set(rates), model
