# web

The React + Vite UI for the live benchmark. You paste a site's URL, pick one of the
generated tasks, and watch an agent try to do it. The result is pass, fail, too slow or
error, with the agent's final report, time, steps, tokens and cost.

It needs only the Python backend in `../server`. No hosted service, Clerk account or
Cloudflare is involved unless you opt into Clerk.

## Run it

```sh
cd web
nvm use            # Node 22 (.nvmrc); anything >= 20 works
npm ci
npm run dev        # http://localhost:5180 (http://127.0.0.1:5180 works too)
```

`npm run dev` proxies `/api/benchmark/*` to the backend. Start the backend first
(`../server`, default `http://127.0.0.1:8000`), otherwise the setup screen says it can't
reach the benchmark server.

The dev and preview servers listen on `127.0.0.1` and `::1` (loopback only, never the
network), so `localhost` and `127.0.0.1` both work whichever address `localhost` resolves
to on your machine; see `config/loopback.ts`.

Other scripts: `npm test` (vitest), `npm run build` (type-check, then `vite build` into
`dist/`), `npm run preview` (serves `dist/` with the same proxy).

## Configuration

Read from the shell or from the `.env` at the repository root, the same file the backend
reads. Only `VITE_*` values ever reach browser code.

| Variable | Default | What it does |
|---|---|---|
| `BENCHMARK_API_URL` | `http://127.0.0.1:8000` | Backend the dev and preview servers proxy to. |
| `BENCHMARK_WEB_PORT` | `5180` | Port of the dev and preview servers. A value that is not a port number is an error. |
| `VITE_CLERK_PUBLISHABLE_KEY` | unset | Set it to sign in with Clerk. Unset means local mode. |

### Local mode (default)

With no Clerk key the app is always signed in as one local user. There is no sign-in UI
and no `Authorization` header is sent, so run the backend with `AUTH_MODE=none`. This is
done at build time: `vite.config.ts` aliases `@clerk/clerk-react` to
`src/lib/auth-local.tsx`.

### Clerk mode (optional)

With `VITE_CLERK_PUBLISHABLE_KEY` set the real `@clerk/clerk-react` is used, the sign-in
modal appears, and the Clerk session token is sent as `Authorization: Bearer <token>`.
Run the backend with `AUTH_MODE=clerk` and its own Clerk settings. Changing the key needs
a dev-server restart or a rebuild.

## What the UI expects from the backend

| UI call | Backend route |
|---|---|
| `POST /api/benchmark/generate-tasks` `{url}` | `POST /benchmark/generate-tasks` |
| `GET /api/benchmark/quota` | `GET /benchmark/quota` |
| `GET /api/benchmark/health` | `GET /health` |
| `POST /api/benchmark/run` `{url, goal, label, viewport_width, viewport_height}` | `POST /benchmark/start` |
| `GET /api/benchmark/status/<run_id>` | `GET /benchmark/status/<run_id>` |
| `GET /api/benchmark/frame/<run_id>?seq=<n>` | `GET /benchmark/frame/<run_id>` |
| `POST /api/benchmark/cancel/<run_id>` | `POST /benchmark/cancel/<run_id>` |

The map lives in `config/vite-helpers.ts` (`API_ROUTES`) and is tested against a real Vite
server in `config/__tests__/dev-proxy.test.ts`.

While a run is going the status payload carries `run_phase` (`starting_browser`,
`opening_site`, `deciding` or `acting` with its `step`, `judging`), shown as a short label, and
`frame: {seq}`, and the preview loads `/api/benchmark/frame/<run_id>?seq=<n>`: the newest JPEG
of the agent's page, about one a second while it changes, scaled to fit the pane whole. The
browser is sized to the pane, but the backend keeps it at least 1024x720 and between 4:3 and 16:9.

The status payload, once the agent has finished (`analyzing` and `complete`), carries the
token counts plus two fields the UI shows as given:

- `cost_usd`: US dollars for the agent's tokens at the agent model's rates, or `null`.
  When it is `null` or missing the UI shows tokens only. The UI never prices tokens itself.
- `agent_model`: the model id, for example `claude-sonnet-5-5`.

`GET /health` is read once, when the visitor leaves the landing page (and again when a run
starts, if the backend had not answered yet). Two fields matter to the UI:

- `demo_mode` (bool): when `true` every screen shows a "Demo mode: canned runs, no real
  agent or API calls" banner, so a canned run is never mistaken for a real one.
- `timeout_s` (int): the backend's agent time limit (`BENCHMARK_TIMEOUT_S`). The UI polls a
  run for `timeout_s + 180` seconds (the 180 are for judging), at least 5 minutes, and for
  10 minutes when `timeout_s` is missing, before it reports "Lost connection".

While a run is in progress the Cost and Tokens cells show "—". Both are the backend's
numbers and arrive when the agent finishes; the UI makes no estimate.

An `error` reply carries the same `total_ms`, token counts, `cost_usd` and `agent_model`
when the agent ran before the run ended (a rejected API key, for example), and the UI
shows them. The Time clock counts only while the run is running: it stops when the
run ends however it ends, and then shows the backend's `total_ms` when there is one.

The quota response is `{remaining, resets_in, limit}`. A `limit` of `0`, or a `remaining`
that is `null`, missing or negative, means no limit: the UI shows no counter and never
blocks a run.

## Layout

```
config/            vite.config helpers (auth alias, port, API proxy, loopback listeners) and their tests
src/App.tsx        view state machine: home -> setup -> running
src/lib/api.ts     fetch wrappers for the routes above, health and the poll limit
src/lib/auth-*.ts  local auth shim and the mode switch
src/components/    views and overlays; components/__tests__ holds their tests
```

The "Rindler Benchmark" name and logo are kept because that is where this came from.
