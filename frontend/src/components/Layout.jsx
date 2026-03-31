import { useState } from 'react'
import { Outlet, NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { IS_CLOUD } from '../config'
import { LayoutDashboard, FileText, TrendingUp, Brain, BarChart3, Settings, Map, BookOpen, Users, Activity, Menu, X, DollarSign, ShieldCheck, ScrollText } from 'lucide-react'
import StatusBadge from './StatusBadge'

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/shadow', icon: TrendingUp, label: 'Shadow Ledger' },
  { to: '/live', icon: DollarSign, label: 'Live Ledger' },
  { to: '/packets', icon: FileText, label: 'Packets' },
  { to: '/council', icon: Users, label: 'Council' },
  { to: '/health', icon: Activity, label: 'Health Score' },
  { to: '/validation', icon: ShieldCheck, label: 'Validation' },
  { to: '/training', icon: Brain, label: 'Training' },
  { to: '/cto-report', icon: BarChart3, label: 'CTO Report' },
  { to: '/docs', icon: BookOpen, label: 'Docs' },
  { to: '/notes', icon: FileText, label: 'Notes' },
  { to: '/logs', icon: ScrollText, label: 'Logs' },
  { to: '/roadmap', icon: Map, label: 'Roadmap' },
  { to: '/settings', icon: Settings, label: 'Settings' },
]

export default function Layout() {
  const { data: status } = useQuery({ queryKey: ['status'], queryFn: api.getStatus })
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 bg-black/50 z-30 md:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Sidebar */}
      <aside className={`${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0 fixed md:static z-40 w-56 h-full bg-[var(--slate-900)] border-r border-[var(--slate-600)] flex flex-col shrink-0 transition-transform duration-200`}>
        <div className="p-4 border-b border-[var(--slate-600)]">
          <h1 className="text-lg font-semibold tracking-wide" style={{ fontFamily: 'var(--font-display)', color: 'var(--teal-400)' }}>HALCYON LAB</h1>
          <div className="text-xs mt-1" style={{ color: 'var(--slate-400)' }}>AI Research Desk</div>
        </div>
        <nav className="flex-1 py-2 overflow-y-auto">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink key={to} to={to} end={to === '/'}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-2 text-sm transition-colors relative ${
                  isActive
                    ? 'text-[var(--slate-50)] bg-[var(--teal-900)]/40'
                    : 'text-[var(--slate-300)] hover:text-[var(--slate-50)] hover:bg-[var(--slate-700)]'
                }`
              }>
              {({ isActive }) => (
                <>
                  {isActive && <span className="absolute left-0 top-1 bottom-1 w-0.5 rounded-r" style={{ background: 'var(--teal-400)' }} />}
                  <Icon size={18} style={{ color: isActive ? 'var(--teal-400)' : 'var(--slate-400)' }} />
                  <span>{label}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>
        {status && (
          <div className="p-4 border-t border-[var(--slate-600)] text-xs space-y-1">
            <div className="flex justify-between">
              <span style={{ color: 'var(--slate-400)' }}>LLM</span>
              {IS_CLOUD
                ? <StatusBadge text="Cloud" variant="info" />
                : <StatusBadge text={status.ollama_available ? 'Online' : 'Offline'} variant={status.ollama_available ? 'success' : 'danger'} />
              }
            </div>
            <div className="flex justify-between">
              <span style={{ color: 'var(--slate-400)' }}>Model</span>
              <span style={{ color: 'var(--slate-300)' }}>{status.model_version || (IS_CLOUD ? 'cloud' : '--')}</span>
            </div>
            <div className="flex justify-between">
              <span style={{ color: 'var(--slate-400)' }}>Shadow</span>
              {IS_CLOUD
                ? <StatusBadge text="Cloud" variant="info" />
                : <StatusBadge text={status.shadow_trading_enabled ? 'Active' : 'Off'} variant={status.shadow_trading_enabled ? 'success' : 'neutral'} />
              }
            </div>
          </div>
        )}
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header bar */}
        <header className="flex items-center h-12 px-4 border-b shrink-0 md:hidden" style={{ background: 'var(--slate-800)', borderColor: 'var(--slate-600)' }}>
          <button onClick={() => setSidebarOpen(!sidebarOpen)} className="p-1 rounded" style={{ color: 'var(--slate-300)' }}>
            {sidebarOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          <span className="ml-3 text-sm font-semibold" style={{ fontFamily: 'var(--font-display)', color: 'var(--teal-400)' }}>HALCYON LAB</span>
        </header>
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
