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

const STATUS_BADGE_STYLES = {
  proposed: { background: 'var(--arcis-bg-elevated)', color: 'var(--arcis-text-secondary)' },
  backtested: { background: 'rgba(59,130,246,0.12)', color: 'var(--arcis-info)' },
  shadow_trading: { background: 'rgba(245,158,11,0.12)', color: 'var(--arcis-warning)' },
  production: { background: 'rgba(34,197,94,0.12)', color: 'var(--arcis-success)' },
  deprecated: { background: 'rgba(239,68,68,0.12)', color: 'var(--arcis-danger)' },
};

function StatusBadge({ status }) {
  const s = STATUS_BADGE_STYLES[status] ?? { background: 'var(--arcis-bg-elevated)', color: 'var(--arcis-text-secondary)' };
  return (
    <span className="px-2 py-0.5 text-xs rounded" style={s}>
      {status}
    </span>
  );
}

function eventColor(toStatus) {
  if (toStatus === "deprecated") return 'var(--arcis-danger)';
  if (toStatus === "shadow_trading" || toStatus === "production") return 'var(--arcis-success)';
  return 'var(--arcis-text-secondary)';
}

export default function StrategyResearch() {
  const [expandedId, setExpandedId] = useState(null);
  const [selectedBacktest, setSelectedBacktest] = useState(null);

  const { data, isLoading } = useQuery({
    queryKey: ["platform-strategies"],
    queryFn: () => getPlatformStrategies(),
  });
  // Defensive: backend has returned non-array shapes on error paths. The
  // = [] destructuring default only fires on `undefined`, not null / {}.
  const strategies = Array.isArray(data) ? data : [];

  const { data: detail } = useQuery({
    enabled: !!expandedId,
    queryKey: ["platform-strategy", expandedId],
    queryFn: () => getPlatformStrategyDetail(expandedId),
  });

  const { data: backtestsData } = useQuery({
    enabled: !!expandedId,
    queryKey: ["platform-backtests", expandedId],
    queryFn: () => getPlatformBacktestResults(expandedId),
  });
  const backtests = Array.isArray(backtestsData) ? backtestsData : [];

  const { data: eventsData } = useQuery({
    enabled: !!expandedId,
    queryKey: ["platform-events", expandedId],
    queryFn: () => getPlatformPromotionEvents(expandedId),
  });
  const events = Array.isArray(eventsData) ? eventsData : [];

  const { data: tradesData } = useQuery({
    enabled: !!selectedBacktest,
    queryKey: ["platform-trades", selectedBacktest?.result_id],
    queryFn: () => getPlatformBacktestTrades(selectedBacktest.result_id),
  });
  const selectedTrades = Array.isArray(tradesData) ? tradesData : [];

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-4">Strategy Research</h1>

      {/* Section 1: Registry table */}
      <section className="mb-8">
        <h2 className="text-lg font-medium mb-2">Strategies</h2>
        {isLoading ? (
          <div style={{ color: 'var(--arcis-text-secondary)' }}>Loading…</div>
        ) : strategies.length === 0 ? (
          <p className="p-4 rounded" style={{ color: 'var(--arcis-text-secondary)', background: 'var(--arcis-bg-elevated)' }}>
            No strategies registered yet. Load one from{" "}
            <code>src/platform/specs/*.yaml</code> and run a backtest
            via <code>scripts/run_backtest.py</code>.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead style={{ background: 'var(--arcis-bg-elevated)' }}>
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
                  className="cursor-pointer"
                  style={{ borderTop: '1px solid var(--arcis-border)' }}
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
                  <td className="p-2 text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>
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
        <section className="mb-8 pl-4" style={{ borderLeft: '4px solid var(--arcis-accent)' }}>
          <h2 className="text-lg font-medium mb-2">
            {detail.display_name}{" "}
            <span className="text-xs font-mono" style={{ color: 'var(--arcis-text-secondary)' }}>
              {detail.current_spec_hash?.slice(0, 12)}
            </span>
          </h2>
          <p className="text-sm mb-3">
            Status: <StatusBadge status={detail.current_status} />
          </p>

          {detail.spec && (
            <details className="mb-4">
              <summary className="cursor-pointer text-sm" style={{ color: 'var(--arcis-accent)' }}>
                YAML spec
              </summary>
              <pre className="text-xs p-3 rounded overflow-auto max-h-80" style={{ background: 'var(--arcis-bg-elevated)' }}>
                {JSON.stringify(detail.spec, null, 2)}
              </pre>
            </details>
          )}

          {/* Section 3: Backtest results grid */}
          <h3 className="font-medium mt-4 mb-2">Backtest history</h3>
          {backtests.length === 0 ? (
            <p className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>
              No backtest results yet for this strategy.
            </p>
          ) : (
            <table className="w-full text-sm mb-4">
              <thead style={{ background: 'var(--arcis-bg-elevated)' }}>
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
                    className="cursor-pointer"
                    style={{ borderTop: '1px solid var(--arcis-border)' }}
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
            <div className="mb-4 p-3 rounded" style={{ background: 'var(--arcis-bg-elevated)' }}>
              <div className="flex justify-between items-center mb-2">
                <h3 className="font-medium">
                  Equity — {selectedBacktest.result_id.slice(0, 8)}
                </h3>
                <button
                  onClick={() => setSelectedBacktest(null)}
                  className="text-xs"
                  style={{ color: 'var(--arcis-text-secondary)' }}
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
            <p className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>
              No promotion events yet.
            </p>
          ) : (
            <ul className="text-sm space-y-1">
              {events.map((e) => (
                <li key={e.event_id} className="p-2 rounded" style={{ background: 'var(--arcis-bg-elevated)' }}>
                  <span className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>
                    {e.timestamp?.slice(0, 19).replace("T", " ")}
                  </span>
                  {" · "}
                  <span style={{ color: eventColor(e.to_status) }}>
                    {e.from_status ?? "∅"} → {e.to_status}
                  </span>
                  {" · "}
                  <span className="text-xs">{e.triggered_by}</span>
                  {e.justification_note && (
                    <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
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
