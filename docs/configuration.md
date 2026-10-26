# Configuration

Settings are environment variables. Put them in `.env` in the repository root. Copy `.env.example`, which lists every variable with its default and a comment. `server/.env` also works and wins over the root file, and a variable exported in your shell wins over both. The Python code loads these files through `server/runtime_env.py`, and the web dev server reads the same root file.

Only `ANTHROPIC_API_KEY` is required.

| variable | default | meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Claude API key for the agent, judge and task generator. `ANTHROPIC_AUTH_TOKEN` is accepted instead. |
| `LLM_PROVIDER` | `anthropic` | `openai` runs the original gpt-4o setup (needs `cd server && uv sync --extra openai` and `OPENAI_API_KEY`). Only unit-tested. |
| `OPENAI_API_KEY` | unset | Only with `LLM_PROVIDER=openai`. |
| `BENCHMARK_AGENT_MODEL`, `BENCHMARK_JUDGE_MODEL`, `BENCHMARK_TASKGEN_MODEL` | `claude-sonnet-5-5` | One model per role. |
| `BENCHMARK_AGENT_EFFORT`, `BENCHMARK_JUDGE_EFFORT`, `BENCHMARK_TASKGEN_EFFORT` | agent `medium`, others model default | `low`, `medium`, `high`, `xhigh`, `max` or `default` (send none). |
| `LLM_FALLBACKS` | `default` | `off` disables the server-side refusal fallback. |
| `DEMO_MODE` | off | `true`: canned runs and tasks, no key, no browser. |
| `BENCHMARK_TIMEOUT_S` | `180` | Hard limit for one run. Over it the run is `too_slow`. `GET /health` reports it as `timeout_s`, and the web UI keeps polling a run for that long plus 180 s of judging. |
| `AUTH_MODE` | `none` | `none`: one local user, no sign-in. `clerk`: see [Clerk sign-in](#clerk-sign-in). |
| `DAILY_RUN_QUOTA` | `0` (`3` with clerk) | Runs per user per rolling 24 hours, `0` = unlimited. |
| `MAX_CONCURRENT_RUNS` | `2` | Runs one user may have going at once, `0` = unlimited. |
| `RUNS_DIR` | `server/runs/` | Where finished runs are saved, one JSON file each. |
| `ALLOWED_ORIGINS` | the Vite dev servers (ports 5180 and 5173) on `localhost` and `127.0.0.1` | CORS origins, comma separated. |
| `INTERNAL_API_KEY` | unset | If set, requests must send it in `X-Internal-Key`. |
| `BENCHMARK_HEADLESS` | `true` | `false` shows the browser window. |
| `BENCHMARK_CHROMIUM_PATH` | the Playwright build | Use another Chromium-based browser. |
| `PLAYWRIGHT_BROWSERS_PATH` | Playwright's cache | Where `playwright install` put the browsers. |
| `BENCHMARK_BROWSER_PROVIDER` | `local` | `browserbase` uses a cloud browser (needs the next two). Live benchmark only, and not run for real in this standalone version. |
| `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID` | unset | Only for `browserbase`. |
| `ANONYMIZED_TELEMETRY`, `BROWSER_USE_CLOUD_SYNC`, `BROWSER_USE_VERSION_CHECK` | `false` | browser-use's telemetry, cloud sync and pypi.org version check stay off unless you export one as `true`. |
| `BENCHMARK_API_URL` | `http://127.0.0.1:8000` | Backend the web dev server proxies to. |
| `BENCHMARK_WEB_PORT` | `5180` | Port of the web dev server. |
| `CLERK_ISSUER_URL`, `CLERK_PUBLISHABLE_KEY`, `CLERK_JWKS_URL`, `VITE_CLERK_PUBLISHABLE_KEY` | unset | Only for Clerk sign-in. |

Browsers run headless unless you say otherwise. Every Chromium launch carries `--use-mock-keychain --password-store=basic`, so macOS never asks about the keychain. To see it, run `ps -axww -o pid,command | grep '[u]se-mock-keychain'` during a run.

## Clerk sign-in

By default the app is one always-signed-in local user. For real sign-in, have the backend verify Clerk tokens and the web app show the Clerk UI. In `.env`:

```dotenv
AUTH_MODE=clerk
CLERK_PUBLISHABLE_KEY=...         # or CLERK_ISSUER_URL=https://<your-clerk-domain>
VITE_CLERK_PUBLISHABLE_KEY=...    # the same publishable key, for the web UI
```

Restart `make dev` after changing them. In Clerk mode the daily quota defaults to 3 runs per user.

This path was only tested with mocks and a build, never against a live Clerk instance. The status and cancel routes take just the run id and don't check who owns the run, so don't host Clerk mode as it is. `@clerk/clerk-react` is deprecated upstream in favour of `@clerk/react`. The web UI can't tell which mode the backend runs in, so a local-mode UI against a Clerk backend shows a hint about the 401.

## OpenAI and Browserbase

`LLM_PROVIDER=openai` switches every model call back to the original gpt-4o setup: run `uv sync --extra openai`, then set `OPENAI_API_KEY`. `BENCHMARK_BROWSER_PROVIDER=browserbase` runs the live benchmark's browser in a Browserbase cloud session. Both exist in the code and are covered by unit tests only.
