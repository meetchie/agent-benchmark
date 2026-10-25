// ─── Types ───────────────────────────────────────────────────────────────────

export interface TelemetryEvent {
  trace_id: string;
  run_id: string;
  lane: string;
  step_index?: number;
  event_type: "step_start" | "step_end" | "artifact";
  timestamp: string;
  duration_ms: number | null;
  tokens_input: number | null;
  tokens_output: number | null;
  cost_usd: number | null;
  action_type?: string;
  observation_hash?: string | null;
  /** Newer logs: true when the step's tool call failed. Absent in the oldest logs. */
  was_error?: boolean;
  action_category?: string;
  artifact_type?: string;
  artifact_url?: string;
}

export interface Step {
  index: number;
  actionType: string;
  startTime: string;
  endTime: string | null;
  durationMs: number;
  tokensInput: number;
  tokensOutput: number;
  costUsd: number;
  observationHash: string | null;
  /** The step's tool call failed (telemetry `was_error`). False when the log does not say. */
  wasError: boolean;
}

export interface JudgeEvaluation {
  verdict: string;
  reason: string;
  criteriaMet?: string;
  criteriaFailed?: string;
  errorsObserved?: string;
  isPosthumous: boolean;
}

export interface FrictionEvent {
  type: "loop" | "long_step" | "error" | "repeated_action" | "failed_step";
  severity: "warning" | "critical";
  stepIndices: number[];
  description: string;
}

export interface ParsedLog {
  // Header
  agent: string;
  scenario: string;
  runId: string;
  traceId: string;
  goal: string;
  startUrl: string;

  // Outcome
  durationSeconds: number;
  success: boolean;
  successRaw: string;
  errorsDetected: string | null;
  judge: JudgeEvaluation | null;

  // Economics
  tokensTotal: number;
  tokensInput: number;
  tokensOutput: number;
  costUsd: number;

  // Telemetry
  steps: Step[];
  artifactUrl: string | null;

  // Analysis
  friction: FrictionEvent[];

  // Meta
  filename: string;
}

export interface LogFileMeta {
  filename: string;
  agent: string;
  isMcp: boolean;
  scenario: string;
  promptType: "simple" | "complex" | "unknown";
  site: string;
  verdict: "PASS" | "FAIL" | "UNKNOWN";
  date: Date | null;
  dateLabel: string;
  timeLabel: string;
}

export function parseLogMeta(raw: string, filename: string): LogFileMeta {
  const telemetryIdx = raw.indexOf("Telemetry Events:");
  const header = telemetryIdx >= 0 ? raw.slice(0, telemetryIdx) : raw;

  const agent = extractField(header, "Agent") ?? "Unknown";
  const scenario = extractField(header, "Scenario") ?? "Unknown";
  const isMcp =
    agent.toUpperCase().includes("MCP") || filename.includes("_mcp_");

  let promptType: "simple" | "complex" | "unknown" = "unknown";
  if (scenario.includes("add_to_cart")) promptType = "simple";
  else if (scenario.includes("complex")) promptType = "complex";

  const sitePart = scenario.split("_")[0];
  const site = sitePart.charAt(0).toUpperCase() + sitePart.slice(1);

  const judge = extractJudge(header);
  let verdict: "PASS" | "FAIL" | "UNKNOWN" = "UNKNOWN";
  if (judge) {
    verdict = judge.verdict === "PASS" ? "PASS" : "FAIL";
  } else {
    const successRaw =
      extractField(header, "Agent Reported Success") ??
      extractField(header, "Success") ??
      "";
    if (successRaw.toLowerCase() === "true") verdict = "PASS";
    else if (successRaw.toLowerCase() === "false") verdict = "FAIL";
  }

  const dateMatch = filename.match(
    /(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.log/
  );
  let date: Date | null = null;
  let dateLabel = "";
  let timeLabel = "";
  if (dateMatch) {
    const [, year, month, day, hour, minute] = dateMatch;
    date = new Date(
      parseInt(year),
      parseInt(month) - 1,
      parseInt(day),
      parseInt(hour),
      parseInt(minute)
    );
    dateLabel = date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
    timeLabel = date.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
    });
  }

  return {
    filename,
    agent,
    isMcp,
    scenario,
    promptType,
    site,
    verdict,
    date,
    dateLabel,
    timeLabel,
  };
}

// ─── Parser ──────────────────────────────────────────────────────────────────

export function parseLog(raw: string, filename: string = ""): ParsedLog {
  // Split header from telemetry
  const telemetryIdx = raw.indexOf("Telemetry Events:");
  const header = telemetryIdx >= 0 ? raw.slice(0, telemetryIdx) : raw;
  const telemetryRaw =
    telemetryIdx >= 0 ? raw.slice(telemetryIdx + "Telemetry Events:".length).trim() : "[]";

  // Parse header fields
  const agent = extractField(header, "Agent") ?? "Unknown";
  const scenario = extractField(header, "Scenario") ?? "Unknown";
  const runId = extractField(header, "Run ID") ?? "";
  const traceId = extractField(header, "Trace ID") ?? "";
  const startUrl = extractField(header, "Start URL") ?? "";

  // Goal: everything between "Goal:" line and "Start URL:" line
  const goal = extractGoal(header);

  // Duration
  const durationStr = extractField(header, "Duration") ?? "0";
  const durationSeconds = parseFloat(durationStr.replace("s", ""));

  // Success — handle multiple formats
  const successRaw =
    extractField(header, "Agent Reported Success") ??
    extractField(header, "Success") ??
    "Unknown";
  const success = successRaw.toLowerCase() === "true";

  // Errors
  const errorsDetected = extractField(header, "Errors Detected") ?? null;

  // Judge evaluation
  const judge = extractJudge(header);

  // Tokens
  const tokenLine = extractField(header, "Token Burn") ?? "0 (0 in / 0 out)";
  const tokenMatch = tokenLine.match(
    /([\d,]+)\s*\(([\d,]+)\s*in\s*\/\s*([\d,]+)\s*out\)/
  );
  const tokensTotal = tokenMatch ? parseNum(tokenMatch[1]) : 0;
  const tokensInput = tokenMatch ? parseNum(tokenMatch[2]) : 0;
  const tokensOutput = tokenMatch ? parseNum(tokenMatch[3]) : 0;

  // Cost
  const costStr = extractField(header, "Cost") ?? "0";
  const costUsd = parseFloat(costStr.replace("$", ""));

  // Parse telemetry events
  let events: TelemetryEvent[] = [];
  try {
    events = JSON.parse(telemetryRaw);
  } catch {
    // telemetry parsing failed, continue with empty
  }

  // Build steps from events
  const steps = buildSteps(events);

  // Extract artifact URL
  const artifactEvent = events.find((e) => e.event_type === "artifact");
  const artifactUrl = artifactEvent?.artifact_url ?? null;

  // Analyze friction
  const friction = analyzeFriction(steps, errorsDetected);

  return {
    agent,
    scenario,
    runId,
    traceId,
    goal,
    startUrl,
    durationSeconds,
    success,
    successRaw,
    errorsDetected,
    judge,
    tokensTotal,
    tokensInput,
    tokensOutput,
    costUsd,
    steps,
    artifactUrl,
    friction,
    filename,
  };
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function extractField(text: string, field: string): string | null {
  // Match "Field: value" at start of line
  const regex = new RegExp(`^${field}:\\s*(.+)$`, "m");
  const match = text.match(regex);
  return match ? match[1].trim() : null;
}

function extractGoal(header: string): string {
  const goalStart = header.indexOf("Goal:");
  if (goalStart < 0) return "";
  const afterGoal = header.slice(goalStart + 5);

  // Find the next known header field
  const endMarkers = ["Start URL:", "Duration:", "Success:", "Agent Reported Success:"];
  let endIdx = afterGoal.length;
  for (const marker of endMarkers) {
    const idx = afterGoal.indexOf(marker);
    if (idx >= 0 && idx < endIdx) endIdx = idx;
  }
  return afterGoal.slice(0, endIdx).trim();
}

function extractJudge(header: string): JudgeEvaluation | null {
  const judgeStart = header.indexOf("--- JUDGE EVALUATION");
  if (judgeStart < 0) return null;
  const judgeEnd = header.indexOf("--- END JUDGE EVALUATION ---");
  const judgeBlock = header.slice(
    judgeStart,
    judgeEnd >= 0 ? judgeEnd : undefined
  );

  const isPosthumous = judgeBlock.includes("POSTHUMOUS");

  return {
    verdict: extractField(judgeBlock, "Judge Verdict") ?? "UNKNOWN",
    reason: extractField(judgeBlock, "Judge Reason") ?? "",
    criteriaMet: extractField(judgeBlock, "Criteria Met") ?? undefined,
    criteriaFailed: extractField(judgeBlock, "Criteria Failed") ?? undefined,
    errorsObserved:
      extractField(judgeBlock, "Errors Observed by Judge") ?? undefined,
    isPosthumous,
  };
}

function parseNum(s: string): number {
  return parseInt(s.replace(/,/g, ""), 10) || 0;
}

function buildSteps(events: TelemetryEvent[]): Step[] {
  const stepMap = new Map<
    number,
    { start?: TelemetryEvent; end?: TelemetryEvent }
  >();

  for (const e of events) {
    if (e.step_index == null) continue;
    if (!stepMap.has(e.step_index)) {
      stepMap.set(e.step_index, {});
    }
    const entry = stepMap.get(e.step_index)!;
    if (e.event_type === "step_start") entry.start = e;
    if (e.event_type === "step_end") entry.end = e;
  }

  const steps: Step[] = [];
  for (const [index, { start, end }] of stepMap) {
    steps.push({
      index,
      actionType: end?.action_type ?? start?.action_type ?? "unknown",
      startTime: start?.timestamp ?? end?.timestamp ?? "",
      endTime: end?.timestamp ?? null,
      durationMs: end?.duration_ms ?? 0,
      tokensInput: end?.tokens_input ?? 0,
      tokensOutput: end?.tokens_output ?? 0,
      costUsd: end?.cost_usd ?? 0,
      observationHash: end?.observation_hash ?? null,
      wasError: end?.was_error === true,
    });
  }

  steps.sort((a, b) => a.index - b.index);
  return steps;
}

export function analyzeFriction(
  steps: Step[],
  errorsDetected: string | null
): FrictionEvent[] {
  const friction: FrictionEvent[] = [];

  // 1. Detect observation loops (consecutive identical observation_hash)
  let loopIndices: number[] = [];
  for (let i = 1; i < steps.length; i++) {
    const prev = steps[i - 1];
    const curr = steps[i];
    if (
      curr.observationHash &&
      prev.observationHash &&
      curr.observationHash === prev.observationHash
    ) {
      if (loopIndices.length === 0) {
        loopIndices = [prev.index, curr.index];
      } else {
        loopIndices.push(curr.index);
      }
    } else {
      if (loopIndices.length >= 2) {
        friction.push({
          type: "loop",
          severity: loopIndices.length >= 3 ? "critical" : "warning",
          stepIndices: [...loopIndices],
          description: `Agent stuck in loop: steps ${loopIndices[0]}-${loopIndices[loopIndices.length - 1]} produced identical observations (${loopIndices.length} repetitions)`,
        });
      }
      loopIndices = [];
    }
  }
  // Flush remaining loop
  if (loopIndices.length >= 2) {
    friction.push({
      type: "loop",
      severity: loopIndices.length >= 3 ? "critical" : "warning",
      stepIndices: [...loopIndices],
      description: `Agent stuck in loop: steps ${loopIndices[0]}-${loopIndices[loopIndices.length - 1]} produced identical observations (${loopIndices.length} repetitions)`,
    });
  }

  // 2. Detect long steps (> 60 seconds)
  for (const step of steps) {
    if (step.durationMs > 60_000) {
      friction.push({
        type: "long_step",
        severity: step.durationMs > 300_000 ? "critical" : "warning",
        stepIndices: [step.index],
        description: `Step ${step.index} (${step.actionType}) took ${formatDuration(step.durationMs / 1000)} — possible stall or timeout`,
      });
    }
  }

  // 3. Detect repeated action bursts (e.g., 4+ identical action_types in a row)
  let runStart = 0;
  for (let i = 1; i <= steps.length; i++) {
    if (
      i < steps.length &&
      steps[i].actionType === steps[runStart].actionType
    ) {
      continue;
    }
    const runLen = i - runStart;
    if (runLen >= 4) {
      const indices = steps.slice(runStart, i).map((s) => s.index);
      friction.push({
        type: "repeated_action",
        severity: "warning",
        stepIndices: indices,
        description: `${runLen} consecutive "${steps[runStart].actionType}" actions (steps ${indices[0]}-${indices[indices.length - 1]}) — agent may be retrying or stuck`,
      });
    }
    runStart = i;
  }

  // 4. Failed tool calls (telemetry was_error on the step's end event). The run
  // may still pass; these are friction the agent hit along the way.
  for (const step of steps) {
    if (step.wasError) {
      friction.push({
        type: "failed_step",
        severity: "warning",
        stepIndices: [step.index],
        description: `Step ${step.index} (${step.actionType}) failed: the tool call returned an error`,
      });
    }
  }

  // 5. Header-level errors
  if (errorsDetected) {
    friction.push({
      type: "error",
      severity: "critical",
      stepIndices: [],
      description: errorsDetected,
    });
  }

  // Sort: critical first, then by first step index
  friction.sort((a, b) => {
    if (a.severity !== b.severity)
      return a.severity === "critical" ? -1 : 1;
    return (a.stepIndices[0] ?? 0) - (b.stepIndices[0] ?? 0);
  });

  return friction;
}

// ─── Formatting Utils ────────────────────────────────────────────────────────

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return `${h}h ${rm}m ${s}s`;
}

export function formatCost(usd: number): string {
  return `$${usd.toFixed(4)}`;
}

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toString();
}

export function scenarioLabel(filename: string): string {
  // arena_browseruse_shipt_20260130_184107.log → Shipt (Jan 30, 2026)
  const match = filename.match(
    /arena_(\w+?)_(.+?)_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.log/
  );
  if (!match) return filename;

  const [, _agent, scenario, year, month, day, hour, minute] = match;
  const site = scenario
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
  const date = new Date(
    parseInt(year),
    parseInt(month) - 1,
    parseInt(day),
    parseInt(hour),
    parseInt(minute)
  );
  const dateStr = date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  const timeStr = date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
  return `${site} — ${dateStr} ${timeStr}`;
}
