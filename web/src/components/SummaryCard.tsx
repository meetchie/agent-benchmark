import type { SummaryData } from "../lib/types";
import { formatMs } from "../lib/utils";

interface SummaryCardProps {
  data: SummaryData;
}

export function SummaryCard({ data }: SummaryCardProps) {
  return (
    <div
      className={`border-2 p-4 ${
        data.success
          ? "border-green-400 bg-green-50"
          : "border-red-400 bg-red-50"
      }`}
    >
      <div className="flex items-center justify-between">
        <span
          className={`text-sm font-bold ${
            data.success ? "text-green-700" : "text-red-700"
          }`}
        >
          {data.success ? "✓ PASS" : "✗ FAIL"}
        </span>
        <span className="text-xs text-slate-500 font-mono">
          {formatMs(data.total_ms)}
        </span>
      </div>
      {data.summary && (
        <p className="mt-1.5 text-xs text-slate-700 leading-relaxed">
          {data.summary}
        </p>
      )}
    </div>
  );
}
