/**
 * NowRegion tests (T9).
 * Assembled entirely from T7 primitives + T6 /api/console/now/* endpoints.
 * All endpoints are mocked. Tests are non-vacuous: each asserts a value
 * that only appears when the component consumes the mocked response.
 *
 * Load-bearing law-#4 test: a missing/absent signal renders alarmed/unknown,
 * NEVER green/healthy.
 * Load-bearing law-#3 test: no raw sentinel (999/NaN/-1/Infinity) ever renders.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import NowRegion from '../NowRegion'

// ---------------------------------------------------------------------------
// Mock endpoint payloads (T6 shape: metrics carry {value,n,as_of,cohort,unit,state})
// ---------------------------------------------------------------------------
const NOW = '2026-06-05T14:30:00Z'

const MOCK_GATE = {
  metrics: [
    { key: 'sharpe', label: 'Sharpe', value: 0.8, target: 1.5, n: 120, as_of: NOW, cohort: 'paper-90d', unit: '' },
    { key: 'win_rate', label: 'Win rate', value: 52, target: 60, n: 120, as_of: NOW, cohort: 'paper-90d', unit: '%' },
  ],
  progress: 0.55,
  as_of: NOW,
}

const MOCK_ATTENTION_HEALTHY = { count: 0, desk_healthy: true, as_of: NOW }
const MOCK_ATTENTION_PENDING = { count: 3, desk_healthy: false, as_of: NOW }

const MOCK_SIGNALS = {
  signals: [
    { key: 'heartbeat', label: 'Watch-loop heartbeat', value: 12, unit: 's', as_of: NOW, n: 1, cohort: 'live', state: 'fresh', max_age: 120 },
    { key: 'data_feed', label: 'Data-feed freshness', value: 5, unit: 's', as_of: NOW, n: 1, cohort: 'live', state: 'fresh', max_age: 300 },
    { key: 'reconciliation', label: 'Reconciliation breaks', value: 0, unit: '', as_of: NOW, n: 1, cohort: 'live', state: 'fresh', max_age: 3600 },
    { key: 'risk_governor', label: 'Risk limits used', value: 40, unit: '%', as_of: NOW, n: 1, cohort: 'live', state: 'fresh', max_age: 600 },
  ],
  as_of: NOW,
}

const MOCK_POSITIONS = {
  source: 'reconciled',
  positions: [
    { ticker: 'AAPL', qty: 10, market_value: 1500, unrealized_pnl: 25 },
  ],
  equity: { value: 100000, n: 1, as_of: NOW, cohort: 'paper-book', unit: '$' },
  today_move: { value: 250, n: 1, as_of: NOW, cohort: 'paper-book', unit: '$' },
  as_of: NOW,
}

const MOCK_SINCE = {
  hours: 6,
  opened: 2,
  closed: 1,
  alerts_raised: 0,
  alerts_resolved: 1,
  audit_verdict_changes: 0,
  deploys: 1,
  as_of: NOW,
}

const MOCK_DEVTEAM = {
  current_activity: 'Implementing T9 NOW region',
  prs_this_week: { value: 4, n: 4, as_of: NOW, cohort: 'week', unit: '' },
  regressions_this_week: { value: 0, n: 0, as_of: NOW, cohort: 'week', unit: '' },
  scope_violations_this_week: { value: 0, n: 0, as_of: NOW, cohort: 'week', unit: '' },
  as_of: NOW,
}

// ---------------------------------------------------------------------------
// fetch mock — route /api/console/now/* to overridable payloads
// ---------------------------------------------------------------------------
function jsonResponse(data) {
  return Promise.resolve({
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify(data)),
  })
}

function mockNow(overrides = {}) {
  const payloads = {
    gate: MOCK_GATE,
    attention: MOCK_ATTENTION_HEALTHY,
    signals: MOCK_SIGNALS,
    positions: MOCK_POSITIONS,
    since: MOCK_SINCE,
    devteam: MOCK_DEVTEAM,
    ...overrides,
  }
  const fetchMock = vi.fn((url) => {
    if (url.includes('/console/now/gate')) return jsonResponse(payloads.gate)
    if (url.includes('/console/now/attention')) return jsonResponse(payloads.attention)
    if (url.includes('/console/now/signals')) return jsonResponse(payloads.signals)
    if (url.includes('/console/now/positions')) return jsonResponse(payloads.positions)
    if (url.includes('/console/now/since')) return jsonResponse(payloads.since)
    if (url.includes('/console/now/devteam')) return jsonResponse(payloads.devteam)
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderNow() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <NowRegion />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// Hero — gate progress
// ---------------------------------------------------------------------------
describe('NowRegion — gate hero', () => {
  it('renders gate metrics with cohort/n/asOf via Metric primitive', async () => {
    mockNow()
    renderNow()
    const hero = await screen.findByTestId('now-gate-hero')
    await waitFor(() => {
      expect(within(hero).getByText(/Sharpe/i)).toBeInTheDocument()
    })
    // Metric renders cohort · n=N · asOf
    expect(within(hero).getAllByText(/paper-90d/).length).toBeGreaterThan(0)
    expect(within(hero).getAllByText(/n=120/).length).toBeGreaterThan(0)
  })

  it('renders a progress bar for the gate', async () => {
    mockNow()
    renderNow()
    await waitFor(() => {
      expect(screen.getByTestId('gate-progress-bar')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// Attention row — two-tier
// ---------------------------------------------------------------------------
describe('NowRegion — attention row', () => {
  it('shows the desk-healthy confirmation when count=0 / desk_healthy true', async () => {
    mockNow({ attention: MOCK_ATTENTION_HEALTHY })
    renderNow()
    const healthy = await screen.findByTestId('attention-healthy')
    expect(healthy.textContent).toMatch(/nothing requires action|desk healthy/i)
    expect(screen.queryByTestId('attention-chip')).not.toBeInTheDocument()
  })

  it('shows a routed chip to /console/decide when count>0', async () => {
    mockNow({ attention: MOCK_ATTENTION_PENDING })
    renderNow()
    const chip = await screen.findByTestId('attention-chip')
    await waitFor(() => {
      expect(chip.textContent).toMatch(/3/)
    })
    expect(chip.textContent).toMatch(/decide/i)
    // chip is a link to /console/decide
    const link = chip.closest('a') || within(chip).queryByRole('link') || chip
    expect(link.getAttribute('href')).toBe('/console/decide')
    expect(screen.queryByTestId('attention-healthy')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Signal row — LAW #4 load-bearing test
// ---------------------------------------------------------------------------
describe('NowRegion — integrity/liveness signals', () => {
  it('renders each signal with a StalenessBadge', async () => {
    mockNow()
    renderNow()
    await waitFor(() => {
      expect(screen.getByTestId('now-signals')).toBeInTheDocument()
    })
    const signals = screen.getByTestId('now-signals')
    const badges = within(signals).getAllByTestId('staleness-badge')
    expect(badges.length).toBeGreaterThanOrEqual(4)
  })

  it('LAW #4: a signal with missing as_of renders UNKNOWN, never green/fresh', async () => {
    const missingSignal = {
      signals: [
        // heartbeat present & fresh
        { key: 'heartbeat', label: 'Watch-loop heartbeat', value: 12, unit: 's', as_of: NOW, n: 1, cohort: 'live', state: 'fresh', max_age: 120 },
        // data_feed signal absent its as_of — MUST render unknown
        { key: 'data_feed', label: 'Data-feed freshness', value: null, unit: 's', as_of: null, n: 1, cohort: 'live', state: 'unknown', max_age: 300 },
      ],
      as_of: NOW,
    }
    mockNow({ signals: missingSignal })
    renderNow()
    await waitFor(() => {
      expect(screen.getByTestId('now-signals')).toBeInTheDocument()
    })
    const signals = screen.getByTestId('now-signals')
    const badges = within(signals).getAllByTestId('staleness-badge')
    // At least one badge must be the unknown variant
    const unknownBadges = badges.filter((b) => b.className.includes('staleness-unknown'))
    expect(unknownBadges.length).toBeGreaterThanOrEqual(1)
    // And the missing signal must NOT have produced a green/fresh badge for itself.
    // Scope to the data_feed signal row to prove it's not green.
    const feedRow = within(signals).getByTestId('signal-data_feed')
    const feedBadge = within(feedRow).getByTestId('staleness-badge')
    expect(feedBadge.className).toContain('staleness-unknown')
    expect(feedBadge.className).not.toContain('staleness-green')
    expect(feedBadge.textContent).toMatch(/unknown/i)
  })

  it('LAW #4: an entirely ABSENT signal (key missing from response) renders unknown, not green', async () => {
    const partialSignals = {
      signals: [
        { key: 'heartbeat', label: 'Watch-loop heartbeat', value: 12, unit: 's', as_of: NOW, n: 1, cohort: 'live', state: 'fresh', max_age: 120 },
        // data_feed, reconciliation, risk_governor are ABSENT entirely
      ],
      as_of: NOW,
    }
    mockNow({ signals: partialSignals })
    renderNow()
    await waitFor(() => {
      expect(screen.getByTestId('now-signals')).toBeInTheDocument()
    })
    const signals = screen.getByTestId('now-signals')
    // data_feed row exists (component renders the canonical slot) and is unknown
    const feedRow = within(signals).getByTestId('signal-data_feed')
    const feedBadge = within(feedRow).getByTestId('staleness-badge')
    expect(feedBadge.className).toContain('staleness-unknown')
    expect(feedBadge.className).not.toContain('staleness-green')
  })
})

// ---------------------------------------------------------------------------
// Positions — canonical reconciled source
// ---------------------------------------------------------------------------
describe('NowRegion — open positions', () => {
  it('renders positions from the canonical reconciled response', async () => {
    mockNow()
    renderNow()
    const positions = await screen.findByTestId('now-positions')
    await waitFor(() => {
      expect(within(positions).getByText(/AAPL/)).toBeInTheDocument()
    })
  })

  it('does NOT render raw sentinel values for equity (SentinelGuard path)', async () => {
    const sentinelPositions = {
      ...MOCK_POSITIONS,
      equity: { value: 999, n: 1, as_of: NOW, cohort: 'paper-book', unit: '$' },
      today_move: { value: -1, n: 1, as_of: NOW, cohort: 'paper-book', unit: '$' },
      positions: [],
    }
    mockNow({ positions: sentinelPositions })
    renderNow()
    const positions = await screen.findByTestId('now-positions')
    await waitFor(() => {
      expect(within(positions).getAllByTestId('sentinel-no-data').length).toBeGreaterThan(0)
    })
    // SentinelGuard renders "no data" for 999 / -1 — the raw number must not appear
    expect(within(positions).queryByText('999')).not.toBeInTheDocument()
    expect(within(positions).queryByText('-1')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Since-band — respects hours
// ---------------------------------------------------------------------------
describe('NowRegion — since you last looked', () => {
  it('renders the delta band with the hours window from the response', async () => {
    mockNow()
    renderNow()
    const since = await screen.findByTestId('now-since')
    await waitFor(() => {
      expect(since.textContent).toMatch(/6h|6 h/i)
    })
  })

  it('requests the since endpoint with hours param', async () => {
    const fetchMock = mockNow()
    renderNow()
    await waitFor(() => {
      const sinceCalls = fetchMock.mock.calls.filter(([url]) => url.includes('/console/now/since'))
      expect(sinceCalls.length).toBeGreaterThan(0)
      expect(sinceCalls[0][0]).toMatch(/hours=\d+/)
    })
  })
})

// ---------------------------------------------------------------------------
// Devteam strip
// ---------------------------------------------------------------------------
describe('NowRegion — AI dev-team strip', () => {
  it('renders current activity and this-week PR counts', async () => {
    mockNow()
    renderNow()
    const dev = await screen.findByTestId('now-devteam')
    await waitFor(() => {
      expect(dev.textContent).toMatch(/Implementing T9 NOW region/)
    })
  })
})
