"""Building blocks of the BrowserUse-vs-Rindler comparison CLI (cli/run.py).

    sites          the site's mapping, page extractor and task instructions
    results        the per-task result record, the on-disk cache and summary.json
    judge          the LLM judge that grades each run against its success criteria
    browseruse_arm phase 1: browser-use on a local headless Chromium
    rindler_arm    phase 2: a tool-calling model on the site's Rindler mapping

Both arms import the repo's shared server/ modules (llm, browser_env, rindler_local), so
the CLI runs with `uv run --project server` and needs only an Anthropic API key.
"""
