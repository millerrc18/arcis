export default function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center py-12">
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--arcis-text-muted)' }}>
        LOADING...
      </span>
    </div>
  )
}
