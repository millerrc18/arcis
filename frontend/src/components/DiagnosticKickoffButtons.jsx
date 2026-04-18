import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'

function typeIsActive(runs, type) {
  return runs.some(
    r => r.diagnostic_type === type
      && (r.status === 'queued' || r.status === 'running'),
  )
}

export default function DiagnosticKickoffButtons({ runs = [], onError }) {
  const qc = useQueryClient()
  const regimeActive = typeIsActive(runs, 'regime')
  const forensicActive = typeIsActive(runs, 'forensic')

  const regimeMut = useMutation({
    mutationFn: (opts) => api.triggerRegimeDiagnostic(opts),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['diagnostic-runs'] }),
    onError: (err) => onError?.(err.message || 'Failed to start regime run'),
  })

  const forensicMut = useMutation({
    mutationFn: () => api.triggerForensicAudit(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['diagnostic-runs'] }),
    onError: (err) => onError?.(err.message || 'Failed to start forensic run'),
  })

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div className="border rounded p-4">
        <h3 className="font-medium mb-1">Regime Diagnostic</h3>
        <p className="text-xs text-gray-500 mb-3">
          CONTAMINATED / NULL / PENDING decision based on VIX regression,
          day clustering, sector rotation, entry-time, and holding-period
          analyses. Takes 3&ndash;5 minutes.
        </p>
        <button
          onClick={() => regimeMut.mutate({ exclude_quarantined: false })}
          disabled={regimeActive || regimeMut.isPending}
          className={`w-full py-2 rounded text-sm font-medium ${
            regimeActive || regimeMut.isPending
              ? 'bg-gray-200 text-gray-500 cursor-not-allowed'
              : 'bg-blue-600 text-white hover:bg-blue-700'
          }`}
        >
          {regimeActive ? 'Running…' : 'Run Regime Diagnostic'}
        </button>
      </div>

      <div className="border rounded p-4">
        <h3 className="font-medium mb-1">Forensic Trade Audit</h3>
        <p className="text-xs text-gray-500 mb-3">
          8-question forensic with bootcamp counterfactual. Takes 2&ndash;3
          minutes.
        </p>
        <button
          onClick={() => forensicMut.mutate()}
          disabled={forensicActive || forensicMut.isPending}
          className={`w-full py-2 rounded text-sm font-medium ${
            forensicActive || forensicMut.isPending
              ? 'bg-gray-200 text-gray-500 cursor-not-allowed'
              : 'bg-blue-600 text-white hover:bg-blue-700'
          }`}
        >
          {forensicActive ? 'Running…' : 'Run Forensic Audit'}
        </button>
      </div>
    </div>
  )
}
