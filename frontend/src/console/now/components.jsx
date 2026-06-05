/**
 * NOW region sub-components (T9).
 * Built ENTIRELY from the T7 honesty primitives. Every number renders
 * through <Metric> or <SentinelGuard>; every freshness through <StalenessBadge>.
 *
 * Law #4 is enforced by the canonical signal slots: a signal that is absent
 * from the API response still renders its slot with an UNKNOWN StalenessBadge
 * (asOf=null) — never green/healthy on missing data.
 */
import { Link } from 'react-router-dom'
import Metric from '../components/Metric'
import SentinelGuard from '../components/SentinelGuard'
import StalenessBadge from '../components/StalenessBadge'

const SECTION_STYLE = {
  padding: '16px 24px',
  borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
}

const SECTION_TITLE_STYLE = {
  fontSize: 11,
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  color: 'var(--arcis-text-muted, #71717a)',
  fontFamily: 'var(--font-mono)',
  fontWeight: 600,
  marginBottom: 12,
}

// ---------------------------------------------------------------------------
// Gate hero — north-star progress vs targets, honest about the gap
// Contract: metrics is a DICT keyed by metric id; targets is a SEPARATE dict.
// There is NO top-level progress — the bar is computed client-side (presentation
// only) from value-vs-target.
// ---------------------------------------------------------------------------
const GATE_METRIC_ORDER = [
  'closed_trade_count',
  'excess_sharpe_vs_spy',
  'sharpe_t_stat',
  'max_drawdown',
]

const GATE_METRIC_LABELS = {
  closed_trade_count: 'Closed trades',
  excess_sharpe_vs_spy: 'Excess Sharpe vs SPY',
  sharpe_t_stat: 'Sharpe t-stat',
  max_drawdown: 'Max drawdown',
}

function gateRatio(id, value, target) {
  if (typeof value !== 'number' || typeof target !== 'number' || target === 0) return null
  // max_drawdown is a "lower is better" metric: progress is how far under target.
  if (id === 'max_drawdown') {
    return Math.max(0, Math.min(1, 1 - value / target))
  }
  return Math.max(0, Math.min(1, value / target))
}

export function GateHero({ data }) {
  const metrics = data?.metrics ?? {}
  const targets = data?.targets ?? {}
  const ids = GATE_METRIC_ORDER.filter((id) => id in metrics)
  const orderedIds = ids.length > 0 ? ids : Object.keys(metrics)

  const ratios = orderedIds
    .map((id) => gateRatio(id, metrics[id]?.value, targets[id]))
    .filter((r) => r != null)
  const progress = ratios.length > 0 ? ratios.reduce((a, b) => a + b, 0) / ratios.length : 0
  const pct = Math.max(0, Math.min(1, progress)) * 100

  return (
    <section data-testid="now-gate-hero" style={SECTION_STYLE}>
      <div style={SECTION_TITLE_STYLE}>North-star gate</div>

      <div
        data-testid="gate-progress-bar"
        role="progressbar"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        style={{
          height: 8,
          borderRadius: 4,
          background: 'var(--arcis-border, rgba(255,255,255,0.08))',
          overflow: 'hidden',
          marginBottom: 16,
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            background: 'var(--arcis-accent, #6366f1)',
          }}
        />
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
        {orderedIds.map((id) => {
          const m = metrics[id] || {}
          const target = targets[id]
          return (
            <div key={id} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <Metric
                label={GATE_METRIC_LABELS[id] || id}
                value={<SentinelGuard value={m.value} />}
                cohort={m.cohort}
                n={m.n}
                asOf={m.as_of}
              />
              {target != null && (
                <div
                  style={{
                    fontSize: 10,
                    color: 'var(--arcis-text-muted, #71717a)',
                    fontFamily: 'var(--font-mono)',
                  }}
                >
                  target {target}
                  {m.unit || ''}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Attention row — two-tier: positive confirmation OR routed chip
// ---------------------------------------------------------------------------
export function AttentionRow({ data }) {
  // Contract: pending_count is an ENV (.value = the count); desk_healthy is a bool.
  const count = data?.pending_count?.value ?? 0
  const deskHealthy = data?.desk_healthy === true && count === 0

  return (
    <section style={SECTION_STYLE}>
      {deskHealthy ? (
        <div
          data-testid="attention-healthy"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 14px',
            borderRadius: 'var(--radius-sm)',
            color: 'var(--arcis-success, #22c55e)',
            background: 'rgba(34,197,94,0.08)',
            border: '1px solid rgba(34,197,94,0.3)',
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          Desk healthy — nothing requires action
        </div>
      ) : (
        <Link
          to="/console/decide"
          data-testid="attention-chip"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 14px',
            borderRadius: 'var(--radius-sm)',
            color: 'var(--arcis-warning, #f59e0b)',
            background: 'rgba(245,158,11,0.1)',
            border: '1px solid rgba(245,158,11,0.4)',
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            fontWeight: 600,
            textDecoration: 'none',
          }}
        >
          {count} decision{count === 1 ? '' : 's'} waiting → Decide
        </Link>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Signal row — canonical liveness slots. ABSENCE renders UNKNOWN (law #4).
// ---------------------------------------------------------------------------
// Contract: signals is a DICT keyed by canonical id. Canonical keys are
// heartbeat, data_feed, reconciliation, risk_limits (NOT risk_governor).
// SIG = {value, n, as_of, state, healthy}.
const SIGNAL_SLOTS = [
  { key: 'heartbeat', label: 'Watch-loop heartbeat', maxAge: 120 },
  { key: 'data_feed', label: 'Data-feed freshness', maxAge: 300 },
  { key: 'reconciliation', label: 'Reconciliation breaks', maxAge: 3600 },
  { key: 'risk_limits', label: 'Risk limits used', maxAge: 600 },
]

// Law #4: a signal is unknown (never green) if it is absent, has state
// "unknown", a null/missing as_of, or a null healthy flag.
function signalIsUnknown(signal) {
  if (!signal) return true
  if (signal.state === 'unknown') return true
  if (signal.as_of == null) return true
  if (signal.healthy == null) return true
  return false
}

export function SignalRow({ data }) {
  const incoming = data?.signals ?? {}

  return (
    <section data-testid="now-signals" style={SECTION_STYLE}>
      <div style={SECTION_TITLE_STYLE}>Integrity / liveness</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
        {SIGNAL_SLOTS.map((slot) => {
          const signal = incoming[slot.key]
          const unknown = signalIsUnknown(signal)
          // Unknown signals MUST render the StalenessBadge unknown variant
          // (asOf=null forces "unknown", never green) — law #4.
          const asOf = unknown ? null : signal.as_of
          return (
            <div
              key={slot.key}
              data-testid={`signal-${slot.key}`}
              style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 160 }}
            >
              {!unknown && signal.n != null ? (
                <Metric
                  label={slot.label}
                  value={<SentinelGuard value={signal.value} />}
                  cohort="live"
                  n={signal.n}
                  asOf={signal.as_of}
                />
              ) : (
                <div
                  style={{
                    fontSize: 11,
                    textTransform: 'uppercase',
                    letterSpacing: '0.06em',
                    color: 'var(--arcis-text-secondary, #a1a1aa)',
                    fontWeight: 500,
                    fontFamily: 'var(--font-mono)',
                  }}
                >
                  {slot.label}
                </div>
              )}
              <StalenessBadge asOf={asOf} maxAge={slot.maxAge} />
            </div>
          )
        })}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Open positions — canonical reconciled source
// ---------------------------------------------------------------------------
const POSITIONS_NODATA_STYLE = {
  fontSize: 12,
  color: 'var(--arcis-text-muted, #71717a)',
  fontFamily: 'var(--font-mono)',
  fontStyle: 'italic',
}

export function PositionsSection({ data }) {
  // Contract: key is data_source (NOT source). positions may be a list or null.
  // The canonical TradingState source carries NO account equity / today's-move —
  // render those as an explicit "no data" state, never fabricated.
  const dataSource = data?.data_source
  const state = data?.state
  const rawPositions = data?.positions
  const positionsUnknown =
    rawPositions == null || state === 'unknown' || state === 'no_data'
  const positions = Array.isArray(rawPositions) ? rawPositions : []

  return (
    <section data-testid="now-positions" style={SECTION_STYLE}>
      <div style={SECTION_TITLE_STYLE}>
        Open positions{dataSource ? ` · ${dataSource}` : ''}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, marginBottom: 12 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span
            style={{
              fontSize: 11,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              color: 'var(--arcis-text-secondary, #a1a1aa)',
              fontWeight: 500,
            }}
          >
            Equity
          </span>
          <span data-testid="equity-no-data" style={POSITIONS_NODATA_STYLE}>
            no data — pending account-equity source
          </span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span
            style={{
              fontSize: 11,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              color: 'var(--arcis-text-secondary, #a1a1aa)',
              fontWeight: 500,
            }}
          >
            Today's move
          </span>
          <span data-testid="today-move-no-data" style={POSITIONS_NODATA_STYLE}>
            no data — pending account-equity source
          </span>
        </div>
      </div>

      {positionsUnknown ? (
        <div data-testid="positions-unknown" style={POSITIONS_NODATA_STYLE}>
          positions unavailable — source state unknown
        </div>
      ) : positions.length === 0 ? (
        <div
          style={{
            fontSize: 12,
            color: 'var(--arcis-text-muted, #71717a)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          No open positions
        </div>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {positions.map((p) => (
            <li
              key={p.ticker}
              style={{
                display: 'flex',
                gap: 16,
                fontFamily: 'var(--font-mono)',
                fontSize: 13,
                color: 'var(--arcis-text-primary, #fff)',
              }}
            >
              <span style={{ fontWeight: 600, minWidth: 64 }}>{p.ticker}</span>
              <span>qty <SentinelGuard value={p.qty} /></span>
              <span>mv <SentinelGuard value={p.market_value} /></span>
              <span>pnl <SentinelGuard value={p.unrealized_pnl} /></span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Since-band — "Since you last looked (Nh ago)"
// ---------------------------------------------------------------------------
export function SinceBand({ data }) {
  // Contract: counts are nested under delta; the field is audit_changes.
  const hours = data?.hours
  const delta = data?.delta ?? {}
  const items = [
    { label: 'opened', value: delta.opened },
    { label: 'closed', value: delta.closed },
    { label: 'alerts raised', value: delta.alerts_raised },
    { label: 'alerts resolved', value: delta.alerts_resolved },
    { label: 'audit changes', value: delta.audit_changes },
    { label: 'deploys', value: delta.deploys },
  ]

  return (
    <section data-testid="now-since" style={SECTION_STYLE}>
      <div style={SECTION_TITLE_STYLE}>
        Since you last looked{hours != null ? ` (${hours}h ago)` : ''}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
        {items.map((it) => (
          <div
            key={it.label}
            style={{
              display: 'flex',
              gap: 6,
              fontFamily: 'var(--font-mono)',
              fontSize: 13,
              color: 'var(--arcis-text-secondary, #a1a1aa)',
            }}
          >
            <SentinelGuard value={it.value} />
            <span>{it.label}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Dev-team quiet strip
// ---------------------------------------------------------------------------
export function DevTeamStrip({ data }) {
  // Contract: activity (NOT current_activity); this_week.{prs,regressions,scope_violations}.
  const thisWeek = data?.this_week ?? {}
  const items = [
    { label: 'PRs this week', value: thisWeek.prs },
    { label: 'Regressions', value: thisWeek.regressions },
    { label: 'Scope violations', value: thisWeek.scope_violations },
  ]

  return (
    <section data-testid="now-devteam" style={SECTION_STYLE}>
      <div style={SECTION_TITLE_STYLE}>AI dev team</div>
      <div
        style={{
          fontSize: 13,
          fontFamily: 'var(--font-mono)',
          color: 'var(--arcis-text-secondary, #a1a1aa)',
          marginBottom: 12,
        }}
      >
        {data?.activity || 'idle'}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
        {items.map((it) => (
          <div
            key={it.label}
            style={{
              display: 'flex',
              gap: 6,
              fontFamily: 'var(--font-mono)',
              fontSize: 13,
              color: 'var(--arcis-text-secondary, #a1a1aa)',
            }}
          >
            <SentinelGuard value={it.value} />
            <span>{it.label}</span>
          </div>
        ))}
      </div>
    </section>
  )
}
