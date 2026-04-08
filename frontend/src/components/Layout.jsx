import { useState, useEffect } from 'react'
import { Outlet, NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { IS_CLOUD } from '../config'
import { LayoutDashboard, FileText, TrendingUp, Brain, BarChart3, Settings, Map, BookOpen, Users, Activity, Menu, X, DollarSign, ShieldCheck, ScrollText, Network, Database, FlaskConical, Zap, TestTube2, Cpu } from 'lucide-react'
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
    { to: '/model-performance', icon: Cpu, label: 'Model Perf' },
    { to: '/stress-test', icon: Zap, label: 'Stress Test' },
    { to: '/simulation', icon: TestTube2, label: 'Simulation' },
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

function StatusBar({ status }) {
  const [time, setTime] = useState('')

  useEffect(() => {
    const tick = () => {
      const now = new Date()
      setTime(now.toLocaleTimeString('en-US', { hour12: false, timeZone: 'America/New_York' }) + ' ET')
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  const llmStatus = IS_CLOUD ? 'CLOUD' : (status?.ollama_available ? 'ONLINE' : 'OFFLINE')
  const mktStatus = status?.market_open ? 'OPEN' : 'CLOSED'
  const tlState = status?.traffic_light || '--'
  const positions = status?.open_positions ?? '--'
  const version = status?.version || 'v0.16.0'

  return (
    <div
      className="flex items-center gap-4 px-3 shrink-0 overflow-x-auto"
      style={{
        height: 28,
        background: 'var(--arcis-bg-primary)',
        borderBottom: '1px solid var(--arcis-border)',
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        color: 'var(--arcis-text-muted)',
        whiteSpace: 'nowrap',
      }}
    >
      <span>ARCIS {version}</span>
      <span style={{ color: 'var(--arcis-border)' }}>|</span>
      <span>LLM <span style={{ color: llmStatus === 'ONLINE' || llmStatus === 'CLOUD' ? 'var(--arcis-success)' : 'var(--arcis-danger)' }}>{llmStatus}</span></span>
      <span style={{ color: 'var(--arcis-border)' }}>|</span>
      <span>MKT <span style={{ color: mktStatus === 'OPEN' ? 'var(--arcis-success)' : 'var(--arcis-text-secondary)' }}>{mktStatus}</span></span>
      <span style={{ color: 'var(--arcis-border)' }}>|</span>
      <span>TL: <span style={{ color: tlState === 'GREEN' ? 'var(--arcis-success)' : tlState === 'RED' ? 'var(--arcis-danger)' : tlState === 'AMBER' ? 'var(--arcis-warning)' : 'var(--arcis-text-secondary)' }}>{tlState.toUpperCase()}</span></span>
      <span style={{ color: 'var(--arcis-border)' }}>|</span>
      <span>{positions} POSITIONS</span>
      <span style={{ color: 'var(--arcis-border)' }}>|</span>
      <span>{time}</span>
    </div>
  )
}

export default function Layout() {
  const { data: status } = useQuery({ queryKey: ['status'], queryFn: api.getStatus, refetchInterval: 30000 })
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div className="flex h-screen overflow-hidden">
      {sidebarOpen && (
        <div className="fixed inset-0 bg-black/50 z-30 md:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      <aside
        className={`${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0 fixed md:static z-40 h-full flex flex-col shrink-0 transition-transform duration-200`}
        style={{ width: 200, background: 'var(--arcis-bg-primary)', borderRight: '1px solid var(--arcis-border)' }}
      >
        <div className="px-3 py-3" style={{ borderBottom: '1px solid var(--arcis-border)' }}>
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-lg font-bold tracking-tight" style={{ color: 'var(--arcis-accent)' }}>ARCIS</h1>
              <div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--arcis-text-muted)' }}>Systematic Equity Research</div>
            </div>
            <ThemeToggle />
          </div>
        </div>
        <nav className="flex-1 py-1 overflow-y-auto">
          {navSections.map(section => (
            <div key={section.label}>
              <div style={{ padding: '12px 12px 4px', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 500, color: 'var(--arcis-text-muted)' }}>
                {section.label}
              </div>
              {section.items.map(({ to, icon: Icon, label }) => (
                <NavLink key={to} to={to} end={to === '/'}
                  onClick={() => setSidebarOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-2.5 relative ${
                      isActive
                        ? 'text-[var(--arcis-text-primary)] font-medium'
                        : 'text-[var(--arcis-text-secondary)] hover:text-[var(--arcis-text-primary)]'
                    }`
                  }
                  style={{ padding: '6px 12px', fontSize: 13 }}>
                  {({ isActive }) => (
                    <>
                      {isActive && (
                        <span className="absolute left-0 top-0.5 bottom-0.5" style={{ width: 2, background: 'var(--arcis-accent)' }} />
                      )}
                      <Icon size={15} className="shrink-0" style={{ color: isActive ? 'var(--arcis-accent)' : 'var(--arcis-text-secondary)' }} />
                      <span className="truncate">{label}</span>
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        {status && (
          <div style={{ padding: '8px 12px', fontSize: 11, borderTop: '1px solid var(--arcis-border)' }}>
            <div className="flex justify-between" style={{ marginBottom: 4 }}>
              <span style={{ color: 'var(--arcis-text-secondary)' }}>LLM</span>
              {IS_CLOUD
                ? <StatusBadge text="Cloud" variant="info" />
                : <StatusBadge text={status.ollama_available ? 'Online' : 'Offline'} variant={status.ollama_available ? 'success' : 'danger'} />
              }
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

      <div className="flex-1 flex flex-col min-w-0">
        <header className="flex items-center px-3 shrink-0 md:hidden justify-between" style={{ height: 40, background: 'var(--arcis-bg-primary)', borderBottom: '1px solid var(--arcis-border)' }}>
          <div className="flex items-center">
            <button onClick={() => setSidebarOpen(!sidebarOpen)} className="p-1" style={{ color: 'var(--arcis-text-secondary)' }}>
              {sidebarOpen ? <X size={18} /> : <Menu size={18} />}
            </button>
            <span className="ml-2 text-sm font-bold" style={{ color: 'var(--arcis-accent)' }}>ARCIS</span>
          </div>
          <ThemeToggle />
        </header>
        <StatusBar status={status} />
        <main className="flex-1 overflow-y-auto p-4">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
