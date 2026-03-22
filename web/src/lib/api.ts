import type { StatusResponse } from "./types";

export async function startBenchmark(
  url: string,
  goal: string
): Promise<{ run_id: string }> {
  const res = await fetch("/api/benchmark/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, goal }),
  });
  if (!res.ok) {
    throw new Error("Failed to start benchmark");
  }
  return res.json();
}

export async function pollStatus(runId: string): Promise<StatusResponse> {
  if (!/^[a-zA-Z0-9_-]+$/.test(runId)) {
    throw new Error("Invalid run ID format");
  }
  const res = await fetch(`/api/benchmark/status/${runId}`);
  if (!res.ok) {
    throw new Error("Status poll failed");
  }
  return res.json();
}
