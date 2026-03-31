export default function MetricCard({ label, value, delta, prefix = '' }) {
  const deltaColor = delta > 0 ? 'text-[var(--arcis-success)]' : delta < 0 ? 'text-[var(--arcis-danger)]' : ''
  return (
    <div className="arcis-card transition-colors">
      <div className="text-xs uppercase tracking-wide mb-1" style={{ color: 'var(--arcis-text-secondary)' }}>{label}</div>
      <div className="text-2xl font-medium" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-primary)' }}>{prefix}{value}</div>
      {delta !== undefined && delta !== null && (
        <div className={`text-sm mt-1 ${deltaColor}`} style={{ fontFamily: 'var(--font-mono)' }}>
          {delta > 0 ? '+' : ''}{typeof delta === 'number' ? delta.toFixed(2) : delta}
        </div>
      )}
    </div>
  )
}
