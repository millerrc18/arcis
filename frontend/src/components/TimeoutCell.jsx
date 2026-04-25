const STATUS_COLORS = {
  on_track:    'var(--arcis-success)',
  approaching: 'var(--arcis-warning)',
  overdue:     'var(--arcis-danger)',
  unknown:     'var(--arcis-text-muted)',
}

export default function TimeoutCell({
  durationDays = null,
  timeoutDays  = null,
  llmTimeoutDays = null,
  status       = 'unknown',
  progressPct  = null,
}) {
  const color = STATUS_COLORS[status] || STATUS_COLORS.unknown
  const barPct = progressPct != null ? Math.min(progressPct, 100) : 0
  const llmMismatch = llmTimeoutDays != null && timeoutDays != null && llmTimeoutDays !== timeoutDays

  const durationLabel = durationDays != null ? durationDays : '--'
  const timeoutLabel  = timeoutDays  != null ? timeoutDays  : '--'
  const llmLabel      = llmTimeoutDays != null ? llmTimeoutDays : 'default'

  return (
    <div style={{ minWidth: 90 }}>
      <div className="financial-data" style={{ color, fontSize: '0.8rem', lineHeight: 1.2 }}>
        {durationLabel} / {timeoutLabel}d
        {llmMismatch && (
          <span
            title={`LLM proposed ${llmTimeoutDays} days; out of bounds; using default ${timeoutDays}.`}
            style={{ marginLeft: 4, cursor: 'help' }}
          >
            &#9888;
          </span>
        )}
      </div>
      <div style={{
        marginTop: 3,
        height: 3,
        borderRadius: 1,
        background: 'var(--arcis-bg-elevated)',
        overflow: 'hidden',
      }}>
        <div style={{
          width: `${barPct}%`,
          height: '100%',
          background: color,
          animation: status === 'overdue' ? 'arcis-pulse 1.5s ease-in-out infinite' : undefined,
        }} />
      </div>
      <div style={{ marginTop: 2, fontSize: '0.65rem', color: 'var(--arcis-text-muted)' }}>
        LLM: {llmLabel}
      </div>
    </div>
  )
}
