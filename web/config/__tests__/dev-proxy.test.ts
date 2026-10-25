// @vitest-environment node
//
// End to end: a real Vite dev server with our proxy table in front of a stub
// backend. Checks the method, the rewritten path and the body that actually
// arrive, which the pure route-map tests cannot.
import { createServer as createHttpServer } from "node:http";
import type { AddressInfo } from "node:net";
import { createServer, type ViteDevServer } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { apiProxy } from "../vite-helpers";

interface Seen {
  method?: string;
  url?: string;
  body: string;
  authorization?: string;
}

let backend: ReturnType<typeof createHttpServer>;
let vite: ViteDevServer;
let base: string;
const seen: Seen[] = [];

beforeAll(async () => {
  backend = createHttpServer((req, res) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      seen.push({ method: req.method, url: req.url, body, authorization: req.headers.authorization });
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ ok: true }));
    });
  });
  await new Promise<void>((resolve) => backend.listen(0, "127.0.0.1", resolve));
  const backendPort = (backend.address() as AddressInfo).port;

  vite = await createServer({
    configFile: false,
    root: new URL("../..", import.meta.url).pathname,
    logLevel: "silent",
    server: { port: 0, host: "127.0.0.1", proxy: apiProxy(`http://127.0.0.1:${backendPort}`) },
  });
  await vite.listen();
  base = `http://127.0.0.1:${(vite.httpServer!.address() as AddressInfo).port}`;
});

afterAll(async () => {
  await vite?.close();
  await new Promise<void>((resolve) => backend?.close(() => resolve()));
});

async function call(path: string, init?: RequestInit): Promise<Seen> {
  seen.length = 0;
  const res = await fetch(base + path, init);
  expect(res.status).toBe(200);
  expect(seen).toHaveLength(1);
  return seen[0];
}

describe("vite dev proxy to the backend", () => {
  it("POST /api/benchmark/run reaches POST /benchmark/start with its body", async () => {
    const got = await call("/api/benchmark/run", { method: "POST", body: JSON.stringify({ url: "https://x.example", goal: "g" }) });
    expect(got.method).toBe("POST");
    expect(got.url).toBe("/benchmark/start");
    expect(JSON.parse(got.body)).toEqual({ url: "https://x.example", goal: "g" });
  });

  it("POST /api/benchmark/generate-tasks reaches /benchmark/generate-tasks", async () => {
    const got = await call("/api/benchmark/generate-tasks", { method: "POST", body: "{}" });
    expect(got.method).toBe("POST");
    expect(got.url).toBe("/benchmark/generate-tasks");
  });

  it("GET /api/benchmark/quota reaches /benchmark/quota", async () => {
    const got = await call("/api/benchmark/quota");
    expect(got.method).toBe("GET");
    expect(got.url).toBe("/benchmark/quota");
  });

  it("GET /api/benchmark/health reaches /health", async () => {
    const got = await call("/api/benchmark/health");
    expect(got.method).toBe("GET");
    expect(got.url).toBe("/health");
  });

  it("GET /api/benchmark/status/<id> keeps the id", async () => {
    const got = await call("/api/benchmark/status/abc-123");
    expect(got.method).toBe("GET");
    expect(got.url).toBe("/benchmark/status/abc-123");
  });

  it("POST /api/benchmark/cancel/<id> keeps the id", async () => {
    const got = await call("/api/benchmark/cancel/abc-123", { method: "POST" });
    expect(got.method).toBe("POST");
    expect(got.url).toBe("/benchmark/cancel/abc-123");
  });

  it("forwards an Authorization header when the browser sends one and none when it does not", async () => {
    expect((await call("/api/benchmark/quota", { headers: { Authorization: "Bearer tok" } })).authorization).toBe("Bearer tok");
    expect((await call("/api/benchmark/quota")).authorization).toBeUndefined();
  });
});
