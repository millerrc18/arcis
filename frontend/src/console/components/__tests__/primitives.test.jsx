/**
 * Honesty-primitive tests for the Founder Console (T7).
 * Tests MUST fail before implementation — they define the contract.
 *
 * Laws:
 *   #2 — Every metric requires cohort, n, asOf (Metric.jsx)
 *   #3 — Sentinel values render as "no data"; true 0 renders as a value (SentinelGuard.jsx)
 *   #4 — asOf missing => "unknown" NEVER green (StalenessBadge.jsx)
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import Metric from '../Metric'
import SentinelGuard from '../SentinelGuard'
import StalenessBadge from '../StalenessBadge'

// ---------------------------------------------------------------------------
// Metric
// ---------------------------------------------------------------------------
describe('Metric', () => {
  it('renders label, value, cohort, n, and asOf when all props provided', () => {
    render(
      <Metric
        label="Win Rate"
        value="68.4%"
        cohort="live-2026-Q1"
        n={160}
        asOf="2026-06-01T12:00:00Z"
      />
    )
    expect(screen.getByText('68.4%')).toBeInTheDocument()
    expect(screen.getByText(/Win Rate/i)).toBeInTheDocument()
    expect(screen.getByText(/live-2026-Q1/i)).toBeInTheDocument()
    expect(screen.getByText(/n=160/i)).toBeInTheDocument()
    expect(screen.getByText(/2026-06-01/)).toBeInTheDocument()
  })

  it('renders error state when cohort is missing', () => {
    render(
      <Metric
        label="Win Rate"
        value="68.4%"
        n={160}
        asOf="2026-06-01T12:00:00Z"
      />
    )
    // Must NOT silently render the bare value alone
    expect(screen.queryByText('68.4%')).not.toBeInTheDocument()
    expect(screen.getByTestId('metric-error')).toBeInTheDocument()
  })

  it('renders error state when n is missing', () => {
    render(
      <Metric
        label="Sharpe"
        value="1.2"
        cohort="live-2026-Q1"
        asOf="2026-06-01T12:00:00Z"
      />
    )
    expect(screen.queryByText('1.2')).not.toBeInTheDocument()
    expect(screen.getByTestId('metric-error')).toBeInTheDocument()
  })

  it('renders error state when asOf is missing', () => {
    render(
      <Metric
        label="Sharpe"
        value="1.2"
        cohort="live-2026-Q1"
        n={80}
      />
    )
    expect(screen.queryByText('1.2')).not.toBeInTheDocument()
    expect(screen.getByTestId('metric-error')).toBeInTheDocument()
  })

  it('renders error state when asOf is undefined', () => {
    render(
      <Metric
        label="Sharpe"
        value="1.2"
        cohort="live-2026-Q1"
        n={80}
        asOf={undefined}
      />
    )
    expect(screen.getByTestId('metric-error')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// SentinelGuard
// ---------------------------------------------------------------------------
describe('SentinelGuard', () => {
  const NO_DATA_LABEL = /no data/i

  it.each([999, NaN, -1, Infinity, null, undefined])(
    'maps sentinel value %s to no-data state',
    (sentinel) => {
      render(<SentinelGuard value={sentinel} label="Open PnL" />)
      expect(screen.getByTestId('sentinel-no-data')).toBeInTheDocument()
      expect(screen.getByText(NO_DATA_LABEL)).toBeInTheDocument()
    }
  )

  it('renders true 0 as a value (not no-data)', () => {
    render(<SentinelGuard value={0} label="Open PnL" />)
    // 0 must show the numeric value
    expect(screen.getByTestId('sentinel-value')).toBeInTheDocument()
    expect(screen.queryByTestId('sentinel-no-data')).not.toBeInTheDocument()
  })

  it('true 0 value element is visually distinct from no-data element (different test-id)', () => {
    const { rerender } = render(<SentinelGuard value={0} label="Score" />)
    expect(screen.getByTestId('sentinel-value')).toBeInTheDocument()

    rerender(<SentinelGuard value={null} label="Score" />)
    expect(screen.getByTestId('sentinel-no-data')).toBeInTheDocument()
    expect(screen.queryByTestId('sentinel-value')).not.toBeInTheDocument()
  })

  it('renders positive numeric value (not sentinel) as a value', () => {
    render(<SentinelGuard value={42.5} label="Score" />)
    expect(screen.getByTestId('sentinel-value')).toBeInTheDocument()
    expect(screen.getByText('42.5')).toBeInTheDocument()
    expect(screen.queryByTestId('sentinel-no-data')).not.toBeInTheDocument()
  })

  it('renders negative value that is not -1 as a value', () => {
    render(<SentinelGuard value={-2.3} label="PnL" />)
    expect(screen.getByTestId('sentinel-value')).toBeInTheDocument()
    expect(screen.queryByTestId('sentinel-no-data')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// StalenessBadge
// ---------------------------------------------------------------------------
describe('StalenessBadge', () => {
  const FRESH_CLASS = 'staleness-fresh'
  const STALE_CLASS = 'staleness-stale'
  const UNKNOWN_CLASS = 'staleness-unknown'
  const GREEN_CLASS = 'staleness-green'

  it('shows green/fresh badge when asOf is recent and within maxAge', () => {
    const recentAsOf = new Date(Date.now() - 60_000).toISOString() // 1 min ago
    render(<StalenessBadge asOf={recentAsOf} maxAge={300} />)
    const badge = screen.getByTestId('staleness-badge')
    expect(badge).toBeInTheDocument()
    expect(badge.className).toMatch(/staleness-fresh|staleness-green/)
    expect(badge.className).not.toMatch(/staleness-unknown/)
  })

  it('shows stale/degraded badge when past maxAge', () => {
    const oldAsOf = new Date(Date.now() - 600_000).toISOString() // 10 min ago
    render(<StalenessBadge asOf={oldAsOf} maxAge={60} />) // maxAge = 60s
    const badge = screen.getByTestId('staleness-badge')
    expect(badge.className).toMatch(/staleness-stale|staleness-degraded/)
    expect(badge.className).not.toMatch(/staleness-fresh|staleness-green/)
  })

  it('shows "unknown" when asOf is null — NEVER green (law #4)', () => {
    render(<StalenessBadge asOf={null} maxAge={300} />)
    const badge = screen.getByTestId('staleness-badge')
    expect(screen.getByText(/unknown/i)).toBeInTheDocument()
    expect(badge.className).not.toMatch(/staleness-fresh|staleness-green/)
    expect(badge.className).toMatch(/staleness-unknown/)
  })

  it('shows "unknown" when asOf is undefined — NEVER green (law #4)', () => {
    render(<StalenessBadge maxAge={300} />)
    const badge = screen.getByTestId('staleness-badge')
    expect(screen.getByText(/unknown/i)).toBeInTheDocument()
    expect(badge.className).not.toMatch(/staleness-fresh|staleness-green/)
    expect(badge.className).toMatch(/staleness-unknown/)
  })

  it('shows "unknown" when asOf is missing entirely — NEVER green (law #4)', () => {
    render(<StalenessBadge maxAge={60} />)
    const badge = screen.getByTestId('staleness-badge')
    expect(badge.className).toMatch(/staleness-unknown/)
    expect(badge.className).not.toMatch(/staleness-fresh/)
  })

  it('displays the staleness timestamp text when fresh', () => {
    const recentAsOf = new Date(Date.now() - 30_000).toISOString()
    render(<StalenessBadge asOf={recentAsOf} maxAge={300} />)
    // Should show SOMETHING about the time (not blank)
    expect(screen.getByTestId('staleness-badge').textContent).not.toBe('')
  })
})
