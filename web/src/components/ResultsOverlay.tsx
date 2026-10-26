import { useEffect } from "react";
import type { RunStats, StepRecord, SummaryData, ResultState } from "../lib/types";
import { formatCostUsd } from "../lib/cost";
import { formatTimer } from "../lib/utils";
import { DemoBanner } from "./DemoBanner";
import { Markdown } from "./Markdown";
import { PhaseList } from "./PhaseList";

interface ResultsOverlayProps {
  url: string;
  taskLabel: string;
  summary: SummaryData | null;
  errorMsg: string | null;
  steps: StepRecord[];
  isAnalyzing: boolean;
  analyzingStats: RunStats | null;
  onClose: () => void;
  onRunAgain: () => void;
  onNewTest: () => void;
  /** The backend plays canned runs: the result card says so. */
  demoMode?: boolean;
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
  demoMode = false,
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
  // Priced by the backend at the agent model's rates; no cost cell when it has none.
  const cost = formatCostUsd(stats?.cost_usd);

  const domain = (() => {
    try { return new URL(url).hostname.replace("www.", ""); }
    catch { return url; }
  })();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true">
      <div className="absolute inset-0 modal-backdrop" onClick={onClose} />

      <div className="relative w-full max-w-[520px] max-h-[90vh] border-2 border-slate-200 bg-white m-4 shadow-2xl flex flex-col">
        {demoMode && <DemoBanner />}
        {/* Close button row */}
        <div className="shrink-0 flex justify-end p-4 pb-0 bg-white">
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="modal-scroll px-8 pb-8">
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
                  : stats.total_tokens || 0}
              </span>
            </div>
            {cost !== null && (
              <div className="text-center">
                <span className="text-xs text-slate-400 block">Cost</span>
                <span className="text-base font-bold font-mono text-slate-900">{cost}</span>
              </div>
            )}
          </div>
        )}
        {stats?.agent_model && (
          <p className="text-center text-xs text-slate-400 -mt-2 mb-5">
            Agent model <span className="font-mono text-slate-600">{stats.agent_model}</span>
          </p>
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
            {resultState === "error" && errorMsg && (
              <div className="bg-red-50 border border-red-600 px-4 py-3 mb-5">
                <p className="text-sm text-red-600">{errorMsg}</p>
              </div>
            )}

            {/* A summary means the judge read the steps, an error run's too. */}
            {summary?.summary && (
              <p className="text-sm text-slate-600 leading-relaxed mb-5">{summary.summary}</p>
            )}

            {/* What the agent itself reported: the judge read it, so the user can too. */}
            {summary?.final_report && (
              <div className="mb-5" data-testid="final-report">
                <div className="text-xs text-slate-400 uppercase tracking-wider mb-2">
                  Agent's final report
                  {summary.agent_reported_success === false && (
                    <span className="normal-case tracking-normal text-red-600"> · says it did not succeed</span>
                  )}
                  {summary.agent_reported_success === true && (
                    <span className="normal-case tracking-normal"> · says it succeeded</span>
                  )}
                </div>
                <div className="text-sm text-slate-600 leading-relaxed break-words space-y-2 max-h-40 overflow-y-auto bg-slate-50 border border-slate-200 px-3 py-2">
                  <Markdown text={summary.final_report} />
                </div>
              </div>
            )}

            {(resultState !== "error" || (summary && steps.length > 0)) && (
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
          </>
        )}
        </div>
      </div>
    </div>
  );
}
