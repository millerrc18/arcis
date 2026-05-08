/**
 * NotificationsHealthPanel — bottom-of-page widget showing last-24h
 * notification health from /api/notifications/health.
 *
 * Sprint 4 T15c. Reads success_rate, fail_count, dedup_hits,
 * oldest_unack_alert. Refreshes every 5 minutes.
 */
import { useQuery } from '@tanstack/react-query'
import { getNotificationsHealth } from '../../api'

function _fetchNotificationsHealth() {
  return getNotificationsHealth()
}

function StatusBadge({ successRate }) {
  const pct = successRate != null ? Math.round(successRate * 100) : null
  let color = 'var(--arcis-text-muted)'
  let label = 'N/A'
  if (pct != null) {
    label = `${pct}%`
    if (pct >= 95) color = 'var(--arcis-success)'
    else if (pct >= 80) color = 'var(--arcis-warning)'
    else color = 'var(--arcis-danger)'
  }
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 'var(--radius-sm)',
        fontSize: 11,
        fontWeight: 600,
        color,
        background: `${color}1a`,
        border: `1px solid ${color}33`,
      }}
    >
      {label}
    </span>
  )
}

function MetricCell({ label, value, color }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '8px 14px',
        minWidth: 80,
      }}
    >
      <div
        style={{
          fontSize: 20,
          fontWeight: 600,
          fontFamily: 'var(--font-mono)',
          color: color || 'var(--arcis-text)',
        }}
      >
        {value != null ? value : '—'}
      </div>
      <div
        style={{
          fontSize: 10,
          textTransform: 'uppercase',
          color: 'var(--arcis-text-muted)',
          marginTop: 2,
          letterSpacing: '0.04em',
        }}
      >
        {label}
      </div>
    </div>
  )
}

export default function NotificationsHealthPanel() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['notifications-health'],
    queryFn: () => _fetchNotificationsHealth(),
    refetchInterval: 300000,
  })

  if (isLoading) {
    return (
      <div className="arcis-card" style={{ padding: 16 }}>
        <span style={{ color: 'var(--arcis-text-muted)', fontSize: 13 }}>
          Loading notifications health...
        </span>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="arcis-card" style={{ padding: 16 }}>
        <span style={{ color: 'var(--arcis-danger)', fontSize: 13 }}>
          Failed to load notifications health
        </span>
      </div>
    )
  }

  const failColor =
    data.fail_count > 0 ? 'var(--arcis-danger)' : 'var(--arcis-success)'
  const dedupColor =
    data.dedup_hits > 0 ? 'var(--arcis-warning)' : 'var(--arcis-text-muted)'

  return (
    <div className="arcis-card" style={{ padding: 16 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
        }}
      >
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            color: 'var(--arcis-text-secondary)',
          }}
        >
          Notifications Health (24h)
        </span>
        <StatusBadge successRate={data.success_rate} />
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <MetricCell
          label="Failures"
          value={data.fail_count}
          color={failColor}
        />
        <MetricCell
          label="Dedup Hits"
          value={data.dedup_hits}
          color={dedupColor}
        />
        {data.oldest_unack_alert && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              padding: '8px 14px',
              fontSize: 11,
              color: 'var(--arcis-warning)',
              fontFamily: 'var(--font-mono)',
            }}
          >
            Oldest unacked: {data.oldest_unack_alert.slice(0, 16).replace('T', ' ')}
          </div>
        )}
      </div>
    </div>
  )
}
