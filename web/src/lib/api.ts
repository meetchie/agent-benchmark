import type { Health, Quota, StatusResponse, Task } from "./types";

type GeneratedTask = Omit<Task, "id"> & { id: string | number };

/**
 * Authorization header for a Clerk session token. In local mode there is no
 * token (see auth-local.tsx) and the header is omitted entirely.
 */
function authHeaders(token: string | null): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** True when the dev proxy or a gateway answered because the backend is down. */
function isBackendUnreachable(status: number): boolean {
  return status === 502 || status === 503 || status === 504;
}

const UNREACHABLE_MESSAGE =
  "Can't reach the benchmark server. Start the backend, then try again.";

/** Quota used when the backend does not answer: no limit is shown or enforced client-side. */
export const UNKNOWN_QUOTA: Quota = { remaining: null, resets_in: 0, limit: null };

/**
 * Normalise a /health body. demo_mode counts only when it is exactly true;
 * timeout_s only when it is a positive finite number (an older backend that
 * does not send it leaves it null). null when the body is not an object.
 */
export function normalizeHealth(raw: unknown): Health | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const t = r.timeout_s;
  return {
    demo_mode: r.demo_mode === true,
    timeout_s: typeof t === "number" && Number.isFinite(t) && t > 0 ? t : null,
  };
}

/** GET /health through the dev proxy. Never throws; null when the backend does not answer. */
export async function fetchHealth(): Promise<Health | null> {
  try {
    const res = await fetch("/api/benchmark/health");
    if (!res.ok) return null;
    return normalizeHealth(await res.json());
  } catch {
    return null;
  }
}

/** Seconds the UI waits for a run, once started, before it reports a lost connection. */
export const MIN_POLL_SECONDS = 300;
/** The judge runs after the agent's time limit; give it this long on top. */
export const JUDGE_ALLOWANCE_SECONDS = 180;
/** Used when the backend's time limit is unknown. */
export const UNKNOWN_TIMEOUT_POLL_SECONDS = 600;

/**
 * How long to keep polling a run: the backend's agent time limit plus the
 * judging allowance, at least 5 minutes, and 10 minutes when the limit is not
 * known. Raising BENCHMARK_TIMEOUT_S on the server therefore raises this too.
 */
export function pollLimitSeconds(timeoutS: number | null | undefined): number {
  if (typeof timeoutS !== "number" || !Number.isFinite(timeoutS) || timeoutS <= 0) {
    return UNKNOWN_TIMEOUT_POLL_SECONDS;
  }
  return Math.max(MIN_POLL_SECONDS, Math.ceil(timeoutS) + JUDGE_ALLOWANCE_SECONDS);
}

// Benchmark
export async function startBenchmark(
  url: string,
  goal: string,
  label: string,
  token: string | null,
  viewport?: { width: number; height: number }
): Promise<{ run_id: string }> {
  const res = await fetch("/api/benchmark/run", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(token),
    },
    body: JSON.stringify({ url, goal, label, ...(viewport && { viewport_width: viewport.width, viewport_height: viewport.height }) }),
  });
  if (res.status === 429) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail?.error || "Too many runs in progress. Wait for one to finish.");
  }
  if (res.status === 401) {
    throw new Error("AUTH_EXPIRED");
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    // The Vite dev proxy answers 500 with an empty body when nothing is listening.
    if (!text.trim() && (res.status === 500 || isBackendUnreachable(res.status))) {
      throw new Error(UNREACHABLE_MESSAGE);
    }
    // A refused URL comes back as { detail: "..." }; show the sentence, as generate-tasks does.
    let detail: unknown;
    try {
      detail = JSON.parse(text).detail;
    } catch {
      detail = undefined;
    }
    if (typeof detail === "string" && detail.trim()) throw new Error(detail);
    throw new Error(`Failed to start benchmark: ${text}`);
  }
  return res.json();
}

export async function pollStatus(runId: string): Promise<StatusResponse> {
  const res = await fetch(`/api/benchmark/status/${runId}`);
  if (!res.ok) throw new Error(`Status poll failed: ${res.status}`);
  return res.json();
}

export async function cancelBenchmark(runId: string): Promise<void> {
  await fetch(`/api/benchmark/cancel/${runId}`, { method: "POST" }).catch(() => {});
}

/**
 * Normalise a /benchmark/quota body. A daily limit of 0, or a missing or
 * negative `remaining`, means "unlimited": remaining and limit become null so
 * the UI shows no counter and never blocks a run.
 */
export function normalizeQuota(raw: Partial<Record<keyof Quota, unknown>> | null | undefined): Quota {
  if (!raw || typeof raw !== "object") return UNKNOWN_QUOTA;
  const remaining = typeof raw.remaining === "number" && Number.isFinite(raw.remaining) ? raw.remaining : null;
  const limit = typeof raw.limit === "number" && Number.isFinite(raw.limit) ? raw.limit : null;
  const resets = typeof raw.resets_in === "number" && Number.isFinite(raw.resets_in) ? raw.resets_in : 0;
  if (limit === 0 || remaining === null || remaining < 0) {
    return { remaining: null, resets_in: 0, limit: null };
  }
  return { remaining, resets_in: resets, limit };
}

export async function fetchQuota(token: string | null): Promise<Quota> {
  try {
    const res = await fetch("/api/benchmark/quota", {
      headers: authHeaders(token),
    });
    if (!res.ok) return UNKNOWN_QUOTA;
    return normalizeQuota(await res.json());
  } catch {
    return UNKNOWN_QUOTA;
  }
}

export async function generateTasks(
  url: string,
  token: string | null,
  signal?: AbortSignal
): Promise<{ tasks: Task[] }> {
  const res = await fetch("/api/benchmark/generate-tasks", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(token),
    },
    body: JSON.stringify({ url }),
    signal,
  });
  if (res.status === 401) {
    throw new Error("AUTH_EXPIRED");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const detail = data.detail?.error || data.detail;
    if (!detail && (res.status === 500 || isBackendUnreachable(res.status))) {
      throw new Error(UNREACHABLE_MESSAGE);
    }
    throw new Error(detail || "Failed to generate tasks");
  }
  const data = await res.json();
  return {
    tasks: (data.tasks ?? []).map((task: GeneratedTask) => ({
      ...task,
      id: String(task.id),
    })),
  };
}
