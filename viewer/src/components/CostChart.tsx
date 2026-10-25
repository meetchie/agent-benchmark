import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { costAxis, formatCostTick } from "../lib/costAxis";
import type { ParsedLog } from "../lib/parseLog";

interface Props {
  log: ParsedLog;
}

export function CostChart({ log }: Props) {
  if (log.steps.length === 0) return null;

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

  const { ticks, decimals } = costAxis(cumCost);

  return (
    <div className="panel cost-panel">
      <h3>Cost Accumulation</h3>
      <div className="chart-container">
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={data} margin={{ top: 10, right: 20, bottom: 8, left: 10 }}>
            <defs>
              <linearGradient id="costGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#3c49ad" stopOpacity={0.25} />
                <stop offset="100%" stopColor="#3c49ad" stopOpacity={0.03} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis
              dataKey="step"
              stroke="#e2e8f0"
              tick={{ fill: "#475569", fontSize: 11 }}
              height={44}
              label={{
                value: "Step",
                position: "insideBottom",
                offset: 0,
                fill: "#475569",
                fontSize: 11,
              }}
            />
            <YAxis
              stroke="#e2e8f0"
              tick={{ fill: "#475569", fontSize: 11 }}
              ticks={ticks}
              domain={[0, ticks[ticks.length - 1]]}
              width={72}
              tickFormatter={(v: number) => formatCostTick(v, decimals)}
              label={{
                value: "Cumulative Cost (USD)",
                angle: -90,
                position: "insideLeft",
                offset: 10,
                fill: "#475569",
                fontSize: 11,
                // Centre the text on the axis; by default it starts there and runs off the top.
                style: { textAnchor: "middle" },
              }}
            />
            <Tooltip
              contentStyle={{
                background: "#ffffff",
                border: "1px solid #e2e8f0",
                fontSize: 12,
                color: "#0f172a",
              }}
              formatter={(value: unknown, name: unknown) => {
                const v = value as number;
                if (name === "cost") return [`$${v.toFixed(4)}`, "Cumulative Cost"];
                return [String(value), String(name)];
              }}
              labelFormatter={(label: unknown) => {
                const pt = data.find((d) => d.step === label);
                return `Step ${label} (${pt?.action ?? ""})`;
              }}
            />
            <Area
              type="monotone"
              dataKey="cost"
              stroke="#3c49ad"
              strokeWidth={2}
              fill="url(#costGrad)"
              dot={false}
              activeDot={{ r: 4, fill: "#3c49ad" }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
