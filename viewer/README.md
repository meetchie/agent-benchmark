# Arena log viewer

A small static web app that shows the archived March 2026 arena logs from the
Rindler vs browser-use benchmark. It only reads files. It does not start agents,
call any API or need any key.

## What it shows

**Results** (`#results`, the default page) is the headline comparison for one task:
`vhlistings_bundle_promo` on vhlistings.com (add three items to the cart, apply the
promo code `SPRING`, reach checkout, stop before payment), 60 runs per arm.
The numbers on this page, and the failure funnel, are hard-coded in
`src/components/ResultsPage.tsx`. They are not computed from the logs at runtime. A
caveats panel (`src/components/CaveatsPanel.tsx`) sits directly under the headline, so a
screenshot of it carries them: hand-mapped against unmapped, Rindler wording in both
prompts, different browsers and step caps, the gpt-4o-mini judge, one site and one
night, and the hand-written funnel. The same list, with detail, is under "Read the
comparison with these caveats" below.

**Log Viewer** (`#logs`, also embedded at the bottom of Results) parses any run log
and shows the judge verdict, duration, cost and tokens, the goal the agent was given,
a per-step timeline, a cumulative cost chart, and simple friction flags (repeated
observations, long steps, repeated actions, and steps whose tool call failed, which
newer logs mark with `was_error` in the telemetry). You can pick one of the bundled runs or
drop in any arena-format `.log` file.

## Run it

Needs Node 20 or newer.

```bash
npm ci
npm run dev        # http://localhost:5173 (http://127.0.0.1:5173 works too)
npm run build      # type-check (tsc) and bundle to dist/
npm run preview    # serve the built dist/ locally
npm test           # vitest: the log parser, the friction rules, the caveats panel
```

`vite --port <n>` changes the port. The dev and preview servers listen on `127.0.0.1` and
`::1` (this machine only), so `localhost` and `127.0.0.1` both work (`vite-loopback.ts`). The app fetches `/logs/...` from the site root,
so serve `dist/` from the root of a host, not from a sub-path.

## The logs

`public/logs/` holds 128 run logs and `manifest.json`, which lists them. They are
unchanged from the original repo. The manifest matches the files on disk exactly.

| Arm | Logs | Notes |
|---|---|---|
| browser-use | 60 | `arena_browseruse_vhlistings_20260331_005641.log` to `_061032.log`, all `vhlistings_bundle_promo` |
| Rindler | 68 | 66 `vhlistings_bundle_promo` plus 2 `vhlistings_product_attribute_search` |

Source: the Rindler arena (the `clean-room` arena in the original monorepo), run on
2026-03-31. File names carry the runner's local time. Each log is plain text: a header
(agent, scenario, goal, duration, judge verdict, token burn, cost) followed by a JSON
list of telemetry events. There are no screenshots and no page content, only hashes of
observations.

The headline uses all 60 browser-use logs and the last 60 Rindler `vhlistings_bundle_promo`
logs of that night (`arena_rindler_vhlistings_20260331_002827.log` to `_032405.log`).
The other eight Rindler logs are in the viewer but not in the headline: four earlier
runs from 00:11 to 00:24 on 03-31 (before the final mapping change that night), two
03-27 bundle runs, and the two attribute-search runs.

Recomputed from the logs (the judge verdict is what counts as pass):

| | Rindler (60) | browser-use (60) |
|---|---|---|
| Pass | 59 (98.3%) | 1 (1.7%) |
| Mean cost per run | $0.1366 | $0.713 |
| Mean duration | 70.1 s | 307.3 s |
| Mean tokens | 52,856 | 272,377 |
| Mean steps (`step_end` events) | 14.1 | 28.5 |

Costs in the logs are token counts priced at gpt-4o list rates ($2.50 and $10 per
million input and output tokens), not billed amounts. The one Rindler failure is
`arena_rindler_vhlistings_20260331_024903.log`. The one browser-use pass is
`arena_browseruse_vhlistings_20260331_023009.log`.

`Agent Reported Success: True` appears in every log of both arms. It only means the
agent run finished without raising, so ignore it. The Status card uses the judge verdict.

## Read the comparison with these caveats

- **Mapped against unmapped.** Rindler drives a site through a hand-written mapping
  (25 versions, tuned on this exact site and task, and its own cleanup step is what removes
  the VIP Membership). browser-use had no mapping.
- **Prompts use Rindler vocabulary.** Both arms received the same task text, which says
  things like "Start a session" and "view_cart".
- **Different setups.** browser-use ran on a Browserbase cloud browser with a 30-step cap.
  Rindler ran on server-local Playwright with a 25-step cap. Both used gpt-4o.
- **Judge.** A gpt-4o-mini judge reads the agent's own final report. The single browser-use
  pass shows the judge can err in either direction. The "no VIP Membership" criterion is
  checked by the judge but is not stated in the prompt.
- **One site, one task, one night.** 60 runs per arm against a live third-party Shopify
  store (with a Klaviyo popup and an asynchronous checkout) on 2026-03-31. The store has
  changed since, so these runs cannot be reproduced against it.
- **The funnel is hand-curated.** The judge criteria in the logs reproduce the stages
  17 (checkout), 8 (promo applied) and 1 (no VIP) exactly. The "added 3 items" stage is 23
  by the judge's criterion against 25 on the page. The "dark pattern" labels and the reasons
  for each drop are the original authors' interpretation, not derived from the logs.
- **Session replay links.** browser-use logs include a Browserbase session id. The replays
  belonged to the original Rindler account and cannot be opened by anyone else.

## Changes from the original viewer

- Removed the Cloudflare Pages Functions, `wrangler.toml` and the related dependencies, and
  moved from pnpm in a monorepo to a plain npm project with its own lockfile.
- Rindler runs were labelled "BU" in the run picker. They now show "RINDLER".
- Corrected the Results page where the logs contradict it. Mean tokens for Rindler is 52,856
  (was 52,855). Mean steps for Rindler is 14.1 (was 15.1, a value the page never displayed).
  The task description said agents complete a real purchase, but the prompt tells them to
  stop after applying the promo code.
- The session replay panel shows the session id as text instead of a link.
- The Results page now carries a caveats panel under the headline and a note under the funnel
  (the archived numbers are unchanged).
- The friction panel counts a step whose telemetry says `was_error: true` as friction. It used
  to ignore the field and say "No friction detected" for a run whose `remove_from_cart` failed.
  66 of the 128 archived logs (all of them Rindler runs) have such steps, mostly failed
  `add_to_cart` calls, so they now list them.
- The dev and preview servers answer on `127.0.0.1` and `::1`, and there is a small vitest
  suite (`npm test`).
