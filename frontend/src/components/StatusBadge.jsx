const variants = {
  success: { bg: 'rgba(16, 185, 129, 0.15)', text: 'var(--success)', border: 'var(--success)' },
  danger: { bg: 'rgba(239, 68, 68, 0.15)', text: 'var(--danger)', border: 'var(--danger)' },
  warning: { bg: 'rgba(245, 158, 11, 0.15)', text: 'var(--warning)', border: 'var(--warning)' },
  info: { bg: 'rgba(59, 130, 246, 0.15)', text: 'var(--info)', border: 'var(--info)' },
  neutral: { bg: 'var(--slate-700)', text: 'var(--slate-300)', border: 'var(--slate-600)' },
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
