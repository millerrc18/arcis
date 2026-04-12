import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import MetricCard from '../components/MetricCard'
import LoadingSpinner from '../components/LoadingSpinner'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip, ResponsiveContainer, Cell,
  ScatterChart, Scatter, ZAxis,
} from 'recharts'

// Capital Velocity dashboard placeholder (DB-3 add-on).
// Spec: docs/research/capital-velocity-optimization.md (Strategy Decision #32).
// Status: gated on 50 closed trades; Component 2+3 of the spec fire at that
// milestone. This page renders whatever is available right now so the metric
// is visible as trades accumulate — time-to-MFE scatter, hold-period histogram,
// and MFE-capture efficiency. When trade count < 50, prominent "pending" copy
// explains why most numbers are blank.
//
// When Component 1 (time_to_mfe_days column) hasn't landed yet, the time-to-MFE
// chart falls back to showing duration_days. The page does NOT try to look
// smart with small sample sizes — the threshold check keeps metrics honest.

const MIN_TRADES_FOR_METRICS = 50

function median(arr) {
  const xs = arr.filter(v => Number.isFinite(v)).sort((a, b) => a - b)
  if (!xs.length) return null
  const m = Math.floor(xs.length / 2)
  return xs.length % 2 ? xs[m] : (xs[m - 1] + xs[m]) / 2
}

export default function Velocity() {
  const { data: closedData, isLoading } = useQuery({
    queryKey: ['velocity-closed'],
    queryFn: () => api.getClosedTrades(180),
    refetchInterval: 600000,
  })

  const trades = useMemo(() => (closedData?.trades || []).filter(t => t.duration_days != null), [closedData])
  const total = trades.length
  const gated = total < MIN_TRADES_FOR_METRICS

  const winners = trades.filter(t => (t.pnl_dollars || 0) > 0)
  const losers = trades.filter(t => (t.pnl_dollars || 0) <= 0)

  const holdSeries = useMemo(() => {
    const bins = Array.from({ length: 16 }, (_, i) => ({ days: i, winners: 0, losers: 0 }))
    for (const t of trades) {
      const d = Math.max(0, Math.min(15, Math.round(t.duration_days || 0)))
      if ((t.pnl_dollars || 0) > 0) bins[d].winners += 1
      else bins[d].losers += 1
    }
    return bins
  }, [trades])

  const mfeScatter = useMemo(() => {
    return trades
      .map((t, i) => {
        const mfeDays = t.time_to_mfe_days ?? t.duration_days
        if (mfeDays == null) return null
        return {
          x: i + 1,
          y: mfeDays,
          pnl: t.pnl_dollars || 0,
          ticker: t.ticker,
        }
      })
      .filter(Boolean)
  }, [trades])

  const mfeCapture = useMemo(() => {
    const caps = []
    for (const t of winners) {
      const mfe = t.max_favorable_excursion
      const pnlPct = t.pnl_pct
      if (mfe == null || pnlPct == null || mfe <= 0) continue
      caps.push((pnlPct / mfe) * 100)
    }
    if (!caps.length) return null
    return caps.reduce((a, b) => a + b, 0) / caps.length
  }, [winners])

  if (isLoading) return <LoadingSpinner />

  const medianHold = median(trades.map(t => t.duration_days || 0))
  const medianWinnerHold = median(winners.map(t => t.duration_days || 0))
  const medianLoserHold = median(losers.map(t => t.duration_days || 0))
  const medianMfeDays = median(
    trades
      .map(t => t.time_to_mfe_days)
      .filter(v => Number.isFinite(v))
  )

  return (
    <div className="space-y-4 md:space-y-6">
      <div>
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Capital Velocity
        </h2>
        <p className="text-sm mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
          How fast capital turns — select faster, don't exit faster.
          <span className="ml-2" style={{ color: 'var(--arcis-text-muted)' }}>
            See docs/research/capital-velocity-optimization.md
          </span>
        </p>
      </div>

      {gated && (
        <div
          className="p-3 text-sm"
          style={{
            borderRadius: 'var(--radius-sm)',
            background: 'rgba(245, 158, 11, 0.12)',
            border: '1px solid rgba(245, 158, 11, 0.3)',
            color: 'var(--arcis-warning)',
          }}
        >
          Metrics gated — {total} / {MIN_TRADES_FOR_METRICS} closed trades. Most analyses
          require at least 50 closed trades to be statistically useful. Counts shown below are
          raw, not ranked.
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard label="Closed trades" value={total} />
        <MetricCard label="Median hold" value={medianHold != null ? `${medianHold.toFixed(1)}d` : '--'} />
        <MetricCard label="Median winner hold" value={medianWinnerHold != null ? `${medianWinnerHold.toFixed(1)}d` : '--'} />
        <MetricCard label="Median loser hold" value={medianLoserHold != null ? `${medianLoserHold.toFixed(1)}d` : '--'} />
        <MetricCard label="Median time-to-MFE" value={medianMfeDays != null ? `${medianMfeDays.toFixed(1)}d` : 'awaiting column'} />
        <MetricCard label="MFE capture" value={mfeCapture != null ? `${mfeCapture.toFixed(0)}%` : '--'} />
      </div>

      {/* Hold period distribution */}
      <div className="arcis-card">
        <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>
          Hold period distribution
        </h3>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={holdSeries}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--arcis-border)" />
            <XAxis dataKey="days" tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} tickFormatter={v => `${v}d`} />
            <YAxis tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} allowDecimals={false} />
            <RTooltip
              contentStyle={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 6, fontSize: 12 }}
              labelFormatter={(d) => `${d}-day hold`}
            />
            <Bar dataKey="winners" stackId="h" fill="var(--arcis-success)" />
            <Bar dataKey="losers" stackId="h" fill="var(--arcis-danger)" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Time-to-MFE scatter */}
      <div className="arcis-card">
        <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>
          Time-to-MFE scatter
          <span className="ml-2 text-xs normal-case" style={{ color: 'var(--arcis-text-muted)' }}>
            (falls back to duration until time_to_mfe_days column lands)
          </span>
        </h3>
        <ResponsiveContainer width="100%" height={240}>
          <ScatterChart margin={{ top: 10, right: 12, bottom: 20, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--arcis-border)" />
            <XAxis type="number" dataKey="x" name="Trade #" tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} />
            <YAxis type="number" dataKey="y" name="Days" tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} />
            <ZAxis dataKey="pnl" range={[20, 200]} />
            <RTooltip
              contentStyle={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 6, fontSize: 12 }}
              formatter={(val, name) => {
                if (name === 'y') return [`${val}d`, 'Days to MFE']
                if (name === 'pnl') return [`$${val.toFixed(2)}`, 'P&L']
                return [val, name]
              }}
            />
            <Scatter data={mfeScatter}>
              {mfeScatter.map((pt, i) => (
                <Cell key={i} fill={pt.pnl > 0 ? 'var(--arcis-success)' : 'var(--arcis-danger)'} opacity={0.7} />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
