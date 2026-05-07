import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchApi, api } from '../api'
import {
  LineChart, Line, BarChart, Bar, AreaChart, Area, ComposedChart,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import MetricCard from '../components/MetricCard'
import LoadingSpinner from '../components/LoadingSpinner'
import TooltipComponent from '../components/Tooltip'

const MONO = { fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }
const BAND_ORDER = ['0-39', '40-59', '60-79', '80-100']
const BAND_COLORS = ['var(--arcis-danger)', 'var(--arcis-warning)', 'var(--arcis-accent)', 'var(--arcis-success)']

function PnlValue({ value }) {
  if (value == null) return <span style={{ ...MONO, color: 'var(--arcis-text-muted)' }}>--</span>
  const color = value > 0 ? 'var(--arcis-success)' : value < 0 ? 'var(--arcis-danger)' : 'var(--arcis-text-secondary)'
  return <span style={{ ...MONO, color }}>{value.toFixed(2)}</span>
}

export default function Strategy() {
  const [selectedStrategy, setSelectedStrategy] = useState('pullback')
  const { data, isLoading, error } = useQuery({
    queryKey: ['strategy-detail', selectedStrategy],
    queryFn: () => api.getStrategyDetail(selectedStrategy),
    refetchInterval: 120000,
  })

  // Compute KPIs from trades
  const kpis = useMemo(() => {
    if (!data?.trades?.length) return null
    const trades = data.trades
    const totalTrades = trades.length
    const wins = trades.filter(t => (t.pnl_dollars || 0) > 0)
    const losses = trades.filter(t => (t.pnl_dollars || 0) <= 0)
    const winRate = totalTrades > 0 ? (wins.length / totalTrades * 100) : 0
    const grossWins = wins.reduce((s, t) => s + Math.abs(t.pnl_pct || 0), 0)
    const grossLosses = losses.reduce((s, t) => s + Math.abs(t.pnl_pct || 0), 0)
    const profitFactor = grossLosses > 0 ? (grossWins / grossLosses) : (grossWins > 0 ? Infinity : 0)
    const durations = trades.map(t => t.duration_days || 0)
    const avgHold = durations.length > 0 ? durations.reduce((a, b) => a + b, 0) / durations.length : 0
    return {
      totalTrades,
      winRate: winRate.toFixed(1),
      profitFactor: profitFactor === Infinity ? '---' : profitFactor.toFixed(2),
      avgHold: avgHold.toFixed(1),
    }
  }, [data])

  // Score band chart data
  const scoreBandData = useMemo(() => {
    if (!data?.by_score_band) return []
    return BAND_ORDER.map(band => ({
      band,
      win_rate: (data.by_score_band[band]?.win_rate || 0) * 100,
      trades: data.by_score_band[band]?.trades || 0,
      avg_pnl: data.by_score_band[band]?.avg_pnl || 0,
    }))
  }, [data])

  // Equity curve data (use trade index + entry_date)
  const equityData = useMemo(() => {
    if (!data?.trades?.length) return []
    return data.trades.map((t, i) => ({
      idx: i + 1,
      date: (t.entry_date || '').slice(0, 10),
      cumulative_pnl: t.cumulative_pnl,
    }))
  }, [data])

  if (isLoading) return <LoadingSpinner />
  if (error) return <div className="arcis-card" style={{ padding: 20, color: 'var(--arcis-danger)' }}>Failed to load strategy data: {error.message}</div>

  const strategyLabel = selectedStrategy === 'pullback' ? 'Pullback' : 'Mean Reversion'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Strategy Selector */}
      <div className="arcis-card" style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 500, color: 'var(--arcis-text-secondary)' }}>
          Strategy
        </div>
        {[
          { key: 'pullback', label: 'Pullback' },
          { key: 'mean_reversion', label: 'Mean Reversion' },
        ].map(s => (
          <button
            key={s.key}
            onClick={() => setSelectedStrategy(s.key)}
            style={{
              padding: '6px 16px',
              fontSize: 12,
              fontWeight: 500,
              border: '1px solid',
              borderColor: selectedStrategy === s.key ? 'var(--arcis-accent)' : 'var(--arcis-border)',
              borderRadius: 4,
              background: selectedStrategy === s.key ? 'var(--arcis-accent)' : 'transparent',
              color: selectedStrategy === s.key ? '#fff' : 'var(--arcis-text-secondary)',
              cursor: 'pointer',
              transition: 'all 0.15s',
              fontFamily: 'var(--font-mono)',
              textTransform: 'uppercase',
              letterSpacing: '0.04em',
            }}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* Empty state */}
      {(!data?.trades?.length) ? (
        <div className="arcis-card" style={{ padding: 32, textAlign: 'center', color: 'var(--arcis-text-muted)', fontSize: 13 }}>
          No closed trades for this strategy yet.
        </div>
      ) : (
        <>
          {/* KPI Cards */}
          {kpis && (
            <div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
                <MetricCard label="Total Trades" value={kpis.totalTrades} />
                <MetricCard label="Win Rate" value={kpis.winRate} suffix="%" />
                <MetricCard label="Profit Factor" value={kpis.profitFactor} />
                <MetricCard label="Avg Hold" value={kpis.avgHold} suffix="d" />
              </div>
              {data?._meta != null && (
                <TooltipComponent content={data._meta.label}>
                  <div
                    data-testid="strategy-meta-badge"
                    style={{ fontSize: 10, fontStyle: 'italic', color: 'var(--arcis-text-muted)', marginTop: 6 }}
                  >
                    {`n=${data._meta.n} · ${data._meta.cohort.split('.').pop()}`}
                  </div>
                </TooltipComponent>
              )}
            </div>
          )}

          {/* Equity Curve */}
          <div className="arcis-card" style={{ padding: '14px 16px' }}>
            <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 500, color: 'var(--arcis-text-secondary)', marginBottom: 8 }}>
              {strategyLabel} Equity Curve
            </div>
            {equityData.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={equityData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--arcis-border)" />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} tickLine={false} axisLine={false} tickFormatter={v => `$${v}`} />
                  <Tooltip
                    contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', borderRadius: 6, fontSize: 12 }}
                    labelStyle={{ color: 'var(--arcis-text-secondary)', fontSize: 11 }}
                    formatter={(val) => [`$${Number(val).toFixed(2)}`, 'Cumulative P&L']}
                  />
                  <Line type="monotone" dataKey="cumulative_pnl" stroke="var(--arcis-accent)" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div style={{ padding: 24, textAlign: 'center', color: 'var(--arcis-text-muted)', fontSize: 13 }}>
                No equity data available
              </div>
            )}
          </div>

          {/* Score Band Bar Chart */}
          <div className="arcis-card" style={{ padding: '14px 16px' }}>
            <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 500, color: 'var(--arcis-text-secondary)', marginBottom: 8 }}>
              Win Rate by Score Band
            </div>
            {scoreBandData.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={scoreBandData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--arcis-border)" />
                  <XAxis dataKey="band" tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} tickLine={false} axisLine={false} tickFormatter={v => `${v}%`} domain={[0, 100]} />
                  <Tooltip
                    contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', borderRadius: 6, fontSize: 12 }}
                    formatter={(val, name) => {
                      if (name === 'win_rate') return [`${Number(val).toFixed(1)}%`, 'Win Rate']
                      return [val, name]
                    }}
                  />
                  <Bar dataKey="win_rate" radius={[3, 3, 0, 0]}>
                    {scoreBandData.map((_, i) => (
                      <Cell key={i} fill={BAND_COLORS[i]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div style={{ padding: 24, textAlign: 'center', color: 'var(--arcis-text-muted)', fontSize: 13 }}>
                No score band data available
              </div>
            )}
          </div>

          {/* Regime Performance Table */}
          <div className="arcis-card" style={{ padding: '14px 16px', overflowX: 'auto' }}>
            <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 500, color: 'var(--arcis-text-secondary)', marginBottom: 8 }}>
              Performance by Regime
            </div>
            {data.by_regime && Object.keys(data.by_regime).length > 0 ? (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                    {['Regime', 'Trades', 'Win Rate', 'Avg P&L %'].map(h => (
                      <th key={h} style={{
                        padding: '6px 8px',
                        textAlign: h === 'Regime' ? 'left' : 'right',
                        fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.04em',
                        color: 'var(--arcis-text-secondary)', fontWeight: 500,
                      }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.by_regime).map(([regime, stats]) => (
                    <tr key={regime} style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                      <td style={{ padding: '6px 8px', ...MONO, textTransform: 'uppercase' }}>{regime}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', ...MONO }}>{stats.trades}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', ...MONO }}>{(stats.win_rate * 100).toFixed(1)}%</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right' }}><PnlValue value={stats.avg_pnl} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div style={{ padding: 16, textAlign: 'center', color: 'var(--arcis-text-muted)', fontSize: 13 }}>
                No regime data available
              </div>
            )}
          </div>

          {/* Hold Period Histogram */}
          <div className="arcis-card" style={{ padding: '14px 16px' }}>
            <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 500, color: 'var(--arcis-text-secondary)', marginBottom: 8 }}>
              Hold Period Distribution (Days)
            </div>
            {data.hold_distribution?.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={data.hold_distribution}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--arcis-border)" />
                  <XAxis dataKey="days" tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} tickLine={false} label={{ value: 'Days', position: 'insideBottom', offset: -2, fontSize: 10, fill: 'var(--arcis-text-secondary)' }} />
                  <YAxis tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} tickLine={false} axisLine={false} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', borderRadius: 6, fontSize: 12 }}
                    formatter={(val) => [val, 'Trades']}
                    labelFormatter={(l) => `${l} days`}
                  />
                  <Bar dataKey="count" fill="var(--arcis-accent)" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div style={{ padding: 24, textAlign: 'center', color: 'var(--arcis-text-muted)', fontSize: 13 }}>
                No hold period data available
              </div>
            )}
          </div>

          {/* Drawdown Profile w/ per-trade win/loss overlay (DB-2 Task 6).
              Same x-axis (trade number), dual display. Win/loss magnitudes
              sit above (green) / below (red) the zero line, drawdown area
              reads from the bottom. Answers: are wins getting bigger and
              losses getting smaller over time? */}
          <div className="arcis-card" style={{ padding: '14px 16px' }}>
            <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 500, color: 'var(--arcis-text-secondary)', marginBottom: 8 }}>
              Drawdown Profile + Trade Magnitudes
            </div>
            {data.drawdown_series?.length > 0 ? (
              (() => {
                const ddByNum = new Map()
                for (const d of (data.drawdown_series || [])) ddByNum.set(d.trade_num, d)
                const pnlSeries = (data.trades || [])
                  .slice()
                  .sort((a, b) => (a.actual_exit_time || '').localeCompare(b.actual_exit_time || ''))
                  .map((t, i) => ({ trade_num: i + 1, pnl_pct: t.pnl_pct }))
                const composed = pnlSeries.map((p) => ({
                  ...p,
                  drawdown_pct: -(ddByNum.get(p.trade_num)?.drawdown_pct ?? 0),
                  win_pct: (p.pnl_pct || 0) > 0 ? p.pnl_pct : null,
                  loss_pct: (p.pnl_pct || 0) < 0 ? p.pnl_pct : null,
                }))
                const series = composed.length > 0 ? composed : data.drawdown_series.map(d => ({ ...d, drawdown_pct: -d.drawdown_pct }))
                return (
                  <ResponsiveContainer width="100%" height={260}>
                    <ComposedChart data={series}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--arcis-border)" />
                      <XAxis dataKey="trade_num" tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} tickLine={false} label={{ value: 'Trade #', position: 'insideBottom', offset: -2, fontSize: 10, fill: 'var(--arcis-text-secondary)' }} />
                      <YAxis tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} tickLine={false} axisLine={false} tickFormatter={v => `${v}%`} />
                      <Tooltip
                        contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', borderRadius: 6, fontSize: 12 }}
                        formatter={(val, name) => {
                          if (val == null) return ['--', name]
                          if (name === 'drawdown_pct') return [`${Math.abs(Number(val)).toFixed(1)}%`, 'Drawdown']
                          if (name === 'win_pct') return [`+${Number(val).toFixed(1)}%`, 'Win']
                          if (name === 'loss_pct') return [`${Number(val).toFixed(1)}%`, 'Loss']
                          return [val, name]
                        }}
                        labelFormatter={(l) => `Trade #${l}`}
                      />
                      <Area type="monotone" dataKey="drawdown_pct" stroke="var(--arcis-danger)" fill="var(--arcis-danger)" fillOpacity={0.15} strokeWidth={1.5} />
                      <Bar dataKey="win_pct" fill="var(--arcis-success)" barSize={6} />
                      <Bar dataKey="loss_pct" fill="var(--arcis-danger)" barSize={6} />
                    </ComposedChart>
                  </ResponsiveContainer>
                )
              })()
            ) : (
              <div style={{ padding: 24, textAlign: 'center', color: 'var(--arcis-text-muted)', fontSize: 13 }}>
                No drawdown data available
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
