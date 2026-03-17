import { describe, it, expect, vi, beforeEach } from "vitest";
import { startBenchmark, pollStatus } from "./api";

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

beforeEach(() => {
  mockFetch.mockReset();
});

// ---------------------------------------------------------------------------
// startBenchmark
// ---------------------------------------------------------------------------
describe("startBenchmark", () => {
  it("sends correct request and returns run_id", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ run_id: "abc-123" }),
    });

    const result = await startBenchmark("https://example.com", "test goal");

    expect(mockFetch).toHaveBeenCalledWith("/api/benchmark/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: "https://example.com", goal: "test goal" }),
    });
    expect(result.run_id).toBe("abc-123");
  });

  it("throws generic error on failure without leaking response body", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      text: () => Promise.resolve("Internal server error: connection to DB failed at 10.0.0.5:5432"),
    });

    await expect(startBenchmark("https://example.com", "goal")).rejects.toThrow(
      "Failed to start benchmark"
    );
    // Should NOT contain internal details
    try {
      await startBenchmark("https://example.com", "goal");
    } catch (e) {
      expect((e as Error).message).not.toContain("10.0.0.5");
      expect((e as Error).message).not.toContain("DB");
    }
  });
});

// ---------------------------------------------------------------------------
// pollStatus — runId validation
// ---------------------------------------------------------------------------
describe("pollStatus", () => {
  it("accepts valid alphanumeric runId", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: "running" }),
    });

    const result = await pollStatus("abc-123_def");
    expect(result.status).toBe("running");
    expect(mockFetch).toHaveBeenCalledWith("/api/benchmark/status/abc-123_def");
  });

  it("rejects runId with path traversal", async () => {
    await expect(pollStatus("../../etc/passwd")).rejects.toThrow("Invalid run ID format");
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("rejects runId with slashes", async () => {
    await expect(pollStatus("foo/bar")).rejects.toThrow("Invalid run ID format");
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("rejects runId with special characters", async () => {
    await expect(pollStatus("foo;ls")).rejects.toThrow("Invalid run ID format");
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("rejects runId with spaces", async () => {
    await expect(pollStatus("foo bar")).rejects.toThrow("Invalid run ID format");
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("rejects empty runId", async () => {
    await expect(pollStatus("")).rejects.toThrow("Invalid run ID format");
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("throws generic error on non-ok response", async () => {
    mockFetch.mockResolvedValue({ ok: false, status: 404 });

    await expect(pollStatus("valid-id")).rejects.toThrow("Status poll failed");
    // Should NOT contain the status code
    try {
      await pollStatus("valid-id");
    } catch (e) {
      expect((e as Error).message).toBe("Status poll failed");
    }
  });
});
