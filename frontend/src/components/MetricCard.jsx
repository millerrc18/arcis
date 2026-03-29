export default function MetricCard({ label, value, delta, prefix = '' }) {
  const deltaColor = delta > 0 ? 'text-[var(--bullish)]' : delta < 0 ? 'text-[var(--bearish)]' : ''
  return (
    <div className="rounded-lg p-4 transition-colors" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
      <div className="text-xs uppercase tracking-wide mb-1" style={{ color: 'var(--slate-400)' }}>{label}</div>
      <div className="text-2xl font-medium" style={{ fontFamily: 'var(--font-mono)', color: 'var(--slate-100)' }}>{prefix}{value}</div>
      {delta !== undefined && delta !== null && (
        <div className={`text-sm mt-1 ${deltaColor}`} style={{ fontFamily: 'var(--font-mono)' }}>
          {delta > 0 ? '+' : ''}{typeof delta === 'number' ? delta.toFixed(2) : delta}
        </div>
      )}
    </div>
  )
}
