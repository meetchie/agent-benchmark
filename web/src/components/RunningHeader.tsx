import { useState, useEffect } from "react";
import { formatTimer, runsRemainingLabel } from "../lib/utils";

interface RunningHeaderProps {
  isRunning: boolean;
  elapsedMs: number;
  totalMs?: number;
  onNewTest: () => void;
  remainingRuns?: number;
  runLimit?: number;
  resetsIn?: number;
  /** The backend plays canned runs: nothing is billed, so the dialog says nothing about tokens. */
  demoMode?: boolean;
}

function formatResetTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function ConfirmLeaveModal({ onConfirm, onCancel, demoMode }: { onConfirm: () => void; onCancel: () => void; demoMode: boolean }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onCancel]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true">
      <div className="absolute inset-0 modal-backdrop" onClick={onCancel} />
      <div className="relative max-w-[400px] w-full border-2 border-slate-200 bg-white p-8 m-4 shadow-2xl text-center">
        <p className="text-lg font-semibold text-slate-900 mb-2">Cancel this run?</p>
        <p className="text-sm text-slate-500 mb-6">
          The benchmark is still running. If you leave now, you won't see the results.
          {!demoMode && " Tokens already used are still billed and kept in the run record."}
        </p>
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            className="flex-1 border-2 border-slate-300 bg-white text-slate-700 py-2.5 text-sm font-semibold hover:border-[#3c49ad] hover:text-[#3c49ad] transition-colors"
          >
            Keep Running
          </button>
          <button
            onClick={onConfirm}
            className="flex-1 border-2 border-red-600 bg-red-600 text-white py-2.5 text-sm font-semibold hover:bg-red-700 hover:border-red-700 transition-colors"
          >
            Cancel Run
          </button>
        </div>
      </div>
    </div>
  );
}

export function RunningHeader({
  isRunning,
  elapsedMs,
  totalMs,
  onNewTest,
  remainingRuns,
  runLimit,
  resetsIn,
  demoMode = false,
}: RunningHeaderProps) {
  const [showConfirm, setShowConfirm] = useState(false);

  const handleLeave = () => {
    if (isRunning) {
      setShowConfirm(true);
    } else {
      onNewTest();
    }
  };

  const handleConfirmLeave = () => {
    setShowConfirm(false);
    onNewTest();
  };

  // Show server time when done; live counter once first step has arrived (elapsedMs > 0); blank while connecting
  const displayTime = totalMs ? formatTimer(totalMs) : elapsedMs > 0 ? formatTimer(elapsedMs) : "";

  return (
    <>
      <header className="bg-white border-b border-slate-200 px-4 sm:px-6 py-2 sm:py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 sm:gap-2.5 min-w-0">
            <button onClick={handleLeave} className="flex items-center gap-2 sm:gap-2.5 shrink-0">
              <img src="/rindler-logo.png" alt="Rindler" className="h-7 sm:h-9 w-auto" />
              <span className="text-base sm:text-lg font-semibold text-slate-900">Rindler</span>
            </button>
            <span className="text-slate-400 font-light shrink-0">|</span>
            <span className="text-xs sm:text-sm font-medium text-[#3c49ad] shrink-0">Benchmark</span>
          </div>
          <div className="flex items-center gap-2 sm:gap-3 shrink-0">
            {displayTime && (
              <span className={`text-xs font-semibold ${isRunning ? "text-[#3c49ad]" : "text-slate-500"}`}>
                {isRunning ? "RUNNING " : ""}{displayTime}
              </span>
            )}
            {remainingRuns !== undefined && remainingRuns > 0 && (
              <span className="hidden sm:inline text-xs text-slate-500">
                {remainingRuns === 1 && (
                  <svg className="inline w-3.5 h-3.5 text-amber-500 mr-1 -mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.168 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
                  </svg>
                )}
                <strong className="text-[#3c49ad]">{remainingRuns}</strong> {runsRemainingLabel(remainingRuns, runLimit)}
              </span>
            )}
            {remainingRuns !== undefined && remainingRuns <= 0 && resetsIn !== undefined && resetsIn > 0 && (
              <span className="hidden sm:inline text-xs font-semibold text-red-500">
                Runs reset in {formatResetTime(resetsIn)}
              </span>
            )}
            <button
              onClick={handleLeave}
              className="text-xs sm:text-sm font-semibold text-[#3c49ad] border-2 border-[#3c49ad] px-3 sm:px-5 py-1 sm:py-1.5 hover:bg-[#3c49ad] hover:text-white transition-colors whitespace-nowrap"
          >
            New Test
          </button>
          </div>
        </div>
        {remainingRuns !== undefined && remainingRuns > 0 && (
          <div className="sm:hidden text-[10px] text-slate-400 mt-1 text-right">
            <strong className="text-[#3c49ad]">{remainingRuns}</strong> {runsRemainingLabel(remainingRuns, runLimit)}
          </div>
        )}
        {remainingRuns !== undefined && remainingRuns <= 0 && resetsIn !== undefined && resetsIn > 0 && (
          <div className="sm:hidden text-[10px] font-semibold text-red-500 mt-1 text-right">
            Runs reset in {formatResetTime(resetsIn)}
          </div>
        )}
      </header>

      {showConfirm && (
        <ConfirmLeaveModal
          onConfirm={handleConfirmLeave}
          onCancel={() => setShowConfirm(false)}
          demoMode={demoMode}
        />
      )}
    </>
  );
}
