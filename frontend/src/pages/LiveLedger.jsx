import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import MetricCard from '../components/MetricCard'
import Tooltip from '../components/Tooltip'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'
import { TrendingUp, ChevronDown, ChevronRight, Search, ArrowUpDown } from 'lucide-react'
import {
  XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer, Area, AreaChart,
  BarChart, Bar, Cell, CartesianGrid, ReferenceLine,
} from 'recharts'

// ── Shared helpers ───────────────────────────────────────────────────

function TickerLogo({ ticker }) {
  const [failed, setFailed] = useState(false)
  const symbol = (ticker || '').toUpperCase()
  if (!symbol) return null
  if (failed) {
    return (
      <div className="shrink-0 rounded flex items-center justify-center text-xs font-bold"
        style={{ width: 20, height: 20, background: 'var(--arcis-bg-elevated)', color: 'var(--arcis-text-secondary)', fontSize: '0.6rem' }}>
        {symbol[0]}
      </div>
    )
  }
  return (
    <img src={`https://logos.stockanalysis.com/${symbol.toLowerCase().replace('.', '-')}.svg`} alt="" className="shrink-0 rounded"
      style={{ width: 20, height: 20, objectFit: 'contain' }} onError={() => setFailed(true)} loading="lazy" />
  )
}

function PnlValue({ value, showArrow = true }) {
  if (value == null) return <span style={{ color: 'var(--arcis-text-muted)' }}>--</span>
  const isPos = value >= 0
  return (
    <span className="financial-data" style={{ color: isPos ? 'var(--arcis-success)' : 'var(--arcis-danger)' }}>
      {showArrow && (isPos ? '\u25B2 ' : '\u25BC ')}${Math.abs(value).toFixed(2)}
    </span>
  )
}

function PnlPctValue({ value }) {
  if (value == null) return <span style={{ color: 'var(--arcis-text-muted)' }}>--</span>
  const isPos = value >= 0
  return (
    <span className="financial-data" style={{ color: isPos ? 'var(--arcis-success)' : 'var(--arcis-danger)' }}>
      {isPos ? '+' : ''}{value.toFixed(2)}%
    </span>
  )
}

function DirectionBadge({ direction }) {
  const isLong = (direction || '').toUpperCase() === 'LONG'
  return (
    <span className="px-1.5 py-0.5 rounded text-xs font-medium" style={{
      background: isLong ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
      color: isLong ? 'var(--arcis-success)' : 'var(--arcis-danger)',
      border: `1px solid ${isLong ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
    }}>
      {isLong ? 'LONG' : 'SHORT'}
    </span>
  )
}

// ── Expandable trade row ─────────────────────────────────────────────

function TradeDetail({ trade }) {
  const fields = [
    { label: 'Entry', value: trade.entry_price, fmt: v => `$${v.toFixed(2)}` },
    { label: 'Exit', value: trade.actual_exit_price, fmt: v => `$${v.toFixed(2)}` },
    { label: 'Stop', value: trade.stop_price, fmt: v => `$${v.toFixed(2)}`, color: 'var(--arcis-danger)' },
    { label: 'Target', value: trade.target_1, fmt: v => `$${v.toFixed(2)}`, color: 'var(--arcis-success)' },
    { label: 'Direction', value: trade.direction, fmt: v => v },
    { label: 'Shares', value: trade.planned_shares || trade.shares, fmt: v => `${v}` },
    { label: 'Allocation', value: trade.planned_allocation, fmt: v => `$${v.toFixed(0)}` },
    { label: 'Exit Reason', value: trade.exit_reason, fmt: v => v },
    { label: 'Duration', value: trade.duration_days, fmt: v => `${v} days` },
    { label: 'P&L $', value: trade.pnl_dollars, fmt: v => `$${v.toFixed(2)}`,
      color: trade.pnl_dollars != null ? ((trade.pnl_dollars || 0) >= 0 ? 'var(--arcis-success)' : 'var(--arcis-danger)') : undefined },
    { label: 'P&L %', value: trade.pnl_pct, fmt: v => `${v.toFixed(2)}%`,
      color: trade.pnl_pct != null ? ((trade.pnl_pct || 0) >= 0 ? 'var(--arcis-success)' : 'var(--arcis-danger)') : undefined },
  ].filter(f => f.value != null)

  return (
    <div className="grid grid-cols-3 md:grid-cols-5 gap-x-4 gap-y-2 text-xs p-3 rounded-lg" style={{ background: 'var(--arcis-bg-primary)' }}>
      {fields.map(f => (
        <div key={f.label}>
          <span style={{ color: 'var(--arcis-text-muted)' }}>{f.label}: </span>
          <span className="financial-data" style={{ color: f.color || 'var(--arcis-text-primary)' }}>{f.fmt(f.value)}</span>
        </div>
      ))}
    </div>
  )
}

function ExpandableTradeRow({ trade, columns, rowIndex }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <>
      <tr
        onClick={() => setExpanded(!expanded)}
        className="cursor-pointer transition-colors"
        style={{ borderBottom: '1px solid var(--arcis-border)', background: rowIndex % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)' }}
        onMouseEnter={e => e.currentTarget.style.background = 'rgba(59,130,246,0.05)'}
        onMouseLeave={e => e.currentTarget.style.background = rowIndex % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)'}
      >
        <td className="py-2.5 px-2 w-6">
          {expanded ? <ChevronDown size={12} style={{ color: 'var(--arcis-accent)' }} /> : <ChevronRight size={12} style={{ color: 'var(--arcis-text-muted)' }} />}
        </td>
        {columns.map(col => (
          <td key={col.key} className={`py-2.5 px-2 text-sm ${col.hideOnMobile ? 'hidden md:table-cell' : ''}`}
            style={{ fontFamily: col.type !== 'text' ? 'var(--font-mono)' : undefined, color: 'var(--arcis-text-primary)' }}>
            {col.render ? col.render(trade) :
              col.type === 'currency' ? `$${(trade[col.key] || 0).toFixed(2)}`
              : col.type === 'percent' ? `${(trade[col.key] || 0).toFixed(2)}%`
              : trade[col.key] ?? '--'}
          </td>
        ))}
      </tr>
      {expanded && (
        <tr style={{ background: 'var(--arcis-bg-surface)' }}>
          <td colSpan={columns.length + 1} className="px-3 py-3">
            <TradeDetail trade={trade} />
          </td>
        </tr>
      )}
    </>
  )
}

// ── Sort + filter ────────────────────────────────────────────────────

const SORT_OPTIONS = [
  { key: 'pnl_pct', label: 'P&L %' },
  { key: 'pnl_dollars', label: 'P&L $' },
  { key: 'ticker', label: 'Ticker' },
  { key: 'duration_days', label: 'Days held' },
  { key: 'entry_price', label: 'Entry price' },
]

function sortTrades(trades, sortKey, sortDir) {
  return [...trades].sort((a, b) => {
    let va = a[sortKey], vb = b[sortKey]
    if (va == null) va = sortKey === 'ticker' ? '' : -Infinity
    if (vb == null) vb = sortKey === 'ticker' ? '' : -Infinity
    if (typeof va === 'string') return sortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va)
    return sortDir === 'asc' ? va - vb : vb - va
  })
}

// ── Main component ───────────────────────────────────────────────────

export default function LiveLedger() {
  const [tab, setTab] = useState('open')
  const [vizTab, setVizTab] = useState('equity')
  const [filter, setFilter] = useState('')
  const [sortKey, setSortKey] = useState('pnl_pct')
  const [sortDir, setSortDir] = useState('desc')

  const { data: summary, isLoading: sumLoading } = useQuery({
    queryKey: ['live-summary'], queryFn: api.getLiveSummary, refetchInterval: 60000,
  })
  const { data: trades, isLoading: tradesLoading } = useQuery({
    queryKey: ['live-trades'], queryFn: api.getLiveTrades, refetchInterval: 60000,
  })

  const isLoading = sumLoading || tradesLoading

  const openTrades = useMemo(() => {
    let t = trades?.open || []
    if (filter) t = t.filter(tr => (tr.ticker || '').toLowerCase().includes(filter.toLowerCase()))
    return sortTrades(t, sortKey, sortDir)
  }, [trades, filter, sortKey, sortDir])

  const closedTrades = useMemo(() => {
    let t = trades?.closed || []
    if (filter) t = t.filter(tr => (tr.ticker || '').toLowerCase().includes(filter.toLowerCase()))
    return sortTrades(t, sortKey, sortDir)
  }, [trades, filter, sortKey, sortDir])

  const startingCapital = summary?.starting_capital || 100
  const equity = summary?.current_equity || startingCapital
  const pnl = summary?.total_pnl || 0
  const winRate = summary?.win_rate

  const toggleSort = (key) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  // Equity curve
  const equityCurve = useMemo(() => {
    return closedTrades.slice().reverse().reduce((acc, t) => {
      const prev = acc.length > 0 ? acc[acc.length - 1].equity : startingCapital
      acc.push({
        date: (t.actual_exit_time || t.created_at || '').slice(5, 10),
        equity: Math.round((prev + (t.pnl_dollars || 0)) * 100) / 100,
      })
      return acc
    }, [])
  }, [closedTrades, startingCapital])

  // Distribution
  const pnlPcts = closedTrades.map(t => t.pnl_pct || 0)
  const distBins = useMemo(() => {
    if (pnlPcts.length === 0) return []
    const min = Math.floor(Math.min(...pnlPcts))
    const max = Math.ceil(Math.max(...pnlPcts))
    const binSize = Math.max(1, Math.ceil((max - min) / 10))
    const bins = []
    for (let b = min; b <= max; b += binSize) {
      const count = pnlPcts.filter(p => p >= b && p < b + binSize).length
      bins.push({ range: `${b}%`, count, isPositive: b >= 0 })
    }
    return bins
  }, [pnlPcts])

  // Column definitions
  const openCols = [
    { key: 'ticker', label: 'Ticker', type: 'text',
      render: (t) => <span className="flex items-center gap-1.5 font-medium"><TickerLogo ticker={t.ticker} />{t.ticker}</span> },
    { key: 'direction', label: 'Dir', type: 'text',
      render: (t) => t.direction ? <DirectionBadge direction={t.direction} /> : '--' },
    { key: 'entry_price', label: 'Entry', type: 'currency', hideOnMobile: true },
    { key: 'current_price', label: 'Current', type: 'currency', hideOnMobile: true },
    { key: 'pnl_dollars', label: 'P&L', type: 'currency',
      render: (t) => <PnlValue value={t.pnl_dollars} /> },
    { key: 'pnl_pct', label: 'P&L %', type: 'percent',
      render: (t) => <PnlPctValue value={t.pnl_pct} /> },
    { key: 'duration_days', label: 'Days', type: 'number',
      render: (t) => <span className="financial-data">{t.duration_days ?? '--'}</span> },
    { key: 'stop_price', label: 'Stop', type: 'currency', hideOnMobile: true },
  ]

  const closedCols = [
    { key: 'ticker', label: 'Ticker', type: 'text',
      render: (t) => <span className="flex items-center gap-1.5 font-medium"><TickerLogo ticker={t.ticker} />{t.ticker}</span> },
    { key: 'direction', label: 'Dir', type: 'text',
      render: (t) => t.direction ? <DirectionBadge direction={t.direction} /> : '--' },
    { key: 'entry_price', label: 'Entry', type: 'currency', hideOnMobile: true },
    { key: 'actual_exit_price', label: 'Exit', type: 'currency', hideOnMobile: true },
    { key: 'pnl_dollars', label: 'P&L', type: 'currency',
      render: (t) => <PnlValue value={t.pnl_dollars} /> },
    { key: 'pnl_pct', label: 'P&L %', type: 'percent',
      render: (t) => <PnlPctValue value={t.pnl_pct} /> },
    { key: 'exit_reason', label: 'Exit', type: 'text', hideOnMobile: true },
  ]

  const currentCols = tab === 'open' ? openCols : closedCols
  const currentTrades = tab === 'open' ? openTrades : closedTrades
  const totalPnl = currentTrades.reduce((s, t) => s + (t.pnl_dollars || 0), 0)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)' }}>Live Ledger</h2>
        <Tooltip content="Syncs Alpaca live positions with the local database. Run locally: python -m src.main reconcile-live">
          <button disabled className="px-3 py-1.5 text-xs rounded opacity-50 cursor-not-allowed"
            style={{ background: 'var(--arcis-border)', color: 'var(--arcis-text-secondary)' }}>
            Reconcile (CLI only)
          </button>
        </Tooltip>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard label="Live Equity" value={equity.toFixed(2)} prefix="$" delta={pnl} />
        <MetricCard label="Open Positions" value={summary?.open_positions || openTrades.length} />
        <MetricCard label="Total P&L" value={`${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}`} prefix="$"
          delta={summary?.total_pnl_pct != null ? `${summary.total_pnl_pct.toFixed(1)}%` : null} />
        <MetricCard label="Win Rate" value={winRate != null ? `${(winRate * 100).toFixed(1)}%` : '--'} />
      </div>

      {/* Tab bar + controls */}
      <div className="flex flex-col md:flex-row md:items-center gap-3" style={{ borderBottom: '1px solid var(--arcis-border)', paddingBottom: '12px' }}>
        <div className="flex gap-1">
          {['open', 'closed'].map(t => (
            <button key={t} onClick={() => setTab(t)}
              className="px-4 py-2 text-sm capitalize transition-colors"
              style={{
                color: tab === t ? 'var(--arcis-text-primary)' : 'var(--arcis-text-secondary)',
                borderBottom: tab === t ? '2px solid var(--arcis-accent)' : '2px solid transparent',
              }}>
              {t} ({t === 'open' ? openTrades.length : closedTrades.length})
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 md:ml-auto">
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: 'var(--arcis-text-muted)' }} />
            <input type="text" value={filter} onChange={e => setFilter(e.target.value)}
              placeholder="Filter ticker..." className="pl-8 pr-3 py-1.5 text-xs rounded-lg"
              style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-primary)', outline: 'none', width: 180 }} />
          </div>
          <div className="relative">
            <select value={sortKey} onChange={e => setSortKey(e.target.value)}
              className="pl-2 pr-7 py-1.5 text-xs rounded-lg appearance-none"
              style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-primary)', outline: 'none' }}>
              {SORT_OPTIONS.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
            </select>
            <ArrowUpDown size={12} className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: 'var(--arcis-text-muted)' }} />
          </div>
          <button onClick={() => setSortDir(d => d === 'asc' ? 'desc' : 'asc')}
            className="px-2 py-1.5 text-xs rounded-lg"
            style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-secondary)' }}>
            {sortDir === 'asc' ? '\u2191' : '\u2193'}
          </button>
        </div>
      </div>

      {/* Trade table */}
      <div className="rounded-lg overflow-hidden" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
        {isLoading ? <div className="p-8"><LoadingSpinner /></div> :
         !currentTrades.length ? <div className="p-8"><EmptyState message={`No ${tab} live trades${filter ? ' matching filter' : ''}`} icon={TrendingUp} /></div> :
         <>
           <div className="flex flex-wrap items-center gap-4 px-3 py-2.5 text-xs" style={{ background: 'var(--arcis-bg-elevated)', borderBottom: '2px solid var(--arcis-border)' }}>
             <span style={{ color: 'var(--arcis-text-secondary)' }}>{currentTrades.length} position{currentTrades.length !== 1 ? 's' : ''}</span>
             <span style={{ color: 'var(--arcis-text-secondary)' }}>P&L: <PnlValue value={totalPnl} /></span>
           </div>
           <div className="overflow-x-auto">
             <table className="w-full text-sm" style={{ tableLayout: 'auto' }}>
               <thead>
                 <tr style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                   <th className="py-2 px-2 w-6"></th>
                   {currentCols.map(col => (
                     <th key={col.key}
                       className={`py-2 px-2 text-left text-xs uppercase cursor-pointer select-none ${col.hideOnMobile ? 'hidden md:table-cell' : ''}`}
                       style={{ color: sortKey === col.key ? 'var(--arcis-accent)' : 'var(--arcis-text-secondary)' }}
                       onClick={() => toggleSort(col.key)}>
                       {col.label}
                       {sortKey === col.key && <span className="ml-1">{sortDir === 'asc' ? '\u2191' : '\u2193'}</span>}
                     </th>
                   ))}
                 </tr>
               </thead>
               <tbody>
                 {currentTrades.map((t, i) => (
                   <ExpandableTradeRow key={t.trade_id || i} trade={t} columns={currentCols} rowIndex={i} />
                 ))}
               </tbody>
             </table>
           </div>
         </>}
      </div>

      {/* Visualizations for closed trades */}
      {tab === 'closed' && closedTrades.length > 0 && (
        <div className="rounded-lg p-4" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
          <div className="flex gap-2 mb-4" style={{ borderBottom: '1px solid var(--arcis-border)' }}>
            {[
              { key: 'equity', label: 'Equity Curve' },
              { key: 'distribution', label: 'Distribution' },
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
          {vizTab === 'equity' && equityCurve.length > 0 && (
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={equityCurve}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--arcis-border)" />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--arcis-text-secondary)' }} />
                <YAxis tick={{ fontSize: 11, fill: 'var(--arcis-text-secondary)' }} />
                <RTooltip contentStyle={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 8, fontSize: 12 }} />
                <ReferenceLine y={startingCapital} stroke="var(--arcis-text-muted)" strokeDasharray="3 3" />
                <Area type="monotone" dataKey="equity" stroke="var(--arcis-accent)" fill="var(--arcis-accent)" fillOpacity={0.25} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          )}
          {vizTab === 'distribution' && distBins.length > 0 && (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={distBins}>
                <XAxis dataKey="range" tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} />
                <YAxis tick={{ fontSize: 11, fill: 'var(--arcis-text-secondary)' }} allowDecimals={false} />
                <RTooltip contentStyle={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {distBins.map((entry, i) => (
                    <Cell key={i} fill={entry.isPositive ? 'var(--arcis-success)' : 'var(--arcis-danger)'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      )}
    </div>
  )
}
