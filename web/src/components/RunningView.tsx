import { useState, useEffect, useRef } from "react";
import type { StepRecord, SummaryData } from "../lib/types";
import { formatTimer } from "../lib/utils";
import { RunningHeader } from "./RunningHeader";
import { StepLog } from "./StepLog";
import { ResultsOverlay } from "./ResultsOverlay";

/** GPT-4o pricing: $2.50/1M input, $10/1M output */
function formatCost(inputTokens: number, outputTokens: number): string {
  const cost = (inputTokens / 1_000_000) * 2.5 + (outputTokens / 1_000_000) * 10;
  if (cost < 0.01) return "<$0.01";
  return "$" + cost.toFixed(2);
}

function LiveStats({ url, taskLabel, steps, isRunning, finalMs }: { url: string; taskLabel: string; steps: StepRecord[]; isRunning: boolean; finalMs?: number }) {
  const [elapsed, setElapsed] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (isRunning) {
      setElapsed(0);
      intervalRef.current = setInterval(() => {
        setElapsed((prev) => prev + 1000);
      }, 1000);
    } else if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isRunning]);

  // Smooth counter while running, snap to real data when done
  const displayMs = finalMs ?? elapsed;

  // Estimate tokens from steps (rough: ~3000 tokens per step for GPT-4o)
  const estimatedTokens = steps.length * 3000;
  const estimatedCost = formatCost(estimatedTokens * 0.8, estimatedTokens * 0.2);

  const domain = (() => {
    try { return new URL(url).hostname.replace("www.", ""); }
    catch { return url; }
  })();

  return (
    <div className="w-[300px] shrink-0">
      <div className="bg-white border border-slate-200 border-t-[3px] border-t-[#3c49ad] rounded-b-lg overflow-hidden flex flex-col" style={{ height: "45vh" }}>
        {/* Site + task info */}
        <div className="px-4 py-4 border-b border-slate-100">
          <p className="text-sm font-semibold text-[#3c49ad]">{domain}</p>
          <p className="text-xs text-slate-400 mt-1 leading-relaxed">{taskLabel}</p>
        </div>

        {/* Time elapsed */}
        <div className="px-4 py-4 border-b border-slate-100 flex justify-between items-baseline flex-1">
          <span className="text-xs text-slate-400 uppercase tracking-wider">Time</span>
          <span className="text-xl font-bold text-slate-900 font-mono">{formatTimer(displayMs)}</span>
        </div>

        {/* Steps completed */}
        <div className="px-4 py-4 border-b border-slate-100 flex justify-between items-baseline flex-1">
          <span className="text-xs text-slate-400 uppercase tracking-wider">Steps</span>
          <span className="text-xl font-bold text-slate-900 font-mono">{steps.length}</span>
        </div>

        {/* Estimated cost */}
        <div className="px-4 py-4 border-b border-slate-100 flex justify-between items-baseline flex-1">
          <span className="text-xs text-slate-400 uppercase tracking-wider">Cost</span>
          <span className="text-xl font-bold text-slate-900 font-mono">{steps.length > 0 ? estimatedCost : "—"}</span>
        </div>

        {/* Estimated tokens */}
        <div className="px-4 py-4 flex justify-between items-baseline flex-1">
          <span className="text-xs text-slate-400 uppercase tracking-wider">Tokens</span>
          <span className="text-xl font-bold text-slate-900 font-mono">{steps.length > 0 ? estimatedTokens.toLocaleString() : "—"}</span>
        </div>
      </div>
    </div>
  );
}

interface RunningViewProps {
  url: string;
  taskLabel: string;
  isRunning: boolean;
  isAnalyzing: boolean;
  analyzingStats: {
    total_ms: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  } | null;
  steps: StepRecord[];
  screenshot: string | null;
  summary: SummaryData | null;
  errorMsg: string | null;
  onRunAgain: () => void;
  onNewTest: () => void;
  remainingRuns?: number;
}

export function RunningView({
  url, taskLabel, isRunning, isAnalyzing, analyzingStats,
  steps, screenshot, summary, errorMsg, onRunAgain, onNewTest, remainingRuns,
}: RunningViewProps) {
  const isDone = !!summary || (!!errorMsg && !isRunning && !isAnalyzing);
  const showOverlayTrigger = isDone || isAnalyzing;

  const [showOverlay, setShowOverlay] = useState(false);

  useEffect(() => {
    if (showOverlayTrigger) setShowOverlay(true);
  }, [showOverlayTrigger]);

  return (
    <div className="h-screen bg-[#f0f4ff] flex flex-col overflow-hidden">
      <RunningHeader
        isRunning={isRunning}
        totalMs={summary?.total_ms} onNewTest={onNewTest} remainingRuns={remainingRuns}
      />

      {/* Running view — always visible */}
      <div className="flex-1 flex p-4 gap-4 overflow-hidden">
        <div className="flex-1 flex flex-col gap-4 min-w-0">
          <div className="border-2 border-slate-200 bg-white overflow-hidden" style={{ height: "45vh", flexShrink: 0 }}>
            {screenshot ? (
              <img src={screenshot} alt="Agent screenshot" className="w-full h-full object-cover object-top" />
            ) : (
              <div className="w-full h-full flex items-center justify-center">
                <svg className="animate-spin h-5 w-5 text-[#3c49ad]" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              </div>
            )}
          </div>
          <div className="flex-1 min-h-0 border-2 border-slate-200 bg-white overflow-hidden">
            <StepLog steps={steps} isRunning={isRunning} />
          </div>
        </div>
        <LiveStats url={url} taskLabel={taskLabel} steps={steps} isRunning={isRunning} finalMs={summary?.total_ms ?? analyzingStats?.total_ms} />
      </div>

      {/* View Results button */}
      {showOverlayTrigger && !showOverlay && (
        <button
          onClick={() => setShowOverlay(true)}
          className="fixed bottom-6 right-6 bg-[#3c49ad] text-white px-5 py-3 rounded-full shadow-lg text-sm font-semibold hover:bg-[#2f3a8a] transition-colors z-40"
        >
          View Results
        </button>
      )}

      {/* Results overlay */}
      {showOverlayTrigger && showOverlay && (
        <ResultsOverlay
          url={url} taskLabel={taskLabel} summary={summary} errorMsg={errorMsg}
          steps={steps} isAnalyzing={isAnalyzing} analyzingStats={analyzingStats}
          onClose={() => setShowOverlay(false)} onRunAgain={onRunAgain} onNewTest={onNewTest}
        />
      )}
    </div>
  );
}
