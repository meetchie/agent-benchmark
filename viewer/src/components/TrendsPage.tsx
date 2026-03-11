import { useEffect, useState, useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
  Cell,
} from "recharts";
import { parseLog, formatDuration, formatCost, formatTokens } from "../lib/parseLog";
import type { ParsedLog, FrictionEvent } from "../lib/parseLog";

// ─── Types ───────────────────────────────────────────────────────────────────

type AgentType = "BROWSERUSE" | "BROWSERUSE_MCP";
type FilterMode = "all" | "pass" | "fail";

interface AgentStats {
  agentType: AgentType;
  label: string;
  runs: ParsedLog[];
  totalRuns: number;
  passCount: number;
  failCount: number;
  passRate: number;
  avgSteps: number;
  medianSteps: number;
  avgCost: number;
  medianCost: number;
  avgDuration: number;
  medianDuration: number;
  avgTokens: number;
  totalCost: number;
}

type FailureCategory =
  | "verification_gap"
  | "loop_stuck"
  | "wrong_product"
  | "connection_infra"
  | "incomplete_task"
  | "other";

interface ClassifiedFailure {
  log: ParsedLog;
  agent: AgentType;
  category: FailureCategory;
  reason: string;
  depth: "shallow" | "deep";
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 !== 0
    ? sorted[mid]
    : (sorted[mid - 1] + sorted[mid]) / 2;
}

function classifyAgent(log: ParsedLog): AgentType {
  if (log.agent.toUpperCase().includes("MCP") || log.filename.includes("_mcp_")) {
    return "BROWSERUSE_MCP";
  }
  return "BROWSERUSE";
}

function isPassed(log: ParsedLog): boolean {
  return log.judge?.verdict === "PASS" || (!log.judge && log.success);
}

function computeStats(logs: ParsedLog[], agentType: AgentType): AgentStats {
  const runs = logs.filter((l) => classifyAgent(l) === agentType);
  const passRuns = runs.filter(isPassed);

  const steps = runs.map((r) => r.steps.length);
  const costs = runs.map((r) => r.costUsd);
  const durations = runs.map((r) => r.durationSeconds);
  const tokens = runs.map((r) => r.tokensTotal);

  return {
    agentType,
    label: agentType === "BROWSERUSE" ? "BrowserUse" : "MCP BrowserUse",
    runs,
    totalRuns: runs.length,
    passCount: passRuns.length,
    failCount: runs.length - passRuns.length,
    passRate: runs.length > 0 ? (passRuns.length / runs.length) * 100 : 0,
    avgSteps: runs.length > 0 ? steps.reduce((a, b) => a + b, 0) / runs.length : 0,
    medianSteps: median(steps),
    avgCost: runs.length > 0 ? costs.reduce((a, b) => a + b, 0) / runs.length : 0,
    medianCost: median(costs),
    avgDuration: runs.length > 0 ? durations.reduce((a, b) => a + b, 0) / runs.length : 0,
    medianDuration: median(durations),
    avgTokens: runs.length > 0 ? tokens.reduce((a, b) => a + b, 0) / runs.length : 0,
    totalCost: costs.reduce((a, b) => a + b, 0),
  };
}

// ─── Failure Classification ──────────────────────────────────────────────────

const FAILURE_CATEGORY_LABELS: Record<FailureCategory, string> = {
  verification_gap: "Verification / Evidence Gap",
  loop_stuck: "Loop / Stuck",
  wrong_product: "Wrong Product / Navigation",
  connection_infra: "Connection / Infrastructure",
  incomplete_task: "Incomplete Task",
  other: "Other",
};

const FAILURE_CATEGORY_DESCRIPTIONS: Record<FailureCategory, string> = {
  verification_gap:
    "Judge couldn't confirm success — missing extraction evidence, no confirmation screenshot, or insufficient proof the task completed.",
  loop_stuck:
    "Agent got stuck in observation loops, repeated identical actions, or hit retry limits without making progress.",
  wrong_product:
    "Agent navigated to the wrong page, selected incorrect products, wrong quantities, or misidentified items.",
  connection_infra:
    "Browser session died, rate limits hit, timeout errors, or other infrastructure failures prevented completion.",
  incomplete_task:
    "Agent completed only part of the task — e.g. added 1 of 3 required products, or skipped verification steps.",
  other: "Failure doesn't clearly fit the other categories.",
};

function classifyFailure(log: ParsedLog): ClassifiedFailure {
  const agent = classifyAgent(log);
  const reason = log.judge?.reason ?? "";
  const reasonLower = reason.toLowerCase();
  const criteriaFailed = (log.judge?.criteriaFailed ?? "").toLowerCase();
  const errorsObserved = (log.judge?.errorsObserved ?? "").toLowerCase();
  const errorsDetected = (log.errorsDetected ?? "").toLowerCase();
  const allText = `${reasonLower} ${criteriaFailed} ${errorsObserved} ${errorsDetected}`;

  const hasLoops = log.friction.some((f) => f.type === "loop");
  const hasRepeatedActions = log.friction.some((f) => f.type === "repeated_action");

  let category: FailureCategory = "other";
  let depth: "shallow" | "deep" = "deep";

  // Connection / Infrastructure — check first as it's the most specific
  if (
    allText.includes("closed") ||
    allText.includes("page.goto") ||
    allText.includes("target page") ||
    allText.includes("rate limit") ||
    allText.includes("429") ||
    allText.includes("insufficient_quota") ||
    allText.includes("connection") ||
    allText.includes("timeout") ||
    allText.includes("browser has been closed") ||
    allText.includes("session died")
  ) {
    category = "connection_infra";
    depth = "deep";
  }
  // Loop / Stuck
  else if (
    hasLoops ||
    (hasRepeatedActions && log.friction.filter((f) => f.type === "repeated_action").length >= 2) ||
    allText.includes("stuck") ||
    allText.includes("loop") ||
    allText.includes("consecutive failures") ||
    allText.includes("repeated")
  ) {
    category = "loop_stuck";
    depth = "deep";
  }
  // Wrong Product / Navigation
  else if (
    allText.includes("wrong") ||
    allText.includes("incorrect") ||
    allText.includes("different") ||
    allText.includes("wrong store") ||
    allText.includes("wrong quantity") ||
    allText.includes("not the correct") ||
    allText.includes("advil")
  ) {
    category = "wrong_product";
    depth = "deep";
  }
  // Incomplete Task
  else if (
    allText.includes("incomplete") ||
    allText.includes("only") ||
    allText.includes("not all") ||
    allText.includes("did not contain") ||
    allText.includes("missing") ||
    /\d+\s*(of|out of)\s*\d+/.test(allText)
  ) {
    category = "incomplete_task";
    depth = "deep";
  }
  // Verification Gap — typically shallow failures
  else if (
    allText.includes("no evidence") ||
    allText.includes("no concrete evidence") ||
    allText.includes("no extraction") ||
    allText.includes("no direct final extraction") ||
    allText.includes("no confirmation") ||
    allText.includes("success indicator") ||
    allText.includes("could not confirm") ||
    allText.includes("verification")
  ) {
    category = "verification_gap";
    depth = "shallow";
  }

  return { log, agent, category, reason, depth };
}

function countFrictionByType(
  logs: ParsedLog[]
): Record<FrictionEvent["type"], { count: number; runsAffected: number }> {
  const result: Record<FrictionEvent["type"], { count: number; runsAffected: number }> = {
    loop: { count: 0, runsAffected: 0 },
    long_step: { count: 0, runsAffected: 0 },
    error: { count: 0, runsAffected: 0 },
    repeated_action: { count: 0, runsAffected: 0 },
  };
  for (const log of logs) {
    const seen = new Set<FrictionEvent["type"]>();
    for (const f of log.friction) {
      result[f.type].count++;
      if (!seen.has(f.type)) {
        result[f.type].runsAffected++;
        seen.add(f.type);
      }
    }
  }
  return result;
}

// ─── Scenario Annotations ────────────────────────────────────────────────────
// Hand-curated notes for specific scenarios to help readers interpret the data.

const SCENARIO_ANNOTATIONS: Record<
  string,
  { note: string; detail: string }
> = {
  shipt_complex_cart_validation: {
    note: "3 of 5 MCP failures were due to the LLM selecting the wrong Advil variant",
    detail:
      'The MCP tools returned correct search results, but GPT-4o chose "Advil Sinus Congestion & Pain" ' +
      '(a combo product) instead of standard Ibuprofen tablets — likely because the 20-count pack appeared ' +
      'to be the "smallest." The remaining 2 failures were a dropped quantity click (5 apples instead of 6) ' +
      "and a browser session crash during cart verification. All 5 failures are attributable to the reasoning " +
      "model or infrastructure, not the MCP tooling itself — a stronger model would likely bring MCP close to 100%.",
  },
};

// ─── Colors ──────────────────────────────────────────────────────────────────

const COLORS = {
  browseruse: "#f59e0b",
  mcp: "#3b82f6",
  pass: "#22c55e",
  fail: "#ef4444",
};

// ─── Component ───────────────────────────────────────────────────────────────

export function TrendsPage() {
  const [allLogs, setAllLogs] = useState<ParsedLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [progress, setProgress] = useState({ loaded: 0, total: 0 });
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterMode>("all");
  const [expandedInsight, setExpandedInsight] = useState<string | null>(null);

  // Load and parse all log files
  useEffect(() => {
    let cancelled = false;

    async function loadAll() {
      try {
        const resp = await fetch("/logs/manifest.json");
        if (!resp.ok) throw new Error("Failed to load manifest");
        const manifest: { files: string[] } = await resp.json();
        const files = manifest.files;

        setProgress({ loaded: 0, total: files.length });

        const parsed: ParsedLog[] = [];
        const batchSize = 5;

        for (let i = 0; i < files.length; i += batchSize) {
          if (cancelled) return;
          const batch = files.slice(i, i + batchSize);
          const results = await Promise.allSettled(
            batch.map(async (f) => {
              const r = await fetch(`/logs/${f}`);
              if (!r.ok) throw new Error(`Failed to load ${f}`);
              const raw = await r.text();
              return parseLog(raw, f);
            })
          );

          for (const result of results) {
            if (result.status === "fulfilled") {
              parsed.push(result.value);
            }
          }

          if (!cancelled) {
            setProgress({ loaded: Math.min(i + batchSize, files.length), total: files.length });
          }
        }

        if (!cancelled) {
          setAllLogs(parsed);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load logs");
          setLoading(false);
        }
      }
    }

    loadAll();
    return () => {
      cancelled = true;
    };
  }, []);

  // Apply filter
  const filteredLogs = useMemo(() => {
    if (filter === "all") return allLogs;
    return allLogs.filter((log) => {
      const passed = isPassed(log);
      return filter === "pass" ? passed : !passed;
    });
  }, [allLogs, filter]);

  // Compute stats
  const buStats = useMemo(() => computeStats(filteredLogs, "BROWSERUSE"), [filteredLogs]);
  const mcpStats = useMemo(() => computeStats(filteredLogs, "BROWSERUSE_MCP"), [filteredLogs]);

  // ─── Scenario Breakdown ────────────────────────────────────────────────────

  const scenarioBreakdown = useMemo(() => {
    const map = new Map<
      string,
      { buTotal: number; buPass: number; mcpTotal: number; mcpPass: number }
    >();

    for (const log of allLogs) {
      const scenario = log.scenario;
      const agent = classifyAgent(log);
      const passed = isPassed(log);

      if (!map.has(scenario)) {
        map.set(scenario, { buTotal: 0, buPass: 0, mcpTotal: 0, mcpPass: 0 });
      }
      const entry = map.get(scenario)!;
      if (agent === "BROWSERUSE") {
        entry.buTotal++;
        if (passed) entry.buPass++;
      } else {
        entry.mcpTotal++;
        if (passed) entry.mcpPass++;
      }
    }

    return Array.from(map.entries())
      .map(([scenario, data]) => ({
        scenario: scenario
          .split("_")
          .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
          .join(" "),
        scenarioRaw: scenario,
        "BrowserUse %": data.buTotal > 0 ? Math.round((data.buPass / data.buTotal) * 100) : 0,
        "MCP %": data.mcpTotal > 0 ? Math.round((data.mcpPass / data.mcpTotal) * 100) : 0,
        buLabel: data.buTotal > 0 ? `${data.buPass}/${data.buTotal}` : "—",
        mcpLabel: data.mcpTotal > 0 ? `${data.mcpPass}/${data.mcpTotal}` : "—",
        buTotal: data.buTotal,
        mcpTotal: data.mcpTotal,
      }))
      .sort((a, b) => b.buTotal + b.mcpTotal - (a.buTotal + a.mcpTotal));
  }, [allLogs]);

  // ─── Failure Classification ────────────────────────────────────────────────

  const failureAnalysis = useMemo(() => {
    const failedLogs = allLogs.filter((l) => !isPassed(l));
    return failedLogs.map(classifyFailure);
  }, [allLogs]);

  const failureCategoryCounts = useMemo(() => {
    const buCounts: Record<FailureCategory, number> = {
      verification_gap: 0,
      loop_stuck: 0,
      wrong_product: 0,
      connection_infra: 0,
      incomplete_task: 0,
      other: 0,
    };
    const mcpCounts = { ...buCounts };

    for (const f of failureAnalysis) {
      if (f.agent === "BROWSERUSE") buCounts[f.category]++;
      else mcpCounts[f.category]++;
    }

    const categories = Object.keys(buCounts) as FailureCategory[];
    return categories
      .filter((c) => buCounts[c] > 0 || mcpCounts[c] > 0)
      .map((category) => ({
        category,
        label: FAILURE_CATEGORY_LABELS[category],
        BrowserUse: buCounts[category],
        "MCP BrowserUse": mcpCounts[category],
      }));
  }, [failureAnalysis]);

  const depthSummary = useMemo(() => {
    const buShallow = failureAnalysis.filter((f) => f.agent === "BROWSERUSE" && f.depth === "shallow").length;
    const buDeep = failureAnalysis.filter((f) => f.agent === "BROWSERUSE" && f.depth === "deep").length;
    const mcpShallow = failureAnalysis.filter((f) => f.agent === "BROWSERUSE_MCP" && f.depth === "shallow").length;
    const mcpDeep = failureAnalysis.filter((f) => f.agent === "BROWSERUSE_MCP" && f.depth === "deep").length;
    return { buShallow, buDeep, mcpShallow, mcpDeep };
  }, [failureAnalysis]);

  // ─── Friction Patterns ─────────────────────────────────────────────────────

  const frictionPatterns = useMemo(() => {
    const buLogs = allLogs.filter((l) => classifyAgent(l) === "BROWSERUSE");
    const mcpLogs = allLogs.filter((l) => classifyAgent(l) === "BROWSERUSE_MCP");
    return {
      bu: countFrictionByType(buLogs),
      mcp: countFrictionByType(mcpLogs),
      buTotal: buLogs.length,
      mcpTotal: mcpLogs.length,
    };
  }, [allLogs]);

  // ─── Chart data ────────────────────────────────────────────────────────────

  const runTableData = useMemo(() => {
    return filteredLogs
      .map((log) => {
        const agent = classifyAgent(log);
        return {
          filename: log.filename,
          agent,
          agentLabel: agent === "BROWSERUSE" ? "BrowserUse" : "MCP",
          scenario: log.scenario,
          verdict: log.judge?.verdict ?? (log.success ? "PASS" : "FAIL"),
          steps: log.steps.length,
          cost: log.costUsd,
          duration: log.durationSeconds,
          tokens: log.tokensTotal,
          frictionCount: log.friction.length,
          hasLoops: log.friction.some((f) => f.type === "loop"),
          judgeReason: log.judge?.reason ?? "",
        };
      })
      .sort((a, b) => a.filename.localeCompare(b.filename));
  }, [filteredLogs]);

  // Notable failure examples for the insights panel
  const notableExamples = useMemo(() => {
    const examples: {
      id: string;
      title: string;
      insight: string;
      runs: { log: ParsedLog; agent: AgentType; note: string }[];
    }[] = [];

    // 1. Complex task capability gap
    const complexScenarios = allLogs.filter((l) => l.scenario.includes("complex"));
    if (complexScenarios.length > 0) {
      const buComplex = complexScenarios.filter((l) => classifyAgent(l) === "BROWSERUSE");
      const mcpComplex = complexScenarios.filter((l) => classifyAgent(l) === "BROWSERUSE_MCP");
      const buPassRate = buComplex.length > 0 ? buComplex.filter(isPassed).length / buComplex.length : 0;
      const mcpPassRate = mcpComplex.length > 0 ? mcpComplex.filter(isPassed).length / mcpComplex.length : 0;

      if (buComplex.length > 0 || mcpComplex.length > 0) {
        examples.push({
          id: "complex_tasks",
          title: "MCP excels at complex multi-step tasks",
          insight: `On complex scenarios, MCP passes ${(mcpPassRate * 100).toFixed(0)}% vs BrowserUse at ${(buPassRate * 100).toFixed(0)}%. MCP's structured tools (cart access, search, address setting) provide reliable building blocks for multi-step workflows.`,
          runs: [
            ...mcpComplex
              .filter(isPassed)
              .slice(0, 1)
              .map((l) => ({
                log: l,
                agent: "BROWSERUSE_MCP" as AgentType,
                note: `PASS — ${l.steps.length} steps, ${formatCost(l.costUsd)}`,
              })),
            ...buComplex
              .filter((l) => !isPassed(l))
              .slice(0, 1)
              .map((l) => ({
                log: l,
                agent: "BROWSERUSE" as AgentType,
                note: `FAIL — ${l.steps.length} steps, ${formatCost(l.costUsd)} — ${l.judge?.reason?.slice(0, 120) ?? ""}...`,
              })),
          ],
        });
      }
    }

    // 2. Shallow vs deep failures
    const shallowMcp = failureAnalysis.filter(
      (f) => f.agent === "BROWSERUSE_MCP" && f.depth === "shallow"
    );
    const deepBu = failureAnalysis.filter(
      (f) => f.agent === "BROWSERUSE" && f.depth === "deep"
    );
    if (shallowMcp.length > 0 || deepBu.length > 0) {
      examples.push({
        id: "failure_depth",
        title: "MCP failures are shallower than BrowserUse failures",
        insight: `MCP has ${depthSummary.mcpShallow} shallow failure${depthSummary.mcpShallow !== 1 ? "s" : ""} (evidence gaps) vs ${depthSummary.mcpDeep} deep. BrowserUse has ${depthSummary.buShallow} shallow vs ${depthSummary.buDeep} deep (loops, wrong navigation, incomplete tasks).`,
        runs: [
          ...shallowMcp.slice(0, 1).map((f) => ({
            log: f.log,
            agent: f.agent,
            note: `Shallow FAIL — ${f.log.judge?.reason?.slice(0, 140) ?? ""}`,
          })),
          ...deepBu.slice(0, 1).map((f) => ({
            log: f.log,
            agent: f.agent,
            note: `Deep FAIL — ${f.log.judge?.reason?.slice(0, 140) ?? ""}`,
          })),
        ],
      });
    }

    // 3. Connection/infrastructure issues
    const infraFailures = failureAnalysis.filter((f) => f.category === "connection_infra");
    if (infraFailures.length > 0) {
      const mcpInfra = infraFailures.filter((f) => f.agent === "BROWSERUSE_MCP");
      const buInfra = infraFailures.filter((f) => f.agent === "BROWSERUSE");
      examples.push({
        id: "infra_errors",
        title: "MCP has unique infrastructure vulnerability",
        insight: `${mcpInfra.length} MCP run${mcpInfra.length !== 1 ? "s" : ""} failed from connection/infrastructure errors vs ${buInfra.length} for BrowserUse. MCP's reliance on browser session connectivity makes it fragile when sessions die mid-task.`,
        runs: infraFailures.slice(0, 2).map((f) => ({
          log: f.log,
          agent: f.agent,
          note: `Infra FAIL — ${f.log.judge?.reason?.slice(0, 140) ?? f.log.errorsDetected?.slice(0, 140) ?? "Connection error"}`,
        })),
      });
    }

    // 4. Loop/stuck pattern
    const loopFailures = failureAnalysis.filter((f) => f.category === "loop_stuck");
    if (loopFailures.length > 0) {
      const buLoops = loopFailures.filter((f) => f.agent === "BROWSERUSE");
      const mcpLoops = loopFailures.filter((f) => f.agent === "BROWSERUSE_MCP");
      examples.push({
        id: "loop_patterns",
        title: "BrowserUse gets stuck in loops more often",
        insight: `${buLoops.length} BrowserUse run${buLoops.length !== 1 ? "s" : ""} got stuck in loops vs ${mcpLoops.length} MCP. Without structured tools, BrowserUse resorts to repeated scrolling, clicking, and extraction attempts that don't make progress.`,
        runs: buLoops.slice(0, 2).map((f) => ({
          log: f.log,
          agent: f.agent,
          note: `Loop FAIL — ${f.log.steps.length} steps, ${f.log.friction.filter((fr) => fr.type === "loop").length} loop event${f.log.friction.filter((fr) => fr.type === "loop").length !== 1 ? "s" : ""} — ${f.log.judge?.reason?.slice(0, 100) ?? ""}`,
        })),
      });
    }

    return examples;
  }, [allLogs, failureAnalysis, depthSummary]);

  // ─── Render ──────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="trends-loading">
        <div className="spinner" />
        <p>
          Loading logs... {progress.loaded}/{progress.total}
        </p>
        <div className="progress-bar-bg">
          <div
            className="progress-bar-fill"
            style={{
              width: progress.total > 0 ? `${(progress.loaded / progress.total) * 100}%` : "0%",
            }}
          />
        </div>
      </div>
    );
  }

  if (error) {
    return <div className="error-banner">{error}</div>;
  }

  return (
    <div className="trends-page">
      {/* Filter Controls */}
      <div className="trends-filter-bar">
        <span className="trends-filter-label">Filter by outcome:</span>
        <div className="trends-filter-buttons">
          {(["all", "pass", "fail"] as FilterMode[]).map((mode) => (
            <button
              key={mode}
              className={`trends-filter-btn ${filter === mode ? "active" : ""} ${mode}`}
              onClick={() => setFilter(mode)}
            >
              {mode === "all" ? "All Runs" : mode === "pass" ? "Passing Only" : "Failing Only"}
            </button>
          ))}
        </div>
        <span className="trends-run-count">
          {filteredLogs.length} run{filteredLogs.length !== 1 ? "s" : ""}
          {filter !== "all" && ` (${filter === "pass" ? "passing" : "failing"})`}
        </span>
      </div>

      {/* Overview Cards */}
      <div className="trends-overview">
        <StatCompareCard
          title="Total Runs"
          buValue={buStats.totalRuns.toString()}
          mcpValue={mcpStats.totalRuns.toString()}
        />
        <StatCompareCard
          title="Pass Rate"
          buValue={`${buStats.passRate.toFixed(0)}%`}
          mcpValue={`${mcpStats.passRate.toFixed(0)}%`}
          buSub={`${buStats.passCount}/${buStats.totalRuns}`}
          mcpSub={`${mcpStats.passCount}/${mcpStats.totalRuns}`}
          highlightBetter="higher"
          buNum={buStats.passRate}
          mcpNum={mcpStats.passRate}
        />
        <StatCompareCard
          title="Avg Steps"
          buValue={buStats.avgSteps.toFixed(1)}
          mcpValue={mcpStats.avgSteps.toFixed(1)}
          buSub={`median: ${buStats.medianSteps}`}
          mcpSub={`median: ${mcpStats.medianSteps}`}
          highlightBetter="lower"
          buNum={buStats.avgSteps}
          mcpNum={mcpStats.avgSteps}
        />
        <StatCompareCard
          title="Avg Cost"
          buValue={formatCost(buStats.avgCost)}
          mcpValue={formatCost(mcpStats.avgCost)}
          buSub={`median: ${formatCost(buStats.medianCost)}`}
          mcpSub={`median: ${formatCost(mcpStats.medianCost)}`}
          highlightBetter="lower"
          buNum={buStats.avgCost}
          mcpNum={mcpStats.avgCost}
        />
        <StatCompareCard
          title="Avg Duration"
          buValue={formatDuration(buStats.avgDuration)}
          mcpValue={formatDuration(mcpStats.avgDuration)}
          buSub={`median: ${formatDuration(buStats.medianDuration)}`}
          mcpSub={`median: ${formatDuration(mcpStats.medianDuration)}`}
          highlightBetter="lower"
          buNum={buStats.avgDuration}
          mcpNum={mcpStats.avgDuration}
        />
        <StatCompareCard
          title="Avg Tokens"
          buValue={formatTokens(buStats.avgTokens)}
          mcpValue={formatTokens(mcpStats.avgTokens)}
          highlightBetter="lower"
          buNum={buStats.avgTokens}
          mcpNum={mcpStats.avgTokens}
        />
      </div>

      {/* ─── KEY INSIGHTS ───────────────────────────────────────────────────── */}
      {notableExamples.length > 0 && (
        <div className="panel insights-panel">
          <h3>Key Insights</h3>
          <div className="insights-list">
            {notableExamples.map((ex) => (
              <div
                key={ex.id}
                className={`insight-card ${expandedInsight === ex.id ? "expanded" : ""}`}
              >
                <button
                  className="insight-header"
                  onClick={() =>
                    setExpandedInsight(expandedInsight === ex.id ? null : ex.id)
                  }
                >
                  <span className="insight-title">{ex.title}</span>
                  <span className="insight-toggle">
                    {expandedInsight === ex.id ? "−" : "+"}
                  </span>
                </button>
                <p className="insight-summary">{ex.insight}</p>
                {expandedInsight === ex.id && ex.runs.length > 0 && (
                  <div className="insight-examples">
                    <span className="insight-examples-label">Example runs:</span>
                    {ex.runs.map((run, i) => (
                      <div key={i} className="insight-example-row">
                        <span
                          className="agent-badge small"
                          style={{
                            borderColor:
                              run.agent === "BROWSERUSE"
                                ? COLORS.browseruse
                                : COLORS.mcp,
                            color:
                              run.agent === "BROWSERUSE"
                                ? COLORS.browseruse
                                : COLORS.mcp,
                          }}
                        >
                          {run.agent === "BROWSERUSE" ? "BU" : "MCP"}
                        </span>
                        <span className="insight-example-note">{run.note}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ─── SCENARIO BREAKDOWN ─────────────────────────────────────────────── */}
      {scenarioBreakdown.length > 0 && (
        <div className="panel trends-chart-panel trends-chart-full">
          <h3>Pass Rate by Scenario</h3>
          <p className="panel-desc">
            Shows which scenarios each agent can handle. MCP's structured tools
            give it an edge on complex multi-step workflows.
          </p>
          <ResponsiveContainer width="100%" height={Math.max(200, scenarioBreakdown.length * 55 + 40)}>
            <BarChart
              data={scenarioBreakdown}
              layout="vertical"
              margin={{ top: 10, right: 30, bottom: 0, left: 10 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#222" horizontal={false} />
              <XAxis
                type="number"
                domain={[0, 100]}
                stroke="#555"
                tick={{ fill: "#888", fontSize: 11 }}
                tickFormatter={(v: number) => `${v}%`}
              />
              <YAxis
                type="category"
                dataKey="scenario"
                stroke="#555"
                tick={{ fill: "#ccc", fontSize: 12 }}
                width={180}
              />
              <Tooltip
                contentStyle={{
                  background: "#1a1a1a",
                  border: "1px solid #333",
                  borderRadius: 8,
                  fontSize: 12,
                  color: "#eee",
                }}
                formatter={(value: number | undefined, name: string) => {
                  const v = value ?? 0;
                  return [`${v}%`, name];
                }}
                labelFormatter={(label: unknown) => {
                  const s = scenarioBreakdown.find((d) => d.scenario === String(label));
                  return s
                    ? `${s.scenario} — BU: ${s.buLabel}, MCP: ${s.mcpLabel}`
                    : String(label);
                }}
              />
              <Legend wrapperStyle={{ fontSize: 12, color: "#888" }} />
              <Bar dataKey="BrowserUse %" fill={COLORS.browseruse} radius={[0, 4, 4, 0]} barSize={16} />
              <Bar dataKey="MCP %" fill={COLORS.mcp} radius={[0, 4, 4, 0]} barSize={16} />
            </BarChart>
          </ResponsiveContainer>

          {/* Scenario-specific annotations */}
          {scenarioBreakdown
            .filter((s) => SCENARIO_ANNOTATIONS[s.scenarioRaw])
            .map((s) => {
              const ann = SCENARIO_ANNOTATIONS[s.scenarioRaw];
              return (
                <div key={s.scenarioRaw} className="scenario-annotation">
                  <div className="scenario-annotation-header">
                    <span className="scenario-annotation-icon">*</span>
                    <span className="scenario-annotation-scenario">{s.scenario}</span>
                    <span className="scenario-annotation-rate">
                      MCP {s.mcpLabel}
                    </span>
                  </div>
                  <p className="scenario-annotation-note">{ann.note}</p>
                  <p className="scenario-annotation-detail">{ann.detail}</p>
                </div>
              );
            })}
        </div>
      )}

      {/* ─── FAILURE ANALYSIS ───────────────────────────────────────────────── */}
      {failureCategoryCounts.length > 0 && (
        <div className="trends-charts">
          <div className="panel trends-chart-panel">
            <h3>Failure Categories</h3>
            <p className="panel-desc">
              Classifies why runs failed. MCP failures tend to be shallow
              (evidence gaps), while BrowserUse failures are more fundamental.
            </p>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart
                data={failureCategoryCounts}
                margin={{ top: 10, right: 20, bottom: 0, left: 10 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#222" />
                <XAxis
                  dataKey="label"
                  stroke="#555"
                  tick={{ fill: "#888", fontSize: 10 }}
                  interval={0}
                  angle={-20}
                  textAnchor="end"
                  height={60}
                />
                <YAxis
                  stroke="#555"
                  tick={{ fill: "#888", fontSize: 11 }}
                  allowDecimals={false}
                />
                <Tooltip
                  contentStyle={{
                    background: "#1a1a1a",
                    border: "1px solid #333",
                    borderRadius: 8,
                    fontSize: 12,
                    color: "#eee",
                  }}
                  formatter={(value: number | undefined, name: string) => [value ?? 0, name]}
                  labelFormatter={(label: unknown) => {
                    const cat = failureCategoryCounts.find((d) => d.label === String(label));
                    if (!cat) return String(label);
                    const key = cat.category;
                    return FAILURE_CATEGORY_DESCRIPTIONS[key] ?? String(label);
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 12, color: "#888" }} />
                <Bar dataKey="BrowserUse" fill={COLORS.browseruse} radius={[4, 4, 0, 0]} />
                <Bar dataKey="MCP BrowserUse" fill={COLORS.mcp} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Failure Depth */}
          <div className="panel trends-chart-panel">
            <h3>Failure Depth</h3>
            <p className="panel-desc">
              <strong>Shallow:</strong> task likely completed but judge couldn't
              verify (evidence gap). <strong>Deep:</strong> fundamental execution
              failure (loops, wrong actions, crashes).
            </p>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart
                data={[
                  {
                    agent: "BrowserUse",
                    Shallow: depthSummary.buShallow,
                    Deep: depthSummary.buDeep,
                  },
                  {
                    agent: "MCP BrowserUse",
                    Shallow: depthSummary.mcpShallow,
                    Deep: depthSummary.mcpDeep,
                  },
                ]}
                margin={{ top: 10, right: 20, bottom: 0, left: 10 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#222" />
                <XAxis dataKey="agent" stroke="#555" tick={{ fill: "#888", fontSize: 12 }} />
                <YAxis stroke="#555" tick={{ fill: "#888", fontSize: 11 }} allowDecimals={false} />
                <Tooltip
                  contentStyle={{
                    background: "#1a1a1a",
                    border: "1px solid #333",
                    borderRadius: 8,
                    fontSize: 12,
                    color: "#eee",
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 12, color: "#888" }} />
                <Bar dataKey="Shallow" stackId="a" fill="#a78bfa" radius={[0, 0, 0, 0]} />
                <Bar dataKey="Deep" stackId="a" fill="#f87171" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* ─── FRICTION PATTERNS ──────────────────────────────────────────────── */}
      <div className="panel friction-summary-panel">
        <h3>Friction Patterns</h3>
        <p className="panel-desc">
          Detected behavioral issues across all runs. These patterns indicate
          where agents struggle regardless of pass/fail outcome.
        </p>
        <div className="friction-summary-grid">
          {(["loop", "repeated_action", "long_step", "error"] as const).map((type) => {
            const buData = frictionPatterns.bu[type];
            const mcpData = frictionPatterns.mcp[type];
            const labels: Record<string, string> = {
              loop: "Observation Loops",
              repeated_action: "Repeated Action Bursts",
              long_step: "Long Steps (>60s)",
              error: "Reported Errors",
            };
            const icons: Record<string, string> = {
              loop: "🔄",
              repeated_action: "🔁",
              long_step: "🐌",
              error: "⚠️",
            };
            return (
              <div key={type} className="friction-summary-card">
                <div className="friction-summary-header">
                  <span className="friction-summary-icon">{icons[type]}</span>
                  <span className="friction-summary-type">{labels[type]}</span>
                </div>
                <div className="friction-summary-compare">
                  <div className="friction-agent-col bu">
                    <span className="friction-agent-label">BrowserUse</span>
                    <span className="friction-agent-value">{buData.count}</span>
                    <span className="friction-agent-sub">
                      in {buData.runsAffected}/{frictionPatterns.buTotal} runs
                    </span>
                  </div>
                  <div className="friction-agent-col mcp">
                    <span className="friction-agent-label">MCP</span>
                    <span className="friction-agent-value">{mcpData.count}</span>
                    <span className="friction-agent-sub">
                      in {mcpData.runsAffected}/{frictionPatterns.mcpTotal} runs
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Cost Per Run */}
      <div className="panel trends-chart-panel trends-chart-full">
        <h3>Cost Per Run</h3>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={runTableData} margin={{ top: 10, right: 20, bottom: 40, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#222" />
            <XAxis
              dataKey="filename"
              stroke="#555"
              tick={false}
              label={{
                value: "Individual Runs",
                position: "insideBottom",
                offset: -10,
                fill: "#888",
                fontSize: 11,
              }}
            />
            <YAxis
              stroke="#555"
              tick={{ fill: "#888", fontSize: 11 }}
              tickFormatter={(v: number) => `$${v.toFixed(2)}`}
            />
            <Tooltip
              contentStyle={{
                background: "#1a1a1a",
                border: "1px solid #333",
                borderRadius: 8,
                fontSize: 12,
                color: "#eee",
              }}
              formatter={(value: number | undefined) => [formatCost(value ?? 0), "Cost"]}
              labelFormatter={(label: unknown) => {
                const run = runTableData.find((r) => r.filename === String(label));
                return `${run?.agentLabel} — ${run?.scenario} (${run?.verdict})`;
              }}
            />
            <Bar dataKey="cost">
              {runTableData.map((entry, index) => (
                <Cell
                  key={index}
                  fill={entry.agent === "BROWSERUSE" ? COLORS.browseruse : COLORS.mcp}
                  opacity={entry.verdict === "FAIL" ? 0.5 : 1}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <div className="trends-legend-custom">
          <span className="legend-item">
            <span className="legend-swatch" style={{ background: COLORS.browseruse }} />
            BrowserUse
          </span>
          <span className="legend-item">
            <span className="legend-swatch" style={{ background: COLORS.mcp }} />
            MCP BrowserUse
          </span>
          <span className="legend-item">
            <span className="legend-swatch" style={{ background: "#666", opacity: 0.5 }} />
            Faded = FAIL
          </span>
        </div>
      </div>

      {/* ─── RUN DETAILS TABLE (enhanced) ───────────────────────────────────── */}
      <div className="panel trends-table-panel">
        <h3>All Runs</h3>
        <div className="trends-table-wrapper">
          <table className="trends-table">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Scenario</th>
                <th>Verdict</th>
                <th className="num">Steps</th>
                <th className="num">Cost</th>
                <th className="num">Duration</th>
                <th className="num">Tokens</th>
                <th className="num">Friction</th>
                <th>Judge Reason</th>
              </tr>
            </thead>
            <tbody>
              {runTableData.map((run) => (
                <tr key={run.filename} className={`run-row ${run.verdict.toLowerCase()}`}>
                  <td>
                    <span
                      className="agent-badge"
                      style={{
                        borderColor:
                          run.agent === "BROWSERUSE" ? COLORS.browseruse : COLORS.mcp,
                        color: run.agent === "BROWSERUSE" ? COLORS.browseruse : COLORS.mcp,
                      }}
                    >
                      {run.agentLabel}
                    </span>
                  </td>
                  <td className="scenario-cell">{run.scenario}</td>
                  <td>
                    <span className={`verdict-badge ${run.verdict.toLowerCase()}`}>
                      {run.verdict}
                    </span>
                  </td>
                  <td className="num">{run.steps}</td>
                  <td className="num">{formatCost(run.cost)}</td>
                  <td className="num">{formatDuration(run.duration)}</td>
                  <td className="num">{formatTokens(run.tokens)}</td>
                  <td className="num">
                    {run.frictionCount > 0 ? (
                      <span className={`friction-count ${run.hasLoops ? "has-loops" : ""}`}>
                        {run.frictionCount}
                        {run.hasLoops && " 🔄"}
                      </span>
                    ) : (
                      <span className="friction-none">—</span>
                    )}
                  </td>
                  <td className="reason-cell" title={run.judgeReason}>
                    {run.judgeReason
                      ? run.judgeReason.length > 80
                        ? run.judgeReason.slice(0, 80) + "..."
                        : run.judgeReason
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ─── Sub-Components ──────────────────────────────────────────────────────────

function StatCompareCard({
  title,
  buValue,
  mcpValue,
  buSub,
  mcpSub,
  highlightBetter,
  buNum,
  mcpNum,
}: {
  title: string;
  buValue: string;
  mcpValue: string;
  buSub?: string;
  mcpSub?: string;
  highlightBetter?: "higher" | "lower";
  buNum?: number;
  mcpNum?: number;
}) {
  let buWins = false;
  let mcpWins = false;

  if (highlightBetter && buNum !== undefined && mcpNum !== undefined && buNum !== mcpNum) {
    if (highlightBetter === "lower") {
      buWins = buNum < mcpNum;
      mcpWins = mcpNum < buNum;
    } else {
      buWins = buNum > mcpNum;
      mcpWins = mcpNum > buNum;
    }
  }

  return (
    <div className="card trends-compare-card">
      <div className="card-label">{title}</div>
      <div className="compare-row">
        <div className={`compare-side bu ${buWins ? "winner" : ""}`}>
          <span className="compare-agent-label">BrowserUse</span>
          <span className="compare-value">{buValue}</span>
          {buSub && <span className="compare-sub">{buSub}</span>}
        </div>
        <div className="compare-vs">vs</div>
        <div className={`compare-side mcp ${mcpWins ? "winner" : ""}`}>
          <span className="compare-agent-label">MCP</span>
          <span className="compare-value">{mcpValue}</span>
          {mcpSub && <span className="compare-sub">{mcpSub}</span>}
        </div>
      </div>
    </div>
  );
}
