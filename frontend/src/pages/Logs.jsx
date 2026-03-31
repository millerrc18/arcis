import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import StatusBadge from '../components/StatusBadge'

const LEVEL_COLORS = {
  DEBUG: 'var(--slate-400)',
  INFO: 'var(--teal-400)',
  WARNING: 'var(--amber-400)',
  ERROR: 'var(--red-400)',
  CRITICAL: 'var(--red-500)',
}

const LEVEL_VARIANTS = {
  DEBUG: 'neutral',
  INFO: 'success',
  WARNING: 'warning',
  ERROR: 'error',
  CRITICAL: 'error',
}

export default function Logs() {
  const [levelFilter, setLevelFilter] = useState('INFO')
  const [sourceFilter, setSourceFilter] = useState('')

  const { data: logData, isLoading } = useQuery({
    queryKey: ['logs', levelFilter, sourceFilter],
    queryFn: () => api.getRecentLogs({
      level: levelFilter,
      limit: 200,
      ...(sourceFilter ? { source: sourceFilter } : {}),
    }),
    refetchInterval: 30000,
  })

  const { data: cmdData } = useQuery({
    queryKey: ['commands-recent'],
    queryFn: () => api.getRecentCommands(20),
    refetchInterval: 15000,
  })

  if (isLoading) return <LoadingSpinner />

  const logs = logData?.logs || []
  const commands = cmdData?.commands || []

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-medium" style={{ color: 'var(--slate-100)' }}>Logs & Commands</h2>

      {/* Command History */}
      {commands.length > 0 && (
        <div className="rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
          <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--slate-400)' }}>Recent Commands</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ color: 'var(--slate-400)' }}>
                  <th className="text-left py-1 pr-3">Time</th>
                  <th className="text-left py-1 pr-3">Command</th>
                  <th className="text-left py-1 pr-3">Type</th>
                  <th className="text-left py-1 pr-3">Status</th>
                  <th className="text-right py-1">Duration</th>
                </tr>
              </thead>
              <tbody>
                {commands.map((cmd, i) => (
                  <tr key={i} style={{ borderTop: '1px solid var(--slate-600)' }}>
                    <td className="py-1.5 pr-3 whitespace-nowrap" style={{ color: 'var(--slate-400)', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                      {cmd.created_at?.slice(11, 19) || '--'}
                    </td>
                    <td className="py-1.5 pr-3" style={{ color: 'var(--slate-200)' }}>
                      {cmd.command_name}
                    </td>
                    <td className="py-1.5 pr-3" style={{ color: 'var(--slate-400)' }}>
                      {cmd.command_type}
                    </td>
                    <td className="py-1.5 pr-3">
                      <StatusBadge
                        text={cmd.result_status || cmd.status}
                        variant={
                          (cmd.result_status || cmd.status) === 'success' ? 'success' :
                          (cmd.result_status || cmd.status) === 'pending' ? 'warning' :
                          (cmd.result_status || cmd.status) === 'claimed' ? 'warning' :
                          (cmd.result_status || cmd.status) === 'error' ? 'error' : 'neutral'
                        }
                      />
                    </td>
                    <td className="py-1.5 text-right" style={{ color: 'var(--slate-400)', fontFamily: 'var(--font-mono)' }}>
                      {cmd.execution_ms ? `${cmd.execution_ms}ms` : '--'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Log Filters */}
      <div className="flex items-center gap-3">
        <div className="flex gap-1">
          {['ALL', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((level) => (
            <button
              key={level}
              onClick={() => setLevelFilter(level)}
              className="px-2.5 py-1 text-xs rounded transition-colors"
              style={{
                background: levelFilter === level ? 'var(--teal-500)' : 'var(--slate-700)',
                color: levelFilter === level ? 'white' : 'var(--slate-400)',
                border: '1px solid ' + (levelFilter === level ? 'var(--teal-500)' : 'var(--slate-600)'),
              }}
            >
              {level}
            </button>
          ))}
        </div>
        <input
          type="text"
          placeholder="Filter by source..."
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
          className="text-sm rounded px-2 py-1"
          style={{ background: 'var(--slate-800)', border: '1px solid var(--slate-600)', color: 'var(--slate-100)' }}
        />
        <span className="text-xs" style={{ color: 'var(--slate-500)' }}>
          {logs.length} entries (auto-refresh 30s)
        </span>
      </div>

      {/* Log Table */}
      <div className="rounded-lg overflow-hidden" style={{ border: '1px solid var(--slate-600)' }}>
        <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0" style={{ background: 'var(--slate-700)' }}>
              <tr style={{ color: 'var(--slate-400)' }}>
                <th className="text-left py-2 px-3">Time</th>
                <th className="text-left py-2 px-3">Level</th>
                <th className="text-left py-2 px-3">Source</th>
                <th className="text-left py-2 px-3">Message</th>
              </tr>
            </thead>
            <tbody>
              {logs.length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-8 text-center" style={{ color: 'var(--slate-500)' }}>
                    No log entries found
                  </td>
                </tr>
              ) : (
                logs.map((log, i) => (
                  <tr key={i} style={{ background: i % 2 === 0 ? 'var(--slate-800)' : 'transparent' }}>
                    <td className="py-1.5 px-3 whitespace-nowrap" style={{ color: 'var(--slate-400)', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                      {log.created_at?.slice(0, 19).replace('T', ' ') || '--'}
                    </td>
                    <td className="py-1.5 px-3">
                      <StatusBadge text={log.log_level} variant={LEVEL_VARIANTS[log.log_level] || 'neutral'} />
                    </td>
                    <td className="py-1.5 px-3" style={{ color: 'var(--slate-300)', fontFamily: 'var(--font-mono)' }}>
                      {log.source}
                    </td>
                    <td className="py-1.5 px-3" style={{ color: 'var(--slate-200)' }}>
                      {log.message}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
