/**
 * Format the backend's cost_usd for display. Returns null when there is no
 * usable cost (absent, null, negative or not a number), so callers can fall
 * back to showing tokens only. The UI never prices tokens itself: the rates
 * depend on the model the backend ran.
 */
export function formatCostUsd(cost: number | null | undefined): string | null {
  if (typeof cost !== "number" || !Number.isFinite(cost) || cost < 0) return null;
  if (cost > 0 && cost < 0.01) return "<$0.01";
  return "$" + cost.toFixed(2);
}
