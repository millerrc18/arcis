/**
 * Metric — honesty-primitive (law #2).
 * REQUIRES cohort, n, and asOf. If any is missing/undefined,
 * renders an explicit error state instead of a bare number.
 * "A metric without a time window is a slogan."
 */
export default function Metric({ label, value, cohort, n, asOf }) {
  const missing = cohort == null || n == null || asOf == null

  if (missing) {
    return (
      <div
        data-testid="metric-error"
        style={{
          padding: '8px 12px',
          border: '1px solid var(--arcis-danger)',
          borderRadius: 'var(--radius-sm)',
          color: 'var(--arcis-danger)',
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
        }}
      >
        {label ? `${label}: ` : ''}missing required context (cohort/n/asOf)
      </div>
    )
  }

  const asOfDisplay = typeof asOf === 'string' ? asOf.slice(0, 10) : String(asOf)

  return (
    <div
      data-testid="metric-card"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        padding: '8px 12px',
        border: '1px solid var(--arcis-border)',
        borderRadius: 'var(--radius-sm)',
      }}
    >
      <div
        style={{
          fontSize: 11,
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          color: 'var(--arcis-text-secondary)',
          fontWeight: 500,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 600,
          fontFamily: 'var(--font-mono)',
          color: 'var(--arcis-text-primary)',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
      </div>
      <div
        style={{
          fontSize: 10,
          color: 'var(--arcis-text-muted)',
          fontFamily: 'var(--font-mono)',
        }}
      >
        {cohort} · n={n} · {asOfDisplay}
      </div>
    </div>
  )
}
