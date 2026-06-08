/**
 * RigorStack — Rigor drill-down for the KNOW region (P3-T8).
 * Three sub-views: Validation, Walkforward, Stress Test.
 * Consumes existing backend routes verbatim (no new routes added).
 *
 * Routes consumed:
 *   GET /api/walkforward/runs          (walkforward.py:63-93)
 *   GET /api/walkforward/runs/{id}/windows (walkforward.py:108-137)
 *   GET /api/stress-test/results       (analytics.py:921-943)
 *   GET /api/system/validation         (via api.js: fetchApi('/system/validation'))
 *
 * Render laws:
 *   Every metric goes through Metric (requires cohort/n/asOf) + SentinelGuard.
 *   Honest no-data states (no fabrication).
 *   StalenessBadge on every panel.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../../api'
import Metric from '../components/Metric'
import SentinelGuard from '../components/SentinelGuard'
import StalenessBadge from '../components/StalenessBadge'
import { BackToOverview } from './components'

// ---------------------------------------------------------------------------
// Shared styles
// ---------------------------------------------------------------------------
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
  gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
  gap: 12,
}

const NO_DATA_STYLE = {
  color: 'var(--arcis-text-muted, #71717a)',
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
  padding: '16px 0',
}

const OUTCOME_STYLES = {
  PASS: {
    background: 'rgba(34,197,94,0.12)',
    color: 'var(--arcis-success, #22c55e)',
    border: '1px solid rgba(34,197,94,0.3)',
  },
  FAIL: {
    background: 'rgba(239,68,68,0.12)',
    color: 'var(--arcis-danger, #ef4444)',
    border: '1px solid rgba(239,68,68,0.3)',
  },
  INCONCLUSIVE: {
    background: 'rgba(245,158,11,0.12)',
    color: 'var(--arcis-warning, #f59e0b)',
    border: '1px solid rgba(245,158,11,0.3)',
  },
}

const SCENARIO_LABELS = {
  '2008_financial_crisis': '2008 Financial Crisis',
  '2020_covid_crash': '2020 COVID Crash',
  '2022_bear_market': '2022 Bear Market',
  '2018_q4_selloff': '2018 Q4 Selloff',
  '2011_debt_ceiling': '2011 Debt Ceiling',
  '2015_china_deval': '2015 China Deval',
  '2024_yen_unwind': '2024 Yen Unwind',
}

function numberOrDash(v, digits = 3) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(digits)
}

function OutcomeBadge({ state }) {
  const s = OUTCOME_STYLES[state] ?? {
    background: 'var(--arcis-surface, #18181b)',
    color: 'var(--arcis-text-secondary, #a1a1aa)',
    border: '1px solid var(--arcis-border)',
  }
  return (
    <span
      style={{
        ...s,
        display: 'inline-flex',
        alignItems: 'center',
        padding: '2px 8px',
        borderRadius: 4,
        fontSize: 10,
        fontWeight: 700,
        fontFamily: 'var(--font-mono)',
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
      }}
    >
      {state ?? '—'}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Tab bar
// ---------------------------------------------------------------------------
const TABS = [
  { key: 'validation', label: 'Validation', testId: 'rigor-tab-validation' },
  { key: 'walkforward', label: 'Walkforward', testId: 'rigor-tab-walkforward' },
  { key: 'stress', label: 'Stress Test', testId: 'rigor-tab-stress' },
]

// ---------------------------------------------------------------------------
// ValidationPanel — consumes GET /api/system/validation
// Shape (from Validation.jsx + api.js:170):
//   { overall_status, checks_passed, checks_warning, checks_failed,
//     checks_total, timestamp, categories: { [name]: [{status,name,detail}] } }
// ---------------------------------------------------------------------------
function ValidationPanel() {
  const query = useQuery({
    queryKey: ['rigor-validation'],
    queryFn: () => fetchApi('/system/validation'),
  })

  const data = query.data
  const overall = data?.overall_status ?? null
  const passed = data?.checks_passed ?? null
  const warning = data?.checks_warning ?? null
  const failed = data?.checks_failed ?? null
  const total = data?.checks_total ?? null
  const timestamp = data?.timestamp ?? null
  const isSettled = query.status !== 'pending'
  const hasData = overall != null || (total != null && total > 0)

  return (
    <div data-testid="rigor-validation-panel">
      <section style={SECTION_STYLE}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <div style={SECTION_TITLE_STYLE}>System Validation (PSR / DSR / PBO)</div>
          <StalenessBadge asOf={timestamp} maxAge={3600} />
        </div>

        {!hasData && isSettled ? (
          <div data-testid="rigor-validation-no-data" style={NO_DATA_STYLE}>
            No validation data available
          </div>
        ) : (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 16 }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 700, textTransform: 'uppercase', color: 'var(--arcis-text-primary, #fff)' }}>
                <SentinelGuard value={overall} />
              </div>
            </div>

            <div style={CARD_GRID_STYLE}>
              <Metric
                label="Passed"
                value={<SentinelGuard value={passed} />}
                cohort="system"
                n={total ?? 0}
                asOf={timestamp ?? 'unknown'}
              />
              <Metric
                label="Warnings"
                value={<SentinelGuard value={warning} />}
                cohort="system"
                n={total ?? 0}
                asOf={timestamp ?? 'unknown'}
              />
              <Metric
                label="Failed"
                value={<SentinelGuard value={failed} />}
                cohort="system"
                n={total ?? 0}
                asOf={timestamp ?? 'unknown'}
              />
              <Metric
                label="Total checks"
                value={<SentinelGuard value={total} />}
                cohort="system"
                n={total ?? 0}
                asOf={timestamp ?? 'unknown'}
              />
            </div>
          </>
        )}
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// WalkforwardPanel — consumes /walkforward/runs + /windows
// Runs shape (walkforward.py:63-93):
//   { runs: [{run_id, strategy_id, outcome_state, reason, pooled_sharpe,
//             pooled_mde, heavy_tail_flag, n_windows, n_windows_pass,
//             n_windows_fail, n_windows_inconclusive_data,
//             n_windows_inconclusive_power, created_at, ...}], count }
// Windows shape (walkforward.py:108-137):
//   { run_id, outcome_state, windows: [{window_index, n_trades, sharpe, mde,
//             bootstrap_se, distinct_vix_tiers}], count }
// ---------------------------------------------------------------------------
function WalkforwardPanel() {
  const runsQuery = useQuery({
    queryKey: ['rigor-wf-runs'],
    queryFn: () => fetchApi('/walkforward/runs'),
  })

  const runs = Array.isArray(runsQuery.data?.runs) ? runsQuery.data.runs : []
  const latestRun = runs[0] ?? null
  const latestRunId = latestRun?.run_id ?? null
  const runsAsOf = latestRun?.created_at ?? null

  const windowsQuery = useQuery({
    queryKey: ['rigor-wf-windows', latestRunId],
    queryFn: () => fetchApi(`/walkforward/runs/${latestRunId}/windows`),
    enabled: latestRunId != null,
  })

  const windows = Array.isArray(windowsQuery.data?.windows) ? windowsQuery.data.windows : []
  const hasRuns = runs.length > 0

  return (
    <div data-testid="rigor-walkforward-panel">
      <section style={SECTION_STYLE}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <div style={SECTION_TITLE_STYLE}>Walk-forward Validation (OOS Windows)</div>
          <StalenessBadge asOf={runsAsOf} maxAge={3600} />
        </div>

        {!hasRuns && runsQuery.status !== 'pending' ? (
          <div data-testid="rigor-walkforward-no-data" style={NO_DATA_STYLE}>
            No walk-forward runs recorded yet. Run{' '}
            <code style={{ background: 'var(--arcis-surface, #18181b)', padding: '1px 4px' }}>
              python -m scripts.backtest.run_walkforward --strategy &lt;id&gt;
            </code>{' '}
            to generate the first result.
          </div>
        ) : latestRun ? (
          <>
            {/* Latest run summary */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
              <OutcomeBadge state={latestRun.outcome_state} />
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--arcis-text-secondary, #a1a1aa)' }}>
                {latestRun.strategy_id}
              </span>
              {latestRun.reason && (
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--arcis-text-muted, #71717a)' }}>
                  {latestRun.reason}
                </span>
              )}
            </div>

            <div style={{ ...CARD_GRID_STYLE, marginBottom: 16 }}>
              <Metric
                label="Pooled Sharpe"
                value={<SentinelGuard value={latestRun.pooled_sharpe != null ? Number(latestRun.pooled_sharpe).toFixed(3) : null} />}
                cohort="walkforward"
                n={latestRun.n_windows ?? 0}
                asOf={latestRun.created_at ?? 'unknown'}
              />
              <Metric
                label="Pooled MDE"
                value={<SentinelGuard value={latestRun.pooled_mde != null ? Number(latestRun.pooled_mde).toFixed(3) : null} />}
                cohort="walkforward"
                n={latestRun.n_windows ?? 0}
                asOf={latestRun.created_at ?? 'unknown'}
              />
              <Metric
                label="Windows (P/F/I)"
                value={
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>
                    {latestRun.n_windows_pass ?? 0}/{latestRun.n_windows_fail ?? 0}/{(latestRun.n_windows_inconclusive_data ?? 0) + (latestRun.n_windows_inconclusive_power ?? 0)}
                  </span>
                }
                cohort="walkforward"
                n={latestRun.n_windows ?? 0}
                asOf={latestRun.created_at ?? 'unknown'}
              />
              <Metric
                label="Max Drawdown"
                value={<SentinelGuard value={latestRun.max_drawdown_pct != null ? `${Number(latestRun.max_drawdown_pct).toFixed(1)}%` : null} />}
                cohort="walkforward"
                n={latestRun.n_windows ?? 0}
                asOf={latestRun.created_at ?? 'unknown'}
              />
            </div>

            {/* Per-window breakdown */}
            {windows.length > 0 && (
              <div>
                <div style={{ ...SECTION_TITLE_STYLE, marginBottom: 8 }}>Per-window breakdown</div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))' }}>
                        {['Window', 'Trades', 'Sharpe', 'MDE', 'Bootstrap SE', 'VIX tiers'].map((h) => (
                          <th key={h} style={{ padding: '4px 8px', textAlign: h === 'Window' ? 'left' : 'right', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--arcis-text-muted, #71717a)', fontWeight: 600 }}>
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {windows.map((w) => (
                        <tr key={w.window_index} style={{ borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))' }}>
                          <td style={{ padding: '6px 8px', color: 'var(--arcis-text-primary, #fff)' }}>{w.window_index}</td>
                          <td style={{ padding: '6px 8px', textAlign: 'right' }}>{w.n_trades}</td>
                          <td style={{ padding: '6px 8px', textAlign: 'right' }}>{numberOrDash(w.sharpe)}</td>
                          <td style={{ padding: '6px 8px', textAlign: 'right' }}>{numberOrDash(w.mde)}</td>
                          <td style={{ padding: '6px 8px', textAlign: 'right' }}>{numberOrDash(w.bootstrap_se)}</td>
                          <td style={{ padding: '6px 8px', textAlign: 'right' }}>{w.distinct_vix_tiers}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        ) : null}
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// StressPanel — consumes GET /api/stress-test/results
// Shape (analytics.py:921-943):
//   { results: [{result_id, scenario, start_date, end_date, total_trades,
//               win_rate, max_drawdown_pct, calmar_ratio,
//               monthly_returns_json, regime_breakdown_json,
//               equity_curve_json, created_at}], _meta }
// ---------------------------------------------------------------------------
function StressPanel() {
  const query = useQuery({
    queryKey: ['rigor-stress-results'],
    queryFn: () => fetchApi('/stress-test/results'),
  })

  const allResults = Array.isArray(query.data?.results) ? query.data.results : []
  const asOf = allResults[0]?.created_at ?? null

  // Deduplicate: latest per scenario
  const latestByScenario = new Map()
  for (const r of allResults) {
    const key = r.scenario ?? 'unknown'
    const existing = latestByScenario.get(key)
    if (!existing || (r.created_at ?? '') > (existing.created_at ?? '')) {
      latestByScenario.set(key, r)
    }
  }
  const results = Array.from(latestByScenario.values())
  const hasResults = results.length > 0

  return (
    <div data-testid="rigor-stress-panel">
      <section style={SECTION_STYLE}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <div style={SECTION_TITLE_STYLE}>Historical Stress Testing</div>
          <StalenessBadge asOf={asOf} maxAge={3600} />
        </div>

        {!hasResults && query.status !== 'pending' ? (
          <div data-testid="rigor-stress-no-data" style={NO_DATA_STYLE}>
            No stress test results yet. Run{' '}
            <code style={{ background: 'var(--arcis-surface, #18181b)', padding: '1px 4px' }}>
              python -m scripts.backtest.run_stress_test
            </code>{' '}
            to generate the first result.
          </div>
        ) : (
          <div style={CARD_GRID_STYLE}>
            {results.map((r) => (
              <div
                key={r.result_id}
                style={{
                  padding: '14px 16px',
                  border: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
                  borderRadius: 6,
                  background: 'var(--arcis-surface, #18181b)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                }}
              >
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 600, color: 'var(--arcis-text-primary, #fff)' }}>
                  {SCENARIO_LABELS[r.scenario] ?? r.scenario}
                </div>
                <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-muted, #71717a)' }}>
                  {r.start_date} — {r.end_date}
                </div>
                <div style={CARD_GRID_STYLE}>
                  <div>
                    <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--arcis-text-secondary, #a1a1aa)', fontFamily: 'var(--font-mono)', marginBottom: 2 }}>
                      Trades
                    </div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', fontSize: 13 }}>
                      <SentinelGuard value={r.total_trades ?? null} />
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--arcis-text-secondary, #a1a1aa)', fontFamily: 'var(--font-mono)', marginBottom: 2 }}>
                      Win Rate
                    </div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', fontSize: 13 }}>
                      {r.win_rate != null ? `${(r.win_rate * 100).toFixed(1)}%` : <span style={{ color: 'var(--arcis-text-muted, #71717a)', fontStyle: 'italic' }}>no data</span>}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--arcis-text-secondary, #a1a1aa)', fontFamily: 'var(--font-mono)', marginBottom: 2 }}>
                      Max DD
                    </div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', fontSize: 13, color: 'var(--arcis-danger, #ef4444)' }}>
                      {r.max_drawdown_pct != null ? `${r.max_drawdown_pct.toFixed(1)}%` : <span style={{ color: 'var(--arcis-text-muted, #71717a)', fontStyle: 'italic' }}>no data</span>}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--arcis-text-secondary, #a1a1aa)', fontFamily: 'var(--font-mono)', marginBottom: 2 }}>
                      Calmar
                    </div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', fontSize: 13 }}>
                      {r.calmar_ratio != null ? r.calmar_ratio.toFixed(2) : <span style={{ color: 'var(--arcis-text-muted, #71717a)', fontStyle: 'italic' }}>no data</span>}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// RigorStack — root
// ---------------------------------------------------------------------------
export default function RigorStack() {
  const [activeTab, setActiveTab] = useState('validation')

  return (
    <div data-testid="know-rigor">
      <BackToOverview />

      {/* Tab bar */}
      <div
        style={{
          display: 'flex',
          gap: 2,
          padding: '0 24px',
          borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
        }}
      >
        {TABS.map((tab) => (
          <button
            key={tab.key}
            data-testid={tab.testId}
            onClick={() => setActiveTab(tab.key)}
            style={{
              padding: '8px 16px',
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

      {/* Sub-view panels */}
      {activeTab === 'validation' && <ValidationPanel />}
      {activeTab === 'walkforward' && <WalkforwardPanel />}
      {activeTab === 'stress' && <StressPanel />}
    </div>
  )
}
