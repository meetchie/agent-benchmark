# agent-benchmark

A benchmark that puts a **normal browser agent** and a **site-mapped agent** on the same shopping tasks and measures what happens.

- The normal agent is [browser-use](https://github.com/browser-use/browser-use): it looks at a page (a screenshot and the element list) and decides what to click, one step at a time.
- The other is **Rindler**, an agent that drives a site through a hand-written *site mapping*. A mapping lists the site's screens and actions (`search_products`, `add_to_cart`, `checkout`, ...) with the selectors, fallbacks and popup handling needed to run each one. Every action becomes a tool, so the model chooses between a few named tools instead of reading raw pages.

It was built at Rindler in 2026 (see [Provenance](#provenance)). The Rindler servers behind it are retired, so this repository has been adapted to run on one machine with **one Anthropic API key**: no Rindler service, OpenAI key, Clerk account, Cloudflare or Browserbase is needed. A mapping is run in-process by `server/rindler_local/` with Playwright.

## What is in here

| folder | what it is |
|---|---|
| `web/` | The live benchmark UI (React + Vite). Paste a site's URL, pick one of three generated tasks, watch a browser-use agent try it. |
| `server/` | One Python package (uv). The FastAPI **live-benchmark API** behind `web/`, Michael's head-to-head **arena** (`arena.py`), the local Rindler interpreter (`rindler_local/`), the site mappings (`mappings/`) and the archived March 2026 arena logs (`arena_logs/`). |
| `cli/` | Arthur's **prose.com comparison CLI**: the same tasks on both arms, judged, with charts. Experimental. |
| `viewer/` | A static **log viewer** for the archived March 2026 arena logs, with the headline results page. Needs no key. |

Each folder has its own README with the details: [web](web/README.md), [server](server/README.md) (and [SETUP](server/SETUP.md)), [cli](cli/README.md), [viewer](viewer/README.md).

## Quickstart

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) (it fetches Python 3.11 itself), Node.js 20 or newer with npm (`web/.nvmrc` says 22), and `make`. It was built and checked on macOS (Apple silicon); Linux should work, Windows was not tried.

```bash
cp .env.example .env     # then put your key after ANTHROPIC_API_KEY=
make setup               # uv sync, Playwright's Chromium, npm ci for web and viewer
make dev                 # backend on 127.0.0.1:8000, web UI on http://localhost:5180
```

Open the URL `make dev` prints. No key yet? `make demo` starts the same UI with canned runs and tasks, so the whole flow works with no key, no browser and no cost.

`make` with no target lists everything:

| command | what it does |
|---|---|
| `make setup` | Installs the Python environment, Chromium and the npm packages. Run once. |
| `make dev` | Backend and web UI together. Ctrl-C stops both. |
| `make demo` | The same with `DEMO_MODE=true`: canned runs, no key. |
| `make test` | Every test suite (offline, no key needed). |
| `make arena AGENT=RINDLER SCENARIO=vhlistings_product_attribute_search` | One arena run. A real run that costs money. `make arena-list` shows the options, `make analyze` the results table. |
| `make compare TASK=add-hair-towel` | The prose CLI on one task, both arms. A real run that costs money. `make compare-tasks` and `make compare-tools` need no key. |
| `make viewer` | Browse the archived March 2026 logs. |

`make dev` starts two servers and, on Ctrl-C or any exit, stops exactly those two by PID (and what they spawned). `scripts/dev.sh` is the whole of it. It starts the backend on the port in `BENCHMARK_API_URL` (default 8000) and the web UI on `BENCHMARK_WEB_PORT` (default 5180), so a busy port is a setting, not a code change.

## Configuration

Settings are environment variables. Put them in **`.env` in the repository root** (copy `.env.example`, which lists every variable with its default and a comment). `server/.env` also works and wins over the root file, and a variable exported in your shell wins over both. The Python code loads these files through `server/runtime_env.py`, and the web dev server reads the same root file. Only `ANTHROPIC_API_KEY` is required.

| variable | default | meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Claude API key for the agent, judge and task generator. `ANTHROPIC_AUTH_TOKEN` is accepted instead. |
| `LLM_PROVIDER` | `anthropic` | `openai` runs the original gpt-4o setup (needs `cd server && uv sync --extra openai` and `OPENAI_API_KEY`). Only unit-tested. |
| `OPENAI_API_KEY` | unset | Only with `LLM_PROVIDER=openai`. |
| `BENCHMARK_AGENT_MODEL`, `BENCHMARK_JUDGE_MODEL`, `BENCHMARK_TASKGEN_MODEL` | `claude-sonnet-5-5` | One model per role. |
| `BENCHMARK_AGENT_EFFORT`, `BENCHMARK_JUDGE_EFFORT`, `BENCHMARK_TASKGEN_EFFORT` | agent `medium`, others model default | `low`, `medium`, `high`, `xhigh`, `max` or `default` (send none). |
| `LLM_FALLBACKS` | `default` | `off` disables the server-side refusal fallback. |
| `DEMO_MODE` | off | `true`: canned runs and tasks, no key, no browser. |
| `BENCHMARK_TIMEOUT_S` | `180` | Hard limit for one run. Over it the run is `too_slow`. |
| `AUTH_MODE` | `none` | `none`: one local user, no sign-in. `clerk`: see [Optional: Clerk sign-in](#optional-clerk-sign-in). |
| `DAILY_RUN_QUOTA` | `0` (`3` with clerk) | Runs per user per rolling 24 hours, `0` = unlimited. |
| `MAX_CONCURRENT_RUNS` | `2` | Runs one user may have going at once, `0` = unlimited. |
| `RUNS_DIR` | `server/runs/` | Where finished runs are saved, one JSON file each. |
| `ALLOWED_ORIGINS` | the Vite dev servers on localhost | CORS origins, comma separated. |
| `INTERNAL_API_KEY` | unset | If set, requests must send it in `X-Internal-Key`. |
| `BENCHMARK_HEADLESS` | `true` | `false` shows the browser window. |
| `BENCHMARK_CHROMIUM_PATH` | the Playwright build | Use another Chromium-based browser. |
| `PLAYWRIGHT_BROWSERS_PATH` | Playwright's cache | Where `playwright install` put the browsers. |
| `BENCHMARK_BROWSER_PROVIDER` | `local` | `browserbase` uses a cloud browser (needs the next two). Live benchmark only, and not run for real in this standalone version. |
| `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID` | unset | Only for `browserbase`. |
| `ANONYMIZED_TELEMETRY`, `BROWSER_USE_CLOUD_SYNC`, `BROWSER_USE_VERSION_CHECK` | `false` | browser-use's telemetry, cloud sync and its pypi.org version check are off unless you export one as `true`. |
| `BENCHMARK_API_URL` | `http://127.0.0.1:8000` | Backend the web dev server proxies to. |
| `BENCHMARK_WEB_PORT` | `5180` | Port of the web dev server. |
| `CLERK_ISSUER_URL`, `CLERK_PUBLISHABLE_KEY`, `CLERK_JWKS_URL`, `VITE_CLERK_PUBLISHABLE_KEY` | unset | Only for Clerk sign-in. |

Browsers always run headless unless you say otherwise, and every Chromium launch carries `--use-mock-keychain --password-store=basic` so macOS never asks about the keychain. Run `ps -axww -o pid,command | grep '[u]se-mock-keychain'` during a run to see it.

## The live benchmark

You give the web app a site URL. The server fetches the page and a model proposes three tasks for it (commerce sites only, anything else answers 422). You pick one and the server starts a browser-use agent in a throwaway headless Chromium, using `BENCHMARK_AGENT_MODEL`. The UI polls the run and shows each step as it happens.

**How a run is scored.** When the agent stops, a judge model (`BENCHMARK_JUDGE_MODEL`) reads the task and the list of steps with their timings and decides. It never sees the page or a screenshot, only the step text. The run ends in one of four states:

| state | meaning |
|---|---|
| `pass` | The judge says the agent fully completed the task as written, including verification. |
| `fail` | The agent ran to the end and the judge says it did not. |
| `too_slow` | The agent was still going after `BENCHMARK_TIMEOUT_S` (default 180 s) and was stopped. The judge still reads the steps it took and marks no phase as failed. |
| `error` | The run could not be judged as a pass or fail: the model refused part-way, every step failed (a bad API key, say), Chromium is missing, a setting is invalid, or you cancelled it. The message says which. |

The judge also groups the steps into 3 to 6 **phases** named for what the user was trying to do ("Find the right yoga mat", "Verify cart contents"). The judge is told to flag a phase as *slow* when it took more than 45 seconds or showed pointless retries (and to flag the slowest one even if nothing was slow, so every run shows something), and to flag at most one phase as *failed*, the one where the agent actually went wrong, never on a `too_slow` run. The results screen shows the verdict, summary, phases, time, steps, tokens and the cost in dollars for the agent's tokens at the agent model's prices. A model without a price table shows tokens only.

Finished runs are saved as JSON in `server/runs/` (gitignored). The API is `POST /benchmark/start`, `GET /benchmark/status/{id}`, `POST /benchmark/cancel/{id}`, `POST /benchmark/generate-tasks`, `GET /benchmark/quota` and `GET /health`, which reports the provider and models and never a key.

## The head-to-head arena

`server/arena.py` runs one scenario on one of two **arms** and has a judge grade it. Run both arms on the same scenario to compare them.

| | BROWSERUSE | RINDLER |
|---|---|---|
| drives the browser with | browser-use, screenshots plus the page's elements | the model calling one tool per mapping action, run by `rindler_local` with Playwright |
| knows the site | no | yes, through `server/mappings/<site>.json` |
| runs on | any site | vhlistings.com and shipt.com (sites with a mapping) |

Both arms use the same model (`--model`), the same step budget (`--max-steps`, default 30), a local headless Chromium, prompt caching, and the same neutral task text, and both log every model call's tokens so costs compare like for like. About 30 scenarios are defined in `server/scenarios/definitions.py`.

```bash
make arena-list
make arena AGENT=RINDLER    SCENARIO=vhlistings_product_attribute_search
make arena AGENT=BROWSERUSE SCENARIO=vhlistings_product_attribute_search
make analyze                                  # table over arena_logs/ and arena_runs/
```

The judge gets the goal, the scenario's success criteria, the agent's own report and its step trace, and answers PASS or FAIL. It cannot see the site, so a PASS means the judge believed the report. Logs go to `server/arena_runs/` in the same format as the March ones, with a few added fields. [server/README.md](server/README.md) has the flags, the log format and what the mappings look like.

## The prose comparison CLI

`cli/` runs ten tasks on prose.com (browsing and adding accessories to a cart) twice, once per arm, then judges both and draws charts. It uses the same local Rindler interpreter with its own mapping (`cli/mappings/prose.json`), the same model and the same step budget for both arms, and it refuses to start if a task's text names a Rindler tool.

```bash
make compare-tools                    # the tools the mapping gives the Rindler arm (no key)
make compare-tasks                    # (no key)
make compare TASK=add-hair-towel      # both arms, one task: about 20 cents
cli/viz.sh cli/results/prose-<date>       # charts for a finished comparison
```

It is **experimental**. Its numbers do not compare with March, and `instructions/prose-hard.yaml` is stale because prose.com's prices changed. See [cli/README.md](cli/README.md).

## The log viewer

```bash
make viewer      # http://localhost:5173
```

`viewer/` shows the archived March 2026 arena logs: a results page with the headline comparison, and a log view with the judge verdict, a step timeline, a cumulative cost chart and simple friction flags. It reads files only and needs no key. You can also drop any arena-format `.log` there; to show new `arena_runs/` logs in its picker, copy them to `viewer/public/logs/` and add them to `manifest.json`.

## The archived March 2026 result

`server/arena_logs/` holds the 137 original logs (131 runs plus 6 Rindler context logs) and is never modified. The headline is one task, `vhlistings_bundle_promo` on the Shopify store vhlistings.com (add three items to the cart, apply the promo code `SPRING`, reach checkout, stop before payment; the judge also fails the run if a "VIP Membership" the site adds on its own is still in the order). 60 runs per arm, all on 2026-03-31, both arms on gpt-4o:

| | Rindler | BrowserUse |
|---|---|---|
| judge passes | **59 / 60** | **1 / 60** |
| mean duration | about 70 s | about 307 s |
| mean cost per run | $0.14 | $0.71 |
| mean tokens | 52,856 | 272,377 |
| mean steps | 14.1 | 28.5 |

The costs are token counts priced at gpt-4o list rates ($2.50 and $10 per million input and output tokens), not billed amounts. Recomputed from the logs: Rindler $8.20 in total, BrowserUse $42.78. The viewer's results page shows the same figures. (`make analyze` counts all 66 Rindler `vhlistings_bundle_promo` logs, 65 of them passes, because it does not drop the 6 earlier runs.)

**Read it with every one of these caveats.** It is evidence that a hand-mapped site makes this task easy for an agent, not a fair contest between two agents.

1. **Mapped against unmapped.** The Rindler arm drove a site that someone had mapped by hand: 25 versions of the mapping, tuned on this exact site and task. The "no VIP Membership" criterion is met by the mapping's own cleanup step. BrowserUse had no mapping.
2. **The prompts used Rindler's vocabulary.** The task text given to both arms said things like "Start a session", "call view_cart" and "remove_from_cart" (the 2026-03-19 shipt Rindler goal even says "using Rindler's semantic commerce tools"). That text has since been removed from the scenarios.
3. **Different setups.** BrowserUse ran in a Browserbase cloud browser with a 30-step cap. Rindler ran on server-local Playwright with a 25-step cap. Both used gpt-4o.
4. **A weak judge.** The judge was gpt-4o-mini reading the agent's own final report. BrowserUse's single pass shows it can err in either direction. `Agent Reported Success: True` appears in every log of both arms and only means the run did not crash, so ignore it. Nine BrowserUse logs mention hitting the step limit.
5. **One site, one task, one night.** 60 runs per arm against a live third-party store (with a Klaviyo popup and an asynchronous Shopify checkout) on 2026-03-31. The store has changed since and these runs cannot be reproduced against it. The viewer's failure funnel and its "dark pattern" labels are hand-curated by the original authors, not derived from the logs.
6. **The shipt numbers are tiny** (1 BrowserUse run against 2 Rindler runs in `arena_logs/`). The February comparisons of BrowserUse against BrowserUse with Rindler's tools over MCP exist only in the git history. They used a judge that was revised on 2026-03-17 and must not be pooled with March.
7. **Time.** The timestamps in the log file names are the runner's local time, not UTC (the commits of that night are at UTC-4).

Also remember what is left out: the 60 runs per arm are the last 60 Rindler and all 60 BrowserUse `vhlistings_bundle_promo` logs. There are 8 more Rindler logs (earlier mapping versions and a different scenario) in the folder and in the viewer's picker that the headline does not use.

### New local runs

On 2026-10-24 the arms were run again in this standalone form (claude-sonnet-5-5 for agent and judge, both arms local, equal budgets, neutral task text), one run each. These runs show the setup works and nothing else. They are **not comparable** to the March numbers, and one run per arm cannot say which arm is better.

| scenario | arm | verdict | steps | time | agent cost |
|---|---|---|---|---|---|
| `vhlistings_product_attribute_search` | RINDLER | PASS | 8 | 55 s | $0.03 |
| `vhlistings_product_attribute_search` | BROWSERUSE | FAIL | 9 | 109 s | $0.59 |
| prose.com `add-hair-towel` (CLI) | RINDLER | pass | 5 | 18 s | $0.02 |
| prose.com `add-hair-towel` (CLI) | BrowserUse | pass | 7 | 36 s | $0.17 |

The first row is a warning about the judge. The store no longer sells the chain belt that March's run picked, so the Rindler arm added a $52 belt with "chain" in its name. Two Rindler runs made that choice and the judge passed one and failed the other. The BrowserUse arm opened that belt's page, saw it was genuine leather and added nothing. A PASS here is the judge accepting a report built on a product's name. [server/README.md](server/README.md) tells it in full.

Cost in practice (single runs, claude-sonnet-5-5): a Rindler arm run is a few cents, and anything driven by browser-use is several times that. Two live-benchmark runs on books.toscrape.com cost $0.28 and $0.41, plus about a cent for the judge and one to two cents to generate tasks.

## Limits

- **Live sites drift.** Every result here is a snapshot of third-party websites. Checked on 2026-10-24: vhlistings.com now rejects the promo code `SPRING`, so `vhlistings_bundle_promo` cannot pass on either arm today; its cart page no longer exposes a remove control, so the `remove_from_cart` action fails; the mappings were repaired where a selector had moved (pagination, the cart listing). books.toscrape.com has no Add to basket button on a book's own page, so a generated task for it can fail whatever the agent does. prose.com's prices changed enough that `instructions/prose-hard.yaml` needs new answers, and the mapping cannot type into a form field. A run that fails because the site changed is a failed run, not a finding.
- **Headless browsers get blocked.** The browser is a headless Chromium on your own IP address. Sites behind a bot wall (Cloudflare, captchas, anything that fingerprints headless Chrome) may show a block page, and then the agent fails for a reason that has nothing to do with it. `BENCHMARK_HEADLESS=false` opens a visible window, which may get past some of them. The original hosted setup used headed cloud browsers (Browserbase) to avoid this; that provider is still in the code but was not run again.
- **The task generator is a model.** For books.toscrape.com it answered "not a commerce site" on 2 of 5 tries. A retry works.
- **The step budgets are not the same unit.** A browser-use step is one model turn that can carry several browser actions. A Rindler step is one model turn with one tool call.
- **One run is an anecdote.** Sampling noise on a live site is large. Use many runs before drawing a conclusion.
- **Real runs cost money,** and the default 180 s limit can be tight for a long task (raise `BENCHMARK_TIMEOUT_S`).
- **Mappings exist for three sites:** vhlistings.com and shipt.com (arena) and prose.com (CLI). The RINDLER arm cannot run anywhere else. Adding a site means writing a mapping, see [cli/README.md](cli/README.md) and [server/SETUP.md](server/SETUP.md).

## Optional setups

### Optional: Clerk sign-in

By default the app is one always-signed-in local user. To use real sign-in, set the backend to verify Clerk tokens and the web app to show the Clerk UI:

```bash
AUTH_MODE=clerk
CLERK_PUBLISHABLE_KEY=...         # or CLERK_ISSUER_URL=https://<your-clerk-domain>
VITE_CLERK_PUBLISHABLE_KEY=...    # the same publishable key, for the web UI
```

Restart `make dev` after changing them. In Clerk mode the daily quota defaults to 3 runs per user. Know the limits: this path was only tested with mocks and a build, never against a live Clerk instance; the status and cancel routes take just the run id and do not check who owns the run, so do not host Clerk mode as it is; and `@clerk/clerk-react` is deprecated upstream in favour of `@clerk/react`. The web UI cannot tell which mode the backend runs in: a local-mode UI against a Clerk backend shows a hint about the 401.

### Optional: OpenAI and Browserbase

`LLM_PROVIDER=openai` switches every model call back to the original gpt-4o setup (`uv sync --extra openai`, then `OPENAI_API_KEY`). `BENCHMARK_BROWSER_PROVIDER=browserbase` runs the live benchmark's browser in a Browserbase cloud session. Both exist in the code and are covered by unit tests only.

## Tests

```bash
make test        # all of it, offline, no key needed
```

| suite | command | what it covers |
|---|---|---|
| server | `make test-server` | The API, the LLM layer, the browser-use adapter, the local Rindler interpreter (some tests drive a real headless Chromium against a local fixture shop and are skipped without one), the arena, the scenarios and the mappings. |
| cli | `make test-cli` | The CLI's arms, judge and results, the prose mapping against a local copy of the site. It must run apart from the server suite because the two have different pytest settings. |
| web | `make test-web` | The UI's tests (vitest) and a production build. |
| viewer | `make test-viewer` | A production build. The viewer has no tests. |

No test calls a model API: the SDK base URLs point at a closed local port, so a stray call fails at once instead of costing money. The browser tests run against local fixture sites.

## Provenance

This was built at Rindler in 2026 by Michelle Serrano (`meetchie`), Michael Serrano and Arthur De Los Santos. By commits before October 2026, the web app is mostly Michelle's (71 of 91), the server and the arena mostly Michael's (115 of 160), and the CLI Arthur's (35 of 36); `git shortlog -sn --before=2026-10-01 -- <folder>` has the exact numbers.

This repository keeps the original commit history, with its authors and dates (341 commits from December 2025 to March 2026, plus a few later ones to the web app). It was extracted from the company's monorepo in October 2026 and then adapted to run standalone: the hosted pieces were replaced with local ones (Anthropic models instead of OpenAI, a local file store instead of the Rindler database, an in-process mapping interpreter instead of the Rindler servers, a no-sign-in local mode, with Clerk optional). The commits from October 2026 are that adaptation.

Some values were redacted when the history was extracted: a street address that was used as task input, staff email addresses, and third-party account identifiers (for example the Browserbase account in session replay links).
