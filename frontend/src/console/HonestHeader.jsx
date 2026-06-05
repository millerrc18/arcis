/**
 * HonestHeader — ARCIS console header (T8).
 * Renders version/PAPER/bootcamp/market/clock from GET /api/console/header.
 * Global PAUSE control reads GET /api/console/pause, toggles via POST.
 * All values come from the API — never hardcoded.
 */
import { useState, useEffect } from 'react'
import { fetchApi } from '../api'
import StalenessBadge from './components/StalenessBadge'

export default function HonestHeader() {
  const [header, setHeader] = useState(null)
  const [pauseStatus, setPauseStatus] = useState(null)
  const [toggling, setToggling] = useState(false)

  useEffect(() => {
    fetchApi('/console/header').then(setHeader).catch(() => setHeader(null))
    fetchApi('/console/pause').then(setPauseStatus).catch(() => setPauseStatus(null))
  }, [])

  async function handlePauseToggle() {
    if (!pauseStatus || toggling) return
    setToggling(true)
    try {
      const action = pauseStatus.paused ? 'resume' : 'pause'
      const result = await fetchApi('/console/pause', {
        method: 'POST',
        body: JSON.stringify({ action }),
      })
      setPauseStatus(result)
    } finally {
      setToggling(false)
    }
  }

  return (
    <header
      data-testid="honest-header"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '8px 16px',
        background: 'var(--arcis-surface, #18181b)',
        borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
        flexWrap: 'wrap',
      }}
    >
      <span style={{ fontWeight: 700, letterSpacing: '0.08em', color: 'var(--arcis-text-primary, #fff)' }}>
        ARCIS
      </span>

      {header ? (
        <>
          <span style={{ color: 'var(--arcis-text-secondary, #a1a1aa)' }}>
            {header.version}
          </span>

          <span
            style={{
              padding: '1px 6px',
              background: 'rgba(245,158,11,0.15)',
              border: '1px solid rgba(245,158,11,0.4)',
              borderRadius: 3,
              color: 'var(--arcis-warning, #f59e0b)',
              fontWeight: 600,
              fontSize: 10,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
            }}
          >
            {header.paper ? 'PAPER' : 'LIVE'}
          </span>

          <span style={{ color: 'var(--arcis-text-secondary, #a1a1aa)' }}>
            {`bootcamp ${header.bootcamp ? 'ON' : 'OFF'}`}
          </span>

          <span style={{ color: 'var(--arcis-text-secondary, #a1a1aa)' }}>
            {header.market_state}
          </span>

          <StalenessBadge asOf={header.clock} maxAge={120} />
        </>
      ) : (
        <span style={{ color: 'var(--arcis-text-muted, #71717a)' }}>loading…</span>
      )}

      <div
        data-testid="pause-control"
        style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}
      >
        {pauseStatus === null ? (
          <span style={{ color: 'var(--arcis-text-muted, #71717a)', fontSize: 11 }}>—</span>
        ) : (
          <>
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
                color: pauseStatus.paused
                  ? 'var(--arcis-danger, #ef4444)'
                  : 'var(--arcis-success, #22c55e)',
              }}
            >
              {pauseStatus.paused ? 'PAUSED' : 'RUNNING'}
            </span>
            <button
              data-testid="pause-toggle-btn"
              onClick={handlePauseToggle}
              disabled={toggling}
              style={{
                padding: '2px 10px',
                fontSize: 11,
                fontFamily: 'var(--font-mono)',
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                cursor: toggling ? 'wait' : 'pointer',
                background: pauseStatus.paused
                  ? 'rgba(34,197,94,0.12)'
                  : 'rgba(239,68,68,0.12)',
                border: pauseStatus.paused
                  ? '1px solid rgba(34,197,94,0.4)'
                  : '1px solid rgba(239,68,68,0.4)',
                borderRadius: 3,
                color: pauseStatus.paused
                  ? 'var(--arcis-success, #22c55e)'
                  : 'var(--arcis-danger, #ef4444)',
              }}
            >
              {pauseStatus.paused ? 'Resume' : 'Pause'}
            </button>
          </>
        )}
      </div>
    </header>
  )
}
