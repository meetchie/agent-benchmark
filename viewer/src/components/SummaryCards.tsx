import type { ParsedLog } from "../lib/parseLog";
import { formatDuration, formatCost, formatTokens } from "../lib/parseLog";

interface Props {
  log: ParsedLog;
}

export function SummaryCards({ log }: Props) {
  const avgStepMs =
    log.steps.length > 0
      ? log.steps.reduce((sum, s) => sum + s.durationMs, 0) / log.steps.length
      : 0;

  const actionCounts = log.steps.reduce(
    (acc, s) => {
      acc[s.actionType] = (acc[s.actionType] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>
  );

  const topActions = Object.entries(actionCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3);

  const verdictLabel = log.judge
    ? log.judge.verdict
    : log.success
      ? "PASS"
      : "FAIL";
  const verdictClass = verdictLabel === "PASS" ? "pass" : "fail";

  return (
    <div className="summary-cards">
      {/* Status */}
      <div className={`card card-status ${verdictClass}`}>
        <div className="card-label">Status</div>
        <div className={`card-value verdict-${verdictClass}`}>{verdictLabel}</div>
        <div className="card-sub">
          {log.agent} &middot; {log.successRaw !== "Unknown" ? `Reported: ${log.successRaw}` : ""}
        </div>
      </div>

      {/* Duration */}
      <div className="card">
        <div className="card-label">Duration</div>
        <div className="card-value">{formatDuration(log.durationSeconds)}</div>
        <div className="card-sub">
          avg {formatDuration(avgStepMs / 1000)}/step &middot; {log.steps.length} steps
        </div>
      </div>

      {/* Cost */}
      <div className="card">
        <div className="card-label">Total Cost</div>
        <div className="card-value">{formatCost(log.costUsd)}</div>
        <div className="card-sub">
          {formatTokens(log.tokensInput)} in / {formatTokens(log.tokensOutput)} out &middot;{" "}
          {formatTokens(log.tokensTotal)} total
        </div>
      </div>

      {/* Steps */}
      <div className="card">
        <div className="card-label">Steps</div>
        <div className="card-value">{log.steps.length}</div>
        <div className="card-sub">
          {topActions.map(([action, count]) => `${action}:${count}`).join(" · ")}
        </div>
      </div>
    </div>
  );
}
