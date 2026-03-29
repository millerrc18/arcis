export default function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center py-12">
      <div className="w-8 h-8 border-2 rounded-full animate-spin" style={{ borderColor: 'var(--slate-600)', borderTopColor: 'var(--teal-400)' }} />
    </div>
  )
}
