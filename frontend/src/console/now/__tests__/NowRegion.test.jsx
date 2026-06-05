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

// Authoritative backend contract (see brief):
//   ENV = {value, n, as_of, cohort, unit, state}
//   SIG = {value, n, as_of, state, healthy}
function env(value, extra = {}) {
  return { value, n: 120, as_of: NOW, cohort: 'paper-90d', unit: '', state: 'ok', ...extra }
}

// gate: metrics is a DICT keyed by metric id; targets is a SEPARATE dict; no top-level progress.
const MOCK_GATE = {
  metrics: {
    closed_trade_count: env(48, { unit: '' }),
    excess_sharpe_vs_spy: env(0.31, { unit: '' }),
    sharpe_t_stat: env(1.4, { unit: '' }),
    max_drawdown: env(0.12, { unit: '' }),
  },
  targets: {
    closed_trade_count: 100,
    excess_sharpe_vs_spy: 0.5,
    sharpe_t_stat: 2.0,
    max_drawdown: 0.2,
  },
  as_of: NOW,
}

// attention: pending_count is an ENV (.value = the count), desk_healthy bool.
const MOCK_ATTENTION_HEALTHY = {
  pending_count: { value: 0, n: 1, as_of: NOW, cohort: 'live', unit: '', state: 'ok' },
  desk_healthy: true,
}
const MOCK_ATTENTION_PENDING = {
  pending_count: { value: 3, n: 1, as_of: NOW, cohort: 'live', unit: '', state: 'ok' },
  desk_healthy: false,
}

// signals: a DICT keyed by canonical id; risk_limits (NOT risk_governor). SIG shape.
function sig(value, extra = {}) {
  return { value, n: 1, as_of: NOW, state: 'ok', healthy: true, ...extra }
}
const MOCK_SIGNALS = {
  signals: {
    heartbeat: sig(12),
    data_feed: sig(5),
    reconciliation: sig(0),
    risk_limits: sig(40),
  },
  as_of: NOW,
}

// positions: data_source (NOT source); no equity / today's-move in the response.
const MOCK_POSITIONS = {
  positions: [
    { ticker: 'AAPL', qty: 10, market_value: 1500, unrealized_pnl: 25 },
  ],
  n: 1,
  as_of: NOW,
  data_source: 'reconciled',
  state: 'ok',
}

// since: fields nested under delta; audit_changes (NOT audit_verdict_changes).
const MOCK_SINCE = {
  hours: 6,
  delta: {
    opened: 2,
    closed: 1,
    alerts_raised: 0,
    alerts_resolved: 1,
    audit_changes: 0,
    deploys: 1,
  },
  as_of: NOW,
}

// devteam: activity (NOT current_activity); nested this_week.{prs,regressions,scope_violations}.
const MOCK_DEVTEAM = {
  activity: 'Implementing T9 NOW region',
  this_week: {
    prs: 4,
    regressions: 0,
    scope_violations: 0,
  },
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
      // metrics is a DICT keyed by id — multiple Sharpe-named metrics exist
      expect(within(hero).getAllByText(/Sharpe/i).length).toBeGreaterThan(0)
    })
    // The closed-trade metric (keyed by id) renders its label
    expect(within(hero).getByText(/Closed trades/i)).toBeInTheDocument()
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
      signals: {
        // heartbeat present & fresh
        heartbeat: { value: 12, as_of: NOW, n: 1, state: 'ok', healthy: true },
        // data_feed signal absent its as_of / state unknown — MUST render unknown
        data_feed: { value: null, as_of: null, n: 1, state: 'unknown', healthy: null },
      },
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
      signals: {
        heartbeat: { value: 12, as_of: NOW, n: 1, state: 'ok', healthy: true },
        // data_feed, reconciliation, risk_limits are ABSENT entirely
      },
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

  it('does NOT render raw sentinel values in per-position fields (SentinelGuard path)', async () => {
    const sentinelPositions = {
      positions: [
        { ticker: 'AAPL', qty: 10, market_value: 999, unrealized_pnl: -1 },
      ],
      n: 1,
      as_of: NOW,
      data_source: 'reconciled',
      state: 'ok',
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

  it('equity and today-move render an explicit no-data state (no fabrication)', async () => {
    // The positions endpoint does NOT carry equity/today-move. The UI must
    // render an explicit pending/no-data state for them, never a fabricated value.
    mockNow()
    renderNow()
    const positions = await screen.findByTestId('now-positions')
    await waitFor(() => {
      expect(within(positions).getByText(/AAPL/)).toBeInTheDocument()
    })
    expect(within(positions).getByTestId('equity-no-data')).toBeInTheDocument()
    expect(within(positions).getByTestId('today-move-no-data')).toBeInTheDocument()
  })

  it('renders an explicit unknown/empty state when positions are null / state unknown', async () => {
    const unknownPositions = {
      positions: null,
      n: 0,
      as_of: null,
      data_source: 'reconciled',
      state: 'unknown',
    }
    mockNow({ positions: unknownPositions })
    renderNow()
    const positions = await screen.findByTestId('now-positions')
    await waitFor(() => {
      expect(within(positions).getByTestId('positions-unknown')).toBeInTheDocument()
    })
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
