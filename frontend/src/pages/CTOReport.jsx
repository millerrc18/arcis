import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'
import MetricCard from '../components/MetricCard'
import MetricTrend from '../components/MetricTrend'

function KpiCard({ label, value, target, good, minTrades, actualTrades }) {
  const needsMore = minTrades && actualTrades < minTrades
  return (
    <div className="arcis-card">
      <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>{label}</div>
      {needsMore ? (
        <>
          <div className="text-lg mt-1" style={{ color: 'var(--arcis-text-muted)', fontFamily: 'var(--font-mono)' }}>
            Requires {minTrades}+ trades
          </div>
          <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-muted)' }}>
            Currently: {actualTrades}
          </div>
        </>
      ) : (
        <>
          <div className="text-2xl font-medium mt-1 financial-data" style={{
            color: good === true ? 'var(--arcis-accent)' : good === false ? 'var(--arcis-danger)' : 'var(--arcis-text-primary)',
          }}>
            {value}
          </div>
          {target && <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>{target}</div>}
        </>
      )}
    </div>
  )
}

function SectionTable({ title, headers, rows }) {
  if (!rows || rows.length === 0) return null
  return (
    <div className="mb-6">
      <h2 className="text-sm font-medium mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>{title}</h2>
      <div className="arcis-card overflow-hidden" style={{ padding: 0 }}>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: '1px solid var(--arcis-border)' }}>
              {headers.map((h, i) => (
                <th key={i} className={`p-3 ${i === 0 ? 'text-left' : 'text-right'}`} style={{ color: 'var(--arcis-text-secondary)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--arcis-border)', background: i % 2 === 0 ? 'transparent' : 'var(--arcis-bg-elevated)' }}>
                {row.map((cell, j) => {
                  const color = cell.color
                    ? (cell.color.includes('emerald') || cell.color.includes('green') ? 'var(--arcis-accent)' : cell.color.includes('red') ? 'var(--arcis-danger)' : undefined)
                    : undefined
                  return (
                    <td key={j} className={`p-3 ${j === 0 ? '' : 'text-right'}`} style={{ color: j === 0 ? 'var(--arcis-text-primary)' : color }}>
                      {cell.text != null ? cell.text : cell}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const PERIOD_OPTIONS = [
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
  { label: 'All', days: 365 },
]

export default function CTOReport() {
  const [days, setDays] = useState(30)
  const { data, isLoading, error } = useQuery({
    queryKey: ['cto-report', days],
    queryFn: () => api.getCtoReport(days),
    refetchInterval: 120000,
  })

  if (isLoading) return <LoadingSpinner />
  if (error) return (
    <div className="text-center py-12">
      <p className="mb-4" style={{ color: 'var(--arcis-danger)' }}>Failed to load CTO report</p>
      <button onClick={() => window.location.reload()}
        className="px-4 py-2 text-white rounded text-sm" style={{ background: 'var(--arcis-accent)' }}>Retry</button>
    </div>
  )
  if (!data) return <EmptyState message="No report data available" />

  // Detect backend error responses that pass as valid data
  if (data?.error) return (
    <div className="max-w-4xl mx-auto space-y-6">
      <h1 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)' }}>CTO performance report</h1>
      <div className="arcis-card" style={{ borderColor: 'var(--arcis-danger)' }}>
        <div className="text-sm font-medium mb-2" style={{ color: 'var(--arcis-danger)' }}>Report generation failed</div>
        <pre className="text-xs overflow-auto p-2 rounded" style={{ background: 'var(--arcis-bg-surface)', color: 'var(--arcis-text-secondary)' }}>
          {data.error}
        </pre>
        <p className="text-xs mt-3" style={{ color: 'var(--arcis-text-muted)' }}>
          This usually means a required database table is missing on the cloud. Run the migration script to fix.
        </p>
      </div>
    </div>
  )

  const period = data?.report_period || {}
  const kpis = data?.headline_kpis || {}
  const ts = data?.trade_summary || {}
  const status = data?.system_status || {}

  const sharpe = kpis?.sharpe_ratio ?? 0
  const winRate = kpis?.win_rate ?? 0
  const maxDD = kpis?.max_drawdown_pct ?? 0
  const cal = kpis?.confidence_calibration ?? 0
  const rubric = kpis?.avg_rubric_score ?? null
  const tradesClosed = ts?.trades_closed ?? 0

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)' }}>CTO performance report</h1>
          <p className="text-sm" style={{ color: 'var(--arcis-text-secondary)' }}>
            {period?.start || 'N/A'} to {period?.end || 'N/A'} | {status?.model_version || 'base'} | {status?.dataset_size ?? 0} examples
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Period selector */}
          <div className="flex rounded overflow-hidden" style={{ border: '1px solid var(--arcis-border)' }}>
            {PERIOD_OPTIONS.map(opt => (
              <button
                key={opt.days}
                onClick={() => setDays(opt.days)}
                className="px-3 py-1.5 text-xs transition-colors"
                style={{
                  background: days === opt.days ? 'var(--arcis-accent)' : 'var(--arcis-bg-surface)',
                  color: days === opt.days ? '#fff' : 'var(--arcis-text-secondary)',
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => navigator.clipboard.writeText(JSON.stringify(data, null, 2))}
            className="px-3 py-1.5 text-xs rounded transition-colors"
            style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-primary)' }}
          >
            Copy JSON
          </button>
        </div>
      </div>

      {/* Phase progress bar */}
      <div className="arcis-card">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium" style={{ color: 'var(--arcis-text-primary)' }}>Phase 1 Gate Progress</span>
          <span className="text-sm financial-data" style={{ color: tradesClosed >= 50 ? 'var(--arcis-success)' : 'var(--arcis-accent)' }}>
            {tradesClosed}/50 trades
          </span>
        </div>
        <div className="h-3 rounded-full overflow-hidden" style={{ background: 'var(--arcis-border)' }}>
          <div className="h-full rounded-full transition-all" style={{
            background: tradesClosed >= 50 ? 'var(--arcis-success)' : 'var(--arcis-accent)',
            width: `${Math.min(100, (tradesClosed / 50) * 100)}%`,
          }} />
        </div>
      </div>

      {/* Win rate callout for small sample */}
      {winRate === 1 && tradesClosed < 10 && tradesClosed > 0 && (
        <div className="rounded-lg p-3 text-sm" style={{ background: 'rgba(59, 130, 246, 0.1)', border: '1px solid rgba(59, 130, 246, 0.25)', color: 'var(--arcis-text-secondary)' }}>
          100% win rate on {tradesClosed} trade{tradesClosed !== 1 ? 's' : ''} \u2014 early results, need 50+ trades for statistical significance
        </div>
      )}

      {/* Headline KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <KpiCard
          label="Sharpe ratio"
          value={sharpe.toFixed(2)}
          target="> 0.5 (P1) | > 1.0 (P3)"
          good={tradesClosed >= 5 ? (sharpe > 0.5 ? true : sharpe < 0 ? false : null) : null}
        />
        <KpiCard
          label="Win rate"
          value={`${(winRate * 100).toFixed(1)}%`}
          target="> 45%"
          good={tradesClosed >= 5 ? (winRate > 0.45 ? true : false) : null}
        />
        <KpiCard
          label="Max drawdown"
          value={`${maxDD.toFixed(1)}%`}
          target="< 15%"
          good={tradesClosed >= 5 ? (maxDD < 15 ? true : false) : null}
        />
        <KpiCard
          label="Confidence cal."
          value={cal !== 0 ? cal.toFixed(3) : 'Pending'}
          target="> 0.3"
          minTrades={10}
          actualTrades={tradesClosed}
          good={tradesClosed >= 10 ? (cal > 0.3 ? true : cal < 0 ? false : null) : null}
        />
        <KpiCard
          label="Rubric score"
          value={rubric != null && rubric > 0 ? `${rubric.toFixed(1)}/5` : 'Quality scoring not yet applied'}
          target="> 3.5"
          good={rubric != null && rubric > 0 ? (rubric >= 3.5 ? true : rubric < 2.5 ? false : null) : null}
        />
      </div>

      {/* Trade summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard label="Trades closed" value={tradesClosed} />
        <MetricCard label="Trades open" value={ts?.trades_open ?? 0} />
        <MetricCard label="Profit factor" value={ts?.profit_factor ?? 'n/a'} />
        <MetricCard label="Expectancy" value={ts?.expectancy_dollars != null ? `$${Number(ts.expectancy_dollars).toFixed(2)}` : 'n/a'} />
        <MetricCard label="Total P&L" value={ts?.total_pnl != null ? `$${Number(ts.total_pnl).toFixed(2)}` : 'n/a'} />
        <MetricCard label="Avg winner" value={ts?.avg_winner_pct != null ? `${Number(ts.avg_winner_pct).toFixed(1)}%` : 'n/a'} />
        <MetricCard label="Avg loser" value={ts?.avg_loser_pct != null ? `${Number(ts.avg_loser_pct).toFixed(1)}%` : 'n/a'} />
        <MetricCard label="Max consec. losses" value={ts?.max_consecutive_losses ?? 0} />
      </div>

      {/* By score band */}
      {data.by_score_band && Object.keys(data.by_score_band).length > 0 && (
        <SectionTable
          title="Performance by score band"
          headers={['Band', 'Trades', 'Win rate', 'Avg P&L']}
          rows={Object.entries(data.by_score_band).map(([band, s]) => [
            band,
            s.trades || 0,
            s.trades > 0 ? `${(s.win_rate * 100).toFixed(0)}%` : 'n/a',
            { text: s.avg_pnl != null ? `${s.avg_pnl >= 0 ? '+' : ''}${s.avg_pnl.toFixed(1)}%` : 'n/a', color: (s.avg_pnl || 0) >= 0 ? 'emerald' : 'red' },
          ])}
        />
      )}

      {/* By exit reason */}
      {data.by_exit_reason && Object.keys(data.by_exit_reason).length > 0 && (
        <SectionTable
          title="By exit reason"
          headers={['Reason', 'Count', 'Avg P&L']}
          rows={Object.entries(data.by_exit_reason).map(([reason, s]) => [
            reason,
            s.count || 0,
            { text: `${s.avg_pnl >= 0 ? '+' : ''}${s.avg_pnl.toFixed(1)}%`, color: (s.avg_pnl || 0) >= 0 ? 'emerald' : 'red' },
          ])}
        />
      )}

      {/* By sector */}
      {data.by_sector && Object.keys(data.by_sector).length > 0 && (
        <SectionTable
          title="By sector"
          headers={['Sector', 'Trades', 'Win rate']}
          rows={Object.entries(data.by_sector)
            .sort((a, b) => (b[1].trades || 0) - (a[1].trades || 0))
            .map(([sector, s]) => [
              sector,
              s.trades || 0,
              s.trades > 0 ? `${(s.win_rate * 100).toFixed(0)}%` : 'n/a',
            ])}
        />
      )}

      {/* By regime */}
      {data.by_regime && Object.keys(data.by_regime).length > 0 && (
        <SectionTable
          title="By market regime"
          headers={['Regime', 'Trades', 'Win rate']}
          rows={Object.entries(data.by_regime)
            .sort((a, b) => (b[1].trades || 0) - (a[1].trades || 0))
            .map(([regime, s]) => [
              regime,
              s.trades || 0,
              s.trades > 0 ? `${(s.win_rate * 100).toFixed(0)}%` : 'n/a',
            ])}
        />
      )}

      {/* Confidence calibration */}
      {data.confidence_calibration && (
        <div className="mb-6">
          <h2 className="text-sm font-medium mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>Confidence calibration</h2>
          {tradesClosed < 10 ? (
            <div className="arcis-card text-center">
              <div className="text-sm" style={{ color: 'var(--arcis-text-muted)' }}>
                Requires 10+ trades with conviction scores recorded ({tradesClosed} available)
              </div>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-3 gap-3 mb-3">
                {Object.entries(data?.confidence_calibration?.by_conviction_band || {}).map(([band, s]) => (
                  <div key={band} className="arcis-card text-center" style={{ padding: '12px' }}>
                    <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Conviction {band}</div>
                    <div className="text-lg mt-1 financial-data">{s.trades > 0 ? `${(s.win_rate * 100).toFixed(0)}%` : 'n/a'}</div>
                    <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>{s.trades} trades</div>
                  </div>
                ))}
              </div>
              <div className="text-sm" style={{ color: 'var(--arcis-text-secondary)' }}>
                Correlation: {data?.confidence_calibration?.correlation_with_outcomes?.toFixed(3) || 'n/a'}
                {data?.confidence_calibration?.is_calibrated != null && (
                  <span className="ml-3">
                    {data.confidence_calibration.is_calibrated
                      ? <span style={{ color: 'var(--arcis-accent)' }}>Calibrated</span>
                      : <span style={{ color: 'var(--arcis-warning)' }}>Not calibrated</span>}
                  </span>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {/* Execution analysis */}
      {data?.execution_analysis && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MetricCard label="Avg hold (days)" value={data.execution_analysis?.avg_hold_period_days?.toFixed(1) || 'n/a'} />
          <MetricCard label="Targets hit" value={data.execution_analysis?.targets_hit_pct != null ? `${data.execution_analysis.targets_hit_pct.toFixed(1)}%` : 'n/a'} />
          <MetricCard label="Timeouts" value={data.execution_analysis?.timeout_pct != null ? `${data.execution_analysis.timeout_pct.toFixed(1)}%` : 'n/a'} />
          <MetricCard label="Avg MFE (winners)" value={data.execution_analysis?.avg_mfe_winners != null ? `$${data.execution_analysis.avg_mfe_winners.toFixed(2)}` : 'n/a'} />
        </div>
      )}

      {/* Fund metrics - only show when enough data */}
      {data.fund_metrics && tradesClosed >= 20 && (
        <div className="mb-6">
          <h2 className="text-sm font-medium mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>Fund metrics</h2>
          <div className="grid grid-cols-3 gap-3">
            <MetricCard label="Sortino ratio" value={data.fund_metrics.sortino_ratio != null ? data.fund_metrics.sortino_ratio : 'n/a'} />
            <MetricCard label="Calmar ratio" value={data.fund_metrics.calmar_ratio != null ? data.fund_metrics.calmar_ratio.toFixed(2) : 'n/a'} />
            <MetricCard label="VaR 95%" value={data.fund_metrics.var_95 != null ? `${data.fund_metrics.var_95.toFixed(2)}%` : 'n/a'} />
            <MetricCard label="Monthly batting avg" value={data.fund_metrics.monthly_batting_avg != null ? `${data.fund_metrics.monthly_batting_avg.toFixed(1)}%` : 'n/a'} />
            <MetricCard label="Avg hold period" value={data.fund_metrics.avg_hold_period_days != null ? `${data.fund_metrics.avg_hold_period_days.toFixed(1)}d` : 'n/a'} />
            <MetricCard label="Return skewness" value={data.fund_metrics.return_skewness != null ? data.fund_metrics.return_skewness.toFixed(2) : 'n/a'} />
            <MetricCard label="Best trade" value={data.fund_metrics.best_trade_pct != null ? `${data.fund_metrics.best_trade_pct >= 0 ? '+' : ''}${data.fund_metrics.best_trade_pct.toFixed(2)}%` : 'n/a'} />
            <MetricCard label="Worst trade" value={data.fund_metrics.worst_trade_pct != null ? `${data.fund_metrics.worst_trade_pct.toFixed(2)}%` : 'n/a'} />
            <MetricCard label="Total return" value={data.fund_metrics.total_return_pct != null ? `${data.fund_metrics.total_return_pct >= 0 ? '+' : ''}${data.fund_metrics.total_return_pct.toFixed(2)}%` : 'n/a'} />
          </div>
        </div>
      )}

      {/* Fund metrics notice when not enough data */}
      {data.fund_metrics && tradesClosed < 20 && (
        <div className="arcis-card text-center">
          <h2 className="text-sm font-medium mb-2" style={{ color: 'var(--arcis-text-secondary)' }}>Fund metrics</h2>
          <div className="text-sm" style={{ color: 'var(--arcis-text-muted)' }}>
            Sortino, Calmar, beta, alpha require 20+ closed trades ({tradesClosed} available)
          </div>
        </div>
      )}

      {/* Metric trend charts */}
      <MetricTrend />
    </div>
  )
}
