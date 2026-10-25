import { afterEach, describe, expect, it, vi } from "vitest";
import {
  UNKNOWN_QUOTA,
  cancelBenchmark,
  fetchHealth,
  fetchQuota,
  generateTasks,
  normalizeHealth,
  normalizeQuota,
  pollLimitSeconds,
  startBenchmark,
} from "../api";

describe("generateTasks", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends bearer auth and normalizes task ids to strings", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          tasks: [{ id: 1, label: "Add item", goal: "Add an item to cart" }],
        }),
        { status: 200 }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await generateTasks("https://example.com", "test-token");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/benchmark/generate-tasks",
      expect.objectContaining({
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer test-token",
        },
        body: JSON.stringify({ url: "https://example.com" }),
      })
    );
    expect(result.tasks).toEqual([
      { id: "1", label: "Add item", goal: "Add an item to cart" },
    ]);
  });

  it("maps unauthorized responses to AUTH_EXPIRED", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));

    await expect(generateTasks("https://example.com", "expired-token")).rejects.toThrow(
      "AUTH_EXPIRED"
    );
  });
});

describe("cancelBenchmark", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts to the run cancel endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await cancelBenchmark("run-123");

    expect(fetchMock).toHaveBeenCalledWith("/api/benchmark/cancel/run-123", { method: "POST" });
  });

  it("swallows cancel request failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));

    await expect(cancelBenchmark("run-123")).resolves.toBeUndefined();
  });
});

function headersOf(fetchMock: ReturnType<typeof vi.fn>): Record<string, string> {
  return fetchMock.mock.calls[0][1].headers;
}

describe("local mode (no token)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends no Authorization header when generating tasks", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ tasks: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await generateTasks("https://example.com", null);

    expect(headersOf(fetchMock)).toEqual({ "Content-Type": "application/json" });
  });

  it("sends no Authorization header when starting a run", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ run_id: "r1" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(startBenchmark("https://example.com", "goal", "label", null)).resolves.toEqual({ run_id: "r1" });

    expect(headersOf(fetchMock)).toEqual({ "Content-Type": "application/json" });
  });

  it("sends no Authorization header when fetching the quota", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ remaining: 3, resets_in: 0, limit: 3 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchQuota(null);

    expect(headersOf(fetchMock)).toEqual({});
  });

  it("still sends the bearer token when there is one", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ run_id: "r1" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await startBenchmark("https://example.com", "goal", "label", "tok-1");

    expect(headersOf(fetchMock).Authorization).toBe("Bearer tok-1");
  });
});

describe("backend unreachable", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("explains an empty 500 from the dev proxy when generating tasks", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 500 })));

    await expect(generateTasks("https://example.com", null)).rejects.toThrow(/Can't reach the benchmark server/);
  });

  it("explains an empty 500 from the dev proxy when starting a run", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 500 })));

    await expect(startBenchmark("https://example.com", "g", "l", null)).rejects.toThrow(/Can't reach the benchmark server/);
  });

  it("keeps the backend's own error text when it sends one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "That site does not look like a store." }), { status: 422 }))
    );

    await expect(generateTasks("https://example.com", null)).rejects.toThrow("That site does not look like a store.");
  });

  it("shows the sentence the backend gives for a refused URL when starting a run", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Invalid or disallowed URL: http://127.0.0.1:8000" }), { status: 422 }))
    );

    await expect(startBenchmark("http://127.0.0.1:8000", "g", "l", null)).rejects.toThrow(
      new Error("Invalid or disallowed URL: http://127.0.0.1:8000")
    );
  });

  it("keeps the raw text for an error that is not a detail sentence when starting a run", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("boom", { status: 500 })));

    await expect(startBenchmark("https://example.com", "g", "l", null)).rejects.toThrow("Failed to start benchmark: boom");
  });

  it("treats a failed quota request as an unknown quota", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 500 })));
    await expect(fetchQuota(null)).resolves.toEqual(UNKNOWN_QUOTA);

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    await expect(fetchQuota(null)).resolves.toEqual(UNKNOWN_QUOTA);
  });
});

describe("normalizeQuota", () => {
  it("passes a normal daily allowance through", () => {
    expect(normalizeQuota({ remaining: 2, resets_in: 3600, limit: 3 })).toEqual({ remaining: 2, resets_in: 3600, limit: 3 });
  });

  it("keeps an exhausted allowance exhausted", () => {
    expect(normalizeQuota({ remaining: 0, resets_in: 120, limit: 3 })).toEqual({ remaining: 0, resets_in: 120, limit: 3 });
  });

  it("reads a limit of 0 as unlimited", () => {
    expect(normalizeQuota({ remaining: 0, resets_in: 0, limit: 0 })).toEqual({ remaining: null, resets_in: 0, limit: null });
  });

  it("reads a missing, null or negative remaining as unlimited", () => {
    expect(normalizeQuota({ resets_in: 0, limit: 3 })).toEqual({ remaining: null, resets_in: 0, limit: null });
    expect(normalizeQuota({ remaining: null, limit: null })).toEqual({ remaining: null, resets_in: 0, limit: null });
    expect(normalizeQuota({ remaining: -1, limit: 3 })).toEqual({ remaining: null, resets_in: 0, limit: null });
  });

  it("copes with a non-object body", () => {
    expect(normalizeQuota(null)).toEqual(UNKNOWN_QUOTA);
    expect(normalizeQuota(undefined)).toEqual(UNKNOWN_QUOTA);
  });
});

describe("normalizeHealth", () => {
  it("reads demo_mode and timeout_s from /health", () => {
    expect(normalizeHealth({ ok: true, demo_mode: true, timeout_s: 180, provider: "anthropic" })).toEqual({
      demo_mode: true,
      timeout_s: 180,
    });
  });

  it("counts demo_mode only when it is exactly true", () => {
    expect(normalizeHealth({ demo_mode: false })?.demo_mode).toBe(false);
    expect(normalizeHealth({ demo_mode: "true" })?.demo_mode).toBe(false);
    expect(normalizeHealth({})?.demo_mode).toBe(false);
  });

  it("leaves timeout_s null when an older backend does not send it or sends nonsense", () => {
    for (const bad of [undefined, null, 0, -5, "180", Number.NaN]) {
      expect(normalizeHealth({ demo_mode: false, timeout_s: bad })?.timeout_s).toBeNull();
    }
  });

  it("is null for a body that is not an object", () => {
    expect(normalizeHealth(null)).toBeNull();
    expect(normalizeHealth("ok")).toBeNull();
  });
});

describe("fetchHealth", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("asks /api/benchmark/health without credentials", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ ok: true, demo_mode: true, timeout_s: 600 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    expect(await fetchHealth()).toEqual({ demo_mode: true, timeout_s: 600 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]).toEqual(["/api/benchmark/health"]);
  });

  it("is null when the backend is down (proxy 500), errors, or returns junk", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 500 })));
    expect(await fetchHealth()).toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    expect(await fetchHealth()).toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not json", { status: 200 })));
    expect(await fetchHealth()).toBeNull();
  });
});

describe("pollLimitSeconds", () => {
  it("is the agent time limit plus 180 s for judging", () => {
    expect(pollLimitSeconds(600)).toBe(780);
    expect(pollLimitSeconds(1800)).toBe(1980);
  });

  it("is never below 5 minutes", () => {
    expect(pollLimitSeconds(30)).toBe(300);
    expect(pollLimitSeconds(120)).toBe(300);
    // The default limit (180 s) gives 360 s.
    expect(pollLimitSeconds(180)).toBe(360);
  });

  it("is 10 minutes when the backend's limit is unknown", () => {
    for (const unknown of [null, undefined, 0, -1, Number.NaN]) {
      expect(pollLimitSeconds(unknown)).toBe(600);
    }
  });
});
