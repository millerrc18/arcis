import { useQuery } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from '../api'

export default function DiagnosticRunDetail({ runId }) {
  const { data: run } = useQuery({
    queryKey: ['diagnostic-run', runId],
    queryFn: () => api.getDiagnosticRun(runId),
    enabled: !!runId,
  })

  const { data: report, isLoading: reportLoading } = useQuery({
    queryKey: ['diagnostic-run-report', runId],
    queryFn: () => api.getDiagnosticRunReport(runId),
    enabled: !!runId && run?.status === 'completed',
    staleTime: 5 * 60 * 1000,
  })

  const { data: plots } = useQuery({
    queryKey: ['diagnostic-run-plots', runId],
    queryFn: () => api.getDiagnosticRunPlots(runId),
    enabled: !!runId && run?.status === 'completed',
    staleTime: 5 * 60 * 1000,
  })

  if (!runId) return null
  if (!run) return <p className="text-sm text-gray-500">Loading…</p>

  if (run.status === 'queued') {
    return (
      <div className="p-4 bg-yellow-50 rounded">
        <p className="text-sm">Queued — waiting for local machine to pick up.</p>
      </div>
    )
  }
  if (run.status === 'running') {
    return (
      <div className="p-4 bg-blue-50 rounded">
        <p className="text-sm">
          Running — started {run.started_at?.slice(11, 19)}.
          Refreshing every 5s.
        </p>
      </div>
    )
  }
  if (run.status === 'failed') {
    return (
      <div className="p-4 bg-red-50 rounded">
        <p className="text-sm font-medium text-red-700 mb-1">Failed</p>
        <pre className="text-xs text-red-800 whitespace-pre-wrap">
          {run.stderr_tail || '(no stderr captured)'}
        </pre>
      </div>
    )
  }

  return (
    <div className="bg-white">
      {reportLoading && <p className="text-sm">Loading report…</p>}
      {report?.markdown && (
        <div className="prose prose-sm max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {report.markdown}
          </ReactMarkdown>
        </div>
      )}
      {plots?.plots && plots.plots.length > 0 && (
        <section className="mt-6">
          <h3 className="font-medium mb-2">Plots</h3>
          <div className="space-y-4">
            {plots.plots.map(p => (
              <figure key={p.filename} className="border rounded p-2">
                <img
                  src={`data:image/png;base64,${p.content_b64}`}
                  alt={p.filename}
                  className="max-w-full"
                />
                <figcaption className="text-xs text-gray-500 mt-1">
                  {p.filename}
                </figcaption>
              </figure>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
