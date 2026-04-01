import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import MetricCard from '../components/MetricCard'
import DataTable from '../components/DataTable'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'
import Tooltip from '../components/Tooltip'
import { TrendingUp, ChevronDown, ChevronRight } from 'lucide-react'
import {
  XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer, Area, AreaChart,
  BarChart, Bar, Cell, CartesianGrid, ReferenceLine,
} from 'recharts'

function computeRMultiple(trade) {
  if (!trade.entry_price || !trade.stop_price || !trade.pnl_pct) return null
  const riskPct = Math.abs(trade.entry_price - trade.stop_price) / trade.entry_price * 100
  if (riskPct === 0) return null
  return trade.pnl_pct / riskPct
}

function computeIsCapture(trade) {
  if (!trade.entry_price || !trade.target_1 || !trade.actual_exit_price) return null
  const totalRange = Math.abs(trade.target_1 - trade.entry_price)
  if (totalRange === 0) return null
  const captured = trade.actual_exit_price - trade.entry_price
  return (captured / totalRange) * 100
}

function PnlValue({ value, showArrow = true }) {
  if (value == null) return <span>--</span>
  const isPos = value >= 0
  return (
    <span className="financial-data" style={{ color: isPos ? 'var(--arcis-success)' : 'var(--arcis-danger)' }}>
      {showArrow && (isPos ? '\u25B2 ' : '\u25BC ')}${Math.abs(value).toFixed(2)}
    </span>
  )
}

function PnlPctValue({ value }) {
  if (value == null) return <span>--</span>
  const isPos = value >= 0
  return (
    <span className="financial-data" style={{ color: isPos ? 'var(--arcis-success)' : 'var(--arcis-danger)' }}>
      {isPos ? '\u25B2 ' : '\u25BC '}{Math.abs(value).toFixed(2)}%
    </span>
  )
}

function TradeDetail({ trade }) {
  const rMultiple = computeRMultiple(trade)
  const isCapture = computeIsCapture(trade)

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs p-3 rounded-lg" style={{ background: 'var(--arcis-bg-primary)' }}>
      <div>
        <span style={{ color: 'var(--arcis-text-muted)' }}>Entry: </span>
        <span className="financial-data">${trade.entry_price?.toFixed(2)}</span>
      </div>
      {trade.actual_exit_price != null && (
        <div>
          <span style={{ color: 'var(--arcis-text-muted)' }}>Exit: </span>
          <span className="financial-data">${trade.actual_exit_price?.toFixed(2)}</span>
        </div>
      )}
      {trade.setup_confidence != null && (
        <div>
          <span style={{ color: 'var(--arcis-text-muted)' }}>Conviction: </span>
          <span className="financial-data">{(trade.setup_confidence * 100).toFixed(0)}%</span>
        </div>
      )}
      {trade.setup_type && (
        <div>
          <span style={{ color: 'var(--arcis-text-muted)' }}>Setup: </span>
          <span>{trade.setup_type}</span>
        </div>
      )}
      {trade.sector && (
        <div>
          <span style={{ color: 'var(--arcis-text-muted)' }}>Sector: </span>
          <span>{trade.sector}</span>
        </div>
      )}
      {trade.planned_shares != null && (
        <div>
          <span style={{ color: 'var(--arcis-text-muted)' }}>Shares: </span>
          <span className="financial-data">{trade.planned_shares}</span>
        </div>
      )}
      {trade.planned_allocation != null && (
        <div>
          <span style={{ color: 'var(--arcis-text-muted)' }}>Allocation: </span>
          <span className="financial-data">${trade.planned_allocation?.toFixed(0)}</span>
        </div>
      )}
      {trade.mfe_dollars != null && (
        <div>
          <span style={{ color: 'var(--arcis-text-muted)' }}>MFE: </span>
          <span className="financial-data" style={{ color: 'var(--arcis-success)' }}>${trade.mfe_dollars?.toFixed(2)}</span>
        </div>
      )}
      {trade.mae_dollars != null && (
        <div>
          <span style={{ color: 'var(--arcis-text-muted)' }}>MAE: </span>
          <span className="financial-data" style={{ color: 'var(--arcis-danger)' }}>${trade.mae_dollars?.toFixed(2)}</span>
        </div>
      )}
      {trade.exit_reason && (
        <div>
          <span style={{ color: 'var(--arcis-text-muted)' }}>Exit: </span>
          <span>{trade.exit_reason}</span>
        </div>
      )}
      {trade.entry_slippage_pct != null && (
        <div>
          <span style={{ color: 'var(--arcis-text-muted)' }}>Entry Slippage: </span>
          <span className="financial-data" style={{ color: Math.abs(trade.entry_slippage_pct) > 0.1 ? 'var(--arcis-warning)' : 'var(--arcis-text-primary)' }}>
            {trade.entry_slippage_pct?.toFixed(3)}%
          </span>
        </div>
      )}
      {trade.entry_slippage_bps != null && (
        <div>
          <span style={{ color: 'var(--arcis-text-muted)' }}>Slippage (bps): </span>
          <span className="financial-data">{trade.entry_slippage_bps?.toFixed(1)}</span>
        </div>
      )}
      {rMultiple != null && (
        <div>
          <Tooltip content="Profit/loss relative to initial risk (entry-to-stop distance). >1R = good trade management.">
            <span style={{ color: 'var(--arcis-text-muted)' }}>R-Multiple: </span>
          </Tooltip>
          <span className="financial-data" style={{ color: rMultiple >= 1 ? 'var(--arcis-success)' : rMultiple >= 0 ? 'var(--arcis-text-primary)' : 'var(--arcis-danger)' }}>
            {rMultiple.toFixed(2)}R
          </span>
        </div>
      )}
      {isCapture != null && (
        <div>
          <Tooltip content="Percentage of the entry-to-target range captured. >100% means exceeded target.">
            <span style={{ color: 'var(--arcis-text-muted)' }}>IS Capture: </span>
          </Tooltip>
          <span className="financial-data" style={{ color: isCapture >= 50 ? 'var(--arcis-success)' : isCapture >= 0 ? 'var(--arcis-text-primary)' : 'var(--arcis-danger)' }}>
            {isCapture.toFixed(1)}%
          </span>
        </div>
      )}
    </div>
  )
}

function ExpandableTradeRow({ trade, columns, rowIndex }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <>
      <tr
        onClick={() => setExpanded(!expanded)}
        className="cursor-pointer hover:opacity-80 transition-opacity"
        style={{
          borderBottom: '1px solid var(--arcis-border)',
          background: rowIndex % 2 === 0 ? 'transparent' : 'var(--arcis-bg-elevated)',
        }}
      >
        <td className="py-2 px-2">
          {expanded ? <ChevronDown size={12} style={{ color: 'var(--arcis-text-muted)' }} /> : <ChevronRight size={12} style={{ color: 'var(--arcis-text-muted)' }} />}
        </td>
        {columns.map(col => (
          <td key={col.key} className={`py-2 px-2 text-sm ${col.hideOnMobile ? 'hidden md:table-cell' : ''}`} style={{
            fontFamily: col.type !== 'text' ? 'var(--font-mono)' : undefined,
            color: col.key === 'pnl_dollars' || col.key === 'pnl_pct'
              ? ((trade[col.key] || 0) >= 0 ? 'var(--arcis-success)' : 'var(--arcis-danger)')
              : col.key === 'r_multiple'
              ? ((trade._rMultiple || 0) >= 1 ? 'var(--arcis-success)' : (trade._rMultiple || 0) >= 0 ? 'var(--arcis-text-primary)' : 'var(--arcis-danger)')
              : 'var(--arcis-text-primary)',
          }}>
            {col.render ? col.render(trade) :
              col.type === 'currency' ? `$${(trade[col.key] || 0).toFixed(2)}`
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

function SummaryRow({ trades, type }) {
  const totalPnl = trades.reduce((sum, t) => sum + (t.pnl_dollars || 0), 0)
  const avgDays = trades.length > 0
    ? (trades.reduce((sum, t) => sum + (t.duration_days || 0), 0) / trades.length).toFixed(1)
    : '0'
  return (
    <div className="flex flex-wrap gap-4 px-3 py-2 text-sm rounded-t-lg" style={{ background: 'var(--arcis-bg-elevated)', borderBottom: '2px solid var(--arcis-border)' }}>
      <span style={{ color: 'var(--arcis-text-secondary)' }}>
        {trades.length} position{trades.length !== 1 ? 's' : ''}
      </span>
      <span style={{ color: 'var(--arcis-text-secondary)' }}>
        Total P&L: <PnlValue value={totalPnl} />
      </span>
      <span style={{ color: 'var(--arcis-text-secondary)' }}>
        Avg days: <span className="financial-data">{avgDays}</span>
      </span>
    </div>
  )
}

function EquityCurveTab({ trades, startingCapital = 100000 }) {
  const data = useMemo(() => {
    const sorted = [...trades].reverse()
    let running = startingCapital
    return sorted.map(t => {
      running += (t.pnl_dollars || 0)
      return { date: (t.actual_exit_time || t.created_at || '').slice(5, 10), equity: Math.round(running) }
    })
  }, [trades, startingCapital])

  if (data.length === 0) return <EmptyState message="No closed trades for equity curve" />

  return (
    <ResponsiveContainer width="100%" height={300}>
      <AreaChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--arcis-border)" />
        <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--arcis-text-secondary)' }} />
        <YAxis tick={{ fontSize: 11, fill: 'var(--arcis-text-secondary)' }} />
        <RTooltip contentStyle={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 8, fontSize: 12 }} />
        <ReferenceLine y={startingCapital} stroke="var(--arcis-text-muted)" strokeDasharray="3 3" />
        <Area type="monotone" dataKey="equity" stroke="var(--arcis-accent)" fill="var(--arcis-accent)" fillOpacity={0.1} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

function DistributionTab({ trades }) {
  const pnls = trades.map(t => t.pnl_pct || 0)
  if (pnls.length === 0) return <EmptyState message="No trades for distribution" />

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
          <RTooltip contentStyle={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 8, fontSize: 12 }} />
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
          <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: 'var(--arcis-text-primary)' }} width={100} />
          <RTooltip contentStyle={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 8, fontSize: 12 }} />
          <Bar dataKey="count" fill="var(--arcis-accent)" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {data.map(s => (
          <div key={s.name} className="rounded p-2 text-xs" style={{ background: 'var(--arcis-bg-elevated)' }}>
            <div className="font-medium" style={{ color: 'var(--arcis-text-primary)' }}>{s.name}</div>
            <PnlValue value={s.pnl} />
          </div>
        ))}
      </div>
    </div>
  )
}

function CalendarTab({ trades }) {
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
            background: d.pnl > 0 ? 'rgba(34,197,94,0.15)' : d.pnl < 0 ? 'rgba(239,68,68,0.15)' : 'var(--arcis-bg-elevated)',
            border: `1px solid ${d.pnl > 0 ? 'rgba(34,197,94,0.3)' : d.pnl < 0 ? 'rgba(239,68,68,0.3)' : 'var(--arcis-border)'}`,
          }}>
            <div style={{ color: 'var(--arcis-text-muted)', fontSize: '0.625rem' }}>{d.date.slice(5)}</div>
            <PnlValue value={d.pnl} showArrow={false} />
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

  const openTrades = useMemo(() => {
    const trades = openData?.open_trades || []
    return [...trades].sort((a, b) => (b.pnl_pct || 0) - (a.pnl_pct || 0))
  }, [openData])

  const openCols = [
    { key: 'ticker', label: 'Ticker', type: 'text' },
    { key: 'entry_price', label: 'Entry', type: 'currency', hideOnMobile: true },
    { key: 'current_price', label: 'Current', type: 'currency', hideOnMobile: true },
    { key: 'pnl_dollars', label: 'P&L', type: 'currency',
      render: (t) => <PnlValue value={t.pnl_dollars} /> },
    { key: 'pnl_pct', label: 'P&L %', type: 'percent',
      render: (t) => <PnlPctValue value={t.pnl_pct} /> },
    { key: 'duration_days', label: 'Days', type: 'number',
      render: (t) => t.duration_days ?? '--' },
    { key: 'setup_type', label: 'Strategy', type: 'text', hideOnMobile: true,
      render: (t) => t.setup_type ? (
        <span className="px-1.5 py-0.5 rounded text-xs" style={{ background: 'var(--arcis-bg-elevated)', color: 'var(--arcis-text-secondary)' }}>
          {t.setup_type}
        </span>
      ) : '--' },
  ]

  const closedCols = [
    { key: 'ticker', label: 'Ticker', type: 'text' },
    { key: 'entry_price', label: 'Entry', type: 'currency', hideOnMobile: true },
    { key: 'pnl_dollars', label: 'P&L', type: 'currency',
      render: (t) => <PnlValue value={t.pnl_dollars} /> },
    { key: 'pnl_pct', label: 'P&L %', type: 'percent',
      render: (t) => <PnlPctValue value={t.pnl_pct} /> },
    { key: 'duration_days', label: 'Days', type: 'number',
      render: (t) => t.duration_days ?? '--' },
    { key: 'entry_slippage_bps', label: 'Slip', type: 'number', hideOnMobile: true,
      render: (t) => t.entry_slippage_bps != null ? <span className="financial-data">{t.entry_slippage_bps.toFixed(1)}</span> : '--' },
    { key: 'r_multiple', label: 'R-Mult', type: 'number', hideOnMobile: true,
      render: (t) => { const r = computeRMultiple(t); return r != null ? <span className="financial-data">{r.toFixed(2)}R</span> : '--' } },
    { key: 'exit_reason', label: 'Exit', type: 'text', hideOnMobile: true },
  ]

  const metrics = closedData?.metrics || {}
  const closedTrades = useMemo(() => {
    const trades = closedData?.trades || []
    return [...trades].sort((a, b) => (b.pnl_pct || 0) - (a.pnl_pct || 0))
  }, [closedData])
  const equity = accountData?.equity || 100000
  const startingCapital = accountData?.starting_capital || 100000

  const closedPnls = closedTrades.map(t => t.pnl_dollars || 0)
  const wins = closedPnls.filter(p => p > 0)
  const losses = closedPnls.filter(p => p <= 0)
  const profitFactor = losses.length > 0 && Math.abs(losses.reduce((a, b) => a + b, 0)) > 0
    ? (wins.reduce((a, b) => a + b, 0) / Math.abs(losses.reduce((a, b) => a + b, 0))).toFixed(2)
    : wins.length > 0 ? '99.00' : '--'

  let running = 0, peak = 0, maxDD = 0
  for (const p of closedPnls) {
    running += p
    if (running > peak) peak = running
    const dd = peak - running
    if (dd > maxDD) maxDD = dd
  }
  const maxDDPct = startingCapital > 0 ? ((maxDD / startingCapital) * 100).toFixed(1) : '0.0'

  const slippages = closedTrades.filter(t => t.entry_slippage_bps != null).map(t => t.entry_slippage_bps)
  const avgSlippage = slippages.length > 0 ? (slippages.reduce((a, b) => a + b, 0) / slippages.length).toFixed(1) : '--'
  const rMultiples = closedTrades.map(computeRMultiple).filter(r => r != null)
  const avgR = rMultiples.length > 0 ? (rMultiples.reduce((a, b) => a + b, 0) / rMultiples.length).toFixed(2) : '--'

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)' }}>Shadow Ledger</h2>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
        <MetricCard label="Paper Equity" value={equity.toLocaleString()} prefix="$" delta={equity - startingCapital} />
        <MetricCard label="Open / Max" value={`${accountData?.open_positions || openData?.open_count || 0} / 50`} />
        <MetricCard label="Closed" value={`${closedTrades.length} / 50`} delta={closedTrades.length >= 50 ? 'Gate met' : null} />
        <MetricCard label="Win Rate" value={metrics.win_rate != null ? `${metrics.win_rate.toFixed(1)}%` : accountData?.win_rate != null ? `${(accountData.win_rate * 100).toFixed(1)}%` : '--'} />
        <MetricCard label="Profit Factor" value={profitFactor} />
        <MetricCard label="Max DD" value={`${maxDDPct}%`} />
        <Tooltip content="Average entry slippage in basis points across all closed trades">
          <MetricCard label="Avg Slip (bps)" value={avgSlippage} />
        </Tooltip>
        <Tooltip content="Average R-Multiple: P&L relative to initial risk (entry-to-stop)">
          <MetricCard label="Avg R-Mult" value={avgR !== '--' ? `${avgR}R` : '--'} />
        </Tooltip>
      </div>

      <div className="flex gap-1" style={{ borderBottom: '1px solid var(--arcis-border)' }}>
        {['open', 'closed'].map(t => (
          <button key={t} onClick={() => setTab(t)}
            className="px-4 py-2 text-sm capitalize transition-colors"
            style={{
              color: tab === t ? 'var(--arcis-text-primary)' : 'var(--arcis-text-secondary)',
              borderBottom: tab === t ? '2px solid var(--arcis-accent)' : '2px solid transparent',
            }}>
            {t} {t === 'open' ? `(${openTrades.length})` : `(${closedTrades.length})`}
          </button>
        ))}
      </div>

      {tab === 'open' ? (
        <div className="rounded-lg p-4" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
          {openLoading ? <LoadingSpinner /> :
           !openTrades.length ? <EmptyState message="No open trades" icon={TrendingUp} /> :
           <>
             <SummaryRow trades={openTrades} type="open" />
             <div className="overflow-x-auto">
               <table className="w-full text-sm" style={{ tableLayout: 'auto' }}>
                 <thead>
                   <tr style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                     <th className="py-2 px-2 w-6"></th>
                     {openCols.map(col => (
                       <th key={col.key} className={`py-2 px-2 text-left text-xs uppercase ${col.hideOnMobile ? 'hidden md:table-cell' : ''}`} style={{ color: 'var(--arcis-text-secondary)' }}>
                         {col.label}
                       </th>
                     ))}
                   </tr>
                 </thead>
                 <tbody>
                   {openTrades.map((t, i) => (
                     <ExpandableTradeRow key={t.trade_id || i} trade={t} columns={openCols} rowIndex={i} />
                   ))}
                 </tbody>
               </table>
             </div>
           </>}
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

          <div className="rounded-lg p-4" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
            {closedLoading ? <LoadingSpinner /> :
             !closedTrades.length ? <EmptyState message="No closed trades" icon={TrendingUp} /> :
             <>
               <SummaryRow trades={closedTrades} type="closed" />
               <div className="overflow-x-auto">
                 <table className="w-full text-sm" style={{ tableLayout: 'auto' }}>
                   <thead>
                     <tr style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                       <th className="py-2 px-2 w-6"></th>
                       {closedCols.map(col => (
                         <th key={col.key} className={`py-2 px-2 text-left text-xs uppercase ${col.hideOnMobile ? 'hidden md:table-cell' : ''}`} style={{ color: 'var(--arcis-text-secondary)' }}>
                           {col.label}
                         </th>
                       ))}
                     </tr>
                   </thead>
                   <tbody>
                     {closedTrades.map((t, i) => (
                       <ExpandableTradeRow key={t.trade_id || i} trade={t} columns={closedCols} rowIndex={i} />
                     ))}
                   </tbody>
                 </table>
               </div>
             </>
            }
          </div>

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
              {vizTab === 'equity' && <EquityCurveTab trades={closedTrades} startingCapital={startingCapital} />}
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
