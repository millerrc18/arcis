import { Inbox } from 'lucide-react'

export default function EmptyState({ message = 'No data available', icon: Icon = Inbox }) {
  return (
    <div className="flex flex-col items-center justify-center py-16" style={{ color: 'var(--arcis-text-secondary)' }}>
      <Icon size={48} strokeWidth={1} className="mb-4 opacity-40" />
      <p className="text-sm">{message}</p>
    </div>
  )
}
