import { useEffect, useRef, useState, useCallback } from "react";
import type { StepRecord } from "../lib/types";
import { formatMs } from "../lib/utils";

interface StepLogProps {
  steps: StepRecord[];
  isRunning: boolean;
  totalMs?: number;
  /** What the run is doing before its first step ("Starting the browser"); a generic line when unknown. */
  startingLabel?: string | null;
}

// The line sits 16px in, dots are centered on it, and the text starts at 32px.
const LINE_LEFT = 16; // px from left edge to line center
const DOT_SIZE = 10;  // px (completed dots)
const ACTIVE_DOT_SIZE = 10; // px (active dots)
const DOT_OFFSET = LINE_LEFT - DOT_SIZE / 2; // centers the dot on the line
const LINE_PAD = 8;   // px of gradient fade before first dot / after last dot

export function StepLog({ steps, isRunning, totalMs, startingLabel }: StepLogProps) {
  const currentStep = isRunning && steps.length > 0 ? steps[steps.length - 1] : null;
  const completedSteps = currentStep ? steps.slice(0, -1) : steps;
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [prevStepCount, setPrevStepCount] = useState(0);
  const [lineHeight, setLineHeight] = useState(0);

  const lastDotRef = useRef<HTMLDivElement>(null);

  // Measure line height to end at the bottom of the last dot
  const measureHeight = useCallback(() => {
    if (contentRef.current && lastDotRef.current) {
      const containerTop = contentRef.current.getBoundingClientRect().top;
      const dotRect = lastDotRef.current.getBoundingClientRect();
      const dotBottom = dotRect.bottom - containerTop;
      setLineHeight(dotBottom);
    } else if (contentRef.current) {
      setLineHeight(contentRef.current.scrollHeight);
    }
  }, []);

  useEffect(() => {
    measureHeight();
  }, [steps.length, isRunning, measureHeight]);

  // Also observe resize in case text wraps differently
  useEffect(() => {
    if (!contentRef.current) return;
    const observer = new ResizeObserver(measureHeight);
    observer.observe(contentRef.current);
    return () => observer.disconnect();
  }, [measureHeight]);

  // Track which steps are "new" for entry animation
  useEffect(() => {
    setPrevStepCount(steps.length);
  }, [steps.length]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [steps.length]);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="px-3 py-2 border-b border-slate-100 flex justify-between items-center shrink-0">
        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
          Steps
        </span>
        <span className="text-xs text-slate-400 font-mono">
          {totalMs ? formatMs(totalMs) : ""}
        </span>
      </div>

      <div className="relative flex-1 overflow-hidden">
        <div className="absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-white to-transparent z-10 pointer-events-none" />

        <div ref={scrollRef} className="h-full overflow-y-auto py-4">
        <div ref={contentRef} className="relative" style={{ paddingLeft: 32 }}>
          {lineHeight > 0 && (
            <div
              className="absolute"
              style={{
                left: LINE_LEFT - 1,
                top: -LINE_PAD,
                width: 2,
                height: lineHeight + LINE_PAD + LINE_PAD,
                background: `linear-gradient(transparent 0%, #3c49ad ${LINE_PAD}px, #3c49ad calc(100% - ${LINE_PAD}px), transparent 100%)`,
                transition: "height 0.4s cubic-bezier(0.22, 1, 0.36, 1)",
              }}
            />
          )}

          {steps.length === 0 && isRunning && (
            <div className="relative pb-4 step-enter leading-4">
              <div
                ref={lastDotRef}
                className="absolute rounded-full bg-[#3c49ad] dot-pulse"
                style={{ left: DOT_OFFSET - 32, top: 5, width: ACTIVE_DOT_SIZE, height: ACTIVE_DOT_SIZE }}
              />
              <span className="text-xs text-slate-400">{startingLabel ? `${startingLabel}…` : "Starting agent..."}</span>
            </div>
          )}

          {completedSteps.map((step) => (
            <div
              key={step.step}
              className={`relative pb-5 leading-4${step.step > prevStepCount - 1 ? " step-enter" : ""}`}
            >
              <div
                ref={!currentStep && step.step === completedSteps.length ? lastDotRef : undefined}
                className="absolute rounded-full border-2 border-[#3c49ad] bg-white"
                style={{ left: DOT_OFFSET - 32, top: 5, width: DOT_SIZE, height: DOT_SIZE }}
              />
              <div className="flex justify-between items-baseline gap-2">
                <div className="min-w-0">
                  <span className="text-[10px] text-slate-400 mr-1">#{step.step}</span>
                  <span className="text-xs text-slate-500">{step.description}</span>
                </div>
                <span className="shrink-0 text-[10px] text-slate-400 font-mono pr-2">{formatMs(step.elapsed_ms)}</span>
              </div>
            </div>
          ))}

          {currentStep && (
            <div
              key={`current-${currentStep.step}`}
              className="relative pb-1 step-enter leading-4"
            >
              <div
                ref={lastDotRef}
                className="absolute rounded-full bg-[#3c49ad] dot-pulse"
                style={{ left: DOT_OFFSET - 32, top: 5, width: ACTIVE_DOT_SIZE, height: ACTIVE_DOT_SIZE }}
              />
              <div>
                <span className="text-[10px] text-[#3c49ad] font-semibold mr-1">#{currentStep.step}</span>
                <span className="text-xs text-slate-900 font-medium">{currentStep.description}</span>
              </div>
            </div>
          )}
        </div>
        </div>
      </div>
    </div>
  );
}
