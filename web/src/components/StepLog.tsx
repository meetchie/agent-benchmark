import { useEffect, useRef } from "react";
import type { StepRecord } from "../lib/types";
import { formatMs } from "../lib/utils";

interface StepLogProps {
  steps: StepRecord[];
  isRunning: boolean;
}

export function StepLog({ steps, isRunning }: StepLogProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [steps.length]);

  const totalMs = steps.reduce((sum, s) => sum + s.elapsed_ms, 0);

  return (
    <div className="space-y-1">
      <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider flex justify-between">
        <span>Steps</span>
        {steps.length > 0 && (
          <span className="text-slate-400">Total: {formatMs(totalMs)}</span>
        )}
      </div>
      <div className="max-h-64 overflow-y-auto border-2 border-slate-200 bg-white">
        {steps.length === 0 && !isRunning ? (
          <p className="text-sm text-slate-400 text-center py-8">Steps will appear here during the run.</p>
        ) : steps.length === 0 ? (
          <div className="flex items-center gap-2 py-6 px-4 text-sm text-slate-500">
            <div className="h-3 w-3 rounded-full bg-indigo-500 animate-pulse" />
            <span>Starting agent…</span>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {steps.map((step, i) => {
              const isLast = i === steps.length - 1;
              const isInProgress = isLast && isRunning;
              return (
                <div key={step.step} className="flex items-start gap-2 px-3 py-2">
                  <span className="mt-0.5 shrink-0">
                    {isInProgress ? (
                      <svg className="animate-spin h-3.5 w-3.5 text-[#3c49ad]" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                    ) : (
                      <svg className="h-3.5 w-3.5 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </span>
                  <span className="flex-1 text-xs text-slate-700 leading-relaxed">
                    <span className="text-slate-400 mr-1.5">#{step.step}</span>
                    {step.description}
                  </span>
                  {!isInProgress && (
                    <span className="shrink-0 text-xs text-slate-400 font-mono">
                      {formatMs(step.elapsed_ms)}
                    </span>
                  )}
                </div>
              );
            })}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </div>
  );
}
