# Quick setup

```bash
cd server
uv sync
uv run playwright install chromium
uv run playwright install-deps chromium    # Linux only: its system libraries (asks for sudo)
echo 'ANTHROPIC_API_KEY=...' > .env        # gitignored

# Head-to-head arena: the same task on both arms, then a judge verdict
uv run python arena.py --agent RINDLER    --scenario vhlistings_product_attribute_search
uv run python arena.py --agent BROWSERUSE --scenario vhlistings_product_attribute_search
uv run python analyze_runs.py --log-dir arena_runs

# Live benchmark API for the web UI
uv run uvicorn server:app --host 127.0.0.1 --port 8000

# Tests (offline)
uv run pytest -q
```

- Only `ANTHROPIC_API_KEY` is needed. Models default to `claude-sonnet-5-5`
  (`BENCHMARK_AGENT_MODEL`, `BENCHMARK_JUDGE_MODEL`, or `--model` / `--judge-model`).
- Both arms run a local headless Chromium with the same `--max-steps` (default 30).
- New run logs go to `arena_runs/` (gitignored). `arena_logs/` is the archived March 2026
  evidence; read the caveats in [README.md](README.md) before quoting it.
- The RINDLER arm works only on mapped sites: vhlistings.com, shipt.com and amazon.com
  (`mappings/*.json`).

More: [SETUP.md](SETUP.md) (every setting, costs, mappings, troubleshooting) and
[README.md](README.md) (how the arms and the judge work, log format, site drift).
