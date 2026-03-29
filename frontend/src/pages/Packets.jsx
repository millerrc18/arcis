import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'
import StatusBadge from '../components/StatusBadge'
import PnlText from '../components/PnlText'
import { FileText } from 'lucide-react'

function scoreVariant(score) {
  if (score >= 90) return 'success'
  if (score >= 70) return 'warning'
  return 'neutral'
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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium" style={{ color: 'var(--slate-100)' }}>Packets</h2>
        <div className="flex gap-3">
          <select value={days} onChange={e => setDays(Number(e.target.value))}
            className="rounded px-3 py-1.5 text-sm"
            style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)', color: 'var(--slate-100)' }}>
            <option value={1}>Today</option>
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
          </select>
          <input type="text" placeholder="Filter ticker..." value={ticker} onChange={e => setTicker(e.target.value)}
            className="rounded px-3 py-1.5 text-sm w-32"
            style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)', color: 'var(--slate-100)' }} />
        </div>
      </div>

      {(!packets || packets.length === 0) ? (
        <EmptyState message="No packets in this period" icon={FileText} />
      ) : (
        <div className="space-y-3">
          {packets.map((p, i) => (
            <div key={p.recommendation_id || i} className="rounded-lg p-4 transition-colors"
              style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-3">
                  <span className="font-medium text-lg">{p.ticker}</span>
                  <span style={{ color: 'var(--slate-300)' }}>{p.company_name}</span>
                  <StatusBadge text={`Score: ${(p.priority_score || 0).toFixed(0)}`} variant={scoreVariant(p.priority_score || 0)} />
                  <StatusBadge text={`Conf: ${p.confidence_score || 0}/10`} variant="neutral" />
                  {p.event_risk_flag && p.event_risk_flag !== 'none' && (
                    <StatusBadge text="Earnings Risk" variant="warning" />
                  )}
                </div>
                <div className="flex items-center gap-3 text-sm">
                  <span style={{ color: 'var(--slate-400)' }}>{(p.created_at || '').slice(0, 10)}</span>
                  {p.shadow_pnl_dollars != null && <PnlText value={p.shadow_pnl_dollars} percent={p.shadow_pnl_pct} />}
                </div>
              </div>
              <div className="grid grid-cols-3 gap-4 text-sm mb-2" style={{ fontFamily: 'var(--font-mono)' }}>
                <div><span style={{ color: 'var(--slate-400)' }}>Entry:</span> {p.entry_zone}</div>
                <div><span style={{ color: 'var(--slate-400)' }}>Stop:</span> {p.stop_level}</div>
                <div><span style={{ color: 'var(--slate-400)' }}>Targets:</span> {p.target_1} / {p.target_2}</div>
              </div>
              <button onClick={() => setExpanded(expanded === i ? null : i)}
                className="text-xs hover:underline" style={{ color: 'var(--teal-400)' }}>
                {expanded === i ? 'Hide analysis' : 'Show analysis'}
              </button>
              {expanded === i && (
                <div className="mt-3 text-sm whitespace-pre-wrap pt-3" style={{ color: 'var(--slate-300)', borderTop: '1px solid var(--slate-600)' }}>
                  {p.thesis_text || 'No analysis available'}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
