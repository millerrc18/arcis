import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, fetchApi } from '../api'
import { IS_CLOUD } from '../config'
import { hapticWarning, hapticSuccess } from '../native'
import MetricCard from '../components/MetricCard'
import KPIStrip from '../components/dashboard/KPIStrip'
import BrokerExceptionsPanel from '../components/dashboard/BrokerExceptionsPanel'
import PreflightStatusCard from '../components/dashboard/PreflightStatusCard'
import DataTable from '../components/DataTable'
import LoadingSpinner from '../components/LoadingSpinner'
import PnlText from '../components/PnlText'
import StatusBadge from '../components/StatusBadge'
import ActivityFeed from '../components/ActivityFeed'
import Tooltip from '../components/Tooltip'
import { XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, Area, AreaChart, Line, LineChart } from 'recharts'
import { TrendingUp, TrendingDown, Minus, AlertTriangle, Zap, ChevronDown, ChevronUp } from 'lucide-react'
import PlatformStatusWidget from '../components/PlatformStatusWidget.jsx'
import QuickStatsPanel from '../components/system/QuickStatsPanel.jsx'
import SystemIndexPanel from '../components/system/SystemIndexPanel.jsx'
import WhatsNewPanel from '../components/system/WhatsNewPanel.jsx'

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
        className="inline-flex items-center gap-1 px-3 py-1 text-xs font-medium cursor-pointer"
        style={{ borderRadius: 'var(--radius-sm)', background: chip.bg, border: `1px solid ${chip.border}`, color: chip.color }}
      >
        <span>{chip.dot}</span>
        <span>{chip.label}</span>
        {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {expanded && (
        <div className="p-4 mt-2" style={{ borderRadius: 'var(--radius-sm)', border: `1px solid ${chip.border}`, background: 'var(--arcis-bg-surface)' }}>
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
  if (score >= 70) return 'var(--arcis-success)'
  if (score >= 40) return 'var(--amber-400)'
  return 'var(--danger)'
}

// #631-7 — Qualitative label gives the operator a one-word read on what the
// numeric Build Score means. Pre-fix the score was a bare number with no
// scale legend — a user landing on the page couldn't tell if 19.8 was good
// or bad.
function scoreLabel(score) {
  if (score >= 80) return 'Elite'
  if (score >= 65) return 'Strong'
  if (score >= 45) return 'Developing'
  if (score >= 25) return 'Early'
  return 'Nascent'
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
        <div className="flex flex-col items-center lg:items-start gap-1 min-w-[140px]"
             title="Build Score — composite 0-100 metric across 6 components (Gate Velocity, System Health, Data Asset, Model Quality, Research Velocity, Reliability). Higher is better.">
          <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-muted)' }}>
            Build Score
          </div>
          <div className="text-5xl font-bold" style={{ fontFamily: 'var(--font-mono)', color: scoreColor(score) }}>
            {score.toFixed(1)}<span className="text-2xl" style={{ color: 'var(--arcis-text-muted)' }}>/100</span>
          </div>
          {/* #631-7 — Qualitative label below the number gives immediate context. */}
          <div className="text-xs uppercase tracking-wide" style={{ color: scoreColor(score), letterSpacing: '0.1em' }}>
            {scoreLabel(score)}
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
                <span className="flex items-center gap-1 text-xs px-2 py-0.5" style={{ borderRadius: 'var(--radius-sm)', background: 'rgba(239,68,68,0.15)', color: '#fca5a5' }}>
                  <AlertTriangle size={10} /> Decay
                </span>
              </Tooltip>
            )}
          </div>
        </div>

        {/* Center: Component bars */}
        {/* #631-6 — Each component score is now explicitly shown as N/100 so a
            value of 0 reads as "0 out of 100" (low score) instead of being
            ambiguous with "no events / system OK". Title attribute adds the
            score-scale tooltip on hover. */}
        <div className="flex-1 grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-2"
             title="Build Score components — 0-100 scale; higher is better">
          {Object.entries(componentLabels).map(([key, label]) => {
            const val = components[key] ?? 0
            return (
              <div key={key}>
                <div className="flex justify-between text-xs mb-1">
                  <span style={{ color: 'var(--arcis-text-muted)' }}>{label}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', color: scoreColor(val) }}>{val.toFixed(0)}/100</span>
                </div>
                <div className="h-1.5 overflow-hidden" style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-text-secondary)' }}>
                  <div className="h-full" style={{ borderRadius: 'var(--radius-sm)', width: `${Math.min(100, val)}%`, background: scoreColor(val) }} />
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
                <Line type="monotone" dataKey="score" stroke="var(--arcis-accent)" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
          <div className="text-xs text-center" style={{ color: 'var(--arcis-text-muted)' }}>
            Phase {phase.current_phase || 1}: {phase.trades_closed || 0}/{phase.trades_required || 50} trades
          </div>
          <div className="h-1.5 w-full max-w-[100px] overflow-hidden" style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-text-secondary)' }}>
            <div className="h-full" style={{ borderRadius: 'var(--radius-sm)', width: `${phase.pct_complete || 0}%`, background: 'var(--arcis-accent)' }} />
          </div>
        </div>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const queryClient = useQueryClient()

  // Task 12c: desk filter — default swing-only (backward compat).
  // researchDesks populated at render time from /api/shadow/desks.
  const [deskFilter, setDeskFilter] = useState('swing')
  const [researchDesks, setResearchDesks] = useState([])

  const { data: status, isLoading: statusLoading } = useQuery({ queryKey: ['status'], queryFn: api.getStatus, refetchInterval: 60000 })
  const { data: openTrades } = useQuery({ queryKey: ['shadow-open', deskFilter], queryFn: () => api.getOpenTrades(deskFilter), refetchInterval: 60000 })
  const { data: closedData } = useQuery({ queryKey: ['shadow-closed', deskFilter], queryFn: () => api.getClosedTrades(30, deskFilter), refetchInterval: 60000 })
  const { data: training } = useQuery({ queryKey: ['training-status'], queryFn: api.getTrainingStatus, refetchInterval: 60000 })
  const { data: packets } = useQuery({ queryKey: ['packets'], queryFn: () => api.getPackets({ days: 1 }), refetchInterval: 60000 })
  const { data: haltData } = useQuery({ queryKey: ['halt-status'], queryFn: api.getHaltStatus, refetchInterval: 30000 })
  const { data: auditData } = useQuery({ queryKey: ['audit-latest'], queryFn: api.getLatestAudit, refetchInterval: 60000 })
  const { data: ctoData } = useQuery({ queryKey: ['cto-report'], queryFn: () => api.getCtoReport(365), refetchInterval: 60000 })
  const { data: configData } = useQuery({ queryKey: ['config'], queryFn: api.getConfig, refetchInterval: 300000 })
  const { data: accountData } = useQuery({ queryKey: ['shadow-account', deskFilter], queryFn: () => api.getAccount(deskFilter), refetchInterval: 60000 })
  const { data: buildScore } = useQuery({ queryKey: ['build-score'], queryFn: api.getBuildScore, refetchInterval: 120000 })
  const { data: scanMetrics } = useQuery({ queryKey: ['scan-metrics'], queryFn: () => api.getScanMetrics(50), refetchInterval: 60000 })
  const { data: systemIndex, isLoading: systemIndexLoading } = useQuery({ queryKey: ['system-index'], queryFn: api.getSystemIndex, refetchInterval: 60000 })
  const { data: kpiData } = useQuery({ queryKey: ['kpis'], queryFn: () => fetchApi('/kpis'), refetchInterval: 30000 })

  // Task 12c: fetch distinct desk values from DB at render time (spec line 1014).
  // Populates the dropdown with any research desks currently in shadow_trades.
  // I7 fix: was useState() initializer (non-reactive); replaced with useEffect.
  useEffect(() => {
    api.getShadowDesks().then(desks => {
      if (Array.isArray(desks)) {
        setResearchDesks(desks.filter(d => d !== 'swing' && d !== 'all'))
      }
    }).catch(() => {})
  }, [])

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

  // #631-19 — Add an Opened-date column so multiple positions in the same
  // ticker (e.g., 2× CVS rows during the 4/21 quarantine incident) are
  // visually distinguishable instead of looking like duplicate rows.
  const tradeColumns = [
    { key: 'ticker', label: 'Ticker', type: 'text' },
    { key: 'created_at', label: 'Opened', type: 'date' },
    { key: 'entry_price', label: 'Entry', type: 'currency' },
    { key: 'current_price', label: 'Current', type: 'currency' },
    { key: 'pnl_dollars', label: 'P&L', type: 'currency' },
    { key: 'duration_days', label: 'Days', type: 'number' },
    { key: 'stop_price', label: 'Stop', type: 'currency' },
    { key: 'target_1', label: 'Target', type: 'currency' },
  ]

  // Round 8.B replaced the legacy headline_kpis hero block with <KPIStrip />
  // which fetches /api/kpis directly. The old `const kpis = ctoData?.headline_kpis`
  // assignment is removed — was a dead reference after the hero rebuild.
  const ts = ctoData?.trade_summary || {}
  const closedCount = ts.trades_closed || accountData?.total_closed || 0
  const hasTrades = closedCount >= 2

  // G5: approaching-timeout count — derived from openTrades already fetched.
  // Shows operator how many open positions are near or past their timeout.
  const approachingTimeoutCount = (openTrades?.open_trades || [])
    .filter(t => t.timeout_status === 'approaching' || t.timeout_status === 'overdue')
    .length

  return (
    <div className="space-y-4 md:space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text)' }}>Dashboard</h2>
        <div className="flex items-center gap-3">
          <AuditChip auditData={auditData} auditAssessment={auditAssessment} auditSummary={auditSummary} />
          {/* IB integration: show live broker connection status */}
          {status?.live_broker && (
            <span className="text-xs" style={{ color: status.ib_connected ? 'var(--arcis-success)' : 'var(--arcis-text-muted)' }}>
              {status.live_broker.toUpperCase()} {status.ib_connected ? 'Connected' : ''}
            </span>
          )}
          <Tooltip content="EMERGENCY: Immediately stops all new trade entries. Open positions are NOT closed.">
            <button
              onClick={() => {
                if (isHalted || confirm('Are you sure? This stops all new trades.')) {
                  if (isHalted) { hapticSuccess(); } else { hapticWarning(); }
                  haltMutation.mutate()
                }
              }}
              className="px-4 py-2 font-medium text-sm text-white transition-colors"
              style={{ borderRadius: 'var(--radius-sm)', background: isHalted ? 'var(--success)' : 'var(--danger)' }}
            >
              {isHalted ? 'RESUME TRADING' : 'HALT TRADING'}
            </button>
          </Tooltip>
        </div>
      </div>

      {/* Halt warning banner */}
      {isHalted && (
        <div className="p-3 text-sm" style={{ borderRadius: 'var(--radius-sm)', background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.4)', color: '#fca5a5' }}>
          Trading is HALTED. No new positions will be opened. Click "Resume Trading" to resume.
        </div>
      )}

      {/* Audit chip is now in header bar */}

      {/* Toast notification */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 px-4 py-2 text-sm" style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)' }}>
          {toast}
        </div>
      )}

      {/* BUILD SCORE HERO */}
      <BuildScoreHero data={buildScore} />

      {/* System Index panels — capability_registry v1 (Sprint 1B) */}
      <QuickStatsPanel data={systemIndex} isLoading={systemIndexLoading} />
      <SystemIndexPanel data={systemIndex} isLoading={systemIndexLoading} />
      <WhatsNewPanel />

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

      {/* Task 12c: Desk filter — populates from /api/shadow/desks at render time */}
      <div className="flex items-center gap-3">
        <label className="text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-muted)' }}>
          Desk filter:
        </label>
        <select
          value={deskFilter}
          onChange={e => setDeskFilter(e.target.value)}
          className="px-2 py-1 text-xs"
          style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text)' }}
        >
          <option value="swing">Swing</option>
          <option value="all">All (aggregate)</option>
          {researchDesks.map(d => <option key={d} value={d}>{d}</option>)}
        </select>
      </div>

      {/* Research Platform status card — renders only when strategies exist */}
      <PlatformStatusWidget />

      {/* 5-KPI hero strip — Track 1.5 / Round 8.B (resolves R1, S1, S2, G3, G6) */}
      <KPIStrip kpis={kpiData} />

      {/* Broker exceptions panel — Track 1.5 / Round 8.C (closes G1) */}
      <BrokerExceptionsPanel />

      {/* Preflight status card — Track 1.5 / Round 8.D (S4 preflight echo) */}
      <PreflightStatusCard />

      {/* System status cards — G5: 5th card always-visible Approaching Timeout */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        {/* R3 — Explicit data-source label so equity card / cumulative P&L divergence
            on first live trade is explainable. Equity reads Alpaca paper account balance;
            chart reads shadow_trades (quarantine-filtered). */}
        <Tooltip content="Source: Alpaca paper account balance. Note: this value will diverge from the cumulative P&L chart (shadow_trades canonical, quarantine-filtered) on first live trade.">
          <MetricCard label="Shadow Equity" value={equity.toLocaleString(undefined, { minimumFractionDigits: 0 })} prefix="$" delta={equityDelta} />
        </Tooltip>
        <MetricCard label="Open Trades" value={openTrades?.open_count || accountData?.open_positions || 0} />
        {/* R2 — Silent Alpaca fallback removed. Alpaca's win_rate uses a different
            denominator and includes pre-#651 cascade trades (not quarantine-filtered).
            When shadow_service returns null, show "—" with a tooltip explaining deferral. */}
        <Tooltip content="Win rate not yet computable; need ≥1 closed quarantine-filtered trade. Alpaca's win_rate is suppressed here — it uses a different denominator and includes pre-#651 cascade trades.">
          <MetricCard label="Win Rate" value={closedData?.metrics?.win_rate != null ? `${(closedData.metrics.win_rate * 100).toFixed(1)}%` : '—'} />
        </Tooltip>
        <MetricCard label="Model Version" value={status?.model_version || 'base'} delta={training ? `${training.dataset_total} examples` : null} />
        {/* G5: Always-visible 5th card — empty state shows 0 so first-time users see the feature */}
        <Tooltip content="Trades at or approaching their configured timeout window. Click ShadowLedger to review.">
          <MetricCard label="Approaching Timeout" value={approachingTimeoutCount} />
        </Tooltip>
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <div className="lg:col-span-3 arcis-card">
          <div className="flex items-baseline gap-3 mb-4">
            <h3 className="text-sm uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Cumulative P&L</h3>
            <span className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>shadow_trades canonical, quarantine-filtered</span>
          </div>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={chartData}>
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--arcis-text-muted)' }} />
                <YAxis tick={{ fontSize: 11, fill: 'var(--arcis-text-muted)' }} />
                {/* Fix for #250: add tooltip text color for dark mode readability */}
                <RechartsTooltip contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-text-secondary)', borderRadius: 3, fontSize: 12, color: 'var(--tooltip-text)' }} />
                {/* Fix for #250: increase fill opacity from 0.25 to 0.3 for dark mode readability */}
                <Area type="monotone" dataKey="cumPnl" stroke="var(--arcis-accent)" fill="var(--arcis-accent)" fillOpacity={0.3} strokeWidth={2} />
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
              <div className="flex justify-between"><span style={{ color: 'var(--arcis-text-secondary)' }}>Model</span><span>{training.model_name}</span></div>
              <div className="flex justify-between"><span style={{ color: 'var(--arcis-text-secondary)' }}>Examples</span><span style={{ fontFamily: 'var(--font-mono)' }}>{training.dataset_total}</span></div>
              <div className="flex justify-between"><span style={{ color: 'var(--arcis-text-secondary)' }}>New</span><span style={{ fontFamily: 'var(--font-mono)' }}>{training.new_since_last_train}</span></div>
              <div className="flex justify-between"><span style={{ color: 'var(--arcis-text-secondary)' }}>Status</span>
                <StatusBadge text={training.train_queued ? 'Queued' : 'Collecting'} variant={training.train_queued ? 'warning' : 'info'} />
              </div>
              <div className="mt-2">
                {/* #631-16 — Defensive math: when new_since_last_train is undefined
                    (loading state) the previous expression evaluated to NaN,
                    which CSS rendered as full-width — making 0/50 look 95% full. */}
                {(() => {
                  const newCount = Number(training?.new_since_last_train ?? 0)
                  const pct = Math.max(0, Math.min(100, (newCount / 50) * 100))
                  return (
                    <>
                      <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--arcis-text-secondary)' }}>
                        <div className="h-full" style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-accent)', width: `${pct}%` }} />
                      </div>
                      <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-muted)' }}>{newCount}/50 to next training</div>
                    </>
                  )
                })()}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Live Activity Feed */}
      <ActivityFeed />

      {/* Open trades table */}
      <div className="arcis-card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Open Shadow Trades</h3>
          {/* #631-3 — Surface market-closed state so empty CURRENT/P&L cells
              are not mistaken for a broken data feed. */}
          {status && !status.market_open && (
            <span className="text-xs italic" style={{ color: 'var(--arcis-text-muted)' }}>
              Live prices unavailable — market closed
            </span>
          )}
        </div>
        <DataTable columns={tradeColumns} data={openTrades?.open_trades || []} />
      </div>

      {/* Today's packets */}
      {packets && packets.length > 0 && (
        <div className="arcis-card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Today's Packets ({packets.length})</h3>
            {/* #631-14 — When the list is truncated to the first 5, surface
                that fact + link to the full Packets page so the user has an
                affordance to see the rest. */}
            {packets.length > 5 && (
              <Link to="/packets" className="text-xs hover:opacity-80" style={{ color: 'var(--arcis-accent)' }}>
                View all {packets.length} →
              </Link>
            )}
          </div>
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
            {packets.length > 5 && (
              <div className="text-xs italic text-center" style={{ color: 'var(--arcis-text-muted)' }}>
                Showing 5 of {packets.length} — <Link to="/packets" style={{ color: 'var(--arcis-accent)' }}>view all</Link>
              </div>
            )}
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
