import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import DiagnosticKickoffButtons from '../components/DiagnosticKickoffButtons'
import DiagnosticRunTable from '../components/DiagnosticRunTable'
import DiagnosticRunDetail from '../components/DiagnosticRunDetail'

function anyActive(runs) {
  return runs.some(r => r.status === 'queued' || r.status === 'running')
}

export default function Diagnostics() {
  const [selectedId, setSelectedId] = useState(null)
  const [errorMsg, setErrorMsg] = useState(null)

  const { data, isLoading } = useQuery({
    queryKey: ['diagnostic-runs'],
    queryFn: () => api.getDiagnosticRuns({ limit: 20 }),
    refetchInterval: (query) => {
      const runs = query?.state?.data?.runs || []
      return anyActive(runs) ? 5000 : 30000
    },
  })
  const runs = data?.runs || []

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-1">Diagnostics</h1>
      <p className="text-sm mb-6" style={{ color: 'var(--arcis-text-muted)' }}>
        Kick off regime and forensic runs against the current closed-trade
        cohort. Runs persist in <code>diagnostic_runs</code>; reports and
        plots render inline below.
      </p>

      {errorMsg && (
        <div className="mb-4 p-3 rounded text-sm flex justify-between"
          style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', color: 'var(--arcis-danger)' }}>
          <span>{errorMsg}</span>
          <button
            onClick={() => setErrorMsg(null)}
            style={{ color: 'var(--arcis-danger)' }}
          >
            ×
          </button>
        </div>
      )}

      <section className="mb-8">
        <h2 className="text-lg font-medium mb-2">Start a run</h2>
        <DiagnosticKickoffButtons runs={runs} onError={setErrorMsg} />
      </section>

      <section className="mb-8">
        <h2 className="text-lg font-medium mb-2">Recent runs</h2>
        {isLoading ? (
          <p className="text-sm" style={{ color: 'var(--arcis-text-muted)' }}>Loading…</p>
        ) : (
          <DiagnosticRunTable
            runs={runs}
            onSelect={setSelectedId}
            selectedId={selectedId}
          />
        )}
      </section>

      {selectedId && (
        <section className="mb-8 border-l-4 border-blue-500 pl-4">
          <div className="flex justify-between items-center mb-2">
            <h2 className="text-lg font-medium">Run detail</h2>
            <button
              onClick={() => setSelectedId(null)}
              className="text-xs"
            style={{ color: 'var(--arcis-text-secondary)' }}
            >
              Close
            </button>
          </div>
          <DiagnosticRunDetail runId={selectedId} />
        </section>
      )}
    </div>
  )
}
