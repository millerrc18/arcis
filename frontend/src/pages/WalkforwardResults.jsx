import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getWalkforwardRuns,
  getWalkforwardRun,
  getWalkforwardRunWindows,
  getWalkforwardRunTrades,
} from "../api.js";

// Three-state outcome color coding. INCONCLUSIVE is distinct amber from FAIL red.
// Sub-badges distinguish INCONCLUSIVE_POWER from INSUFFICIENT_DATA per spec.
const OUTCOME_STYLES = {
  PASS: { background: 'rgba(34,197,94,0.12)', color: 'var(--arcis-success)', border: '1px solid rgba(34,197,94,0.3)' },
  FAIL: { background: 'rgba(239,68,68,0.12)', color: 'var(--arcis-danger)', border: '1px solid rgba(239,68,68,0.3)' },
  INCONCLUSIVE: { background: 'rgba(245,158,11,0.12)', color: 'var(--arcis-warning)', border: '1px solid rgba(245,158,11,0.3)' },
};

const OUTCOME_LABEL = {
  PASS: "PASS",
  FAIL: "FAIL",
  INCONCLUSIVE: "INCONCLUSIVE",
};

function OutcomeBadge({ state }) {
  const s = OUTCOME_STYLES[state] ?? { background: 'var(--arcis-bg-elevated)', color: 'var(--arcis-text-secondary)', border: '1px solid var(--arcis-border)' };
  return (
    <span className="px-2 py-0.5 text-xs font-semibold rounded" style={s}>
      {OUTCOME_LABEL[state] ?? state}
    </span>
  );
}

function InconclusiveReasonBadge({ row }) {
  if (row.outcome_state !== "INCONCLUSIVE") return null;
  const incPower = Number(row.n_windows_inconclusive_power || 0);
  const incData = Number(row.n_windows_inconclusive_data || 0);
  const label = incData >= 2 ? "INSUFFICIENT_DATA" : "INCONCLUSIVE_POWER";
  return (
    <span className="ml-2 px-1.5 py-0.5 text-[10px] rounded font-mono"
      style={{ background: 'rgba(245,158,11,0.1)', color: 'var(--arcis-warning)', border: '1px solid rgba(245,158,11,0.2)' }}>
      {label}
    </span>
  );
}

function HeavyTailBadge({ flag }) {
  if (!flag) return null;
  return (
    <span className="ml-1 px-1.5 py-0.5 text-[10px] rounded font-mono"
      style={{ background: 'rgba(168,85,247,0.1)', color: '#c084fc', border: '1px solid rgba(168,85,247,0.2)' }}>
      HEAVY-TAIL
    </span>
  );
}

function numberOrDash(v, digits = 3) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "∞";
  return n.toFixed(digits);
}

function RunRow({ row, expanded, onToggle }) {
  return (
    <>
      <tr
        className="cursor-pointer"
        style={{ borderTop: '1px solid var(--arcis-border)' }}
        onClick={onToggle}
      >
        <td className="px-3 py-2 font-mono text-xs">{row.strategy_id}</td>
        <td className="px-3 py-2">
          <OutcomeBadge state={row.outcome_state} />
          <InconclusiveReasonBadge row={row} />
          <HeavyTailBadge flag={row.heavy_tail_flag} />
        </td>
        <td className="px-3 py-2 font-mono text-xs">{row.reason}</td>
        <td className="px-3 py-2 text-right font-mono">{numberOrDash(row.pooled_sharpe)}</td>
        <td className="px-3 py-2 text-right font-mono">{numberOrDash(row.pooled_mde)}</td>
        <td className="px-3 py-2 text-center font-mono text-xs">
          {row.n_windows_pass}/{row.n_windows_fail}/{row.n_windows_inconclusive_data}/{row.n_windows_inconclusive_power}
        </td>
        <td className="px-3 py-2 text-center font-mono text-xs">
          {row.derived_from_source_type ?? "null"}
        </td>
        <td className="px-3 py-2 text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>
          {row.created_at?.slice(0, 19).replace("T", " ")}
        </td>
      </tr>
      {expanded && <RunDetailRow runId={row.run_id} />}
    </>
  );
}

function RunDetailRow({ runId }) {
  const { data: windowsResp, isLoading: wLoading } = useQuery({
    queryKey: ["wf-windows", runId],
    queryFn: () => getWalkforwardRunWindows(runId),
  });
  const [selectedWindow, setSelectedWindow] = useState(null);
  const { data: tradesResp } = useQuery({
    queryKey: ["wf-trades", runId, selectedWindow],
    queryFn: () => getWalkforwardRunTrades(runId, selectedWindow),
    enabled: selectedWindow !== null,
  });
  return (
    <tr>
      <td colSpan={8} className="px-6 py-4" style={{ background: 'var(--arcis-bg-elevated)' }}>
        <div className="text-sm font-semibold mb-2">
          Per-window breakdown (run {runId.slice(0, 8)})
        </div>
        {wLoading && <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Loading windows…</div>}
        {!wLoading && windowsResp && (
          <table className="w-full text-xs border">
            <thead style={{ background: 'var(--arcis-bg-primary)' }}>
              <tr>
                <th className="px-2 py-1 text-left">Window</th>
                <th className="px-2 py-1 text-right">Trades</th>
                <th className="px-2 py-1 text-right">Sharpe</th>
                <th className="px-2 py-1 text-right">MDE</th>
                <th className="px-2 py-1 text-right">Bootstrap SE</th>
                <th className="px-2 py-1 text-right">VIX tiers</th>
              </tr>
            </thead>
            <tbody>
              {(windowsResp.windows || []).map((w) => (
                <tr
                  key={w.window_index}
                  className="cursor-pointer"
                  style={{
                    borderTop: '1px solid var(--arcis-border)',
                    background: selectedWindow === w.window_index ? 'var(--arcis-bg-elevated)' : 'transparent',
                  }}
                  onClick={() => setSelectedWindow(
                    selectedWindow === w.window_index ? null : w.window_index,
                  )}
                >
                  <td className="px-2 py-1 font-mono">{w.window_index}</td>
                  <td className="px-2 py-1 text-right font-mono">{w.n_trades}</td>
                  <td className="px-2 py-1 text-right font-mono">{numberOrDash(w.sharpe)}</td>
                  <td className="px-2 py-1 text-right font-mono">{numberOrDash(w.mde)}</td>
                  <td className="px-2 py-1 text-right font-mono">{numberOrDash(w.bootstrap_se)}</td>
                  <td className="px-2 py-1 text-right font-mono">{w.distinct_vix_tiers}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {selectedWindow !== null && tradesResp && (
          <div className="mt-3">
            <div className="text-xs font-semibold mb-1">
              Trades in window {selectedWindow} ({tradesResp.count} shown)
            </div>
            <table className="w-full text-xs border">
              <thead style={{ background: 'var(--arcis-bg-primary)' }}>
                <tr>
                  <th className="px-2 py-1 text-left">Ticker</th>
                  <th className="px-2 py-1 text-left">Entry</th>
                  <th className="px-2 py-1 text-left">Exit</th>
                  <th className="px-2 py-1 text-right">PnL %</th>
                  <th className="px-2 py-1 text-left">VIX tier</th>
                </tr>
              </thead>
              <tbody>
                {(tradesResp.trades || []).slice(0, 50).map((t) => (
                  <tr key={t.trade_id} style={{ borderTop: '1px solid var(--arcis-border)' }}>
                    <td className="px-2 py-1 font-mono">{t.ticker}</td>
                    <td className="px-2 py-1 font-mono">{t.entry_date}</td>
                    <td className="px-2 py-1 font-mono">{t.exit_date || "—"}</td>
                    <td className="px-2 py-1 text-right font-mono">
                      {numberOrDash(t.pnl_pct, 4)}
                    </td>
                    <td className="px-2 py-1 font-mono">{t.vix_tier || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </td>
    </tr>
  );
}

export default function WalkforwardResults() {
  const [filterState, setFilterState] = useState("all");
  const [expandedRun, setExpandedRun] = useState(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["wf-runs", filterState],
    queryFn: () => getWalkforwardRuns(
      filterState === "all" ? {} : { outcome_state: filterState },
    ),
  });

  const runs = Array.isArray(data?.runs) ? data.runs : [];

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-2">Walk-Forward Validation Results</h1>
      <p className="text-sm mb-4 max-w-3xl" style={{ color: 'var(--arcis-text-secondary)' }}>
        Three-state outcome framework (PASS / FAIL / INCONCLUSIVE). Every
        strategy must clear walk-forward v1 before promotion to shadow
        trading. INCONCLUSIVE is distinct from FAIL — it means the sample
        was too small or too heavy-tailed to distinguish a real effect
        from noise, regardless of observed Sharpe.
      </p>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 mb-4 text-xs">
        <div className="flex items-center gap-1">
          <OutcomeBadge state="PASS" />
          <span style={{ color: 'var(--arcis-text-secondary)' }}>all five criteria satisfied</span>
        </div>
        <div className="flex items-center gap-1">
          <OutcomeBadge state="FAIL" />
          <span style={{ color: 'var(--arcis-text-secondary)' }}>at least one criterion failed with power</span>
        </div>
        <div className="flex items-center gap-1">
          <OutcomeBadge state="INCONCLUSIVE" />
          <span style={{ color: 'var(--arcis-text-secondary)' }}>≥2 windows underpowered or insufficient data</span>
        </div>
      </div>

      {/* Filter */}
      <div className="mb-3 flex items-center gap-2">
        <label className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Filter outcome:</label>
        {["all", "PASS", "FAIL", "INCONCLUSIVE"].map((s) => (
          <button
            key={s}
            onClick={() => setFilterState(s)}
            className="px-2 py-1 text-xs rounded"
            style={filterState === s
              ? { background: 'var(--arcis-accent)', color: '#fff', border: '1px solid var(--arcis-accent)' }
              : { background: 'var(--arcis-bg-elevated)', color: 'var(--arcis-text-secondary)', border: '1px solid var(--arcis-border)' }}
          >
            {s}
          </button>
        ))}
      </div>

      {isLoading && <div className="text-sm" style={{ color: 'var(--arcis-text-secondary)' }}>Loading…</div>}
      {error && (
        <div className="text-sm" style={{ color: 'var(--arcis-danger)' }}>
          Error loading runs: {String(error.message || error)}
        </div>
      )}
      {!isLoading && !error && runs.length === 0 && (
        <div className="text-sm" style={{ color: 'var(--arcis-text-secondary)' }}>
          No walk-forward runs recorded yet. Run{" "}
          <code className="px-1" style={{ background: 'var(--arcis-bg-elevated)' }}>
            python -m scripts.backtest.run_walkforward --strategy &lt;id&gt;
          </code>{" "}
          to generate the first result.
        </div>
      )}

      {runs.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border">
            <thead style={{ background: 'var(--arcis-bg-elevated)' }}>
              <tr>
                <th className="px-3 py-2 text-left">Strategy</th>
                <th className="px-3 py-2 text-left">Outcome</th>
                <th className="px-3 py-2 text-left">Reason</th>
                <th className="px-3 py-2 text-right">Pooled Sharpe</th>
                <th className="px-3 py-2 text-right">Pooled MDE</th>
                <th className="px-3 py-2 text-center">P/F/I-D/I-P</th>
                <th className="px-3 py-2 text-center">derived_from</th>
                <th className="px-3 py-2 text-left">Created</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <RunRow
                  key={r.run_id}
                  row={r}
                  expanded={expandedRun === r.run_id}
                  onToggle={() =>
                    setExpandedRun(expandedRun === r.run_id ? null : r.run_id)
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
