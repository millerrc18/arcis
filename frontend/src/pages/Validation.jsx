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

  const catIcon = failed > 0 ? '\u274c' : warned > 0 ? '\u26a0\ufe0f' : '\u2705'

  return (
    <div
      className="overflow-hidden"
      style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}
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
  const [error, setError] = useState(null)
  const [lastRunResult, setLastRunResult] = useState(null)

  const { data, isLoading } = useQuery({
    queryKey: ['validation'],
    queryFn: api.getValidation,
    refetchInterval: 300000,
  })

  const handleRefresh = async () => {
    setRefreshing(true)
    setError(null)
    setLastRunResult(null)
    const startTime = Date.now()
    try {
      // Try direct validation first (works when API is serving)
      const result = await api.runValidation()
      qc.invalidateQueries({ queryKey: ['validation'] })
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1)
      setLastRunResult({
        status: result?.overall_status || 'completed',
        passed: result?.checks_passed || 0,
        warned: result?.checks_warning || 0,
        failed: result?.checks_failed || 0,
        elapsed,
      })
    } catch (err) {
      // If direct call fails, try via command queue
      try {
        const cmd = await api.submitCommand({
          command_type: 'action',
          command_name: 'validate-system',
        })
        // Poll for completion
        const cmdId = cmd?.command_id
        if (cmdId) {
          let attempts = 0
          const poll = setInterval(async () => {
            attempts++
            try {
              const status = await api.getCommandStatus(cmdId)
              if (status?.status === 'success' || status?.result_status === 'success') {
                clearInterval(poll)
                qc.invalidateQueries({ queryKey: ['validation'] })
                const elapsed = ((Date.now() - startTime) / 1000).toFixed(1)
                setLastRunResult({ status: 'completed', elapsed })
                setRefreshing(false)
              } else if (status?.status === 'error' || status?.result_status === 'error' || attempts > 20) {
                clearInterval(poll)
                setError(status?.error || 'Validation timed out')
                setRefreshing(false)
              }
            } catch {
              if (attempts > 20) {
                clearInterval(poll)
                setError('Watch loop offline \u2014 validation requires the local system to be running')
                setRefreshing(false)
              }
            }
          }, 3000)
          return
        }
      } catch {
        setError('Watch loop offline \u2014 validation requires the local system to be running')
      }
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
          className="px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50 flex items-center gap-2"
          style={{
            borderRadius: 'var(--radius-sm)',
            background: 'var(--arcis-accent-hover)',
            color: 'var(--arcis-text-primary)',
          }}
        >
          {refreshing && <LoadingSpinner size="sm" />}
          {refreshing ? 'Running...' : 'Run Validation'}
        </button>
      </div>

      {/* Error message */}
      {error && (
        <div className="p-3 text-sm" style={{ borderRadius: 'var(--radius-sm)', background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.4)', color: 'var(--arcis-danger)' }}>
          {error}
        </div>
      )}

      {/* Success feedback */}
      {lastRunResult && !error && (
        <div className="p-3 text-sm flex items-center justify-between" style={{
          borderRadius: 'var(--radius-sm)',
          background: lastRunResult.failed > 0
            ? 'rgba(239, 68, 68, 0.1)'
            : lastRunResult.warned > 0
              ? 'rgba(245, 158, 11, 0.1)'
              : 'rgba(34, 197, 94, 0.1)',
          border: `1px solid ${lastRunResult.failed > 0
            ? 'rgba(239, 68, 68, 0.3)'
            : lastRunResult.warned > 0
              ? 'rgba(245, 158, 11, 0.3)'
              : 'rgba(34, 197, 94, 0.3)'}`,
          color: 'var(--arcis-text-primary)',
        }}>
          <span>
            Validation complete: {lastRunResult.passed || 0} passed
            {lastRunResult.warned > 0 && `, ${lastRunResult.warned} warnings`}
            {lastRunResult.failed > 0 && `, ${lastRunResult.failed} failed`}
          </span>
          <span className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>
            {lastRunResult.elapsed}s
          </span>
        </div>
      )}

      {/* Summary bar */}
      <div
        className="p-5 flex flex-col md:flex-row items-center gap-6"
        style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}
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
            <div className="text-2xl font-bold financial-data" style={{ color: 'var(--arcis-accent)' }}>
              {result.checks_passed || 0}
            </div>
            <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Passed</div>
          </div>
          <div>
            <div className="text-2xl font-bold financial-data" style={{ color: 'var(--arcis-warning)' }}>
              {result.checks_warning || 0}
            </div>
            <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Warnings</div>
          </div>
          <div>
            <div className="text-2xl font-bold financial-data" style={{ color: 'var(--arcis-danger)' }}>
              {result.checks_failed || 0}
            </div>
            <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Failed</div>
          </div>
          <div>
            <div className="text-2xl font-bold financial-data" style={{ color: 'var(--arcis-text-secondary)' }}>
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
