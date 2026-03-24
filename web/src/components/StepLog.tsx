import type { StepRecord } from "../lib/types";
import { formatMs } from "../lib/utils";

interface StepLogProps {
  steps: StepRecord[];
  isRunning: boolean;
}

export function StepLog({ steps, isRunning }: StepLogProps) {
  const currentStep = isRunning && steps.length > 0 ? steps[steps.length - 1] : null;
  const completedSteps = currentStep ? steps.slice(0, -1) : steps;
  const totalMs = steps.reduce((sum, s) => sum + s.elapsed_ms, 0);

  return (
    <div className="space-y-3">
      {/* Current step — highlighted card, always at top */}
      {currentStep && (
        <div className="border-2 border-[#3c49ad] bg-[#f0f4ff] px-4 py-3">
          <div className="flex items-center gap-2">
            <svg
              className="animate-spin h-4 w-4 text-[#3c49ad] shrink-0"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span className="text-sm font-medium text-[#3c49ad]">
              Step {currentStep.step}
            </span>
            <span className="text-sm text-slate-700">{currentStep.description}</span>
          </div>
        </div>
      )}

      {/* Starting state — no steps yet */}
      {steps.length === 0 && isRunning && (
        <div className="border-2 border-[#3c49ad] bg-[#f0f4ff] px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 rounded-full bg-[#3c49ad] animate-pulse shrink-0" />
            <span className="text-sm text-slate-500">Starting agent...</span>
          </div>
        </div>
      )}

      {/* Completed steps — compact scrollable list */}
      {completedSteps.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider flex justify-between">
            <span>{isRunning ? "Completed Steps" : "Steps"}</span>
            <span className="text-slate-400">Total: {formatMs(totalMs)}</span>
          </div>
          <div className="max-h-40 overflow-y-auto">
            <div className="divide-y divide-slate-100">
              {completedSteps.map((step) => (
                <div key={step.step} className="flex items-center gap-2 px-3 py-1.5">
                  <svg className="h-3 w-3 text-green-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                  <span className="flex-1 text-xs text-slate-600">
                    <span className="text-slate-400 mr-1">#{step.step}</span>
                    {step.description}
                  </span>
                  <span className="shrink-0 text-xs text-slate-400 font-mono">
                    {formatMs(step.elapsed_ms)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
