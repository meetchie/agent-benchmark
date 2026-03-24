import { useEffect, useRef } from "react";
import type { StepRecord } from "../lib/types";
import { formatMs } from "../lib/utils";

interface StepLogProps {
  steps: StepRecord[];
  isRunning: boolean;
}

/* Layout: time on left (50px), then line at 58px, dots centered on 58px, text starts at 74px */
const TIME_WIDTH = 50; // px for the time column
const LINE_LEFT = TIME_WIDTH + 8; // 58px from left edge to line center
const DOT_SIZE = 12;  // px
const DOT_OFFSET = LINE_LEFT - DOT_SIZE / 2; // 52px — centers dot on line
const TEXT_LEFT = LINE_LEFT + 16; // 74px — text starts after dot

export function StepLog({ steps, isRunning }: StepLogProps) {
  const currentStep = isRunning && steps.length > 0 ? steps[steps.length - 1] : null;
  const completedSteps = currentStep ? steps.slice(0, -1) : steps;
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [steps.length]);

  return (
    <div className="relative h-full overflow-hidden">
      {/* Top fade */}
      <div className="absolute top-0 left-0 right-0 h-10 bg-gradient-to-b from-[#f0f4ff] to-transparent z-10 pointer-events-none" />
      {/* Bottom fade */}
      <div className="absolute bottom-0 left-0 right-0 h-10 bg-gradient-to-t from-[#f0f4ff] to-transparent z-10 pointer-events-none" />

      {/* Scrollable timeline */}
      <div ref={scrollRef} className="h-full overflow-y-auto py-10">
        <div className="relative" style={{ paddingLeft: TEXT_LEFT }}>
          {/* Vertical line — centered at LINE_LEFT */}
          <div
            className="absolute top-0 bottom-0"
            style={{
              left: LINE_LEFT - 1,
              width: 2,
              background: "linear-gradient(transparent 0%, #3c49ad 8%, #3c49ad 92%, transparent 100%)",
            }}
          />

          {/* Starting state */}
          {steps.length === 0 && isRunning && (
            <div className="relative pb-4">
              <div
                className="absolute rounded-full bg-[#3c49ad] shadow-[0_0_0_4px_rgba(60,73,173,0.15)]"
                style={{ left: DOT_OFFSET - TEXT_LEFT, top: 4, width: DOT_SIZE, height: DOT_SIZE }}
              />
              <span className="text-xs text-slate-400">Starting agent...</span>
            </div>
          )}

          {/* Completed steps */}
          {completedSteps.map((step) => (
            <div key={step.step} className="relative pb-5">
              {/* Time — left of line */}
              <span
                className="absolute text-[10px] text-slate-400 font-mono text-right"
                style={{ left: -TEXT_LEFT, width: TIME_WIDTH - 4, top: 4 }}
              >
                {formatMs(step.elapsed_ms)}
              </span>
              {/* Dot */}
              <div
                className="absolute rounded-full border-2 border-[#3c49ad] bg-[#f0f4ff]"
                style={{ left: DOT_OFFSET - TEXT_LEFT, top: 4, width: DOT_SIZE, height: DOT_SIZE }}
              />
              {/* Description — right of line */}
              <div className="min-w-0">
                <span className="text-[10px] text-slate-400 mr-1">#{step.step}</span>
                <span className="text-xs text-slate-500">{step.description}</span>
              </div>
            </div>
          ))}

          {/* Current step */}
          {currentStep && (
            <div className="relative pb-1">
              <div
                className="absolute rounded-full bg-[#3c49ad] shadow-[0_0_0_4px_rgba(60,73,173,0.15)]"
                style={{ left: DOT_OFFSET - TEXT_LEFT, top: 4, width: DOT_SIZE, height: DOT_SIZE }}
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
  );
}
