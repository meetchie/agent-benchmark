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

      {isDone ? (
        /* ===== RESULTS: Single flowing card (Option D) ===== */
        <div className="flex-1 overflow-y-auto flex justify-center p-6">
          <div className="w-full max-w-[680px] border-2 border-slate-200 bg-white p-8">
            {/* Big centered result */}
            <div className="text-center mb-6">
              <div className="text-xs text-slate-400 uppercase tracking-widest mb-1">Benchmark Result</div>
              <div className={`text-3xl font-bold ${isPass ? "text-green-600" : "text-red-600"}`}>
                {isPass ? "PASS" : isError ? "ERROR" : "FAIL"}
              </div>
              {url && (
                <div className="text-sm text-slate-500 mt-1">
                  {(() => { try { return new URL(url).hostname.replace("www.", ""); } catch { return url; } })()} — {taskLabel}
                </div>
              )}
            </div>

            {/* Stats bar */}
            <div className="flex justify-center gap-8 py-4 border-t border-b border-slate-100 mb-5">
              {summary && (
                <>
                  <div className="text-center">
                    <span className="text-xs text-slate-400 block">Time</span>
                    <span className="text-base font-bold font-mono text-slate-900">{formatTimer(summary.total_ms)}</span>
                  </div>
                  <div className="text-center">
                    <span className="text-xs text-slate-400 block">Steps</span>
                    <span className="text-base font-bold font-mono text-slate-900">{steps.length}</span>
                  </div>
                  {summary.total_tokens > 0 && (
                    <>
                      <div className="text-center">
                        <span className="text-xs text-slate-400 block">Tokens</span>
                        <span className="text-base font-bold font-mono text-slate-900">
                          {summary.total_tokens >= 1000
                            ? (summary.total_tokens / 1000).toFixed(1) + "k"
                            : summary.total_tokens}
                        </span>
                      </div>
                      <div className="text-center">
                        <span className="text-xs text-slate-400 block">Cost</span>
                        <span className="text-base font-bold font-mono text-slate-900">
                          {formatCost(summary.input_tokens, summary.output_tokens)}
                        </span>
                      </div>
                    </>
                  )}
                </>
              )}
            </div>

            {/* Summary text */}
            {(isPass || isFail) && summary?.summary && (
              <p className="text-sm text-slate-600 leading-relaxed mb-5">
                {summary.summary}
              </p>
            )}

            {/* Error message */}
            {isError && (
              <p className="text-sm text-red-600 leading-relaxed mb-5">
                {errorMsg}
              </p>
            )}

            {/* Where it failed */}
            {isFail && stuckStep && (
              <div className="bg-red-50 border border-red-200 px-4 py-3 mb-5">
                <p className="text-xs font-semibold text-red-600 uppercase tracking-wider mb-1">Where it failed</p>
                <p className="text-sm text-red-700 font-medium">
                  Step #{stuckStep.step}: {stuckStep.description}
                </p>
                <p className="text-xs text-slate-500 mt-1">
                  Spent {formatMs(stuckStep.elapsed_ms)} on this step
                </p>
              </div>
            )}

            {/* Slow steps */}
            {slowSteps.length > 0 && (
              <div className="bg-amber-50 border border-amber-200 px-4 py-3 mb-5">
                <p className="text-xs font-semibold text-amber-600 uppercase tracking-wider mb-2">Slow Steps</p>
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

            {/* All steps */}
            <div className="border-t border-slate-100 pt-5 mb-5">
              <div className="text-xs text-slate-400 uppercase tracking-wider mb-3">All Steps</div>
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {steps.map((step) => (
                  <div key={step.step} className="flex items-start gap-2 text-xs text-slate-600">
                    <span className="text-green-500 shrink-0 mt-0.5">✓</span>
                    <span className="text-slate-400 shrink-0">#{step.step}</span>
                    <span className="flex-1">{step.description}</span>
                    <span className="text-slate-400 font-mono shrink-0">{formatMs(step.elapsed_ms)}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex gap-3 mb-6">
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

            {/* CTA section */}
            <div className="border-t border-slate-100 pt-5 text-center">
              <div className="text-base font-semibold text-slate-900 mb-1">Want to make your site agent-ready?</div>
              <div className="text-sm text-slate-500 mb-4">Rindler turns any website into a deterministic API for AI agents.</div>
              <div className="flex gap-3">
                <a
                  href="https://rindler.ai"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex-1 border-2 border-[#3c49ad] bg-[#3c49ad] text-white py-2.5 text-sm font-semibold text-center hover:bg-[#2f3a8a]"
                >
                  Check out Rindler →
                </a>
                <a
                  href="https://rindler.ai"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex-1 border-2 border-slate-300 bg-white text-slate-700 py-2.5 text-sm font-semibold text-center hover:border-[#3c49ad] hover:text-[#3c49ad]"
                >
                  Book a Demo →
                </a>
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* ===== RUNNING: Screenshot + steps + stats ===== */
        <div className="flex-1 flex p-4 gap-4 overflow-hidden">
          <div className="flex-1 flex flex-col gap-4 min-w-0">
            {/* Screenshot — fixed 55vh */}
            <div className="border-2 border-slate-200 bg-white overflow-hidden" style={{ height: "55vh", flexShrink: 0 }}>
              {screenshot ? (
                <img
                  src={screenshot}
                  alt="Agent screenshot"
                  className="w-full h-full object-cover object-top"
                />
              ) : (
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

            {/* Steps */}
            <div className="flex-1 min-h-0 overflow-y-auto">
              <StepLog steps={steps} isRunning={isRunning} />
            </div>
          </div>

          {/* Stats sidebar */}
          <LiveStats steps={steps} />
        </div>
      )}
    </div>
  );
}
