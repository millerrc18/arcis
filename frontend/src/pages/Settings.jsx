import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { IS_CLOUD } from '../config'
import LoadingSpinner from '../components/LoadingSpinner'
import StatusBadge from '../components/StatusBadge'
import MetricCard from '../components/MetricCard'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { Settings2, Shield, Brain, Clock, RotateCcw } from 'lucide-react'

const SETTING_META = {
  'shadow_trading.max_positions': { label: 'Max Positions', type: 'number', section: 'Trading', min: 1, max: 100, desc: 'Maximum concurrent open positions' },
  'shadow_trading.enabled': { label: 'Enabled', type: 'toggle', section: 'Trading', desc: 'Enable shadow trading execution' },
  'shadow_trading.timeout_days.default': { label: 'Timeout Days (Default)', type: 'number', section: 'Trading', min: 1, max: 60, desc: 'Default trade timeout period' },
  'shadow_trading.timeout_days.pullback': { label: 'Timeout Days (Pullback)', type: 'number', section: 'Trading', min: 1, max: 60, desc: 'Pullback setup timeout period' },
  'risk.planned_risk_pct_min': { label: 'Risk % Min', type: 'number', section: 'Risk', min: 0.001, max: 0.1, step: 0.001, desc: 'Minimum position risk percentage' },
  'risk.planned_risk_pct_max': { label: 'Risk % Max', type: 'number', section: 'Risk', min: 0.001, max: 0.1, step: 0.001, desc: 'Maximum position risk percentage' },
  'llm.min_conviction_score': { label: 'Min Conviction Score', type: 'number', section: 'Model', min: 0, max: 100, desc: 'Minimum score to enter a trade' },
  'llm.enabled': { label: 'Enabled', type: 'toggle', section: 'Model', desc: 'Enable LLM inference for trade scoring' },
  'scheduler.scan_interval_minutes': { label: 'Scan Interval (min)', type: 'number', section: 'Scheduler', min: 5, max: 120, desc: 'Minutes between market scans' },
}

const SECTION_ICONS = {
  Trading: Settings2,
  Risk: Shield,
  Model: Brain,
  Scheduler: Clock,
}

function getNestedValue(obj, path) {
  return path.split('.').reduce((o, k) => o?.[k], obj)
}

function SettingInput({ settingKey, meta, currentValue, overrideInfo, onUpdate, pending }) {
  const isOverridden = !!overrideInfo
  const displayValue = isOverridden ? overrideInfo.value : currentValue
  const [localValue, setLocalValue] = useState(displayValue)
  const [saveAnim, setSaveAnim] = useState(null)

  const showSaveAnim = () => {
    setSaveAnim('saving')
    setTimeout(() => setSaveAnim('saved'), 300)
    setTimeout(() => setSaveAnim(null), 1500)
  }

  if (meta.type === 'toggle') {
    return (
      <div className="flex items-center justify-between py-3" style={{ borderBottom: '1px solid var(--arcis-border)' }}>
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm" style={{ color: 'var(--arcis-text-primary)' }}>{meta.label}</span>
            <span className="text-xs px-1.5 py-0.5 rounded" style={{
              background: isOverridden ? 'rgba(59, 130, 246, 0.15)' : 'var(--arcis-bg-elevated)',
              color: isOverridden ? 'var(--arcis-accent)' : 'var(--arcis-text-muted)',
            }}>
              {isOverridden ? 'dashboard override' : 'yaml default'}
            </span>
          </div>
          {meta.desc && <div className="text-xs mt-0.5" style={{ color: 'var(--arcis-text-muted)' }}>{meta.desc}</div>}
        </div>
        <div className="flex items-center gap-2">
          {saveAnim && <span className="text-xs" style={{ color: 'var(--arcis-success)' }}>{saveAnim === 'saving' ? 'Saving...' : 'Saved \u2713'}</span>}
          <button
            onClick={() => { onUpdate(settingKey, !displayValue); showSaveAnim() }}
            disabled={pending}
            className="relative w-11 h-6 rounded-full transition-colors"
            style={{ background: displayValue ? 'var(--arcis-success)' : 'var(--arcis-text-muted)' }}
          >
            <span className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform shadow-sm"
              style={{ transform: displayValue ? 'translateX(20px)' : 'translateX(0)' }} />
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-between py-3" style={{ borderBottom: '1px solid var(--arcis-border)' }}>
      <div>
        <div className="flex items-center gap-2">
          <span className="text-sm" style={{ color: 'var(--arcis-text-primary)' }}>{meta.label}</span>
          <span className="text-xs px-1.5 py-0.5 rounded" style={{
            background: isOverridden ? 'rgba(59, 130, 246, 0.15)' : 'var(--arcis-bg-elevated)',
            color: isOverridden ? 'var(--arcis-accent)' : 'var(--arcis-text-muted)',
          }}>
            {isOverridden ? 'dashboard override' : 'yaml default'}
          </span>
        </div>
        {meta.desc && <div className="text-xs mt-0.5" style={{ color: 'var(--arcis-text-muted)' }}>{meta.desc}</div>}
      </div>
      <div className="flex items-center gap-2">
        {saveAnim && <span className="text-xs" style={{ color: 'var(--arcis-success)' }}>{saveAnim === 'saving' ? 'Saving...' : 'Saved \u2713'}</span>}
        <input
          type="number"
          value={localValue ?? ''}
          min={meta.min}
          max={meta.max}
          step={meta.step || 1}
          disabled={pending}
          className="w-28 text-right text-sm rounded-lg px-3 py-1.5"
          style={{
            background: 'var(--arcis-bg-elevated)',
            border: '1px solid var(--arcis-border)',
            color: 'var(--arcis-text-primary)',
            fontFamily: 'var(--font-mono)',
          }}
          onChange={(e) => setLocalValue(e.target.value)}
          onBlur={(e) => {
            const v = meta.step && meta.step < 1 ? parseFloat(e.target.value) : parseInt(e.target.value, 10)
            if (!isNaN(v) && v !== displayValue) { onUpdate(settingKey, v); showSaveAnim() }
          }}
          onKeyDown={(e) => { if (e.key === 'Enter') e.target.blur() }}
        />
      </div>
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
  const [showResetConfirm, setShowResetConfirm] = useState(false)

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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      setShowResetConfirm(false)
    },
  })

  const handleUpdate = useCallback((key, value) => {
    updateMutation.mutate({ key, value })
  }, [updateMutation])

  if (isLoading) return <LoadingSpinner />

  const overrides = settings?.overrides || {}

  const sections = {}
  for (const [key, meta] of Object.entries(SETTING_META)) {
    if (!sections[meta.section]) sections[meta.section] = []
    sections[meta.section].push({ key, meta })
  }

  const hasOverrides = Object.keys(overrides).length > 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)' }}>Settings</h2>
      </div>

      {!IS_CLOUD && (
        <div className="rounded-lg p-3 text-sm" style={{ background: 'rgba(245, 158, 11, 0.12)', border: '1px solid rgba(245, 158, 11, 0.3)', color: 'var(--arcis-warning)' }}>
          Local mode \u2014 edits here take effect on the next sync cycle (up to 60s).
        </div>
      )}

      {/* Settings sections */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {Object.entries(sections).map(([sectionName, items]) => {
          const Icon = SECTION_ICONS[sectionName] || Settings2
          return (
            <div key={sectionName} className="arcis-card">
              <div className="flex items-center gap-2 mb-3">
                <Icon size={16} style={{ color: 'var(--arcis-accent)' }} />
                <h3 className="text-sm uppercase tracking-wide font-medium" style={{ color: 'var(--arcis-text-primary)' }}>{sectionName}</h3>
              </div>
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
            </div>
          )
        })}
      </div>

      {/* Reset button */}
      {hasOverrides && (
        <div className="arcis-card">
          {showResetConfirm ? (
            <div className="flex items-center justify-between">
              <span className="text-sm" style={{ color: 'var(--arcis-danger)' }}>
                Reset all dashboard overrides to YAML defaults?
              </span>
              <div className="flex gap-2">
                <button onClick={() => setShowResetConfirm(false)}
                  className="px-3 py-1.5 text-xs rounded-lg"
                  style={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-primary)' }}>
                  Cancel
                </button>
                <button onClick={() => clearMutation.mutate()} disabled={clearMutation.isPending}
                  className="px-3 py-1.5 text-xs rounded-lg disabled:opacity-50"
                  style={{ background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.4)', color: 'var(--arcis-danger)' }}>
                  {clearMutation.isPending ? 'Resetting...' : 'Confirm Reset'}
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setShowResetConfirm(true)}
              className="flex items-center gap-2 text-sm"
              style={{ color: 'var(--arcis-danger)' }}
            >
              <RotateCcw size={14} />
              Reset all to YAML defaults
            </button>
          )}
        </div>
      )}

      {/* System Health */}
      {status && (
        <div className="arcis-card">
          <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>System Health</h3>
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
              <div key={label} className="flex items-center justify-between p-2 rounded" style={{ background: 'var(--arcis-bg-elevated)' }}>
                <span style={{ color: 'var(--arcis-text-primary)' }}>{label}</span>
                <StatusBadge text={ok ? 'OK' : 'Off'} variant={ok ? 'success' : 'neutral'} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* API Cost Tracking */}
      {costs && (
        <>
          <h3 className="text-sm uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>API Costs</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <MetricCard label="All Time" value={`$${(costs.total_all_time ?? costs.total_cost ?? 0).toFixed(2)}`} />
            <MetricCard label="Today" value={`$${(costs.total_today ?? 0).toFixed(4)}`} />
            <MetricCard label="This Week" value={`$${(costs.total_week ?? 0).toFixed(4)}`} />
            <MetricCard label="API Calls (30d)" value={costs.total_calls ?? (costs.breakdown || []).reduce((s, r) => s + (r.call_count || 0), 0)} />
          </div>

          {/* Breakdown by purpose */}
          {costs.by_purpose && Object.keys(costs.by_purpose).length > 0 && (
            <div className="arcis-card">
              <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>Cost by Purpose (30d)</h3>
              <div className="space-y-2 text-sm">
                {Object.entries(costs.by_purpose)
                  .sort((a, b) => b[1].cost - a[1].cost)
                  .map(([purpose, data]) => (
                    <div key={purpose} className="flex items-center justify-between py-1" style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                      <span className="capitalize" style={{ color: 'var(--arcis-text-primary)' }}>{purpose.replace(/_/g, ' ')}</span>
                      <div className="flex items-center gap-4 financial-data">
                        <span className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>{data.calls} calls</span>
                        <span style={{ color: 'var(--arcis-text-primary)' }}>${data.cost.toFixed(4)}</span>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Breakdown (cloud format) */}
          {!costs.by_purpose && costs.breakdown && costs.breakdown.length > 0 && (
            <div className="arcis-card">
              <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>Cost Breakdown (30d)</h3>
              <div className="space-y-2 text-sm">
                {costs.breakdown.map((row, i) => (
                  <div key={i} className="flex items-center justify-between py-1" style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                    <span className="capitalize" style={{ color: 'var(--arcis-text-primary)' }}>{(row.purpose || row.model || 'unknown').replace(/_/g, ' ')}</span>
                    <div className="flex items-center gap-4 financial-data">
                      <span className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>{row.call_count || 0} calls</span>
                      <span style={{ color: 'var(--arcis-text-primary)' }}>${(row.total_cost || 0).toFixed(4)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Daily spend chart */}
          {costs.daily && costs.daily.length > 0 && (
            <div className="arcis-card">
              <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>Daily Spend (30d)</h3>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={costs.daily}>
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} tickFormatter={d => d.slice(5)} />
                  <YAxis tick={{ fontSize: 10, fill: 'var(--arcis-text-secondary)' }} tickFormatter={v => `$${v}`} />
                  {/* Fix for #250: add tooltip text color for dark mode readability */}
                  <Tooltip
                    contentStyle={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 8, fontSize: 12, color: 'var(--tooltip-text)' }}
                    formatter={v => [`$${v.toFixed(4)}`, 'Cost']}
                  />
                  <Bar dataKey="cost" fill="var(--arcis-accent)" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </div>
  )
}
