import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";

/**
 * Compact "4-6 key numbers with delta since last visit" panel.
 * Reads /api/system/index and highlights a curated subset of state
 * entries + counts. Delta shown when non-null; hidden on first view
 * or type change.
 *
 * Curated surface: shadow_trade_cohort, strategy_registry_state,
 * training_corpus, bootcamp_mode. Other states are browsable via
 * SystemIndexPanel below.
 */
const FEATURED_STATES = [
  "shadow_trade_cohort",
  "strategy_registry_state",
  "training_corpus",
  "bootcamp_mode",
];

function pickHeadlineNumber(stateEntry) {
  const result = stateEntry?.live?.result?.value;
  if (result == null) return null;
  if (typeof result === "number") return result;
  if (typeof result === "object") {
    if (typeof result.total === "number") return result.total;
    if (typeof result.enabled === "boolean") return result.enabled ? "ON" : "OFF";
  }
  return null;
}

function pickHeadlineDelta(stateEntry) {
  const delta = stateEntry?.delta_since_last_view;
  if (delta == null) return null;
  if (typeof delta === "number") return delta;
  if (typeof delta === "object" && typeof delta.total === "number") return delta.total;
  return null;
}

function DeltaBadge({ delta }) {
  if (delta == null || delta === 0) return null;
  const sign = delta > 0 ? "+" : "";
  const color = delta > 0 ? "text-green-700" : "text-red-700";
  return <span className={`ml-2 text-xs ${color}`}>{sign}{delta}</span>;
}

export default function QuickStatsPanel({ data, isLoading, isError }) {
  if (isLoading) {
    return (
      <div className="arcis-card mb-4">
        <h3 className="text-sm font-semibold mb-2">Quick Stats</h3>
        <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>Loading...</div>
      </div>
    );
  }
  if (isError) {
    return (
      <div className="arcis-card mb-4">
        <h3 className="text-sm font-semibold mb-2">Quick Stats</h3>
        <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>
          Temporarily unavailable. The system index API did not return a valid payload.
        </div>
      </div>
    );
  }
  if (!data) return null;

  const statesByName = Object.fromEntries((data.states || []).map((s) => [s.name, s]));
  const counts = data.counts || {};

  return (
    <div className="arcis-card mb-4">
      <div className="flex justify-between items-center mb-3">
        <h3 className="text-sm font-semibold">Quick Stats</h3>
        <span className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>
          {counts.total || 0} capabilities · {counts.needs_review || 0} need review
        </span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {FEATURED_STATES.map((name) => {
          const entry = statesByName[name];
          if (!entry) return null;
          const value = pickHeadlineNumber(entry);
          const delta = pickHeadlineDelta(entry);
          const unavailable = entry.live?.status !== "ok";
          return (
            <div
              key={name}
              className="rounded p-3"
              style={{ border: '1px solid var(--arcis-border)' }}
            >
              <div className="text-xs mb-1" style={{ color: 'var(--arcis-text-muted)' }}>{name}</div>
              <div className="text-xl font-semibold flex items-baseline">
                {unavailable ? (
                  <span className="text-sm" style={{ color: 'var(--arcis-text-muted)' }}>unavailable</span>
                ) : value == null ? (
                  <span className="text-sm" style={{ color: 'var(--arcis-text-muted)' }}>—</span>
                ) : (
                  <>
                    <span>{value}</span>
                    <DeltaBadge delta={delta} />
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
