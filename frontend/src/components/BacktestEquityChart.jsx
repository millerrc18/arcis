import {
  CartesianGrid, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

/**
 * Plot the cumulative equity curve derived from a backtest's trades list.
 * Each trade contributes pnl_dollars to a running equity starting at 100_000.
 * Uses ResponsiveContainer so the chart adapts to its parent width.
 */
export default function BacktestEquityChart({ trades, initialCapital = 100000 }) {
  if (!trades || trades.length === 0) {
    return <div className="text-gray-500 text-sm">No trades</div>;
  }
  let equity = initialCapital;
  const data = trades.map((t) => {
    equity += t.pnl_dollars || 0;
    return {
      date: t.exit_date || t.entry_date,
      equity: Math.round(equity * 100) / 100,
    };
  });
  return (
    <div style={{ width: "100%", height: 280 }}>
      <ResponsiveContainer>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" fontSize={10} />
          <YAxis
            domain={["dataMin", "dataMax"]}
            fontSize={10}
            tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
          />
          <Tooltip formatter={(v) => `$${v.toLocaleString()}`} />
          <Line
            type="monotone"
            dataKey="equity"
            stroke="#2563eb"
            dot={false}
            strokeWidth={2}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
