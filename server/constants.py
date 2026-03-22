# Shared constants for the clean-room arena system.

# LLM cost rates per million tokens (USD).
COST_RATES = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "claude-sonnet": {"input": 3.00, "output": 15.00},
}

# TODO: Stagehand and Skyvern do not report token usage.
# Cost comparisons are incomplete for these agents until their SDKs
# expose per-step token counts.
