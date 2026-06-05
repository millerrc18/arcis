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
// ---------------------------------------------------------------------------
export function GateHero({ data }) {
  const metrics = data?.metrics ?? []
  const progress = typeof data?.progress === 'number' ? data.progress : 0
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
        {metrics.map((m) => (
          <div key={m.key} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <Metric
              label={m.label}
              value={<SentinelGuard value={m.value} />}
              cohort={m.cohort}
              n={m.n}
              asOf={m.as_of}
            />
            {m.target != null && (
              <div
                style={{
                  fontSize: 10,
                  color: 'var(--arcis-text-muted, #71717a)',
                  fontFamily: 'var(--font-mono)',
                }}
              >
                target {m.target}
                {m.unit || ''}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Attention row — two-tier: positive confirmation OR routed chip
// ---------------------------------------------------------------------------
export function AttentionRow({ data }) {
  const count = data?.count ?? 0
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
const SIGNAL_SLOTS = [
  { key: 'heartbeat', label: 'Watch-loop heartbeat', maxAge: 120 },
  { key: 'data_feed', label: 'Data-feed freshness', maxAge: 300 },
  { key: 'reconciliation', label: 'Reconciliation breaks', maxAge: 3600 },
  { key: 'risk_governor', label: 'Risk limits used', maxAge: 600 },
]

export function SignalRow({ data }) {
  const incoming = data?.signals ?? []
  const byKey = new Map(incoming.map((s) => [s.key, s]))

  return (
    <section data-testid="now-signals" style={SECTION_STYLE}>
      <div style={SECTION_TITLE_STYLE}>Integrity / liveness</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
        {SIGNAL_SLOTS.map((slot) => {
          const signal = byKey.get(slot.key)
          // Absence (or missing as_of) => asOf is null => StalenessBadge unknown.
          const asOf = signal?.as_of ?? null
          const maxAge = signal?.max_age ?? slot.maxAge
          return (
            <div
              key={slot.key}
              data-testid={`signal-${slot.key}`}
              style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 160 }}
            >
              {signal && signal.cohort != null && signal.n != null && signal.as_of != null ? (
                <Metric
                  label={slot.label}
                  value={<SentinelGuard value={signal.value} />}
                  cohort={signal.cohort}
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
              <StalenessBadge asOf={asOf} maxAge={maxAge} />
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
export function PositionsSection({ data }) {
  const positions = data?.positions ?? []
  const equity = data?.equity
  const todayMove = data?.today_move

  return (
    <section data-testid="now-positions" style={SECTION_STYLE}>
      <div style={SECTION_TITLE_STYLE}>
        Open positions{data?.source ? ` · ${data.source}` : ''}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
        {equity && (
          <Metric
            label="Equity"
            value={<SentinelGuard value={equity.value} />}
            cohort={equity.cohort}
            n={equity.n}
            asOf={equity.as_of}
          />
        )}
        {todayMove && (
          <Metric
            label="Today's move"
            value={<SentinelGuard value={todayMove.value} />}
            cohort={todayMove.cohort}
            n={todayMove.n}
            asOf={todayMove.as_of}
          />
        )}
      </div>

      {positions.length === 0 ? (
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
  const hours = data?.hours
  const items = [
    { label: 'opened', value: data?.opened },
    { label: 'closed', value: data?.closed },
    { label: 'alerts raised', value: data?.alerts_raised },
    { label: 'alerts resolved', value: data?.alerts_resolved },
    { label: 'audit verdict changes', value: data?.audit_verdict_changes },
    { label: 'deploys', value: data?.deploys },
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
  const prs = data?.prs_this_week
  const regressions = data?.regressions_this_week
  const scope = data?.scope_violations_this_week

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
        {data?.current_activity || 'idle'}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
        {prs && (
          <Metric
            label="PRs this week"
            value={<SentinelGuard value={prs.value} />}
            cohort={prs.cohort}
            n={prs.n}
            asOf={prs.as_of}
          />
        )}
        {regressions && (
          <Metric
            label="Regressions"
            value={<SentinelGuard value={regressions.value} />}
            cohort={regressions.cohort}
            n={regressions.n}
            asOf={regressions.as_of}
          />
        )}
        {scope && (
          <Metric
            label="Scope violations"
            value={<SentinelGuard value={scope.value} />}
            cohort={scope.cohort}
            n={scope.n}
            asOf={scope.as_of}
          />
        )}
      </div>
    </section>
  )
}
