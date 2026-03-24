import { useState, useEffect, useRef } from "react";
import { formatTimer } from "../lib/utils";

interface RunningHeaderProps {
  isRunning: boolean;
  totalMs?: number;
  onNewTest: () => void;
  remainingRuns?: number;
}

function ConfirmLeaveModal({ onConfirm, onCancel }: { onConfirm: () => void; onCancel: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onCancel]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-[#3c49ad]/15 backdrop-blur-sm" onClick={onCancel} />
      <div className="relative max-w-[400px] w-full border-2 border-slate-200 bg-white p-8 m-4 shadow-2xl text-center">
        <p className="text-lg font-semibold text-slate-900 mb-2">Cancel this run?</p>
        <p className="text-sm text-slate-500 mb-6">The benchmark is still running. If you leave now, you won't see the results.</p>
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
  totalMs,
  onNewTest,
  remainingRuns,
}: RunningHeaderProps) {
  const [elapsed, setElapsed] = useState(0);
  const [showConfirm, setShowConfirm] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (isRunning) {
      setElapsed(0);
      intervalRef.current = setInterval(() => {
        setElapsed((prev) => prev + 1000);
      }, 1000);
    } else {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isRunning]);

  const displayTime = isRunning ? formatTimer(elapsed) : totalMs ? formatTimer(totalMs) : "";

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

  return (
    <>
      <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2.5 min-w-0">
          <button onClick={handleLeave} className="flex items-center gap-2.5 shrink-0">
            <img src="/rindler-logo.png" alt="Rindler" className="h-9 w-auto" />
            <span className="text-lg font-semibold text-slate-900">Rindler</span>
          </button>
          <span className="text-slate-400 font-light shrink-0">|</span>
          <span className="text-sm font-medium text-[#3c49ad] shrink-0">Benchmark</span>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {displayTime && (
            <span className={`text-xs font-semibold ${isRunning ? "text-[#3c49ad]" : "text-slate-500"}`}>
              {isRunning ? "RUNNING " : ""}{displayTime}
            </span>
          )}
          {remainingRuns !== undefined && (
            <span className={`text-xs font-semibold px-2.5 py-1 border ${
              remainingRuns > 0
                ? "border-[#3c49ad] text-[#3c49ad] bg-[#3c49ad]/5"
                : "border-amber-600 text-amber-600 bg-amber-50"
            }`}>
              Remaining: {remainingRuns}
            </span>
          )}
          <button
            onClick={handleLeave}
            className="text-xs font-medium text-[#3c49ad] border border-[#3c49ad] px-3 py-1 hover:bg-[#3c49ad] hover:text-white transition-colors"
          >
            New Test
          </button>
        </div>
      </header>

      {showConfirm && (
        <ConfirmLeaveModal
          onConfirm={handleConfirmLeave}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </>
  );
}
