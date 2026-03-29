import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { IS_CLOUD } from '../config'
import LoadingSpinner from '../components/LoadingSpinner'
import StatusBadge from '../components/StatusBadge'
import MetricCard from '../components/MetricCard'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

export default function Settings() {
  const { data: config, isLoading } = useQuery({ queryKey: ['config'], queryFn: api.getConfig })
  const { data: status } = useQuery({ queryKey: ['status'], queryFn: api.getStatus })
  const { data: costs } = useQuery({ queryKey: ['costs'], queryFn: () => api.getCosts(30), refetchInterval: 120000 })

  if (isLoading) return <LoadingSpinner />

  const Section = ({ title, children }) => (
    <div className="rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
      <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--slate-400)' }}>{title}</h3>
      <div className="space-y-3 text-sm">{children}</div>
    </div>
  )

  const Row = ({ label, value }) => (
    <div className="flex justify-between">
      <span style={{ color: 'var(--slate-300)' }}>{label}</span>
      <span style={{ fontFamily: 'var(--font-mono)' }}>{String(value)}</span>
    </div>
  )

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-medium" style={{ color: 'var(--slate-100)' }}>Settings</h2>

      <div className="rounded-lg p-3 text-sm" style={{ background: 'rgba(245, 158, 11, 0.15)', border: '1px solid rgba(245, 158, 11, 0.4)', color: 'var(--amber-300)' }}>
        {IS_CLOUD
          ? 'Cloud mode — showing cached configuration. Changes require local access.'
          : 'Configuration changes require a watch loop restart to take effect.'}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Section title="Risk">
          <Row label="Starting Capital" value={`$${config?.risk?.starting_capital || 1000}`} />
          <Row label="Risk Min" value={`${((config?.risk?.planned_risk_pct_min || 0) * 100).toFixed(1)}%`} />
          <Row label="Risk Max" value={`${((config?.risk?.planned_risk_pct_max || 0) * 100).toFixed(1)}%`} />
        </Section>

        <Section title="Shadow Trading">
          <Row label="Enabled" value={config?.shadow_trading?.enabled ? 'Yes' : 'No'} />
          <Row label="Max Positions" value={config?.shadow_trading?.max_positions || 10} />
          <Row label="Timeout Days" value={config?.shadow_trading?.timeout_days || 15} />
        </Section>

        <Section title="LLM">
          <Row label="Enabled" value={config?.llm?.enabled ? 'Yes' : 'No'} />
          <Row label="Model" value={config?.llm?.model || 'qwen3:8b'} />
          <Row label="Temperature" value={config?.llm?.temperature || 0.7} />
        </Section>

        <Section title="Bootcamp">
          <Row label="Enabled" value={config?.bootcamp?.enabled ? 'Yes' : 'No'} />
          <Row label="Phase" value={config?.bootcamp?.phase || 1} />
          <Row label="Qualification Threshold" value={config?.bootcamp?.qualification_threshold || 40} />
          <Row label="Email Mode" value={config?.bootcamp?.email_mode || 'full_stream'} />
        </Section>

        <Section title="Automation">
          <Row label="Morning Watchlist" value={`${config?.automation?.morning_watchlist_hour_et || 8}:00 ET`} />
          <Row label="EOD Recap" value={`${config?.automation?.eod_recap_hour_et || 16}:00 ET`} />
          <Row label="Scan Interval" value={`${config?.automation?.scan_interval_minutes || 30} min`} />
        </Section>

        <Section title="Training">
          <Row label="Enabled" value={config?.training?.enabled ? 'Yes' : 'No'} />
          <Row label="Claude Model" value={config?.training?.claude_model || '--'} />
          <Row label="Train Threshold" value={config?.training?.auto_train_threshold || 50} />
        </Section>
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
