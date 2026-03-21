import type { SummaryData, StepRecord } from "../lib/types";
import { formatMs, formatTimer } from "../lib/utils";

interface ResultsOverlayProps {
  summary: SummaryData | null;
  errorMsg: string | null;
  steps: StepRecord[];
  onRunAgain: () => void;
  onNewTest: () => void;
}

export function ResultsOverlay({
  summary,
  errorMsg,
  steps,
  onRunAgain,
  onNewTest,
}: ResultsOverlayProps) {
  const isError = !summary && !!errorMsg;
  const isFail = summary && !summary.success;
  const isPass = summary && summary.success;

  const stuckStep = isFail && steps.length > 0 ? steps[steps.length - 1] : null;

  return (
    <div className="absolute inset-0 bg-black/40 flex items-center justify-center z-10">
      <div
        className={`w-full max-w-md border-2 p-6 ${
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
            <span className="text-sm text-slate-500 font-mono">
              {formatTimer(summary.total_ms)}
            </span>
          )}
        </div>

        {isPass && summary.summary && (
          <p className="text-sm text-slate-700 leading-relaxed mb-4">
            {summary.summary}
          </p>
        )}

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

        {isFail && !stuckStep && summary.summary && (
          <p className="text-sm text-slate-700 leading-relaxed mb-4">
            {summary.summary}
          </p>
        )}

        {isError && (
          <p className="text-sm text-red-700 leading-relaxed mb-4">
            {errorMsg}
          </p>
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
    </div>
  );
}
