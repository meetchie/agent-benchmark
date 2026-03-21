import { useState, useEffect, useRef } from "react";
import { formatTimer } from "../lib/utils";

interface RunningHeaderProps {
  url: string;
  taskLabel: string;
  isRunning: boolean;
  totalMs?: number;
  onNewTest: () => void;
}

export function RunningHeader({
  url,
  taskLabel,
  isRunning,
  totalMs,
  onNewTest,
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
    <header className="bg-white border-b border-slate-200 px-5 py-2.5 flex items-center justify-between">
      <div className="flex items-center gap-2.5 min-w-0">
        <span className="text-sm font-semibold text-slate-900 shrink-0">Rindler</span>
        <span className="text-slate-300 shrink-0">|</span>
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
