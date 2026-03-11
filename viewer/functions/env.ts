// Shared environment type for all Cloudflare Pages Functions.
// Add bindings here as you enable them in wrangler.toml / Cloudflare dashboard.

import type { BrowserWorker } from "@cloudflare/puppeteer";

export interface Env {
  // --- Browser Rendering ---
  BROWSER: BrowserWorker;

  // --- Secrets (set via .dev.vars locally, Cloudflare dashboard in prod) ---
  // OPENAI_API_KEY: string;

  // --- Python Agent Container ---
  // TODO: Set this to your container's base URL once deployed (e.g. https://agents.example.invalid)
  // Set via: wrangler pages secret put AGENT_CONTAINER_URL
  AGENT_CONTAINER_URL: string;

  // --- Future bindings (uncomment as needed) ---
  // DB: D1Database;
  // KV: KVNamespace;
  // BUCKET: R2Bucket;

  // --- Cloudflare Pages built-in ---
  ASSETS: Fetcher;
}
