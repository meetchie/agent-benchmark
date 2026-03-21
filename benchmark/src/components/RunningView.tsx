import type { StepRecord, SummaryData } from "../lib/types";
import { formatMs, formatTimer } from "../lib/utils";
import { RunningHeader } from "./RunningHeader";
import { StepLog } from "./StepLog";

/** GPT-4o pricing: $2.50/1M input, $10/1M output */
function formatCost(inputTokens: number, outputTokens: number): string {
  const cost = (inputTokens / 1_000_000) * 2.5 + (outputTokens / 1_000_000) * 10;
  if (cost < 0.01) return "<$0.01";
  return "$" + cost.toFixed(2);
}

interface RunningViewProps {
  url: string;
  taskLabel: string;
  isRunning: boolean;
  steps: StepRecord[];
  screenshot: string | null;
  summary: SummaryData | null;
  errorMsg: string | null;
  onRunAgain: () => void;
  onNewTest: () => void;
}

export function RunningView({
  url,
  taskLabel,
  isRunning,
  steps,
  screenshot,
  summary,
  errorMsg,
  onRunAgain,
  onNewTest,
}: RunningViewProps) {
  const isDone = !!summary || (!!errorMsg && !isRunning);
  const isError = !summary && !!errorMsg;
  const isFail = summary && !summary.success;
  const isPass = summary && summary.success;
  const stuckStep = isFail && steps.length > 0 ? steps[steps.length - 1] : null;

  // Find slow steps (>2x average or >3s)
  const avgMs = steps.length > 0 ? steps.reduce((sum, s) => sum + s.elapsed_ms, 0) / steps.length : 0;
  const slowThreshold = Math.max(avgMs * 2, 3000);
  const slowSteps = steps.filter((s, i) => {
    if (isFail && i === steps.length - 1) return false; // stuck step shown separately
    return s.elapsed_ms > slowThreshold;
  }).sort((a, b) => b.elapsed_ms - a.elapsed_ms);

  return (
    <div className="min-h-screen bg-[#f0f4ff] flex flex-col">
      <RunningHeader
        url={url}
        taskLabel={taskLabel}
        isRunning={isRunning}
        totalMs={summary?.total_ms}
        onNewTest={onNewTest}
      />

      <div className="flex-1 flex flex-col p-4 space-y-4 overflow-y-auto">
        {isDone ? (
          /* ===== RESULTS VIEW ===== */
          <>
            {/* Result header card */}
            <div
              className={`border-2 p-5 ${
                isPass
                  ? "border-green-400 bg-green-50"
                  : "border-red-400 bg-red-50"
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <span
                  className={`text-lg font-bold ${
                    isPass ? "text-green-700" : "text-red-700"
                  }`}
                >
                  {isPass ? "✓ PASS" : isError ? "✗ ERROR" : "✗ FAIL"}
                </span>
                {summary && (
                  <div className="flex items-center gap-4">
                    <span className="text-sm text-slate-500 font-mono">
                      {formatTimer(summary.total_ms)}
                    </span>
                    {summary.total_tokens > 0 && (
                      <span className="text-sm text-slate-500 font-mono">
                        {formatCost(summary.input_tokens, summary.output_tokens)}
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Summary text */}
              {(isPass || isFail) && summary?.summary && (
                <p className="text-sm text-slate-700 leading-relaxed">
                  {summary.summary}
                </p>
              )}

              {/* Error message */}
              {isError && (
                <p className="text-sm text-red-700 leading-relaxed">
                  {errorMsg}
                </p>
              )}

              {/* Stuck step — inside the card */}
              {isFail && stuckStep && (
                <div className="mt-3 pt-3 border-t border-red-200">
                  <p className="text-xs font-semibold text-red-600 uppercase tracking-wider mb-1">
                    Where it failed
                  </p>
                  <p className="text-sm text-red-700 font-medium">
                    Step #{stuckStep.step}: {stuckStep.description}
                  </p>
                  <p className="text-xs text-slate-500 mt-1">
                    Spent {formatMs(stuckStep.elapsed_ms)} on this step
                  </p>
                </div>
              )}

              {/* Slow steps — inside the card */}
              {slowSteps.length > 0 && (
                <div className={`mt-3 pt-3 ${isFail ? "border-t border-red-200" : "border-t border-green-200"}`}>
                  <p className="text-xs font-semibold text-amber-600 uppercase tracking-wider mb-2">
                    Slow Steps
                  </p>
                  <div className="space-y-1">
                    {slowSteps.map((step) => (
                      <div key={step.step} className="flex items-center gap-2">
                        <span className="text-xs text-amber-500">⚠</span>
                        <span className="flex-1 text-xs text-slate-600">
                          <span className="text-slate-400 mr-1">#{step.step}</span>
                          {step.description}
                        </span>
                        <span className="text-xs text-amber-600 font-mono font-medium">
                          {formatMs(step.elapsed_ms)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* All steps */}
            <StepLog steps={steps} isRunning={false} />

            {/* Action buttons */}
            <div className="flex gap-3">
              <button
                onClick={onRunAgain}
                className="flex-1 border-2 border-[#3c49ad] bg-[#3c49ad] text-white py-2.5 text-sm font-semibold hover:bg-[#2f3a8a]"
              >
                Run Again
              </button>
              <button
                onClick={onNewTest}
                className="flex-1 border-2 border-slate-300 bg-white text-slate-700 py-2.5 text-sm font-semibold hover:border-[#3c49ad] hover:text-[#3c49ad]"
              >
                New Test
              </button>
            </div>
          </>
        ) : (
          /* ===== RUNNING VIEW ===== */
          <>
            {/* Screenshot area */}
            <div className="border-2 border-slate-200 bg-white overflow-hidden" style={{ maxHeight: "55vh" }}>
              {screenshot ? (
                <img
                  src={screenshot}
                  alt="Agent screenshot"
                  className="w-full block object-contain"
                  style={{ maxHeight: "55vh" }}
                />
              ) : (
                <div className="flex items-center justify-center" style={{ height: "40vh" }}>
                  <svg
                    className="animate-spin h-5 w-5 text-[#3c49ad]"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                </div>
              )}
            </div>

            {/* Steps below */}
            <StepLog steps={steps} isRunning={isRunning} />
          </>
        )}
      </div>
    </div>
  );
}
