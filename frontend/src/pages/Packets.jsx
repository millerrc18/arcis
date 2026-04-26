import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'
import StatusBadge from '../components/StatusBadge'
import PnlText from '../components/PnlText'

function scoreVariant(score) {
  if (score >= 90) return 'success'
  if (score >= 70) return 'warning'
  return 'neutral'
}

// Packets.thesis_text historically concatenates the system prompt + the LLM's
// XML output. Display should show only the analysis — strip everything before
// the first recognized XML tag (why_now, thesis, setup_analysis, etc.).
const ANALYSIS_START_TAGS = [
  '<why_now>', '<thesis>', '<setup_analysis>', '<analysis>', '<assessment>',
  '<pullback_analysis>', '<mean_reversion_analysis>',
]
function cleanAnalysis(text) {
  if (!text) return ''
  let earliest = -1
  for (const tag of ANALYSIS_START_TAGS) {
    const i = text.indexOf(tag)
    if (i !== -1 && (earliest === -1 || i < earliest)) earliest = i
  }
  return (earliest === -1 ? text : text.slice(earliest)).trim()
}

export default function Packets() {
  const [days, setDays] = useState(7)
  const [ticker, setTicker] = useState('')
  const [expanded, setExpanded] = useState(null)

  const { data: packets, isLoading } = useQuery({
    queryKey: ['packets', days, ticker],
    queryFn: () => api.getPackets({ days, ...(ticker && { ticker: ticker.toUpperCase() }) }),
  })

  if (isLoading) return <LoadingSpinner />

  return (
    <div className="space-y-4 md:space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Packets</h2>
        <div className="flex gap-3">
          <select value={days} onChange={e => setDays(Number(e.target.value))}
            className="px-3 py-1.5 text-sm"
            style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-primary)', borderRadius: 'var(--radius-sm)' }}>
            <option value={1}>Today</option>
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
          </select>
          <input type="text" placeholder="Filter ticker..." value={ticker} onChange={e => setTicker(e.target.value)}
            className="px-3 py-1.5 text-sm w-32"
            style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-primary)', borderRadius: 'var(--radius-sm)' }} />
        </div>
      </div>

      {(!Array.isArray(packets) || packets.length === 0) ? (
        <EmptyState message="No packets in this period" />
      ) : (
        <div className="space-y-3">
          {packets.map((p, i) => (
            <div key={p.recommendation_id || i} className="p-4"
              style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 'var(--radius-sm)' }}>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-3">
                  <span className="font-medium text-lg" style={{ fontFamily: 'var(--font-mono)' }}>{p.ticker}</span>
                  <span style={{ color: 'var(--arcis-text-secondary)' }}>{p.company_name}</span>
                  <StatusBadge text={`Score: ${(p.priority_score || 0).toFixed(0)}`} variant={scoreVariant(p.priority_score || 0)} />
                  <StatusBadge text={`Conf: ${p.confidence_score || 0}/10`} variant="neutral" />
                  {p.event_risk_flag && p.event_risk_flag !== 'none' && (
                    <StatusBadge text="Earnings Risk" variant="warning" />
                  )}
                </div>
                <div className="flex items-center gap-3 text-sm">
                  <span style={{ color: 'var(--arcis-text-secondary)' }}>{(p.created_at || '').slice(0, 10)}</span>
                  {p.shadow_pnl_dollars != null && <PnlText value={p.shadow_pnl_dollars} percent={p.shadow_pnl_pct} />}
                </div>
              </div>
              <div className="grid grid-cols-3 gap-4 text-sm mb-2" style={{ fontFamily: 'var(--font-mono)' }}>
                <div><span style={{ color: 'var(--arcis-text-secondary)', textTransform: 'uppercase', fontSize: 11, letterSpacing: '0.06em' }}>Entry:</span> {p.entry_zone}</div>
                <div><span style={{ color: 'var(--arcis-text-secondary)', textTransform: 'uppercase', fontSize: 11, letterSpacing: '0.06em' }}>Stop:</span> {p.stop_level}</div>
                <div><span style={{ color: 'var(--arcis-text-secondary)', textTransform: 'uppercase', fontSize: 11, letterSpacing: '0.06em' }}>Targets:</span> {p.target_1} / {p.target_2}</div>
              </div>
              <button onClick={() => setExpanded(expanded === i ? null : i)}
                className="text-xs hover:underline" style={{ color: 'var(--arcis-accent)' }}>
                {expanded === i ? 'Hide analysis' : 'Show analysis'}
              </button>
              {expanded === i && (
                <div className="mt-3 text-sm whitespace-pre-wrap pt-3" style={{ color: 'var(--arcis-text-secondary)', borderTop: '1px solid var(--arcis-border)' }}>
                  {cleanAnalysis(p.thesis_text) || 'No analysis available'}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
