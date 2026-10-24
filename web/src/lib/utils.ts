/** Format milliseconds to a human-readable string: "1.2s" or "34.5s" */
export function formatMs(ms: number): string {
  return (ms / 1000).toFixed(1) + "s";
}

/** Format milliseconds to M:SS timer format: "0:24", "1:05" */
export function formatTimer(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

/**
 * Text after the bold count in "2 of 3 runs remaining". Without a known daily
 * limit (the backend reports none) it is just "runs remaining".
 */
export function runsRemainingLabel(remaining: number, limit?: number): string {
  if (limit !== undefined) return `of ${limit} runs remaining`;
  return `${remaining === 1 ? "run" : "runs"} remaining`;
}
