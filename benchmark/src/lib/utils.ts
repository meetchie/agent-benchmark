/** Format milliseconds to a human-readable string: "1.2s" or "34.5s" */
export function formatMs(ms: number): string {
  return (ms / 1000).toFixed(1) + "s";
}
