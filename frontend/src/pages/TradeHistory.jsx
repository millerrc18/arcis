import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, ResponsiveContainer, Cell, ReferenceLine, ComposedChart,
} from 'recharts'
import { TrendingUp, TrendingDown, Clock, Target, Shield, Activity } from 'lucide-react'

// Trade History — comprehensive visualization of trade performance over time.
//
// Answers two questions:
// (a) Are we getting better or worse? (rolling metrics, trends, regime shifts)
// (b) How are recent trades doing? (today/yesterday breakdowns, last 7d)
//
// Replaces the prior Broker Comparison page which was underutilized.
// IB shadow data is deprioritized — Phase 1 is about validating the core
// strategy, not comparing execution venues.

const MONO = { fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }

function formatPct(val, decimals = 2) {
  if (val == null || isNaN(val)) return '--'
  const sign = val >= 0 ? '+' : ''
  return `${sign}${val.toFixed(decimals)}%`
}

function formatDollars(val, decimals = 2) {
  if (val == null || isNaN(val)) return '--'
  const sign = val >= 0 ? '+' : ''
  const abs = Math.abs(val)
  return `${sign}$${abs.toFixed(decimals)}`
}

function pnlColor(val) {
  if (val == null || val === 0) return 'var(--arcis-text-muted)'
  return val > 0 ? 'var(--arcis-success)' : 'var(--arcis-danger)'
}

function dateKey(iso) {
  if (!iso) return null
  return iso.slice(0, 10)
}

function todayET() {
  // Use Intl to get the current ET date as YYYY-MM-DD
  const now = new Date()
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric', month: '2-digit', day: '2-digit',
  })
  return fmt.format(now)
}

function yesterdayET() {
  const now = new Date()
  // Subtract enough hours to get yesterday even in ET
  const yest = new Date(now.getTime() - 24 * 60 * 60 * 1000)
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric', month: '2-digit', day: '2-digit',
  })
  return fmt.format(yest)
}

// Compute win rate over a rolling window of trades
function rollingWinRate(trades, window = 10) {
  if (!trades || trades.length === 0) return []
  const sorted = [...trades].sort((a, b) => (a.actual_exit_time || '').localeCompare(b.actual_exit_time || ''))
  const result = []
  for (let i = 0; i < sorted.length; i++) {
    const slice = sorted.slice(Math.max(0, i - window + 1), i + 1)
    const wins = slice.filter(t => (Number(t.pnl_dollars) || 0) > 0).length
    const wr = slice.length > 0 ? (wins / slice.length) * 100 : 0
    const cumPnl = sorted.slice(0, i + 1).reduce((s, t) => s + (Number(t.pnl_dollars) || 0), 0)
    result.push({
      idx: i + 1,
      date: dateKey(sorted[i].actual_exit_time),
      ticker: sorted[i].ticker,
      win_rate: Math.round(wr),
      cum_pnl: Math.round(cumPnl * 100) / 100,
      trade_pnl: Number(sorted[i].pnl_dollars) || 0,
      pnl_pct: Number(sorted[i].pnl_pct) || 0,
    })
  }
  return result
}

// Compute rolling Sharpe ratio
function rollingSharpe(trades, window = 20) {
  if (!trades || trades.length < 2) return []
  const sorted = [...trades].sort((a, b) => (a.actual_exit_time || '').localeCompare(b.actual_exit_time || ''))
  const result = []
  for (let i = 0; i < sorted.length; i++) {
    const slice = sorted.slice(Math.max(0, i - window + 1), i + 1)
    if (slice.length < 2) {
      result.push({ idx: i + 1, date: dateKey(sorted[i].actual_exit_time), sharpe: null })
      continue
    }
    const returns = slice.map(t => Number(t.pnl_pct) || 0)
    const mean = returns.reduce((s, r) => s + r, 0) / returns.length
    const variance = returns.reduce((s, r) => s + (r - mean) ** 2, 0) / (returns.length - 1)
    const std = Math.sqrt(variance)
    // Annualize assuming ~150 trades/year
    const sharpe = std > 0 ? (mean / std) * Math.sqrt(150) : 0
    result.push({
      idx: i + 1,
      date: dateKey(sorted[i].actual_exit_time),
      sharpe: Math.round(sharpe * 100) / 100,
    })
  }
  return result
}

function StatCard({ label, value, subtitle, color, icon: Icon }) {
  return (
    <div className="arcis-card">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>{label}</div>
        {Icon && <Icon size={14} style={{ color: 'var(--arcis-text-muted)' }} />}
      </div>
      <div className="text-xl font-medium" style={{ ...MONO, color: color || 'var(--arcis-text-primary)' }}>
        {value}
      </div>
      {subtitle && (
        <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>{subtitle}</div>
      )}
    </div>
  )
}

function RecentTradesTable({ trades, title, emptyMessage }) {
  if (!trades || trades.length === 0) {
    return (
      <div className="arcis-card">
        <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>{title}</h3>
        <div className="text-sm py-4 text-center" style={{ color: 'var(--arcis-text-muted)' }}>
          {emptyMessage || 'No trades in this period'}
        </div>
      </div>
    )
  }
  return (
    <div className="arcis-card">
      <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>{title} ({trades.length})</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: '1px solid var(--arcis-border)' }}>
              <th className="py-2 px-2 text-left text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Ticker</th>
              <th className="py-2 px-2 text-left text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Exit</th>
              <th className="py-2 px-2 text-right text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>P&L $</th>
              <th className="py-2 px-2 text-right text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>P&L %</th>
              <th className="py-2 px-2 text-right text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Hold</th>
              <th className="py-2 px-2 text-left text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Reason</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => {
              const pnl = Number(t.pnl_dollars) || 0
              const pnlPct = Number(t.pnl_pct) || 0
              const duration = t.duration_days || '--'
              const reason = (t.exit_reason || '--').replace(/_/g, ' ')
              return (
                <tr key={t.trade_id || i} style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                  <td className="py-2 px-2" style={MONO}>{t.ticker}</td>
                  <td className="py-2 px-2 text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>
                    {t.actual_exit_time ? new Date(t.actual_exit_time).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false }) : '--'}
                  </td>
                  <td className="py-2 px-2 text-right" style={{ ...MONO, color: pnlColor(pnl) }}>{formatDollars(pnl)}</td>
                  <td className="py-2 px-2 text-right" style={{ ...MONO, color: pnlColor(pnl) }}>{formatPct(pnlPct)}</td>
                  <td className="py-2 px-2 text-right" style={MONO}>{duration}d</td>
                  <td className="py-2 px-2 text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>{reason}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function TradeHistory() {
  const { data: closedData, isLoading } = useQuery({
    queryKey: ['trade-history-closed'],
    queryFn: () => api.getClosedTrades(180),  // 6 months history
    refetchInterval: 60000,
  })

  const analysis = useMemo(() => {
    const trades = closedData?.trades || closedData || []
    if (!Array.isArray(trades) || trades.length === 0) return null

    // Filter out open trades (pnl_dollars is null for open)
    const closed = trades.filter(t => t.pnl_dollars != null && t.actual_exit_time)

    const today = todayET()
    const yest = yesterdayET()

    // Bucket by recency
    const todayTrades = closed.filter(t => dateKey(t.actual_exit_time) === today)
    const yestTrades = closed.filter(t => dateKey(t.actual_exit_time) === yest)

    const last7dCutoff = new Date()
    last7dCutoff.setDate(last7dCutoff.getDate() - 7)
    const last7dIso = last7dCutoff.toISOString()
    const last7d = closed.filter(t => (t.actual_exit_time || '') >= last7dIso)

    const last30dCutoff = new Date()
    last30dCutoff.setDate(last30dCutoff.getDate() - 30)
    const last30dIso = last30dCutoff.toISOString()
    const last30d = closed.filter(t => (t.actual_exit_time || '') >= last30dIso)

    // Compute metrics for any trade bucket
    const metrics = (arr) => {
      if (!arr.length) return { count: 0, wr: 0, pnl: 0, avg_pnl: 0, avg_duration: 0 }
      const wins = arr.filter(t => (Number(t.pnl_dollars) || 0) > 0)
      const totalPnl = arr.reduce((s, t) => s + (Number(t.pnl_dollars) || 0), 0)
      const avgDuration = arr.reduce((s, t) => s + (t.duration_days || 0), 0) / arr.length
      return {
        count: arr.length,
        wins: wins.length,
        losses: arr.length - wins.length,
        wr: (wins.length / arr.length) * 100,
        pnl: totalPnl,
        avg_pnl: totalPnl / arr.length,
        avg_duration: avgDuration,
      }
    }

    return {
      all: metrics(closed),
      today: metrics(todayTrades),
      yesterday: metrics(yestTrades),
      last7d: metrics(last7d),
      last30d: metrics(last30d),
      todayTrades: todayTrades.sort((a, b) => (b.actual_exit_time || '').localeCompare(a.actual_exit_time || '')),
      yestTrades: yestTrades.sort((a, b) => (b.actual_exit_time || '').localeCompare(a.actual_exit_time || '')),
      last7dTrades: last7d,
      closedSorted: [...closed].sort((a, b) => (a.actual_exit_time || '').localeCompare(b.actual_exit_time || '')),
      rolling10: rollingWinRate(closed, 10),
      rolling20Sharpe: rollingSharpe(closed, 20),
      exitReasonBreakdown: (() => {
        const buckets = {}
        closed.forEach(t => {
          const r = t.exit_reason || 'unknown'
          if (!buckets[r]) buckets[r] = { reason: r.replace(/_/g, ' '), count: 0, total_pnl: 0 }
          buckets[r].count++
          buckets[r].total_pnl += Number(t.pnl_dollars) || 0
        })
        return Object.values(buckets).sort((a, b) => b.count - a.count)
      })(),
      pnlHistogram: (() => {
        const bins = [
          { label: '< -3%', min: -Infinity, max: -3, count: 0 },
          { label: '-3 to -1%', min: -3, max: -1, count: 0 },
          { label: '-1 to 0%', min: -1, max: 0, count: 0 },
          { label: '0 to +1%', min: 0, max: 1, count: 0 },
          { label: '+1 to +3%', min: 1, max: 3, count: 0 },
          { label: '+3 to +5%', min: 3, max: 5, count: 0 },
          { label: '> +5%', min: 5, max: Infinity, count: 0 },
        ]
        closed.forEach(t => {
          const p = Number(t.pnl_pct) || 0
          const b = bins.find(x => p >= x.min && p < x.max)
          if (b) b.count++
        })
        return bins
      })(),
      dailyBreakdown: (() => {
        const days = {}
        closed.forEach(t => {
          const d = dateKey(t.actual_exit_time)
          if (!d) return
          if (!days[d]) days[d] = { date: d, count: 0, wins: 0, pnl: 0 }
          days[d].count++
          if ((Number(t.pnl_dollars) || 0) > 0) days[d].wins++
          days[d].pnl += Number(t.pnl_dollars) || 0
        })
        return Object.values(days).sort((a, b) => a.date.localeCompare(b.date)).slice(-30)
      })(),
    }
  }, [closedData])

  if (isLoading) return <LoadingSpinner />
  if (!analysis) {
    return (
      <div className="space-y-4">
        <div>
          <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)' }}>Trade History</h2>
          <p className="text-sm mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>No closed trades yet</p>
        </div>
      </div>
    )
  }

  const { all, today, yesterday, last7d, last30d, todayTrades, yestTrades,
    rolling10, rolling20Sharpe, exitReasonBreakdown, pnlHistogram, dailyBreakdown } = analysis

  // Detect trend direction (last 10 vs prior 10)
  const recent10 = rolling10.slice(-10)
  const prior10 = rolling10.slice(-20, -10)
  const recentAvgPnl = recent10.length > 0 ? recent10.reduce((s, r) => s + r.trade_pnl, 0) / recent10.length : 0
  const priorAvgPnl = prior10.length > 0 ? prior10.reduce((s, r) => s + r.trade_pnl, 0) / prior10.length : 0
  const trendingUp = recent10.length >= 5 && prior10.length >= 5 && recentAvgPnl > priorAvgPnl

  return (
    <div className="space-y-4 md:space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)' }}>Trade History</h2>
        <p className="text-sm mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
          {all.count} closed trades · Last 6 months · Are we getting better or worse?
        </p>
      </div>

      {/* Recency buckets */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4">
        <div className="arcis-card">
          <div className="text-xs uppercase tracking-wide mb-2" style={{ color: 'var(--arcis-accent)' }}>Today</div>
          <div className="text-2xl font-medium" style={{ ...MONO, color: pnlColor(today.pnl) }}>
            {formatDollars(today.pnl)}
          </div>
          <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
            {today.count} trades · {today.wins || 0}W / {today.losses || 0}L
          </div>
        </div>
        <div className="arcis-card">
          <div className="text-xs uppercase tracking-wide mb-2" style={{ color: 'var(--arcis-text-secondary)' }}>Yesterday</div>
          <div className="text-2xl font-medium" style={{ ...MONO, color: pnlColor(yesterday.pnl) }}>
            {formatDollars(yesterday.pnl)}
          </div>
          <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
            {yesterday.count} trades · {yesterday.wins || 0}W / {yesterday.losses || 0}L
          </div>
        </div>
        <div className="arcis-card">
          <div className="text-xs uppercase tracking-wide mb-2" style={{ color: 'var(--arcis-text-secondary)' }}>Last 7 Days</div>
          <div className="text-2xl font-medium" style={{ ...MONO, color: pnlColor(last7d.pnl) }}>
            {formatDollars(last7d.pnl)}
          </div>
          <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
            {last7d.count} trades · {last7d.wr.toFixed(0)}% WR
          </div>
        </div>
        <div className="arcis-card">
          <div className="text-xs uppercase tracking-wide mb-2" style={{ color: 'var(--arcis-text-secondary)' }}>Last 30 Days</div>
          <div className="text-2xl font-medium" style={{ ...MONO, color: pnlColor(last30d.pnl) }}>
            {formatDollars(last30d.pnl)}
          </div>
          <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
            {last30d.count} trades · {last30d.wr.toFixed(0)}% WR
          </div>
        </div>
      </div>

      {/* Trend indicator + aggregate stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 md:gap-4">
        <StatCard
          label="Trending"
          value={trendingUp ? 'Improving' : (recent10.length < 5 ? 'Need data' : 'Cooling')}
          subtitle={recent10.length >= 5 && prior10.length >= 5 ? `${formatDollars(recentAvgPnl)}/trade recent vs ${formatDollars(priorAvgPnl)}/trade prior` : 'Need 20+ trades'}
          color={trendingUp ? 'var(--arcis-success)' : (recent10.length < 5 ? 'var(--arcis-text-muted)' : 'var(--arcis-warning)')}
          icon={trendingUp ? TrendingUp : TrendingDown}
        />
        <StatCard
          label="All-Time Win Rate"
          value={`${all.wr.toFixed(1)}%`}
          subtitle={`${all.wins}W / ${all.losses}L · ${all.count} trades`}
          color={all.wr >= 50 ? 'var(--arcis-success)' : 'var(--arcis-danger)'}
          icon={Target}
        />
        <StatCard
          label="Total P&L"
          value={formatDollars(all.pnl)}
          subtitle={`${formatDollars(all.avg_pnl)}/trade avg`}
          color={pnlColor(all.pnl)}
          icon={Activity}
        />
        <StatCard
          label="Avg Hold Time"
          value={`${all.avg_duration.toFixed(1)} days`}
          subtitle="Target: 3-8 days"
          color={all.avg_duration >= 3 && all.avg_duration <= 8 ? 'var(--arcis-success)' : 'var(--arcis-warning)'}
          icon={Clock}
        />
      </div>

      {/* Rolling win rate + Sharpe (progress indicators) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="arcis-card">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Rolling 10-Trade Win Rate</h3>
            <span className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>Improving = trending up</span>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={rolling10}>
              <defs>
                <linearGradient id="wrGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--arcis-accent)" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="var(--arcis-accent)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--arcis-border)" opacity={0.3} />
              <XAxis dataKey="idx" tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} tickFormatter={v => `${v}%`} />
              <RTooltip
                contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', borderRadius: 4, fontSize: 12 }}
                formatter={(val) => [`${val}%`, 'Win Rate']}
                labelFormatter={(idx) => `Trade #${idx}`}
              />
              <ReferenceLine y={50} stroke="var(--arcis-text-muted)" strokeDasharray="3 3" />
              <Area type="monotone" dataKey="win_rate" stroke="var(--arcis-accent)" fill="url(#wrGradient)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="arcis-card">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Rolling 20-Trade Sharpe</h3>
            <span className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>Annualized (√150 trades/yr)</span>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={rolling20Sharpe}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--arcis-border)" opacity={0.3} />
              <XAxis dataKey="idx" tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} />
              <YAxis tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} />
              <RTooltip
                contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', borderRadius: 4, fontSize: 12 }}
                formatter={(val) => [val?.toFixed(2) || '--', 'Sharpe']}
                labelFormatter={(idx) => `Trade #${idx}`}
              />
              <ReferenceLine y={1.0} stroke="var(--arcis-success)" strokeDasharray="3 3" label={{ value: 'IB gate', fontSize: 10, fill: 'var(--arcis-success)' }} />
              <ReferenceLine y={0.15} stroke="var(--arcis-warning)" strokeDasharray="3 3" label={{ value: 'Phase 1', fontSize: 10, fill: 'var(--arcis-warning)' }} />
              <Line type="monotone" dataKey="sharpe" stroke="var(--arcis-accent)" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Daily P&L bar chart (last 30 days with activity) */}
      {dailyBreakdown.length > 0 && (
        <div className="arcis-card">
          <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>Daily P&L (Last 30 Days with Trades)</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={dailyBreakdown}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--arcis-border)" opacity={0.3} />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} tickFormatter={d => d.slice(5)} />
              <YAxis tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} tickFormatter={v => `$${v}`} />
              <RTooltip
                contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', borderRadius: 4, fontSize: 12 }}
                formatter={(val, name) => {
                  if (name === 'pnl') return [formatDollars(val), 'P&L']
                  return [val, name]
                }}
              />
              <ReferenceLine y={0} stroke="var(--arcis-text-muted)" />
              <Bar dataKey="pnl">
                {dailyBreakdown.map((d, i) => (
                  <Cell key={i} fill={d.pnl >= 0 ? 'var(--arcis-success)' : 'var(--arcis-danger)'} opacity={0.7} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Today's and yesterday's trade tables */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <RecentTradesTable trades={todayTrades} title="Today's Closed Trades" emptyMessage="No closed trades today" />
        <RecentTradesTable trades={yestTrades} title="Yesterday's Closed Trades" emptyMessage="No closed trades yesterday" />
      </div>

      {/* P&L distribution histogram + exit reason breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="arcis-card">
          <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>P&L Distribution</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={pnlHistogram}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--arcis-border)" opacity={0.3} />
              <XAxis dataKey="label" tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} />
              <YAxis tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} />
              <RTooltip
                contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', borderRadius: 4, fontSize: 12 }}
              />
              <Bar dataKey="count">
                {pnlHistogram.map((b, i) => (
                  <Cell key={i} fill={b.min >= 0 ? 'var(--arcis-success)' : 'var(--arcis-danger)'} opacity={0.7} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="arcis-card">
          <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>Exit Reason Breakdown</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                  <th className="py-2 px-2 text-left text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Reason</th>
                  <th className="py-2 px-2 text-right text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Count</th>
                  <th className="py-2 px-2 text-right text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>% of Total</th>
                  <th className="py-2 px-2 text-right text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Total P&L</th>
                  <th className="py-2 px-2 text-right text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Avg P&L</th>
                </tr>
              </thead>
              <tbody>
                {exitReasonBreakdown.map((r, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                    <td className="py-2 px-2 text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>{r.reason}</td>
                    <td className="py-2 px-2 text-right" style={MONO}>{r.count}</td>
                    <td className="py-2 px-2 text-right" style={MONO}>{((r.count / all.count) * 100).toFixed(0)}%</td>
                    <td className="py-2 px-2 text-right" style={{ ...MONO, color: pnlColor(r.total_pnl) }}>{formatDollars(r.total_pnl)}</td>
                    <td className="py-2 px-2 text-right" style={{ ...MONO, color: pnlColor(r.total_pnl / r.count) }}>{formatDollars(r.total_pnl / r.count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Cumulative P&L area chart */}
      <div className="arcis-card">
        <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>Cumulative P&L Over Time</h3>
        <ResponsiveContainer width="100%" height={250}>
          <ComposedChart data={rolling10}>
            <defs>
              <linearGradient id="cumPnlGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="var(--arcis-accent)" stopOpacity={0.3} />
                <stop offset="95%" stopColor="var(--arcis-accent)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--arcis-border)" opacity={0.3} />
            <XAxis dataKey="idx" tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} />
            <YAxis tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} tickFormatter={v => `$${v}`} />
            <RTooltip
              contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', borderRadius: 4, fontSize: 12 }}
              formatter={(val, name) => {
                if (name === 'cum_pnl') return [formatDollars(val), 'Cumulative P&L']
                if (name === 'trade_pnl') return [formatDollars(val), 'Trade P&L']
                return [val, name]
              }}
              labelFormatter={(idx, payload) => {
                const p = payload?.[0]?.payload
                return p?.ticker ? `Trade #${idx} · ${p.ticker} · ${p.date}` : `Trade #${idx}`
              }}
            />
            <ReferenceLine y={0} stroke="var(--arcis-text-muted)" />
            <Area type="monotone" dataKey="cum_pnl" stroke="var(--arcis-accent)" fill="url(#cumPnlGradient)" strokeWidth={2} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
