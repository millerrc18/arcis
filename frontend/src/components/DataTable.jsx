import { useState } from 'react'

export default function DataTable({ columns, data, onRowClick }) {
  const [sortKey, setSortKey] = useState(null)
  const [sortAsc, setSortAsc] = useState(true)

  const sorted = [...(data || [])].sort((a, b) => {
    if (!sortKey) return 0
    const av = a[sortKey], bv = b[sortKey]
    if (av == null) return 1
    if (bv == null) return -1
    const cmp = typeof av === 'number' ? av - bv : String(av).localeCompare(String(bv))
    return sortAsc ? cmp : -cmp
  })

  const handleSort = (key) => {
    if (sortKey === key) setSortAsc(!sortAsc)
    else { setSortKey(key); setSortAsc(true) }
  }

  const fmt = (val, type) => {
    if (val === null || val === undefined) return '--'
    switch (type) {
      case 'currency': return `$${Number(val).toFixed(2)}`
      case 'percent': return `${Number(val).toFixed(1)}%`
      case 'number': return Number(val).toFixed(2)
      // #631-19 — Format ISO timestamps as YYYY-MM-DD so the Open Shadow
      // Trades table can show an Opened-date column to disambiguate two
      // simultaneous positions in the same ticker.
      case 'date': {
        const s = String(val)
        return s.length >= 10 ? s.slice(0, 10) : s
      }
      default: return String(val)
    }
  }

  const numTypes = ['currency', 'percent', 'number']

  return (
    <div className="overflow-x-auto">
      <table className="w-full" style={{ fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--arcis-border)' }}>
            {columns.map(col => (
              <th key={col.key}
                  className={`cursor-pointer select-none ${numTypes.includes(col.type) ? 'text-right' : 'text-left'}`}
                  style={{ padding: '6px 8px', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 500, color: 'var(--arcis-text-secondary)' }}
                  onClick={() => handleSort(col.key)}>
                {col.label} {sortKey === col.key ? (sortAsc ? '\u2191' : '\u2193') : ''}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr key={i}
                className={onRowClick ? 'cursor-pointer' : ''}
                style={{ height: 28, borderBottom: '1px solid var(--arcis-border)' }}
                onMouseEnter={(e) => e.currentTarget.style.background = 'var(--arcis-bg-elevated)'}
                onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                onClick={() => onRowClick?.(row)}>
              {columns.map(col => {
                const val = row[col.key]
                const isNum = numTypes.includes(col.type)
                let style = { padding: '4px 8px' }
                if (isNum) {
                  style.fontFamily = 'var(--font-mono)'
                  style.fontVariantNumeric = 'tabular-nums'
                  style.textAlign = 'right'
                }
                if (col.type === 'currency' && val != null) {
                  style.color = val > 0 ? 'var(--arcis-success)' : val < 0 ? 'var(--arcis-danger)' : undefined
                }
                return (
                  <td key={col.key} style={style}>
                    {fmt(val, col.type)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {(!data || data.length === 0) && (
        <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--arcis-text-secondary)', fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>NO DATA</div>
      )}
    </div>
  )
}
