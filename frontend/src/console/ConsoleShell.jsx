/**
 * ConsoleShell — three-region console shell (T8).
 * Nav: Now / Decide / Know
 * Decide and Know are placeholders (T9+ will build content).
 * Now region is the default route — body is T9's responsibility.
 */
import { NavLink, Routes, Route, Navigate } from 'react-router-dom'
import HonestHeader from './HonestHeader'
import NowRegion from './now/NowRegion'

function DecidePlaceholder() {
  return (
    <div
      data-testid="decide-region"
      style={{
        padding: 24,
        color: 'var(--arcis-text-muted, #71717a)',
        fontFamily: 'var(--font-mono)',
        fontSize: 13,
        textAlign: 'center',
      }}
    >
      Decide — coming soon
    </div>
  )
}

function KnowPlaceholder() {
  return (
    <div
      data-testid="know-region"
      style={{
        padding: 24,
        color: 'var(--arcis-text-muted, #71717a)',
        fontFamily: 'var(--font-mono)',
        fontSize: 13,
        textAlign: 'center',
      }}
    >
      Know — coming soon
    </div>
  )
}

const NAV_STYLE = {
  display: 'flex',
  gap: 0,
  padding: '0 16px',
  background: 'var(--arcis-surface, #18181b)',
  borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
}

const linkStyle = ({ isActive }) => ({
  display: 'inline-block',
  padding: '8px 16px',
  fontSize: 12,
  fontFamily: 'var(--font-mono)',
  fontWeight: 600,
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  textDecoration: 'none',
  color: isActive
    ? 'var(--arcis-text-primary, #fff)'
    : 'var(--arcis-text-muted, #71717a)',
  borderBottom: isActive
    ? '2px solid var(--arcis-accent, #6366f1)'
    : '2px solid transparent',
})

export default function ConsoleShell() {
  return (
    <div
      data-testid="console-shell"
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: '100vh',
        background: 'var(--arcis-bg, #09090b)',
      }}
    >
      <HonestHeader />

      <nav style={NAV_STYLE} aria-label="Console regions">
        <NavLink to="/console/now" style={linkStyle} end>Now</NavLink>
        <NavLink to="/console/decide" style={linkStyle}>Decide</NavLink>
        <NavLink to="/console/know" style={linkStyle}>Know</NavLink>
      </nav>

      <main style={{ flex: 1, overflow: 'auto' }}>
        <Routes>
          <Route index element={<Navigate to="now" replace />} />
          <Route path="now" element={<NowRegion />} />
          <Route path="decide" element={<DecidePlaceholder />} />
          <Route path="know" element={<KnowPlaceholder />} />
        </Routes>
      </main>
    </div>
  )
}
