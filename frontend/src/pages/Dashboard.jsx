import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import { IS_CLOUD } from '../config'
import MetricCard from '../components/MetricCard'
import DataTable from '../components/DataTable'
import LoadingSpinner from '../components/LoadingSpinner'
import PnlText from '../components/PnlText'
import StatusBadge from '../components/StatusBadge'
import ActivityFeed from '../components/ActivityFeed'
import Tooltip from '../components/Tooltip'
import { XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, Area, AreaChart, Line, LineChart } from 'recharts'
import { TrendingUp, TrendingDown, Minus, AlertTriangle, Zap, ChevronDown, ChevronUp } from 'lucide-react'

function parseAuditSummary(raw) {
  if (!raw) return null
  let text = raw
  text = text.replace(/```json\s*/gi, '').replace(/```\s*/g, '')
  try {
    const parsed = JSON.parse(text)
    return parsed.summary || parsed.overall_summary || text
  } catch {
    const match = text.match(/"summary"\s*:\s*"([^"]+)"/i)
    if (match) return match[1]
    text = text.replace(/^\s*\{\s*"overall_assessment"\s*:\s*"[^"]*"\s*,?\s*/i, '')
    text = text.replace(/^\s*"summary"\s*:\s*"?/i, '')
    text = text.replace(/"?\s*,?\s*"[^"]*"\s*:\s*[\[{].*$/s, '')
    return text.trim().replace(/^"|"$/g, '') || raw.slice(0, 200)
  }
}

function getAuditChipState(assessment, auditData) {
  const createdAt = auditData?.created_at || auditData?.audit_date
  const isStale = createdAt && (Date.now() - new Date(createdAt).getTime()) > 24 * 60 * 60 * 1000
  if (isStale) return { label: 'Stale (>24h)', dot: '\u26AA', bg: 'rgba(148,163,184,0.15)', border: 'rgba(148,163,184,0.3)', color: 'var(--arcis-text-muted)' }
  if (!assessment) return { label: 'No audit', dot: '\u26AA', bg: 'rgba(148,163,184,0.15)', border: 'rgba(148,163,184,0.3)', color: 'var(--arcis-text-muted)' }
  if (assessment === 'green' || assessment === 'healthy') return { label: 'System OK', dot: '\uD83D\uDFE2', bg: 'rgba(34,197,94,0.12)', border: 'rgba(34,197,94,0.3)', color: 'var(--arcis-success)' }
  if (assessment === 'yellow' || assessment === 'warning') return { label: 'Warnings', dot: '\uD83D\uDFE1', bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.3)', color: 'var(--amber-300)' }
  if (assessment === 'red' || assessment === 'critical') return { label: 'Issues found', dot: '\uD83D\uDD34', bg: 'rgba(239,68,68,0.12)', border: 'rgba(239,68,68,0.3)', color: '#fca5a5' }
  return { label: 'No audit', dot: '\u26AA', bg: 'rgba(148,163,184,0.15)', border: 'rgba(148,163,184,0.3)', color: 'var(--arcis-text-muted)' }
}

function relativeTime(dateStr) {
  if (!dateStr) return ''
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function AuditChip({ auditData, auditAssessment, auditSummary }) {
  const [expanded, setExpanded] = useState(false)
  const chip = getAuditChipState(auditAssessment, auditData)
  const createdAt = auditData?.created_at || auditData?.audit_date

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium cursor-pointer transition-colors"
        style={{ background: chip.bg, border: `1px solid ${chip.border}`, color: chip.color }}
      >
        <span>{chip.dot}</span>
        <span>{chip.label}</span>
        {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {expanded && (
        <div className="rounded-lg p-4 mt-2" style={{ border: `1px solid ${chip.border}`, background: 'var(--arcis-bg-surface)' }}>
          <div className="flex items-center gap-2 mb-2">
            <span>{chip.dot}</span>
            <span className="text-sm font-medium" style={{ color: chip.color }}>{chip.label}</span>
          </div>
          {auditSummary && <p className="text-sm mb-2" style={{ color: 'var(--arcis-text-secondary)' }}>{auditSummary.slice(0, 300)}</p>}
          {createdAt && <p className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>Last audit: {relativeTime(createdAt)}</p>}
          <button onClick={() => setExpanded(false)} className="text-xs mt-2" style={{ color: 'var(--arcis-text-secondary)' }}>Collapse</button>
        </div>
      )}
    </div>
  )
}

function scoreColor(score) {
  if (score >= 70) return 'var(--teal-400)'
  if (score >= 40) return 'var(--amber-400)'
  return 'var(--danger)'
}

function BuildScoreHero({ data }) {
  if (!data) return null
  const score = data.build_score ?? 0
  if (score === 0 && (!data.components || Object.values(data.components).every(v => v === 0))) {
    return (
      <div className="arcis-card" style={{ padding: '20px', textAlign: 'center' }}>
        <span className="text-sm font-medium" style={{ color: 'var(--arcis-text-muted)' }}>Build Score not yet computed</span>
        <p className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>Click "Generate CTO Report" or wait for 4:30 PM ET</p>
      </div>
    )
  }
  const delta = data.delta_7d
  const decay = data.decay_today
  const components = data.components || {}
  const phase = data.phase_progress || {}
  const history = (data.history_7d || []).map((v, i) => ({ day: i + 1, score: v }))

  const componentLabels = {
    gate_velocity: 'Gate Velocity',
    system_health: 'System Health',
    data_asset_value: 'Data Asset',
    model_quality: 'Model Quality',
    research_velocity: 'Research Velocity',
    reliability: 'Reliability',
  }

  return (
    <div className="arcis-card" style={{ padding: '20px' }}>
      <div className="flex flex-col lg:flex-row gap-6">
        {/* Left: Score + delta */}
        <div className="flex flex-col items-center lg:items-start gap-1 min-w-[140px]">
          <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-muted)' }}>Build Score</div>
          <div className="text-5xl font-bold" style={{ fontFamily: 'var(--font-mono)', color: scoreColor(score) }}>
            {score.toFixed(1)}
          </div>
          <div className="flex items-center gap-2 mt-1">
            {delta != null && (
              <span className="flex items-center gap-1 text-sm" style={{ color: delta > 0 ? 'var(--success)' : delta < 0 ? 'var(--danger)' : 'var(--arcis-text-muted)' }}>
                {delta > 0 ? <TrendingUp size={14} /> : delta < 0 ? <TrendingDown size={14} /> : <Minus size={14} />}
                {delta > 0 ? '+' : ''}{delta.toFixed(1)} 7d
              </span>
            )}
            {decay && (
              <Tooltip content="Idle day: no closed trades, new examples, or scans today. -1 decay applied.">
                <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full" style={{ background: 'rgba(239,68,68,0.15)', color: '#fca5a5' }}>
                  <AlertTriangle size={10} /> Decay
                </span>
              </Tooltip>
            )}
          </div>
        </div>

        {/* Center: Component bars */}
        <div className="flex-1 grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-2">
          {Object.entries(componentLabels).map(([key, label]) => {
            const val = components[key] ?? 0
            return (
              <div key={key}>
                <div className="flex justify-between text-xs mb-1">
                  <span style={{ color: 'var(--arcis-text-muted)' }}>{label}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', color: scoreColor(val) }}>{val.toFixed(0)}</span>
                </div>
                <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--arcis-text-secondary)' }}>
                  <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, val)}%`, background: scoreColor(val) }} />
                </div>
              </div>
            )
          })}
        </div>

        {/* Right: Sparkline + phase */}
        <div className="flex flex-col items-center gap-2 min-w-[120px]">
          {history.length > 1 && (
            <ResponsiveContainer width={120} height={48}>
              <LineChart data={history}>
                <Line type="monotone" dataKey="score" stroke="var(--teal-400)" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
          <div className="text-xs text-center" style={{ color: 'var(--arcis-text-muted)' }}>
            Phase {phase.current_phase || 1}: {phase.trades_closed || 0}/{phase.trades_required || 50} trades
          </div>
          <div className="h-1.5 w-full max-w-[100px] rounded-full overflow-hidden" style={{ background: 'var(--arcis-text-secondary)' }}>
            <div className="h-full rounded-full" style={{ width: `${phase.pct_complete || 0}%`, background: 'var(--teal-500)' }} />
          </div>
        </div>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const queryClient = useQueryClient()
  const { data: status, isLoading: statusLoading } = useQuery({ queryKey: ['status'], queryFn: api.getStatus, refetchInterval: 60000 })
  const { data: openTrades } = useQuery({ queryKey: ['shadow-open'], queryFn: api.getOpenTrades, refetchInterval: 60000 })
  const { data: closedData } = useQuery({ queryKey: ['shadow-closed'], queryFn: () => api.getClosedTrades(30), refetchInterval: 60000 })
  const { data: training } = useQuery({ queryKey: ['training-status'], queryFn: api.getTrainingStatus, refetchInterval: 60000 })
  const { data: packets } = useQuery({ queryKey: ['packets'], queryFn: () => api.getPackets({ days: 1 }), refetchInterval: 60000 })
  const { data: haltData } = useQuery({ queryKey: ['halt-status'], queryFn: api.getHaltStatus, refetchInterval: 30000 })
  const { data: auditData } = useQuery({ queryKey: ['audit-latest'], queryFn: api.getLatestAudit, refetchInterval: 60000 })
  const { data: ctoData } = useQuery({ queryKey: ['cto-report'], queryFn: () => api.getCtoReport(7), refetchInterval: 60000 })
  const { data: configData } = useQuery({ queryKey: ['config'], queryFn: api.getConfig, refetchInterval: 300000 })
  const { data: accountData } = useQuery({ queryKey: ['shadow-account'], queryFn: api.getAccount, refetchInterval: 60000 })
  const { data: buildScore } = useQuery({ queryKey: ['build-score'], queryFn: api.getBuildScore, refetchInterval: 120000 })
  const { data: scanMetrics } = useQuery({ queryKey: ['scan-metrics'], queryFn: () => api.getScanMetrics(50), refetchInterval: 60000 })

  const [toast, setToast] = useState(null)
  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(null), 3000) }

  const haltMutation = useMutation({
    mutationFn: () => haltData?.halted ? api.resumeTrading() : api.haltTrading(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['halt-status'] }),
  })

  const handleCloudAction = (fn, successMsg, failMsg) => ({
    mutationFn: fn,
    onSuccess: (data) => {
      if (data?.error === 'cloud_mode') {
        showToast('This action is only available locally')
      } else {
        showToast(successMsg)
      }
    },
    onError: (e) => showToast(`${failMsg}: ${e.message}`),
  })
  const scanMutation = useMutation(handleCloudAction(api.triggerActionScan, 'Scan started...', 'Scan failed'))
  const ctoMutation = useMutation(handleCloudAction(api.triggerCtoReport, 'CTO report generating...', 'CTO report failed'))
  const collectMutation = useMutation(handleCloudAction(api.triggerCollectTraining, 'Training data collection started...', 'Collection failed'))

  const isHalted = haltData?.halted || false

  const auditAssessment = auditData?.overall_assessment || auditData?.audit?.overall_assessment
  const rawSummary = auditData?.summary || auditData?.audit?.summary
  const auditSummary = parseAuditSummary(rawSummary)

  if (statusLoading) return <LoadingSpinner />

  const startingCapital = configData?.risk?.starting_capital || 100000
  const rawEquity = accountData?.equity
  const equity = (rawEquity && rawEquity > 0) ? rawEquity : (startingCapital + (accountData?.closed_pnl || 0))
  const equityDelta = equity - startingCapital

  const chartData = (closedData?.trades || [])
    .filter(t => t.pnl_dollars != null)
    .reverse()
    .reduce((acc, t, i) => {
      const prev = acc.length > 0 ? acc[acc.length - 1].cumPnl : 0
      const exitDate = t.actual_exit_time || t.updated_at || t.created_at || ''
      const dateLabel = exitDate.slice(5, 10) || `T${i + 1}`
      acc.push({ date: dateLabel, cumPnl: Math.round((prev + (t.pnl_dollars || 0)) * 100) / 100, trade: t.ticker })
      return acc
    }, [])

  const tradeColumns = [
    { key: 'ticker', label: 'Ticker', type: 'text' },
    { key: 'entry_price', label: 'Entry', type: 'currency' },
    { key: 'current_price', label: 'Current', type: 'currency' },
    { key: 'pnl_dollars', label: 'P&L', type: 'currency' },
    { key: 'duration_days', label: 'Days', type: 'number' },
    { key: 'stop_price', label: 'Stop', type: 'currency' },
    { key: 'target_1', label: 'Target', type: 'currency' },
  ]

  const kpis = ctoData?.headline_kpis || {}
  const ts = ctoData?.trade_summary || {}
  const closedCount = ts.trades_closed || accountData?.total_closed || 0
  const hasTrades = closedCount >= 2

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text)' }}>Dashboard</h2>
        <div className="flex items-center gap-3">
          <AuditChip auditData={auditData} auditAssessment={auditAssessment} auditSummary={auditSummary} />
          <Tooltip content="EMERGENCY: Immediately stops all new trade entries. Open positions are NOT closed.">
            <button
              onClick={() => {
                if (isHalted || confirm('Are you sure? This stops all new trades.')) {
                  haltMutation.mutate()
                }
              }}
              className="px-4 py-2 rounded-lg font-medium text-sm text-white transition-colors"
              style={{ background: isHalted ? 'var(--success)' : 'var(--danger)' }}
            >
              {isHalted ? 'RESUME TRADING' : 'HALT TRADING'}
            </button>
          </Tooltip>
        </div>
      </div>

      {/* Halt warning banner */}
      {isHalted && (
        <div className="rounded-lg p-3 text-sm" style={{ background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.4)', color: '#fca5a5' }}>
          Trading is HALTED. No new positions will be opened. Click "Resume Trading" to resume.
        </div>
      )}

      {/* Audit chip is now in header bar */}

      {/* Toast notification */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 rounded-lg px-4 py-2 text-sm shadow-lg" style={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)' }}>
          {toast}
        </div>
      )}

      {/* BUILD SCORE HERO */}
      <BuildScoreHero data={buildScore} />

      {/* Actions */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs uppercase tracking-wide mr-2" style={{ color: 'var(--arcis-text-muted)' }}>Actions</span>
        <Tooltip content="Triggers an immediate market scan outside the normal 30-min schedule.">
          <button onClick={() => scanMutation.mutate()} disabled={scanMutation.isPending}
            className="px-3 py-1.5 text-xs rounded-md disabled:opacity-50 transition-colors"
            style={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-text-secondary)' }}>
            {scanMutation.isPending ? 'Scanning...' : 'Run Scan'}
          </button>
        </Tooltip>
        <Tooltip content="Generates a CTO Performance Report covering the last 7 days.">
          <button onClick={() => ctoMutation.mutate()} disabled={ctoMutation.isPending}
            className="px-3 py-1.5 text-xs rounded-md disabled:opacity-50 transition-colors"
            style={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-text-secondary)' }}>
            {ctoMutation.isPending ? 'Generating...' : 'Generate CTO Report'}
          </button>
        </Tooltip>
        <Tooltip content="Collects training examples from recently closed trades.">
          <button onClick={() => collectMutation.mutate()} disabled={collectMutation.isPending}
            className="px-3 py-1.5 text-xs rounded-md disabled:opacity-50 transition-colors"
            style={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-text-secondary)' }}>
            {collectMutation.isPending ? 'Collecting...' : 'Collect Training Data'}
          </button>
        </Tooltip>
      </div>

      {/* Headline KPIs */}
      {/* Fix for #247 */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="arcis-card text-center" style={{ padding: '12px' }}>
          <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Sharpe ratio</div>
          <div className="text-xl font-medium" style={{ fontFamily: 'var(--font-mono)', color: hasTrades ? ((kpis.sharpe_ratio || 0) > 0.5 ? 'var(--teal-400)' : (kpis.sharpe_ratio || 0) < 0 ? 'var(--danger)' : 'var(--arcis-text)') : 'var(--arcis-text)' }}>
            {hasTrades ? (kpis.sharpe_ratio || 0).toFixed(2) : '--'}
          </div>
        </div>
        <div className="arcis-card text-center" style={{ padding: '12px' }}>
          <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Win rate</div>
          <div className="text-xl font-medium" style={{ fontFamily: 'var(--font-mono)', color: hasTrades ? ((kpis.win_rate || 0) > 0.45 ? 'var(--teal-400)' : 'var(--danger)') : 'var(--arcis-text)' }}>
            {hasTrades ? `${((kpis.win_rate || 0) * 100).toFixed(1)}%` : '--'}
          </div>
        </div>
        <div className="arcis-card text-center" style={{ padding: '12px' }}>
          <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Max drawdown</div>
          <div className="text-xl font-medium" style={{ fontFamily: 'var(--font-mono)', color: hasTrades ? ((kpis.max_drawdown_pct || 0) < 15 ? 'var(--teal-400)' : 'var(--danger)') : 'var(--arcis-text)' }}>
            {hasTrades ? `${(kpis.max_drawdown_pct || 0).toFixed(1)}%` : '--'}
          </div>
        </div>
        <Tooltip content="Measures how well the model's confidence predictions match actual outcomes. Requires 50+ closed trades.">
          <div className="arcis-card text-center" style={{ padding: '12px' }}>
            <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Confidence cal.</div>
            <div className="text-xl font-medium" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text)' }}>
              {closedCount >= 50 ? (kpis.confidence_calibration || 0).toFixed(3) : `< ${closedCount}/50 trades`}
            </div>
          </div>
        </Tooltip>
        <Tooltip content="Average quality score from Claude-graded rubric evaluation of trade reasoning.">
          <div className="arcis-card text-center" style={{ padding: '12px' }}>
            <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Rubric score</div>
            <div className="text-xl font-medium" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text)' }}>
              {kpis.avg_rubric_score != null ? `${kpis.avg_rubric_score.toFixed(1)}/5` : 'Not scored yet'}
            </div>
          </div>
        </Tooltip>
      </div>

      {/* System status cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard label="Shadow Equity" value={equity.toLocaleString(undefined, { minimumFractionDigits: 0 })} prefix="$" delta={equityDelta} />
        <MetricCard label="Open Trades" value={openTrades?.open_count || accountData?.open_positions || 0} />
        <MetricCard label="Win Rate" value={closedData?.metrics?.win_rate != null ? `${(closedData.metrics.win_rate * 100).toFixed(1)}%` : accountData?.win_rate != null ? `${(accountData.win_rate * 100).toFixed(1)}%` : '--'} />
        <MetricCard label="Model Version" value={status?.model_version || 'base'} delta={training ? `${training.dataset_total} examples` : null} />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <div className="lg:col-span-3 arcis-card">
          <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>Cumulative P&L</h3>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={chartData}>
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--arcis-text-muted)' }} />
                <YAxis tick={{ fontSize: 11, fill: 'var(--arcis-text-muted)' }} />
                {/* Fix for #250: add tooltip text color for dark mode readability */}
                <RechartsTooltip contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-text-secondary)', borderRadius: 8, fontSize: 12, color: 'var(--tooltip-text)' }} />
                {/* Fix for #250: increase fill opacity from 0.25 to 0.3 for dark mode readability */}
                <Area type="monotone" dataKey="cumPnl" stroke="var(--teal-400)" fill="var(--teal-400)" fillOpacity={0.3} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="text-center py-12 text-sm" style={{ color: 'var(--arcis-text-muted)' }}>No closed trades yet</div>
          )}
        </div>
        <div className="lg:col-span-2 arcis-card">
          <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>Training Progress</h3>
          {training && (
            <div className="space-y-3 text-sm">
              <div className="flex justify-between"><span style={{ color: 'var(--arcis-border)' }}>Model</span><span>{training.model_name}</span></div>
              <div className="flex justify-between"><span style={{ color: 'var(--arcis-border)' }}>Examples</span><span style={{ fontFamily: 'var(--font-mono)' }}>{training.dataset_total}</span></div>
              <div className="flex justify-between"><span style={{ color: 'var(--arcis-border)' }}>New</span><span style={{ fontFamily: 'var(--font-mono)' }}>{training.new_since_last_train}</span></div>
              <div className="flex justify-between"><span style={{ color: 'var(--arcis-border)' }}>Status</span>
                <StatusBadge text={training.train_queued ? 'Queued' : 'Collecting'} variant={training.train_queued ? 'warning' : 'info'} />
              </div>
              <div className="mt-2">
                <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--arcis-text-secondary)' }}>
                  <div className="h-full rounded-full" style={{ background: 'var(--teal-500)', width: `${Math.min(100, (training.new_since_last_train / 50) * 100)}%` }} />
                </div>
                <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-muted)' }}>{training.new_since_last_train}/50 to next training</div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Live Activity Feed */}
      <ActivityFeed />

      {/* Open trades table */}
      <div className="arcis-card">
        <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>Open Shadow Trades</h3>
        <DataTable columns={tradeColumns} data={openTrades?.open_trades || []} />
      </div>

      {/* Today's packets */}
      {packets && packets.length > 0 && (
        <div className="arcis-card">
          <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>Today's Packets ({packets.length})</h3>
          <div className="space-y-3">
            {packets.slice(0, 5).map((p, i) => (
              <div key={i} className="rounded p-3" style={{ border: '1px solid var(--arcis-text-secondary)' }}>
                <div className="flex items-center gap-3 mb-1">
                  <span className="font-medium">{p.ticker}</span>
                  <span className="text-sm" style={{ color: 'var(--arcis-border)' }}>{p.company_name}</span>
                  <StatusBadge text={`Score: ${p.priority_score || 0}`} variant="info" />
                </div>
                <p className="text-sm" style={{ color: 'var(--arcis-border)' }}>{(p.thesis_text || '').slice(0, 200)}...</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Scan Metrics */}
      {scanMetrics && Array.isArray(scanMetrics) && scanMetrics.length > 0 && (() => {
        const today = new Date().toISOString().slice(0, 10)
        const todayScans = scanMetrics.filter(m => (m.created_at || m.scan_date || '').slice(0, 10) === today)
        const totalToday = todayScans.length
        const packetsToday = todayScans.reduce((s, m) => s + (m.packet_worthy || 0), 0)
        const llmSuccessToday = todayScans.reduce((s, m) => s + (m.llm_success || 0), 0)
        const llmTotalToday = todayScans.reduce((s, m) => s + (m.llm_total || 0), 0)
        const llmRate = llmTotalToday > 0 ? (llmSuccessToday / llmTotalToday * 100) : 0
        const llmColor = llmRate > 90 ? 'var(--arcis-success)' : llmRate > 70 ? 'var(--arcis-warning)' : 'var(--arcis-danger)'

        // Aggregate by day for sparkline (last 7 days)
        const byDay = {}
        scanMetrics.forEach(m => {
          const d = (m.created_at || m.scan_date || '').slice(0, 10)
          if (!d) return
          if (!byDay[d]) byDay[d] = 0
          byDay[d]++
        })
        const sparkData = Object.entries(byDay).sort((a, b) => a[0].localeCompare(b[0])).slice(-7).map(([date, count]) => ({ date: date.slice(5), count }))

        return (
          <div className="arcis-card">
            <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>Scan Metrics</h3>
            <div className="flex flex-col md:flex-row gap-4">
              <div className="flex gap-4 text-sm">
                <div>
                  <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>Today's Scans</div>
                  <div className="financial-data text-lg" style={{ color: 'var(--arcis-text-primary)' }}>{totalToday}</div>
                </div>
                <div>
                  <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>Packets</div>
                  <div className="financial-data text-lg" style={{ color: 'var(--arcis-text-primary)' }}>{packetsToday}</div>
                </div>
                <div>
                  <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>LLM Success</div>
                  <div className="financial-data text-lg" style={{ color: llmColor }}>
                    {llmTotalToday > 0 ? `${llmRate.toFixed(0)}%` : '--'}
                  </div>
                </div>
              </div>
              {sparkData.length > 1 && (
                <div className="flex-1 min-w-[200px]">
                  <div className="text-xs mb-1" style={{ color: 'var(--arcis-text-muted)' }}>7-Day Trend</div>
                  <ResponsiveContainer width="100%" height={48}>
                    <LineChart data={sparkData}>
                      <Line type="monotone" dataKey="count" stroke="var(--arcis-accent)" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </div>
        )
      })()}
    </div>
  )
}
