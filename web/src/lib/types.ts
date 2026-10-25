export interface Task {
  id: string;
  label: string;
  goal: string;
}

export interface StepRecord {
  step: number;
  description: string;
  elapsed_ms: number;
  screenshot_b64?: string;
}

export interface Phase {
  name: string;
  steps: number[];
  total_ms: number;
  failed: boolean;
  slow: boolean;
}

export type ResultState = "pass" | "fail" | "too_slow" | "error";

export interface StatusRunning {
  status: "running";
  steps: StepRecord[];
}

export interface StatusAnalyzing {
  status: "analyzing";
  steps: StepRecord[];
  total_ms: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  /** US dollars for the agent's tokens at the agent model's rates; null when the backend has no rate for the model. */
  cost_usd?: number | null;
  /** Model id the agent ran on, e.g. "claude-sonnet-5-5". */
  agent_model?: string | null;
}

export interface StatusComplete {
  status: "complete";
  steps: StepRecord[];
  success: boolean;
  summary: string;
  result_state: ResultState;
  total_ms: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd?: number | null;
  agent_model?: string | null;
  phases: Phase[];
  /** Why the run is an error, when result_state is "error" (the steps were still judged). */
  message?: string;
  /** The agent's closing report, as the judge read it; null when it did not finish on its own. */
  final_report?: string | null;
  /** The success flag the agent set with its report; null when it set none. */
  agent_reported_success?: boolean | null;
}

export interface StatusError {
  status: "error";
  message: string;
  steps?: StepRecord[];
}

export type StatusResponse = StatusRunning | StatusAnalyzing | StatusComplete | StatusError;

export type RunStatus = "idle" | "running" | "analyzing" | "complete" | "error";

/** Totals the backend reports once the agent has finished (status "analyzing" and "complete"). */
export interface RunStats {
  total_ms: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  /** Absent or null: the backend could not price the run, so the UI shows tokens only. */
  cost_usd?: number | null;
  agent_model?: string | null;
}

export interface SummaryData extends RunStats {
  success: boolean;
  summary: string;
  result_state: ResultState;
  phases: Phase[];
  final_report?: string | null;
  agent_reported_success?: boolean | null;
}

/** Daily run allowance. remaining and limit are null when the backend enforces none. */
export interface Quota {
  remaining: number | null;
  resets_in: number;
  limit: number | null;
}

/**
 * What GET /health tells the UI about the backend it is talking to. Both
 * fields are read defensively: an older backend without timeout_s, or no
 * backend at all, gives the defaults in api.ts (UNKNOWN_HEALTH).
 */
export interface Health {
  /** The backend plays canned runs: no real agent and no API calls. */
  demo_mode: boolean;
  /** The agent's hard time limit in seconds (BENCHMARK_TIMEOUT_S); null when unknown. */
  timeout_s: number | null;
}

// Positional degradation benchmark (#87)
// Measures whether agent success rate degrades based on where in a result list
// the target item appears (lost-in-the-middle effect).

export interface PositionalResult {
  position: number;
  success: boolean;
  summary: string;
  result_state: ResultState;
}

export interface PositionalRunStatus {
  run_id: string;
  status: "running" | "complete" | "error";
  query: string;
  positions: number[];
  results: PositionalResult[];
  message?: string;
}
