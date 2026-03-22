import type { StatusResponse, Task, AuthResponse, MeResponse } from "./types";

function getToken(): string | null {
  return localStorage.getItem("auth_token");
}

export function setToken(token: string) {
  localStorage.setItem("auth_token", token);
}

export function clearToken() {
  localStorage.removeItem("auth_token");
}

export function hasToken(): boolean {
  return !!getToken();
}

async function authFetch(url: string, init?: RequestInit): Promise<Response> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> || {}),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(url, { ...init, headers });
  if (res.status === 401) {
    clearToken();
    window.location.reload();
    throw new Error("Session expired");
  }
  return res;
}

// Auth
export async function signup(email: string, password: string): Promise<AuthResponse> {
  const res = await fetch("/api/auth/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Signup failed");
  }
  return res.json();
}

export async function signin(email: string, password: string): Promise<AuthResponse> {
  const res = await fetch("/api/auth/signin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Invalid email or password");
  }
  return res.json();
}

export async function getMe(): Promise<MeResponse> {
  const res = await authFetch("/api/auth/me");
  if (!res.ok) throw new Error("Not authenticated");
  return res.json();
}

// Benchmark
export async function startBenchmark(
  url: string,
  goal: string
): Promise<{ run_id: string; remaining_runs: number }> {
  const res = await authFetch("/api/benchmark/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, goal }),
  });
  if (res.status === 429) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail?.error || "Rate limit exceeded");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Failed to start benchmark: ${text}`);
  }
  return res.json();
}

export async function pollStatus(runId: string): Promise<StatusResponse> {
  const res = await authFetch(`/api/benchmark/status/${runId}`);
  if (!res.ok) throw new Error(`Status poll failed: ${res.status}`);
  return res.json();
}

export async function generateTasks(
  url: string
): Promise<{ tasks: Task[] }> {
  const res = await authFetch("/api/benchmark/generate-tasks", {
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
