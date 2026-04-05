export default function EmptyState({ message = 'NO DATA' }) {
  return (
    <div className="flex items-center justify-center py-16">
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--arcis-text-muted)' }}>
        {message}
      </span>
    </div>
  )
}
