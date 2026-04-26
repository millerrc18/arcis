/**
 * BrokerExceptionsPanel — surfaces broker_exceptions table to the operator.
 *
 * Track 1.5 / Round 8.C. Closes audit finding G1.
 * Color treatment:
 *   Red border  — outcome='alert_qty_mismatch' (severe CVS-style)
 *   Amber border — recoverable=false (non-severe but non-recoverable)
 *   Default      — all other rows
 */
import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../../api'

function _fetchBrokerExceptions() {
  return Promise.all([
    fetchApi('/broker-exceptions/summary'),
    fetchApi('/broker-exceptions/recent?limit=50&since_hours=24'),
  ]).then(([summary, recent]) => ({ summary, recent }))
}

function _rowBorderColor(row) {
  if (row.outcome === 'alert_qty_mismatch') return 'var(--arcis-danger)'
  if (row.recoverable === 0 || row.recoverable === false) return 'var(--arcis-warning)'
  return 'var(--arcis-border)'
}

function SummaryCards({ summary }) {
  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
      <div className="arcis-card" style={{ padding: '10px 14px', minWidth: 100 }}>
        <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--arcis-text-muted)' }}>24h Total</div>
        <div style={{ fontSize: 22, fontWeight: 600, fontFamily: 'var(--font-mono)',
                      color: summary.total_24h > 0 ? 'var(--arcis-warning)' : 'var(--arcis-success)' }}>
          {summary.total_24h}
        </div>
      </div>
      <div className="arcis-card" style={{ padding: '10px 14px', minWidth: 100 }}>
        <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--arcis-text-muted)' }}>7d Total</div>
        <div style={{ fontSize: 22, fontWeight: 600, fontFamily: 'var(--font-mono)',
                      color: 'var(--arcis-text)' }}>
          {summary.total_7d}
        </div>
      </div>
      <div className="arcis-card" style={{ padding: '10px 14px', minWidth: 120 }}>
        <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--arcis-text-muted)' }}>Qty Mismatch</div>
        <div style={{ fontSize: 22, fontWeight: 600, fontFamily: 'var(--font-mono)',
                      color: summary.alert_qty_mismatch_count > 0 ? 'var(--arcis-danger)' : 'var(--arcis-success)' }}>
          {summary.alert_qty_mismatch_count}
        </div>
      </div>
      {Object.keys(summary.by_broker).length > 0 && (
        <div className="arcis-card" style={{ padding: '10px 14px' }}>
          <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--arcis-text-muted)', marginBottom: 4 }}>By Broker</div>
          {Object.entries(summary.by_broker).map(([broker, count]) => (
            <div key={broker} style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-secondary)' }}>
              {broker}: {count}
            </div>
          ))}
        </div>
      )}
      {Object.keys(summary.by_operation).length > 0 && (
        <div className="arcis-card" style={{ padding: '10px 14px' }}>
          <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--arcis-text-muted)', marginBottom: 4 }}>By Operation</div>
          {Object.entries(summary.by_operation).map(([op, count]) => (
            <div key={op} style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-secondary)' }}>
              {op}: {count}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ExceptionRow({ row }) {
  const borderColor = _rowBorderColor(row)
  const msg = row.exception_message || ''
  const msgDisplay = msg.length > 80 ? msg.slice(0, 80) + '…' : msg
  const ts = row.timestamp ? row.timestamp.replace('T', ' ').slice(0, 19) : ''

  return (
    <div
      title={msg}
      data-outcome={row.outcome}
      style={{
        padding: '8px 10px',
        borderRadius: 'var(--radius-sm)',
        border: `1px solid ${borderColor}`,
        display: 'grid',
        gridTemplateColumns: '140px 70px 100px 80px 1fr',
        gap: 8,
        fontSize: 12,
        alignItems: 'center',
      }}
    >
      <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-muted)' }}>{ts}</span>
      <span style={{ fontWeight: 600 }}>{row.ticker}</span>
      <span style={{ color: 'var(--arcis-text-secondary)' }}>{row.operation}</span>
      <span style={{ color: 'var(--arcis-text-secondary)' }}>{row.broker}</span>
      <span style={{ color: 'var(--arcis-text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        [{row.exception_class}] {msgDisplay}
      </span>
    </div>
  )
}

export default function BrokerExceptionsPanel() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['broker-exceptions'],
    queryFn: _fetchBrokerExceptions,
    refetchInterval: 60000,
  })

  if (isLoading) {
    return (
      <div className="arcis-card" style={{ padding: 16 }}>
        <span style={{ color: 'var(--arcis-text-muted)', fontSize: 13 }}>Loading broker exceptions...</span>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="arcis-card" style={{ padding: 16 }}>
        <span style={{ color: 'var(--arcis-danger)', fontSize: 13 }}>Failed to load broker exceptions</span>
      </div>
    )
  }

  const { summary, recent } = data
  const rows = recent?.rows || []

  return (
    <div className="arcis-card" style={{ padding: '14px 16px' }}>
      <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em',
                    color: 'var(--arcis-text-secondary)', fontWeight: 500, marginBottom: 10 }}>
        Broker Exceptions
      </div>
      {summary && <SummaryCards summary={summary} />}
      {rows.length === 0 ? (
        <div style={{ color: 'var(--arcis-success)', fontSize: 13, padding: '8px 0' }}>
          No broker exceptions in last 24h. ✓
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 320, overflowY: 'auto' }}>
          {rows.map(row => (
            <ExceptionRow key={row.id} row={row} />
          ))}
        </div>
      )}
    </div>
  )
}
