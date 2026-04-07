import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import StatusBadge from '../components/StatusBadge'
import { ChevronDown, ChevronRight, Terminal, Play } from 'lucide-react'

const LEVEL_COLORS = {
  CRITICAL: { bg: 'rgba(239, 68, 68, 0.2)', color: 'var(--arcis-danger)', border: 'rgba(239, 68, 68, 0.4)' },
  ERROR: { color: 'var(--arcis-danger)' },
  WARNING: { color: 'var(--arcis-warning)' },
  INFO: { color: 'var(--arcis-text-secondary)' },
  DEBUG: { color: 'var(--arcis-text-muted)' },
}

const LEVEL_VARIANTS = {
  DEBUG: 'neutral',
  INFO: 'neutral',
  WARNING: 'warning',
  ERROR: 'error',
  CRITICAL: 'error',
}

const QUICK_COMMANDS = [
  { name: 'scan', label: 'Scan', type: 'action' },
  { name: 'council', label: 'Council', type: 'action' },
  { name: 'collect-data', label: 'Collect Data', type: 'action' },
  { name: 'validate-system', label: 'Validate', type: 'action' },
]

function ExpandableLogRow({ log, rowIndex }) {
  const [expanded, setExpanded] = useState(false)
  const hasDetails = log.details_json && log.details_json !== '{}'
  const isCritical = log.log_level === 'CRITICAL'

  let parsedDetails = null
  if (expanded && hasDetails) {
    try { parsedDetails = typeof log.details_json === 'string' ? JSON.parse(log.details_json) : log.details_json } catch { /* ignore */ }
  }

  return (
    <>
      <tr
        className={hasDetails ? 'cursor-pointer' : ''}
        onClick={() => hasDetails && setExpanded(!expanded)}
        style={{
          background: isCritical ? LEVEL_COLORS.CRITICAL.bg
            : rowIndex % 2 === 0 ? 'transparent' : 'var(--arcis-bg-elevated)',
          borderBottom: isCritical ? `1px solid ${LEVEL_COLORS.CRITICAL.border}` : undefined,
        }}
      >
        <td className="py-1.5 px-3 w-6">
          {hasDetails && (
            expanded
              ? <ChevronDown size={12} style={{ color: 'var(--arcis-text-muted)' }} />
              : <ChevronRight size={12} style={{ color: 'var(--arcis-text-muted)' }} />
          )}
        </td>
        <td className="py-1.5 px-3 whitespace-nowrap" style={{ color: 'var(--arcis-text-muted)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', fontSize: '11px' }}>
          {log.created_at?.slice(0, 19).replace('T', ' ') || '--'}
        </td>
        <td className="py-1.5 px-3">
          <StatusBadge text={log.log_level} variant={LEVEL_VARIANTS[log.log_level] || 'neutral'} />
        </td>
        <td className="py-1.5 px-3 hidden md:table-cell" style={{ color: 'var(--arcis-text-secondary)', fontFamily: 'var(--font-mono)' }}>
          {log.source}
        </td>
        <td className="py-1.5 px-3" style={{ color: LEVEL_COLORS[log.log_level]?.color || 'var(--arcis-text-primary)' }}>
          {log.message}
        </td>
      </tr>
      {expanded && parsedDetails && (
        <tr>
          <td colSpan={5} className="px-6 py-3">
            <pre className="text-xs p-3 overflow-x-auto" style={{ borderRadius: 'var(--radius-sm)',
              background: 'var(--arcis-bg-primary)',
              border: '1px solid var(--arcis-border)',
              fontFamily: 'var(--font-mono)',
              color: 'var(--arcis-text-secondary)',
            }}>
              {JSON.stringify(parsedDetails, null, 2)}
            </pre>
          </td>
        </tr>
      )}
    </>
  )
}

export default function Logs() {
  const [levelFilter, setLevelFilter] = useState('INFO')
  const [sourceFilter, setSourceFilter] = useState('')
  const [showCmdDropdown, setShowCmdDropdown] = useState(false)

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
    refetchInterval: 10000,
  })

  const submitCmd = useMutation({
    mutationFn: (cmd) => api.submitCommand({ command_type: cmd.type, command_name: cmd.name }),
  })

  if (isLoading) return <LoadingSpinner />

  const logs = logData?.logs || []
  const commands = cmdData?.commands || []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium uppercase" style={{ color: 'var(--arcis-text-primary)', letterSpacing: '0.06em' }}>Logs & Commands</h2>
        {/* Quick command dropdown */}
        <div className="relative">
          <button
            onClick={() => setShowCmdDropdown(!showCmdDropdown)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm"
            style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-primary)' }}
          >
            <Play size={14} />
            Run Command
          </button>
          {showCmdDropdown && (
            <div className="absolute right-0 top-full mt-1 z-20 py-1 min-w-[160px]"
              style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
              {QUICK_COMMANDS.map(cmd => (
                <button
                  key={cmd.name}
                  onClick={() => { submitCmd.mutate(cmd); setShowCmdDropdown(false) }}
                  className="w-full text-left px-4 py-2 text-sm hover:opacity-80 flex items-center gap-2"
                  style={{ color: 'var(--arcis-text-primary)' }}
                >
                  <Terminal size={13} style={{ color: 'var(--arcis-text-muted)' }} />
                  {cmd.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Command History */}
      <div className="p-4" style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
        <h3 className="text-sm uppercase mb-3" style={{ color: 'var(--arcis-text-secondary)', letterSpacing: '0.06em' }}>
          Recent Commands
          <span className="ml-2 text-xs normal-case" style={{ color: 'var(--arcis-text-muted)' }}>(auto-refresh 10s)</span>
        </h3>
        {commands.length === 0 ? (
          <div className="text-sm py-4 text-center" style={{ color: 'var(--arcis-text-muted)' }}>
            No commands recorded yet \u2014 use "Run Command" above or the dashboard to submit commands
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ color: 'var(--arcis-text-secondary)', letterSpacing: '0.06em' }}>
                  <th className="text-left py-1 pr-3 text-xs uppercase" style={{ fontSize: '10px' }}>Time</th>
                  <th className="text-left py-1 pr-3 text-xs uppercase" style={{ fontSize: '10px' }}>Command</th>
                  <th className="text-left py-1 pr-3 text-xs uppercase hidden md:table-cell" style={{ fontSize: '10px' }}>Type</th>
                  <th className="text-left py-1 pr-3 text-xs uppercase" style={{ fontSize: '10px' }}>Status</th>
                  <th className="text-right py-1 text-xs uppercase hidden md:table-cell" style={{ fontSize: '10px' }}>Duration</th>
                </tr>
              </thead>
              <tbody>
                {commands.map((cmd, i) => (
                  <tr key={cmd.command_id || i} style={{
                    borderTop: '1px solid var(--arcis-border)',
                    background: i % 2 === 0 ? 'transparent' : 'var(--arcis-bg-elevated)',
                  }}>
                    <td className="py-1.5 pr-3 whitespace-nowrap" style={{ color: 'var(--arcis-text-muted)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', fontSize: '11px' }}>
                      {cmd.created_at?.slice(11, 19) || '--'}
                    </td>
                    <td className="py-1.5 pr-3" style={{ color: 'var(--arcis-text-primary)' }}>
                      {cmd.command_name}
                    </td>
                    <td className="py-1.5 pr-3 hidden md:table-cell" style={{ color: 'var(--arcis-text-secondary)' }}>
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
                    <td className="py-1.5 text-right hidden md:table-cell" style={{ color: 'var(--arcis-text-muted)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
                      {cmd.execution_ms ? `${cmd.execution_ms}ms` : '--'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Log Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex gap-1">
          {['ALL', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((level) => (
            <button
              key={level}
              onClick={() => setLevelFilter(level)}
              className="px-2.5 py-1 text-xs"
              style={{
                borderRadius: 'var(--radius-sm)',
                background: levelFilter === level ? 'var(--arcis-accent)' : 'var(--arcis-bg-surface)',
                color: levelFilter === level ? 'white' : 'var(--arcis-text-secondary)',
                border: '1px solid ' + (levelFilter === level ? 'var(--arcis-accent)' : 'var(--arcis-border)'),
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
          className="text-sm px-2 py-1"
          style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-primary)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-primary)' }}
        />
        <span className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>
          {logs.length} entries (auto-refresh 30s)
        </span>
      </div>

      {/* Log Table */}
      <div className="overflow-hidden" style={{ borderRadius: 'var(--radius-sm)', background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
        <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0" style={{ background: 'var(--arcis-bg-surface)' }}>
              <tr style={{ color: 'var(--arcis-text-secondary)', borderBottom: '1px solid var(--arcis-border)', letterSpacing: '0.06em' }}>
                <th className="py-2 px-3 w-6"></th>
                <th className="text-left py-2 px-3 text-xs uppercase" style={{ fontSize: '10px' }}>Time</th>
                <th className="text-left py-2 px-3 text-xs uppercase" style={{ fontSize: '10px' }}>Level</th>
                <th className="text-left py-2 px-3 text-xs uppercase hidden md:table-cell" style={{ fontSize: '10px' }}>Source</th>
                <th className="text-left py-2 px-3 text-xs uppercase" style={{ fontSize: '10px' }}>Message</th>
              </tr>
            </thead>
            <tbody>
              {logs.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-8 text-center" style={{ color: 'var(--arcis-text-muted)' }}>
                    System logs will appear here once the watch loop starts recording
                  </td>
                </tr>
              ) : (
                logs.map((log, i) => (
                  <ExpandableLogRow key={log.log_id || i} log={log} rowIndex={i} />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
