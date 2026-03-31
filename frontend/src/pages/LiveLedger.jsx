import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import MetricCard from '../components/MetricCard'
import Tooltip from '../components/Tooltip'
import DataTable from '../components/DataTable'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'
import { XAxis, YAxis, Tooltip as ChartTooltip, ResponsiveContainer, Area, AreaChart, ReferenceLine } from 'recharts'

export default function LiveLedger() {
  const { data: summary, isLoading: sumLoading } = useQuery({
    queryKey: ['live-summary'],
    queryFn: api.getLiveSummary,
    refetchInterval: 60000,
  })
  const { data: trades, isLoading: tradesLoading } = useQuery({
    queryKey: ['live-trades'],
    queryFn: api.getLiveTrades,
    refetchInterval: 60000,
  })

  if (sumLoading || tradesLoading) return <LoadingSpinner />

  const openTrades = trades?.open || []
  const closedTrades = trades?.closed || []
  const startingCapital = summary?.starting_capital || 100
  const equity = summary?.current_equity || startingCapital
  const pnl = summary?.total_pnl || 0
  const winRate = summary?.win_rate

  // Build equity curve from closed trades
  const equityCurve = closedTrades
    .slice()
    .reverse()
    .reduce((acc, t) => {
      const prev = acc.length > 0 ? acc[acc.length - 1].equity : startingCapital
      const newEquity = prev + (t.pnl_dollars || 0)
      acc.push({
        date: (t.actual_exit_time || t.created_at || '').slice(5, 10),
        equity: Math.round(newEquity * 100) / 100,
      })
      return acc
    }, [])

  const openColumns = [
    { key: 'ticker', label: 'Ticker', type: 'text' },
    { key: 'direction', label: 'Dir', type: 'text' },
    { key: 'entry_price', label: 'Entry', type: 'currency' },
    { key: 'current_price', label: 'Current', type: 'currency' },
    { key: 'pnl_dollars', label: 'P&L $', type: 'currency' },
    { key: 'pnl_pct', label: 'P&L %', type: 'percent' },
    { key: 'duration_days', label: 'Days', type: 'number' },
    { key: 'stop_price', label: 'Stop', type: 'currency' },
    { key: 'target_1', label: 'Target', type: 'currency' },
  ]

  const closedColumns = [
    { key: 'ticker', label: 'Ticker', type: 'text' },
    { key: 'direction', label: 'Dir', type: 'text' },
    { key: 'entry_price', label: 'Entry', type: 'currency' },
    { key: 'actual_exit_price', label: 'Exit', type: 'currency' },
    { key: 'pnl_dollars', label: 'P&L $', type: 'currency' },
    { key: 'pnl_pct', label: 'P&L %', type: 'percent' },
    { key: 'exit_reason', label: 'Exit Reason', type: 'text' },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)' }}>Live Ledger</h2>
        <Tooltip content="Syncs Alpaca live positions with the local database. Run locally: python -m src.main reconcile-live">
          <button disabled className="px-3 py-1.5 text-xs rounded opacity-50 cursor-not-allowed" style={{ background: 'var(--arcis-border)', color: 'var(--arcis-text-secondary)' }}>
            Reconcile (CLI only)
          </button>
        </Tooltip>
      </div>

      {/* Header metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Live Equity" value={equity.toFixed(2)} prefix="$" delta={pnl} />
        <MetricCard label="Open Positions" value={summary?.open_positions || 0} />
        <MetricCard label="Total P&L" value={`${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}`} prefix="$"
          delta={summary?.total_pnl_pct != null ? `${summary.total_pnl_pct.toFixed(1)}%` : null} />
        <MetricCard label="Win Rate" value={winRate != null ? `${(winRate * 100).toFixed(1)}%` : '--'} />
      </div>

      {/* Equity curve */}
      {equityCurve.length > 0 && (
        <div className="rounded-lg p-4" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
          <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>Equity Curve</h3>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={equityCurve}>
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--arcis-text-secondary)' }} />
              <YAxis tick={{ fontSize: 11, fill: 'var(--arcis-text-secondary)' }} domain={['dataMin - 5', 'dataMax + 5']} />
              <ChartTooltip contentStyle={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 8, fontSize: 12 }} />
              <ReferenceLine y={startingCapital} stroke="var(--arcis-text-muted)" strokeDasharray="3 3" label={{ value: `$${startingCapital}`, position: 'right', fill: 'var(--arcis-text-secondary)', fontSize: 10 }} />
              <Area type="monotone" dataKey="equity" stroke="var(--arcis-accent)" fill="var(--arcis-accent)" fillOpacity={0.1} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Open positions */}
      <div className="rounded-lg p-4" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
        <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>
          Open Positions ({openTrades.length})
        </h3>
        {openTrades.length > 0 ? (
          <DataTable columns={openColumns} data={openTrades} />
        ) : (
          <EmptyState message="No open live positions" />
        )}
      </div>

      {/* Closed trades */}
      <div className="rounded-lg p-4" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
        <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>
          Closed Trades ({closedTrades.length})
        </h3>
        {closedTrades.length > 0 ? (
          <>
            <DataTable columns={closedColumns} data={closedTrades} />
            {/* Summary row */}
            <div className="mt-3 pt-3 flex gap-6 text-sm" style={{ borderTop: '1px solid var(--arcis-border)' }}>
              <span style={{ color: 'var(--arcis-text-secondary)' }}>
                Total P&L: <span style={{ fontFamily: 'var(--font-mono)', color: pnl >= 0 ? 'var(--arcis-success)' : 'var(--arcis-danger)' }}>
                  ${pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}
                </span>
              </span>
              <span style={{ color: 'var(--arcis-text-secondary)' }}>
                Avg P&L: <span style={{ fontFamily: 'var(--font-mono)' }}>
                  ${closedTrades.length > 0 ? (pnl / closedTrades.length).toFixed(2) : '0.00'}
                </span>
              </span>
            </div>
          </>
        ) : (
          <EmptyState message="No closed live trades yet" />
        )}
      </div>
    </div>
  )
}
