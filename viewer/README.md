# Rindler Arena Log Analyzer — Shipt Demo

## What this is

A Vite + React dashboard for visualizing results from automated browser-agent benchmark runs against Shipt.com. It is a **log viewer and analytics tool**, not a live agent runner — no agents are started from the UI. The dashboard compares two configurations side-by-side: **BrowserUse (raw)** and **BrowserUse + MCP** (augmented with Rindler tooling), surfacing pass rates, token costs, friction points, and step-by-step timelines from pre-recorded arena run logs.

---

## Quick Start

```bash
cd packages/shipt-demo
pnpm install
pnpm dev
```

No environment variables are required for log viewing. Open `http://localhost:5173` and navigate via the hash-based router.

---

## Scripts

| Script | Description |
|---|---|
| `pnpm dev` | Vite dev server (UI only, no Cloudflare Functions) |
| `pnpm dev:full` | Wrangler Pages dev with Functions wired in |
| `pnpm build` | Type-check and produce `dist/` for deployment |
| `pnpm preview` | Serve the built `dist/` through Wrangler locally |
| `pnpm deploy` | Deploy to Cloudflare Pages |

---

## Pages

### Log Viewer (`#viewer`)

Load any `.log` file from the bundled set or drag-and-drop a custom file. For each run the viewer shows:

- **Summary cards** — pass/fail, total steps, token usage, wall-clock duration
- **Goal panel** — the natural-language task the agent was given
- **Friction analysis** — categorized obstacles the agent encountered
- **Cost chart** — per-step token cost breakdown (Recharts bar chart)
- **Step timeline** — ordered list of agent actions with status indicators

### Trends (`#trends`)

Cross-run comparison across all 38 bundled logs:

- Pass rates by configuration (BrowserUse raw vs. BrowserUse + MCP)
- Aggregate and per-run cost comparison
- Failure classification breakdown

---

## Log Data

Logs live in `public/logs/` and are referenced by `public/logs/manifest.json`. Files follow the naming convention:

```
arena_browseruse[_mcp]_shipt_YYYYMMDD_HHmmss.log
```

- `arena_browseruse_shipt_*` — 19 raw BrowserUse runs
- `arena_browseruse_mcp_shipt_*` — 19 BrowserUse + MCP runs

You can also drag-and-drop any arena-format `.log` file onto the Log Viewer page to inspect it without modifying the bundle.

---

## Cloudflare Functions

API routes are scaffolded under `functions/api/` for future use but are **not currently wired to the UI**:

| Endpoint | File |
|---|---|
| `GET /api/health` | `functions/api/health.ts` |
| `POST /api/agent/run` | `functions/api/agent/run.ts` |
| `GET /api/agent/status` | `functions/api/agent/status.ts` |
| `POST /api/browser/scrape` | `functions/api/browser/scrape.ts` |
| `POST /api/browser/screenshot` | `functions/api/browser/screenshot.ts` |

Run `pnpm dev:full` to serve them locally via Wrangler.

---

## Tech Stack

| Layer | Library / Tool |
|---|---|
| UI framework | React 19 |
| Build tool | Vite 6 |
| Charts | Recharts 3 |
| Hosting / Functions | Cloudflare Pages + Workers |
| Language | TypeScript 5 |
