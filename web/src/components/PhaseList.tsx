import { useState } from "react";
import type { Phase, StepRecord } from "../lib/types";
import { formatMs, formatTimer } from "../lib/utils";

interface PhaseListProps {
  phases: Phase[];
  steps: StepRecord[];
  isLastPhaseIncomplete?: boolean;
}

export function PhaseList({ phases, steps, isLastPhaseIncomplete }: PhaseListProps) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const toggle = (index: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const stepMap = new Map(steps.map((s) => [s.step, s]));

  if (phases.length === 0) {
    return (
      <div className="border-t border-slate-100 pt-5 mb-5">
        <div className="text-xs text-slate-400 uppercase tracking-wider mb-3">All Steps</div>
        <div className="space-y-1">
          {steps.map((step) => (
            <div key={step.step} className="flex items-start gap-2 text-xs text-slate-600">
              <span className="text-green-600 shrink-0 mt-0.5">✓</span>
              <span className="text-slate-400 shrink-0">#{step.step}</span>
              <span className="flex-1">{step.description}</span>
              <span className="text-slate-400 font-mono shrink-0">{formatMs(step.elapsed_ms)}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="border-t border-slate-100 pt-5 mb-5">
      <div className="text-xs text-slate-400 uppercase tracking-wider mb-3">Phases</div>
      <div>
        {phases.map((phase, i) => {
          const isExpanded = expanded.has(i);
          const isLast = i === phases.length - 1;
          const isIncomplete = isLast && isLastPhaseIncomplete;

          let nameClass = "text-slate-900";
          let timeClass = "text-slate-500";
          let borderClass = "border-slate-200";
          let prefix = "";

          if (phase.failed) {
            nameClass = "text-red-600";
            timeClass = "text-red-600";
            borderClass = "border-red-600";
          } else if (phase.slow || isIncomplete) {
            nameClass = "text-amber-600";
            timeClass = "text-amber-600";
            borderClass = "border-amber-600";
            prefix = "⚠ ";
          }

          const phaseSteps = phase.steps
            .map((num) => stepMap.get(num))
            .filter(Boolean) as StepRecord[];

          return (
            <div key={i} className={i < phases.length - 1 ? "border-b border-slate-100" : ""}>
              <button
                onClick={() => toggle(i)}
                className="w-full flex items-center justify-between py-2.5 text-left"
              >
                <span className={`font-semibold text-sm ${nameClass}`}>
                  {prefix}{phase.name}
                </span>
                <div className="flex items-center gap-3">
                  <span className={`font-mono text-xs ${timeClass}`}>
                    {formatTimer(phase.total_ms)}{isIncomplete ? " +" : ""}
                  </span>
                  <span className="text-slate-400 text-[10px]">
                    {isExpanded ? "▲" : "▼"}
                  </span>
                </div>
              </button>

              {isExpanded && (
                <div className={`mb-3 pl-4 border-l-2 ${borderClass}`}>
                  {phaseSteps.map((step, stepIdx) => {
                    const isLastStep = stepIdx === phaseSteps.length - 1;
                    const isFailedStep = phase.failed && isLastStep;

                    return (
                      <div
                        key={step.step}
                        className={`flex items-start gap-2 py-1 text-xs ${
                          isFailedStep ? "text-red-600" : "text-slate-500"
                        }`}
                      >
                        <span className={isFailedStep ? "text-red-600" : "text-slate-400"}>
                          #{step.step}
                        </span>
                        <span className="flex-1">{step.description}</span>
                        <span className="font-mono shrink-0">{formatMs(step.elapsed_ms)}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
