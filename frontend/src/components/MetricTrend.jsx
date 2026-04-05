import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import LoadingSpinner from './LoadingSpinner'
import EmptyState from './EmptyState'
import { TrendingUp } from 'lucide-react'

const METRIC_OPTIONS = [
  { key: 'cumulative_pnl', label: 'Cumulative P&L', color: 'var(--arcis-success)', format: v => `$${v}` },
  { key: 'win_rate', label: 'Win Rate', color: 'var(--chart-1)', format: v => `${(v * 100).toFixed(1)}%` },
  { key: 'sharpe_ratio', label: 'Sharpe Ratio', color: 'var(--chart-3)', format: v => v.toFixed(2) },
  { key: 'max_drawdown', label: 'Max Drawdown', color: 'var(--arcis-danger)', format: v => `$${v}` },
  { key: 'expectancy', label: 'Expectancy', color: 'var(--chart-4)', format: v => `$${v}` },
]

const DAY_OPTIONS = [
  { value: 7, label: '7d' },
  { value: 30, label: '30d' },
  { value: 90, label: '90d' },
  { value: 365, label: 'All' },
]

export default function MetricTrend() {
  const [days, setDays] = useState(90)
  const [selectedMetrics, setSelectedMetrics] = useState(['cumulative_pnl', 'sharpe_ratio'])

  const { data, isLoading } = useQuery({
    queryKey: ['metric-history', days],
    queryFn: () => api.getMetricHistory(days),
  })

  const toggleMetric = (key) => {
    setSelectedMetrics(prev =>
      prev.includes(key)
        ? prev.filter(k => k !== key)
        : [...prev, key]
    )
  }

  if (isLoading) return <LoadingSpinner />
  if (!data || data.length === 0) return <EmptyState message="No metric history available" icon={TrendingUp} />

  const activeMetrics = METRIC_OPTIONS.filter(m => selectedMetrics.includes(m.key))

  return (
    <div className="rounded-lg p-4" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Metric Trends</h3>
        <div className="flex gap-1">
          {DAY_OPTIONS.map(opt => (
            <button
              key={opt.value}
              onClick={() => setDays(opt.value)}
              className="px-2.5 py-1 text-xs rounded transition-colors"
              style={{
                background: days === opt.value ? 'var(--arcis-accent)' : 'var(--arcis-border)',
                color: days === opt.value ? 'white' : 'var(--arcis-text-secondary)',
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Metric toggles */}
      <div className="flex flex-wrap gap-2 mb-4">
        {METRIC_OPTIONS.map(m => (
          <button
            key={m.key}
            onClick={() => toggleMetric(m.key)}
            className={`px-2.5 py-1 text-xs rounded border transition-colors ${
              selectedMetrics.includes(m.key)
                ? 'border-current opacity-100'
                : 'opacity-50 hover:opacity-75'
            }`}
            style={{ color: m.color, borderColor: selectedMetrics.includes(m.key) ? undefined : 'var(--arcis-border)' }}
          >
            {m.label}
          </button>
        ))}
      </div>

      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data}>
          <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--arcis-text-secondary)' }} />
          <YAxis tick={{ fontSize: 11, fill: 'var(--arcis-text-secondary)' }} />
          {/* Fix for #250: add tooltip text color for dark mode readability */}
          <Tooltip
            contentStyle={{
              background: 'var(--arcis-bg-surface)',
              border: '1px solid var(--arcis-border)',
              borderRadius: 8,
              fontSize: 12,
              color: 'var(--tooltip-text)',
            }}
            formatter={(value, name) => {
              const metric = METRIC_OPTIONS.find(m => m.key === name)
              return [metric ? metric.format(value) : value, metric?.label || name]
            }}
          />
          {/* Fix for #250: set legend text color for dark mode readability */}
          <Legend wrapperStyle={{ color: 'var(--arcis-text-secondary)' }} />
          {activeMetrics.map(m => (
            <Line
              key={m.key}
              type="monotone"
              dataKey={m.key}
              name={m.key}
              stroke={m.color}
              dot={false}
              strokeWidth={2}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
