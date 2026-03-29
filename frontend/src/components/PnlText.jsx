export default function PnlText({ value, percent }) {
  if (value === null || value === undefined) return <span style={{ color: 'var(--slate-400)' }}>--</span>
  const color = value > 0 ? 'var(--bullish)' : value < 0 ? 'var(--bearish)' : 'var(--slate-400)'
  const sign = value > 0 ? '+' : ''
  return (
    <span style={{ fontFamily: 'var(--font-mono)', color }}>
      {sign}${value.toFixed(2)}
      {percent !== undefined && percent !== null && (
        <span className="ml-1 text-sm">({sign}{percent.toFixed(1)}%)</span>
      )}
    </span>
  )
}
