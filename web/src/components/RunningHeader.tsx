import { useState, useEffect, useRef } from "react";
import { formatTimer } from "../lib/utils";

interface RunningHeaderProps {
  url: string;
  taskLabel: string;
  isRunning: boolean;
  totalMs?: number;
  onNewTest: () => void;
  remainingRuns?: number;
}

export function RunningHeader({
  url,
  taskLabel,
  isRunning,
  totalMs,
  onNewTest,
  remainingRuns,
}: RunningHeaderProps) {
  const [elapsed, setElapsed] = useState(0);
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

  let domain = url;
  try {
    domain = new URL(url).hostname.replace("www.", "");
  } catch {
    // keep original
  }

  const displayTime = isRunning ? formatTimer(elapsed) : totalMs ? formatTimer(totalMs) : "";

  return (
    <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-2.5 min-w-0">
        <a href="https://benchmark.rindler.ai" className="flex items-center gap-2.5 shrink-0">
          <img src="/rindler-logo.png" alt="Rindler" className="h-9 w-auto" />
          <span className="text-lg font-semibold text-slate-900">Rindler</span>
        </a>
        <span className="text-slate-400 font-light shrink-0">|</span>
        <span className="text-sm font-medium text-[#3c49ad] shrink-0">Benchmark</span>
        <span className="text-slate-400 font-light shrink-0">|</span>
        <span className="text-xs text-slate-500 truncate">{domain}</span>
        <span className="text-slate-300 shrink-0">|</span>
        <span className="text-xs text-slate-500 truncate">{taskLabel}</span>
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
              : "border-amber-400 text-amber-600 bg-amber-50"
          }`}>
            Remaining: {remainingRuns}
          </span>
        )}
        <button
          onClick={onNewTest}
          className="text-xs font-medium text-[#3c49ad] border border-[#3c49ad] px-3 py-1 hover:bg-[#3c49ad] hover:text-white transition-colors"
        >
          New Test
        </button>
      </div>
    </header>
  );
}
