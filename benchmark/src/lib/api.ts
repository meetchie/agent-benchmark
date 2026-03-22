import type { StatusResponse, Task } from "./types";

// Benchmark
export async function startBenchmark(
  url: string,
  goal: string,
  token: string
): Promise<{ run_id: string }> {
  const res = await fetch("/api/benchmark/run", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ url, goal }),
  });
  if (res.status === 429) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail?.error || "Too many runs in progress. Wait for one to finish.");
  }
  if (res.status === 401) {
    throw new Error("AUTH_EXPIRED");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to start benchmark: ${text}`);
  }
  return res.json();
}

export async function pollStatus(runId: string): Promise<StatusResponse> {
  const res = await fetch(`/api/benchmark/status/${runId}`);
  if (!res.ok) throw new Error(`Status poll failed: ${res.status}`);
  return res.json();
}

export async function generateTasks(
  url: string
): Promise<{ tasks: Task[] }> {
  const res = await fetch("/api/benchmark/generate-tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail?.error || data.detail || "Failed to generate tasks");
  }
  return res.json();
}
