import { useQuery } from '@tanstack/react-query'
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
  const { data, isLoading } = useQuery({
    queryKey: ['stress-test-results'],
    queryFn: api.getStressTestResults,
    refetchInterval: 300000,
  })

  if (isLoading) return <LoadingSpinner />

  const results = data?.results || []

  if (results.length === 0) {
    return (
      <div className="space-y-6">
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text)' }}>Historical Stress Testing</h2>
        <div className="arcis-card" style={{ padding: '20px', textAlign: 'center' }}>
          <span className="text-sm font-medium" style={{ color: 'var(--arcis-text-muted)' }}>No stress test results yet</span>
          <p className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
            Run <code>python scripts/stress_test.py</code> to generate results for 2008, 2020, and 2022 crisis periods
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text)' }}>Historical Stress Testing</h2>

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
              <Tooltip contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', borderRadius: 8, fontSize: 12 }} />
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
