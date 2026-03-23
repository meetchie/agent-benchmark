import type { RunStatus } from "../lib/types";

interface RunButtonProps {
  status: RunStatus;
  disabled: boolean;
  onClick: () => void;
}

export function RunButton({ status, disabled, onClick }: RunButtonProps) {
  const isRunning = status === "running";

  return (
    <button
      onClick={onClick}
      disabled={disabled || isRunning}
      className={`w-full rounded-none border-2 py-3.5 text-base font-semibold transition-all
        ${
          disabled || isRunning
            ? "border-[#3c49ad]/30 bg-[#3c49ad]/10 text-[#3c49ad]/40 cursor-not-allowed"
            : "border-[#3c49ad] bg-[#3c49ad] text-white hover:bg-[#2f3a8a] cursor-pointer"
        }
      `}
    >
      {isRunning ? (
        <span className="flex items-center justify-center gap-2">
          <svg
            className="animate-spin h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
          Running…
        </span>
      ) : (
        "Run Benchmark"
      )}
    </button>
  );
}
