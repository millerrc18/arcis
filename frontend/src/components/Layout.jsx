import { useState } from 'react'
import { Outlet, NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { IS_CLOUD } from '../config'
import { LayoutDashboard, FileText, TrendingUp, Brain, BarChart3, Settings, Map, BookOpen, Users, Activity, Menu, X, DollarSign, ShieldCheck, ScrollText, Network, Database, FlaskConical, Zap, BarChart2 } from 'lucide-react'
import StatusBadge from './StatusBadge'
import ThemeToggle from './ThemeToggle'

const navSections = [
  { label: 'Trading', items: [
    { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
    { to: '/packets', icon: FileText, label: 'Packets' },
    { to: '/shadow', icon: TrendingUp, label: 'Shadow Ledger' },
    { to: '/live', icon: DollarSign, label: 'Live Ledger' },
  ]},
  { label: 'Intelligence', items: [
    { to: '/training', icon: Brain, label: 'Training' },
    { to: '/council', icon: Users, label: 'Council' },
    { to: '/cto-report', icon: BarChart3, label: 'CTO Report' },
    { to: '/attribution', icon: FlaskConical, label: 'Attribution' },
    { to: '/stress-test', icon: Zap, label: 'Stress Test' },
    { to: '/simulation', icon: BarChart2, label: 'Simulation' },
  ]},
  { label: 'System', items: [
    { to: '/architecture', icon: Network, label: 'Architecture' },
    { to: '/schema', icon: Database, label: 'DB Schema' },
    { to: '/health', icon: Activity, label: 'Health Score' },
    { to: '/validation', icon: ShieldCheck, label: 'Validation' },
    { to: '/logs', icon: ScrollText, label: 'Logs' },
  ]},
  { label: 'Reference', items: [
    { to: '/settings', icon: Settings, label: 'Settings' },
    { to: '/roadmap', icon: Map, label: 'Roadmap' },
    { to: '/docs', icon: BookOpen, label: 'Docs' },
    { to: '/notes', icon: FileText, label: 'Notes' },
  ]},
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
      <aside className={`${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0 fixed md:static z-40 w-56 h-full flex flex-col shrink-0 transition-transform duration-200`} style={{ background: 'var(--arcis-bg-primary)', borderRight: '1px solid var(--arcis-border)' }}>
        <div className="p-4" style={{ borderBottom: '1px solid var(--arcis-border)' }}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <h1 className="text-2xl font-extrabold" style={{ color: 'var(--arcis-accent)', letterSpacing: '-0.03em' }}>ARCIS</h1>
              <div className="text-xs mt-1 uppercase tracking-[0.04em]" style={{ color: 'var(--arcis-text-secondary)' }}>Systematic Equity Research</div>
            </div>
            <ThemeToggle />
          </div>
        </div>
        <nav className="flex-1 py-1 overflow-y-auto">
          {navSections.map(section => (
            <div key={section.label}>
              <div className="px-4 pt-4 pb-1 text-[10px] uppercase tracking-[0.08em] font-medium"
                style={{ color: 'var(--arcis-text-muted)' }}>
                {section.label}
              </div>
              {section.items.map(({ to, icon: Icon, label }) => (
                <NavLink key={to} to={to} end={to === '/'}
                  onClick={() => setSidebarOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-4 py-2 text-sm transition-colors relative ${
                      isActive
                        ? 'text-[var(--arcis-text-primary)]'
                        : 'text-[var(--arcis-text-secondary)] hover:text-[var(--arcis-text-primary)]'
                    }`
                  }>
                  {({ isActive }) => (
                    <>
                      {isActive && (
                        <>
                          <span className="absolute inset-x-2 inset-y-0 rounded-lg" style={{ background: 'var(--arcis-accent-muted)' }} />
                          <span className="absolute left-0 top-1 bottom-1 w-0.5 rounded-r" style={{ background: 'var(--arcis-accent)' }} />
                        </>
                      )}
                      <Icon size={18} className="relative z-10" style={{ color: isActive ? 'var(--arcis-accent)' : 'var(--arcis-text-secondary)' }} />
                      <span>{label}</span>
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        {status && (
          <div className="p-4 text-xs space-y-1" style={{ borderTop: '1px solid var(--arcis-border)' }}>
            <div className="flex justify-between">
              <span style={{ color: 'var(--arcis-text-secondary)' }}>LLM</span>
              {IS_CLOUD
                ? <StatusBadge text="Cloud" variant="info" />
                : <StatusBadge text={status.ollama_available ? 'Online' : 'Offline'} variant={status.ollama_available ? 'success' : 'danger'} />
              }
            </div>
            <div className="flex justify-between">
              <span style={{ color: 'var(--arcis-text-secondary)' }}>Model</span>
              <span style={{ color: 'var(--arcis-text-secondary)' }}>{status.model_version || (IS_CLOUD ? 'cloud' : '--')}</span>
            </div>
            <div className="flex justify-between">
              <span style={{ color: 'var(--arcis-text-secondary)' }}>Shadow</span>
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
        <header className="flex items-center h-14 px-4 border-b shrink-0 md:hidden justify-between" style={{ background: 'var(--arcis-bg-primary)', borderColor: 'var(--arcis-border)' }}>
          <div className="flex items-center">
            <button onClick={() => setSidebarOpen(!sidebarOpen)} className="p-1 rounded" style={{ color: 'var(--arcis-text-secondary)' }}>
              {sidebarOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
            <span className="ml-3 text-base font-extrabold" style={{ color: 'var(--arcis-accent)', letterSpacing: '-0.03em' }}>ARCIS</span>
          </div>
          <ThemeToggle />
        </header>
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
