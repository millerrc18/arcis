import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { IS_CLOUD } from '../config'
import { api } from '../api'
import useWebSocket from '../hooks/useWebSocket'
import { TrendingUp, TrendingDown, CheckCircle, XCircle, Brain, AlertTriangle, Shield, Database, Settings } from 'lucide-react'

const EVENT_STYLE = {
  trade_opened: { icon: TrendingUp, color: 'var(--arcis-accent)' },
  trade_closed_win: { icon: CheckCircle, color: 'var(--arcis-success)' },
  trade_closed_loss: { icon: XCircle, color: 'var(--arcis-danger)' },
  trade_closed: { icon: CheckCircle, color: 'var(--arcis-success)' },
  training_complete: { icon: Brain, color: 'var(--arcis-success)' },
  action_complete: { icon: CheckCircle, color: 'var(--arcis-success)' },
  scan_complete: { icon: Database, color: 'var(--arcis-info)' },
  scan_started: { icon: Database, color: 'var(--arcis-info)' },
  overnight_task: { icon: Database, color: 'var(--arcis-info)' },
  pre_market_refresh: { icon: Database, color: 'var(--arcis-info)' },
  training_started: { icon: Brain, color: 'var(--arcis-warning)' },
  training_collection: { icon: Brain, color: 'var(--arcis-warning)' },
  action_started: { icon: Settings, color: 'var(--arcis-warning)' },
  order_submitted: { icon: TrendingUp, color: 'var(--arcis-warning)' },
  order_filled: { icon: TrendingUp, color: 'var(--arcis-warning)' },
  action_error: { icon: AlertTriangle, color: 'var(--arcis-danger)' },
  error: { icon: AlertTriangle, color: 'var(--arcis-danger)' },
  risk_alert: { icon: Shield, color: 'var(--arcis-danger)' },
  llm_generation: { icon: Brain, color: 'var(--arcis-info)' },
  data_collection: { icon: Database, color: 'var(--arcis-text-secondary)' },
  system: { icon: Settings, color: 'var(--arcis-info)' },
}

function getEventStyle(evt) {
  if (evt.type === 'trade_closed') {
    return (evt.data?.pnl_dollars || 0) >= 0
      ? EVENT_STYLE.trade_closed_win
      : EVENT_STYLE.trade_closed_loss
  }
  return EVENT_STYLE[evt.type] || EVENT_STYLE[evt.category] || { icon: Settings, color: 'var(--arcis-text-secondary)' }
}

function formatEvent(evt) {
  const d = evt.data || {}
  switch (evt.type || evt.event) {
    case 'scan_started':
      return 'Market scan started'
    case 'scan_complete':
      return `Scanned ${d.tickers_scanned || '?'} tickers, ${d.packets || 0} packets generated`
    case 'trade_opened':
      return `Opened ${d.side || 'BUY'} ${d.ticker || '?'}${d.score ? ` (score: ${d.score})` : ''}`
    case 'trade_closed': {
      const pnl = d.pnl_pct != null ? `${d.pnl_pct >= 0 ? '+' : ''}${d.pnl_pct.toFixed(1)}%` : ''
      const dollars = d.pnl_dollars != null ? ` ($${d.pnl_dollars >= 0 ? '+' : ''}${d.pnl_dollars.toFixed(2)})` : ''
      return `Closed ${d.ticker || '?'} ${pnl}${dollars}`
    }
    case 'training_started':
      return `Training pipeline started${d.examples ? ` (${d.examples} examples)` : ''}`
    case 'training_complete':
      return `Training complete: ${d.model || 'new model'}${d.loss ? ` (loss: ${d.loss.toFixed(4)})` : ''}`
    case 'training_collection':
      return `Collected ${d.examples_collected || 0} training examples`
    case 'overnight_task': {
      if (d.task) {
        const parts = [`${d.task.replace(/_/g, ' ')}: ${d.status || 'complete'}`]
        if (d.articles_cached) parts.push(`(${d.articles_cached} articles)`)
        if (d.tickers_enriched) parts.push(`(${d.tickers_enriched} tickers)`)
        return parts.join(' ')
      }
      return evt.detail ? String(evt.detail).slice(0, 120) : 'Overnight task completed'
    }
    case 'action_started':
      return `Action started: ${d.action || '?'}`
    case 'action_complete':
      return `Action complete: ${d.action || '?'}`
    case 'action_error':
      return `Action failed: ${d.action || '?'} — ${d.error || 'unknown error'}`
    case 'order_submitted':
      return `Order submitted: ${d.ticker || '?'} ${d.order_type || ''}`
    case 'order_filled':
      return `Order filled: ${d.ticker || '?'}${d.price ? ` @ $${d.price}` : ''}`
    default: {
      const detail = evt.detail || d.detail || ''
      if (detail && !detail.startsWith('{')) return detail.slice(0, 120)
      const eventName = (evt.type || evt.event || 'system').replace(/_/g, ' ')
      const summary = d.detail || d.message || d.status || ''
      return summary ? `${eventName}: ${String(summary).slice(0, 80)}` : eventName
    }
  }
}

function normalizeActivityLogEntry(entry) {
  let parsed = {}
  try {
    if (typeof entry.detail === 'string' && entry.detail.startsWith('{')) {
      parsed = JSON.parse(entry.detail)
    }
  } catch { /* detail is plain text */ }
  return {
    type: entry.event_type || parsed.event || 'system',
    category: parsed.category || entry.event_type || 'system',
    timestamp: entry.created_at || new Date().toISOString(),
    data: parsed,
    detail: typeof entry.detail === 'string' ? entry.detail : '',
    event: entry.event_type || parsed.event,
  }
}

export default function ActivityFeed() {
  const { events: wsEvents, connected, clearEvents } = useWebSocket()
  const scrollRef = useRef(null)

  // Cloud mode: poll activity_log API
  const { data: polledEvents } = useQuery({
    queryKey: ['activity-feed'],
    queryFn: () => api.getActivityFeed(30),
    refetchInterval: 60000,
    enabled: IS_CLOUD,
  })

  // Merge: prefer WebSocket events (local), fall back to polled (cloud)
  const events = wsEvents.length > 0
    ? wsEvents
    : (polledEvents || []).map(normalizeActivityLogEntry)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0
    }
  }, [events.length])

  return (
    <div className="rounded-lg p-4" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm uppercase tracking-wide" style={{ color: 'var(--arcis-text-secondary)' }}>Live Activity</h3>
        <div className="flex items-center gap-3">
          {wsEvents.length > 0 && (
            <button
              onClick={clearEvents}
              className="text-xs hover:opacity-80"
              style={{ color: 'var(--arcis-text-secondary)' }}
            >
              Clear
            </button>
          )}
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full" style={{ background: connected ? 'var(--arcis-success)' : (IS_CLOUD || events.length > 0) ? 'var(--arcis-info)' : 'var(--arcis-text-muted)' }} />
            <span className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>
              {connected ? 'Live' : IS_CLOUD ? 'Polling' : events.length > 0 ? 'Polling' : 'Idle'}
            </span>
          </div>
        </div>
      </div>
      <div ref={scrollRef} className="space-y-1 max-h-64 overflow-y-auto text-sm" style={{ fontFamily: 'var(--font-mono)' }}>
        {events.length === 0 && (
          <p className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Waiting for events...</p>
        )}
        {events.map((evt, i) => {
          const style = getEventStyle(evt)
          const Icon = style.icon
          return (
            <div key={i} className="flex gap-2 items-start">
              <span className="text-xs shrink-0 pt-0.5" style={{ color: 'var(--arcis-text-secondary)' }}>
                {new Date(evt.timestamp || evt.created_at).toLocaleTimeString()}
              </span>
              <Icon size={12} className="shrink-0 mt-1" style={{ color: style.color }} />
              <span style={{ color: 'var(--arcis-text-secondary)' }}>{formatEvent(evt)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
