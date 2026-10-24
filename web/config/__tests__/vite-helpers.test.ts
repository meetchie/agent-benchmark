// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  API_ROUTES,
  DEFAULT_API_URL,
  DEFAULT_WEB_PORT,
  apiProxy,
  apiUrl,
  authAlias,
  clerkEnabled,
  devPort,
} from "../vite-helpers";

describe("clerkEnabled", () => {
  it("is false when the publishable key is unset, empty or blank", () => {
    expect(clerkEnabled({})).toBe(false);
    expect(clerkEnabled({ VITE_CLERK_PUBLISHABLE_KEY: "" })).toBe(false);
    expect(clerkEnabled({ VITE_CLERK_PUBLISHABLE_KEY: "   " })).toBe(false);
  });

  it("is true when a key is set", () => {
    expect(clerkEnabled({ VITE_CLERK_PUBLISHABLE_KEY: "pk_test_not-a-real-key" })).toBe(true);
  });
});

describe("authAlias", () => {
  it("points @clerk/clerk-react at the local shim when no key is set", () => {
    const alias = authAlias({});
    expect(Object.keys(alias)).toEqual(["@clerk/clerk-react"]);
    expect(alias["@clerk/clerk-react"]).toMatch(/src\/lib\/auth-local\.tsx$/);
  });

  it("leaves the real Clerk package alone when a key is set", () => {
    expect(authAlias({ VITE_CLERK_PUBLISHABLE_KEY: "pk_test_not-a-real-key" })).toEqual({});
  });
});

describe("apiUrl", () => {
  it("defaults to the local backend", () => {
    expect(apiUrl({})).toBe("http://127.0.0.1:8000");
    expect(DEFAULT_API_URL).toBe("http://127.0.0.1:8000");
    expect(apiUrl({ BENCHMARK_API_URL: "  " })).toBe("http://127.0.0.1:8000");
  });

  it("reads BENCHMARK_API_URL and drops trailing slashes", () => {
    expect(apiUrl({ BENCHMARK_API_URL: "http://localhost:9000" })).toBe("http://localhost:9000");
    expect(apiUrl({ BENCHMARK_API_URL: "http://localhost:9000//" })).toBe("http://localhost:9000");
  });
});

describe("devPort", () => {
  it("defaults to 5180", () => {
    expect(devPort({})).toBe(5180);
    expect(DEFAULT_WEB_PORT).toBe(5180);
    expect(devPort({ BENCHMARK_WEB_PORT: "" })).toBe(5180);
  });

  it("reads BENCHMARK_WEB_PORT", () => {
    expect(devPort({ BENCHMARK_WEB_PORT: "18102" })).toBe(18102);
  });

  it("rejects anything that is not a port number rather than silently using the default", () => {
    for (const bad of ["abc", "0", "70000", "51.5", "-1"]) {
      expect(() => devPort({ BENCHMARK_WEB_PORT: bad })).toThrow(/BENCHMARK_WEB_PORT/);
    }
  });
});

describe("apiProxy", () => {
  const proxy = apiProxy("http://127.0.0.1:8123");
  const rewrite = (context: string, path: string) => {
    const fn = proxy[context].rewrite;
    if (!fn) throw new Error(`no rewrite for ${context}`);
    return fn(path);
  };

  it("proxies exactly the five API routes the Cloudflare functions covered", () => {
    expect(Object.keys(proxy).sort()).toEqual(
      [
        "/api/benchmark/cancel",
        "/api/benchmark/generate-tasks",
        "/api/benchmark/quota",
        "/api/benchmark/run",
        "/api/benchmark/status",
      ].sort()
    );
    expect(API_ROUTES).toHaveLength(5);
  });

  it("sends every route to the configured backend", () => {
    for (const options of Object.values(proxy)) {
      expect(options.target).toBe("http://127.0.0.1:8123");
      expect(options.changeOrigin).toBe(true);
    }
  });

  it("maps /api/benchmark/run to the backend's /benchmark/start", () => {
    expect(rewrite("/api/benchmark/run", "/api/benchmark/run")).toBe("/benchmark/start");
  });

  it("maps generate-tasks and quota to their backend counterparts", () => {
    expect(rewrite("/api/benchmark/generate-tasks", "/api/benchmark/generate-tasks")).toBe("/benchmark/generate-tasks");
    expect(rewrite("/api/benchmark/quota", "/api/benchmark/quota")).toBe("/benchmark/quota");
  });

  it("keeps the run id when mapping status and cancel", () => {
    expect(rewrite("/api/benchmark/status", "/api/benchmark/status/3f2a-run")).toBe("/benchmark/status/3f2a-run");
    expect(rewrite("/api/benchmark/cancel", "/api/benchmark/cancel/3f2a-run")).toBe("/benchmark/cancel/3f2a-run");
  });
});
