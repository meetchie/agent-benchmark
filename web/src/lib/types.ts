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
}

/** Daily run allowance. remaining and limit are null when the backend enforces none. */
export interface Quota {
  remaining: number | null;
  resets_in: number;
  limit: number | null;
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
