import { useState, useEffect, useRef } from "react";
import type { StepRecord, SummaryData } from "../lib/types";
import { formatTimer } from "../lib/utils";
import { RunningHeader } from "./RunningHeader";
import { StepLog } from "./StepLog";
import { ResultsOverlay } from "./ResultsOverlay";
import { DemoModal } from "./DemoModal";

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

  const statItems = [
    { label: "Time", value: formatTimer(displayMs) },
    { label: "Steps", value: String(steps.length) },
    { label: "Cost", value: steps.length > 0 ? estimatedCost : "—" },
    { label: "Tokens", value: steps.length > 0 ? estimatedTokens.toLocaleString() : "—" },
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

        {/* CTA card — I5 style: left-aligned, divider accent */}
        <div className="flex-1 bg-white border-t-[3px] border-t-[#3c49ad] p-5 flex flex-col justify-center">
          <p className="text-base font-bold text-slate-900 mb-1.5">Make your site agent-accessible</p>
          <p className="text-xs text-slate-500 mb-5 leading-relaxed">No website changes needed.</p>
          <div className="flex flex-col gap-2 w-full">
            <a
              href="https://rindler.ai"
              target="_blank"
              rel="noopener noreferrer"
              className="group border-2 border-[#3c49ad] bg-white text-[#3c49ad] py-2.5 text-sm font-semibold text-center hover:bg-[#3c49ad] hover:text-white transition-all"
            >
              <span className="relative inline-flex items-center">
                <span className="transition-transform duration-200 group-hover:-translate-x-2">Check out Rindler</span>
                <span className="absolute left-full ml-1 opacity-0 translate-x-[-6px] group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-200">→</span>
              </span>
            </a>
            <DemoModal>
              <button
                className="group border-2 border-[#3c49ad] bg-white text-[#3c49ad] py-2.5 text-sm font-semibold text-center hover:bg-[#3c49ad] hover:text-white transition-all w-full"
              >
                <span className="relative inline-flex items-center">
                  <span className="transition-transform duration-200 group-hover:-translate-x-2">Book a Demo</span>
                  <span className="absolute left-full ml-1 opacity-0 translate-x-[-6px] group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-200">→</span>
                </span>
              </button>
            </DemoModal>
          </div>
        </div>
      </div>
    </>
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
  resetsIn?: number;
}

export function RunningView({
  url, taskLabel, isRunning, isAnalyzing, analyzingStats,
  steps, screenshot, summary, errorMsg, onRunAgain, onNewTest, remainingRuns, resetsIn,
}: RunningViewProps) {
  const isDone = !!summary || (!!errorMsg && !isRunning && !isAnalyzing);
  const showOverlayTrigger = isDone || isAnalyzing;

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
      <RunningHeader
        isRunning={isRunning}
        onNewTest={onNewTest} remainingRuns={remainingRuns} resetsIn={resetsIn}
      />

      {/* Desktop layout */}
      <div className="hidden md:flex flex-1 p-4 gap-4 overflow-hidden">
        <div className="flex-1 flex flex-col gap-4 min-w-0">
          <div className="relative bg-white overflow-hidden" style={{ height: "55vh", flexShrink: 0 }}>
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
            <StepLog steps={steps} isRunning={isRunning} />
          </div>
        </div>
        <LiveStats url={url} taskLabel={taskLabel} steps={steps} isRunning={isRunning} finalMs={summary?.total_ms ?? analyzingStats?.total_ms} />
      </div>

      {/* Mobile layout */}
      <div className="md:hidden flex-1 flex flex-col p-4 gap-4 overflow-auto">
        {/* Screenshot */}
        <div className="relative bg-white overflow-hidden" style={{ height: "55vh", flexShrink: 0 }}>
          {screenshot ? (
            <img src={screenshot} alt="Agent screenshot" className="w-full h-full object-contain object-top" />
          ) : (
            <div className="w-full h-full flex items-center justify-center">
              <svg className="animate-spin h-5 w-5 text-[#3c49ad]" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            </div>
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
        <LiveStats url={url} taskLabel={taskLabel} steps={steps} isRunning={isRunning} finalMs={summary?.total_ms ?? analyzingStats?.total_ms} />
        {/* Steps */}
        <div className="h-[200px] min-h-0 bg-white border-t-[3px] border-t-[#3c49ad] overflow-hidden">
          <StepLog steps={steps} isRunning={isRunning} />
        </div>
        {/* CTA card */}
        <div className="bg-white border-t-[3px] border-t-[#3c49ad] p-5">
          <p className="text-base font-bold text-slate-900 mb-1.5">Make your site agent-accessible</p>
          <p className="text-xs text-slate-500 mb-4 leading-relaxed">No website changes needed.</p>
          <div className="flex gap-2 w-full">
            <a href="https://rindler.ai" target="_blank" rel="noopener noreferrer"
              className="flex-1 border-2 border-[#3c49ad] bg-white text-[#3c49ad] py-2.5 text-sm font-semibold text-center hover:bg-[#3c49ad] hover:text-white transition-all">
              Learn More
            </a>
            <DemoModal>
              <button className="flex-1 border-2 border-[#3c49ad] bg-white text-[#3c49ad] py-2.5 text-sm font-semibold text-center hover:bg-[#3c49ad] hover:text-white transition-all">
                Book a Demo
              </button>
            </DemoModal>
          </div>
        </div>
      </div>

      {/* Results overlay */}
      {showOverlayTrigger && showOverlay && (
        <ResultsOverlay
          url={url} taskLabel={taskLabel} summary={summary} errorMsg={errorMsg}
          steps={steps} isAnalyzing={isAnalyzing} analyzingStats={analyzingStats}
          onClose={() => { setShowOverlay(false); setBannerDismissed(false); }} onRunAgain={onRunAgain} onNewTest={onNewTest}
        />
      )}
    </div>
  );
}
