import { useQuery } from '@tanstack/react-query'
import { api } from '../api'

const VERDICT_COLORS = {
  edge: 'text-green-400',
  neutral: 'text-gray-400',
  marginal: 'text-yellow-400',
  bleeds: 'text-red-400',
  insufficient: 'text-gray-500',
}

const VERDICT_ICONS = {
  edge: '\u2705',
  neutral: '\u26aa',
  marginal: '\u26a0\ufe0f',
  bleeds: '\u274c',
  insufficient: '\ud83d\udcca',
}

function formatPct(v, decimals = 1) {
  if (v == null) return '-'
  const num = Number(v)
  return `${num >= 0 ? '+' : ''}${num.toFixed(decimals)}%`
}

function PnlCell({ value }) {
  if (value == null) return <td className="px-3 py-2 text-right font-mono text-gray-500">-</td>
  const num = Number(value)
  const color = num >= 0 ? 'text-green-400' : 'text-red-400'
  return <td className={`px-3 py-2 text-right font-mono ${color}`}>{formatPct(num)}</td>
}

export default function Simulation() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['simulation-results'],
    queryFn: api.getSimulationResults,
    refetchInterval: 60000,
  })

  const results = data?.results || []

  // Group by run_id to get the latest run
  const latestRunId = results.length > 0 ? results[0].run_id : null
  const latestResults = results.filter(r => r.run_id === latestRunId)

  // Separate MC results (stored per-scenario but we show aggregate)
  const hasMC = latestResults.some(r => r.mc_p95_dd != null)

  const handleRunSimulation = async () => {
    try {
      await api.submitCommand({ command: 'simulation' })
    } catch (e) {
      console.error('Failed to trigger simulation:', e)
    }
  }

  if (isLoading) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold mb-4" style={{ fontFamily: 'var(--font-mono)' }}>Simulation Engine</h1>
        <p className="text-gray-400">Loading simulation results...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold mb-4" style={{ fontFamily: 'var(--font-mono)' }}>Simulation Engine</h1>
        <p className="text-red-400">Error: {error.message}</p>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ fontFamily: 'var(--font-mono)' }}>Simulation Engine</h1>
          <p className="text-sm text-gray-400 mt-1">
            Full-regime backtesting across 13 market scenarios
          </p>
        </div>
        <div className="flex items-center gap-4">
          {latestResults.length > 0 && (
            <span className="text-xs text-gray-500">
              Last run: {new Date(latestResults[0].created_at).toLocaleString()}
            </span>
          )}
          <button
            onClick={handleRunSimulation}
            className="px-4 py-2 rounded text-sm font-medium"
            style={{ background: 'var(--arcis-accent, #3b82f6)', color: '#fff' }}
          >
            Run Simulation
          </button>
        </div>
      </div>

      {/* Regime Heatmap Table */}
      {latestResults.length > 0 ? (
        <div className="overflow-x-auto rounded border" style={{ borderColor: 'var(--arcis-border, #333)', background: 'var(--arcis-bg-surface, #1a1a2e)' }}>
          <table className="w-full text-sm" style={{ fontFamily: 'var(--font-mono)' }}>
            <thead>
              <tr className="border-b" style={{ borderColor: 'var(--arcis-border, #333)' }}>
                <th className="px-3 py-2 text-left">Regime</th>
                <th className="px-3 py-2 text-right">Trades</th>
                <th className="px-3 py-2 text-right">WR</th>
                <th className="px-3 py-2 text-right">PF</th>
                <th className="px-3 py-2 text-right">DD</th>
                <th className="px-3 py-2 text-right">Sharpe</th>
                <th className="px-3 py-2 text-right">SPY</th>
                <th className="px-3 py-2 text-right">Excess</th>
                <th className="px-3 py-2 text-center">TL</th>
                <th className="px-3 py-2 text-center">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {latestResults.map((r) => {
                const excess = (r.total_pnl_pct || 0) - (r.benchmark_pnl_pct || 0)
                return (
                  <tr key={r.result_id} className="border-b hover:bg-white/5" style={{ borderColor: 'var(--arcis-border, #333)' }}>
                    <td className="px-3 py-2 font-medium">{r.regime_label || r.scenario}</td>
                    <td className="px-3 py-2 text-right font-mono">{r.total_trades}</td>
                    <td className="px-3 py-2 text-right font-mono">{r.win_rate != null ? `${(r.win_rate * 100).toFixed(0)}%` : '-'}</td>
                    <td className="px-3 py-2 text-right font-mono">{r.profit_factor?.toFixed(2) || '-'}</td>
                    <td className="px-3 py-2 text-right font-mono text-red-400">{r.max_drawdown_pct?.toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right font-mono">{r.sharpe_ratio?.toFixed(2) || '-'}</td>
                    <PnlCell value={r.benchmark_pnl_pct} />
                    <PnlCell value={excess} />
                    <td className="px-3 py-2 text-center">{r.tl_correct ? '\u2705' : '\u274c'}</td>
                    <td className={`px-3 py-2 text-center font-medium ${VERDICT_COLORS[r.verdict] || 'text-gray-500'}`}>
                      {VERDICT_ICONS[r.verdict] || ''} {r.verdict?.toUpperCase()}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="p-8 text-center rounded border" style={{ borderColor: 'var(--arcis-border, #333)', background: 'var(--arcis-bg-surface, #1a1a2e)' }}>
          <p className="text-gray-400 mb-4">No simulation results yet</p>
          <button
            onClick={handleRunSimulation}
            className="px-4 py-2 rounded text-sm"
            style={{ background: 'var(--arcis-accent, #3b82f6)', color: '#fff' }}
          >
            Run First Simulation
          </button>
        </div>
      )}

      {/* Bottom row: Equity Curve + Monte Carlo */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Equity Curves */}
        <div className="rounded border p-4" style={{ borderColor: 'var(--arcis-border, #333)', background: 'var(--arcis-bg-surface, #1a1a2e)' }}>
          <h3 className="text-sm font-bold mb-3" style={{ fontFamily: 'var(--font-mono)' }}>Equity Curves</h3>
          {latestResults.length > 0 ? (
            <div className="space-y-2">
              {latestResults.map((r) => {
                const curve = r.equity_curve_json || []
                const startVal = curve[0] || 100000
                const endVal = curve[curve.length - 1] || startVal
                const pctChange = ((endVal - startVal) / startVal * 100)
                const color = pctChange >= 0 ? 'text-green-400' : 'text-red-400'
                return (
                  <div key={r.result_id} className="flex justify-between text-xs font-mono">
                    <span className="text-gray-400">{r.regime_label || r.scenario}</span>
                    <span className={color}>
                      ${startVal.toLocaleString()} → ${endVal.toLocaleString()} ({pctChange >= 0 ? '+' : ''}{pctChange.toFixed(1)}%)
                    </span>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className="text-gray-500 text-sm">No data</p>
          )}
        </div>

        {/* Monte Carlo Summary */}
        <div className="rounded border p-4" style={{ borderColor: 'var(--arcis-border, #333)', background: 'var(--arcis-bg-surface, #1a1a2e)' }}>
          <h3 className="text-sm font-bold mb-3" style={{ fontFamily: 'var(--font-mono)' }}>Monte Carlo Summary</h3>
          {hasMC ? (
            <div className="space-y-2 text-sm font-mono">
              {latestResults.filter(r => r.mc_p95_dd != null).slice(0, 1).map((r) => (
                <div key={r.result_id} className="space-y-1">
                  <div className="flex justify-between"><span className="text-gray-400">P5 Equity</span><span>${r.mc_p5_equity?.toLocaleString()}</span></div>
                  <div className="flex justify-between"><span className="text-gray-400">P95 Equity</span><span>${r.mc_p95_equity?.toLocaleString()}</span></div>
                  <div className="flex justify-between"><span className="text-gray-400">P95 Drawdown</span><span className="text-red-400">{r.mc_p95_dd?.toFixed(1)}%</span></div>
                  <div className="flex justify-between"><span className="text-gray-400">P(Ruin)</span><span>{(r.mc_probability_of_ruin * 100)?.toFixed(2)}%</span></div>
                  <div className="flex justify-between"><span className="text-gray-400">Simulations</span><span>{r.mc_n_simulations?.toLocaleString()}</span></div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-500 text-sm">No Monte Carlo data — run with --monte-carlo flag</p>
          )}
        </div>
      </div>
    </div>
  )
}
