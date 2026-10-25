import { useState, useEffect, useRef } from "react";
import type { RunStats, StepRecord, SummaryData } from "../lib/types";
import { formatCostUsd } from "../lib/cost";
import { formatTimer } from "../lib/utils";
import { AgentCard } from "./AgentCard";
import { DemoBanner } from "./DemoBanner";
import { RunningHeader } from "./RunningHeader";
import { StepLog } from "./StepLog";
import { ResultsOverlay } from "./ResultsOverlay";

function LiveStats({
  url, taskLabel, steps, elapsedMs, finalMs,
  finalTotalTokens, finalCostUsd, agentModel, demoMode = false,
}: {
  url: string;
  taskLabel: string;
  steps: StepRecord[];
  elapsedMs: number;
  finalMs?: number;
  /** The backend's total_tokens: input (cache reads included) + cache writes + output. */
  finalTotalTokens?: number;
  finalCostUsd?: number | null;
  agentModel?: string | null;
  demoMode?: boolean;
}) {
  // Snap to real server time when done, otherwise show shared live counter
  const displayMs = finalMs ?? elapsedMs;

  // Tokens are whatever the backend counted, the same total_tokens the results
  // card shows. Adding input_tokens and output_tokens here would leave out the
  // cache writes, which are billed. Until the agent finishes there is no honest
  // number (an estimate from the step count read about 7x low on current
  // models), so the cell shows "—" just like Cost does.
  const totalTokens = finalTotalTokens ?? null;
  const hasRealTokens = totalTokens !== null;

  const domain = (() => {
    try { return new URL(url).hostname.replace("www.", ""); }
    catch { return url; }
  })();

  // Cost is whatever the backend priced the run at. Until the run finishes
  // there is nothing to show, and if the backend has no rate for the model
  // (cost_usd null or absent) the row is dropped and tokens stand alone.
  const costValue = hasRealTokens ? formatCostUsd(finalCostUsd) : "—";

  const statItems = [
    { label: "Time", value: formatTimer(displayMs) },
    { label: "Steps", value: String(steps.length) },
    ...(costValue !== null ? [{ label: "Cost", value: steps.length > 0 ? costValue : "—" }] : []),
    { label: "Tokens", value: totalTokens !== null ? totalTokens.toLocaleString() : "—" },
  ];

  return (
    <>
      {/* Mobile: horizontal stats bar */}
      <div className="md:hidden w-full bg-white border-t-[3px] border-t-[#3c49ad]">
        <div className="px-4 py-3 border-b border-slate-100">
          <p className="text-sm font-semibold text-[#3c49ad]">{domain}</p>
          <p className="text-xs text-slate-500 mt-0.5 leading-snug">{taskLabel}</p>
        </div>
        <div className="flex">
          {statItems.map((s, i) => (
            <div key={s.label} className={`flex-1 text-center py-3 ${i < statItems.length - 1 ? "border-r border-slate-100" : ""}`}>
              <span className="text-[10px] text-slate-500 uppercase tracking-wider block">{s.label}</span>
              <span className="text-sm font-bold text-slate-900 font-mono">{s.value}</span>
            </div>
          ))}
        </div>
        {agentModel && (
          <div className="flex justify-between gap-3 px-4 py-2 border-t border-slate-100 text-[11px] text-slate-500">
            <span className="uppercase tracking-wider">Agent model</span>
            <span className="font-mono text-slate-900 truncate">{agentModel}</span>
          </div>
        )}
      </div>

      {/* Desktop: vertical sidebar */}
      <div className="hidden md:flex w-[300px] shrink-0 flex-col gap-4">
        {/* Stats card */}
        <div className="bg-white border-t-[3px] border-t-[#3c49ad] overflow-hidden flex flex-col" style={{ height: "55vh" }}>
          <div className="px-4 py-4 border-b border-slate-100">
            <p className="text-base font-semibold text-[#3c49ad]">{domain}</p>
            <p className="text-sm text-slate-600 mt-1.5 leading-relaxed">{taskLabel}</p>
          </div>
          {statItems.map((s, i) => (
            <div key={s.label} className={`px-4 py-4 flex justify-between items-center flex-1 ${i < statItems.length - 1 ? "border-b border-slate-100" : ""}`}>
              <span className="text-xs text-slate-600 uppercase tracking-wider">{s.label}</span>
              <span className="text-xl font-bold text-slate-900 font-mono">{s.value}</span>
            </div>
          ))}
        </div>
        <AgentCard model={agentModel} priced={hasRealTokens ? costValue !== null : true} demoMode={demoMode} />
      </div>
    </>
  );
}

/**
 * What the screenshot pane shows when there is no picture: a spinner while the
 * agent is still working, and a calm note once the run is over (a canned demo
 * run, for one, never has a screenshot, so a spinner there would wait forever).
 */
function ScreenshotPlaceholder({ finished }: { finished: boolean }) {
  return (
    <div className="w-full h-full flex items-center justify-center">
      {finished ? (
        <p data-testid="no-screenshot" className="text-sm text-slate-400">No screenshot for this run</p>
      ) : (
        <svg className="animate-spin h-5 w-5 text-[#3c49ad]" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )}
    </div>
  );
}

interface RunningViewProps {
  url: string;
  taskLabel: string;
  isRunning: boolean;
  isAnalyzing: boolean;
  analyzingStats: RunStats | null;
  steps: StepRecord[];
  screenshot: string | null;
  summary: SummaryData | null;
  errorMsg: string | null;
  onRunAgain: () => void;
  onNewTest: () => void;
  remainingRuns?: number;
  runLimit?: number;
  resetsIn?: number;
  /** The backend plays canned runs: show the demo banner. */
  demoMode?: boolean;
}

export function RunningView({
  url, taskLabel, isRunning, isAnalyzing, analyzingStats,
  steps, screenshot, summary, errorMsg, onRunAgain, onNewTest, remainingRuns, runLimit, resetsIn, demoMode = false,
}: RunningViewProps) {
  const isDone = !!summary || (!!errorMsg && !isRunning && !isAnalyzing);
  const showOverlayTrigger = isDone || isAnalyzing;

  const finalMs = summary?.total_ms ?? analyzingStats?.total_ms;
  const finalTotalTokens = summary?.total_tokens ?? analyzingStats?.total_tokens;
  const finalStats = summary ?? analyzingStats;
  const finalCostUsd = finalStats?.cost_usd;
  const agentModel = finalStats?.agent_model;

  // Timer starts when first step arrives (server is ready), stops when server gives final time
  const [elapsedMs, setElapsedMs] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAtRef = useRef<number>(0);
  const timerStartedRef = useRef(false);

  // Reset on each new run
  useEffect(() => {
    if (isRunning) {
      timerStartedRef.current = false;
      setElapsedMs(0);
      if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
    }
  }, [isRunning]);

  // Start on first step
  useEffect(() => {
    if (steps.length === 1 && !timerStartedRef.current) {
      timerStartedRef.current = true;
      startedAtRef.current = Date.now();
      intervalRef.current = setInterval(() => {
        setElapsedMs(Date.now() - startedAtRef.current);
      }, 500);
    }
  }, [steps.length]);

  // Stop when server gives us the real duration
  useEffect(() => {
    if (finalMs && intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finalMs]);

  const [showOverlay, setShowOverlay] = useState(false);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  const handleViewResults = () => {
    setBannerDismissed(true);
    setShowOverlay(true);
  };

  // Reset banner when a new run starts
  useEffect(() => {
    if (!showOverlayTrigger) setBannerDismissed(false);
  }, [showOverlayTrigger]);

  useEffect(() => {
    if (showOverlayTrigger) setShowOverlay(true);
  }, [showOverlayTrigger]);

  return (
    <div className="h-screen bg-[#f0f4ff] flex flex-col overflow-hidden">
      {demoMode && <DemoBanner />}
      <RunningHeader
        isRunning={isRunning}
        elapsedMs={elapsedMs}
        totalMs={finalMs}
        onNewTest={onNewTest}
        remainingRuns={remainingRuns}
        runLimit={runLimit}
        resetsIn={resetsIn}
        demoMode={demoMode}
      />

      {/* Desktop layout */}
      <div className="hidden md:flex flex-1 p-4 gap-4 overflow-hidden">
        <div className="flex-1 flex flex-col gap-4 min-w-0">
          <div className="relative bg-white overflow-hidden" style={{ height: "55vh", flexShrink: 0 }}>
            {screenshot ? (
              <img src={screenshot} alt="Agent screenshot" className="w-full h-full object-cover object-top" />
            ) : (
              <ScreenshotPlaceholder finished={showOverlayTrigger} />
            )}
            {isDone && (
              <div className="absolute inset-0 pointer-events-none" style={{ background: "linear-gradient(to bottom, rgba(60,73,173,0.1) 0%, rgba(60,73,173,0.3) 100%)" }} />
            )}
            {showOverlayTrigger && (
              <div
                className={`absolute bottom-0 left-0 right-0 flex items-center justify-between px-5 py-3 bg-white ${
                  bannerDismissed ? "animate-[slideDown_0.3s_ease-in_forwards]" : "animate-[slideUp_0.3s_ease-out]"
                }`}
                style={bannerDismissed ? { pointerEvents: "none" } : undefined}
              >
                <div className="text-left">
                  <div className="text-[13px] font-semibold text-slate-900">Benchmark complete</div>
                  <div className="text-[11px] text-slate-500">{steps.length} steps{summary?.total_ms ? ` · ${formatTimer(summary.total_ms)}` : ""}</div>
                </div>
                <button onClick={handleViewResults} className="group bg-[#3c49ad] text-white px-5 py-2 text-[13px] font-semibold hover:bg-[#5563c9] transition-colors relative inline-flex items-center">
                  <span className="transition-transform duration-200 group-hover:-translate-x-2">View Results</span>
                  <span className="absolute left-full ml-[-22px] opacity-0 translate-x-[-6px] group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-200">→</span>
                </button>
              </div>
            )}
          </div>
          <div className="flex-1 min-h-0 bg-white border-t-[3px] border-t-[#3c49ad] overflow-hidden">
            <StepLog steps={steps} isRunning={isRunning} totalMs={finalMs ?? elapsedMs} />
          </div>
        </div>
        <LiveStats
          url={url} taskLabel={taskLabel} steps={steps}
          elapsedMs={elapsedMs} finalMs={finalMs}
          finalTotalTokens={finalTotalTokens}
          finalCostUsd={finalCostUsd} agentModel={agentModel} demoMode={demoMode}
        />
      </div>

      {/* Mobile layout */}
      <div className="md:hidden flex-1 flex flex-col p-4 gap-4 overflow-auto">
        {/* Screenshot */}
        <div className="relative bg-white overflow-hidden" style={{ height: "55vh", flexShrink: 0 }}>
          {screenshot ? (
            <img src={screenshot} alt="Agent screenshot" className="w-full h-full object-contain object-top" />
          ) : (
            <ScreenshotPlaceholder finished={showOverlayTrigger} />
          )}
          {isDone && (
            <div className="absolute inset-0 pointer-events-none" style={{ background: "linear-gradient(to bottom, rgba(60,73,173,0.1) 0%, rgba(60,73,173,0.3) 100%)" }} />
          )}
          {showOverlayTrigger && (
            <div
              className={`absolute bottom-0 left-0 right-0 flex items-center justify-between px-5 py-3 bg-white ${
                bannerDismissed ? "animate-[slideDown_0.3s_ease-in_forwards]" : "animate-[slideUp_0.3s_ease-out]"
              }`}
              style={bannerDismissed ? { pointerEvents: "none" } : undefined}
            >
              <div className="text-left">
                <div className="text-[13px] font-semibold text-slate-900">Benchmark complete</div>
                <div className="text-[11px] text-slate-500">{steps.length} steps{summary?.total_ms ? ` · ${formatTimer(summary.total_ms)}` : ""}</div>
              </div>
              <button onClick={handleViewResults} className="group bg-[#3c49ad] text-white px-5 py-2 text-[13px] font-semibold hover:bg-[#5563c9] transition-colors relative inline-flex items-center">
                <span className="transition-transform duration-200 group-hover:-translate-x-2">View Results</span>
                <span className="absolute left-full ml-[-22px] opacity-0 translate-x-[-6px] group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-200">→</span>
              </button>
            </div>
          )}
        </div>
        {/* Horizontal stats bar */}
        <LiveStats url={url} taskLabel={taskLabel} steps={steps} elapsedMs={elapsedMs} finalMs={finalMs} finalTotalTokens={finalTotalTokens} finalCostUsd={finalCostUsd} agentModel={agentModel} demoMode={demoMode} />
        {/* Steps */}
        <div className="h-[200px] min-h-0 bg-white border-t-[3px] border-t-[#3c49ad] overflow-hidden">
          <StepLog steps={steps} isRunning={isRunning} totalMs={finalMs ?? elapsedMs} />
        </div>
      </div>

      {/* Results overlay */}
      {showOverlayTrigger && showOverlay && (
        <ResultsOverlay
          url={url} taskLabel={taskLabel} summary={summary} errorMsg={errorMsg}
          steps={steps} isAnalyzing={isAnalyzing} analyzingStats={analyzingStats}
          onClose={() => { setShowOverlay(false); setBannerDismissed(false); }} onRunAgain={onRunAgain} onNewTest={onNewTest}
          demoMode={demoMode}
        />
      )}
    </div>
  );
}
