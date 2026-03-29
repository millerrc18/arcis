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
      default: return String(val)
    }
  }

  const numTypes = ['currency', 'percent', 'number']

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr style={{ borderBottom: '1px solid var(--slate-600)' }}>
            {columns.map(col => (
              <th key={col.key}
                  className={`py-2 px-3 text-xs uppercase tracking-wide cursor-pointer ${numTypes.includes(col.type) ? 'text-right' : 'text-left'}`}
                  style={{ color: 'var(--slate-400)' }}
                  onClick={() => handleSort(col.key)}>
                {col.label} {sortKey === col.key ? (sortAsc ? '\u2191' : '\u2193') : ''}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr key={i}
                className={`transition-colors ${onRowClick ? 'cursor-pointer' : ''}`}
                style={{
                  borderBottom: '1px solid var(--slate-600)',
                  background: i % 2 === 0 ? 'transparent' : 'rgba(30, 41, 59, 0.5)',
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = 'var(--slate-700)'}
                onMouseLeave={(e) => e.currentTarget.style.background = i % 2 === 0 ? 'transparent' : 'rgba(30, 41, 59, 0.5)'}
                onClick={() => onRowClick?.(row)}>
              {columns.map(col => {
                const val = row[col.key]
                const isNum = numTypes.includes(col.type)
                let style = {}
                if (col.type === 'currency' && val != null) {
                  style.color = val > 0 ? 'var(--bullish)' : val < 0 ? 'var(--bearish)' : undefined
                }
                return (
                  <td key={col.key}
                      className={`py-2 px-3 ${isNum ? 'text-right' : ''}`}
                      style={{ fontFamily: isNum ? 'var(--font-mono)' : undefined, ...style }}>
                    {fmt(val, col.type)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {(!data || data.length === 0) && (
        <div className="text-center py-8" style={{ color: 'var(--slate-400)' }}>No data available</div>
      )}
    </div>
  )
}
