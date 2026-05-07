import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import { XAxis, YAxis, Tooltip, ResponsiveContainer, LineChart, Line } from 'recharts'
import { ChevronDown, ChevronRight } from 'lucide-react'

const SCENARIO_LABELS = {
  '2008_financial_crisis': '2008 Financial Crisis',
  '2020_covid_crash': '2020 COVID Crash',
  '2022_bear_market': '2022 Bear Market',
  // DB-3 Task 8 additions
  '2018_q4_selloff': '2018 Q4 Selloff',
  '2011_debt_ceiling': '2011 Debt Ceiling',
  '2015_china_deval': '2015 China Deval',
  '2024_yen_unwind': '2024 Yen Unwind',
}

const SCENARIO_COLORS = {
  '2008_financial_crisis': 'var(--arcis-danger)',
  '2020_covid_crash': 'var(--arcis-warning)',
  '2022_bear_market': 'var(--arcis-accent)',
  '2018_q4_selloff': '#c084fc',
  '2011_debt_ceiling': '#f472b6',
  '2015_china_deval': '#60a5fa',
  '2024_yen_unwind': '#fbbf24',
}

export default function StressTest() {
  /* Fix for #252: Run button to trigger stress test via command queue */
  const [running, setRunning] = useState(false)
  const [runStatus, setRunStatus] = useState(null)
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['stress-test-results'],
    queryFn: () => api.getStressTestResults(),
    refetchInterval: running ? 10000 : 300000,
  })

  async function handleRunStressTest() {
    setRunning(true)
    setRunStatus('Submitting...')
    try {
      const cmd = await api.submitCommand({
        command_type: 'action',
        command_name: 'stress-test',
      })
      const cmdId = cmd?.command_id
      if (!cmdId) {
        setRunStatus('Submitted (no tracking ID)')
        setTimeout(() => { setRunning(false); setRunStatus(null); qc.invalidateQueries({ queryKey: ['stress-test-results'] }) }, 30000)
        return
      }
      setRunStatus('Running scenarios...')
      let attempts = 0
      const poll = setInterval(async () => {
        attempts++
        try {
          const status = await api.getCommandStatus(cmdId)
          if (status?.status === 'success' || status?.result_status === 'success') {
            clearInterval(poll)
            setRunStatus('Complete!')
            qc.invalidateQueries({ queryKey: ['stress-test-results'] })
            setTimeout(() => { setRunning(false); setRunStatus(null) }, 3000)
          } else if (status?.status === 'error' || status?.result_status === 'error' || attempts > 60) {
            clearInterval(poll)
            setRunStatus(status?.error || 'Timed out')
            setTimeout(() => { setRunning(false); setRunStatus(null) }, 5000)
          }
        } catch { /* ignore poll errors */ }
      }, 5000)
    } catch (err) {
      setRunStatus(`Error: ${err.message}`)
      setTimeout(() => { setRunning(false); setRunStatus(null) }, 5000)
    }
  }

  const [showPrevious, setShowPrevious] = useState(false)

  // Group by scenario so re-running a scenario shows one summary card with
  // the latest run only. Previous runs are archived in a collapsible block
  // so the page doesn't accumulate stale duplicates over time (issue #52).
  const allResults = data?.results || []
  const { latestResults, previousResults } = useMemo(() => {
    const sortKey = (r) => r.created_at || r.run_date || r.end_date || ''
    const groups = new Map()
    for (const r of allResults) {
      const key = r.scenario || 'unknown'
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(r)
    }
    const latest = []
    const previous = []
    for (const [, rows] of groups) {
      rows.sort((a, b) => sortKey(b).localeCompare(sortKey(a)))
      latest.push(rows[0])
      if (rows.length > 1) previous.push(...rows.slice(1))
    }
    return { latestResults: latest, previousResults: previous }
  }, [allResults])

  if (isLoading) return <LoadingSpinner />

  const results = latestResults

  if (results.length === 0) {
    return (
      <div className="space-y-4 md:space-y-6">
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Historical Stress Testing</h2>
        <div className="arcis-card" style={{ padding: '20px', textAlign: 'center' }}>
          <span className="text-sm font-medium" style={{ color: 'var(--arcis-text-muted)' }}>No stress test results yet</span>
          <p className="text-xs mt-1 mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>
            Click Run to simulate the model across 2008, 2020, and 2022 crisis periods
          </p>
          {/* Fix for #252: Run button on empty state */}
          <div className="flex items-center justify-center gap-3">
            {runStatus && <span className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>{runStatus}</span>}
            <button
              onClick={handleRunStressTest}
              disabled={running}
              className="px-4 py-2 text-sm font-medium"
              style={{
                borderRadius: 'var(--radius-sm)',
                background: running ? 'var(--arcis-bg-elevated)' : 'var(--arcis-accent)',
                color: running ? 'var(--arcis-text-muted)' : '#fff',
                cursor: running ? 'not-allowed' : 'pointer',
                border: '1px solid var(--arcis-border)',
              }}
            >
              {running ? 'Running...' : 'Run Stress Test'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Fix for #252: header with Run button */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Historical Stress Testing</h2>
        <div className="flex items-center gap-3">
          {runStatus && <span className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>{runStatus}</span>}
          <button
            onClick={handleRunStressTest}
            disabled={running}
            className="px-4 py-2 text-sm font-medium"
            style={{
              borderRadius: 'var(--radius-sm)',
              background: running ? 'var(--arcis-bg-elevated)' : 'var(--arcis-accent)',
              color: running ? 'var(--arcis-text-muted)' : '#fff',
              cursor: running ? 'not-allowed' : 'pointer',
              border: '1px solid var(--arcis-border)',
            }}
          >
            {running ? 'Running...' : 'Run Stress Test'}
          </button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {results.map((r) => (
          <div key={r.result_id} className="arcis-card" style={{ padding: '16px' }}>
            <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--arcis-text-primary)' }}>
              {SCENARIO_LABELS[r.scenario] || r.scenario}
            </h3>
            <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>{r.start_date} — {r.end_date}</div>
            <div className="grid grid-cols-2 gap-2 mt-3 text-sm">
              <div>
                <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Trades</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{r.total_trades || 0}</div>
              </div>
              <div>
                <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Win Rate</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{r.win_rate != null ? `${(r.win_rate * 100).toFixed(1)}%` : '--'}</div>
              </div>
              <div>
                <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Max DD</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', color: 'var(--arcis-danger)' }}>{r.max_drawdown_pct != null ? `${r.max_drawdown_pct.toFixed(1)}%` : '--'}</div>
              </div>
              <div>
                <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Calmar</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{r.calmar_ratio != null ? r.calmar_ratio.toFixed(2) : '--'}</div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Equity curves */}
      {results.some(r => r.equity_curve_json) && (
        <div className="arcis-card">
          <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>Equity Curves</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart>
              <XAxis dataKey="day" tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} />
              <YAxis tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} />
              {/* Fix for #250: add tooltip text color for dark mode readability */}
              <Tooltip contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', borderRadius: 3, fontSize: 12, color: 'var(--tooltip-text)' }} isAnimationActive={false} />
              {results.map((r) => {
                const curve = Array.isArray(r.equity_curve_json) ? r.equity_curve_json : []
                if (curve.length === 0) return null
                return (
                  <Line
                    key={r.scenario}
                    data={curve.map((v, i) => ({ day: i, value: v }))}
                    dataKey="value"
                    name={SCENARIO_LABELS[r.scenario] || r.scenario}
                    stroke={SCENARIO_COLORS[r.scenario] || '#888'}
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                )
              })}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Previous runs archive */}
      {previousResults.length > 0 && (
        <div className="arcis-card" style={{ padding: '16px' }}>
          <button
            onClick={() => setShowPrevious(v => !v)}
            className="flex items-center gap-2 text-sm uppercase tracking-wide"
            style={{ color: 'var(--arcis-text-secondary)' }}
          >
            {showPrevious ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            Previous Runs ({previousResults.length})
          </button>
          {showPrevious && (
            <div className="mt-3 space-y-1 text-xs" style={{ fontFamily: 'var(--font-mono)' }}>
              {previousResults.map((r) => (
                <div key={r.result_id} className="flex items-center gap-3 py-1" style={{ color: 'var(--arcis-text-muted)' }}>
                  <span style={{ minWidth: 180 }}>{SCENARIO_LABELS[r.scenario] || r.scenario}</span>
                  <span>{(r.created_at || r.run_date || '').slice(0, 10)}</span>
                  <span>{r.total_trades || 0} trades</span>
                  <span>{r.win_rate != null ? `${(r.win_rate * 100).toFixed(1)}% WR` : '--'}</span>
                  <span style={{ color: 'var(--arcis-danger)' }}>{r.max_drawdown_pct != null ? `${r.max_drawdown_pct.toFixed(1)}% DD` : '--'}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Methodology note */}
      <div className="arcis-card" style={{ padding: '16px' }}>
        <h3 className="text-sm uppercase tracking-wide mb-2" style={{ color: 'var(--arcis-text-secondary)' }}>Methodology</h3>
        <div className="text-xs space-y-1" style={{ color: 'var(--arcis-text-muted)' }}>
          <p>Pure ranker + mechanical brackets (no LLM). For each trading day in the crisis period: fetch OHLCV, compute features, run ranker, simulate bracket outcomes.</p>
          <p><strong>Survivorship bias note:</strong> Universe is filtered to tickers with available data for the test period. Results may overstate performance vs. a truly contemporaneous universe.</p>
          <p>Scenarios: 2008 Financial Crisis (Sep 2008 - Mar 2009), 2020 COVID Crash (Feb - Apr 2020), 2022 Bear Market (Jan - Oct 2022).</p>
        </div>
      </div>
    </div>
  )
}
