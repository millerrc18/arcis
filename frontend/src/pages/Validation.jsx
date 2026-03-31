import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'

const STATUS_ICONS = { pass: '\u2705', warn: '\u26a0\ufe0f', fail: '\u274c' }
const STATUS_COLORS = {
  pass: 'var(--arcis-accent)',
  warn: 'var(--arcis-warning)',
  fail: 'var(--arcis-danger)',
}
const OVERALL_COLORS = {
  healthy: 'var(--arcis-accent)',
  degraded: 'var(--arcis-warning)',
  critical: 'var(--arcis-danger)',
}

const CATEGORY_LABELS = {
  database: 'Database',
  trading: 'Trading',
  training: 'Training Pipeline',
  api: 'API / Dashboard',
  collectors: 'Data Collectors',
  notifications: 'Notifications',
  scheduler: 'Scheduler',
  llm: 'LLM / Inference',
}

function CategoryCard({ name, checks, expanded, onToggle }) {
  const passed = checks.filter((c) => c.status === 'pass').length
  const warned = checks.filter((c) => c.status === 'warn').length
  const failed = checks.filter((c) => c.status === 'fail').length

  const catColor = failed > 0 ? 'var(--arcis-danger)' : warned > 0 ? 'var(--arcis-warning)' : 'var(--arcis-accent)'
  const catIcon = failed > 0 ? '\u274c' : warned > 0 ? '\u26a0\ufe0f' : '\u2705'

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}
    >
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-4 text-left hover:bg-[var(--arcis-border)]/30 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-lg">{catIcon}</span>
          <span className="text-sm font-medium" style={{ color: 'var(--arcis-text-primary)' }}>
            {CATEGORY_LABELS[name] || name}
          </span>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex gap-2 text-xs" style={{ fontFamily: 'var(--font-mono)' }}>
            <span style={{ color: 'var(--arcis-accent)' }}>{passed}P</span>
            {warned > 0 && <span style={{ color: 'var(--arcis-warning)' }}>{warned}W</span>}
            {failed > 0 && <span style={{ color: 'var(--arcis-danger)' }}>{failed}F</span>}
          </div>
          <span style={{ color: 'var(--arcis-text-secondary)' }}>{expanded ? '\u25b2' : '\u25bc'}</span>
        </div>
      </button>

      {expanded && (
        <div className="border-t px-4 pb-3 pt-2 space-y-1" style={{ borderColor: 'var(--arcis-border)' }}>
          {checks.map((check, i) => (
            <div key={i} className="flex items-start gap-2 py-1">
              <span className="text-sm shrink-0">{STATUS_ICONS[check.status]}</span>
              <div className="min-w-0">
                <span className="text-xs font-medium" style={{ color: STATUS_COLORS[check.status] }}>
                  {check.name}
                </span>
                <span className="text-xs ml-2" style={{ color: 'var(--arcis-text-secondary)' }}>
                  {check.detail}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Validation() {
  const qc = useQueryClient()
  const [expanded, setExpanded] = useState({})
  const [refreshing, setRefreshing] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['validation'],
    queryFn: api.getValidation,
    refetchInterval: 300000, // 5 minutes
  })

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await api.runValidation()
      qc.invalidateQueries({ queryKey: ['validation'] })
    } finally {
      setRefreshing(false)
    }
  }

  const toggleCategory = (name) => {
    setExpanded((prev) => ({ ...prev, [name]: !prev[name] }))
  }

  if (isLoading) return <LoadingSpinner />

  const result = data || {}
  const overall = result.overall_status || 'unknown'
  const categories = result.categories || {}

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)' }}>
          System Validation
        </h2>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
          style={{
            background: 'var(--arcis-accent-hover)',
            color: 'var(--arcis-text-primary)',
          }}
        >
          {refreshing ? 'Running...' : 'Run Validation'}
        </button>
      </div>

      {/* Summary bar */}
      <div
        className="rounded-lg p-5 flex flex-col md:flex-row items-center gap-6"
        style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}
      >
        <div className="text-center md:text-left">
          <div className="text-xs uppercase tracking-wide mb-1" style={{ color: 'var(--arcis-text-secondary)' }}>
            Overall Status
          </div>
          <div
            className="text-3xl font-bold uppercase"
            style={{ fontFamily: 'var(--font-mono)', color: OVERALL_COLORS[overall] || 'var(--arcis-text-secondary)' }}
          >
            {overall}
          </div>
        </div>

        <div className="flex gap-6 text-center">
          <div>
            <div className="text-2xl font-bold" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-accent)' }}>
              {result.checks_passed || 0}
            </div>
            <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Passed</div>
          </div>
          <div>
            <div className="text-2xl font-bold" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-warning)' }}>
              {result.checks_warning || 0}
            </div>
            <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Warnings</div>
          </div>
          <div>
            <div className="text-2xl font-bold" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-danger)' }}>
              {result.checks_failed || 0}
            </div>
            <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Failed</div>
          </div>
          <div>
            <div className="text-2xl font-bold" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-secondary)' }}>
              {result.checks_total || 0}
            </div>
            <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Total</div>
          </div>
        </div>

        {result.timestamp && (
          <div className="text-xs md:ml-auto" style={{ color: 'var(--arcis-text-muted)' }}>
            Last run: {new Date(result.timestamp).toLocaleString()}
          </div>
        )}
      </div>

      {/* Category cards */}
      <div className="space-y-3">
        {Object.entries(categories).map(([name, checks]) => (
          <CategoryCard
            key={name}
            name={name}
            checks={checks}
            expanded={!!expanded[name]}
            onToggle={() => toggleCategory(name)}
          />
        ))}
      </div>
    </div>
  )
}
