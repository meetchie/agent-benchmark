import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import type { ParsedLog } from "../lib/parseLog";

interface Props {
  log: ParsedLog;
}

export function CostChart({ log }: Props) {
  if (log.steps.length === 0) return null;

  // Build cumulative cost + token data
  let cumCost = 0;
  let cumTokens = 0;
  const data = log.steps.map((step) => {
    cumCost += step.costUsd;
    cumTokens += step.tokensInput + step.tokensOutput;
    return {
      step: step.index,
      cost: parseFloat(cumCost.toFixed(4)),
      tokens: cumTokens,
      action: step.actionType,
      stepCost: step.costUsd,
    };
  });

  return (
    <div className="panel cost-panel">
      <h3>Cost Accumulation</h3>
      <div className="chart-container">
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={data} margin={{ top: 10, right: 20, bottom: 0, left: 10 }}>
            <defs>
              <linearGradient id="costGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#222" />
            <XAxis
              dataKey="step"
              stroke="#555"
              tick={{ fill: "#888", fontSize: 11 }}
              label={{ value: "Step", position: "insideBottom", offset: -2, fill: "#888", fontSize: 11 }}
            />
            <YAxis
              stroke="#555"
              tick={{ fill: "#888", fontSize: 11 }}
              tickFormatter={(v: number) => `$${v.toFixed(2)}`}
              label={{ value: "Cumulative Cost (USD)", angle: -90, position: "insideLeft", offset: 10, fill: "#888", fontSize: 11 }}
            />
            <Tooltip
              contentStyle={{
                background: "#1a1a1a",
                border: "1px solid #333",
                borderRadius: 8,
                fontSize: 12,
                color: "#eee",
              }}
              formatter={(value: number, name: string) => {
                if (name === "cost") return [`$${value.toFixed(4)}`, "Cumulative Cost"];
                return [value, name];
              }}
              labelFormatter={(label: number) => {
                const pt = data.find((d) => d.step === label);
                return `Step ${label} (${pt?.action ?? ""})`;
              }}
            />
            <Area
              type="monotone"
              dataKey="cost"
              stroke="#3b82f6"
              strokeWidth={2}
              fill="url(#costGrad)"
              dot={false}
              activeDot={{ r: 4, fill: "#3b82f6" }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
