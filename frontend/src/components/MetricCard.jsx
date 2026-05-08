/* Bloomberg MetricCard — tight padding, uppercase label, mono value */
function _formatValue(prefix, value, suffix) {
  // Move a leading numeric sign before the prefix so a negative dollar amount renders
  // as "-$6.55" rather than "$-6.55" (T18 sibling-fix). Guard with /^[-+]\d/ so non-numeric
  // leading-dash values like "--" pass through unchanged.
  if (typeof value === 'string' && prefix) {
    const m = value.match(/^([-+])(\d.*)$/)
    if (m) return `${m[1]}${prefix}${m[2]}${suffix}`
  }
  return `${prefix}${value}${suffix}`
}

export default function MetricCard({ label, value, delta, prefix = '', suffix = '' }) {
  const deltaColor = delta > 0 ? 'var(--arcis-success)' : delta < 0 ? 'var(--arcis-danger)' : 'var(--arcis-text-secondary)'
  return (
    <div className="arcis-card" style={{ padding: '10px 12px' }}>
      <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 500, marginBottom: 4, color: 'var(--arcis-text-secondary)' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 500, fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-primary)', fontVariantNumeric: 'tabular-nums' }}>
        {_formatValue(prefix, value, suffix)}
      </div>
      {delta !== undefined && delta !== null && (
        <div style={{ fontSize: 12, marginTop: 2, fontFamily: 'var(--font-mono)', color: deltaColor, fontVariantNumeric: 'tabular-nums' }}>
          {delta > 0 ? '+' : ''}{typeof delta === 'number' ? delta.toFixed(2) : delta}
        </div>
      )}
    </div>
  )
}
