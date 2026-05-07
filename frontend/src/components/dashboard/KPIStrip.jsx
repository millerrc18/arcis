/**
 * KPIStrip — 5-KPI hero strip for the Dashboard.
 *
 * Track 1.5 / Round 8.B. Resolves R1, S1, S2, G3, G6.
 * Color tokens: --arcis-success (green), --arcis-warning (amber),
 *   --arcis-danger (red), --arcis-info (blue), --arcis-text-muted (unknown/gray).
 */
import Tooltip from '../Tooltip'

const STATUS_COLOR = {
  green:   'var(--arcis-success)',
  amber:   'var(--arcis-warning)',
  red:     'var(--arcis-danger)',
  blue:    'var(--arcis-info)',
  unknown: 'var(--arcis-text-muted)',
}

const DEFAULT_KPIS = {
  rf_adjusted_excess_sharpe: {
    value: null,
    p_value: null,
    ci_lower: null,
    ci_upper: null,
    status: 'unknown',
  },
  spy_relative_sharpe: {
    value: null,
    p_value: null,
    ci_lower: null,
    ci_upper: null,
    status: 'unknown',
  },
  win_rate: {
    value: null,
    n_wins: 0,
    n_losses: 0,
    status: 'unknown',
  },
  stage_traffic_light: {
    status: 'unknown',
    S: null,
    t_stat: null,
    ci_lower: null,
    decision_matrix_state: 'HALT',
  },
  promotion_gate: {
    votes_passed: null,
    votes_total: 5,
    status: 'blue',
    caption: 'KPI data unavailable',
  },
}

function isRecord(value) {
  return value != null && typeof value === 'object' && !Array.isArray(value)
}

function withDefaults(value, defaults) {
  return isRecord(value) ? { ...defaults, ...value } : { ...defaults }
}

function normalizeKpis(kpis) {
  if (!isRecord(kpis)) return null
  return {
    ...kpis,
    rf_adjusted_excess_sharpe: withDefaults(kpis.rf_adjusted_excess_sharpe, DEFAULT_KPIS.rf_adjusted_excess_sharpe),
    spy_relative_sharpe: withDefaults(kpis.spy_relative_sharpe, DEFAULT_KPIS.spy_relative_sharpe),
    win_rate: withDefaults(kpis.win_rate, DEFAULT_KPIS.win_rate),
    stage_traffic_light: withDefaults(kpis.stage_traffic_light, DEFAULT_KPIS.stage_traffic_light),
    promotion_gate: withDefaults(kpis.promotion_gate, DEFAULT_KPIS.promotion_gate),
  }
}

function StatusPill({ status, label }) {
  const color = STATUS_COLOR[status] || STATUS_COLOR.unknown
  return (
    <span
      className={`kpi-pill kpi-pill--${status}`}
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 'var(--radius-sm)',
        fontSize: 11,
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        color,
        background: `${color}1a`,
        border: `1px solid ${color}33`,
      }}
    >
      {label || status}
    </span>
  )
}

export function KPICard({ title, value, status, subLine, caption, meta, children }) {
  const color = STATUS_COLOR[status] || STATUS_COLOR.unknown
  return (
    <div
      className="arcis-card"
      style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 6 }}
    >
      <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em',
                    color: 'var(--arcis-text-secondary)', fontWeight: 500 }}>
        {title}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 24, fontWeight: 600, fontFamily: 'var(--font-mono)',
                       color, fontVariantNumeric: 'tabular-nums' }}>
          {value ?? '--'}
        </span>
        <StatusPill status={status} label={status} />
      </div>
      {subLine && (
        <div style={{ fontSize: 11, color: 'var(--arcis-text-secondary)',
                      fontFamily: 'var(--font-mono)' }}>
          {subLine}
        </div>
      )}
      {children}
      {caption && (
        <div style={{ fontSize: 10, color: 'var(--arcis-text-muted)', marginTop: 2 }}>
          {caption}
        </div>
      )}
      {meta != null && (
        <Tooltip content={meta.label}>
          <div
            data-testid="kpi-meta-badge"
            style={{ fontSize: 10, fontStyle: 'italic', color: 'var(--arcis-text-muted)', marginTop: 4 }}
          >
            {`n=${meta.n} · ${meta.cohort.split('.').pop()}`}
          </div>
        </Tooltip>
      )}
    </div>
  )
}

function RfAdjustedCard({ kpi, n, meta }) {
  const v = kpi.value != null ? kpi.value.toFixed(2) : null
  const sub = kpi.p_value != null
    ? `p=${kpi.p_value.toFixed(2)}  CI [${(kpi.ci_lower ?? 0).toFixed(2)}, ${(kpi.ci_upper ?? 0).toFixed(2)}]`
    : null
  return (
    <KPICard
      title="rf-Adj Excess Sharpe"
      value={v}
      status={kpi.status}
      subLine={sub}
      caption={`N=${n} | canonical T1.03`}
      meta={meta}
    />
  )
}

function SpyRelativeCard({ kpi, nSpy, nTotal }) {
  const v = kpi.value != null ? kpi.value.toFixed(2) : null
  const sub = kpi.p_value != null
    ? `p=${kpi.p_value.toFixed(2)}  CI lower=${(kpi.ci_lower ?? 0).toFixed(2)}`
    : null
  // I4 — SPY-Relative is a smaller subset (only trades with spy_return_over_hold).
  // Caption shows N=<n_spy> of <n_total> so operator can see this is a subset of
  // the rf-Adj card's denominator, not the same N.
  const caption = nTotal != null && nSpy !== nTotal
    ? `N=${nSpy} of ${nTotal} instrumented | vs SPY benchmark`
    : `N=${nSpy} | vs SPY benchmark`
  return (
    <KPICard
      title="SPY-Relative Sharpe"
      value={v}
      status={kpi.status}
      subLine={sub}
      caption={caption}
    />
  )
}

function WinRateCard({ kpi, n, meta }) {
  const v = kpi.value != null ? `${(kpi.value * 100).toFixed(1)}%` : null
  const sub = kpi.n_wins != null
    ? `${kpi.n_wins}W / ${kpi.n_losses}L`
    : null
  return (
    <KPICard
      title="Win Rate"
      value={v}
      status={kpi.status}
      subLine={sub}
      caption={`N=${n} | quarantine-filtered`}
      meta={meta}
    />
  )
}

function TrafficLightCard({ kpi, n }) {
  const v = kpi.S != null ? kpi.S.toFixed(2) : null
  const sub = kpi.t_stat != null
    ? `t=${kpi.t_stat.toFixed(2)}  CI lower=${(kpi.ci_lower ?? 0).toFixed(2)}`
    : null
  return (
    <KPICard
      title="Stage Traffic Light"
      value={kpi.decision_matrix_state || '--'}
      status={kpi.status}
      subLine={sub}
      caption={`S=${v ?? '--'}  N=${n}`}
    />
  )
}

function PromotionGateCard({ kpi, nTrades, nMinTrl }) {
  const pct = Math.min(100, (nTrades / nMinTrl) * 100)
  const barColor = STATUS_COLOR[kpi.status] || STATUS_COLOR.unknown
  const v = kpi.votes_passed != null ? `${kpi.votes_passed}/5` : '--/5'
  return (
    <KPICard
      title="Promotion Gate"
      value={v}
      status={kpi.status}
      caption={kpi.caption}
    >
      <div style={{ marginTop: 4 }}>
        <div style={{ fontSize: 10, color: 'var(--arcis-text-muted)', marginBottom: 3 }}>
          Stage-2 eligibility: {nTrades} / {nMinTrl} OOS trades
        </div>
        <div style={{ height: 4, borderRadius: 'var(--radius-sm)',
                      background: 'var(--arcis-bg-elevated)', overflow: 'hidden' }}>
          <div style={{ width: `${pct}%`, height: '100%', background: barColor }} />
        </div>
      </div>
    </KPICard>
  )
}

function InstrumentationBadge({ pct }) {
  if (pct == null) return null
  return (
    <div style={{ fontSize: 11, color: 'var(--arcis-text-secondary)',
                  padding: '4px 0', display: 'flex', alignItems: 'center', gap: 6 }}>
      <span style={{ width: 8, height: 8, borderRadius: '50%',
                     background: pct >= 90 ? 'var(--arcis-success)'
                               : pct >= 50 ? 'var(--arcis-warning)'
                               : 'var(--arcis-danger)',
                     display: 'inline-block', flexShrink: 0 }} />
      <span>
        <span style={{ fontFamily: 'var(--font-mono)' }}>{pct.toFixed(0)}%</span>
        {' '}of recent trades are instrumentation v3
      </span>
    </div>
  )
}

export default function KPIStrip({ kpis, error = false, loading = false }) {
  const safeKpis = normalizeKpis(kpis)

  if (error) {
    return (
      <div className="arcis-card" style={{ padding: 20, textAlign: 'center' }}>
        <span style={{ color: 'var(--arcis-warning)', fontSize: 13 }}>
          KPI data unavailable right now
        </span>
      </div>
    )
  }

  if (loading || !safeKpis) {
    return (
      <div className="arcis-card" style={{ padding: 20, textAlign: 'center' }}>
        <span style={{ color: 'var(--arcis-text-muted)', fontSize: 13 }}>Loading KPIs...</span>
      </div>
    )
  }

  // I4 — Backend may return separate denominators: n_total (fully-instrumented
  // closed trades, used by rf-Adj/Win-Rate/Traffic-Light) and n_spy (subset
  // with spy_return_over_hold, used by SPY-Relative). Fall back to n_trades
  // when the backend has not yet split the fields, so the strip stays valid
  // across the contract migration.
  const nTotal = safeKpis.n_total ?? safeKpis.n_trades ?? 0
  const nSpy = safeKpis.n_spy ?? nTotal
  const nMin = safeKpis.n_minimum_trl ?? 150

  return (
    <div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(5, 1fr)',
          gap: 12,
        }}
        className="kpi-strip"
      >
        {/* _meta.rf_adjusted_excess_sharpe: wired — spec field 1 of 4.
            _meta.win_rate: wired — spec field 2 of 4; .n equals n_trades (spec field 3, exposed via badge).
            total_pnl_dollars: no primary value card in this strip shows dollar P&L — TODO #SP3-T12-pnl-card */}
        <RfAdjustedCard kpi={safeKpis.rf_adjusted_excess_sharpe} n={nTotal} meta={safeKpis._meta?.rf_adjusted_excess_sharpe} />
        <SpyRelativeCard kpi={safeKpis.spy_relative_sharpe} nSpy={nSpy} nTotal={nTotal} />
        <WinRateCard kpi={safeKpis.win_rate} n={nTotal} meta={safeKpis._meta?.win_rate} />
        <TrafficLightCard kpi={safeKpis.stage_traffic_light} n={nTotal} />
        <PromotionGateCard kpi={safeKpis.promotion_gate} nTrades={nTotal} nMinTrl={nMin} />
      </div>
      <InstrumentationBadge pct={safeKpis.instrumentation_pct} />
      <style>{`
        @media (max-width: 767px) {
          .kpi-strip { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  )
}
