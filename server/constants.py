# Shared constants: model prices and the cost helper.

from __future__ import annotations

# LLM prices in USD per 1M tokens.
# "input" and "output" are required (benchmark_runner and the arena read them
# directly). "cache_read" and "cache_write" (5-minute TTL) are optional; when a
# model has none, cached tokens are priced at the input rate.
#
# Claude prices are Anthropic first-party API list prices (as published,
# checked 2026-10-06). claude-haiku-5-5 has a second rate card ($0.50 / $2.50) for
# prompts over 100K tokens; benchmark prompts stay far below that, so only the
# standard card is listed.
COST_RATES = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    # Legacy alias used by the March 2026 arena runs (resolved to claude-sonnet-4-6).
    "claude-sonnet": {"input": 3.00, "output": 15.00},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00},
}

# TODO: Stagehand and Skyvern do not report token usage.
# Cost comparisons are incomplete for these agents until their SDKs
# expose per-step token counts.


def _rates_for(model: str | None) -> dict | None:
    if not model:
        return None
    name = str(model).strip()
    if name in COST_RATES:
        return COST_RATES[name]
    # Amazon Bedrock spells Claude ids with an "anthropic." prefix.
    if name.startswith("anthropic.") and name[len("anthropic."):] in COST_RATES:
        return COST_RATES[name[len("anthropic."):]]
    return None


def cost_usd(
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cache_read_tokens: int | None = 0,
    cache_write_tokens: int | None = 0,
) -> float | None:
    """Dollar cost of a token count on ``model``, or None when the model has no known price.

    ``input_tokens`` are uncached prompt tokens (Anthropic's ``usage.input_tokens``);
    cache reads and writes are passed separately because they bill at other rates.
    """
    rates = _rates_for(model)
    if rates is None:
        return None
    per_million = (
        (input_tokens or 0) * rates["input"]
        + (output_tokens or 0) * rates["output"]
        + (cache_read_tokens or 0) * rates.get("cache_read", rates["input"])
        + (cache_write_tokens or 0) * rates.get("cache_write", rates["input"])
    )
    return per_million / 1_000_000
