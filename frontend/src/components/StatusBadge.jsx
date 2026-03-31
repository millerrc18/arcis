const variants = {
  success: { bg: 'rgba(34, 197, 94, 0.15)', text: 'var(--arcis-success)', border: 'var(--arcis-success)' },
  danger: { bg: 'rgba(239, 68, 68, 0.15)', text: 'var(--arcis-danger)', border: 'var(--arcis-danger)' },
  warning: { bg: 'rgba(245, 158, 11, 0.15)', text: 'var(--arcis-warning)', border: 'var(--arcis-warning)' },
  info: { bg: 'var(--arcis-accent-muted)', text: 'var(--arcis-info)', border: 'var(--arcis-info)' },
  neutral: { bg: 'var(--arcis-bg-surface)', text: 'var(--arcis-text-secondary)', border: 'var(--arcis-border)' },
}

export default function StatusBadge({ text, variant = 'neutral' }) {
  const v = variants[variant] || variants.neutral
  return (
    <span
      className="inline-block px-2 py-0.5 text-xs rounded"
      style={{ background: v.bg, color: v.text, border: `1px solid ${v.border}` }}
    >
      {text}
    </span>
  )
}
