import { afterEach, describe, expect, it, vi } from "vitest";
import { cancelBenchmark, generateTasks } from "../api";

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
