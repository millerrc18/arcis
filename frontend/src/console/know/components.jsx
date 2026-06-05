/**
 * KNOW region sub-components (P3-T4, design §3.3).
 * Overview synthesis cards + drill-down views.
 * Each view carries its own data-testid for shell-test compatibility.
 */
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { fetchApi } from '../../api'
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

export function TrackRecordStub() {
  return <DrillStub testId="know-track-record" label="Track record" />
}

export function LedgersStub() {
  return <DrillStub testId="know-ledgers" label="Trade ledgers" />
}

export function RigorStub() {
  return <DrillStub testId="know-rigor" label="Rigor stack" />
}

export function AttributionStub() {
  return <DrillStub testId="know-attribution" label="Attribution" />
}

export function ResearchStub() {
  return <DrillStub testId="know-research" label="Research & calibration" />
}

export function ScorecardsStub() {
  return <DrillStub testId="know-scorecards" label="AI dev-team scorecards" />
}
