/**
 * KNOW region sub-components (P3-T4, design §3.3).
 * Overview synthesis cards + drill-down views.
 * Each view carries its own data-testid for shell-test compatibility.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { fetchApi } from '../../api'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from 'recharts'
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

const CARD_GRID_STYLE = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
  gap: 12,
}

const CARD_STYLE = {
  display: 'flex',
  flexDirection: 'column',
  gap: 6,
  padding: '14px 16px',
  border: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
  borderRadius: 6,
  background: 'var(--arcis-surface, #18181b)',
  textDecoration: 'none',
  color: 'inherit',
  cursor: 'pointer',
  transition: 'border-color 0.15s',
}

const PINNED_CARD_STYLE = {
  ...CARD_STYLE,
  borderColor: 'var(--arcis-accent, #6366f1)',
  background: 'rgba(99,102,241,0.06)',
}

const CARD_LABEL_STYLE = {
  fontSize: 13,
  fontFamily: 'var(--font-mono)',
  fontWeight: 600,
  color: 'var(--arcis-text-primary, #fff)',
}

const CARD_HINT_STYLE = {
  fontSize: 11,
  fontFamily: 'var(--font-mono)',
  color: 'var(--arcis-text-muted, #71717a)',
}

const PINNED_BADGE_STYLE = {
  display: 'inline-block',
  fontSize: 9,
  fontFamily: 'var(--font-mono)',
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.1em',
  color: 'var(--arcis-accent, #6366f1)',
  marginBottom: 2,
}

const BACK_LINK_STYLE = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  fontSize: 12,
  fontFamily: 'var(--font-mono)',
  color: 'var(--arcis-text-muted, #71717a)',
  textDecoration: 'none',
  padding: '8px 24px',
  borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
}

const GEN_FAILED_BANNER_STYLE = {
  margin: '16px 24px',
  padding: '10px 16px',
  border: '1px solid var(--arcis-danger, #ef4444)',
  borderRadius: 6,
  background: 'rgba(239,68,68,0.08)',
  color: 'var(--arcis-danger, #ef4444)',
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
  fontWeight: 600,
}

const SHA_STAMP_STYLE = {
  fontSize: 10,
  fontFamily: 'var(--font-mono)',
  color: 'var(--arcis-text-muted, #71717a)',
  marginTop: 4,
}

const PENDING_BADGE_STYLE = {
  display: 'inline-flex',
  alignItems: 'center',
  padding: '2px 8px',
  borderRadius: 4,
  fontSize: 10,
  fontWeight: 600,
  fontFamily: 'var(--font-mono)',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  color: 'var(--arcis-text-muted, #71717a)',
  background: 'rgba(113,113,122,0.15)',
  border: '1px dashed var(--arcis-text-muted, #71717a)',
}

// ---------------------------------------------------------------------------
// BackToOverview — back affordance rendered on every drill-down
// ---------------------------------------------------------------------------
export function BackToOverview() {
  return (
    <Link to="/console/know" data-testid="know-back-link" style={BACK_LINK_STYLE}>
      ← Know overview
    </Link>
  )
}

// ---------------------------------------------------------------------------
// KnowOverview — synthesis cards (3 pinned + 5 entry cards)
// ---------------------------------------------------------------------------
const PINNED_ITEMS = [
  { label: 'Fund ladder', to: '/console/know/ladder', hint: 'Live fund composition & transitions' },
  { label: 'Track record', to: '/console/know/track-record', hint: 'Audited performance history' },
  { label: 'Trade ledgers', to: '/console/know/ledgers', hint: 'Full trade log & P&L breakdown' },
]

const ENTRY_ITEMS = [
  { label: 'System map', to: '/console/know/system-map', hint: 'Architecture & component graph' },
  { label: 'Rigor stack', to: '/console/know/rigor', hint: 'Test coverage & quality gates' },
  { label: 'Attribution', to: '/console/know/attribution', hint: 'Alpha source decomposition' },
  { label: 'Research & calibration', to: '/console/know/research', hint: 'Signal calibration log' },
  { label: 'AI dev-team scorecards', to: '/console/know/scorecards', hint: 'Agent output quality metrics' },
]

export function KnowOverview() {
  return (
    <div data-testid="know-overview">
      <section style={SECTION_STYLE}>
        <div style={SECTION_TITLE_STYLE}>Pinned — first-class synthesis</div>
        <div style={CARD_GRID_STYLE}>
          {PINNED_ITEMS.map((item) => (
            <Link key={item.to} to={item.to} style={PINNED_CARD_STYLE}>
              <span style={PINNED_BADGE_STYLE}>pinned</span>
              <span style={CARD_LABEL_STYLE}>{item.label}</span>
              <span style={CARD_HINT_STYLE}>{item.hint}</span>
            </Link>
          ))}
        </div>
      </section>

      <section style={SECTION_STYLE}>
        <div style={SECTION_TITLE_STYLE}>Drill-down library</div>
        <div style={CARD_GRID_STYLE}>
          {ENTRY_ITEMS.map((item) => (
            <Link key={item.to} to={item.to} style={CARD_STYLE}>
              <span style={CARD_LABEL_STYLE}>{item.label}</span>
              <span style={CARD_HINT_STYLE}>{item.hint}</span>
            </Link>
          ))}
        </div>
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// FundLadderView — consumes GET /console/know/ladder
// ---------------------------------------------------------------------------
function PhaseProgressBar({ progress, status }) {
  // pending phases: DISTINCT treatment — dashed outline bar, no fill, no "0"
  if (status === 'pending') {
    return (
      <div
        data-testid="phase-status-pending"
        style={{
          height: 8,
          borderRadius: 4,
          border: '1px dashed var(--arcis-text-muted, #71717a)',
          background: 'transparent',
          marginBottom: 12,
          position: 'relative',
        }}
      >
        <span
          style={{
            position: 'absolute',
            left: 0,
            top: '50%',
            transform: 'translateY(-50%)',
            fontSize: 9,
            fontFamily: 'var(--font-mono)',
            color: 'var(--arcis-text-muted, #71717a)',
            whiteSpace: 'nowrap',
            paddingLeft: 4,
          }}
        >
          pending
        </span>
      </div>
    )
  }

  const pct =
    typeof progress === 'number' ? Math.max(0, Math.min(1, progress)) * 100 : 0

  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      style={{
        height: 8,
        borderRadius: 4,
        background: 'var(--arcis-border, rgba(255,255,255,0.08))',
        overflow: 'hidden',
        marginBottom: 12,
      }}
    >
      <div
        style={{
          width: `${pct}%`,
          height: '100%',
          background:
            status === 'complete'
              ? 'var(--arcis-success, #22c55e)'
              : 'var(--arcis-accent, #6366f1)',
        }}
      />
    </div>
  )
}

function GateCard({ gate }) {
  const { metric_id, value, target, n, as_of, cohort, unit, state } = gate

  // unknown / no_data gate — StalenessBadge unknown variant + sentinel guard
  if (state === 'unknown' || state === 'no_data') {
    return (
      <div
        style={{
          padding: '8px 12px',
          border: '1px solid var(--arcis-border)',
          borderRadius: 6,
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
        }}
      >
        <div
          style={{
            fontSize: 11,
            textTransform: 'uppercase',
            color: 'var(--arcis-text-secondary)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {metric_id}
        </div>
        <SentinelGuard value={value} />
        <StalenessBadge asOf={as_of} />
      </div>
    )
  }

  // pending gate — distinct dashed treatment
  if (state === 'pending') {
    return (
      <div
        style={{
          padding: '8px 12px',
          border: '1px dashed var(--arcis-text-muted, #71717a)',
          borderRadius: 6,
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
        }}
      >
        <div
          style={{
            fontSize: 11,
            textTransform: 'uppercase',
            color: 'var(--arcis-text-muted)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {metric_id}
        </div>
        <span style={PENDING_BADGE_STYLE}>pending</span>
        {target != null && (
          <div style={{ fontSize: 10, color: 'var(--arcis-text-muted)', fontFamily: 'var(--font-mono)' }}>
            target {target}{unit || ''}
          </div>
        )}
      </div>
    )
  }

  // normal gate — Metric primitive (requires cohort/n/asOf)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <Metric
        label={metric_id}
        value={<SentinelGuard value={value} />}
        cohort={cohort}
        n={n}
        asOf={as_of}
      />
      {target != null && (
        <div style={{ fontSize: 10, color: 'var(--arcis-text-muted, #71717a)', fontFamily: 'var(--font-mono)' }}>
          target {target}{unit || ''}
        </div>
      )}
    </div>
  )
}

export function FundLadderView() {
  const query = useQuery({
    queryKey: ['console-know-ladder'],
    queryFn: () => fetchApi('/console/know/ladder'),
  })

  const data = query.data
  const phases = data?.ladder ?? []
  const generationOk = data?.generation_ok !== false
  const sourceSha = data?.source_sha ?? ''
  const asOf = data?.as_of ?? null

  return (
    <div>
      <BackToOverview />
      <div data-testid="know-ladder">
        {/* LAW #7: fail-closed banner when generation_ok is false */}
        {data && !generationOk && (
          <div data-testid="know-ladder-gen-failed" style={GEN_FAILED_BANNER_STYLE}>
            generation failed / stale as of {sourceSha}
          </div>
        )}

        <section style={SECTION_STYLE}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={SECTION_TITLE_STYLE}>Fund ladder</div>
            <div style={SHA_STAMP_STYLE}>sha {sourceSha}</div>
          </div>
          {asOf && <StalenessBadge asOf={asOf} maxAge={3600} />}
        </section>

        {phases.map((phase) => (
          <section key={phase.phase} style={SECTION_STYLE}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
              <div style={CARD_LABEL_STYLE}>{phase.name}</div>
              {phase.status === 'complete' && (
                <span
                  style={{
                    fontSize: 10,
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    color: 'var(--arcis-success, #22c55e)',
                    background: 'rgba(34,197,94,0.1)',
                    border: '1px solid rgba(34,197,94,0.3)',
                    borderRadius: 4,
                    padding: '2px 6px',
                  }}
                >
                  complete
                </span>
              )}
              {phase.status === 'active' && (
                <span
                  style={{
                    fontSize: 10,
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    color: 'var(--arcis-accent, #6366f1)',
                    background: 'rgba(99,102,241,0.1)',
                    border: '1px solid rgba(99,102,241,0.3)',
                    borderRadius: 4,
                    padding: '2px 6px',
                  }}
                >
                  active
                </span>
              )}
              <div style={{ fontSize: 11, color: 'var(--arcis-text-muted, #71717a)', fontFamily: 'var(--font-mono)' }}>
                AUM target {phase.aum_target}
              </div>
            </div>

            <PhaseProgressBar progress={phase.progress} status={phase.status} />

            {phase.gates && phase.gates.length > 0 && (
              <div style={CARD_GRID_STYLE}>
                {phase.gates.map((gate) => (
                  <GateCard key={gate.metric_id} gate={gate} />
                ))}
              </div>
            )}
          </section>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SystemMapView — consumes GET /console/know/system-map
// ---------------------------------------------------------------------------
export function SystemMapView() {
  const query = useQuery({
    queryKey: ['console-know-system-map'],
    queryFn: () => fetchApi('/console/know/system-map'),
  })

  const data = query.data
  const generationOk = data?.generation_ok !== false
  const sourceSha = data?.source_sha ?? ''
  const asOf = data?.as_of ?? null
  const capabilities = data?.capabilities ?? {}
  const schema = data?.schema ?? {}
  const byCategory = capabilities.by_category ?? {}
  const tables = Array.isArray(schema.tables) ? schema.tables : []

  return (
    <div>
      <BackToOverview />
      <div data-testid="know-system-map">
        {/* LAW #7: fail-closed banner when generation_ok is false */}
        {data && !generationOk && (
          <div data-testid="know-system-map-gen-failed" style={GEN_FAILED_BANNER_STYLE}>
            generation failed / stale as of {sourceSha}
          </div>
        )}

        <section style={SECTION_STYLE}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={SECTION_TITLE_STYLE}>System map</div>
            <div style={SHA_STAMP_STYLE}>sha {sourceSha}</div>
          </div>
          {asOf && <StalenessBadge asOf={asOf} maxAge={3600} />}
        </section>

        {/* Capabilities section */}
        <section style={SECTION_STYLE}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            <div style={SECTION_TITLE_STYLE}>Capabilities</div>
            <StalenessBadge asOf={capabilities.state === 'unknown' ? null : asOf} maxAge={3600} />
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, marginBottom: 12 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <div style={{ fontSize: 11, textTransform: 'uppercase', color: 'var(--arcis-text-secondary)', fontFamily: 'var(--font-mono)', fontWeight: 500 }}>
                Total
              </div>
              <div style={{ fontSize: 22, fontWeight: 600, fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-primary)', fontVariantNumeric: 'tabular-nums' }}>
                <SentinelGuard value={capabilities.total} />
              </div>
            </div>
          </div>

          <div style={CARD_GRID_STYLE}>
            {Object.entries(byCategory).map(([cat, count]) => (
              <div
                key={cat}
                style={{
                  padding: '8px 12px',
                  border: '1px solid var(--arcis-border)',
                  borderRadius: 6,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 4,
                }}
              >
                <div style={{ fontSize: 11, textTransform: 'uppercase', color: 'var(--arcis-text-secondary)', fontFamily: 'var(--font-mono)', fontWeight: 500 }}>
                  {cat}
                </div>
                <div style={{ fontSize: 20, fontWeight: 600, fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-primary)', fontVariantNumeric: 'tabular-nums' }}>
                  <SentinelGuard value={count} />
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Schema section */}
        <section style={SECTION_STYLE}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            <div style={SECTION_TITLE_STYLE}>Schema</div>
            <StalenessBadge asOf={schema.state === 'unknown' ? null : asOf} maxAge={3600} />
          </div>

          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, textTransform: 'uppercase', color: 'var(--arcis-text-secondary)', fontFamily: 'var(--font-mono)', fontWeight: 500, marginBottom: 4 }}>
              Tables
            </div>
            <div style={{ fontSize: 20, fontWeight: 600, fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-primary)', fontVariantNumeric: 'tabular-nums' }}>
              <SentinelGuard value={schema.table_count} />
            </div>
          </div>

          {tables.length > 0 && (
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
              {tables.map((t) => (
                <li
                  key={t.name}
                  style={{
                    display: 'flex',
                    gap: 16,
                    fontFamily: 'var(--font-mono)',
                    fontSize: 12,
                    color: 'var(--arcis-text-secondary, #a1a1aa)',
                    alignItems: 'center',
                  }}
                >
                  <span style={{ fontWeight: 600, minWidth: 180 }}>{t.name}</span>
                  <span style={{ color: 'var(--arcis-text-muted, #71717a)', fontSize: 11 }}>
                    <SentinelGuard value={t.column_count} /> cols
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Stub components — stubs that are NOT yet implemented (other tasks)
// ---------------------------------------------------------------------------
function DrillStub({ testId, label }) {
  return (
    <div>
      <BackToOverview />
      <div data-testid={testId} style={{ padding: 32, color: 'var(--arcis-text-muted, #71717a)', fontFamily: 'var(--font-mono)', fontSize: 13, textAlign: 'center' }}>
        {label} — coming soon
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TrackRecordView — consumes GET /console/know/track-record
// ---------------------------------------------------------------------------

const HEADLINE_STAT_IDS = [
  'rf_adjusted_sharpe',
  'excess_sharpe_vs_spy',
  'psr',
  'win_rate',
  'profit_factor',
  'max_drawdown',
  'expectancy',
  'closed_trade_count',
]

function EquityCurveChart({ curve }) {
  const data = curve.map((pt) => ({ date: pt.t, equity: pt.equity }))

  return (
    <div data-testid="know-track-record-equity-curve" style={{ width: '100%', height: 220 }}>
      <ResponsiveContainer>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--arcis-border, rgba(255,255,255,0.08))" />
          <XAxis dataKey="date" fontSize={10} tick={{ fill: 'var(--arcis-text-muted, #71717a)' }} />
          <YAxis
            domain={['dataMin', 'dataMax']}
            fontSize={10}
            tick={{ fill: 'var(--arcis-text-muted, #71717a)' }}
            tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
          />
          <RechartsTooltip
            formatter={(v) => `$${Number(v).toLocaleString()}`}
            contentStyle={{ background: 'var(--arcis-surface, #18181b)', border: '1px solid var(--arcis-border)', borderRadius: 6, fontSize: 12 }}
          />
          <Line
            type="monotone"
            dataKey="equity"
            stroke="var(--arcis-accent, #6366f1)"
            dot={false}
            strokeWidth={2}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export function TrackRecordView() {
  const query = useQuery({
    queryKey: ['console-know-track-record'],
    queryFn: () => fetchApi('/console/know/track-record'),
  })

  const data = query.data
  const metrics = data?.metrics ?? {}
  const unavailable = Array.isArray(data?.unavailable) ? data.unavailable : []
  const equityCurve = data?.equity_curve ?? null
  const ctoReportLink = data?.cto_report_link ?? null
  const asOf = data?.as_of ?? null

  return (
    <div>
      <BackToOverview />
      <div data-testid="know-track-record">
        <section style={SECTION_STYLE}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={SECTION_TITLE_STYLE}>Track record</div>
            {asOf && <StalenessBadge asOf={asOf} maxAge={3600} />}
          </div>
          {ctoReportLink && (
            <a
              data-testid="know-track-record-cto-link"
              href={ctoReportLink}
              style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--arcis-accent, #6366f1)', textDecoration: 'none' }}
            >
              Full CTO Report →
            </a>
          )}
        </section>

        {/* Headline stats grid */}
        <section style={SECTION_STYLE}>
          <div style={SECTION_TITLE_STYLE}>Headline stats</div>
          <div style={CARD_GRID_STYLE}>
            {HEADLINE_STAT_IDS.map((id) => {
              const m = metrics[id]
              if (!m) return null
              const { value, n, as_of, cohort, unit, state } = m

              // no_data or unknown state — honest no-data treatment, not 0
              if (state === 'no_data' || state === 'unknown') {
                return (
                  <Metric
                    key={id}
                    label={id}
                    value={<SentinelGuard value={null} />}
                    cohort={cohort}
                    n={n}
                    asOf={as_of}
                  />
                )
              }

              return (
                <Metric
                  key={id}
                  label={id}
                  value={<SentinelGuard value={value} />}
                  cohort={cohort}
                  n={n}
                  asOf={as_of}
                />
              )
            })}
          </div>
        </section>

        {/* Unavailable metrics — explicit not-available treatment */}
        {unavailable.length > 0 && (
          <section style={SECTION_STYLE}>
            <div style={SECTION_TITLE_STYLE}>Not available</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {unavailable.map((id) => (
                <div
                  key={id}
                  data-testid={`know-track-record-unavailable-${id}`}
                  style={{
                    padding: '4px 12px',
                    border: '1px dashed var(--arcis-text-muted, #71717a)',
                    borderRadius: 4,
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    color: 'var(--arcis-text-muted, #71717a)',
                  }}
                >
                  {id}: not available
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Equity curve */}
        <section style={SECTION_STYLE}>
          <div style={SECTION_TITLE_STYLE}>Equity curve</div>
          {equityCurve === null ? (
            <div data-testid="know-track-record-no-curve" style={{ color: 'var(--arcis-text-muted, #71717a)', fontFamily: 'var(--font-mono)', fontSize: 12, padding: '12px 0' }}>
              Equity curve not available
            </div>
          ) : (
            <EquityCurveChart curve={equityCurve} />
          )}
        </section>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TradeLedgersView — consumes GET /console/know/ledgers
// ---------------------------------------------------------------------------

const LEDGER_TABS = [
  { key: 'open', label: 'Open' },
  { key: 'closed', label: 'Closed' },
  { key: 'all', label: 'History' },
]

function LedgerRow({ trade }) {
  const ticker = trade.ticker ?? '--'
  const pnlDollars = trade.pnl_dollars
  const pnlPct = trade.pnl_pct

  return (
    <tr style={{ borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))' }}>
      <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--arcis-text-primary, #fff)', fontWeight: 600 }}>
        {ticker}
      </td>
      <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)', fontSize: 13 }}>
        <SentinelGuard value={pnlDollars} />
      </td>
      <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)', fontSize: 13 }}>
        <SentinelGuard value={pnlPct} />
      </td>
    </tr>
  )
}

export function TradeLedgersView() {
  const [activeTab, setActiveTab] = useState('open')
  const [search, setSearch] = useState('')

  const query = useQuery({
    queryKey: ['console-know-ledgers', activeTab, search],
    queryFn: () => {
      const params = new URLSearchParams({ status: activeTab, limit: '50' })
      if (search) params.set('q', search)
      return fetchApi(`/console/know/ledgers?${params}`)
    },
  })

  const data = query.data
  const rows = Array.isArray(data?.rows) ? data.rows : []
  const asOf = data?.as_of ?? null
  const state = data?.state ?? null

  return (
    <div>
      <BackToOverview />
      <div data-testid="know-ledgers">
        <section style={SECTION_STYLE}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={SECTION_TITLE_STYLE}>Trade ledgers</div>
            <StalenessBadge asOf={asOf} maxAge={3600} />
          </div>

          {/* Tab bar */}
          <div style={{ display: 'flex', gap: 2, marginBottom: 12, borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))' }}>
            {LEDGER_TABS.map((tab) => (
              <button
                key={tab.key}
                data-testid={`know-ledgers-tab-${tab.key}`}
                onClick={() => setActiveTab(tab.key)}
                style={{
                  padding: '6px 16px',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                  background: 'transparent',
                  border: 'none',
                  borderBottom: activeTab === tab.key ? '2px solid var(--arcis-accent, #6366f1)' : '2px solid transparent',
                  color: activeTab === tab.key ? 'var(--arcis-text-primary, #fff)' : 'var(--arcis-text-muted, #71717a)',
                  cursor: 'pointer',
                }}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Search box */}
          <div style={{ marginBottom: 12 }}>
            <input
              data-testid="know-ledgers-search"
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search ticker..."
              style={{
                padding: '6px 12px',
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                background: 'var(--arcis-surface, #18181b)',
                border: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
                borderRadius: 4,
                color: 'var(--arcis-text-primary, #fff)',
                outline: 'none',
                width: 220,
              }}
            />
          </div>
        </section>

        {/* Table or no-data */}
        <section style={SECTION_STYLE}>
          {state === 'no_data' || state === 'unknown' ? (
            <div
              data-testid="know-ledgers-no-data"
              style={{ color: 'var(--arcis-text-muted, #71717a)', fontFamily: 'var(--font-mono)', fontSize: 12, padding: '16px 0' }}
            >
              No trade data available
            </div>
          ) : rows.length === 0 && data ? (
            <div
              data-testid="know-ledgers-no-data"
              style={{ color: 'var(--arcis-text-muted, #71717a)', fontFamily: 'var(--font-mono)', fontSize: 12, padding: '16px 0' }}
            >
              No trades
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', tableLayout: 'auto', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))' }}>
                    <th style={{ padding: '6px 12px', textAlign: 'left', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--arcis-text-muted, #71717a)', fontFamily: 'var(--font-mono)' }}>Ticker</th>
                    <th style={{ padding: '6px 12px', textAlign: 'left', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--arcis-text-muted, #71717a)', fontFamily: 'var(--font-mono)' }}>P&L $</th>
                    <th style={{ padding: '6px 12px', textAlign: 'left', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--arcis-text-muted, #71717a)', fontFamily: 'var(--font-mono)' }}>P&L %</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <LedgerRow key={row.trade_id ?? i} trade={row} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

export function ResearchStub() {
  return <DrillStub testId="know-research" label="Research & calibration" />
}

export function ScorecardsStub() {
  return <DrillStub testId="know-scorecards" label="AI dev-team scorecards" />
}
