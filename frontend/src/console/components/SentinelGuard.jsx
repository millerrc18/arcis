/**
 * SentinelGuard — honesty-primitive (law #3).
 * Catches sentinel values: 999, NaN, -1, Infinity, null, undefined
 * and renders an explicit labeled "no data" state.
 * A true 0 MUST render as a value and be visually DISTINCT from no-data.
 */

const SENTINELS = new Set([999, -1])

function isSentinel(value) {
  if (value === null || value === undefined) return true
  if (typeof value === 'number') {
    if (Number.isNaN(value)) return true
    if (!Number.isFinite(value)) return true
    if (SENTINELS.has(value)) return true
  }
  return false
}

export default function SentinelGuard({ value, label }) {
  if (isSentinel(value)) {
    return (
      <span
        data-testid="sentinel-no-data"
        style={{
          color: 'var(--arcis-text-muted)',
          fontFamily: 'var(--font-mono)',
          fontSize: 13,
          fontStyle: 'italic',
        }}
      >
        {label ? `${label}: ` : ''}no data
      </span>
    )
  }

  return (
    <span
      data-testid="sentinel-value"
      style={{
        color: 'var(--arcis-text-primary)',
        fontFamily: 'var(--font-mono)',
        fontSize: 13,
        fontVariantNumeric: 'tabular-nums',
      }}
    >
      {String(value)}
    </span>
  )
}
