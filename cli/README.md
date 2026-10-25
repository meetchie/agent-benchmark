# Comparison CLI (experimental)

Runs the same shopping tasks on prose.com twice and compares the runs.

- **BrowserUse arm.** [browser-use](https://github.com/browser-use/browser-use) drives a local headless Chromium. It gets the task text and nothing else, so it works the site out from what the page shows.
- **Rindler arm.** The model works the site through a hand-written *site mapping* (`mappings/prose.json`), a list of screens and actions with the selectors to run them. Each action becomes a tool (`view_cart`, `add_to_cart`, ...). The mapping is run in-process by `server/rindler_local` with Playwright, so the Rindler servers that used to do this are not needed. A small script (`extractors/prose.js`) summarises each page for the model.

Both arms get the same tasks, the same model and the same step budget. A judge model then grades each run against the task's success criteria.

**Treat it as experimental.** The numbers do not compare with the March 2026 results. The model, the judge, the prompts and what counts as a step have all changed, and prose.com has changed too. One run per task and arm shows that the harness works. It says very little about which arm is better.

## Run it

You need an Anthropic API key and the server environment (one environment serves the whole repo).

```bash
cd server
uv sync
uv run playwright install chromium     # once
uv run playwright install-deps chromium  # Linux only, once: its system libraries (asks for sudo)
export ANTHROPIC_API_KEY=...           # or put it in server/.env or a repo-root .env
cd ..

cli/bench.sh prose --show-tools                       # the tools the mapping gives the Rindler arm (no key needed)
cli/bench.sh prose --list-tasks
cli/bench.sh prose --task add-hair-towel              # both arms, one task
cli/bench.sh prose --browseruse-only --task add-candle
cli/bench.sh prose --rindler-only --task add-candle   # reuses the saved BrowserUse result, so the two compare
cli/bench.sh prose                                    # every task in instructions/prose.yaml
cli/viz.sh cli/results/prose-2026-10-24               # charts (from the repo root; elsewhere pass an absolute path)
```

Real runs cost money. The scripts work from any directory. Browsers are always headless, and every Chromium is started with `--use-mock-keychain --password-store=basic` so macOS never asks about the keychain.

| Flag | Meaning |
|---|---|
| `site` | File name in `mappings/` and `instructions/` (`prose`, `prose-hard`) |
| `--task ID` | Run only this task (repeat the flag, or comma-separate) |
| `--model ID` | Model for both agents. Default `BENCHMARK_AGENT_MODEL`, else `claude-sonnet-5-5` |
| `--judge-model ID` | Judge model. Default `BENCHMARK_JUDGE_MODEL`, else `claude-sonnet-5-5` |
| `--max-steps N` | One step budget for both arms on every task. Default is each task's own `max_steps` |
| `--timeout S` | Seconds one run may take, per task and arm (default 900, 0 for none) |
| `--browseruse-only` / `--rindler-only` | Run one phase. The other arm uses its saved result if there is one |
| `--fresh` | Re-run the selected phases instead of using saved results |
| `--show-tools` / `--list-tasks` | Print and exit |

A saved result is reused only if it was made with the same model and step budget.

## What it writes

```
cli/results/<site>-<date>/            (ignored by git)
    browseruse/task-<id>.json         one record per task: meta, result, stats, steps, judge
    rindler/task-<id>.json
    */screenshots/                    last page of a run that did not succeed
    summary.json                      per-arm totals, per-task rows, comparison
    charts/                           from viz.sh
```

A step is one model turn. The Rindler session start is logged as step 0 and not counted. Input tokens count every prompt token, cache reads included, and costs use the prices in `server/constants.py`. Judge cost is reported separately from agent cost.

## How fair is it

- The BrowserUse arm receives the task's goal text verbatim. The CLI refuses to start if a goal names a Rindler tool (`view_cart` and so on) or the word Rindler.
- Both arms run the same model and the same step budget. The budgets are not quite the same thing, though. A BrowserUse step is one model turn that can carry several browser actions, and a Rindler step is one model turn with one tool call.
- The Rindler arm has an advantage by design. Someone wrote its mapping for this site and it sees structured summaries, not pages. The comparison measures what that is worth, so treat the mapping as part of the product under test.
- The judge reads the agent's final report and its step trace. It cannot see the site, so it can reject a claim the trace contradicts but cannot confirm a price on the page.
- Headless Chromium can be blocked by a site. A run that fails because the site changed or blocked it is a failure of the run, and the judge may call it a plain fail.

## Known drift

The mapping, the extractor and `instructions/prose.yaml` were last checked against the live site on 2026-10-24 (see the commit history for what was fixed).

- `instructions/prose-hard.yaml` is **not** current. Its puzzles were built on March prices (brushes $72, now $85, and a new $26 eye patch) and need new answers: the exact-$107 cart, the best cart under $200, three brushes totalling $216, and the price-per-ounce task.
- prose.com renamed its candle from "Prose Candle" to "Arcadia Candle" (same $52.00 price, 8.6 fl oz). `instructions/prose.yaml` now uses the new name; `prose-hard.yaml` still refers to "the candle" generically.
- The mapping has no action to type into a form field, so tasks that need typing (the gift card recipient name) can only be done by the BrowserUse arm.

## Tests

```bash
uv run --project server pytest cli
```

No network and no model. The tests that need a browser (the Rindler arm and the prose mapping, against a local copy of the site in `tests/prose_fixture.py`) run in headless Chromium and are skipped when none is installed.

## Adding a site

Add `mappings/<site>.json`, `instructions/<site>.yaml` and, if the pages need summarising, `extractors/<site>.js`. `cli/bench.sh <site> --show-tools` prints the tool list the mapping produces. The mapping format is described in `server/rindler_local/mapping.py`.
