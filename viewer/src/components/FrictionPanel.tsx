import type { ParsedLog, FrictionEvent } from "../lib/parseLog";

interface Props {
  log: ParsedLog;
}

const ICON_MAP: Record<string, string> = {
  loop: "↻",
  long_step: "⏱",
  error: "✕",
  repeated_action: "⟳",
  failed_step: "✕",
};

function FrictionItem({ event }: { event: FrictionEvent }) {
  return (
    <div className={`friction-item severity-${event.severity}`}>
      <span className="friction-icon">{ICON_MAP[event.type] ?? "!"}</span>
      <div className="friction-content">
        <span className={`friction-badge ${event.severity}`}>
          {event.severity}
        </span>
        <span className="friction-type">{event.type.replace(/_/g, " ")}</span>
        <p className="friction-desc">{event.description}</p>
      </div>
    </div>
  );
}

export function FrictionPanel({ log }: Props) {
  const hasFriction = log.friction.length > 0;
  const hasJudge = log.judge !== null;

  return (
    <div className="panel friction-panel">
      <h3>Friction &amp; Errors</h3>

      {/* Judge Evaluation */}
      {hasJudge && (
        <div className={`judge-block verdict-${log.judge!.verdict.toLowerCase()}`}>
          <div className="judge-header">
            <span className={`judge-verdict ${log.judge!.verdict.toLowerCase()}`}>
              Judge: {log.judge!.verdict}
            </span>
            {log.judge!.isPosthumous && (
              <span className="judge-posthumous">Posthumous</span>
            )}
          </div>
          <p className="judge-reason">{log.judge!.reason}</p>
          {log.judge!.criteriaMet && (
            <div className="judge-criteria met">
              <strong>Met:</strong> {log.judge!.criteriaMet}
            </div>
          )}
          {log.judge!.criteriaFailed && (
            <div className="judge-criteria failed">
              <strong>Failed:</strong> {log.judge!.criteriaFailed}
            </div>
          )}
          {log.judge!.errorsObserved && (
            <div className="judge-criteria errors">
              <strong>Observed Errors:</strong> {log.judge!.errorsObserved}
            </div>
          )}
        </div>
      )}

      {/* Friction events */}
      {hasFriction ? (
        <div className="friction-list">
          {log.friction.map((f, i) => (
            <FrictionItem key={i} event={f} />
          ))}
        </div>
      ) : (
        <div className="friction-empty">
          No friction detected in the step telemetry.
        </div>
      )}
    </div>
  );
}
