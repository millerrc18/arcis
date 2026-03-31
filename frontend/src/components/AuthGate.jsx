import { useState, useEffect } from 'react'
import { API_BASE, IS_CLOUD } from '../config'

const TOKEN_KEY = 'hl_token'
const TOKEN_TS_KEY = 'hl_token_ts'
const SESSION_MAX_MS = 7 * 24 * 60 * 60 * 1000 // 7 days

function isSessionValid() {
  const token = localStorage.getItem(TOKEN_KEY)
  const ts = localStorage.getItem(TOKEN_TS_KEY)
  if (!token || !ts) return false
  const elapsed = Date.now() - parseInt(ts, 10)
  return elapsed < SESSION_MAX_MS
}

export function clearAuthSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(TOKEN_TS_KEY)
}

export default function AuthGate({ children }) {
  const [authed, setAuthed] = useState(false)
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  // If not cloud mode, render children directly
  if (!IS_CLOUD) return children

  useEffect(() => {
    if (isSessionValid()) {
      setAuthed(true)
    }
  }, [])

  if (authed) return children

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/auth`, {
        headers: { Authorization: `Bearer ${password}` },
      })
      if (res.ok) {
        localStorage.setItem(TOKEN_KEY, password)
        localStorage.setItem(TOKEN_TS_KEY, String(Date.now()))
        setAuthed(true)
      } else {
        setError('Invalid password')
      }
    } catch {
      setError('Connection failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--arcis-bg-primary)' }}>
      <form
        onSubmit={handleSubmit}
        className="rounded-xl p-8 w-full max-w-sm shadow-lg"
        style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}
      >
        <h1
          className="text-center mb-6"
          style={{ fontSize: '28px', fontWeight: 800, color: 'var(--arcis-accent)', letterSpacing: '-0.03em' }}
        >
          ARCIS
        </h1>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Dashboard password"
          className="w-full px-4 py-2 rounded-lg mb-4 text-sm outline-none transition-shadow"
          style={{
            background: 'var(--arcis-bg-elevated)',
            border: '1px solid var(--arcis-border)',
            color: 'var(--arcis-text-primary)',
          }}
          onFocus={(e) => e.target.style.boxShadow = '0 0 0 2px var(--arcis-accent)'}
          onBlur={(e) => e.target.style.boxShadow = 'none'}
          autoFocus
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !password}
          className="w-full py-2 font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ background: 'var(--arcis-accent)', color: 'white' }}
          onMouseEnter={(e) => { if (!e.target.disabled) e.target.style.background = 'var(--arcis-accent-hover)' }}
          onMouseLeave={(e) => e.target.style.background = 'var(--arcis-accent)'}
        >
          {loading ? 'Signing in...' : 'Sign in'}
        </button>
        {error && (
          <p className="mt-3 text-sm text-center" style={{ color: 'var(--arcis-danger)' }}>{error}</p>
        )}
      </form>
    </div>
  )
}
