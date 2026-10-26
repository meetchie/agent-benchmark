import { useState } from "react";
import type { ParsedLog, Step } from "../lib/parseLog";
import { formatDuration, formatCost, formatTokens } from "../lib/parseLog";

interface Props {
  log: ParsedLog;
}

const ACTION_ICONS: Record<string, string> = {
  navigate: "🧭",
  click: "👆",
  scroll: "📜",
  send_keys: "⌨️",
  wait: "⏳",
  extract: "📋",
  input_text: "✏️",
};

function getStepClass(step: Step, log: ParsedLog): string {
  const inLoop = log.friction.some(
    (f) => f.type === "loop" && f.stepIndices.includes(step.index)
  );
  if (inLoop) return "step-loop";

  if (step.durationMs > 300_000) return "step-critical";
  if (step.durationMs > 60_000) return "step-slow";

  return "step-ok";
}

export function StepTimeline({ log }: Props) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const maxDuration = Math.max(...log.steps.map((s) => s.durationMs), 1);

  return (
    <div className="panel timeline-panel">
      <h3>Step Timeline</h3>
      <div className="timeline-header-row">
        <span className="th-step">#</span>
        <span className="th-action">Action</span>
        <span className="th-duration">Duration</span>
        <span className="th-bar"></span>
        <span className="th-cost">Cost</span>
        <span className="th-tokens">Tokens</span>
      </div>
      <div className="timeline-list">
        {log.steps.map((step) => {
          const cls = getStepClass(step, log);
          const isExpanded = expanded === step.index;
          const barWidth = Math.max(
            (step.durationMs / maxDuration) * 100,
            2
          );

          return (
            <div key={step.index}>
              <div
                className={`timeline-row ${cls} ${isExpanded ? "expanded" : ""}`}
                onClick={() =>
                  setExpanded(isExpanded ? null : step.index)
                }
              >
                <span className="td-step">{step.index}</span>
                <span className="td-action">
                  <span className="action-icon">
                    {ACTION_ICONS[step.actionType] ?? "•"}
                  </span>
                  {step.actionType}
                </span>
                <span className="td-duration">
                  {formatDuration(step.durationMs / 1000)}
                </span>
                <span className="td-bar">
                  <div
                    className={`bar-fill bar-${cls}`}
                    style={{ width: `${barWidth}%` }}
                  />
                </span>
                <span className="td-cost">{formatCost(step.costUsd)}</span>
                <span className="td-tokens">
                  {formatTokens(step.tokensInput + step.tokensOutput)}
                </span>
              </div>
              {isExpanded && (
                <div className="timeline-detail">
                  <div className="detail-grid">
                    <div>
                      <span className="detail-label">Start</span>
                      <span className="detail-value">
                        {step.startTime
                          ? new Date(step.startTime).toLocaleTimeString()
                          : "—"}
                      </span>
                    </div>
                    <div>
                      <span className="detail-label">End</span>
                      <span className="detail-value">
                        {step.endTime
                          ? new Date(step.endTime).toLocaleTimeString()
                          : "—"}
                      </span>
                    </div>
                    <div>
                      <span className="detail-label">Tokens In</span>
                      <span className="detail-value">
                        {step.tokensInput.toLocaleString()}
                      </span>
                    </div>
                    <div>
                      <span className="detail-label">Tokens Out</span>
                      <span className="detail-value">
                        {step.tokensOutput.toLocaleString()}
                      </span>
                    </div>
                    {step.observationHash && (
                      <div className="detail-full">
                        <span className="detail-label">Observation Hash</span>
                        <span className="detail-value mono">
                          {step.observationHash.slice(0, 16)}...
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
