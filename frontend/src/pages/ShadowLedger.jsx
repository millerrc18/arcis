import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import MetricCard from '../components/MetricCard'
import DataTable from '../components/DataTable'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'
import { TrendingUp, ChevronDown, ChevronRight } from 'lucide-react'
import {
  XAxis, YAxis, Tooltip, ResponsiveContainer, Area, AreaChart,
  BarChart, Bar, Cell, CartesianGrid, Line, LineChart, ReferenceLine,
} from 'recharts'

function TradeDetail({ trade }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs p-3 rounded-lg" style={{ background: 'rgba(100,116,139,0.15)' }}>
      <div>
        <span style={{ color: 'var(--arcis-text-secondary)' }}>Entry: </span>
        <span style={{ fontFamily: 'var(--font-mono)' }}>${trade.entry_price?.toFixed(2)}</span>
      </div>
      {trade.actual_exit_price != null && (
        <div>
          <span style={{ color: 'var(--arcis-text-secondary)' }}>Exit: </span>
          <span style={{ fontFamily: 'var(--font-mono)' }}>${trade.actual_exit_price?.toFixed(2)}</span>
        </div>
      )}
      {trade.setup_confidence != null && (
        <div>
          <span style={{ color: 'var(--arcis-text-secondary)' }}>Conviction: </span>
          <span style={{ fontFamily: 'var(--font-mono)' }}>{(trade.setup_confidence * 100).toFixed(0)}%</span>
        </div>
      )}
      {trade.setup_type && (
        <div>
          <span style={{ color: 'var(--arcis-text-secondary)' }}>Setup: </span>
          <span>{trade.setup_type}</span>
        </div>
      )}
      {trade.sector && (
        <div>
          <span style={{ color: 'var(--arcis-text-secondary)' }}>Sector: </span>
          <span>{trade.sector}</span>
        </div>
      )}
      {trade.planned_shares != null && (
        <div>
          <span style={{ color: 'var(--arcis-text-secondary)' }}>Shares: </span>
          <span style={{ fontFamily: 'var(--font-mono)' }}>{trade.planned_shares}</span>
        </div>
      )}
      {trade.planned_allocation != null && (
        <div>
          <span style={{ color: 'var(--arcis-text-secondary)' }}>Allocation: </span>
          <span style={{ fontFamily: 'var(--font-mono)' }}>${trade.planned_allocation?.toFixed(0)}</span>
        </div>
      )}
      {trade.mfe_dollars != null && (
        <div>
          <span style={{ color: 'var(--arcis-text-secondary)' }}>MFE: </span>
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-success)' }}>${trade.mfe_dollars?.toFixed(2)}</span>
        </div>
      )}
      {trade.mae_dollars != null && (
        <div>
          <span style={{ color: 'var(--arcis-text-secondary)' }}>MAE: </span>
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-danger)' }}>${trade.mae_dollars?.toFixed(2)}</span>
        </div>
      )}
      {trade.exit_reason && (
        <div>
          <span style={{ color: 'var(--arcis-text-secondary)' }}>Exit: </span>
          <span>{trade.exit_reason}</span>
        </div>
      )}
      {trade.entry_slippage_pct != null && (
        <div>
          <span style={{ color: 'var(--arcis-text-secondary)' }}>Slippage: </span>
          <span style={{ fontFamily: 'var(--font-mono)' }}>{trade.entry_slippage_pct?.toFixed(3)}%</span>
        </div>
      )}
    </div>
  )
}

function ExpandableTradeRow({ trade, columns }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <>
      <tr
        onClick={() => setExpanded(!expanded)}
        className="cursor-pointer hover:opacity-80 transition-opacity"
        style={{ borderBottom: '1px solid var(--arcis-border)' }}
      >
        <td className="py-2 px-2">
          {expanded ? <ChevronDown size={12} style={{ color: 'var(--arcis-text-secondary)' }} /> : <ChevronRight size={12} style={{ color: 'var(--arcis-text-secondary)' }} />}
        </td>
        {columns.map(col => (
          <td key={col.key} className="py-2 px-2 text-sm" style={{
            fontFamily: col.type !== 'text' ? 'var(--font-mono)' : undefined,
            color: col.key === 'pnl_dollars' || col.key === 'pnl_pct'
              ? ((trade[col.key] || 0) >= 0 ? 'var(--arcis-success)' : 'var(--arcis-danger)')
              : 'var(--arcis-text-primary)',
          }}>
            {col.type === 'currency' ? `$${(trade[col.key] || 0).toFixed(2)}`
              : col.type === 'percent' ? `${(trade[col.key] || 0).toFixed(2)}%`
              : trade[col.key] ?? '--'}
          </td>
        ))}
      </tr>
      {expanded && (
        <tr>
          <td colSpan={columns.length + 1} className="px-2 py-2">
            <TradeDetail trade={trade} />
          </td>
        </tr>
      )}
    </>
  )
}

function EquityCurveTab({ trades }) {
  const data = useMemo(() => {
    const sorted = [...trades].reverse()
    let running = 100000
    return sorted.map(t => {
      running += (t.pnl_dollars || 0)
      return { date: (t.actual_exit_time || t.created_at || '').slice(5, 10), equity: Math.round(running) }
    })
  }, [trades])

  if (data.length === 0) return <EmptyState message="No closed trades for equity curve" />

  return (
    <ResponsiveContainer width="100%" height={300}>
      <AreaChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--arcis-border)" />
        <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--arcis-text-secondary)' }} />
        <YAxis tick={{ fontSize: 11, fill: 'var(--arcis-text-secondary)' }} />
        <Tooltip contentStyle={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 8, fontSize: 12 }} />
        <ReferenceLine y={100000} stroke="var(--arcis-text-muted)" strokeDasharray="3 3" />
        <Area type="monotone" dataKey="equity" stroke="var(--arcis-accent)" fill="var(--arcis-accent)" fillOpacity={0.1} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

function DistributionTab({ trades }) {
  const pnls = trades.map(t => t.pnl_pct || 0)
  if (pnls.length === 0) return <EmptyState message="No trades for distribution" />

  // Histogram bins
  const min = Math.floor(Math.min(...pnls))
  const max = Math.ceil(Math.max(...pnls))
  const binSize = Math.max(1, Math.ceil((max - min) / 10))
  const bins = []
  for (let b = min; b <= max; b += binSize) {
    const count = pnls.filter(p => p >= b && p < b + binSize).length
    bins.push({ range: `${b}%`, count, isPositive: b >= 0 })
  }

  return (
    <div className="space-y-4">
      <h4 className="text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>P&L Distribution</h4>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={bins}>
          <XAxis dataKey="range" tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} />
          <YAxis tick={{ fontSize: 11, fill: 'var(--arcis-text-secondary)' }} allowDecimals={false} />
          <Tooltip contentStyle={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 8, fontSize: 12 }} />
          <Bar dataKey="count" radius={[4, 4, 0, 0]}>
            {bins.map((entry, i) => (
              <Cell key={i} fill={entry.isPositive ? 'var(--arcis-success)' : 'var(--arcis-danger)'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function SectorTab({ trades }) {
  const sectors = {}
  for (const t of trades) {
    const s = t.sector || 'Unknown'
    if (!sectors[s]) sectors[s] = { count: 0, pnl: 0 }
    sectors[s].count++
    sectors[s].pnl += (t.pnl_dollars || 0)
  }
  const data = Object.entries(sectors).map(([name, v]) => ({
    name, count: v.count, pnl: Math.round(v.pnl * 100) / 100,
  })).sort((a, b) => b.count - a.count)

  if (data.length === 0) return <EmptyState message="No sector data" />

  return (
    <div className="space-y-4">
      <h4 className="text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Sector Exposure</h4>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} layout="vertical">
          <XAxis type="number" tick={{ fontSize: 11, fill: 'var(--arcis-text-secondary)' }} />
          <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: 'var(--arcis-text-secondary)' }} width={100} />
          <Tooltip contentStyle={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 8, fontSize: 12 }} />
          <Bar dataKey="count" fill="var(--arcis-accent)" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {data.map(s => (
          <div key={s.name} className="rounded p-2 text-xs" style={{ background: 'rgba(100,116,139,0.15)' }}>
            <div className="font-medium" style={{ color: 'var(--arcis-text-primary)' }}>{s.name}</div>
            <div style={{ fontFamily: 'var(--font-mono)', color: s.pnl >= 0 ? 'var(--arcis-success)' : 'var(--arcis-danger)' }}>
              ${s.pnl.toFixed(2)}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function CalendarTab({ trades }) {
  // Group by date
  const byDate = {}
  for (const t of trades) {
    const d = (t.actual_exit_time || t.created_at || '').slice(0, 10)
    if (!d) continue
    if (!byDate[d]) byDate[d] = 0
    byDate[d] += (t.pnl_dollars || 0)
  }
  const dates = Object.entries(byDate).sort().map(([date, pnl]) => ({ date, pnl: Math.round(pnl * 100) / 100 }))

  if (dates.length === 0) return <EmptyState message="No calendar data" />

  return (
    <div className="space-y-2">
      <h4 className="text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Daily P&L</h4>
      <div className="grid grid-cols-7 gap-1">
        {dates.map(d => (
          <div key={d.date} className="rounded p-2 text-center text-xs" style={{
            background: d.pnl > 0 ? 'rgba(34,197,94,0.15)' : d.pnl < 0 ? 'rgba(239,68,68,0.15)' : 'rgba(100,116,139,0.1)',
            border: `1px solid ${d.pnl > 0 ? 'rgba(34,197,94,0.3)' : d.pnl < 0 ? 'rgba(239,68,68,0.3)' : 'var(--arcis-border)'}`,
          }}>
            <div style={{ color: 'var(--arcis-text-secondary)', fontSize: '0.625rem' }}>{d.date.slice(5)}</div>
            <div style={{ fontFamily: 'var(--font-mono)', color: d.pnl >= 0 ? 'var(--arcis-success)' : 'var(--arcis-danger)' }}>
              ${d.pnl.toFixed(0)}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function ShadowLedger() {
  const [tab, setTab] = useState('open')
  const [vizTab, setVizTab] = useState('equity')
  const { data: openData, isLoading: openLoading } = useQuery({ queryKey: ['shadow-open'], queryFn: api.getOpenTrades, refetchInterval: 30000 })
  const { data: closedData, isLoading: closedLoading } = useQuery({ queryKey: ['shadow-closed'], queryFn: () => api.getClosedTrades(90), refetchInterval: 30000 })
  const { data: accountData } = useQuery({ queryKey: ['shadow-account'], queryFn: api.getAccount, refetchInterval: 60000 })

  const openCols = [
    { key: 'ticker', label: 'Ticker', type: 'text' },
    { key: 'entry_price', label: 'Entry', type: 'currency' },
    { key: 'current_price', label: 'Current', type: 'currency' },
    { key: 'pnl_dollars', label: 'P&L', type: 'currency' },
    { key: 'pnl_pct', label: 'P&L %', type: 'percent' },
    { key: 'duration_days', label: 'Days', type: 'number' },
    { key: 'stop_price', label: 'Stop', type: 'currency' },
    { key: 'target_1', label: 'Target 1', type: 'currency' },
  ]

  const closedCols = [
    { key: 'ticker', label: 'Ticker', type: 'text' },
    { key: 'entry_price', label: 'Entry', type: 'currency' },
    { key: 'pnl_dollars', label: 'P&L', type: 'currency' },
    { key: 'pnl_pct', label: 'P&L %', type: 'percent' },
    { key: 'duration_days', label: 'Days', type: 'number' },
    { key: 'exit_reason', label: 'Exit Reason', type: 'text' },
  ]

  const metrics = closedData?.metrics || {}
  const closedTrades = closedData?.trades || []
  const equity = accountData?.equity || 100000
  const startingCapital = accountData?.starting_capital || 100000

  // Compute additional metrics
  const closedPnls = closedTrades.map(t => t.pnl_dollars || 0)
  const wins = closedPnls.filter(p => p > 0)
  const losses = closedPnls.filter(p => p <= 0)
  const profitFactor = losses.length > 0 && Math.abs(losses.reduce((a, b) => a + b, 0)) > 0
    ? (wins.reduce((a, b) => a + b, 0) / Math.abs(losses.reduce((a, b) => a + b, 0))).toFixed(2)
    : wins.length > 0 ? '99.00' : '--'

  // Max drawdown
  let running = 0, peak = 0, maxDD = 0
  for (const p of closedPnls) {
    running += p
    if (running > peak) peak = running
    const dd = peak - running
    if (dd > maxDD) maxDD = dd
  }
  const maxDDPct = startingCapital > 0 ? ((maxDD / startingCapital) * 100).toFixed(1) : '0.0'

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)' }}>Shadow Ledger</h2>

      {/* F1: Enhanced metrics strip */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        <MetricCard label="Paper Equity" value={equity.toLocaleString()} prefix="$" delta={equity - startingCapital} />
        <MetricCard label="Open / Max" value={`${accountData?.open_positions || openData?.open_count || 0} / 50`} />
        <MetricCard label="Closed" value={`${closedTrades.length} / 50`} delta={closedTrades.length >= 50 ? 'Gate met' : null} />
        <MetricCard label="Win Rate" value={metrics.win_rate != null ? `${metrics.win_rate.toFixed(1)}%` : accountData?.win_rate != null ? `${(accountData.win_rate * 100).toFixed(1)}%` : '--'} />
        <MetricCard label="Profit Factor" value={profitFactor} />
        <MetricCard label="Max DD" value={`${maxDDPct}%`} />
      </div>

      {/* Tab bar */}
      <div className="flex gap-1" style={{ borderBottom: '1px solid var(--arcis-border)' }}>
        {['open', 'closed'].map(t => (
          <button key={t} onClick={() => setTab(t)}
            className="px-4 py-2 text-sm capitalize transition-colors"
            style={{
              color: tab === t ? 'var(--arcis-text-primary)' : 'var(--arcis-text-secondary)',
              borderBottom: tab === t ? '2px solid var(--arcis-accent)' : '2px solid transparent',
            }}>
            {t} {t === 'open' ? `(${openData?.open_count || 0})` : `(${closedTrades.length})`}
          </button>
        ))}
      </div>

      {tab === 'open' ? (
        <div className="rounded-lg p-4" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
          {openLoading ? <LoadingSpinner /> :
           !openData?.open_trades?.length ? <EmptyState message="No open trades" icon={TrendingUp} /> :
           <DataTable columns={openCols} data={openData.open_trades} />}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <MetricCard label="Total Trades" value={metrics.total_trades || closedTrades.length} />
            <MetricCard label="Avg Gain" value={(metrics.avg_gain || 0).toFixed(2)} prefix="$" />
            <MetricCard label="Avg Loss" value={(metrics.avg_loss || 0).toFixed(2)} prefix="$" />
            <MetricCard label="Expectancy" value={(metrics.expectancy || 0).toFixed(2)} prefix="$" delta={metrics.expectancy} />
            <MetricCard label="Total P&L" value={(metrics.total_pnl || 0).toFixed(2)} prefix="$" delta={metrics.total_pnl} />
          </div>

          {/* F2: Expandable trade rows */}
          <div className="rounded-lg p-4" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
            {closedLoading ? <LoadingSpinner /> :
             !closedTrades.length ? <EmptyState message="No closed trades" icon={TrendingUp} /> :
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                      <th className="py-2 px-2 w-6"></th>
                      {closedCols.map(col => (
                        <th key={col.key} className="py-2 px-2 text-left text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>
                          {col.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {closedTrades.map((t, i) => (
                      <ExpandableTradeRow key={t.trade_id || i} trade={t} columns={closedCols} />
                    ))}
                  </tbody>
                </table>
              </div>
            }
          </div>

          {/* F3: Visualization tabs */}
          {closedTrades.length > 0 && (
            <div className="rounded-lg p-4" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
              <div className="flex gap-2 mb-4" style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                {[
                  { key: 'equity', label: 'Equity Curve' },
                  { key: 'distribution', label: 'Distribution' },
                  { key: 'sector', label: 'Sector' },
                  { key: 'calendar', label: 'Calendar' },
                ].map(t => (
                  <button key={t.key} onClick={() => setVizTab(t.key)}
                    className="px-3 py-2 text-xs transition-colors"
                    style={{
                      color: vizTab === t.key ? 'var(--arcis-text-primary)' : 'var(--arcis-text-secondary)',
                      borderBottom: vizTab === t.key ? '2px solid var(--arcis-accent)' : '2px solid transparent',
                    }}>
                    {t.label}
                  </button>
                ))}
              </div>
              {vizTab === 'equity' && <EquityCurveTab trades={closedTrades} />}
              {vizTab === 'distribution' && <DistributionTab trades={closedTrades} />}
              {vizTab === 'sector' && <SectorTab trades={closedTrades} />}
              {vizTab === 'calendar' && <CalendarTab trades={closedTrades} />}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
