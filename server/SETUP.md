# Arena setup

How to set up and run the head-to-head arena (`arena.py`) on one machine. The live
benchmark API in the same folder has its own settings; see `../.env.example` and the
short section in [README.md](README.md).

## What you need

- Python 3.11 and [uv](https://docs.astral.sh/uv/)
- A Chromium that Playwright installed (`uv run playwright install chromium`) and, on
  Linux, the system libraries it needs (`uv run playwright install-deps chromium`)
- An Anthropic API key in `ANTHROPIC_API_KEY`

Nothing else: no Rindler server or database, no OpenAI key, no Browserbase, Steel or
Skyvern account. Both arms run a local headless Chromium.

## Install

```bash
cd server
uv sync
uv run playwright install chromium
uv run playwright install-deps chromium    # Linux only, once: Chromium's system libraries
uv run python browser_env.py               # starts Chromium once and says whether it works
```

On Linux a bare system lacks libraries Chromium needs (`libnspr4`, `libnss3`, `libgbm` and
others), so a Chromium that installed fine still cannot start. `install-deps` adds them
with apt-get (Debian or Ubuntu; it asks for sudo unless you are root). On another
distribution install the same libraries with its package manager.

If several projects share one Playwright cache, add `PLAYWRIGHT_SKIP_BROWSER_GC=1` so
the install does not delete other projects' browser builds.

## Environment

Put these in `server/.env` or the repo-root `.env` (both are gitignored and loaded by
`runtime_env.py`; variables already set in the shell win), or export them.

| variable | default | used for |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | both arms and the judge (`ANTHROPIC_AUTH_TOKEN` also works) |
| `BENCHMARK_AGENT_MODEL` | `claude-sonnet-5-5` | agent model of both arms (`--model` overrides) |
| `BENCHMARK_JUDGE_MODEL` | `claude-sonnet-5-5` | judge model (`--judge-model` overrides) |
| `BENCHMARK_AGENT_EFFORT` | `medium` | effort for the agent model: low, medium, high, xhigh, max, or `default` (send none) |
| `BENCHMARK_JUDGE_EFFORT` | model default | effort for the judge |
| `LLM_FALLBACKS` | `default` | `off` disables the server-side refusal fallback on Sonnet/Opus |
| `BENCHMARK_HEADLESS` | `true` | `false` shows the browser windows (both arms) |
| `BENCHMARK_CHROMIUM_PATH` | the Playwright build | use another Chromium-based browser |
| `LLM_PROVIDER` | `anthropic` | `openai` runs the original gpt-4o setup (needs `uv sync --extra openai` and `OPENAI_API_KEY`) |

Telemetry is off by construction: `runtime_env.py` sets `ANONYMIZED_TELEMETRY=false`
and `BROWSER_USE_CLOUD_SYNC=false` before browser-use loads.

## Running each arm

```bash
# Rindler arm: picks mappings/vhlistings.json from the start URL's domain
uv run python arena.py --agent RINDLER --scenario vhlistings_product_attribute_search

# Same task on the browser-use arm
uv run python arena.py --agent BROWSERUSE --scenario vhlistings_product_attribute_search

# Cheaper model, smaller budget, and a full transcript of the Rindler arm
uv run python arena.py --agent RINDLER --scenario vhlistings_add_to_cart \
    --model claude-haiku-5-5 --max-steps 15 --context-log
```

The RINDLER arm only runs on sites that have a mapping (vhlistings.com, shipt.com). Any
scenario, or your own `--goal` and `--url`, runs on BROWSERUSE.

Each run prints its steps, then the judge's verdict and the token and cost totals, and
writes `arena_runs/arena_<agent>_<site>_<timestamp>.log`. Compare runs with

```bash
uv run python analyze_runs.py --log-dir arena_runs
uv run python analyze_runs.py --scenarios vhlistings_product_attribute_search
```

## What a run costs

Agent tokens are priced from `constants.COST_RATES` (claude-sonnet-5-5: $2 / $10 per
million input / output, cache reads $0.20, cache writes $2.50). As a rough guide from
the 2026-10-24 runs on vhlistings_product_attribute_search: the RINDLER arm used about
33,000 tokens ($0.03) and the judge about $0.01. The BrowserUse arm sends a screenshot
and the page's element list on every step, so it costs several times more per step.

## Adding or fixing a site mapping

1. Edit the override in `mappings/overrides/<site>.json` (a JSON merge patch; add a
   line to `_notes` saying why), or write a new `mappings/<site>.json` by hand in the
   same format (`rindler_local/mapping.py` documents it).
2. For a seed-based site, regenerate: `uv run python tools/seed_to_json.py --all`.
3. Try the actions without a model: `LocalRindlerHost(load_mapping("<site>"))` and
   `await host.call(...)` each action in turn; a failing step names the selector.
4. `uv run pytest -q tests/test_seed_to_json.py tests/test_rindler_local.py`.

## Troubleshooting

- **`ChromiumNotFoundError` / "No local Chromium found"**: run
  `uv run playwright install chromium`, or set `BENCHMARK_CHROMIUM_PATH`.
- **"Chromium cannot start: the system library libnspr4.so is missing"** (Linux):
  Chromium is installed but its system libraries are not. Run
  `uv run playwright install-deps chromium` (Debian or Ubuntu, asks for sudo) or install
  them with your package manager, then check with `uv run python browser_env.py`.
  `make setup` stops with this message, the server logs it at start-up, and a run ends
  as `error` with it.
- **"Chromium exited as soon as it started"** (a live run's message; the arena log says
  "Browser process ... exited before CDP became available"): Chromium passed the start
  check but died when a run launched it. To see its own error, start it by hand the way
  a run does: `uv run python browser_env.py` prints its path, then run
  `"<that path>" --headless=new --use-mock-keychain --password-store=basic --user-data-dir="$(mktemp -d)" about:blank`
  (add `--no-sandbox` as root in a container, as browser-use does there; Ctrl-C stops it
  if it keeps running). On Linux Chromium also aborts as it starts when `TMPDIR` is
  longer than 61 characters (its socket path would not fit), so runs then start it with
  `TMPDIR=/tmp`; set a shorter `TMPDIR` yourself only if `/tmp` cannot be written to.
- **"no model API key"**: `ANTHROPIC_API_KEY` is not set in the shell or a `.env` file.
- **`No site mapping covers ...`** (RINDLER): the start URL's domain has no
  `mappings/*.json`; use `--mapping` or run that scenario on BROWSERUSE.
- **A Rindler action returns `execution_failed`**: the message names the step and every
  selector it tried. The live site has changed; see the drift table in README.md and
  fix the mapping as above.
- **Judge verdict `ERROR`**: the judge call failed (network, rate limit, refusal); the
  reason is in the log's `Judge Reason:` line. The agent's part of the run is still logged.
- **A run seems stuck**: browser-use has its own 180 s step timeout, Rindler actions stop
  after 120 s, and the whole run stops at `--timeout` (default 1200 s).
- **Keychain dialogs on macOS**: both arms launch Chromium with `--use-mock-keychain
  --password-store=basic`; check with
  `ps -axww -o pid,command | grep '[u]se-mock-keychain'` while a run is going.
