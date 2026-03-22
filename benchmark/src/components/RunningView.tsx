import { useState, useEffect, useRef } from "react";
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

function LiveStats({ steps }: { steps: StepRecord[] }) {
  const [elapsed, setElapsed] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    setElapsed(0);
    intervalRef.current = setInterval(() => {
      setElapsed((prev) => prev + 1000);
    }, 1000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  // Estimate tokens from steps (rough: ~3000 tokens per step for GPT-4o)
  const estimatedTokens = steps.length * 3000;
  const estimatedCost = formatCost(estimatedTokens * 0.8, estimatedTokens * 0.2);

  return (
    <div className="w-[220px] shrink-0 space-y-4">
      {/* Time elapsed */}
      <div className="border-2 border-slate-200 bg-white p-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Time Elapsed</p>
        <p className="text-2xl font-bold text-slate-900 font-mono">{formatTimer(elapsed)}</p>
      </div>

      {/* Steps completed */}
      <div className="border-2 border-slate-200 bg-white p-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Steps</p>
        <p className="text-2xl font-bold text-slate-900 font-mono">{steps.length}</p>
      </div>

      {/* Estimated cost */}
      <div className="border-2 border-slate-200 bg-white p-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Est. Cost</p>
        <p className="text-2xl font-bold text-slate-900 font-mono">{steps.length > 0 ? estimatedCost : "—"}</p>
      </div>

      {/* Estimated tokens */}
      <div className="border-2 border-slate-200 bg-white p-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Est. Tokens</p>
        <p className="text-2xl font-bold text-slate-900 font-mono">{steps.length > 0 ? estimatedTokens.toLocaleString() : "—"}</p>
      </div>
    </div>
  );
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
  remainingRuns?: number;
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
  remainingRuns,
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
    if (isFail && i === steps.length - 1) return false;
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
        remainingRuns={remainingRuns}
      />

      <div className="flex-1 flex p-4 gap-4 overflow-hidden">
        {/* LEFT — always same fixed layout: top section (55vh) + bottom section (rest) */}
        <div className="flex-1 flex flex-col gap-4 min-w-0">
          {/* TOP SECTION — fixed 55vh, screenshot or results */}
          <div className="border-2 border-slate-200 bg-white overflow-hidden" style={{ height: "55vh", flexShrink: 0 }}>
            {isDone ? (
              /* Results inside the fixed box */
              <div className="h-full overflow-y-auto p-5">
                <div
                  className={`border-2 p-5 mb-4 ${
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

                  {(isPass || isFail) && summary?.summary && (
                    <p className="text-sm text-slate-700 leading-relaxed">
                      {summary.summary}
                    </p>
                  )}

                  {isError && (
                    <p className="text-sm text-red-700 leading-relaxed">
                      {errorMsg}
                    </p>
                  )}

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

                {/* Token breakdown */}
                {summary && summary.total_tokens > 0 && (
                  <div className="border-2 border-slate-200 bg-slate-50 p-4 mb-4">
                    <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Usage</p>
                    <div className="flex gap-6 text-sm text-slate-600 font-mono">
                      <div>
                        <span className="text-slate-400 text-xs block">Input</span>
                        {summary.input_tokens.toLocaleString()}
                      </div>
                      <div>
                        <span className="text-slate-400 text-xs block">Output</span>
                        {summary.output_tokens.toLocaleString()}
                      </div>
                      <div>
                        <span className="text-slate-400 text-xs block">Total</span>
                        {summary.total_tokens.toLocaleString()}
                      </div>
                      <div>
                        <span className="text-slate-400 text-xs block">Cost</span>
                        {formatCost(summary.input_tokens, summary.output_tokens)}
                      </div>
                    </div>
                  </div>
                )}

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
              </div>
            ) : screenshot ? (
              /* Screenshot — fills container, crops to fit */
              <img
                src={screenshot}
                alt="Agent screenshot"
                className="w-full h-full object-cover object-top"
              />
            ) : (
              /* Loading spinner */
              <div className="w-full h-full flex items-center justify-center">
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

          {/* BOTTOM SECTION — fills remaining space, scrolls internally */}
          <div className="flex-1 min-h-0 overflow-y-auto">
            <StepLog steps={steps} isRunning={isDone ? false : isRunning} />
          </div>
        </div>

        {/* RIGHT — live stats sidebar (only while running) */}
        {!isDone && (
          <LiveStats steps={steps} />
        )}
      </div>
    </div>
  );
}
