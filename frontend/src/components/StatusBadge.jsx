const variants = {
  success: { bg: 'rgba(34, 197, 94, 0.12)', text: 'var(--arcis-success)' },
  danger: { bg: 'rgba(239, 68, 68, 0.12)', text: 'var(--arcis-danger)' },
  warning: { bg: 'rgba(245, 158, 11, 0.12)', text: 'var(--arcis-warning)' },
  info: { bg: 'var(--arcis-accent-muted)', text: 'var(--arcis-info)' },
  neutral: { bg: 'var(--arcis-bg-elevated)', text: 'var(--arcis-text-secondary)' },
}

export default function StatusBadge({ text, variant = 'neutral' }) {
  const v = variants[variant] || variants.neutral
  return (
    <span style={{ display: 'inline-block', padding: '2px 6px', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 500, background: v.bg, color: v.text, borderRadius: 'var(--radius-sm)' }}>
      {text}
    </span>
  )
}
