import { useEffect } from "react";
import type { StepRecord, SummaryData, ResultState } from "../lib/types";
import { formatTimer } from "../lib/utils";
import { PhaseList } from "./PhaseList";

function formatCost(inputTokens: number, outputTokens: number): string {
  const cost = (inputTokens / 1_000_000) * 2.5 + (outputTokens / 1_000_000) * 10;
  if (cost < 0.01) return "<$0.01";
  return "$" + cost.toFixed(2);
}

interface ResultsOverlayProps {
  url: string;
  taskLabel: string;
  summary: SummaryData | null;
  errorMsg: string | null;
  steps: StepRecord[];
  isAnalyzing: boolean;
  analyzingStats: {
    total_ms: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  } | null;
  onClose: () => void;
  onRunAgain: () => void;
  onNewTest: () => void;
}

const RESULT_CONFIG: Record<ResultState, { label: string; color: string }> = {
  pass: { label: "Pass", color: "text-green-600" },
  fail: { label: "Fail", color: "text-red-600" },
  too_slow: { label: "Agent Too Slow", color: "text-amber-600" },
  error: { label: "Error", color: "text-red-600" },
};

export function ResultsOverlay({
  url,
  taskLabel,
  summary,
  errorMsg,
  steps,
  isAnalyzing,
  analyzingStats,
  onClose,
  onRunAgain,
  onNewTest,
}: ResultsOverlayProps) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const resultState = summary?.result_state ?? (errorMsg ? "error" : null);
  const config = resultState ? RESULT_CONFIG[resultState] : null;
  const stats = summary ?? analyzingStats;

  const domain = (() => {
    try { return new URL(url).hostname.replace("www.", ""); }
    catch { return url; }
  })();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      <div className="relative w-full max-w-[680px] max-h-[90vh] overflow-y-auto border-2 border-slate-200 bg-white p-8 m-4 shadow-2xl">
        <button onClick={onClose} className="absolute top-4 right-4 text-slate-400 hover:text-slate-600 transition-colors">
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        <div className="text-center mb-6">
          <div className="text-xs text-slate-400 uppercase tracking-widest mb-1">Benchmark Result</div>
          {isAnalyzing ? (
            <div className="text-sm font-semibold text-slate-400">Evaluating...</div>
          ) : (
            config && <div className={`text-3xl font-bold ${config.color}`}>{config.label}</div>
          )}
          <div className="text-sm text-slate-500 mt-1">{domain} — {taskLabel}</div>
        </div>

        {stats && (
          <div className="flex justify-center gap-8 py-4 border-t border-b border-slate-100 mb-5">
            <div className="text-center">
              <span className="text-xs text-slate-400 block">Time</span>
              <span className="text-base font-bold font-mono text-slate-900">{formatTimer(stats.total_ms)}</span>
            </div>
            <div className="text-center">
              <span className="text-xs text-slate-400 block">Steps</span>
              <span className="text-base font-bold font-mono text-slate-900">{steps.length}</span>
            </div>
            <div className="text-center">
              <span className="text-xs text-slate-400 block">Tokens</span>
              <span className="text-base font-bold font-mono text-slate-900">
                {stats.total_tokens >= 1000
                  ? (stats.total_tokens / 1000).toFixed(1) + "k"
                  : stats.total_tokens || "—"}
              </span>
            </div>
            <div className="text-center">
              <span className="text-xs text-slate-400 block">Cost</span>
              <span className="text-base font-bold font-mono text-slate-900">
                {stats.input_tokens || stats.output_tokens
                  ? formatCost(stats.input_tokens, stats.output_tokens)
                  : "—"}
              </span>
            </div>
          </div>
        )}

        {isAnalyzing && (
          <div className="flex flex-col items-center gap-3 py-8">
            <svg className="animate-spin h-6 w-6 text-[#3c49ad]" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span className="text-sm text-slate-400">Analyzing run...</span>
          </div>
        )}

        {!isAnalyzing && (
          <>
            {summary?.summary && resultState !== "error" && (
              <p className="text-sm text-slate-600 leading-relaxed mb-5">{summary.summary}</p>
            )}

            {resultState === "error" && errorMsg && (
              <div className="bg-red-50 border border-red-200 px-4 py-3 mb-5 rounded">
                <p className="text-sm text-red-700">{errorMsg}</p>
              </div>
            )}

            {resultState !== "error" && (
              <PhaseList
                phases={summary?.phases ?? []}
                steps={steps}
                isLastPhaseIncomplete={resultState === "too_slow"}
              />
            )}

            {resultState === "error" && steps.length === 0 && (
              <div className="border-t border-slate-100 pt-5 mb-5 text-center">
                <p className="text-sm text-slate-400 italic">No steps were completed</p>
              </div>
            )}

            <div className="flex justify-center gap-4 mb-6">
              <button onClick={onRunAgain} className="text-sm font-semibold text-[#3c49ad] hover:text-[#2f3a8a]">
                ↻ Run Again
              </button>
              <span className="text-slate-300">|</span>
              <button onClick={onNewTest} className="text-sm font-medium text-slate-500 hover:text-slate-700">
                New Test
              </button>
            </div>

            <div className="bg-[#f0f4ff] border border-[#3c49ad]/10 p-5 text-center">
              <div className="text-sm text-slate-600 mb-3">Want to make your site work seamlessly with AI agents?</div>
              <div className="flex gap-3">
                <a href="https://rindler.ai" target="_blank" rel="noopener noreferrer"
                  className="flex-1 border-2 border-[#3c49ad] bg-[#3c49ad] text-white py-2.5 text-sm font-semibold text-center hover:bg-[#2f3a8a]">
                  Check out Rindler →
                </a>
                <a href="https://cal.com/example/demo" target="_blank" rel="noopener noreferrer"
                  className="flex-1 border-2 border-slate-300 bg-white text-slate-700 py-2.5 text-sm font-semibold text-center hover:border-[#3c49ad] hover:text-[#3c49ad]">
                  Book a Demo →
                </a>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
