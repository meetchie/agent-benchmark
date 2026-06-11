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
  phases: Phase[];
}

export interface StatusError {
  status: "error";
  message: string;
  steps?: StepRecord[];
}

export type StatusResponse = StatusRunning | StatusAnalyzing | StatusComplete | StatusError;

export type RunStatus = "idle" | "running" | "analyzing" | "complete" | "error";

export interface SummaryData {
  success: boolean;
  summary: string;
  result_state: ResultState;
  total_ms: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  phases: Phase[];
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
