import type { StepRecord, SummaryData } from "../lib/types";
import { formatMs, formatTimer } from "../lib/utils";
import { RunningHeader } from "./RunningHeader";
import { StepLog } from "./StepLog";

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
        {/* Screenshot or Results — they replace each other */}
        {isDone ? (
          /* Results card — replaces screenshot when done */
          <div
            className={`border-2 p-6 ${
              isPass
                ? "border-green-400 bg-green-50"
                : "border-red-400 bg-red-50"
            }`}
          >
            <div className="flex items-center justify-between mb-3">
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
                    <span className="text-xs text-slate-400 font-mono">
                      {summary.total_tokens.toLocaleString()} tokens
                    </span>
                  )}
                </div>
              )}
            </div>

            {/* Pass summary */}
            {isPass && summary.summary && (
              <p className="text-sm text-slate-700 leading-relaxed mb-4">
                {summary.summary}
              </p>
            )}

            {/* Fail — show which step it got stuck on */}
            {isFail && stuckStep && (
              <div className="mb-4 space-y-1">
                <p className="text-sm text-red-700 font-medium">
                  Stuck on step #{stuckStep.step}: {stuckStep.description}
                </p>
                <p className="text-xs text-slate-500">
                  Spent {formatMs(stuckStep.elapsed_ms)} on this step
                </p>
                {summary.summary && (
                  <p className="text-sm text-slate-700 mt-2 leading-relaxed">
                    {summary.summary}
                  </p>
                )}
              </div>
            )}

            {/* Fail without steps */}
            {isFail && !stuckStep && summary.summary && (
              <p className="text-sm text-slate-700 leading-relaxed mb-4">
                {summary.summary}
              </p>
            )}

            {/* Error */}
            {isError && (
              <p className="text-sm text-red-700 leading-relaxed mb-4">
                {errorMsg}
              </p>
            )}

            {/* Token breakdown */}
            {summary && summary.total_tokens > 0 && (
              <div className="flex gap-4 mb-4 text-xs text-slate-400 font-mono">
                <span>Input: {summary.input_tokens.toLocaleString()}</span>
                <span>Output: {summary.output_tokens.toLocaleString()}</span>
                <span>Total: {summary.total_tokens.toLocaleString()}</span>
              </div>
            )}

            <div className="flex gap-3">
              <button
                onClick={onRunAgain}
                className="flex-1 border-2 border-[#3c49ad] bg-[#3c49ad] text-white py-2 text-sm font-semibold hover:bg-[#2f3a8a]"
              >
                Run Again
              </button>
              <button
                onClick={onNewTest}
                className="flex-1 border-2 border-slate-300 bg-white text-slate-700 py-2 text-sm font-semibold hover:border-[#3c49ad] hover:text-[#3c49ad]"
              >
                New Test
              </button>
            </div>
          </div>
        ) : (
          /* Screenshot area — capped height so steps are always visible */
          <div className="border-2 border-slate-200 bg-white overflow-hidden" style={{ maxHeight: "55vh" }}>
            {screenshot ? (
              <img
                src={screenshot}
                alt="Agent screenshot"
                className="w-full block object-contain"
                style={{ maxHeight: "55vh" }}
              />
            ) : (
              <div className="flex items-center justify-center" style={{ height: "55vh" }}>
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
        )}

        {/* Steps below */}
        <StepLog steps={steps} isRunning={isRunning} />
      </div>
    </div>
  );
}
