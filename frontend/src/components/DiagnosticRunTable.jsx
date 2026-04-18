import StatusBadge from './StatusBadge'

const STATUS_VARIANT = {
  queued: 'neutral',
  running: 'info',
  completed: 'success',
  failed: 'danger',
}

function parseDecision(summaryJson) {
  if (!summaryJson) return '—'
  try {
    const s = typeof summaryJson === 'string' ? JSON.parse(summaryJson) : summaryJson
    if (s.decision) return s.decision
    if (s.n_total != null) return `N=${s.n_total}`
    return '—'
  } catch {
    return '—'
  }
}

export default function DiagnosticRunTable({
  runs = [],
  onSelect,
  selectedId,
}) {
  if (runs.length === 0) {
    return (
      <p className="text-sm text-gray-500 p-4 bg-gray-50 rounded">
        No diagnostic runs yet. Click a button above to start one.
      </p>
    )
  }
  return (
    <table className="w-full text-sm">
      <thead className="bg-gray-100">
        <tr>
          <th className="text-left p-2">When</th>
          <th className="text-left p-2">Type</th>
          <th className="text-left p-2">Status</th>
          <th className="text-left p-2">Cohort N</th>
          <th className="text-left p-2">Decision / Finding</th>
          <th className="text-left p-2">Triggered by</th>
        </tr>
      </thead>
      <tbody>
        {runs.map(r => (
          <tr
            key={r.run_id}
            onClick={() => onSelect?.(r.run_id)}
            className={`cursor-pointer hover:bg-gray-50 border-t ${
              selectedId === r.run_id ? 'bg-blue-50' : ''
            }`}
          >
            <td className="p-2 text-xs">
              {r.created_at?.slice(0, 19).replace('T', ' ')}
            </td>
            <td className="p-2 capitalize">{r.diagnostic_type}</td>
            <td className="p-2">
              <StatusBadge
                text={r.status}
                variant={STATUS_VARIANT[r.status] || 'neutral'}
              />
            </td>
            <td className="p-2">{r.cohort_n ?? '—'}</td>
            <td className="p-2 font-mono text-xs">
              {parseDecision(r.summary_json)}
            </td>
            <td className="p-2 text-xs text-gray-600">{r.triggered_by}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
