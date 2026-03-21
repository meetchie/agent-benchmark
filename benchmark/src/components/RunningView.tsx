import type { StepRecord, SummaryData } from "../lib/types";
import { RunningHeader } from "./RunningHeader";
import { ScreenshotViewer } from "./ScreenshotViewer";
import { StepLog } from "./StepLog";
import { ResultsOverlay } from "./ResultsOverlay";

interface RunningViewProps {
  url: string;
  taskLabel: string;
  isRunning: boolean;
  steps: StepRecord[];
  screenshot: string | null;
  summary: SummaryData | null;
  errorMsg: string | null;
  onRunAgain: () => void;
  onNewTest: () => void;
}

export function RunningView({
  url,
  taskLabel,
  isRunning,
  steps,
  screenshot,
  summary,
  errorMsg,
  onRunAgain,
  onNewTest,
}: RunningViewProps) {
  const showOverlay = !!summary || (!!errorMsg && !isRunning);

  return (
    <div className="min-h-screen bg-[#f0f4ff] flex flex-col">
      <RunningHeader
        url={url}
        taskLabel={taskLabel}
        isRunning={isRunning}
        totalMs={summary?.total_ms}
        onNewTest={onNewTest}
      />

      <div className="flex-1 flex flex-col p-4 space-y-4 overflow-y-auto">
        <div className="relative flex-1 min-h-[400px]">
          <div className="h-full border-2 border-slate-200 bg-white overflow-hidden">
            {screenshot ? (
              <img
                src={screenshot}
                alt="Agent screenshot"
                className="w-full h-full object-contain"
              />
            ) : (
              <div className="flex items-center justify-center h-full">
                {isRunning ? (
                  <div className="flex items-center gap-2">
                    <svg
                      className="animate-spin h-5 w-5 text-[#3c49ad]"
                      fill="none"
                      viewBox="0 0 24 24"
                    >
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    <p className="text-sm text-slate-400">Waiting for first screenshot...</p>
                  </div>
                ) : (
                  <p className="text-sm text-slate-400">Screenshot will appear here</p>
                )}
              </div>
            )}
          </div>

          {showOverlay && (
            <ResultsOverlay
              summary={summary}
              errorMsg={errorMsg}
              steps={steps}
              onRunAgain={onRunAgain}
              onNewTest={onNewTest}
            />
          )}
        </div>

        <StepLog steps={steps} isRunning={isRunning} />
      </div>
    </div>
  );
}
