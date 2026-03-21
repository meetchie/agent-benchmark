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

export interface StatusRunning {
  status: "running";
  steps: StepRecord[];
}

export interface StatusComplete {
  status: "complete";
  steps: StepRecord[];
  success: boolean;
  summary: string;
  total_ms: number;
}

export interface StatusError {
  status: "error";
  message: string;
}

export type StatusResponse = StatusRunning | StatusComplete | StatusError;

export type RunStatus = "idle" | "running" | "complete" | "error";

export interface SummaryData {
  success: boolean;
  summary: string;
  total_ms: number;
}
