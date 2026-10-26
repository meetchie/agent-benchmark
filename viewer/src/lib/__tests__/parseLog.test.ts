import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { analyzeFriction, parseLog, parseLogMeta, type Step } from "../parseLog";
// Real runs from the local arena, copied unchanged. The Rindler one has a remove_from_cart call
// that failed (telemetry was_error true) in a run the judge still passed; the browser-use one has
// no failed call.
import rindlerFailedRemove from "../__fixtures__/arena_rindler_vhlistings_20261024_221846.log?raw";
import browserUseClean from "../__fixtures__/arena_browseruse_vhlistings_20261024_221948.log?raw";

/** A log with a header and the given step_end events (one per entry). */
function logWith(
  steps: Array<{
    action?: string;
    hash?: string | null;
    ms?: number;
    was_error?: boolean;
  }>,
  headerExtra = ""
): string {
  const events = steps.flatMap((s, i) => {
    const base = {
      trace_id: "t",
      run_id: "r",
      lane: "RINDLER",
      step_index: i + 1,
      timestamp: "2026-10-24T22:00:00.000000",
      tokens_input: 0,
      tokens_output: 0,
      cost_usd: 0,
      action_type: s.action ?? "click",
    };
    const end: Record<string, unknown> = {
      ...base,
      event_type: "step_end",
      duration_ms: s.ms ?? 1000,
      observation_hash: s.hash === undefined ? `hash-${i}` : s.hash,
    };
    if (s.was_error !== undefined) end.was_error = s.was_error;
    return [{ ...base, event_type: "step_start", duration_ms: null, observation_hash: null }, end];
  });
  return `Agent: RINDLER\nScenario: x_add_to_cart\nDuration: 5.0s\nSuccess: True\n${headerExtra}\nTelemetry Events:\n${JSON.stringify(events)}`;
}

describe("a new-format log whose remove_from_cart failed", () => {
  const log = parseLog(rindlerFailedRemove, "arena_rindler_vhlistings_20261024_221846.log");

  it("reads the header and the six steps", () => {
    expect(log.agent).toBe("RINDLER");
    expect(log.judge?.verdict).toBe("PASS");
    expect(log.tokensTotal).toBe(25945);
    expect(log.steps.map((s) => s.actionType)).toEqual([
      "search_products",
      "view_product",
      "add_to_cart",
      "view_cart",
      "remove_from_cart",
      "done",
    ]);
  });

  it("marks only the failed step as an error", () => {
    expect(log.steps.filter((s) => s.wasError).map((s) => s.index)).toEqual([5]);
  });

  it("reports the failed call as friction instead of a clean run", () => {
    expect(log.friction).toHaveLength(1);
    expect(log.friction[0]).toMatchObject({
      type: "failed_step",
      severity: "warning",
      stepIndices: [5],
    });
    expect(log.friction[0].description).toContain("remove_from_cart");
  });
});

describe("a new-format log with no failed call", () => {
  it("still has no friction", () => {
    const log = parseLog(browserUseClean, "arena_browseruse_vhlistings_20261024_221948.log");
    expect(log.steps).toHaveLength(7);
    expect(log.steps.some((s) => s.wasError)).toBe(false);
    expect(log.friction).toEqual([]);
  });
});

describe("failed steps in the friction rules", () => {
  it("count every step whose end event says was_error true", () => {
    const log = parseLog(logWith([{ was_error: true }, { was_error: false }, { was_error: true }]), "x.log");
    expect(log.friction.map((f) => [f.type, f.stepIndices])).toEqual([
      ["failed_step", [1]],
      ["failed_step", [3]],
    ]);
  });

  it("ignore logs that have no was_error field (the oldest format)", () => {
    const log = parseLog(logWith([{}, {}, {}]), "x.log");
    expect(log.steps.every((s) => !s.wasError)).toBe(true);
    expect(log.friction).toEqual([]);
  });

  it("do not trust a truthy value other than true", () => {
    const raw = logWith([{}]).replace('"event_type":"step_end"', '"event_type":"step_end","was_error":"false"');
    expect(parseLog(raw, "x.log").friction).toEqual([]);
  });
});

describe("a file that is not a readable arena log", () => {
  it.each([
    ["random text", "hello\nthis is a shopping list, not a run log\n"],
    ["an empty file", ""],
    ["a JSON file", JSON.stringify([{ event_type: "step_end", step_index: 1 }])],
    ["binary data", "PK\u0003\u0004\u0000\u0000\u0008\u0000ÿþ\u0000garbage"],
    ["one very long line", "x".repeat(3_000_000)],
    // server/arena_logs/ also holds Rindler context dumps, which are not run logs.
    ["a Rindler context log", "=====\n  RINDLER AGENT — FULL CONTEXT LOG\n=====\n  Run ID:     abc\n  Goal:       shop\n"],
  ])("is refused with a reason instead of shown as a run: %s", (_name, raw) => {
    expect(() => parseLog(raw, "x.log")).toThrow(/not an arena run log/);
    expect(() => parseLogMeta(raw, "x.log")).toThrow(/not an arena run log/);
  });

  it("is refused when the log stops before its telemetry list", () => {
    const raw = logWith([{}, {}]).split("\nTelemetry Events:")[0];
    expect(() => parseLog(raw, "x.log")).toThrow(/no "Telemetry Events:" list/);
  });

  it("is refused when the telemetry list is cut short", () => {
    const raw = logWith([{}, {}, {}]);
    expect(() => parseLog(raw.slice(0, raw.length - 25), "x.log")).toThrow(/telemetry list in this log is damaged/);
  });

  it("is refused when the telemetry is not a list of events", () => {
    const raw = logWith([]).replace("Telemetry Events:\n[]", 'Telemetry Events:\n{"steps": 3}');
    expect(() => parseLog(raw, "x.log")).toThrow(/not a list of events/);
  });

  it("still opens a run that stopped before its first step", () => {
    const raw = logWith([], "Errors Detected: TimeoutError: page did not load");
    const log = parseLog(raw, "x.log");
    expect(log.steps).toEqual([]);
    expect(log.friction).toMatchObject([{ type: "error", description: "TimeoutError: page did not load" }]);
  });
});

describe("every archived log", () => {
  // The bundled viewer logs and the arena_*.log files in server/arena_logs/ must all
  // open; the six context_*.log files there are not run logs and must be refused.
  const dirs = [
    new URL("../../../public/logs/", import.meta.url),
    new URL("../../../../server/arena_logs/", import.meta.url),
  ];
  const files = dirs.flatMap((dir) =>
    readdirSync(dir)
      .filter((f) => f.endsWith(".log"))
      .map((f) => ({ name: f, raw: readFileSync(new URL(f, dir), "utf8") }))
  );

  it("is found", () => {
    expect(files.filter((f) => f.name.startsWith("arena_"))).toHaveLength(128 + 131);
    expect(files.filter((f) => f.name.startsWith("context_"))).toHaveLength(6);
  });

  it("opens with at least one step, or is refused if it is a context log", () => {
    for (const { name, raw } of files) {
      if (name.startsWith("context_")) {
        expect(() => parseLog(raw, name), name).toThrow(/not an arena run log/);
      } else {
        expect(parseLog(raw, name).steps.length, name).toBeGreaterThan(0);
        expect(parseLogMeta(raw, name).agent, name).not.toBe("Unknown");
      }
    }
  });
});

describe("the other friction rules still fire", () => {
  const step = (over: Partial<Step> & { index: number }): Step => ({
    actionType: "click",
    startTime: "",
    endTime: null,
    durationMs: 1000,
    tokensInput: 0,
    tokensOutput: 0,
    costUsd: 0,
    observationHash: `h${over.index}`,
    wasError: false,
    ...over,
  });

  it("finds a loop of identical observations", () => {
    // Different actions, so only the repeated observation is flagged.
    const f = analyzeFriction(
      [
        step({ index: 1, actionType: "click", observationHash: "a" }),
        step({ index: 2, actionType: "scroll", observationHash: "a" }),
        step({ index: 3, actionType: "click", observationHash: "a" }),
        step({ index: 4, actionType: "navigate" }),
      ],
      null
    );
    expect(f).toHaveLength(1);
    expect(f[0]).toMatchObject({ type: "loop", severity: "critical", stepIndices: [1, 2, 3] });
  });

  it("flags a step over 60 s, critical over 300 s", () => {
    const f = analyzeFriction([step({ index: 1, durationMs: 61_000 }), step({ index: 2, durationMs: 301_000 })], null);
    expect(f.map((e) => [e.type, e.severity, e.stepIndices[0]])).toEqual([
      ["long_step", "critical", 2],
      ["long_step", "warning", 1],
    ]);
  });

  it("flags four identical actions in a row", () => {
    const steps = [1, 2, 3, 4].map((i) => step({ index: i, actionType: "scroll" }));
    expect(analyzeFriction(steps, null)).toMatchObject([{ type: "repeated_action", stepIndices: [1, 2, 3, 4] }]);
  });

  it("flags a header-level error and sorts critical first", () => {
    const f = analyzeFriction([step({ index: 1, wasError: true })], "Agent crashed");
    expect(f.map((e) => [e.type, e.severity])).toEqual([
      ["error", "critical"],
      ["failed_step", "warning"],
    ]);
  });

  it("finds nothing in a healthy run", () => {
    expect(analyzeFriction([step({ index: 1 }), step({ index: 2, actionType: "navigate" })], null)).toEqual([]);
  });
});
