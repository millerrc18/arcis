import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import MetricCard from '../components/MetricCard'
import ActionButton from '../components/ActionButton'
import LoadingSpinner from '../components/LoadingSpinner'
import { XAxis, YAxis, Tooltip, ResponsiveContainer, LineChart, Line, Legend } from 'recharts'

const CHART_COLORS = [
  'var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)',
  'var(--chart-5)', 'var(--chart-6)', 'var(--chart-7)', 'var(--chart-8)',
]

const VERDICT_BORDER = {
  edge: 'var(--arcis-success)',
  marginal: 'var(--arcis-warning)',
  bleeds: 'var(--arcis-danger)',
}

function formatPct(v, decimals = 1) {
  if (v == null) return '--'
  const num = Number(v)
  return `${num >= 0 ? '+' : ''}${num.toFixed(decimals)}%`
}

function VerdictBadge({ verdict }) {
  if (!verdict) return <span style={{ color: 'var(--arcis-text-muted)' }}>--</span>
  const v = verdict.toLowerCase()
  let color = 'var(--arcis-text-muted)'
  if (v === 'edge') color = 'var(--arcis-success)'
  else if (v === 'marginal') color = 'var(--arcis-warning)'
  else if (v === 'bleeds') color = 'var(--arcis-danger)'
  else if (v === 'insufficient') color = 'var(--arcis-text-muted)'
  return (
    <span className="text-xs font-medium uppercase" style={{ color }}>
      {verdict}
    </span>
  )
}

export default function Simulation() {
  const [running, setRunning] = useState(false)
  const [runStatus, setRunStatus] = useState(null)
  // DB-3 Task 6 — regime selector for equity curve overlay. 'all' shows all
  // at full strength; a specific regime highlights its line and dims the rest.
  const [highlightedRegime, setHighlightedRegime] = useState('all')
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['simulation-results'],
    queryFn: () => api.getSimulationResults(),
    refetchInterval: running ? 10000 : 300000,
  })

  async function handleRunSimulation() {
    setRunning(true)
    setRunStatus('Submitting...')
    try {
      const cmd = await api.submitCommand({
        command_type: 'action',
        command_name: 'simulation',
      })
      const cmdId = cmd?.command_id
      if (!cmdId) {
        setRunStatus('Submitted (no tracking ID)')
        setTimeout(() => { setRunning(false); setRunStatus(null); qc.invalidateQueries({ queryKey: ['simulation-results'] }) }, 30000)
        return
      }
      setRunStatus('Running simulation...')
      let attempts = 0
      const poll = setInterval(async () => {
        attempts++
        try {
          const status = await api.getCommandStatus(cmdId)
          if (status?.status === 'success' || status?.result_status === 'success') {
            clearInterval(poll)
            setRunStatus('Complete!')
            qc.invalidateQueries({ queryKey: ['simulation-results'] })
            setTimeout(() => { setRunning(false); setRunStatus(null) }, 3000)
          } else if (status?.status === 'error' || status?.result_status === 'error' || attempts > 120) {
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

  // Group by run_id to get the latest run
  const latestRunId = results.length > 0 ? results[0].run_id : null
  const latestResults = results.filter(r => r.run_id === latestRunId)

  // Monte Carlo data
  const hasMC = latestResults.some(r => r.mc_p95_dd != null)
  const mcRow = latestResults.find(r => r.mc_p95_dd != null)

  // Traffic light scorecard
  const tlResults = latestResults.map(r => ({
    scenario: r.regime_label || r.scenario,
    expected: r.tl_expected || '--',
    actual: r.tl_actual_majority || '--',
    correct: !!r.tl_correct,
  }))
  const tlCorrect = tlResults.filter(r => r.correct).length
  const tlTotal = tlResults.length

  // Last run metadata
  const lastRunTime = latestResults.length > 0 ? latestResults[0].created_at : null
  const modelVersion = latestResults.length > 0 ? latestResults[0].model_version : null

  // Build equity curve chart data
  const equityCurveData = (() => {
    if (latestResults.length === 0) return []
    const maxLen = Math.max(...latestResults.map(r => (r.equity_curve_json || []).length))
    const chartData = []
    for (let i = 0; i < maxLen; i++) {
      const point = { day: i }
      latestResults.forEach(r => {
        const curve = r.equity_curve_json || []
        if (i < curve.length) {
          const start = curve[0] || 100000
          point[r.scenario] = start > 0 ? ((curve[i] - start) / start * 100) : 0
        }
      })
      chartData.push(point)
    }
    return chartData
  })()

  if (latestResults.length === 0) {
    return (
      <div className="space-y-4 md:space-y-6">
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text)' }}>Simulation Engine</h2>
        <div className="arcis-card" style={{ padding: '20px', textAlign: 'center' }}>
          <span className="text-sm font-medium" style={{ color: 'var(--arcis-text-muted)' }}>No simulation results yet</span>
          <p className="text-xs mt-1 mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>
            Run the simulation engine across all 13 market regime scenarios
          </p>
          <div className="flex items-center justify-center gap-3">
            {runStatus && <span className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>{runStatus}</span>}
            <ActionButton
              cliOnly={false}
              pending={running}
              onClick={handleRunSimulation}
            >
              {running ? 'Running...' : 'Run Simulation'}
            </ActionButton>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Section 5: Run Controls — header with run button, timestamp, model version */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text)' }}>Simulation Engine</h2>
          <p className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
            Full-regime backtesting across 13 market scenarios
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastRunTime && (
            <span className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>
              Last run: {new Date(lastRunTime).toLocaleString()}
            </span>
          )}
          {modelVersion && (
            <span className="text-xs" style={{ color: 'var(--arcis-text-secondary)', fontFamily: 'var(--font-mono)' }}>
              {modelVersion}
            </span>
          )}
          {runStatus && <span className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>{runStatus}</span>}
          <ActionButton
            cliOnly={false}
            pending={running}
            onClick={handleRunSimulation}
          >
            {running ? 'Running...' : 'Run Simulation'}
          </ActionButton>
        </div>
      </div>

      {/* Section 1: Regime Heatmap Table */}
      <div className="arcis-card" style={{ padding: 0, overflow: 'hidden' }}>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: '1px solid var(--arcis-border)' }}>
              <th className="px-3 py-2 text-left text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Regime</th>
              <th className="px-3 py-2 text-right text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Trades</th>
              <th className="px-3 py-2 text-right text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>WR</th>
              <th className="px-3 py-2 text-right text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>PF</th>
              <th className="px-3 py-2 text-right text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>DD</th>
              <th className="px-3 py-2 text-right text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Sharpe</th>
              <th className="px-3 py-2 text-right text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>SPY</th>
              <th className="px-3 py-2 text-right text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Excess</th>
              <th className="px-3 py-2 text-center text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Verdict</th>
            </tr>
          </thead>
          <tbody>
            {latestResults.map((r) => {
              const v = (r.verdict || '').toLowerCase()
              const excess = (r.excess_return_pct != null) ? r.excess_return_pct : ((r.total_pnl_pct || 0) - (r.benchmark_pnl_pct || 0))
              const borderColor = VERDICT_BORDER[v]
              const isInsufficient = v === 'insufficient'
              const rowStyle = {
                borderBottom: '1px solid var(--arcis-border)',
                borderLeft: borderColor ? `3px solid ${borderColor}` : '3px solid transparent',
                fontStyle: isInsufficient ? 'italic' : 'normal',
              }
              const cellColor = isInsufficient ? 'var(--arcis-text-muted)' : 'var(--arcis-text-primary)'
              const monoStyle = { fontFamily: 'var(--font-mono)', color: cellColor }
              return (
                <tr key={r.result_id} style={rowStyle}>
                  <td className="px-3 py-2 text-sm font-medium" style={{ color: cellColor }}>{r.regime_label || r.scenario}</td>
                  <td className="px-3 py-2 text-right" style={monoStyle}>{r.total_trades ?? '--'}</td>
                  <td className="px-3 py-2 text-right" style={monoStyle}>{r.win_rate != null ? `${(r.win_rate * 100).toFixed(0)}%` : '--'}</td>
                  <td className="px-3 py-2 text-right" style={monoStyle}>{r.profit_factor != null ? r.profit_factor.toFixed(2) : 'N/A (no losses)'}</td>
                  <td className="px-3 py-2 text-right" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-danger)' }}>{r.max_drawdown_pct != null ? `${r.max_drawdown_pct.toFixed(1)}%` : '--'}</td>
                  <td className="px-3 py-2 text-right" style={monoStyle}>{r.sharpe_ratio != null ? r.sharpe_ratio.toFixed(2) : '--'}</td>
                  <td className="px-3 py-2 text-right" style={{ fontFamily: 'var(--font-mono)', color: (r.benchmark_pnl_pct || 0) >= 0 ? 'var(--arcis-success)' : 'var(--arcis-danger)' }}>{formatPct(r.benchmark_pnl_pct)}</td>
                  <td className="px-3 py-2 text-right" style={{ fontFamily: 'var(--font-mono)', color: excess >= 0 ? 'var(--arcis-success)' : 'var(--arcis-danger)' }}>{formatPct(excess)}</td>
                  <td className="px-3 py-2 text-center"><VerdictBadge verdict={r.verdict} /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Section 2: Equity Curve Overlay */}
      {equityCurveData.length > 0 && (
        <div className="arcis-card">
          <div className="flex items-center justify-between flex-wrap gap-2 mb-4">
            <h3 className="text-sm uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Equity Curves</h3>
            {/* DB-3 Task 6: regime selector — highlight one curve, dim the rest */}
            <select
              value={highlightedRegime}
              onChange={(e) => setHighlightedRegime(e.target.value)}
              className="text-xs px-2 py-1"
              style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-primary)', outline: 'none' }}
            >
              <option value="all">All regimes</option>
              {latestResults
                .filter(r => (r.equity_curve_json || []).length > 0)
                .map((r) => (
                  <option key={r.scenario} value={r.scenario}>
                    {r.regime_label || r.scenario}
                  </option>
                ))}
            </select>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={equityCurveData}>
              <XAxis dataKey="day" tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} />
              <YAxis tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} tickFormatter={v => `${v.toFixed(0)}%`} />
              <Tooltip
                contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', borderRadius: 'var(--radius-md)', fontSize: 12, color: 'var(--tooltip-text)' }}
                formatter={(val) => [`${val.toFixed(2)}%`, undefined]}
                labelFormatter={(day) => `Day ${day}`}
              />
              <Legend wrapperStyle={{ color: 'var(--arcis-text-secondary)', fontSize: 11 }} />
              {latestResults.map((r, i) => {
                const curve = r.equity_curve_json || []
                if (curve.length === 0) return null
                const isHighlighted = highlightedRegime === 'all' || highlightedRegime === r.scenario
                return (
                  <Line
                    key={r.scenario}
                    dataKey={r.scenario}
                    name={r.regime_label || r.scenario}
                    stroke={CHART_COLORS[i % CHART_COLORS.length]}
                    strokeWidth={isHighlighted ? (highlightedRegime !== 'all' && highlightedRegime === r.scenario ? 2.5 : 1.5) : 1}
                    strokeOpacity={isHighlighted ? 1 : 0.15}
                    dot={false}
                    connectNulls
                    isAnimationActive={false}
                  />
                )
              })}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Section 3: Monte Carlo Confidence Band */}
      {hasMC && mcRow && (
        <>
          <h3 className="text-sm uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Monte Carlo Confidence Band</h3>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <MetricCard
              label="P5 Equity"
              value={mcRow.mc_p5_equity != null ? `$${Number(mcRow.mc_p5_equity).toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '--'}
            />
            <MetricCard
              label="Median Equity"
              value={mcRow.mc_median_equity != null ? `$${Number(mcRow.mc_median_equity).toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '--'}
            />
            <MetricCard
              label="P95 Equity"
              value={mcRow.mc_p95_equity != null ? `$${Number(mcRow.mc_p95_equity).toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '--'}
            />
            <MetricCard
              label="P(Ruin)"
              value={mcRow.mc_probability_of_ruin != null ? `${(mcRow.mc_probability_of_ruin * 100).toFixed(2)}%` : '--'}
            />
            <MetricCard
              label="P95 Worst DD"
              value={mcRow.mc_p95_dd != null ? `${mcRow.mc_p95_dd.toFixed(1)}%` : '--'}
            />
          </div>
        </>
      )}

      {/* Section 4: Traffic Light Validation Scorecard */}
      {tlResults.length > 0 && (
        <div className="arcis-card" style={{ padding: 0, overflow: 'hidden' }}>
          <div className="px-4 pt-4 pb-2 flex items-center justify-between">
            <h3 className="text-sm uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Traffic Light Validation</h3>
            <span className="text-xs" style={{ fontFamily: 'var(--font-mono)', color: tlCorrect === tlTotal ? 'var(--arcis-success)' : 'var(--arcis-text-secondary)' }}>
              {tlCorrect}/{tlTotal} correct
            </span>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                <th className="px-4 py-2 text-left text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Scenario</th>
                <th className="px-4 py-2 text-center text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Expected TL</th>
                <th className="px-4 py-2 text-center text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Actual TL</th>
                <th className="px-4 py-2 text-center text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Correct?</th>
              </tr>
            </thead>
            <tbody>
              {tlResults.map((tl, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                  <td className="px-4 py-2" style={{ color: 'var(--arcis-text-primary)' }}>{tl.scenario}</td>
                  <td className="px-4 py-2 text-center" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-primary)' }}>{tl.expected}</td>
                  <td className="px-4 py-2 text-center" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-primary)' }}>{tl.actual}</td>
                  <td className="px-4 py-2 text-center text-lg">
                    {tl.correct
                      ? <span style={{ color: 'var(--arcis-success)' }}>&#x2713;</span>
                      : <span style={{ color: 'var(--arcis-danger)' }}>&#x2717;</span>
                    }
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
