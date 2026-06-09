/**
 * ScorecardsView — AI dev-team scorecards drill-down (P3-T11 + F6).
 *
 * Consumes existing endpoints (no new backend):
 *   GET /api/model-performance  — training.py:553-617
 *   GET /api/activity/feed      — council.py:94-117
 *   GET /api/training/versions  — training.py:231-239
 *
 * F6 NEW:
 *   GET /console/know/scorecards (BARE path — fetchApi prepends /api)
 *   Shape: { per_role, per_task_type, scope_drift, n, state, as_of }
 *
 * HONEST INSTRUMENTATION:
 *   REAL dimensions: per-model win-rate/profit-factor/sharpe/trades, training
 *     version history, activity event types (pr_merged, deploy, regression),
 *     per-role success/rework/escalation/scope-drift from scorecards endpoint.
 *   HONEST no-data: when state=no_data or per_role is empty, renders an
 *     explicit forward-looking copy rather than fabricated zeros.
 */
import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../../api'
import { BackToOverview } from './components'
import StalenessBadge from '../components/StalenessBadge'
import SentinelGuard from '../components/SentinelGuard'

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
  gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
  gap: 10,
}

const CARD_STYLE = {
  padding: '10px 14px',
  border: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
  borderRadius: 6,
  background: 'var(--arcis-surface, #18181b)',
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
}

const CARD_LABEL_STYLE = {
  fontSize: 10,
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  color: 'var(--arcis-text-muted, #71717a)',
  fontFamily: 'var(--font-mono)',
  fontWeight: 500,
}

const CARD_VALUE_STYLE = {
  fontSize: 18,
  fontWeight: 600,
  fontFamily: 'var(--font-mono)',
  color: 'var(--arcis-text-primary, #fff)',
  fontVariantNumeric: 'tabular-nums',
}

const VERSION_ROW_STYLE = {
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  padding: '8px 0',
  borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
}

const ACTIVITY_ROW_STYLE = {
  display: 'flex',
  alignItems: 'flex-start',
  gap: 12,
  padding: '6px 0',
  borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
  color: 'var(--arcis-text-secondary, #a1a1aa)',
}

const NI_BADGE_STYLE = {
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

const NO_DATA_STYLE = {
  color: 'var(--arcis-text-muted, #71717a)',
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
  padding: '12px 0',
}

// ---------------------------------------------------------------------------
// Helper: pct formatter
// ---------------------------------------------------------------------------
function fmtPct(v) {
  if (v == null) return null
  return (v * 100).toFixed(1) + '%'
}

function fmtFixed(v, d = 2) {
  if (v == null) return null
  return Number(v).toFixed(d)
}

// ---------------------------------------------------------------------------
// Model version row
// ---------------------------------------------------------------------------
function VersionRow({ model }) {
  const { version, meta = {}, live_metrics: lm = {} } = model
  const isActive = meta.status === 'active'

  return (
    <div style={VERSION_ROW_STYLE}>
      <span style={{ fontWeight: 700, color: isActive ? 'var(--arcis-accent, #6366f1)' : 'var(--arcis-text-primary, #fff)', minWidth: 110 }}>
        {version}
      </span>
      {isActive && (
        <span style={{ fontSize: 9, textTransform: 'uppercase', fontWeight: 700, color: 'var(--arcis-accent, #6366f1)', background: 'rgba(99,102,241,0.1)', border: '1px solid rgba(99,102,241,0.3)', borderRadius: 3, padding: '1px 5px' }}>
          active
        </span>
      )}
      <span style={{ color: 'var(--arcis-text-muted, #71717a)' }}>{meta.created_at || ''}</span>
      <span>t={meta.training_examples ?? 0}</span>
      <span>holdout <SentinelGuard value={meta.holdout_score != null ? Number(fmtFixed(meta.holdout_score)) : null} /></span>
      <span>trades {lm.trades ?? 0}</span>
      <span>wr <SentinelGuard value={fmtPct(lm.win_rate)} /></span>
      <span>pf <SentinelGuard value={fmtFixed(lm.profit_factor)} /></span>
      <span>sharpe <SentinelGuard value={fmtFixed(lm.sharpe_ratio)} /></span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Activity row
// ---------------------------------------------------------------------------
function ActivityRow({ entry }) {
  const ts = entry.created_at ? entry.created_at.slice(0, 16).replace('T', ' ') : '—'
  return (
    <div style={ACTIVITY_ROW_STYLE}>
      <span style={{ color: 'var(--arcis-text-muted, #71717a)', minWidth: 120 }}>{ts}</span>
      <span style={{ minWidth: 90, color: 'var(--arcis-text-secondary, #a1a1aa)' }}>{entry.event_type || '—'}</span>
      <span style={{ flex: 1 }}>{entry.detail || ''}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ScorecardsView — main component
// ---------------------------------------------------------------------------
export default function ScorecardsView() {
  const modelPerfQuery = useQuery({
    queryKey: ['scorecards-model-performance'],
    queryFn: () => fetchApi('/model-performance'),
  })

  const activityQuery = useQuery({
    queryKey: ['scorecards-activity-feed'],
    queryFn: () => fetchApi('/activity/feed?limit=30'),
  })

  const versionsQuery = useQuery({
    queryKey: ['scorecards-training-versions'],
    queryFn: () => fetchApi('/training/versions'),
  })

  const scorecardsQuery = useQuery({
    queryKey: ['scorecards'],
    queryFn: () => fetchApi('/console/know/scorecards'),
  })

  const mp = modelPerfQuery.data
  const models = Array.isArray(mp?.models) ? mp.models : []
  const overall = mp?.overall ?? {}
  const totalTrades = mp?.total_closed_trades ?? 0
  const mpAsOf = modelPerfQuery.dataUpdatedAt ? new Date(modelPerfQuery.dataUpdatedAt).toISOString() : null

  const activityRows = Array.isArray(activityQuery.data) ? activityQuery.data : []
  const actAsOf = activityQuery.dataUpdatedAt ? new Date(activityQuery.dataUpdatedAt).toISOString() : null

  const versions = versionsQuery.data?.versions ?? []

  // Active model for headline metrics
  const activeModel = models.find((m) => m.meta?.status === 'active') || models[0] || null
  const alm = activeModel?.live_metrics ?? {}

  // F6: per-role / scope-drift scorecards
  const scData = scorecardsQuery.data
  const scState = scData?.state ?? null
  const perRole = scData?.per_role ?? null
  const perTaskType = scData?.per_task_type ?? null
  const scopeDrift = scData?.scope_drift ?? null
  const scAsOf = scData?.as_of ?? null
  const hasPerRoleData = perRole != null && Object.keys(perRole).length > 0
  const scIsSettled = scorecardsQuery.status !== 'pending'
  const showNoData = scIsSettled && (scState === 'no_data' || !hasPerRoleData)

  return (
    <div>
      <BackToOverview />
      <div data-testid="know-scorecards">

        {/* ── Section: Headline — Overall Model Performance ── */}
        <section style={SECTION_STYLE}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={SECTION_TITLE_STYLE}>AI dev-team scorecards</div>
            <StalenessBadge asOf={mpAsOf} maxAge={300} />
          </div>

          <div style={{ ...CARD_GRID_STYLE, marginBottom: 16 }}>
            <div style={CARD_STYLE}>
              <div style={CARD_LABEL_STYLE}>Total closed trades</div>
              <div style={CARD_VALUE_STYLE}><SentinelGuard value={totalTrades > 0 ? totalTrades : null} /></div>
            </div>
            <div style={CARD_STYLE}>
              <div style={CARD_LABEL_STYLE}>Overall win rate</div>
              <div style={CARD_VALUE_STYLE}><SentinelGuard value={fmtPct(overall.win_rate)} /></div>
            </div>
            <div style={CARD_STYLE}>
              <div style={CARD_LABEL_STYLE}>Overall profit factor</div>
              <div style={CARD_VALUE_STYLE}><SentinelGuard value={fmtFixed(overall.profit_factor)} /></div>
            </div>
            <div style={CARD_STYLE}>
              <div style={CARD_LABEL_STYLE}>Overall sharpe</div>
              <div style={CARD_VALUE_STYLE}><SentinelGuard value={fmtFixed(overall.sharpe_ratio)} /></div>
            </div>
          </div>
        </section>

        {/* ── Section: Per-version model metrics (REAL) ── */}
        <section style={SECTION_STYLE}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={SECTION_TITLE_STYLE}>Per-model-version performance</div>
            <span style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-muted, #71717a)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>real · /api/model-performance</span>
          </div>

          {models.length === 0 && modelPerfQuery.isFetched ? (
            <div data-testid="scorecards-model-no-data" style={NO_DATA_STYLE}>
              No model versions available
            </div>
          ) : (
            <div>
              {models.map((m) => (
                <VersionRow key={m.version} model={m} />
              ))}
            </div>
          )}
        </section>

        {/* ── Section: Training version history (REAL) ── */}
        {versions.length > 0 && (
          <section style={SECTION_STYLE}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <div style={SECTION_TITLE_STYLE}>Training version history</div>
              <span style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-muted, #71717a)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>real · /api/training/versions</span>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))' }}>
                    {['Version', 'Created', 'Examples', 'Holdout', 'Status'].map((h) => (
                      <th key={h} style={{ textAlign: 'left', padding: '4px 10px', fontSize: 10, textTransform: 'uppercase', color: 'var(--arcis-text-muted, #71717a)', fontWeight: 600 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {versions.map((v) => (
                    <tr key={v.version_id} style={{ borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))' }}>
                      <td style={{ padding: '6px 10px', color: 'var(--arcis-text-primary, #fff)', fontWeight: 600 }}>{v.version_name}</td>
                      <td style={{ padding: '6px 10px', color: 'var(--arcis-text-secondary, #a1a1aa)' }}>{(v.created_at || '').slice(0, 10)}</td>
                      <td style={{ padding: '6px 10px' }}><SentinelGuard value={v.training_examples_count} /></td>
                      <td style={{ padding: '6px 10px' }}><SentinelGuard value={v.holdout_score != null ? fmtFixed(v.holdout_score) : null} /></td>
                      <td style={{ padding: '6px 10px', color: v.status === 'active' ? 'var(--arcis-accent, #6366f1)' : 'var(--arcis-text-muted, #71717a)' }}>{v.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* ── Section: Activity feed — task-type trends (REAL event types) ── */}
        <section style={SECTION_STYLE}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={SECTION_TITLE_STYLE}>Activity log — recent events</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-muted, #71717a)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>real · /api/activity/feed</span>
              <StalenessBadge asOf={actAsOf} maxAge={300} />
            </div>
          </div>

          {activityRows.length === 0 && activityQuery.isFetched ? (
            <div data-testid="scorecards-activity-no-data" style={NO_DATA_STYLE}>
              No activity log entries
            </div>
          ) : (
            <div>
              {activityRows.slice(0, 20).map((entry, i) => (
                <ActivityRow key={entry.id ?? i} entry={entry} />
              ))}
            </div>
          )}
        </section>

        {/* ── Section: Per-role + scope-drift scorecards (F6 REAL) ── */}
        <section style={SECTION_STYLE}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={SECTION_TITLE_STYLE}>Per-role scorecards (Planner / Developer / Reviewer)</div>
            {scAsOf && <StalenessBadge asOf={scAsOf} maxAge={3600} />}
          </div>

          {showNoData ? (
            <div
              data-testid="scorecards-per-role-no-data"
              style={NO_DATA_STYLE}
            >
              no instrumented runs yet — per-role scorecards populate once coding-team runs record outcomes
            </div>
          ) : (
            <div data-testid="scorecards-per-role-real">
              {/* Per-role table */}
              {perRole && Object.keys(perRole).length > 0 && (
                <div style={{ overflowX: 'auto', marginBottom: 16 }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))' }}>
                        {['Role', 'n', 'Success', 'Rework', 'Escalation', 'Scope violations', 'Avg review cycles'].map((h) => (
                          <th key={h} style={{ textAlign: 'left', padding: '4px 10px', fontSize: 10, textTransform: 'uppercase', color: 'var(--arcis-text-muted, #71717a)', fontWeight: 600 }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(perRole).map(([role, m]) => (
                        <tr key={role} style={{ borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))' }}>
                          <td style={{ padding: '6px 10px', color: 'var(--arcis-text-primary, #fff)', fontWeight: 600 }}>{role}</td>
                          <td style={{ padding: '6px 10px' }}><SentinelGuard value={m.n} /></td>
                          <td style={{ padding: '6px 10px' }}><SentinelGuard value={fmtPct(m.success_rate)} /></td>
                          <td style={{ padding: '6px 10px' }}><SentinelGuard value={fmtPct(m.rework_rate)} /></td>
                          <td style={{ padding: '6px 10px' }}><SentinelGuard value={fmtPct(m.escalation_rate)} /></td>
                          <td style={{ padding: '6px 10px' }}><SentinelGuard value={m.scope_violations} /></td>
                          <td style={{ padding: '6px 10px' }}><SentinelGuard value={fmtFixed(m.avg_review_cycles)} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Per-task-type table */}
              {perTaskType && Object.keys(perTaskType).length > 0 && (
                <div style={{ overflowX: 'auto', marginBottom: 16 }}>
                  <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--arcis-text-muted, #71717a)', fontFamily: 'var(--font-mono)', fontWeight: 600, marginBottom: 6 }}>By task type</div>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))' }}>
                        {['Type', 'n', 'Success', 'Rework', 'Escalation', 'Scope violations', 'Avg review cycles'].map((h) => (
                          <th key={h} style={{ textAlign: 'left', padding: '4px 10px', fontSize: 10, textTransform: 'uppercase', color: 'var(--arcis-text-muted, #71717a)', fontWeight: 600 }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(perTaskType).map(([type, m]) => (
                        <tr key={type} style={{ borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))' }}>
                          <td style={{ padding: '6px 10px', color: 'var(--arcis-text-primary, #fff)', fontWeight: 600 }}>{type}</td>
                          <td style={{ padding: '6px 10px' }}><SentinelGuard value={m.n} /></td>
                          <td style={{ padding: '6px 10px' }}><SentinelGuard value={fmtPct(m.success_rate)} /></td>
                          <td style={{ padding: '6px 10px' }}><SentinelGuard value={fmtPct(m.rework_rate)} /></td>
                          <td style={{ padding: '6px 10px' }}><SentinelGuard value={fmtPct(m.escalation_rate)} /></td>
                          <td style={{ padding: '6px 10px' }}><SentinelGuard value={m.scope_violations} /></td>
                          <td style={{ padding: '6px 10px' }}><SentinelGuard value={fmtFixed(m.avg_review_cycles)} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Scope drift summary */}
              {scopeDrift != null && (
                <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                  <div style={CARD_STYLE}>
                    <div style={CARD_LABEL_STYLE}>Total scope violations</div>
                    <div style={CARD_VALUE_STYLE}><SentinelGuard value={scopeDrift.total_scope_violations} /></div>
                  </div>
                  <div style={CARD_STYLE}>
                    <div style={CARD_LABEL_STYLE}>Tasks tracked</div>
                    <div style={CARD_VALUE_STYLE}><SentinelGuard value={scopeDrift.n} /></div>
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

      </div>
    </div>
  )
}
