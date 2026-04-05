import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import { XAxis, YAxis, Tooltip, ResponsiveContainer, LineChart, Line } from 'recharts'

const SCENARIO_LABELS = {
  '2008_financial_crisis': '2008 Financial Crisis',
  '2020_covid_crash': '2020 COVID Crash',
  '2022_bear_market': '2022 Bear Market',
}

const SCENARIO_COLORS = {
  '2008_financial_crisis': '#ef4444',
  '2020_covid_crash': '#f59e0b',
  '2022_bear_market': '#3b82f6',
}

export default function StressTest() {
  /* Fix for #252: Run button to trigger stress test via command queue */
  const [running, setRunning] = useState(false)
  const [runStatus, setRunStatus] = useState(null)
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['stress-test-results'],
    queryFn: api.getStressTestResults,
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

  if (isLoading) return <LoadingSpinner />

  const results = data?.results || []

  if (results.length === 0) {
    return (
      <div className="space-y-6">
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text)' }}>Historical Stress Testing</h2>
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
              className="px-4 py-2 rounded text-sm font-medium transition-colors"
              style={{
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
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text)' }}>Historical Stress Testing</h2>
        <div className="flex items-center gap-3">
          {runStatus && <span className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>{runStatus}</span>}
          <button
            onClick={handleRunStressTest}
            disabled={running}
            className="px-4 py-2 rounded text-sm font-medium transition-colors"
            style={{
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
            <h3 className="text-sm font-medium mb-2" style={{ color: SCENARIO_COLORS[r.scenario] || 'var(--arcis-text)' }}>
              {SCENARIO_LABELS[r.scenario] || r.scenario}
            </h3>
            <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>{r.start_date} — {r.end_date}</div>
            <div className="grid grid-cols-2 gap-2 mt-3 text-sm">
              <div>
                <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Trades</div>
                <div style={{ fontFamily: 'var(--font-mono)' }}>{r.total_trades || 0}</div>
              </div>
              <div>
                <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Win Rate</div>
                <div style={{ fontFamily: 'var(--font-mono)' }}>{r.win_rate != null ? `${(r.win_rate * 100).toFixed(1)}%` : '--'}</div>
              </div>
              <div>
                <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Max DD</div>
                <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-danger)' }}>{r.max_drawdown_pct != null ? `${r.max_drawdown_pct.toFixed(1)}%` : '--'}</div>
              </div>
              <div>
                <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Calmar</div>
                <div style={{ fontFamily: 'var(--font-mono)' }}>{r.calmar_ratio != null ? r.calmar_ratio.toFixed(2) : '--'}</div>
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
              <Tooltip contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', borderRadius: 8, fontSize: 12, color: 'var(--tooltip-text)' }} />
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
                  />
                )
              })}
            </LineChart>
          </ResponsiveContainer>
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
