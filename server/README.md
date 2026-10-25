# server/

One Python project (uv, Python 3.11) with three parts:

| part | what it is | entry point |
|---|---|---|
| Live benchmark API | FastAPI backend of the web UI in `../web`: runs one browser-use agent on a URL you give it and grades the run | `server.py` |
| Arena | Michael's head-to-head runner: the same task on two arms, **BROWSERUSE** (browser-use on its own) and **RINDLER** (a model driving the site through a hand-written Rindler site mapping), judged by an LLM | `arena.py` |
| Local Rindler | in-process interpreter of Rindler site mappings, used by the arena's RINDLER arm and by the comparison CLI | `rindler_local/` |

Everything runs on one machine with one key: `ANTHROPIC_API_KEY`. No Rindler servers, OpenAI, Browserbase, Clerk or Cloudflare are needed.

From the repository root, `make setup` and `make dev` do the setup and start-up described below; see [../README.md](../README.md). Settings live in `.env` at the repository root (`server/.env` also works and wins over it).

## Setup

```bash
cd server
uv sync
uv run playwright install chromium        # the local Chromium both arms use
echo 'ANTHROPIC_API_KEY=...' > .env       # or export it; .env files are gitignored
uv run pytest -q                          # offline; no key or network needed
```

[QUICK_SETUP.md](QUICK_SETUP.md) is the short version; [SETUP.md](SETUP.md) covers every setting and the usual problems.

## Live benchmark API (short)

```bash
uv run uvicorn server:app --host 127.0.0.1 --port 8000     # run from server/
DEMO_MODE=true uv run uvicorn server:app                   # canned runs, no key, no browser
```

Routes: `POST /benchmark/start`, `GET /benchmark/status/{id}`, `POST /benchmark/cancel/{id}`, `POST /benchmark/generate-tasks`, `GET /benchmark/quota`, `GET /health`. Finished runs are saved as JSON under `server/runs/`. Settings (`AUTH_MODE`, `DAILY_RUN_QUOTA`, `BENCHMARK_TIMEOUT_S`, ...) are listed in `../.env.example` (the one template for the whole repo). The web UI talks to it on `http://127.0.0.1:8000`.

## Arena

```bash
uv run python arena.py --list-scenarios --tag e-commerce
uv run python arena.py --agent RINDLER    --scenario vhlistings_product_attribute_search
uv run python arena.py --agent BROWSERUSE --scenario vhlistings_product_attribute_search
uv run python analyze_runs.py                               # table over March + new runs
uv run python analyze_runs.py --march-headline              # the March headline: Rindler 59/60 vs BrowserUse 1/60
```

### The two arms

| | BROWSERUSE | RINDLER |
|---|---|---|
| what drives the browser | browser-use 0.13 (screenshots + DOM, its own action set) | the model calls one tool per mapping action; `rindler_local` runs the action's steps with Playwright |
| site knowledge | none | the site's mapping in `mappings/<site>.json` (selectors, screens, fallbacks, popup handling) |
| browser | local headless Chromium (`browser_env.browser_profile()`) | local headless Chromium (`rindler_local.LocalRindlerHost`) |
| model | `--model`, else `BENCHMARK_AGENT_MODEL`, else `claude-sonnet-5-5` | same |
| step budget | `--max-steps` browser-use steps (default 30) | `--max-steps` model turns (default 30) |
| task text | the scenario goal (no Rindler tool names in it) | the scenario goal, plus a system prompt that explains the tools |
| finishes when | browser-use calls its `done` action | the model calls the injected `done` tool |
| sites | any | only sites with a mapping: vhlistings.com and shipt.com |

Both arms start on the scenario's start URL without spending a step, use prompt caching, and log every model call's tokens, so the costs compare like for like. Chromium is always launched with `--use-mock-keychain --password-store=basic` (no macOS keychain prompts) and headless unless `BENCHMARK_HEADLESS=false`.

### Flags

| flag | default | meaning |
|---|---|---|
| `--agent` | (required) | `BROWSERUSE` or `RINDLER` |
| `--scenario` / `--goal` + `--url` | | a scenario from `scenarios/definitions.py`, or your own goal |
| `--model` (alias `--llm`) | `BENCHMARK_AGENT_MODEL` / `claude-sonnet-5-5` | agent model, either arm |
| `--judge-model` | `BENCHMARK_JUDGE_MODEL` / `claude-sonnet-5-5` | judge model |
| `--max-steps` | 30 | the same budget for both arms |
| `--timeout` | 1200 | seconds before a run is stopped (0 = none) |
| `--mapping` | by start-URL domain | RINDLER: mapping name (`vhlistings`) or a JSON path |
| `--context-log` | off | RINDLER: also write `context_rindler_<ts>.log` with every message sent to the model |
| `--log-dir` | `arena_runs/` | where logs go |
| `--no-judge` | off | skip the judge call |

### Scoring

After a run the judge (`run_judge` in `arena.py`, the March prompt unchanged, verdict schema enforced with structured outputs) gets the goal, the scenario's success criteria and verification hint, the agent's own success flag, step count, errors and action names, and the agent's final report. It answers PASS or FAIL with the criteria met and failed. It never looks at the site, so a PASS means "the judge believed the agent's report". The judge's cost is logged separately from the agent's.

### Logs

New runs are written to `arena_runs/arena_<agent>_<site>_<YYYYmmdd_HHMMSS>.log` (gitignored). The format is the March one: header lines (`Agent:`, `Scenario:`, `Goal:`, `Start URL:`, `Duration:`, `Agent Reported Success:`), the `--- JUDGE EVALUATION ---` block, `Token Burn:` and `Cost:`, then `Telemetry Events:` followed by a JSON list of `step_start` / `step_end` events. New logs add `Agent Model:`, `Max Steps:`, `Mapping:` (RINDLER), `Judge Model:`, `Judge Cost:` and `Final Report:`; older readers ignore them. Each `step_end` carries `tokens_input` (all prompt tokens, cache reads and writes included), `tokens_output`, `tokens_cache_read`, `tokens_cache_write` and `cost_usd` (from `constants.COST_RATES`).

`analyze_runs.py` reads `arena_logs/` and `arena_runs/` (or any `--log-dir`, repeatable) and groups runs by scenario, agent and agent model, so the March runs (model not recorded, shown as `-`) never mix with new ones. Judge Pass and Reported are shown as counts with percentages (`59/60 (98.3%)`). Reported is only the agent's own claim of success. Filters: `--agents`, `--scenarios`, `--since` and `--until` (a date, or a date and time such as `"2026-03-31 00:28:27"`, both inclusive). `uv run python analyze_runs.py --march-headline` prints the March headline table, the exact set behind it (all 60 BrowserUse and the last 60 Rindler `vhlistings_bundle_promo` logs, Rindler 59/60 against BrowserUse 1/60), from `arena_logs/` only. The log viewer in `../viewer` reads the same format: copy logs into `viewer/public/logs/` and add them to its `manifest.json`.

## Local Rindler (`rindler_local/`)

The March Rindler arm talked to a Go MCP server backed by Postgres, Redis and OAuth. `rindler_local` replaces that stack with Playwright running the same mapping JSON in-process:

```python
from rindler_local import LocalRindlerHost, load_mapping

async with LocalRindlerHost(load_mapping("vhlistings")) as host:
    tools = await host.list_tools()          # start_session, the mapping's actions, close_session
    env = await host.call("start_session", {"url": "https://vhlistings.com"})
    env = await host.call("search_products", {"query": "chain belt"})
    # env == {"screen", "context", "data": {"page_url", "products" | "cart_items", "page_info"},
    #         "available_actions", "global_actions"}  (+ "error": {"code", "message"} on failure)
```

`call_tool(name, args)` returns the MCP-style `{"content": [{"type": "text", "text": <json>}], "isError": bool}`; `call()` returns the parsed envelope. Screens are matched by `url_pattern` (longest first); actions run `navigate`, `click` (with css / xpath / text / text_exact / role / label / placeholder fallbacks), `type`, `select`, `press_key`, `extract`, `wait` and `script` steps with `{{param}}` interpolation, optional steps and per-step timeouts; `context_extractors` fill `context`; `interrupt_handlers` dismiss a popup once per session; the mapping's `page_extractor` JavaScript fills `data.page_info`. `products` and `cart_items` are read from the page's accessibility tree.

### Mappings

`mappings/vhlistings.json` and `mappings/shipt.json` are what runs. They are generated from the March seeds (`mappings/seed_*.sql`, kept as the source) by

```bash
uv run python tools/seed_to_json.py --all          # rewrite the JSON
uv run python tools/seed_to_json.py --all --check  # exit 1 if the JSON is stale (also a test)
```

which also applies `mappings/overrides/<site>.json`, a JSON merge patch whose `_notes` say why each change was made. The notes are copied into the JSON's `_provenance`, so every difference from the March seed is visible in the file that runs.

### What the live sites look like now (checked 2026-10-24)

vhlistings.com, each action driven without a model:

| action | today |
|---|---|
| start_session, search_products, view_product, add_to_cart, checkout | work as in March (the newsletter popup is dismissed by the interrupt handler) |
| view_cart | the cart page no longer lists its items in the accessibility tree; the override makes `page_info` read Shopify's `/cart.js` (`cart_item_count`, `cart_lines`) |
| next_page / prev_page | work through a fallback added in the override (the arrows carry only an aria-label) |
| remove_from_cart | **fails**: the cart page has no visible remove control any more (only a hidden one inside the cart drawer). Not fixed |
| apply_promo | runs, but the site rejects the code `SPRING` ("Enter a valid discount code or gift card"), so `vhlistings_bundle_promo` cannot pass today on either arm |
| VIP Membership | still added to the cart by the site and re-added whenever /cart is opened; `checkout` still removes it before the order summary |

shipt.com, driven without a model: start_session, update_address (with the placeholder address), search_products (the store slug defaults to `target`), add_to_cart and view_cart work. checkout, remove_from_cart, update_quantity and select_store were not tried, and no shipt scenario has been run with a model since March.

### First local runs (2026-10-24, claude-sonnet-5-5 on both arms and the judge)

vhlistings_product_attribute_search, one run each:

| run | verdict | steps | duration | agent cost | judge cost |
|---|---|---|---|---|---|
| RINDLER, before the pagination fix | FAIL | 7 | 43.8 s | $0.0262 | $0.0088 |
| BROWSERUSE, after the adapter fix | FAIL | 23 | 138.9 s | $0.4587 | $0.0088 |
| RINDLER, after the pagination fix | PASS | 8 | 54.6 s | $0.0278 | $0.0084 |

The store no longer has a chain belt under $35. Both Rindler runs added "Gravechain Crucifix Belt" ($52) and called it a chain belt from its name, as the task allows; its product page says it is genuine leather. The BrowserUse arm looked through three result pages and a second search, found no chain belt under $35, added the same belt as the closest fallback and said in its report that it was neither a chain belt nor under $35, and the judge failed it. The Rindler PASS is therefore the judge accepting a name-based report, the weakness caveat 4 below describes. One run per arm proves the setup works; it says nothing about which arm is better.

The BrowserUse row was first measured before the browser-use adapter was fixed (9 steps, 109.3 s, $0.5890): the model answered each step by calling the action itself and the adapter made a second request to have it wrapped, 21 API calls for 9 steps. After the fix every step is one API call with no repairs (23 calls for 23 steps). The task cannot be completed on today's store, so the number of steps depends on how long the agent keeps looking and differs from run to run.

## The March 2026 results (`arena_logs/`)

`arena_logs/` holds the 137 archived March logs (131 runs plus 6 Rindler context logs), unchanged since extraction apart from the redactions listed under Provenance in the root README. The headline result, vhlistings_bundle_promo, is Rindler 59/60 judge passes against BrowserUse 1/60 (`uv run python analyze_runs.py --march-headline` prints it), at $0.14 vs $0.71 mean cost and 70 s vs 307 s mean duration. Read it with these caveats, all checked in the code and history:

1. The Rindler arm drove a hand-mapped site (25 mapping versions tuned on this exact site and task); BrowserUse had no mapping. The VIP criterion is met by the mapping's own cleanup step.
2. The task text both arms got contained Rindler tool vocabulary ("Start a session", "call view_cart", "remove_from_cart"). It has since been removed from the scenarios.
3. Different substrates: BrowserUse on a Browserbase cloud browser with 30 steps, Rindler on a local Playwright browser with 25 steps; both on gpt-4o, costed at gpt-4o list prices.
4. The judge was gpt-4o-mini reading the agent's own final report. Single site, single task, n=60 each, all on 2026-03-31 against a live third-party store.
5. The shipt numbers are tiny (1 BrowserUse run vs 2 Rindler runs).
6. Timestamps in the file names are the runner's local time.

New runs on Claude models, both arms local, equal step budgets and neutral task text are not comparable to these numbers, and the site has changed since (see above).

## Tests

`uv run pytest -q` runs everything offline. The arena's part: `tests/test_rindler_local.py` (the interpreter on a real headless Chromium against a local fixture shop, `tests/fixture_shop.py`; skipped if no Chromium is installed), `test_seed_to_json.py`, `test_rindler_agent.py`, `test_arena.py` (judge with a mocked model, logs, analyze_runs, the BrowserUse arm with a fake browser-use Agent) and `test_scenarios.py`.
