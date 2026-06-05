/**
 * StalenessBadge — honesty-primitive (law #4).
 * Takes asOf (ISO string) + maxAge (seconds).
 * fresh  = green, within maxAge
 * stale  = degraded/amber, past maxAge
 * unknown = gray "unknown", when asOf is missing/null — NEVER green
 */

function getAgeSeconds(asOf) {
  if (!asOf) return null
  const d = new Date(asOf)
  if (isNaN(d.getTime())) return null
  return (Date.now() - d.getTime()) / 1000
}

export default function StalenessBadge({ asOf, maxAge = 300 }) {
  const ageSeconds = getAgeSeconds(asOf)

  if (ageSeconds === null) {
    return (
      <span
        data-testid="staleness-badge"
        className="staleness-unknown"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '2px 7px',
          borderRadius: 'var(--radius-sm)',
          fontSize: 10,
          fontWeight: 600,
          fontFamily: 'var(--font-mono)',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          color: 'var(--arcis-text-muted)',
          background: 'rgba(63,63,70,0.2)',
          border: '1px solid var(--arcis-text-muted)',
        }}
      >
        unknown
      </span>
    )
  }

  const isFresh = ageSeconds <= maxAge

  if (isFresh) {
    return (
      <span
        data-testid="staleness-badge"
        className="staleness-fresh staleness-green"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '2px 7px',
          borderRadius: 'var(--radius-sm)',
          fontSize: 10,
          fontWeight: 600,
          fontFamily: 'var(--font-mono)',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          color: 'var(--arcis-success)',
          background: 'rgba(34,197,94,0.1)',
          border: '1px solid rgba(34,197,94,0.3)',
        }}
      >
        {typeof asOf === 'string' ? asOf.slice(0, 16).replace('T', ' ') : String(asOf)}
      </span>
    )
  }

  return (
    <span
      data-testid="staleness-badge"
      className="staleness-stale staleness-degraded"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 7px',
        borderRadius: 'var(--radius-sm)',
        fontSize: 10,
        fontWeight: 600,
        fontFamily: 'var(--font-mono)',
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        color: 'var(--arcis-warning)',
        background: 'rgba(245,158,11,0.1)',
        border: '1px solid rgba(245,158,11,0.3)',
      }}
    >
      stale · {typeof asOf === 'string' ? asOf.slice(0, 16).replace('T', ' ') : String(asOf)}
    </span>
  )
}
