import { useEffect, useRef } from "react";
import type { StepRecord } from "../lib/types";
import { formatMs } from "../lib/utils";

interface StepLogProps {
  steps: StepRecord[];
  isRunning: boolean;
}

export function StepLog({ steps, isRunning }: StepLogProps) {
  const currentStep = isRunning && steps.length > 0 ? steps[steps.length - 1] : null;
  const completedSteps = currentStep ? steps.slice(0, -1) : steps;
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new steps arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [steps.length]);

  return (
    <div className="relative h-full overflow-hidden">
      {/* Top fade */}
      <div className="absolute top-0 left-0 right-0 h-6 bg-gradient-to-b from-[#f0f4ff] to-transparent z-10 pointer-events-none" />
      {/* Bottom fade */}
      <div className="absolute bottom-0 left-0 right-0 h-6 bg-gradient-to-t from-[#f0f4ff] to-transparent z-10 pointer-events-none" />

      {/* Scrollable timeline */}
      <div ref={scrollRef} className="h-full overflow-y-auto px-2 py-5">
        <div className="relative pl-8">
          {/* Vertical line with gradient */}
          <div
            className="absolute left-[11px] top-0 bottom-0 w-0.5"
            style={{
              background: "linear-gradient(transparent 0%, #3c49ad 8%, #3c49ad 92%, transparent 100%)",
            }}
          />

          {/* Starting state */}
          {steps.length === 0 && isRunning && (
            <div className="relative pb-4">
              <div className="absolute -left-[13px] top-[6px] w-3 h-3 rounded-full bg-[#3c49ad] shadow-[0_0_0_4px_rgba(60,73,173,0.15)]" />
              <span className="text-xs text-slate-400">Starting agent...</span>
            </div>
          )}

          {/* Completed steps */}
          {completedSteps.map((step) => (
            <div key={step.step} className="relative pb-5">
              <div className="absolute -left-[13px] top-[6px] w-3 h-3 rounded-full border-2 border-[#3c49ad] bg-[#f0f4ff]" />
              <div className="flex justify-between items-baseline gap-2">
                <div className="min-w-0">
                  <span className="text-[10px] text-slate-400 mr-1">#{step.step}</span>
                  <span className="text-xs text-slate-500">{step.description}</span>
                </div>
                <span className="shrink-0 text-[10px] text-slate-400 font-mono">{formatMs(step.elapsed_ms)}</span>
              </div>
            </div>
          ))}

          {/* Current step */}
          {currentStep && (
            <div className="relative pb-1">
              <div className="absolute -left-[13px] top-[6px] w-3 h-3 rounded-full bg-[#3c49ad] shadow-[0_0_0_4px_rgba(60,73,173,0.15)]" />
              <div>
                <span className="text-[10px] text-[#3c49ad] font-semibold mr-1">#{currentStep.step}</span>
                <span className="text-xs text-slate-900 font-medium">{currentStep.description}</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
