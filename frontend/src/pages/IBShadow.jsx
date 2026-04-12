import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import MetricCard from '../components/MetricCard'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'
import { GitCompare } from 'lucide-react'

function StatusBadge({ ok }) {
  return (
    <span style={{
      color: ok ? 'var(--arcis-success)' : 'var(--arcis-danger)',
      fontFamily: 'var(--font-mono)',
      fontSize: 13,
    }}>
      {ok ? '\u2705' : '\u274C'}
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
    <img src={`https://logos.stockanalysis.com/${symbol.toLowerCase().replace('.', '-')}.svg`} alt="" className="shrink-0 rounded"
      style={{ width: 20, height: 20, objectFit: 'contain' }} onError={() => setFailed(true)} loading="lazy" />
  )
}

function formatTime(ts) {
  if (!ts) return '--'
  try {
    const d = new Date(ts)
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
  } catch {
    return ts
  }
}

function pctColor(val, greenThresh, yellowThresh) {
  if (val >= greenThresh) return 'var(--arcis-success)'
  if (val >= yellowThresh) return 'var(--arcis-warning)'
  return 'var(--arcis-danger)'
}

export default function IBShadow() {
  const { data: summary, isLoading: sumLoading } = useQuery({
    queryKey: ['ib-shadow-summary'],
    queryFn: api.getIBShadowSummary,
    refetchInterval: 60000,
  })
  const { data: logData, isLoading: logLoading } = useQuery({
    queryKey: ['ib-shadow-log'],
    queryFn: () => api.getIBShadowLog(50),
    refetchInterval: 60000,
  })

  const isLoading = sumLoading || logLoading
  const total = summary?.total_shadows || 0
  const entries = logData?.entries || []
  const errorEntries = entries.filter(e => e.ib_error)

  // Empty state — no shadow data at all
  if (!isLoading && total === 0 && !summary?.error) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <GitCompare size={20} style={{ color: 'var(--arcis-accent)' }} />
          <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)' }}>Broker Comparison</h2>
        </div>
        <div className="flex flex-col items-center justify-center py-16 gap-4"
          style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
          <GitCompare size={40} style={{ color: 'var(--arcis-text-muted)' }} />
          <div className="text-center">
            <p style={{ color: 'var(--arcis-text-secondary)', fontSize: 14, marginBottom: 8 }}>
              Shadow mode logs what IB would have done for each Alpaca trade.
            </p>
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--arcis-text-muted)' }}>
              Enable in settings.local.yaml: live_trading.ib.shadow_mode: true
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <GitCompare size={20} style={{ color: 'var(--arcis-accent)' }} />
          <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)' }}>Broker Comparison</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-block rounded-full" style={{
            width: 8, height: 8,
            background: summary?.shadow_mode_enabled ? 'var(--arcis-success)' : 'var(--arcis-text-muted)',
          }} />
          <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-secondary)', textTransform: 'uppercase' }}>
            {summary?.shadow_mode_enabled ? 'Active' : 'Inactive'}
          </span>
        </div>
      </div>
      <p style={{ fontSize: 13, color: 'var(--arcis-text-secondary)', marginTop: -8 }}>
        Comparing IB behavior against Alpaca execution
      </p>

      {/* KPI Cards */}
      {isLoading ? <LoadingSpinner /> : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <MetricCard label="Shadow Trades" value={total} />
            <MetricCard
              label="Gateway Uptime"
              value={`${(summary?.ib_connected_pct || 0).toFixed(1)}%`}
              delta={summary?.ib_connected_pct >= 90 ? 'healthy' : summary?.ib_connected_pct >= 70 ? 'degraded' : 'down'}
            />
            <MetricCard
              label="Contract Valid"
              value={`${(summary?.ib_contract_valid_pct || 0).toFixed(1)}%`}
            />
            <MetricCard
              label="BP Acceptance"
              value={`${(summary?.ib_would_accept_pct || 0).toFixed(1)}%`}
              delta={summary?.errors ? `${summary.errors} errors` : null}
            />
          </div>

          {/* Shadow Trade Log */}
          <div className="overflow-hidden" style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
            {entries.length === 0 ? (
              <EmptyState message="No shadow log entries" />
            ) : (
              <>
                <div className="flex items-center gap-4 px-3 py-2.5 text-xs" style={{ background: 'var(--arcis-bg-elevated)', borderBottom: '2px solid var(--arcis-border)' }}>
                  <span style={{ color: 'var(--arcis-text-secondary)' }}>Shadow Trade Log</span>
                  <span style={{ color: 'var(--arcis-text-muted)' }}>{logData?.total || entries.length} total</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm" style={{ tableLayout: 'auto' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                        <th className="py-2 px-2 text-left text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Time</th>
                        <th className="py-2 px-2 text-left text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Ticker</th>
                        <th className="py-2 px-2 text-left text-xs uppercase hidden md:table-cell" style={{ color: 'var(--arcis-text-secondary)' }}>Qty</th>
                        <th className="py-2 px-2 text-left text-xs uppercase hidden md:table-cell" style={{ color: 'var(--arcis-text-secondary)' }}>Entry</th>
                        <th className="py-2 px-2 text-left text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>IB OK</th>
                        <th className="py-2 px-2 text-left text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Contract</th>
                        <th className="py-2 px-2 text-left text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>BP OK</th>
                        <th className="py-2 px-2 text-left text-xs uppercase hidden md:table-cell" style={{ color: 'var(--arcis-text-secondary)' }}>Error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {entries.map((entry, i) => (
                        <tr key={entry.shadow_id || i}
                          style={{
                            borderBottom: '1px solid var(--arcis-border)',
                            background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)',
                          }}>
                          <td className="py-2.5 px-2 text-xs" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-secondary)' }}>
                            {formatTime(entry.created_at)}
                          </td>
                          <td className="py-2.5 px-2">
                            <span className="flex items-center gap-1.5 font-medium" style={{ color: 'var(--arcis-text-primary)' }}>
                              <TickerLogo ticker={entry.ticker} />
                              {entry.ticker}
                            </span>
                          </td>
                          <td className="py-2.5 px-2 hidden md:table-cell" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-primary)' }}>
                            {entry.quantity ?? '--'}
                          </td>
                          <td className="py-2.5 px-2 hidden md:table-cell" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-primary)' }}>
                            {entry.entry_price != null ? `$${entry.entry_price.toFixed(2)}` : '--'}
                          </td>
                          <td className="py-2.5 px-2"><StatusBadge ok={entry.ib_connected === 1} /></td>
                          <td className="py-2.5 px-2"><StatusBadge ok={entry.ib_contract_valid === 1} /></td>
                          <td className="py-2.5 px-2"><StatusBadge ok={entry.ib_would_accept === 1} /></td>
                          <td className="py-2.5 px-2 hidden md:table-cell text-xs" style={{ fontFamily: 'var(--font-mono)', color: entry.ib_error ? 'var(--arcis-danger)' : 'var(--arcis-text-muted)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {entry.ib_error || '--'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>

          {/* Error Log */}
          {errorEntries.length > 0 && (
            <div className="overflow-hidden" style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
              <div className="px-3 py-2.5 text-xs" style={{ background: 'var(--arcis-bg-elevated)', borderBottom: '2px solid var(--arcis-border)', color: 'var(--arcis-text-secondary)' }}>
                Error Log ({errorEntries.length})
              </div>
              <div className="divide-y" style={{ borderColor: 'var(--arcis-border)' }}>
                {errorEntries.slice(0, 10).map((entry, i) => (
                  <div key={entry.shadow_id || i} className="px-3 py-2 text-xs" style={{ fontFamily: 'var(--font-mono)' }}>
                    <span style={{ color: 'var(--arcis-text-muted)' }}>{formatTime(entry.created_at)}</span>
                    <span style={{ color: 'var(--arcis-text-secondary)', margin: '0 8px' }}>|</span>
                    <span style={{ color: 'var(--arcis-text-primary)', fontWeight: 500 }}>{entry.ticker}</span>
                    <span style={{ color: 'var(--arcis-text-secondary)', margin: '0 8px' }}>|</span>
                    <span style={{ color: 'var(--arcis-danger)' }}>{entry.ib_error}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
