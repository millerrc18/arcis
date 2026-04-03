import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import MetricCard from '../components/MetricCard'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'
import Tooltip from '../components/Tooltip'
import { TrendingUp, ChevronDown, ChevronRight, Search, ArrowUpDown } from 'lucide-react'
import {
  XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer, Area, AreaChart,
  BarChart, Bar, Cell, CartesianGrid, ReferenceLine,
} from 'recharts'

// ── Helpers ──────────────────────────────────────────────────────────

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

const STRATEGY_COLORS = {
  pullback: { bg: 'rgba(59,130,246,0.15)', text: '#60a5fa', border: 'rgba(59,130,246,0.3)' },
  breakout: { bg: 'rgba(34,197,94,0.15)', text: '#4ade80', border: 'rgba(34,197,94,0.3)' },
  momentum: { bg: 'rgba(168,85,247,0.15)', text: '#c084fc', border: 'rgba(168,85,247,0.3)' },
  reversal: { bg: 'rgba(245,158,11,0.15)', text: '#fbbf24', border: 'rgba(245,158,11,0.3)' },
  earnings: { bg: 'rgba(236,72,153,0.15)', text: '#f472b6', border: 'rgba(236,72,153,0.3)' },
  default: { bg: 'var(--arcis-bg-elevated)', text: 'var(--arcis-text-secondary)', border: 'var(--arcis-border)' },
}

function getStrategyColor(type) {
  if (!type) return STRATEGY_COLORS.default
  const key = type.toLowerCase()
  for (const [k, v] of Object.entries(STRATEGY_COLORS)) {
    if (key.includes(k)) return v
  }
  return STRATEGY_COLORS.default
}

/** P&L with color intensity — brighter = bigger magnitude */
function pnlOpacity(value, maxAbs) {
  if (value == null || !maxAbs) return 0.6
  return Math.min(1, 0.4 + (Math.abs(value) / maxAbs) * 0.6)
}

// ── Small display components ─────────────────────────────────────────

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

function StrategyBadge({ type }) {
  if (!type) return <span style={{ color: 'var(--arcis-text-muted)' }}>--</span>
  const c = getStrategyColor(type)
  return (
    <span className="px-2 py-0.5 rounded text-xs font-medium" style={{
      background: c.bg, color: c.text, border: `1px solid ${c.border}`,
    }}>
      {type}
    </span>
  )
}

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
    <img
      src={`https://logos.stockanalysis.com/${symbol.toLowerCase().replace('.', '-')}.svg`}
      alt=""
      className="shrink-0 rounded"
      style={{ width: 20, height: 20, objectFit: 'contain' }}
      onError={() => setFailed(true)}
      loading="lazy"
    />
  )
}

function BracketIndicator({ trade }) {
  if (!trade.entry_price || !trade.stop_price) return null
  const entry = trade.entry_price
  const stop = trade.stop_price
  const target = trade.target_1
  const current = trade.current_price || entry

  const stopDist = ((current - stop) / current * 100).toFixed(1)
  const targetDist = target ? ((target - current) / current * 100).toFixed(1) : null

  return (
    <div className="flex items-center gap-1 text-xs">
      <Tooltip content={`Stop: $${stop.toFixed(2)} (${stopDist}% away)`}>
        <span className="px-1 rounded" style={{
          background: 'rgba(239,68,68,0.1)', color: 'var(--arcis-danger)', fontSize: '0.65rem',
        }}>
          S {stopDist}%
        </span>
      </Tooltip>
      {targetDist && (
        <Tooltip content={`Target: $${target.toFixed(2)} (${targetDist}% away)`}>
          <span className="px-1 rounded" style={{
            background: 'rgba(34,197,94,0.1)', color: 'var(--arcis-success)', fontSize: '0.65rem',
          }}>
            T {targetDist}%
          </span>
        </Tooltip>
      )}
    </div>
  )
}

// ── Portfolio allocation strip ───────────────────────────────────────

function AllocationStrip({ trades, equity }) {
  if (!trades.length || !equity) return null
  const total = trades.reduce((s, t) => s + (t.planned_allocation || 0), 0)
  if (total === 0) return null
  const cashPct = Math.max(0, ((equity - total) / equity) * 100)

  return (
    <div className="rounded-lg overflow-hidden" style={{ height: 8 }}>
      <div className="flex h-full">
        {trades.map((t, i) => {
          const pct = (t.planned_allocation || 0) / equity * 100
          if (pct < 0.5) return null
          const isPos = (t.pnl_pct || 0) >= 0
          return (
            <Tooltip key={t.trade_id || i} content={`${t.ticker}: ${pct.toFixed(1)}% ($${(t.planned_allocation || 0).toFixed(0)})`}>
              <div style={{
                width: `${pct}%`, height: '100%',
                background: isPos ? 'var(--arcis-success)' : 'var(--arcis-danger)',
                opacity: 0.6,
                borderRight: '1px solid var(--arcis-bg-primary)',
              }} />
            </Tooltip>
          )
        })}
        {cashPct > 0 && (
          <div style={{ width: `${cashPct}%`, height: '100%', background: 'var(--arcis-bg-elevated)' }} />
        )}
      </div>
    </div>
  )
}

// ── Trade detail expansion panel ─────────────────────────────────────

function TradeDetail({ trade }) {
  const rMultiple = computeRMultiple(trade)
  const isCapture = computeIsCapture(trade)
  const fields = [
    { label: 'Entry', value: trade.entry_price, fmt: v => `$${v.toFixed(2)}` },
    { label: 'Exit', value: trade.actual_exit_price, fmt: v => `$${v.toFixed(2)}` },
    { label: 'Stop', value: trade.stop_price, fmt: v => `$${v.toFixed(2)}`, color: 'var(--arcis-danger)' },
    { label: 'Target', value: trade.target_1, fmt: v => `$${v.toFixed(2)}`, color: 'var(--arcis-success)' },
    { label: 'Conviction', value: trade.setup_confidence, fmt: v => `${(v * 100).toFixed(0)}%` },
    { label: 'Priority', value: trade.priority_score, fmt: v => `${v.toFixed(0)}` },
    { label: 'Regime', value: trade.regime_label, fmt: v => v },
    { label: 'Shares', value: trade.planned_shares, fmt: v => `${v}` },
    { label: 'Allocation', value: trade.planned_allocation, fmt: v => `$${v.toFixed(0)}` },
    { label: 'MFE', value: trade.mfe_dollars, fmt: v => `$${v.toFixed(2)}`, color: 'var(--arcis-success)' },
    { label: 'MAE', value: trade.mae_dollars, fmt: v => `$${v.toFixed(2)}`, color: 'var(--arcis-danger)' },
    { label: 'Exit Reason', value: trade.exit_reason, fmt: v => v },
    { label: 'Slippage', value: trade.entry_slippage_bps, fmt: v => `${v.toFixed(1)} bps`,
      color: trade.entry_slippage_bps != null && Math.abs(trade.entry_slippage_bps) > 5 ? 'var(--arcis-warning)' : undefined },
    { label: 'R-Multiple', value: rMultiple, fmt: v => `${v.toFixed(2)}R`,
      color: rMultiple != null ? (rMultiple >= 1 ? 'var(--arcis-success)' : rMultiple < 0 ? 'var(--arcis-danger)' : undefined) : undefined },
    { label: 'IS Capture', value: isCapture, fmt: v => `${v.toFixed(1)}%`,
      color: isCapture != null ? (isCapture >= 50 ? 'var(--arcis-success)' : isCapture < 0 ? 'var(--arcis-danger)' : undefined) : undefined },
  ].filter(f => f.value != null)

  return (
    <div className="grid grid-cols-3 md:grid-cols-5 gap-x-4 gap-y-2 text-xs p-3 rounded-lg" style={{ background: 'var(--arcis-bg-primary)' }}>
      {fields.map(f => (
        <div key={f.label}>
          <span style={{ color: 'var(--arcis-text-muted)' }}>{f.label}: </span>
          <span className="financial-data" style={{ color: f.color || 'var(--arcis-text-primary)' }}>
            {f.fmt(f.value)}
          </span>
        </div>
      ))}
    </div>
  )
}

// ── Expandable trade row ─────────────────────────────────────────────

function ExpandableTradeRow({ trade, columns, rowIndex, maxPnl }) {
  const [expanded, setExpanded] = useState(false)
  const pnlPct = trade.pnl_pct || 0
  const isPos = pnlPct >= 0

  return (
    <>
      <tr
        onClick={() => setExpanded(!expanded)}
        className="cursor-pointer transition-colors"
        style={{
          borderBottom: '1px solid var(--arcis-border)',
          background: rowIndex % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)',
        }}
        onMouseEnter={e => e.currentTarget.style.background = 'rgba(59,130,246,0.05)'}
        onMouseLeave={e => e.currentTarget.style.background = rowIndex % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)'}
      >
        <td className="py-2.5 px-2 w-6">
          {expanded
            ? <ChevronDown size={12} style={{ color: 'var(--arcis-accent)' }} />
            : <ChevronRight size={12} style={{ color: 'var(--arcis-text-muted)' }} />}
        </td>
        {columns.map(col => (
          <td key={col.key} className={`py-2.5 px-2 text-sm ${col.hideOnMobile ? 'hidden md:table-cell' : ''}`} style={{
            fontFamily: col.type !== 'text' ? 'var(--font-mono)' : undefined,
            color: 'var(--arcis-text-primary)',
          }}>
            {col.render ? col.render(trade, maxPnl) :
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

// ── Summary bar ──────────────────────────────────────────────────────

function SummaryRow({ trades }) {
  const totalPnl = trades.reduce((sum, t) => sum + (t.pnl_dollars || 0), 0)
  const avgDays = trades.length > 0
    ? (trades.reduce((sum, t) => sum + (t.duration_days || 0), 0) / trades.length).toFixed(1) : '0'
  const strategies = {}
  for (const t of trades) {
    const s = t.setup_type || 'unknown'
    strategies[s] = (strategies[s] || 0) + 1
  }

  return (
    <div className="flex flex-wrap items-center gap-4 px-3 py-2.5 text-xs" style={{ background: 'var(--arcis-bg-elevated)', borderBottom: '2px solid var(--arcis-border)' }}>
      <span style={{ color: 'var(--arcis-text-secondary)' }}>
        {trades.length} position{trades.length !== 1 ? 's' : ''}
      </span>
      <span style={{ color: 'var(--arcis-text-secondary)' }}>
        P&L: <PnlValue value={totalPnl} />
      </span>
      <span style={{ color: 'var(--arcis-text-secondary)' }}>
        Avg days: <span className="financial-data">{avgDays}</span>
      </span>
      {Object.entries(strategies).length > 1 && Object.entries(strategies)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([s, n]) => (
          <span key={s} className="flex items-center gap-1">
            <StrategyBadge type={s} /> <span style={{ color: 'var(--arcis-text-muted)' }}>{n}</span>
          </span>
        ))
      }
    </div>
  )
}

// ── Viz tabs ─────────────────────────────────────────────────────────

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
        <Area type="monotone" dataKey="equity" stroke="var(--arcis-accent)" fill="var(--arcis-accent)" fillOpacity={0.25} strokeWidth={2} />
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
    const s = t.setup_type || t.sector || 'Unknown'
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
      <h4 className="text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Strategy / Sector Exposure</h4>
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

// ── Sort helper ──────────────────────────────────────────────────────

const SORT_OPTIONS = [
  { key: 'pnl_pct', label: 'P&L %' },
  { key: 'pnl_dollars', label: 'P&L $' },
  { key: 'ticker', label: 'Ticker' },
  { key: 'duration_days', label: 'Days held' },
  { key: 'setup_type', label: 'Strategy' },
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

export default function ShadowLedger() {
  const [tab, setTab] = useState('open')
  const [vizTab, setVizTab] = useState('equity')
  const [filter, setFilter] = useState('')
  const [strategyFilter, setStrategyFilter] = useState('')
  const [sortKey, setSortKey] = useState('pnl_pct')
  const [sortDir, setSortDir] = useState('desc')

  const { data: openData, isLoading: openLoading } = useQuery({ queryKey: ['shadow-open'], queryFn: api.getOpenTrades, refetchInterval: 30000 })
  const { data: closedData, isLoading: closedLoading } = useQuery({ queryKey: ['shadow-closed'], queryFn: () => api.getClosedTrades(90), refetchInterval: 30000 })
  const { data: accountData } = useQuery({ queryKey: ['shadow-account'], queryFn: api.getAccount, refetchInterval: 60000 })

  const openTrades = useMemo(() => {
    let trades = openData?.open_trades || []
    if (filter) trades = trades.filter(t => (t.ticker || '').toLowerCase().includes(filter.toLowerCase())
      || (t.setup_type || '').toLowerCase().includes(filter.toLowerCase()))
    if (strategyFilter) trades = trades.filter(t => t.strategy_type === strategyFilter)
    return sortTrades(trades, sortKey, sortDir)
  }, [openData, filter, strategyFilter, sortKey, sortDir])

  const closedTrades = useMemo(() => {
    let trades = closedData?.trades || []
    if (filter) trades = trades.filter(t => (t.ticker || '').toLowerCase().includes(filter.toLowerCase())
      || (t.setup_type || '').toLowerCase().includes(filter.toLowerCase()))
    if (strategyFilter) trades = trades.filter(t => t.strategy_type === strategyFilter)
    return sortTrades(trades, sortKey, sortDir)
  }, [closedData, filter, strategyFilter, sortKey, sortDir])

  const equity = accountData?.equity || 100000
  const startingCapital = accountData?.starting_capital || 100000
  const metrics = closedData?.metrics || {}

  // Compute aggregate stats
  const closedPnls = closedTrades.map(t => t.pnl_dollars || 0)
  const wins = closedPnls.filter(p => p > 0)
  const losses = closedPnls.filter(p => p <= 0)
  const profitFactor = losses.length > 0 && Math.abs(losses.reduce((a, b) => a + b, 0)) > 0
    ? (wins.reduce((a, b) => a + b, 0) / Math.abs(losses.reduce((a, b) => a + b, 0))).toFixed(2)
    : wins.length > 0 ? '\u221e' : '--'

  let running = 0, peak = 0, maxDD = 0
  for (const p of closedPnls) {
    running += p; if (running > peak) peak = running
    const dd = peak - running; if (dd > maxDD) maxDD = dd
  }
  const maxDDPct = startingCapital > 0 ? ((maxDD / startingCapital) * 100).toFixed(1) : '0.0'
  const slippages = closedTrades.filter(t => t.entry_slippage_bps != null).map(t => t.entry_slippage_bps)
  const avgSlippage = slippages.length > 0 ? (slippages.reduce((a, b) => a + b, 0) / slippages.length).toFixed(1) : '--'
  const rMultiples = closedTrades.map(computeRMultiple).filter(r => r != null)
  const avgR = rMultiples.length > 0 ? (rMultiples.reduce((a, b) => a + b, 0) / rMultiples.length).toFixed(2) : '--'

  // Max P&L for color intensity scaling
  const allTrades = tab === 'open' ? openTrades : closedTrades
  const maxAbsPnl = Math.max(1, ...allTrades.map(t => Math.abs(t.pnl_dollars || 0)))

  const toggleSort = (key) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('desc') }
  }

  // Column definitions with intensity-aware P&L renders
  const openCols = [
    { key: 'ticker', label: 'Ticker', type: 'text',
      render: (t) => <span className="flex items-center gap-1.5 font-medium"><TickerLogo ticker={t.ticker} />{t.ticker}</span> },
    { key: 'entry_price', label: 'Entry', type: 'currency', hideOnMobile: true },
    { key: 'pnl_dollars', label: 'P&L', type: 'currency',
      render: (t, maxPnl) => {
        const opacity = pnlOpacity(t.pnl_dollars, maxPnl)
        return <span className="financial-data" style={{
          color: (t.pnl_dollars || 0) >= 0 ? 'var(--arcis-success)' : 'var(--arcis-danger)', opacity,
        }}>{t.pnl_dollars != null ? `${t.pnl_dollars >= 0 ? '+' : ''}$${Math.abs(t.pnl_dollars).toFixed(2)}` : '--'}</span>
      }},
    { key: 'pnl_pct', label: 'P&L %', type: 'percent',
      render: (t) => <PnlPctValue value={t.pnl_pct} /> },
    { key: 'duration_days', label: 'Days', type: 'number',
      render: (t) => <span className="financial-data">{t.duration_days ?? '--'}</span> },
    { key: 'setup_type', label: 'Strategy', type: 'text', hideOnMobile: true,
      render: (t) => <StrategyBadge type={t.setup_type} /> },
    { key: 'bracket', label: 'Bracket', type: 'text', hideOnMobile: true,
      render: (t) => <BracketIndicator trade={t} /> },
  ]

  const closedCols = [
    { key: 'ticker', label: 'Ticker', type: 'text',
      render: (t) => <span className="flex items-center gap-1.5 font-medium"><TickerLogo ticker={t.ticker} />{t.ticker}</span> },
    { key: 'entry_price', label: 'Entry', type: 'currency', hideOnMobile: true },
    { key: 'pnl_dollars', label: 'P&L', type: 'currency',
      render: (t, maxPnl) => {
        const opacity = pnlOpacity(t.pnl_dollars, maxPnl)
        return <span className="financial-data" style={{
          color: (t.pnl_dollars || 0) >= 0 ? 'var(--arcis-success)' : 'var(--arcis-danger)', opacity,
        }}>{t.pnl_dollars != null ? `${t.pnl_dollars >= 0 ? '+' : ''}$${Math.abs(t.pnl_dollars).toFixed(2)}` : '--'}</span>
      }},
    { key: 'pnl_pct', label: 'P&L %', type: 'percent',
      render: (t) => <PnlPctValue value={t.pnl_pct} /> },
    { key: 'duration_days', label: 'Days', type: 'number',
      render: (t) => <span className="financial-data">{t.duration_days ?? '--'}</span> },
    { key: 'setup_type', label: 'Strategy', type: 'text', hideOnMobile: true,
      render: (t) => <StrategyBadge type={t.setup_type} /> },
    { key: 'r_multiple', label: 'R-Mult', type: 'number', hideOnMobile: true,
      render: (t) => { const r = computeRMultiple(t); return r != null
        ? <span className="financial-data" style={{ color: r >= 1 ? 'var(--arcis-success)' : r < 0 ? 'var(--arcis-danger)' : 'var(--arcis-text-primary)' }}>{r.toFixed(2)}R</span>
        : <span style={{ color: 'var(--arcis-text-muted)' }}>--</span> } },
    { key: 'exit_reason', label: 'Exit', type: 'text', hideOnMobile: true },
  ]

  const currentCols = tab === 'open' ? openCols : closedCols
  const currentTrades = tab === 'open' ? openTrades : closedTrades
  const isLoading = tab === 'open' ? openLoading : closedLoading

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)' }}>Shadow Ledger</h2>
        <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>
          Updated every 30s
        </div>
      </div>

      {/* Portfolio allocation strip */}
      <AllocationStrip trades={openData?.open_trades || []} equity={equity} />

      {/* Metrics grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
        <MetricCard label="Paper Equity" value={equity.toLocaleString()} prefix="$" delta={equity - startingCapital} />
        <MetricCard label="Open / Max" value={`${accountData?.open_positions || openData?.open_count || 0} / 50`} />
        <MetricCard label="Closed" value={`${closedTrades.length} / 50`} delta={closedTrades.length >= 50 ? 'Gate met' : null} />
        <MetricCard label="Win Rate" value={metrics.win_rate != null ? `${(metrics.win_rate * 100).toFixed(1)}%` : accountData?.win_rate != null ? `${(accountData.win_rate * 100).toFixed(1)}%` : '--'} />
        <MetricCard label="Profit Factor" value={profitFactor} />
        <MetricCard label="Max DD" value={`${maxDDPct}%`} />
        <Tooltip content="Average entry slippage in basis points across all closed trades">
          <MetricCard label="Avg Slip (bps)" value={avgSlippage} />
        </Tooltip>
        <Tooltip content="Average R-Multiple: P&L relative to initial risk (entry-to-stop)">
          <MetricCard label="Avg R-Mult" value={avgR !== '--' ? `${avgR}R` : '--'} />
        </Tooltip>
      </div>

      {/* Tab bar + search + sort */}
      <div className="flex flex-col md:flex-row md:items-center gap-3" style={{ borderBottom: '1px solid var(--arcis-border)', paddingBottom: '12px' }}>
        <div className="flex gap-1">
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

        <div className="flex items-center gap-2 md:ml-auto">
          {/* Search */}
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: 'var(--arcis-text-muted)' }} />
            <input
              type="text" value={filter} onChange={e => setFilter(e.target.value)}
              placeholder="Filter ticker or strategy..."
              className="pl-8 pr-3 py-1.5 text-xs rounded-lg"
              style={{
                background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)',
                color: 'var(--arcis-text-primary)', outline: 'none', width: 200,
              }}
            />
          </div>

          {/* Strategy filter */}
          <select
            value={strategyFilter}
            onChange={e => setStrategyFilter(e.target.value)}
            className="pl-2 pr-2 py-1.5 text-xs rounded-lg appearance-none"
            style={{
              background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)',
              color: 'var(--arcis-text-primary)', outline: 'none',
            }}
          >
            <option value="">All strategies</option>
            <option value="pullback">Pullback</option>
            <option value="mean_reversion">Mean Reversion</option>
          </select>

          {/* Sort dropdown */}
          <div className="relative">
            <select
              value={sortKey}
              onChange={e => setSortKey(e.target.value)}
              className="pl-2 pr-7 py-1.5 text-xs rounded-lg appearance-none"
              style={{
                background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)',
                color: 'var(--arcis-text-primary)', outline: 'none',
              }}
            >
              {SORT_OPTIONS.map(o => (
                <option key={o.key} value={o.key}>{o.label}</option>
              ))}
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
         !currentTrades.length ? <div className="p-8"><EmptyState message={`No ${tab} trades${filter ? ' matching filter' : ''}`} icon={TrendingUp} /></div> :
         <>
           <SummaryRow trades={currentTrades} />
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
                   <ExpandableTradeRow key={t.trade_id || i} trade={t} columns={currentCols} rowIndex={i} maxPnl={maxAbsPnl} />
                 ))}
               </tbody>
             </table>
           </div>
         </>}
      </div>

      {/* Closed trade metrics + viz */}
      {tab === 'closed' && closedTrades.length > 0 && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <MetricCard label="Total Trades" value={metrics.total_trades || closedTrades.length} />
            <MetricCard label="Avg Gain" value={(metrics.avg_gain || 0).toFixed(2)} prefix="$" />
            <MetricCard label="Avg Loss" value={(metrics.avg_loss || 0).toFixed(2)} prefix="$" />
            <MetricCard label="Expectancy" value={(metrics.expectancy || 0).toFixed(2)} prefix="$" delta={metrics.expectancy} />
            <MetricCard label="Total P&L" value={(metrics.total_pnl || 0).toFixed(2)} prefix="$" delta={metrics.total_pnl} />
          </div>

          <div className="rounded-lg p-4" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
            <div className="flex gap-2 mb-4" style={{ borderBottom: '1px solid var(--arcis-border)' }}>
              {[
                { key: 'equity', label: 'Equity Curve' },
                { key: 'distribution', label: 'Distribution' },
                { key: 'sector', label: 'Strategy' },
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
        </>
      )}
    </div>
  )
}
