/**
 * PreflightStatusCard — surfaces the most recent preflight_monday.py transcript.
 *
 * Track 1.5 / Round 8.D. Closes S4 (preflight gate UI echo).
 * Reads GET /api/preflight/latest and renders last_run_at, overall_status,
 * and per-item check statuses. Shows empty state when no preflight has run.
 */
import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../../api'

const STATUS_COLOR = {
  green:   'var(--arcis-success)',
  yellow:  'var(--arcis-warning)',
  red:     'var(--arcis-danger)',
  unknown: 'var(--arcis-text-muted)',
}

const STATUS_LABEL = {
  green:   'ALL PASS',
  yellow:  'WARN',
  red:     'FAIL',
  unknown: 'NOT RUN',
}

function _fetchPreflight() {
  return fetchApi('/preflight/latest')
}

function OverallBadge({ status }) {
  const color = STATUS_COLOR[status] || STATUS_COLOR.unknown
  const label = STATUS_LABEL[status] || 'UNKNOWN'
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 'var(--radius-sm)',
        fontSize: 11,
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        color,
        background: `${color}1a`,
        border: `1px solid ${color}33`,
      }}
    >
      {label}
    </span>
  )
}

function ItemRow({ item }) {
  const color = item.status === 'pass' ? 'var(--arcis-success)' : 'var(--arcis-danger)'
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '3px 0',
        fontSize: 12,
      }}
    >
      <span style={{ color, fontWeight: 600, width: 36, flexShrink: 0 }}>
        {item.status === 'pass' ? 'PASS' : 'FAIL'}
      </span>
      <span style={{ color: 'var(--arcis-text-secondary)', fontFamily: 'var(--font-mono)' }}>
        {item.name}
      </span>
    </div>
  )
}

export default function PreflightStatusCard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['preflight-latest'],
    queryFn: _fetchPreflight,
    refetchInterval: 300000,
  })

  if (isLoading) {
    return (
      <div className="arcis-card" style={{ padding: 16 }}>
        <span style={{ color: 'var(--arcis-text-muted)', fontSize: 13 }}>Loading preflight status...</span>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="arcis-card" style={{ padding: 16 }}>
        <span style={{ color: 'var(--arcis-danger)', fontSize: 13 }}>Failed to load preflight status</span>
      </div>
    )
  }

  const isEmpty = data.last_run_at == null

  return (
    <div className="arcis-card" style={{ padding: '14px 16px' }}>
      <div
        style={{
          fontSize: 11,
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          color: 'var(--arcis-text-secondary)',
          fontWeight: 500,
          marginBottom: 8,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}
      >
        <span>Preflight Gate</span>
        <OverallBadge status={data.overall_status} />
      </div>

      {isEmpty ? (
        <div style={{ color: 'var(--arcis-text-muted)', fontSize: 13, padding: '8px 0' }}>
          Preflight has not been run yet today.
        </div>
      ) : (
        <>
          <div style={{ fontSize: 11, color: 'var(--arcis-text-muted)', marginBottom: 8 }}>
            Last run: <span style={{ fontFamily: 'var(--font-mono)' }}>{data.last_run_at}</span>
            {' · '}
            <span style={{ color: 'var(--arcis-success)' }}>{data.n_pass} pass</span>
            {data.n_fail > 0 && (
              <span style={{ color: 'var(--arcis-danger)', marginLeft: 6 }}>{data.n_fail} fail</span>
            )}
          </div>
          {data.items.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {data.items.map((item) => (
                <ItemRow key={item.name} item={item} />
              ))}
            </div>
          )}
          {data.transcript_path && (
            <div style={{ marginTop: 8, fontSize: 10, color: 'var(--arcis-text-muted)' }}>
              Transcript: <span style={{ fontFamily: 'var(--font-mono)' }}>{data.transcript_path}</span>
            </div>
          )}
        </>
      )}
    </div>
  )
}
