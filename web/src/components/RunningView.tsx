import { useState, useEffect } from "react";
import type { RunPhase, RunStats, StepRecord, SummaryData } from "../lib/types";
import { formatCostUsd } from "../lib/cost";
import { formatTimer, runPhaseLabel, siteName } from "../lib/utils";
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
  const displayMs = finalMs ?? elapsedMs;

  // Tokens are the backend's total_tokens, the same figure the results card shows. Summing
  // input_tokens and output_tokens would leave out the cache writes, which are billed. A step-count
  // estimate read far too low, so the cell shows "—", like Cost, until the agent finishes.
  const totalTokens = finalTotalTokens ?? null;
  const hasRealTokens = totalTokens !== null;

  const domain = siteName(url);

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

      <div className="hidden md:flex w-[300px] shrink-0 flex-col gap-4">
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
 * What the screenshot pane shows when there is no picture: a spinner while the agent works (with
 * what it is doing, when the backend says), and a short note once the run is over. A canned demo
 * run never has a screenshot, so a spinner there would wait forever.
 */
function ScreenshotPlaceholder({ finished, label }: { finished: boolean; label: string | null }) {
  return (
    <div className="w-full h-full flex flex-col items-center justify-center gap-3">
      {finished ? (
        <p data-testid="no-screenshot" className="text-sm text-slate-400">No screenshot for this run</p>
      ) : (
        <>
          <svg className="animate-spin h-5 w-5 text-[#3c49ad]" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          {label && <p className="text-sm text-slate-500">{label}…</p>}
        </>
      )}
    </div>
  );
}

/**
 * The newest picture of the agent's browser, scaled to fit the pane whole (the
 * browser can be a different shape from the pane: nothing is cut off, the rest
 * of the pane stays plain), with what the run is doing on top while it runs.
 */
function LivePicture({ src, label }: { src: string; label: string | null }) {
  return (
    <>
      <img
        src={src}
        alt="Agent screenshot"
        data-testid="live-frame"
        className="w-full h-full object-contain object-center"
      />
      {label && <PhaseBadge label={label} />}
    </>
  );
}

function PhaseBadge({ label }: { label: string }) {
  return (
    <div
      data-testid="run-phase"
      role="status"
      className="absolute top-3 left-3 flex items-center gap-2 bg-white/95 px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm"
    >
      <span className="h-2 w-2 rounded-full bg-[#3c49ad] dot-pulse" />
      {label}
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
  /** URL (or data URI) of the newest picture of the agent's page. */
  screenshot: string | null;
  /** What the run is doing now, from the status reply; null when unknown or over. */
  runPhase?: RunPhase | null;
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
  steps, screenshot, runPhase = null, summary, errorMsg, onRunAgain, onNewTest, remainingRuns, runLimit, resetsIn, demoMode = false,
}: RunningViewProps) {
  const isDone = !!summary || (!!errorMsg && !isRunning && !isAnalyzing);
  const showOverlayTrigger = isDone || isAnalyzing;
  const phaseLabel = isRunning || isAnalyzing ? runPhaseLabel(runPhase, url) : null;

  const finalMs = summary?.total_ms ?? analyzingStats?.total_ms;
  const finalTotalTokens = summary?.total_tokens ?? analyzingStats?.total_tokens;
  const finalStats = summary ?? analyzingStats;
  const finalCostUsd = finalStats?.cost_usd;
  const agentModel = finalStats?.agent_model;

  // The live clock runs from the moment the server reports the run going (its
  // first run_phase, or the first step from a backend that sends no phase) for as
  // long as the agent is working, so it counts the browser start and the first
  // model turn as the server's total does. It stops the moment the run is no
  // longer running, whether the server sent the real duration (finalMs, shown
  // instead) or the run ended as an error without one, and it never outlives the view.
  const [elapsedMs, setElapsedMs] = useState(0);
  const ticking = isRunning && (steps.length > 0 || runPhase !== null) && finalMs === undefined;

  useEffect(() => {
    if (isRunning) setElapsedMs(0);
  }, [isRunning]);

  useEffect(() => {
    if (!ticking) return;
    const startedAt = Date.now();
    const interval = setInterval(() => setElapsedMs(Date.now() - startedAt), 500);
    return () => clearInterval(interval);
  }, [ticking]);

  // A run that ended as an error without being judged has no result to call complete.
  const bannerTitle = !summary && errorMsg ? "Run ended in an error" : "Benchmark complete";
  const bannerDetail = `${steps.length} steps${finalMs ? ` · ${formatTimer(finalMs)}` : ""}`;

  const [showOverlay, setShowOverlay] = useState(false);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  const handleViewResults = () => {
    setBannerDismissed(true);
    setShowOverlay(true);
  };

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

      <div className="hidden md:flex flex-1 p-4 gap-4 overflow-hidden">
        <div className="flex-1 flex flex-col gap-4 min-w-0">
          <div data-preview className={`relative overflow-hidden ${screenshot ? "bg-slate-100" : "bg-white"}`} style={{ height: "55vh", flexShrink: 0 }}>
            {screenshot ? (
              <LivePicture src={screenshot} label={phaseLabel} />
            ) : (
              <ScreenshotPlaceholder finished={showOverlayTrigger} label={phaseLabel} />
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
                  <div className="text-[13px] font-semibold text-slate-900">{bannerTitle}</div>
                  <div className="text-[11px] text-slate-500">{bannerDetail}</div>
                </div>
                <button onClick={handleViewResults} className="group bg-[#3c49ad] text-white px-5 py-2 text-[13px] font-semibold hover:bg-[#5563c9] transition-colors relative inline-flex items-center">
                  <span className="transition-transform duration-200 group-hover:-translate-x-2">View Results</span>
                  <span className="absolute left-full ml-[-22px] opacity-0 translate-x-[-6px] group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-200">→</span>
                </button>
              </div>
            )}
          </div>
          <div className="flex-1 min-h-0 bg-white border-t-[3px] border-t-[#3c49ad] overflow-hidden">
            <StepLog steps={steps} isRunning={isRunning} totalMs={finalMs ?? elapsedMs} startingLabel={phaseLabel} />
          </div>
        </div>
        <LiveStats
          url={url} taskLabel={taskLabel} steps={steps}
          elapsedMs={elapsedMs} finalMs={finalMs}
          finalTotalTokens={finalTotalTokens}
          finalCostUsd={finalCostUsd} agentModel={agentModel} demoMode={demoMode}
        />
      </div>

      <div className="md:hidden flex-1 flex flex-col p-4 gap-4 overflow-auto">
        <div data-preview className={`relative overflow-hidden ${screenshot ? "bg-slate-100" : "bg-white"}`} style={{ height: "55vh", flexShrink: 0 }}>
          {screenshot ? (
            <LivePicture src={screenshot} label={phaseLabel} />
          ) : (
            <ScreenshotPlaceholder finished={showOverlayTrigger} label={phaseLabel} />
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
                <div className="text-[13px] font-semibold text-slate-900">{bannerTitle}</div>
                <div className="text-[11px] text-slate-500">{bannerDetail}</div>
              </div>
              <button onClick={handleViewResults} className="group bg-[#3c49ad] text-white px-5 py-2 text-[13px] font-semibold hover:bg-[#5563c9] transition-colors relative inline-flex items-center">
                <span className="transition-transform duration-200 group-hover:-translate-x-2">View Results</span>
                <span className="absolute left-full ml-[-22px] opacity-0 translate-x-[-6px] group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-200">→</span>
              </button>
            </div>
          )}
        </div>
        <LiveStats url={url} taskLabel={taskLabel} steps={steps} elapsedMs={elapsedMs} finalMs={finalMs} finalTotalTokens={finalTotalTokens} finalCostUsd={finalCostUsd} agentModel={agentModel} demoMode={demoMode} />
        <div className="h-[200px] min-h-0 bg-white border-t-[3px] border-t-[#3c49ad] overflow-hidden">
          <StepLog steps={steps} isRunning={isRunning} totalMs={finalMs ?? elapsedMs} startingLabel={phaseLabel} />
        </div>
      </div>

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
