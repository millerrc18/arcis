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
import { XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, Area, AreaChart } from 'recharts'

function parseAuditSummary(raw) {
  if (!raw) return null
  let text = raw
  // Strip code fences and JSON wrapper
  text = text.replace(/```json\s*/gi, '').replace(/```\s*/g, '')
  // Try to parse as JSON to extract summary
  try {
    const parsed = JSON.parse(text)
    return parsed.summary || parsed.overall_summary || text
  } catch {
    // Not JSON — try to extract summary from structured text
    const match = text.match(/"summary"\s*:\s*"([^"]+)"/i)
    if (match) return match[1]
    // Strip leading JSON keys
    text = text.replace(/^\s*\{\s*"overall_assessment"\s*:\s*"[^"]*"\s*,?\s*/i, '')
    text = text.replace(/^\s*"summary"\s*:\s*"?/i, '')
    text = text.replace(/"?\s*,?\s*"[^"]*"\s*:\s*[\[{].*$/s, '')
    return text.trim().replace(/^"|"$/g, '') || raw.slice(0, 200)
  }
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

  // D1: Parse audit data properly
  const auditAssessment = auditData?.overall_assessment || auditData?.audit?.overall_assessment
  const rawSummary = auditData?.summary || auditData?.audit?.summary
  const auditSummary = parseAuditSummary(rawSummary)

  if (statusLoading) return <LoadingSpinner />

  // D2: Fix shadow equity — use account endpoint which correctly computes starting_capital + closed_pnl
  const startingCapital = configData?.risk?.starting_capital || 100000
  const rawEquity = accountData?.equity
  const equity = (rawEquity && rawEquity > 0) ? rawEquity : (startingCapital + (accountData?.closed_pnl || 0))
  const equityDelta = equity - startingCapital

  // Build cumulative P&L chart data
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

  // D2: Compute metrics with lower thresholds
  const kpis = ctoData?.headline_kpis || {}
  const ts = ctoData?.trade_summary || {}
  const closedCount = ts.trades_closed || accountData?.total_closed || 0
  const hasTrades = closedCount >= 2  // Show with >= 2 trades (was 5)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium" style={{ color: 'var(--slate-100)' }}>Dashboard</h2>
        <Tooltip content="EMERGENCY: Immediately stops all new trade entries. Open positions are NOT closed — they continue to be managed by bracket orders. Use only in emergencies. Resume with the 'resume-trading' CLI command.">
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

      {/* Halt warning banner */}
      {isHalted && (
        <div className="rounded-lg p-3 text-sm" style={{ background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.4)', color: '#fca5a5' }}>
          Trading is HALTED. No new positions will be opened. Click "Resume Trading" to resume.
        </div>
      )}

      {/* D1: Audit warning banner — cleaned up */}
      {auditAssessment && auditAssessment !== 'green' && (
        <div className="rounded-lg p-3 text-sm" style={{
          background: auditAssessment === 'red' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(245, 158, 11, 0.15)',
          border: `1px solid ${auditAssessment === 'red' ? 'rgba(239, 68, 68, 0.4)' : 'rgba(245, 158, 11, 0.4)'}`,
          color: auditAssessment === 'red' ? '#fca5a5' : 'var(--amber-300)',
        }}>
          <span className="font-medium uppercase">Audit: {auditAssessment}</span>
          {auditSummary && <span className="ml-2">{'\u2014'} {auditSummary.slice(0, 300)}</span>}
        </div>
      )}

      {/* Toast notification */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 rounded-lg px-4 py-2 text-sm shadow-lg" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
          {toast}
        </div>
      )}

      {/* D3: Actions with tooltips */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs uppercase tracking-wide mr-2" style={{ color: 'var(--slate-400)' }}>Actions</span>
        <Tooltip content="Triggers an immediate market scan outside the normal 30-min schedule. Use when you want to check for new setups between scheduled scans.">
          <button onClick={() => scanMutation.mutate()} disabled={scanMutation.isPending}
            className="px-3 py-1.5 text-xs rounded-md disabled:opacity-50 transition-colors"
            style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
            {scanMutation.isPending ? 'Scanning...' : 'Run Scan'}
          </button>
        </Tooltip>
        <Tooltip content="Generates a CTO Performance Report covering the last 7 days. Includes Sharpe, win rate, P&L, and strategy assessment. Normally runs automatically on Saturdays.">
          <button onClick={() => ctoMutation.mutate()} disabled={ctoMutation.isPending}
            className="px-3 py-1.5 text-xs rounded-md disabled:opacity-50 transition-colors"
            style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
            {ctoMutation.isPending ? 'Generating...' : 'Generate CTO Report'}
          </button>
        </Tooltip>
        <Tooltip content="Collects training examples from recently closed trades. Normally runs automatically at 4:30 PM ET and 6:00 PM ET.">
          <button onClick={() => collectMutation.mutate()} disabled={collectMutation.isPending}
            className="px-3 py-1.5 text-xs rounded-md disabled:opacity-50 transition-colors"
            style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
            {collectMutation.isPending ? 'Collecting...' : 'Collect Training Data'}
          </button>
        </Tooltip>
      </div>

      {/* D2: Headline KPIs — fixed thresholds */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="rounded-lg p-3" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
          <div className="text-xs" style={{ color: 'var(--slate-400)' }}>Sharpe ratio</div>
          <div className="text-xl font-medium" style={{ fontFamily: 'var(--font-mono)', color: hasTrades ? ((kpis.sharpe_ratio || 0) > 0.5 ? 'var(--teal-400)' : (kpis.sharpe_ratio || 0) < 0 ? 'var(--danger)' : 'var(--slate-100)') : 'var(--slate-100)' }}>
            {hasTrades ? (kpis.sharpe_ratio || 0).toFixed(2) : '--'}
          </div>
        </div>
        <div className="rounded-lg p-3" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
          <div className="text-xs" style={{ color: 'var(--slate-400)' }}>Win rate</div>
          <div className="text-xl font-medium" style={{ fontFamily: 'var(--font-mono)', color: hasTrades ? ((kpis.win_rate || 0) > 0.45 ? 'var(--teal-400)' : 'var(--danger)') : 'var(--slate-100)' }}>
            {hasTrades ? `${((kpis.win_rate || 0) * 100).toFixed(1)}%` : '--'}
          </div>
        </div>
        <div className="rounded-lg p-3" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
          <div className="text-xs" style={{ color: 'var(--slate-400)' }}>Max drawdown</div>
          <div className="text-xl font-medium" style={{ fontFamily: 'var(--font-mono)', color: hasTrades ? ((kpis.max_drawdown_pct || 0) < 15 ? 'var(--teal-400)' : 'var(--danger)') : 'var(--slate-100)' }}>
            {hasTrades ? `${(kpis.max_drawdown_pct || 0).toFixed(1)}%` : '--'}
          </div>
        </div>
        <Tooltip content="Measures how well the model's confidence predictions match actual outcomes. Requires 50+ closed trades for statistical significance.">
          <div className="rounded-lg p-3" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
            <div className="text-xs" style={{ color: 'var(--slate-400)' }}>Confidence cal.</div>
            <div className="text-xl font-medium" style={{ fontFamily: 'var(--font-mono)', color: 'var(--slate-100)' }}>
              {closedCount >= 50 ? (kpis.confidence_calibration || 0).toFixed(3) : `< ${closedCount}/50 trades`}
            </div>
          </div>
        </Tooltip>
        <Tooltip content="Average quality score from Claude-graded rubric evaluation of trade reasoning. Requires running the scoring pipeline ($5-8 API cost).">
          <div className="rounded-lg p-3" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
            <div className="text-xs" style={{ color: 'var(--slate-400)' }}>Rubric score</div>
            <div className="text-xl font-medium" style={{ fontFamily: 'var(--font-mono)', color: 'var(--slate-100)' }}>
              {kpis.avg_rubric_score != null ? `${kpis.avg_rubric_score.toFixed(1)}/5` : 'Not scored yet'}
            </div>
          </div>
        </Tooltip>
      </div>

      {/* D2: System status cards — fixed equity */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard label="Shadow Equity" value={equity.toLocaleString(undefined, { minimumFractionDigits: 0 })} prefix="$" delta={equityDelta} />
        <MetricCard label="Open Trades" value={openTrades?.open_count || accountData?.open_positions || 0} />
        <MetricCard label="Win Rate" value={closedData?.metrics?.win_rate != null ? `${closedData.metrics.win_rate.toFixed(1)}%` : accountData?.win_rate != null ? `${(accountData.win_rate * 100).toFixed(1)}%` : '--'} />
        <MetricCard label="Model Version" value={status?.model_version || 'base'} delta={training ? `${training.dataset_total} examples` : null} />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <div className="lg:col-span-3 rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
          <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--slate-400)' }}>Cumulative P&L</h3>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={chartData}>
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--slate-400)' }} />
                <YAxis tick={{ fontSize: 11, fill: 'var(--slate-400)' }} />
                <RechartsTooltip contentStyle={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)', borderRadius: 8, fontSize: 12 }} />
                <Area type="monotone" dataKey="cumPnl" stroke="var(--teal-400)" fill="var(--teal-400)" fillOpacity={0.1} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="text-center py-12 text-sm" style={{ color: 'var(--slate-400)' }}>No closed trades yet</div>
          )}
        </div>
        <div className="lg:col-span-2 rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
          <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--slate-400)' }}>Training Progress</h3>
          {training && (
            <div className="space-y-3 text-sm">
              <div className="flex justify-between"><span style={{ color: 'var(--slate-300)' }}>Model</span><span>{training.model_name}</span></div>
              <div className="flex justify-between"><span style={{ color: 'var(--slate-300)' }}>Examples</span><span style={{ fontFamily: 'var(--font-mono)' }}>{training.dataset_total}</span></div>
              <div className="flex justify-between"><span style={{ color: 'var(--slate-300)' }}>New</span><span style={{ fontFamily: 'var(--font-mono)' }}>{training.new_since_last_train}</span></div>
              <div className="flex justify-between"><span style={{ color: 'var(--slate-300)' }}>Status</span>
                <StatusBadge text={training.train_queued ? 'Queued' : 'Collecting'} variant={training.train_queued ? 'warning' : 'info'} />
              </div>
              <div className="mt-2">
                <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--slate-600)' }}>
                  <div className="h-full rounded-full" style={{ background: 'var(--teal-500)', width: `${Math.min(100, (training.new_since_last_train / 50) * 100)}%` }} />
                </div>
                <div className="text-xs mt-1" style={{ color: 'var(--slate-400)' }}>{training.new_since_last_train}/50 to next training</div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Live Activity Feed */}
      <ActivityFeed />

      {/* Open trades table */}
      <div className="rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
        <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--slate-400)' }}>Open Shadow Trades</h3>
        <DataTable columns={tradeColumns} data={openTrades?.open_trades || []} />
      </div>

      {/* Today's packets */}
      {packets && packets.length > 0 && (
        <div className="rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
          <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--slate-400)' }}>Today's Packets ({packets.length})</h3>
          <div className="space-y-3">
            {packets.slice(0, 5).map((p, i) => (
              <div key={i} className="rounded p-3" style={{ border: '1px solid var(--slate-600)' }}>
                <div className="flex items-center gap-3 mb-1">
                  <span className="font-medium">{p.ticker}</span>
                  <span className="text-sm" style={{ color: 'var(--slate-300)' }}>{p.company_name}</span>
                  <StatusBadge text={`Score: ${p.priority_score || 0}`} variant="info" />
                </div>
                <p className="text-sm" style={{ color: 'var(--slate-300)' }}>{(p.thesis_text || '').slice(0, 200)}...</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
