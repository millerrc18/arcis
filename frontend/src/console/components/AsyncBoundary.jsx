/**
 * AsyncBoundary — distinguishes the three TanStack Query states the console
 * otherwise collapses into a single UNKNOWN/no-data render (a law-#4 refinement).
 *
 *   isError (fetch threw — the API SERVER itself is unreachable) -> "source unavailable"
 *   first load in flight (isPending, no data yet)                -> "loading…"
 *   resolved (data present, even honest-degraded)                -> render children
 *
 * Loading and error are muted/neutral — NEVER green/healthy, so law #4 still
 * holds. Only the resolved case reaches the child's own honest no-data/UNKNOWN
 * render, so a genuinely-absent signal still reads UNKNOWN (not "loading").
 *
 * Why this matters: before this, every section flashed UNKNOWN for ~1s on first
 * paint (data undefined while the first fetch is in flight) and rendered UNKNOWN
 * identically whether the source was loading, errored, or genuinely empty. After
 * #1210/#1211 the console backend returns 200-honest-degraded (not 5xx) on a DB
 * hiccup, so `isError` here specifically means the API server is unreachable — a
 * distinct, rarer condition that deserves its own state rather than masquerading
 * as no-data.
 */
const BASE = {
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
  padding: '8px 12px',
  borderRadius: 'var(--radius-sm)',
}

const LOADING_STYLE = {
  ...BASE,
  color: 'var(--arcis-text-muted, #71717a)',
  background: 'rgba(63,63,70,0.15)',
  border: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
}

const ERROR_STYLE = {
  ...BASE,
  color: 'var(--arcis-warning, #f59e0b)',
  background: 'rgba(245,158,11,0.08)',
  border: '1px solid rgba(245,158,11,0.4)',
}

export default function AsyncBoundary({ query, label, children }) {
  // Error first: an unreachable API server must never show stale data as healthy.
  if (query?.isError) {
    return (
      <div data-testid="async-error" style={ERROR_STYLE}>
        {label ? `${label} — ` : ''}source unavailable
      </div>
    )
  }
  // First load only: isPending (v5) is true until the first fetch resolves; the
  // `data == null` guard means a background refetch (data present) does NOT flash.
  const loading = query?.isPending ?? query?.isLoading
  if (loading && query?.data == null) {
    return (
      <div data-testid="async-loading" style={LOADING_STYLE}>
        {label ? `${label} — ` : ''}loading…
      </div>
    )
  }
  return children
}
