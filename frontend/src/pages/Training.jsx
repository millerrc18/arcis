import { useState, useMemo } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../api'
import { formatRelativeTime, formatDate } from '../utils/formatTimestamp'
import MetricCard from '../components/MetricCard'
import StatusBadge from '../components/StatusBadge'
import LoadingSpinner from '../components/LoadingSpinner'
import CollectorGrid from '../components/CollectorGrid'
import PipelineStatus from '../components/PipelineStatus'

const OUTCOME_COLORS = {
  WIN: 'var(--arcis-success)',
  LOSS: 'var(--arcis-danger)',
  TIMEOUT: 'var(--arcis-warning)',
  PASS: 'var(--arcis-text-muted)',
}
const OUTCOME_TARGETS = { WIN: 40, LOSS: 25, TIMEOUT: 5, PASS: 15 }

export default function Training() {
  const { data: status, isLoading } = useQuery({ queryKey: ['training-status'], queryFn: api.getTrainingStatus, refetchInterval: 60000 })
  const { data: history } = useQuery({ queryKey: ['training-versions'], queryFn: api.getTrainingVersions, refetchInterval: 60000 })
  const { data: collectorStats } = useQuery({ queryKey: ['data-collection-stats'], queryFn: api.getDataCollectionStats, refetchInterval: 300000 })
  const [toast, setToast] = useState(null)
  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(null), 3000) }

  const trainMutation = useMutation({
    mutationFn: api.triggerTrainPipeline,
    onSuccess: () => showToast('Training pipeline started (this will take a while)...'),
    onError: (e) => showToast(`Training failed: ${e.message}`),
  })
  const scoreMutation = useMutation({
    mutationFn: api.triggerScore,
    onSuccess: () => showToast('Scoring started...'),
    onError: (e) => showToast(`Scoring failed: ${e.message}`),
  })

  const versions = history?.versions || []

  // Compute outcome distribution — derive types dynamically from data
  const outcomes = useMemo(() => {
    const total = status?.dataset_total || 0
    const hasOutcomes = status?.outcome_counts != null
    if (!hasOutcomes || total === 0) return null
    const counts = status.outcome_counts
    const knownTypes = ['WIN', 'LOSS', 'TIMEOUT', 'PASS']
    const dataTypes = [...new Set([
      ...Object.keys(counts).map(k => k.toUpperCase()),
      ...knownTypes,
    ])]
    return dataTypes.map(type => ({
      type,
      count: counts[type] || counts[type.toLowerCase()] || 0,
      pct: total > 0 ? ((counts[type] || counts[type.toLowerCase()] || 0) / total * 100) : 0,
    })).filter(o => o.count > 0 || knownTypes.includes(o.type))
  }, [status])

  // Source breakdown
  const sources = useMemo(() => {
    if (!status?.source_counts) return null
    return Object.entries(status.source_counts)
      .map(([name, count]) => ({ name: name.replace(/_/g, ' '), count }))
      .sort((a, b) => b.count - a.count)
  }, [status])

  // Ticker coverage
  const tickerCoverage = status?.ticker_coverage || null
  const regimeCoverage = status?.regime_coverage || null
  const recentExamples = status?.recent_examples || null

  if (isLoading) return <LoadingSpinner />

  const total = status?.dataset_total || 0
  const thisWeek = status?.examples_this_week ?? status?.new_since_last_train ?? 0
  const avgQuality = status?.avg_quality_score

  return (
    <div className="space-y-6">
      {toast && (
        <div className="fixed top-4 right-4 z-50 rounded-lg px-4 py-2 text-sm shadow-lg" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-primary)' }}>
          {toast}
        </div>
      )}

      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)' }}>Training Pipeline</h2>
        <div className="flex items-center gap-2">
          <button onClick={() => scoreMutation.mutate()} disabled={scoreMutation.isPending}
            className="px-3 py-1.5 text-xs rounded-md disabled:opacity-50 transition-colors"
            style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-primary)' }}>
            {scoreMutation.isPending ? 'Scoring...' : 'Score Unscored'}
          </button>
          <button onClick={() => { if (confirm('This will run the full training pipeline and may take a long time. Continue?')) trainMutation.mutate() }}
            disabled={trainMutation.isPending}
            className="px-3 py-1.5 text-xs rounded-md text-white disabled:opacity-50 transition-colors"
            style={{ background: 'var(--arcis-accent)' }}>
            {trainMutation.isPending ? 'Training...' : 'Run Training Pipeline'}
          </button>
        </div>
      </div>

      {/* Hero metrics */}
      {/* Fix for #247 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="arcis-card text-center" style={{ padding: '20px' }}>
          <div className="text-3xl font-bold financial-data" style={{ color: 'var(--arcis-text-primary)' }}>{total.toLocaleString()}</div>
          <div className="text-xs uppercase tracking-wide mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>Total Examples</div>
        </div>
        <MetricCard label="This Week" value={thisWeek} />
        <MetricCard label="Avg Quality" value={avgQuality != null && avgQuality > 0 ? avgQuality.toFixed(1) : 'Not scored'} />
        <MetricCard label="Active Model" value={status?.model_name || 'base'} />
      </div>

      {/* Data Collectors */}
      <CollectorGrid stats={collectorStats} />

      {/* Pipeline Status */}
      <PipelineStatus status={status} />

      {/* Outcome distribution */}
      {outcomes ? (
        <div className="arcis-card">
          <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>Outcome Distribution</h3>
          <div className="flex gap-0.5 h-6 rounded-full overflow-hidden mb-3" style={{ background: 'var(--arcis-border)' }}>
            {outcomes.filter(o => o.pct > 0).map(o => (
              <div key={o.type} style={{ width: `${o.pct}%`, background: OUTCOME_COLORS[o.type], minWidth: o.pct > 0 ? 4 : 0 }}
                title={`${o.type}: ${o.count} (${o.pct.toFixed(1)}%)`} />
            ))}
          </div>
          <div className="flex flex-wrap gap-4 text-xs">
            {outcomes.map(o => (
              <div key={o.type} className="flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full" style={{ background: OUTCOME_COLORS[o.type] }} />
                <span style={{ color: 'var(--arcis-text-secondary)' }}>{o.type}: {o.count} ({o.pct.toFixed(1)}%)</span>
              </div>
            ))}
          </div>
          {/* Target vs actual */}
          <div className="mt-3 pt-3" style={{ borderTop: '1px solid var(--arcis-border)' }}>
            <div className="text-xs mb-2" style={{ color: 'var(--arcis-text-muted)' }}>v2 targets vs actual</div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
              {outcomes.map(o => (
                <div key={o.type} className="flex justify-between px-2 py-1 rounded" style={{ background: 'var(--arcis-bg-elevated)' }}>
                  <span style={{ color: 'var(--arcis-text-secondary)' }}>{o.type}</span>
                  <span className="financial-data">
                    <span style={{ color: Math.abs(o.pct - (OUTCOME_TARGETS[o.type] || 0)) < 10 ? 'var(--arcis-success)' : 'var(--arcis-warning)' }}>
                      {o.pct.toFixed(0)}%
                    </span>
                    <span style={{ color: 'var(--arcis-text-muted)' }}> / {OUTCOME_TARGETS[o.type] || '?'}%</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="arcis-card">
          <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>Outcome Distribution</h3>
          <div className="text-sm py-4 text-center" style={{ color: 'var(--arcis-text-muted)' }}>
            Outcome data pending migration
          </div>
        </div>
      )}

      {/* Dataset breakdown by source */}
      <div className="arcis-card">
        <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>Source Breakdown</h3>
        {sources ? (
          <div className="space-y-2">
            {sources.map(s => {
              const pct = total > 0 ? (s.count / total * 100) : 0
              return (
                <div key={s.name} className="flex items-center gap-3">
                  <span className="text-xs w-32 capitalize" style={{ color: 'var(--arcis-text-secondary)' }}>{s.name}</span>
                  <div className="flex-1 h-3 rounded-full overflow-hidden" style={{ background: 'var(--arcis-border)' }}>
                    <div className="h-full rounded-full" style={{ width: `${pct}%`, background: 'var(--arcis-accent)' }} />
                  </div>
                  <span className="text-xs financial-data w-16 text-right" style={{ color: 'var(--arcis-text-primary)' }}>{s.count}</span>
                </div>
              )
            })}
          </div>
        ) : (
          <>
            <div className="flex gap-1 h-4 rounded-full overflow-hidden" style={{ background: 'var(--arcis-border)' }}>
              {total > 0 && (
                <>
                  <div style={{ width: `${((status?.dataset_synthetic || 0) / total) * 100}%`, background: 'var(--chart-1)' }} />
                  <div style={{ width: `${((status?.dataset_wins || 0) / total) * 100}%`, background: 'var(--arcis-success)' }} />
                  <div style={{ width: `${((status?.dataset_losses || 0) / total) * 100}%`, background: 'var(--arcis-danger)' }} />
                </>
              )}
            </div>
            <div className="flex gap-6 mt-2 text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>
              <span><span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: 'var(--chart-1)' }} />Synthetic: {status?.dataset_synthetic || 0}</span>
              <span><span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: 'var(--arcis-success)' }} />Wins: {status?.dataset_wins || 0}</span>
              <span><span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: 'var(--arcis-danger)' }} />Losses: {status?.dataset_losses || 0}</span>
            </div>
          </>
        )}
      </div>

      {/* Ticker + Regime coverage */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Ticker coverage */}
        <div className="arcis-card">
          <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>Ticker Coverage</h3>
          {tickerCoverage ? (
            <>
              <div className="text-lg font-medium financial-data mb-2" style={{ color: 'var(--arcis-text-primary)' }}>
                {tickerCoverage.covered}/{tickerCoverage.total} tickers covered
              </div>
              <div className="h-3 rounded-full overflow-hidden" style={{ background: 'var(--arcis-border)' }}>
                <div className="h-full rounded-full" style={{ width: `${tickerCoverage.total > 0 ? (tickerCoverage.covered / tickerCoverage.total * 100) : 0}%`, background: 'var(--arcis-accent)' }} />
              </div>
            </>
          ) : (
            <div className="text-sm" style={{ color: 'var(--arcis-text-muted)' }}>Coverage data not available</div>
          )}
        </div>

        {/* Regime coverage */}
        <div className="arcis-card">
          <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>Regime Coverage</h3>
          {regimeCoverage ? (
            <div className="flex flex-wrap gap-2">
              {Object.entries(regimeCoverage).map(([regime, count]) => (
                <div key={regime} className="px-2 py-1 rounded text-xs" style={{
                  background: count > 0 ? 'rgba(59, 130, 246, 0.15)' : 'var(--arcis-bg-elevated)',
                  border: `1px solid ${count > 0 ? 'rgba(59, 130, 246, 0.3)' : 'var(--arcis-border)'}`,
                  color: count > 0 ? 'var(--arcis-accent)' : 'var(--arcis-text-muted)',
                }}>
                  {regime}: {count > 0 ? count : 'gap'}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm" style={{ color: 'var(--arcis-text-muted)' }}>Regime data not available</div>
          )}
        </div>
      </div>

      {/* Recent examples */}
      {recentExamples && recentExamples.length > 0 && (
        <div className="arcis-card">
          <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>Recent Examples</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                  <th className="py-2 px-2 text-left text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Ticker</th>
                  <th className="py-2 px-2 text-left text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Source</th>
                  <th className="py-2 px-2 text-left text-xs uppercase" style={{ color: 'var(--arcis-text-secondary)' }}>Outcome</th>
                  <th className="py-2 px-2 text-right text-xs uppercase hidden md:table-cell" style={{ color: 'var(--arcis-text-secondary)' }}>Quality</th>
                  <th className="py-2 px-2 text-right text-xs uppercase hidden md:table-cell" style={{ color: 'var(--arcis-text-secondary)' }}>Created</th>
                </tr>
              </thead>
              <tbody>
                {recentExamples.slice(0, 10).map((ex, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--arcis-border)', background: i % 2 === 0 ? 'transparent' : 'var(--arcis-bg-elevated)' }}>
                    <td className="py-1.5 px-2 font-medium" style={{ color: 'var(--arcis-text-primary)' }}>{ex.ticker || '--'}</td>
                    <td className="py-1.5 px-2 capitalize text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>{(ex.source || '--').replace(/_/g, ' ')}</td>
                    <td className="py-1.5 px-2">
                      {ex.outcome_type ? (
                        <span className="px-1.5 py-0.5 rounded text-xs" style={{
                          background: OUTCOME_COLORS[ex.outcome_type] ? `${OUTCOME_COLORS[ex.outcome_type]}20` : 'var(--arcis-bg-elevated)',
                          color: OUTCOME_COLORS[ex.outcome_type] || 'var(--arcis-text-secondary)',
                        }}>
                          {ex.outcome_type}
                        </span>
                      ) : '--'}
                    </td>
                    <td className="py-1.5 px-2 text-right financial-data hidden md:table-cell" style={{ color: 'var(--arcis-text-primary)' }}>
                      {ex.quality_score != null ? ex.quality_score.toFixed(1) : '--'}
                    </td>
                    <td className="py-1.5 px-2 text-right text-xs hidden md:table-cell" style={{ color: 'var(--arcis-text-muted)' }}>
                      {ex.created_at?.slice(0, 10) || '--'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Training progress */}
      <div className="arcis-card">
        <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>Next Training</h3>
        <div className="h-3 rounded-full overflow-hidden mb-2" style={{ background: 'var(--arcis-border)' }}>
          <div className="h-full rounded-full transition-all" style={{ background: 'var(--arcis-accent)', width: `${Math.min(100, ((status?.new_since_last_train || 0) / 50) * 100)}%` }} />
        </div>
        <p className="text-sm" style={{ color: 'var(--arcis-text-secondary)' }}>{status?.train_reason}</p>
        <p className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>Rollback: {status?.rollback_status}</p>
      </div>

      {/* Version history */}
      <div className="arcis-card">
        <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>Version History</h3>
        <div className="space-y-3">
          {versions.map((v, i) => (
            <div key={v.version_id || i} className="flex items-center gap-4 border-l-2 pl-4 py-2"
              style={{ borderColor: v.status === 'active' ? 'var(--arcis-success)' : v.status === 'rolled_back' ? 'var(--arcis-danger)' : 'var(--arcis-border)' }}>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium" style={{ color: 'var(--arcis-text-primary)' }}>{v.version_name}</span>
                  <StatusBadge text={v.status} variant={v.status === 'active' ? 'success' : v.status === 'rolled_back' ? 'danger' : 'neutral'} />
                </div>
                <div className="text-xs mt-0.5" style={{ color: 'var(--arcis-text-secondary)' }}>{v.created_at ? v.created_at.slice(0, 10) : '--'}</div>
              </div>
              <div className="text-sm text-right" style={{ fontFamily: 'var(--font-mono)' }}>
                <div style={{ color: 'var(--arcis-text-primary)' }}>{v.training_examples_count || '--'} examples</div>
                <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>
                  {v.trade_count > 0 ? `${v.win_rate?.toFixed(1)}% WR | $${v.expectancy?.toFixed(2)} exp` : 'No trades yet'}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
