import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import BacktestEquityChart from "../components/BacktestEquityChart.jsx";
import {
  getPlatformBacktestResults,
  getPlatformBacktestTrades,
  getPlatformPromotionEvents,
  getPlatformStrategies,
  getPlatformStrategyDetail,
} from "../api.js";

const STATUS_BADGES = {
  proposed: "bg-gray-200 text-gray-700",
  backtested: "bg-blue-100 text-blue-800",
  shadow_trading: "bg-yellow-100 text-yellow-800",
  production: "bg-green-100 text-green-800",
  deprecated: "bg-red-100 text-red-800",
};

function StatusBadge({ status }) {
  return (
    <span
      className={`px-2 py-0.5 text-xs rounded ${
        STATUS_BADGES[status] ?? "bg-gray-100 text-gray-600"
      }`}
    >
      {status}
    </span>
  );
}

function eventColor(toStatus) {
  if (toStatus === "deprecated") return "text-red-700";
  if (toStatus === "shadow_trading" || toStatus === "production") {
    return "text-green-700";
  }
  return "text-gray-700";
}

export default function StrategyResearch() {
  const [expandedId, setExpandedId] = useState(null);
  const [selectedBacktest, setSelectedBacktest] = useState(null);

  const { data: strategies = [], isLoading } = useQuery({
    queryKey: ["platform-strategies"],
    queryFn: getPlatformStrategies,
  });

  const { data: detail } = useQuery({
    enabled: !!expandedId,
    queryKey: ["platform-strategy", expandedId],
    queryFn: () => getPlatformStrategyDetail(expandedId),
  });

  const { data: backtests = [] } = useQuery({
    enabled: !!expandedId,
    queryKey: ["platform-backtests", expandedId],
    queryFn: () => getPlatformBacktestResults(expandedId),
  });

  const { data: events = [] } = useQuery({
    enabled: !!expandedId,
    queryKey: ["platform-events", expandedId],
    queryFn: () => getPlatformPromotionEvents(expandedId),
  });

  const { data: selectedTrades = [] } = useQuery({
    enabled: !!selectedBacktest,
    queryKey: ["platform-trades", selectedBacktest?.result_id],
    queryFn: () => getPlatformBacktestTrades(selectedBacktest.result_id),
  });

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-4">Strategy Research</h1>

      {/* Section 1: Registry table */}
      <section className="mb-8">
        <h2 className="text-lg font-medium mb-2">Strategies</h2>
        {isLoading ? (
          <div className="text-gray-500">Loading…</div>
        ) : strategies.length === 0 ? (
          <p className="text-gray-500 p-4 bg-gray-50 rounded">
            No strategies registered yet. Load one from{" "}
            <code>src/platform/specs/*.yaml</code> and run a backtest
            via <code>scripts/run_backtest.py</code>.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-100">
              <tr>
                <th className="text-left p-2">Name</th>
                <th className="text-left p-2">Status</th>
                <th className="text-left p-2">Last DSR</th>
                <th className="text-left p-2">Last max DD</th>
                <th className="text-left p-2">Trades</th>
                <th className="text-left p-2">Last backtest</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((s) => (
                <tr
                  key={s.strategy_id}
                  onClick={() => setExpandedId(s.strategy_id)}
                  className="cursor-pointer hover:bg-gray-50 border-t"
                >
                  <td className="p-2 font-medium">{s.display_name}</td>
                  <td className="p-2">
                    <StatusBadge status={s.current_status} />
                  </td>
                  <td className="p-2">
                    {s.last_dsr != null ? s.last_dsr.toFixed(3) : "—"}
                  </td>
                  <td className="p-2">
                    {s.last_max_dd != null
                      ? (s.last_max_dd * 100).toFixed(1) + "%"
                      : "—"}
                  </td>
                  <td className="p-2">{s.last_n_trades ?? "—"}</td>
                  <td className="p-2 text-xs text-gray-500">
                    {s.last_backtest_at?.slice(0, 10) ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Section 2: Strategy detail */}
      {expandedId && detail && (
        <section className="mb-8 border-l-4 border-blue-500 pl-4">
          <h2 className="text-lg font-medium mb-2">
            {detail.display_name}{" "}
            <span className="text-xs text-gray-500 font-mono">
              {detail.current_spec_hash?.slice(0, 12)}
            </span>
          </h2>
          <p className="text-sm mb-3">
            Status: <StatusBadge status={detail.current_status} />
          </p>

          {detail.spec && (
            <details className="mb-4">
              <summary className="cursor-pointer text-blue-600 text-sm">
                YAML spec
              </summary>
              <pre className="bg-gray-50 text-xs p-3 rounded overflow-auto max-h-80">
                {JSON.stringify(detail.spec, null, 2)}
              </pre>
            </details>
          )}

          {/* Section 3: Backtest results grid */}
          <h3 className="font-medium mt-4 mb-2">Backtest history</h3>
          {backtests.length === 0 ? (
            <p className="text-xs text-gray-500">
              No backtest results yet for this strategy.
            </p>
          ) : (
            <table className="w-full text-sm mb-4">
              <thead className="bg-gray-100">
                <tr>
                  <th className="text-left p-2">Date</th>
                  <th className="text-left p-2">Range</th>
                  <th className="text-left p-2">DSR</th>
                  <th className="text-left p-2">PBO</th>
                  <th className="text-left p-2">OOS eff</th>
                  <th className="text-left p-2">Max DD</th>
                  <th className="text-left p-2">N trades</th>
                </tr>
              </thead>
              <tbody>
                {backtests.map((b) => (
                  <tr
                    key={b.result_id}
                    onClick={() => setSelectedBacktest(b)}
                    className="cursor-pointer hover:bg-gray-50 border-t"
                  >
                    <td className="p-2">{b.created_at?.slice(0, 10)}</td>
                    <td className="p-2 text-xs">
                      {b.start_date} — {b.end_date}
                    </td>
                    <td className="p-2">
                      {b.deflated_sharpe != null
                        ? b.deflated_sharpe.toFixed(3)
                        : "—"}
                    </td>
                    <td className="p-2">
                      {b.pbo != null ? b.pbo.toFixed(3) : "—"}
                    </td>
                    <td className="p-2">
                      {b.oos_efficiency != null
                        ? b.oos_efficiency.toFixed(3)
                        : "—"}
                    </td>
                    <td className="p-2">
                      {b.max_drawdown_pct != null
                        ? (b.max_drawdown_pct * 100).toFixed(1) + "%"
                        : "—"}
                    </td>
                    <td className="p-2">{b.total_trades ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* Equity curve modal */}
          {selectedBacktest && (
            <div className="mb-4 bg-gray-50 p-3 rounded">
              <div className="flex justify-between items-center mb-2">
                <h3 className="font-medium">
                  Equity — {selectedBacktest.result_id.slice(0, 8)}
                </h3>
                <button
                  onClick={() => setSelectedBacktest(null)}
                  className="text-xs text-gray-600 hover:text-gray-900"
                >
                  Close
                </button>
              </div>
              <BacktestEquityChart
                trades={selectedTrades}
                initialCapital={selectedBacktest.initial_capital ?? 100000}
              />
            </div>
          )}

          {/* Section 4: Promotion events log */}
          <h3 className="font-medium mt-6 mb-2">Promotion events</h3>
          {events.length === 0 ? (
            <p className="text-xs text-gray-500">
              No promotion events yet.
            </p>
          ) : (
            <ul className="text-sm space-y-1">
              {events.map((e) => (
                <li key={e.event_id} className="p-2 bg-gray-50 rounded">
                  <span className="text-xs text-gray-500">
                    {e.timestamp?.slice(0, 19).replace("T", " ")}
                  </span>
                  {" · "}
                  <span className={eventColor(e.to_status)}>
                    {e.from_status ?? "∅"} → {e.to_status}
                  </span>
                  {" · "}
                  <span className="text-xs">{e.triggered_by}</span>
                  {e.justification_note && (
                    <div className="text-xs text-gray-700 mt-1">
                      {e.justification_note}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
