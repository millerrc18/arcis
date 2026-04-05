import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import MetricCard from '../components/MetricCard'
import StatusBadge from '../components/StatusBadge'
import LoadingSpinner from '../components/LoadingSpinner'

const MONO = { fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }
const MODEL_COLORS = ['#6366F1', '#F59E0B', '#10B981', '#EF4444', '#8B5CF6', '#EC4899']

function PnlValue({ value, prefix = '$' }) {
  if (value == null) return <span style={{ ...MONO, color: 'var(--arcis-text-muted)' }}>—</span>
  const color = value > 0 ? 'var(--arcis-success)' : value < 0 ? 'var(--arcis-danger)' : 'var(--arcis-text-secondary)'
  return <span style={{ ...MONO, color }}>{prefix}{value.toFixed(2)}</span>
}

function DeltaArrow({ value, suffix = '' }) {
  if (value == null) return null
  const color = value > 0 ? 'var(--arcis-success)' : value < 0 ? 'var(--arcis-danger)' : 'var(--arcis-text-secondary)'
  const arrow = value > 0 ? '↑' : value < 0 ? '↓' : '→'
  return <span style={{ ...MONO, color, fontSize: 12 }}>{arrow}{Math.abs(value).toFixed(2)}{suffix}</span>
}

function statusVariant(status) {
  if (status === 'active') return 'success'
  if (status === 'retired') return 'neutral'
  if (status === 'testing') return 'warning'
  return 'neutral'
}

export default function ModelPerformance() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['model-performance'],
    queryFn: api.getModelPerformance,
    refetchInterval: 120000,
  })
  const [sortKey, setSortKey] = useState('trades')
  const [sortAsc, setSortAsc] = useState(false)

  const activeModel = useMemo(() => {
    if (!data?.models) return null
    return data.models.find(m => m.status === 'active') || data.models[0] || null
  }, [data])

  const sortedModels = useMemo(() => {
    if (!data?.models) return []
    return [...data.models].sort((a, b) => {
      const av = sortKey === 'version' ? a.version : (a.live_metrics?.[sortKey] ?? 0)
      const bv = sortKey === 'version' ? b.version : (b.live_metrics?.[sortKey] ?? 0)
      if (sortKey === 'version') return sortAsc ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av))
      return sortAsc ? av - bv : bv - av
    })
  }, [data, sortKey, sortAsc])

  // Merge equity curves from all models for chart
  const equityData = useMemo(() => {
    if (!data?.models) return []
    const dateMap = {}
    data.models.forEach(m => {
      (m.equity_curve || []).forEach(pt => {
        if (!pt.date) return
        if (!dateMap[pt.date]) dateMap[pt.date] = { date: pt.date }
        dateMap[pt.date][m.version] = pt.cumulative_pnl
      })
    })
    return Object.values(dateMap).sort((a, b) => a.date.localeCompare(b.date))
  }, [data])

  const modelVersions = useMemo(() => (data?.models || []).filter(m => (m.equity_curve || []).length > 0).map(m => m.version), [data])

  if (isLoading) return <LoadingSpinner />
  if (error) return <div className="arcis-card" style={{ padding: 20, color: 'var(--arcis-danger)' }}>Failed to load model performance: {error.message}</div>
  if (!data) return <div className="arcis-card" style={{ padding: 20 }}>No model performance data available.</div>

  const comp = data.comparison?.current_vs_previous || {}
  const canary = data.canary_comparison || {}
  const am = activeModel?.live_metrics || {}

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Section 1: Active Model Summary */}
      <div className="arcis-card" style={{ padding: '14px 16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: 'var(--arcis-text-primary)' }}>
              {activeModel?.version || 'No Model'}
            </h2>
            <div style={{ fontSize: 12, color: 'var(--arcis-text-secondary)', marginTop: 2 }}>
              Created {activeModel?.created_at || '—'} · {activeModel?.training_examples || 0} training examples
              · Holdout: <span style={MONO}>{activeModel?.holdout_score != null ? activeModel.holdout_score.toFixed(2) : '—'}</span>
            </div>
          </div>
          <StatusBadge text={activeModel?.status || 'unknown'} variant={statusVariant(activeModel?.status)} />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 8 }}>
          <MetricCard label="Trades" value={am.trades ?? 0} />
          <MetricCard label="Win Rate" value={am.win_rate != null ? (am.win_rate * 100).toFixed(1) : '—'} suffix="%" delta={comp.wr_delta != null ? +(comp.wr_delta * 100).toFixed(1) : undefined} />
          <MetricCard label="Profit Factor" value={am.profit_factor ?? '—'} delta={comp.pf_delta} />
          <MetricCard label="Sharpe" value={am.sharpe_ratio ?? '—'} delta={comp.sharpe_delta} />
          <MetricCard label="Max DD" value={am.max_drawdown_pct ?? '—'} suffix="%" />
          <MetricCard label="Expectancy" value={am.expectancy_dollars ?? '—'} prefix="$" />
          <MetricCard label="Avg Hold" value={am.avg_holding_days ?? '—'} suffix="d" />
          <MetricCard label="Total P&L" value={am.total_pnl_dollars != null ? am.total_pnl_dollars.toFixed(2) : '—'} prefix="$" />
        </div>
      </div>

      {/* Section 2: Comparison Verdict */}
      {comp.previous && (
        <div className="arcis-card" style={{ padding: '12px 16px' }}>
          <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 500, color: 'var(--arcis-text-secondary)', marginBottom: 6 }}>
            Version Comparison
          </div>
          <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ ...MONO, fontSize: 13 }}>{comp.current} vs {comp.previous}</span>
            <span>Sharpe: <DeltaArrow value={comp.sharpe_delta} /></span>
            <span>WR: <DeltaArrow value={comp.wr_delta != null ? comp.wr_delta * 100 : null} suffix="%" /></span>
            <span>PF: <DeltaArrow value={comp.pf_delta} /></span>
            <StatusBadge
              text={comp.verdict === 'current_improved' ? 'Improved' : comp.verdict === 'current_regressed' ? 'Regressed' : comp.verdict === 'no_significant_difference' ? 'No Change' : 'Insufficient Data'}
              variant={comp.verdict === 'current_improved' ? 'success' : comp.verdict === 'current_regressed' ? 'danger' : 'neutral'}
            />
          </div>
        </div>
      )}

      {/* Section 3: Per-Model Comparison Table */}
      <div className="arcis-card" style={{ padding: '14px 16px', overflowX: 'auto' }}>
        <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 500, color: 'var(--arcis-text-secondary)', marginBottom: 8 }}>
          All Model Versions
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--arcis-border)' }}>
              {[
                { key: 'version', label: 'Version' },
                { key: 'trades', label: 'Trades' },
                { key: 'win_rate', label: 'WR' },
                { key: 'profit_factor', label: 'PF' },
                { key: 'sharpe_ratio', label: 'Sharpe' },
                { key: 'max_drawdown_pct', label: 'Max DD' },
                { key: 'expectancy_dollars', label: 'Expect $' },
                { key: 'total_pnl_dollars', label: 'Total P&L' },
              ].map(col => (
                <th key={col.key}
                  onClick={() => { if (sortKey === col.key) { setSortAsc(!sortAsc) } else { setSortKey(col.key); setSortAsc(false) } }}
                  style={{ padding: '6px 8px', textAlign: col.key === 'version' ? 'left' : 'right', cursor: 'pointer', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--arcis-text-secondary)', fontWeight: 500, whiteSpace: 'nowrap' }}>
                  {col.label} {sortKey === col.key ? (sortAsc ? '▲' : '▼') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedModels.map((m, i) => {
              const lm = m.live_metrics || {}
              const isActive = m.status === 'active'
              return (
                <tr key={m.version} style={{
                  borderBottom: '1px solid var(--arcis-border)',
                  background: isActive ? 'var(--arcis-accent-muted)' : 'transparent'
                }}>
                  <td style={{ padding: '6px 8px', ...MONO, fontWeight: isActive ? 600 : 400 }}>
                    {m.version} {isActive && <StatusBadge text="active" variant="success" />}
                  </td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', ...MONO }}>{lm.trades ?? 0}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', ...MONO }}>{lm.win_rate != null ? (lm.win_rate * 100).toFixed(1) + '%' : '—'}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', ...MONO }}>{lm.profit_factor ?? '—'}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', ...MONO }}>{lm.sharpe_ratio ?? '—'}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', ...MONO }}>{lm.max_drawdown_pct != null ? lm.max_drawdown_pct.toFixed(1) + '%' : '—'}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}><PnlValue value={lm.expectancy_dollars} /></td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}><PnlValue value={lm.total_pnl_dollars} /></td>
                </tr>
              )
            })}
            {sortedModels.length === 0 && (
              <tr><td colSpan={8} style={{ padding: 16, textAlign: 'center', color: 'var(--arcis-text-muted)' }}>No model versions found</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Section 4: Equity Curve per Model */}
      <div className="arcis-card" style={{ padding: '14px 16px' }}>
        <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 500, color: 'var(--arcis-text-secondary)', marginBottom: 8 }}>
          Equity Curve by Model Version
        </div>
        {equityData.length > 0 ? (
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={equityData}>
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} tickLine={false} axisLine={false} tickFormatter={v => `$${v}`} />
              <Tooltip
                contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', borderRadius: 6, fontSize: 12 }}
                labelStyle={{ color: 'var(--arcis-text-secondary)', fontSize: 11 }}
                formatter={(val) => [`$${Number(val).toFixed(2)}`, undefined]}
              />
              <Legend wrapperStyle={{ fontSize: 11, ...MONO }} />
              {modelVersions.map((ver, i) => (
                <Line key={ver} type="monotone" dataKey={ver} stroke={MODEL_COLORS[i % MODEL_COLORS.length]}
                  dot={false} strokeWidth={2} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ padding: 24, textAlign: 'center', color: 'var(--arcis-text-muted)', fontSize: 13 }}>
            No equity curve data — models need closed trades to generate curves
          </div>
        )}
      </div>

      {/* Section 5: LLM vs Canary */}
      <div className="arcis-card" style={{ padding: '14px 16px' }}>
        <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 500, color: 'var(--arcis-text-secondary)', marginBottom: 8 }}>
          LLM vs Canary Comparison
        </div>
        {canary.paired_trades > 0 ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
            <MetricCard label="LLM Win Rate" value={canary.llm_win_rate != null ? (canary.llm_win_rate * 100).toFixed(1) : '—'} suffix="%" />
            <MetricCard label="Canary Win Rate" value={canary.canary_win_rate != null ? (canary.canary_win_rate * 100).toFixed(1) : '—'} suffix="%" />
            <MetricCard label="Paired Trades" value={canary.paired_trades} />
            <MetricCard label="McNemar p-val" value={canary.mcnemar_pvalue != null ? canary.mcnemar_pvalue.toFixed(4) : '—'} />
            <div className="arcis-card" style={{ padding: '10px 12px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <StatusBadge
                text={canary.verdict || 'Unknown'}
                variant={canary.verdict === 'LLM adds value' ? 'success' : canary.verdict === 'Canary outperforms' ? 'danger' : 'neutral'}
              />
            </div>
          </div>
        ) : (
          <div style={{ padding: 16, textAlign: 'center', color: 'var(--arcis-text-muted)', fontSize: 13 }}>
            Insufficient data ({canary.paired_trades || 0} paired trades) — canary comparison requires llm_conviction and canary_score columns in recommendations
          </div>
        )}
      </div>
    </div>
  )
}
