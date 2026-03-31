export default function PnlText({ value, percent }) {
  if (value === null || value === undefined) return <span style={{ color: 'var(--arcis-text-secondary)' }}>--</span>
  const color = value > 0 ? 'var(--arcis-success)' : value < 0 ? 'var(--arcis-danger)' : 'var(--arcis-text-secondary)'
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
