import { useState, useEffect } from "react";

interface BenchmarkHeaderProps {
  userEmail?: string | null;
  remainingRuns?: number;
  resetTime?: string | null;
  onSignOut?: () => void;
}

export function BenchmarkHeader({ userEmail, remainingRuns, resetTime, onSignOut }: BenchmarkHeaderProps) {
  const [countdown, setCountdown] = useState("");

  useEffect(() => {
    if (!resetTime || remainingRuns !== 0) {
      setCountdown("");
      return;
    }

    function update() {
      const diff = new Date(resetTime!).getTime() - Date.now();
      if (diff <= 0) {
        setCountdown("now");
        return;
      }
      const h = Math.floor(diff / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      setCountdown(`${h}h ${m}m`);
    }

    update();
    const id = setInterval(update, 30000);
    return () => clearInterval(id);
  }, [resetTime, remainingRuns]);

  return (
    <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <a href="https://rindlerapp.com" className="flex items-center gap-2.5">
          <img src="/rindler-logo.png" alt="Rindler" className="h-9 w-auto" />
          <span className="text-lg font-semibold text-slate-900">Rindler</span>
        </a>
        <span className="text-slate-400 font-light">|</span>
        <span className="text-sm font-medium text-[#3c49ad]">Benchmark</span>
      </div>

      {userEmail && (
        <div className="flex items-center gap-4">
          {remainingRuns !== undefined && (
            <span className={`text-xs font-semibold px-2.5 py-1 border ${
              remainingRuns > 0
                ? "border-[#3c49ad] text-[#3c49ad] bg-[#3c49ad]/5"
                : "border-amber-400 text-amber-600 bg-amber-50"
            }`}>
              Remaining: {remainingRuns}
            </span>
          )}
          {countdown && remainingRuns === 0 && (
            <span className="text-xs text-amber-600">
              Resets in {countdown}
            </span>
          )}
          <span className="text-xs text-slate-500">{userEmail}</span>
          {onSignOut && (
            <button
              onClick={onSignOut}
              className="text-xs text-slate-400 hover:text-[#3c49ad]"
            >
              Sign out
            </button>
          )}
        </div>
      )}
    </header>
  );
}
