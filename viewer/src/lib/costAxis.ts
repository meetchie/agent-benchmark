// The y-axis of the cost chart. Recharts picks its own ticks, and a fixed
// toFixed(2) makes cheap runs read $0.02, $0.02, $0.01, $0.01, $0.00. Here the
// ticks are chosen first, in steps of 1, 2 or 5 times a power of ten, and the
// labels get as many decimals as that step needs, so they are always distinct.

export interface CostAxis {
  /** Tick values, from 0 up to the first step at or above the largest cost. */
  ticks: number[];
  /** Decimals every label needs (at least 2: dollars and cents). */
  decimals: number;
}

// At most this many gaps between ticks, so at most this many plus one labels.
const MAX_INTERVALS = 5;

export function costAxis(maxCost: number): CostAxis {
  if (!Number.isFinite(maxCost) || maxCost <= 0) return { ticks: [0, 0.01], decimals: 2 };

  const rough = maxCost / MAX_INTERVALS;
  const power = 10 ** Math.floor(Math.log10(rough));
  const ratio = rough / power;
  const step = (ratio <= 1 ? 1 : ratio <= 2 ? 2 : ratio <= 5 ? 5 : 10) * power;

  // Whole multiples of the step, so no floating-point drift builds up.
  const count = Math.ceil(maxCost / step - 1e-9);
  let decimals = 2;
  while (decimals < 8 && Math.abs(step * 10 ** decimals - Math.round(step * 10 ** decimals)) > 1e-6) {
    decimals += 1;
  }
  const ticks = Array.from({ length: count + 1 }, (_, i) => Number((i * step).toFixed(decimals)));
  return { ticks, decimals };
}

export function formatCostTick(value: number, decimals: number): string {
  return `$${value.toFixed(decimals)}`;
}
