// Pure helpers for vite.config.ts and vitest.config.ts, kept apart so they
// can be unit tested (config/__tests__/vite-helpers.test.ts).
import { fileURLToPath } from "node:url";
import type { ProxyOptions } from "vite";

export type Env = Record<string, string | undefined>;

/** Repository root. The one .env lives here, shared with the backend. */
export const repoRoot = fileURLToPath(new URL("../..", import.meta.url));

/** Env prefixes read for build config. Only VITE_ is ever exposed to browser code. */
export const ENV_PREFIXES = ["VITE_", "BENCHMARK_"];

/** True when a Clerk publishable key is configured. */
export function clerkEnabled(env: Env): boolean {
  return Boolean(env.VITE_CLERK_PUBLISHABLE_KEY?.trim());
}

/**
 * Without a Clerk key every import of "@clerk/clerk-react" resolves to the
 * local always-signed-in shim, so the app needs no Clerk account. With a key
 * the real package is used.
 */
export function authAlias(env: Env): Record<string, string> {
  if (clerkEnabled(env)) return {};
  return {
    "@clerk/clerk-react": fileURLToPath(new URL("../src/lib/auth-local.tsx", import.meta.url)),
  };
}

// Dev and preview server: port and API proxy

export const DEFAULT_API_URL = "http://127.0.0.1:8000";
export const DEFAULT_WEB_PORT = 5180;

/** Backend base URL: BENCHMARK_API_URL, without a trailing slash. */
export function apiUrl(env: Env): string {
  const raw = env.BENCHMARK_API_URL?.trim();
  return (raw || DEFAULT_API_URL).replace(/\/+$/, "");
}

/** Dev server port: BENCHMARK_WEB_PORT. A typo fails loudly instead of silently using the default. */
export function devPort(env: Env): number {
  const raw = env.BENCHMARK_WEB_PORT?.trim();
  if (!raw) return DEFAULT_WEB_PORT;
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`BENCHMARK_WEB_PORT must be a port number (1-65535), got "${raw}"`);
  }
  return port;
}

/**
 * Browser path -> backend path. The UI calls /api/benchmark/*; the Python server serves the same
 * routes under /benchmark/*.
 *   fixed: any request to the path goes to one backend path (POST run -> /benchmark/start)
 *   prefix: only the prefix is swapped, so /status/<id> keeps its id
 */
export const API_ROUTES: ReadonlyArray<{ from: string; to: string; kind: "fixed" | "prefix" }> = [
  { from: "/api/benchmark/run", to: "/benchmark/start", kind: "fixed" },
  { from: "/api/benchmark/generate-tasks", to: "/benchmark/generate-tasks", kind: "fixed" },
  { from: "/api/benchmark/quota", to: "/benchmark/quota", kind: "fixed" },
  { from: "/api/benchmark/health", to: "/health", kind: "fixed" },
  { from: "/api/benchmark/status", to: "/benchmark/status", kind: "prefix" },
  { from: "/api/benchmark/frame", to: "/benchmark/frame", kind: "prefix" },
  { from: "/api/benchmark/cancel", to: "/benchmark/cancel", kind: "prefix" },
];

/** Vite proxy table sending the UI's API calls to the backend at `target`. */
export function apiProxy(target: string): Record<string, ProxyOptions> {
  return Object.fromEntries(
    API_ROUTES.map(({ from, to, kind }) => [
      from,
      {
        target,
        changeOrigin: true,
        rewrite: kind === "fixed" ? () => to : (path: string) => path.replace(from, to),
      } satisfies ProxyOptions,
    ])
  );
}
