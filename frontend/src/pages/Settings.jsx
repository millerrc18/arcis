import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { IS_CLOUD } from '../config'
import LoadingSpinner from '../components/LoadingSpinner'
import StatusBadge from '../components/StatusBadge'
import MetricCard from '../components/MetricCard'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

const SETTING_META = {
  'shadow_trading.max_positions': { label: 'Max Positions', type: 'number', section: 'Shadow Trading', min: 1, max: 100 },
  'shadow_trading.enabled': { label: 'Enabled', type: 'toggle', section: 'Shadow Trading' },
  'shadow_trading.timeout_days.default': { label: 'Timeout Days (Default)', type: 'number', section: 'Shadow Trading', min: 1, max: 60 },
  'shadow_trading.timeout_days.pullback': { label: 'Timeout Days (Pullback)', type: 'number', section: 'Shadow Trading', min: 1, max: 60 },
  'risk.planned_risk_pct_min': { label: 'Risk % Min', type: 'number', section: 'Risk', min: 0.001, max: 0.1, step: 0.001 },
  'risk.planned_risk_pct_max': { label: 'Risk % Max', type: 'number', section: 'Risk', min: 0.001, max: 0.1, step: 0.001 },
  'llm.min_conviction_score': { label: 'Min Conviction Score', type: 'number', section: 'LLM', min: 0, max: 100 },
  'llm.enabled': { label: 'Enabled', type: 'toggle', section: 'LLM' },
  'scheduler.scan_interval_minutes': { label: 'Scan Interval (min)', type: 'number', section: 'Scheduler', min: 5, max: 120 },
}

function getNestedValue(obj, path) {
  return path.split('.').reduce((o, k) => o?.[k], obj)
}

function SettingInput({ settingKey, meta, currentValue, overrideInfo, onUpdate, pending }) {
  const isOverridden = !!overrideInfo
  const displayValue = isOverridden ? overrideInfo.value : currentValue

  if (meta.type === 'toggle') {
    return (
      <div className="flex items-center justify-between py-2">
        <div className="flex items-center gap-2">
          <span className="text-sm" style={{ color: 'var(--slate-300)' }}>{meta.label}</span>
          <span className="text-xs px-1.5 py-0.5 rounded" style={{
            background: isOverridden ? 'rgba(59, 130, 246, 0.2)' : 'rgba(100, 116, 139, 0.2)',
            color: isOverridden ? 'var(--blue-400)' : 'var(--slate-500)',
          }}>
            {isOverridden ? 'dashboard override' : 'yaml default'}
          </span>
        </div>
        <button
          onClick={() => onUpdate(settingKey, !displayValue)}
          disabled={pending}
          className="relative w-10 h-5 rounded-full transition-colors"
          style={{ background: displayValue ? 'var(--teal-500)' : 'var(--slate-600)' }}
        >
          <span className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform"
            style={{ transform: displayValue ? 'translateX(20px)' : 'translateX(0)' }} />
        </button>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-between py-2">
      <div className="flex items-center gap-2">
        <span className="text-sm" style={{ color: 'var(--slate-300)' }}>{meta.label}</span>
        <span className="text-xs px-1.5 py-0.5 rounded" style={{
          background: isOverridden ? 'rgba(59, 130, 246, 0.2)' : 'rgba(100, 116, 139, 0.2)',
          color: isOverridden ? 'var(--blue-400)' : 'var(--slate-500)',
        }}>
          {isOverridden ? 'dashboard override' : 'yaml default'}
        </span>
      </div>
      <input
        type="number"
        value={displayValue ?? ''}
        min={meta.min}
        max={meta.max}
        step={meta.step || 1}
        disabled={pending}
        className="w-24 text-right text-sm rounded px-2 py-1"
        style={{ background: 'var(--slate-800)', border: '1px solid var(--slate-600)', color: 'var(--slate-100)' }}
        onBlur={(e) => {
          const v = meta.step && meta.step < 1 ? parseFloat(e.target.value) : parseInt(e.target.value, 10)
          if (!isNaN(v) && v !== displayValue) onUpdate(settingKey, v)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.target.blur()
        }}
        onChange={() => {}} // controlled display; actual update on blur
      />
    </div>
  )
}

export default function Settings() {
  const queryClient = useQueryClient()
  const { data: config, isLoading } = useQuery({ queryKey: ['config'], queryFn: api.getConfig })
  const { data: status } = useQuery({ queryKey: ['status'], queryFn: api.getStatus })
  const { data: costs } = useQuery({ queryKey: ['costs'], queryFn: () => api.getCosts(30), refetchInterval: 120000 })
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: api.getSettings, refetchInterval: 15000 })

  const [pendingKeys, setPendingKeys] = useState(new Set())

  const updateMutation = useMutation({
    mutationFn: ({ key, value }) => api.updateSettings({ key, value }),
    onMutate: ({ key }) => setPendingKeys(prev => new Set(prev).add(key)),
    onSettled: (_, __, { key }) => {
      setPendingKeys(prev => { const n = new Set(prev); n.delete(key); return n })
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
  })

  const clearMutation = useMutation({
    mutationFn: () => api.clearOverrides(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings'] }),
  })

  const handleUpdate = useCallback((key, value) => {
    updateMutation.mutate({ key, value })
  }, [updateMutation])

  if (isLoading) return <LoadingSpinner />

  const overrides = settings?.overrides || {}

  // Group settings by section
  const sections = {}
  for (const [key, meta] of Object.entries(SETTING_META)) {
    if (!sections[meta.section]) sections[meta.section] = []
    sections[meta.section].push({ key, meta })
  }

  const Section = ({ title, children }) => (
    <div className="rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
      <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--slate-400)' }}>{title}</h3>
      <div className="divide-y" style={{ borderColor: 'var(--slate-600)' }}>{children}</div>
    </div>
  )

  const hasOverrides = Object.keys(overrides).length > 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium" style={{ color: 'var(--slate-100)' }}>Settings</h2>
        {hasOverrides && (
          <button
            onClick={() => clearMutation.mutate()}
            disabled={clearMutation.isPending}
            className="text-xs px-3 py-1.5 rounded transition-colors"
            style={{ background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.4)', color: 'var(--red-400)' }}
          >
            {clearMutation.isPending ? 'Resetting...' : 'Reset to YAML'}
          </button>
        )}
      </div>

      {!IS_CLOUD && (
        <div className="rounded-lg p-3 text-sm" style={{ background: 'rgba(245, 158, 11, 0.15)', border: '1px solid rgba(245, 158, 11, 0.4)', color: 'var(--amber-300)' }}>
          Local mode — edits here take effect on the next sync cycle (up to 60s).
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {Object.entries(sections).map(([sectionName, items]) => (
          <Section key={sectionName} title={sectionName}>
            {items.map(({ key, meta }) => (
              <SettingInput
                key={key}
                settingKey={key}
                meta={meta}
                currentValue={getNestedValue(settings || config, key.replace('scheduler.', 'automation.'))}
                overrideInfo={overrides[key]}
                onUpdate={handleUpdate}
                pending={pendingKeys.has(key)}
              />
            ))}
          </Section>
        ))}
      </div>

      {/* System Health */}
      {status && (
        <div className="rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
          <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--slate-400)' }}>System Health</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            {[
              ['Config', status.config_loaded],
              ['Email', status.email_configured],
              ['Alpaca', status.alpaca_connected],
              ['Ollama', status.ollama_available],
              ['LLM', status.llm_enabled],
              ['Shadow', status.shadow_trading_enabled],
              ['Training', status.training_enabled],
              ['Bootcamp', status.bootcamp_enabled],
            ].map(([label, ok]) => (
              <div key={label} className="flex items-center justify-between">
                <span style={{ color: 'var(--slate-300)' }}>{label}</span>
                <StatusBadge text={ok ? 'OK' : 'Off'} variant={ok ? 'success' : 'neutral'} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* API Cost Tracking */}
      {costs && (
        <>
          <h3 className="text-sm uppercase tracking-wide" style={{ color: 'var(--slate-400)' }}>API Costs</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <MetricCard label="All Time" value={`$${(costs.total_all_time ?? costs.total_cost ?? 0).toFixed(2)}`} />
            <MetricCard label="Today" value={`$${(costs.total_today ?? 0).toFixed(4)}`} />
            <MetricCard label="This Week" value={`$${(costs.total_week ?? 0).toFixed(4)}`} />
            <MetricCard label="API Calls (30d)" value={costs.total_calls ?? (costs.breakdown || []).reduce((s, r) => s + (r.call_count || 0), 0)} />
          </div>

          {/* Breakdown by purpose (local format) */}
          {costs.by_purpose && Object.keys(costs.by_purpose).length > 0 && (
            <div className="rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
              <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--slate-400)' }}>Cost by Purpose (30d)</h3>
              <div className="space-y-2 text-sm">
                {Object.entries(costs.by_purpose)
                  .sort((a, b) => b[1].cost - a[1].cost)
                  .map(([purpose, data]) => (
                    <div key={purpose} className="flex items-center justify-between">
                      <span className="capitalize" style={{ color: 'var(--slate-300)' }}>{purpose.replace(/_/g, ' ')}</span>
                      <div className="flex items-center gap-4" style={{ fontFamily: 'var(--font-mono)' }}>
                        <span className="text-xs" style={{ color: 'var(--slate-400)' }}>{data.calls} calls</span>
                        <span>${data.cost.toFixed(4)}</span>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Breakdown (cloud format) */}
          {!costs.by_purpose && costs.breakdown && costs.breakdown.length > 0 && (
            <div className="rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
              <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--slate-400)' }}>Cost Breakdown (30d)</h3>
              <div className="space-y-2 text-sm">
                {costs.breakdown.map((row, i) => (
                  <div key={i} className="flex items-center justify-between">
                    <span className="capitalize" style={{ color: 'var(--slate-300)' }}>{(row.purpose || row.model || 'unknown').replace(/_/g, ' ')}</span>
                    <div className="flex items-center gap-4" style={{ fontFamily: 'var(--font-mono)' }}>
                      <span className="text-xs" style={{ color: 'var(--slate-400)' }}>{row.call_count || 0} calls</span>
                      <span>${(row.total_cost || 0).toFixed(4)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Daily spend chart */}
          {costs.daily && costs.daily.length > 0 && (
            <div className="rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
              <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--slate-400)' }}>Daily Spend (30d)</h3>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={costs.daily}>
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--slate-400)' }} tickFormatter={d => d.slice(5)} />
                  <YAxis tick={{ fontSize: 10, fill: 'var(--slate-400)' }} tickFormatter={v => `$${v}`} />
                  <Tooltip
                    contentStyle={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)', borderRadius: 8, fontSize: 12 }}
                    formatter={v => [`$${v.toFixed(4)}`, 'Cost']}
                  />
                  <Bar dataKey="cost" fill="var(--teal-400)" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </div>
  )
}
