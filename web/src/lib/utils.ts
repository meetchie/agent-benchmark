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

// A step that only opens the site or one of its pages: "Go to the Products page.",
// "Open the site.", "Go to Menu.", "Navigate to https://shop.example/".
const NAV_START = String.raw`^(?:please\s+|first,?\s+|then,?\s+)?(?:go|navigate|head|return|browse|open|visit|load)(?:\s+(?:back|over))?(?:\s+(?:to|into|onto|on))?`;
const NAV_TO_PAGE = new RegExp(
  NAV_START +
    String.raw`(?:\s+the)?(?:\s+[\w'’&-]+){0,4}?\s+(?:page|site|website|homepage|home\s?page|home|section|tab|menu|store|shop|storefront)\s*[.!]?$`,
  "i"
);
const NAV_TO_URL = new RegExp(
  NAV_START + String.raw`\s+(?:https?:\/\/)?(?:www\.)?[\w-]+(?:\.[\w-]+)+(?:\/\S*)?\s*[.!]?$`,
  "i"
);

/** Where a sentence may end: ".", "!" or "?" (and a closing quote or bracket), a space, then a capital. */
const SENTENCE_END = /[.!?]+["”’')\]]*\s+(?=["“‘'(\[]?[A-Z])/g;
/** A full stop that ends an abbreviation or an initial ("e.g.", "Rs.", "U.S."), not a sentence. */
const ABBREVIATION = /(?:^|[\s(])(?:e\.g|i\.e|etc|vs|approx|mr|mrs|ms|dr|st|rs)\.$/i;
const INITIAL = /(?:^|[\s(.])[A-Z]\.$/;

function goalSentences(goal: string): string[] {
  const sentences: string[] = [];
  for (const rawLine of goal.split(/\r?\n/)) {
    const line = rawLine.trim().replace(/^(?:[-*•]|\d{1,3}[.)])\s+/, "");
    let start = 0;
    for (const m of line.matchAll(SENTENCE_END)) {
      const end = m.index! + m[0].trimEnd().length;
      const piece = line.slice(start, end);
      if (ABBREVIATION.test(piece) || INITIAL.test(piece)) continue;
      sentences.push(piece.trim());
      start = m.index! + m[0].length;
    }
    const rest = line.slice(start).trim();
    if (rest) sentences.push(rest);
  }
  return sentences;
}

/**
 * The line under a task's title on its card: the goal's first sentence that says
 * what to do, skipping steps that only open the site or a page ("Go to the Products
 * page."), which generated tasks for one site often all start with. The goal's
 * first line when every sentence is such a step.
 */
export function taskSubtitle(goal: string): string {
  const useful = goalSentences(goal).find((s) => !NAV_TO_PAGE.test(s) && !NAV_TO_URL.test(s));
  if (useful) return useful;
  return goal.split(/\r?\n/).map((line) => line.trim()).find(Boolean) ?? "";
}
