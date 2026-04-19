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
  PASS: "bg-green-100 text-green-800 border border-green-300",
  FAIL: "bg-red-100 text-red-800 border border-red-300",
  INCONCLUSIVE: "bg-amber-100 text-amber-800 border border-amber-300",
};

const OUTCOME_LABEL = {
  PASS: "PASS",
  FAIL: "FAIL",
  INCONCLUSIVE: "INCONCLUSIVE",
};

function OutcomeBadge({ state }) {
  const cls = OUTCOME_STYLES[state] ?? "bg-gray-100 text-gray-700 border border-gray-300";
  return (
    <span className={`px-2 py-0.5 text-xs font-semibold rounded ${cls}`}>
      {OUTCOME_LABEL[state] ?? state}
    </span>
  );
}

function InconclusiveReasonBadge({ row }) {
  // INCONCLUSIVE_POWER vs INCONCLUSIVE_DATA differentiation (spec requirement:
  // distinct from INSUFFICIENT_DATA). Shows the dominant sub-cause.
  if (row.outcome_state !== "INCONCLUSIVE") return null;
  const incPower = Number(row.n_windows_inconclusive_power || 0);
  const incData = Number(row.n_windows_inconclusive_data || 0);
  const label = incData >= 2 ? "INSUFFICIENT_DATA" : "INCONCLUSIVE_POWER";
  return (
    <span className="ml-2 px-1.5 py-0.5 text-[10px] rounded bg-amber-50 text-amber-700 border border-amber-200 font-mono">
      {label}
    </span>
  );
}

function HeavyTailBadge({ flag }) {
  if (!flag) return null;
  return (
    <span className="ml-1 px-1.5 py-0.5 text-[10px] rounded bg-purple-50 text-purple-700 border border-purple-200 font-mono">
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
        className="border-t cursor-pointer hover:bg-slate-50"
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
        <td className="px-3 py-2 text-xs text-slate-500">
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
      <td colSpan={8} className="bg-slate-50 px-6 py-4">
        <div className="text-sm font-semibold mb-2">
          Per-window breakdown (run {runId.slice(0, 8)})
        </div>
        {wLoading && <div className="text-xs text-slate-500">Loading windows…</div>}
        {!wLoading && windowsResp && (
          <table className="w-full text-xs border">
            <thead className="bg-slate-200">
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
                  className={`border-t hover:bg-slate-100 cursor-pointer ${
                    selectedWindow === w.window_index ? "bg-slate-100" : ""
                  }`}
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
              <thead className="bg-slate-200">
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
                  <tr key={t.trade_id} className="border-t">
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
      <p className="text-sm text-slate-600 mb-4 max-w-3xl">
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
          <span className="text-slate-600">all five criteria satisfied</span>
        </div>
        <div className="flex items-center gap-1">
          <OutcomeBadge state="FAIL" />
          <span className="text-slate-600">at least one criterion failed with power</span>
        </div>
        <div className="flex items-center gap-1">
          <OutcomeBadge state="INCONCLUSIVE" />
          <span className="text-slate-600">≥2 windows underpowered or insufficient data</span>
        </div>
      </div>

      {/* Filter */}
      <div className="mb-3 flex items-center gap-2">
        <label className="text-xs text-slate-600">Filter outcome:</label>
        {["all", "PASS", "FAIL", "INCONCLUSIVE"].map((s) => (
          <button
            key={s}
            onClick={() => setFilterState(s)}
            className={`px-2 py-1 text-xs rounded border ${
              filterState === s
                ? "bg-slate-800 text-white border-slate-800"
                : "bg-white text-slate-700 border-slate-300 hover:bg-slate-100"
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {isLoading && <div className="text-sm text-slate-500">Loading…</div>}
      {error && (
        <div className="text-sm text-red-600">
          Error loading runs: {String(error.message || error)}
        </div>
      )}
      {!isLoading && !error && runs.length === 0 && (
        <div className="text-sm text-slate-500">
          No walk-forward runs recorded yet. Run{" "}
          <code className="px-1 bg-slate-100">
            python -m scripts.backtest.run_walkforward --strategy &lt;id&gt;
          </code>{" "}
          to generate the first result.
        </div>
      )}

      {runs.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border">
            <thead className="bg-slate-100">
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
