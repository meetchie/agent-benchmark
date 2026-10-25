import { describe, expect, it } from "vitest";
import { costAxis, formatCostTick } from "../costAxis";

/** The labels the chart would show for a run that costs `maxCost` in total. */
function labels(maxCost: number): string[] {
  const { ticks, decimals } = costAxis(maxCost);
  return ticks.map((t) => formatCostTick(t, decimals));
}

describe("costAxis", () => {
  it("gives a cheap run distinct tick labels (not $0.02 $0.02 $0.01 $0.01 $0.00)", () => {
    expect(labels(0.0185)).toEqual(["$0.000", "$0.005", "$0.010", "$0.015", "$0.020"]);
  });

  it("keeps whole cents where cents are enough", () => {
    expect(labels(0.083)).toEqual(["$0.00", "$0.02", "$0.04", "$0.06", "$0.08", "$0.10"]);
    expect(labels(0.71)).toEqual(["$0.00", "$0.20", "$0.40", "$0.60", "$0.80"]);
    expect(labels(3.2)).toEqual(["$0.00", "$1.00", "$2.00", "$3.00", "$4.00"]);
  });

  it("adds decimals as runs get cheaper", () => {
    expect(labels(0.0042)).toEqual(["$0.000", "$0.001", "$0.002", "$0.003", "$0.004", "$0.005"]);
    expect(labels(0.0004)).toEqual(["$0.0000", "$0.0001", "$0.0002", "$0.0003", "$0.0004"]);
  });

  it("always reaches the largest cost, with distinct, increasing ticks and few of them", () => {
    for (const max of [0.0003, 0.0012, 0.0185, 0.029, 0.0499, 0.05, 0.1, 0.1366, 0.7130, 1, 4.99, 12.5]) {
      const { ticks, decimals } = costAxis(max);
      expect(ticks[0]).toBe(0);
      expect(ticks[ticks.length - 1]).toBeGreaterThanOrEqual(max);
      expect(ticks.length).toBeLessThanOrEqual(6);
      expect(new Set(labels(max)).size, `max ${max}`).toBe(ticks.length);
      expect(ticks.every((t, i) => i === 0 || t > ticks[i - 1])).toBe(true);
      expect(decimals).toBeGreaterThanOrEqual(2);
    }
  });

  it("copes with a run that cost nothing", () => {
    for (const none of [0, -1, NaN, Infinity]) {
      expect(labels(none)).toEqual(["$0.00", "$0.01"]);
    }
  });
});
