import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { BarChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ComposedChart } from 'recharts'

const scenarios = {
  conservative: { sharpe: 0.35, vol: 15, brkMonth: 12, divBenefit: 25 },
  base:         { sharpe: 0.60, vol: 15, brkMonth: 10, divBenefit: 35 },
  optimistic:   { sharpe: 0.90, vol: 15, brkMonth: 8,  divBenefit: 45 },
}

const phases = [
  { name: 'Phase 1',  months: [1,3],   capStart: 100,     capEnd: 100,     cost: 64,   strategy: 'pullback' },
  { name: 'Phase 2',  months: [4,6],   capStart: 100,     capEnd: 1000,    cost: 125,  strategy: 'pullback' },
  { name: 'Phase 2b', months: [7,9],   capStart: 1000,    capEnd: 1000,    cost: 140,  strategy: 'pullback' },
  { name: 'Phase 3',  months: [10,12], capStart: 1000,    capEnd: 5000,    cost: 155,  strategy: 'dual' },
  { name: 'Phase 4',  months: [13,18], capStart: 5000,    capEnd: 25000,   cost: 220,  strategy: 'dual' },
  { name: 'Phase 4b', months: [19,24], capStart: 25000,   capEnd: 100000,  cost: 300,  strategy: 'dual' },
  { name: 'Phase 5',  months: [25,36], capStart: 100000,  capEnd: 500000,  cost: 500,  strategy: 'dual' },
  { name: 'Phase 5b', months: [37,48], capStart: 500000,  capEnd: 1500000, cost: 2000, strategy: 'dual' },
  { name: 'Phase 6',  months: [49,60], capStart: 1500000, capEnd: 3000000, cost: 5000, strategy: 'dual' },
]

const GATE_THRESHOLDS = {
  winRate: { green: 0.45, yellow: 0.38 },
  profitFactor: { green: 1.3, yellow: 1.1 },
  sharpe: { green: 0.15, yellow: 0.05 },
  maxDD: { green: 12, yellow: 18, invert: true },
}

function gatePill(value, key) {
  if (value == null) return { color: 'var(--arcis-text-muted)', label: 'pending' }
  const t = GATE_THRESHOLDS[key]
  if (!t) return { color: 'var(--arcis-text-muted)', label: '--' }
  if (t.invert) {
    if (value <= t.green) return { color: 'var(--arcis-accent)', label: 'pass' }
    if (value <= t.yellow) return { color: 'var(--arcis-warning)', label: 'watch' }
    return { color: 'var(--arcis-danger)', label: 'fail' }
  }
  if (value >= t.green) return { color: 'var(--arcis-accent)', label: 'pass' }
  if (value >= t.yellow) return { color: 'var(--arcis-warning)', label: 'watch' }
  return { color: 'var(--arcis-danger)', label: 'fail' }
}

function computeProjections(params) {
  const { sharpe, vol, brkMonth, divBenefit } = params
  let cumPnl = 0
  return phases.map(p => {
    const periodMonths = p.months[1] - p.months[0] + 1
    const avgCap = (p.capStart + p.capEnd) / 2
    const effectiveSharpe = p.strategy === 'dual' && p.months[0] >= brkMonth
      ? sharpe * (1 + divBenefit / 100)
      : sharpe
    const annReturn = effectiveSharpe * (vol / 100) * 0.85 // 15% DD haircut
    const periodReturn = annReturn * (periodMonths / 12)
    const periodPnl = avgCap * periodReturn - p.cost * periodMonths
    cumPnl += periodPnl
    return {
      name: p.name,
      capital: p.capEnd,
      annReturn: Math.round(annReturn * 100),
      periodPnl: Math.round(periodPnl),
      cumPnl: Math.round(cumPnl),
      cost: p.cost * periodMonths,
      sharpe: effectiveSharpe.toFixed(2),
    }
  })
}

function GatePill({ value, metricKey }) {
  const g = gatePill(value, metricKey)
  return (
    <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
      style={{ background: g.color, color: '#fff', opacity: value == null ? 0.5 : 1 }}>
      {g.label}
    </span>
  )
}

export default function RevenueProjection() {
  const [mode, setMode] = useState('base')
  const [sliders, setSliders] = useState(scenarios.base)

  const { data: live } = useQuery({
    queryKey: ['projections-live'],
    queryFn: () => api.getProjectionsLive(),
    refetchInterval: 60000,
  })

  const isLive = mode === 'live'
  const liveLocked = isLive && (live?.trades || 0) >= 20

  const effectiveParams = useMemo(() => {
    if (isLive && liveLocked) {
      return { ...sliders, sharpe: live?.sharpe || 0 }
    }
    return sliders
  }, [isLive, liveLocked, sliders, live])

  const projections = useMemo(() => computeProjections(effectiveParams), [effectiveParams])

  const handleMode = (m) => {
    setMode(m)
    if (m !== 'live' && scenarios[m]) setSliders(scenarios[m])
  }

  const metrics = isLive && live ? [
    { label: 'Trades', value: live.trades, fmt: v => v, key: null },
    { label: 'Win Rate', value: live.winRate != null ? live.winRate * 100 : null, fmt: v => `${v.toFixed(1)}%`, key: 'winRate', raw: live.winRate },
    { label: 'Sharpe', value: live.sharpe, fmt: v => v.toFixed(2), key: 'sharpe' },
    { label: 'Profit Factor', value: live.profitFactor, fmt: v => v.toFixed(2), key: 'profitFactor' },
    { label: 'Max DD', value: live.maxDD, fmt: v => `${v.toFixed(1)}%`, key: 'maxDD' },
    { label: 'Net P&L', value: live.netPnl, fmt: v => `$${v.toLocaleString()}`, key: null },
  ] : null

  const modes = [
    { key: 'live', label: 'Live' },
    { key: 'conservative', label: 'Conservative' },
    { key: 'base', label: 'Base case' },
    { key: 'optimistic', label: 'Optimistic' },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>
          Revenue Projection
        </h3>
        <div className="flex gap-1">
          {modes.map(m => (
            <button key={m.key} onClick={() => handleMode(m.key)}
              className="px-3 py-1 text-xs rounded-md transition-colors"
              style={{
                background: mode === m.key ? 'var(--arcis-accent-muted)' : 'var(--arcis-bg-surface)',
                color: mode === m.key ? 'var(--arcis-accent)' : 'var(--arcis-text-secondary)',
                border: `1px solid ${mode === m.key ? 'var(--arcis-accent-hover)' : 'var(--arcis-border)'}`,
              }}>
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {/* Live metrics strip */}
      {metrics && (
        <div className="grid grid-cols-6 gap-2">
          {metrics.map((m, i) => (
            <div key={i} className="p-2 text-center" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 'var(--radius-sm)' }}>
              <div className="text-[10px] uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>{m.label}</div>
              <div className="text-sm font-medium mt-0.5" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-primary)' }}>
                {m.value != null ? m.fmt(m.value) : '--'}
              </div>
              {m.key && <GatePill value={m.key === 'winRate' ? m.raw : m.value} metricKey={m.key} />}
            </div>
          ))}
        </div>
      )}

      {/* Sliders */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div>
          <label className="text-[10px] uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>
            Sharpe {liveLocked ? '(locked)' : ''}
          </label>
          <input type="range" min="0.1" max="1.5" step="0.05" disabled={liveLocked}
            value={effectiveParams.sharpe}
            onChange={e => setSliders(s => ({ ...s, sharpe: parseFloat(e.target.value) }))}
            className="w-full accent-[var(--arcis-accent)]" />
          <div className="text-xs text-center" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-secondary)' }}>
            {effectiveParams.sharpe.toFixed(2)}
          </div>
        </div>
        <div>
          <label className="text-[10px] uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Portfolio Vol %</label>
          <input type="range" min="8" max="25" step="1"
            value={sliders.vol}
            onChange={e => setSliders(s => ({ ...s, vol: parseInt(e.target.value) }))}
            className="w-full accent-[var(--arcis-accent)]" />
          <div className="text-xs text-center" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-secondary)' }}>
            {sliders.vol}%
          </div>
        </div>
        <div>
          <label className="text-[10px] uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Breakout Month</label>
          <input type="range" min="6" max="18" step="1"
            value={sliders.brkMonth}
            onChange={e => setSliders(s => ({ ...s, brkMonth: parseInt(e.target.value) }))}
            className="w-full accent-[var(--arcis-accent)]" />
          <div className="text-xs text-center" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-secondary)' }}>
            Month {sliders.brkMonth}
          </div>
        </div>
        <div>
          <label className="text-[10px] uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Diversification %</label>
          <input type="range" min="10" max="60" step="5"
            value={sliders.divBenefit}
            onChange={e => setSliders(s => ({ ...s, divBenefit: parseInt(e.target.value) }))}
            className="w-full accent-[var(--arcis-accent)]" />
          <div className="text-xs text-center" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-secondary)' }}>
            {sliders.divBenefit}%
          </div>
        </div>
      </div>

      {/* Chart */}
      <div className="p-4" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 'var(--radius-sm)' }}>
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={projections}>
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} />
            <YAxis yAxisId="pnl" tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} tickFormatter={v => `$${(v/1000).toFixed(0)}K`} />
            <YAxis yAxisId="cap" orientation="right" tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} tickFormatter={v => v >= 1000000 ? `$${(v/1000000).toFixed(1)}M` : `$${(v/1000).toFixed(0)}K`} />
            {/* Fix for #250: add tooltip text color for dark mode readability */}
            <Tooltip contentStyle={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 8, fontSize: 12, color: 'var(--tooltip-text)' }}
              formatter={(v, name) => [`$${v.toLocaleString()}`, name]} />
            <Bar yAxisId="pnl" dataKey="cumPnl" name="Cumulative P&L" fill="var(--arcis-accent)" radius={[2,2,0,0]} fillOpacity={0.7} />
            <Line yAxisId="cap" dataKey="capital" name="Capital" stroke="var(--arcis-warning)" strokeWidth={2} dot={{ r: 3 }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Projection table */}
      <div className="overflow-hidden" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 'var(--radius-sm)' }}>
        <table className="w-full text-xs">
          <thead>
            <tr style={{ borderBottom: '1px solid var(--arcis-border)' }}>
              {['Phase', 'Capital', 'Sharpe', 'Ann. Return', 'Period P&L', 'Cumulative', 'Costs'].map(h => (
                <th key={h} className="p-2 text-right first:text-left" style={{ color: 'var(--arcis-text-secondary)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {projections.map((p, i) => (
              /* Fix for #250: use theme-aware border color */
              <tr key={i} style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                <td className="p-2" style={{ color: 'var(--arcis-text-primary)' }}>{p.name}</td>
                <td className="p-2 text-right" style={{ fontFamily: 'var(--font-mono)' }}>${p.capital.toLocaleString()}</td>
                <td className="p-2 text-right" style={{ fontFamily: 'var(--font-mono)' }}>{p.sharpe}</td>
                <td className="p-2 text-right" style={{ fontFamily: 'var(--font-mono)' }}>{p.annReturn}%</td>
                <td className="p-2 text-right" style={{ fontFamily: 'var(--font-mono)', color: p.periodPnl >= 0 ? 'var(--arcis-accent)' : 'var(--arcis-danger)' }}>
                  ${p.periodPnl.toLocaleString()}
                </td>
                <td className="p-2 text-right" style={{ fontFamily: 'var(--font-mono)', color: p.cumPnl >= 0 ? 'var(--arcis-accent)' : 'var(--arcis-danger)' }}>
                  ${p.cumPnl.toLocaleString()}
                </td>
                <td className="p-2 text-right" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-secondary)' }}>
                  ${p.cost.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
