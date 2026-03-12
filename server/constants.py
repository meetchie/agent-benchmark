# Shared constants for the clean-room arena system.

# LLM cost rates per million tokens (USD).
COST_RATES = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "claude-sonnet": {"input": 3.00, "output": 15.00},
}

# Default cost rates (used when model is unknown or for BrowserUse).
DEFAULT_COST_INPUT = 5.00   # $/M tokens
DEFAULT_COST_OUTPUT = 15.00  # $/M tokens
