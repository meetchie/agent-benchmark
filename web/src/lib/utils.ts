import type { RunPhase } from "./types";

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

/** The site's name for labels: the URL's host without "www.", or the text as given. */
export function siteName(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/**
 * The short line that says what a run is doing while there is nothing else to
 * see, from the status reply's run_phase. null when there is none (an older
 * backend, or a run that has ended).
 */
export function runPhaseLabel(phase: RunPhase | null | undefined, url: string): string | null {
  if (!phase) return null;
  switch (phase.name) {
    case "starting_browser":
      return "Starting the browser";
    case "opening_site":
      return `Opening ${siteName(url)}`;
    case "deciding":
      return phase.step ? `Deciding step ${phase.step}` : "Deciding the next step";
    case "acting":
      return phase.step ? `Doing step ${phase.step}` : "Doing the next step";
    case "judging":
      return "Judging the run";
    default:
      return null;
  }
}

/**
 * Text after the bold count in "2 of 3 runs remaining". Without a known daily
 * limit (the backend reports none) it is just "runs remaining".
 */
export function runsRemainingLabel(remaining: number, limit?: number): string {
  if (limit !== undefined) return `of ${limit} runs remaining`;
  return `${remaining === 1 ? "run" : "runs"} remaining`;
}
