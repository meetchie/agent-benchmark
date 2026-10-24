import { describe, expect, it } from "vitest";
import { formatCostUsd } from "../cost";

describe("formatCostUsd", () => {
  it("formats dollars to the cent", () => {
    expect(formatCostUsd(0.0423)).toBe("$0.04");
    expect(formatCostUsd(1)).toBe("$1.00");
    expect(formatCostUsd(12.345)).toBe("$12.35");
  });

  it("shows a sub-cent cost as <$0.01 but an exact zero as $0.00", () => {
    expect(formatCostUsd(0.0049)).toBe("<$0.01");
    expect(formatCostUsd(0)).toBe("$0.00");
  });

  it("returns null when there is no usable cost", () => {
    expect(formatCostUsd(null)).toBeNull();
    expect(formatCostUsd(undefined)).toBeNull();
    expect(formatCostUsd(Number.NaN)).toBeNull();
    expect(formatCostUsd(Number.POSITIVE_INFINITY)).toBeNull();
    expect(formatCostUsd(-0.5)).toBeNull();
  });
});
