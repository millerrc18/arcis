export default function PnlText({ value, percent }) {
  if (value === null || value === undefined) return <span style={{ color: 'var(--arcis-text-secondary)', fontFamily: 'var(--font-mono)' }}>--</span>
  const color = value > 0 ? 'var(--arcis-success)' : value < 0 ? 'var(--arcis-danger)' : 'var(--arcis-text-secondary)'
  const sign = value > 0 ? '+' : ''
  return (
    <span style={{ fontFamily: 'var(--font-mono)', color, fontVariantNumeric: 'tabular-nums' }}>
      {sign}${value.toFixed(2)}
      {percent !== undefined && percent !== null && (
        <span style={{ marginLeft: 4, fontSize: '0.85em' }}>({sign}{percent.toFixed(1)}%)</span>
      )}
    </span>
  )
}
