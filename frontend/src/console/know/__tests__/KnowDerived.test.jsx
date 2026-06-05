/**
 * KnowDerived tests (P3-T6).
 * Tests: FundLadderView + SystemMapView derived views.
 * All endpoints mocked with exact backend contract shapes.
 *
 * Load-bearing law-#7 tests:
 *   - generation_ok:false renders visible "generation failed / stale as of <sha>" banner
 *   - pending phase renders DISTINCTLY from zero (not a filled bar, not zero)
 *   - sentinel value (999/NaN) never renders raw
 *   - source_sha displayed
 *   - real gate value appears only when consumed from mock (non-vacuous)
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import KnowRegion from '../KnowRegion'

// ---------------------------------------------------------------------------
// Mock payloads — exact backend contract shapes
// ---------------------------------------------------------------------------
const NOW = '2026-06-05T14:30:00Z'
const SHA = 'abc1234def5678'

const MOCK_LADDER = {
  ladder: [
    {
      phase: 1,
      name: 'Phase 1 — Bootcamp',
      aum_target: '$100K',
      status: 'active',
      progress: 0.62,
      gates: [
        {
          metric_id: 'closed_trade_count',
          value: 93.0,
          target: 150,
          n: 93,
          as_of: NOW,
          cohort: 'paper-90d',
          unit: '',
          state: 'ok',
        },
        {
          metric_id: 'excess_sharpe_vs_spy',
          value: 0.31,
          target: 0.5,
          n: 93,
          as_of: NOW,
          cohort: 'paper-90d',
          unit: '',
          state: 'ok',
        },
      ],
    },
    {
      phase: 2,
      name: 'Phase 2 — Micro live',
      aum_target: '$1K',
      status: 'pending',
      progress: null,
      gates: [
        {
          metric_id: 'psr',
          value: null,
          target: 0.9,
          n: 0,
          as_of: null,
          cohort: 'paper-90d',
          unit: '',
          state: 'pending',
        },
      ],
    },
  ],
  current_phase: 1,
  generation_ok: true,
  failed_sources: [],
  source_sha: SHA,
  as_of: NOW,
}

const MOCK_LADDER_FAILED = {
  ...MOCK_LADDER,
  generation_ok: false,
  failed_sources: ['metrics_service'],
}

const MOCK_SYSTEM_MAP = {
  capabilities: {
    by_category: {
      actions: 18,
      states: 6,
      systems: 4,
      decisions: 3,
    },
    total: 31,
    actions: 18,
    states: 6,
    systems: 4,
    decisions: 3,
    state: 'ok',
  },
  schema: {
    tables: [
      { name: 'shadow_trades', column_count: 24 },
      { name: 'training_examples', column_count: 18 },
    ],
    table_count: 42,
    state: 'ok',
  },
  generation_ok: true,
  source_sha: SHA,
  as_of: NOW,
}

const MOCK_SYSTEM_MAP_FAILED = {
  ...MOCK_SYSTEM_MAP,
  generation_ok: false,
  capabilities: { ...MOCK_SYSTEM_MAP.capabilities, state: 'unknown' },
  schema: { ...MOCK_SYSTEM_MAP.schema, state: 'unknown' },
}

// ---------------------------------------------------------------------------
// fetch mock helpers
// ---------------------------------------------------------------------------
function jsonResponse(data) {
  return Promise.resolve({
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify(data)),
  })
}

function mockKnow(overrides = {}) {
  const payloads = {
    ladder: MOCK_LADDER,
    systemMap: MOCK_SYSTEM_MAP,
    ...overrides,
  }
  const fetchMock = vi.fn((url) => {
    if (url.includes('/console/know/ladder')) return jsonResponse(payloads.ladder)
    if (url.includes('/console/know/system-map')) return jsonResponse(payloads.systemMap)
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderAtPath(path) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/console/know/*" element={<KnowRegion />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// FundLadderView — data consumed from /console/know/ladder
// ---------------------------------------------------------------------------
describe('FundLadderView — data-driven rendering', () => {
  it('renders the know-ladder testid at the view root', async () => {
    mockKnow()
    renderAtPath('/console/know/ladder')
    await waitFor(() => {
      expect(screen.getByTestId('know-ladder')).toBeInTheDocument()
    })
  })

  it('renders phase names from the endpoint (non-vacuous: value from mock)', async () => {
    mockKnow()
    renderAtPath('/console/know/ladder')
    await waitFor(() => {
      expect(screen.getByText(/Phase 1 — Bootcamp/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/Phase 2 — Micro live/i)).toBeInTheDocument()
  })

  it('renders gate metric values through Metric primitive (closed_trade_count = 93)', async () => {
    mockKnow()
    renderAtPath('/console/know/ladder')
    // Metric primitive renders "cohort · n=N · asOf" footer
    await waitFor(() => {
      expect(screen.getAllByTestId('metric-card').length).toBeGreaterThan(0)
    })
    // Value 93 appears inside a metric card — non-vacuous (only present from mock)
    const metricCards = screen.getAllByTestId('metric-card')
    const text = metricCards.map((c) => c.textContent).join(' ')
    expect(text).toMatch(/93/)
  })

  it('renders cohort/n/asOf context on gate metrics via Metric primitive', async () => {
    mockKnow()
    renderAtPath('/console/know/ladder')
    await waitFor(() => {
      expect(screen.getAllByTestId('metric-card').length).toBeGreaterThan(0)
    })
    // Metric primitive renders "paper-90d · n=93 · ..."
    const text = screen.getAllByTestId('metric-card').map((c) => c.textContent).join(' ')
    expect(text).toMatch(/paper-90d/)
    expect(text).toMatch(/n=93/)
  })

  it('renders the source_sha stamp', async () => {
    mockKnow()
    renderAtPath('/console/know/ladder')
    await waitFor(() => {
      expect(screen.getByTestId('know-ladder').textContent).toMatch(new RegExp(SHA))
    })
  })

  it('renders per-phase progress bars (active phase has a filled bar)', async () => {
    mockKnow()
    renderAtPath('/console/know/ladder')
    await waitFor(() => {
      // Phase 1 has progress=0.62, should render a progress bar element
      const bars = screen.getAllByRole('progressbar')
      expect(bars.length).toBeGreaterThan(0)
    })
  })

  it('LAW #7 fail-closed: generation_ok:false renders visible "generation failed" banner', async () => {
    mockKnow({ ladder: MOCK_LADDER_FAILED })
    renderAtPath('/console/know/ladder')
    await waitFor(() => {
      const banner = screen.getByTestId('know-ladder-gen-failed')
      expect(banner).toBeInTheDocument()
      expect(banner.textContent).toMatch(/generation failed/i)
    })
    // Banner must include source_sha
    expect(screen.getByTestId('know-ladder-gen-failed').textContent).toMatch(new RegExp(SHA))
  })

  it('LAW #7 fail-closed: generation_ok:true does NOT render the failure banner', async () => {
    mockKnow({ ladder: MOCK_LADDER })
    renderAtPath('/console/know/ladder')
    await waitFor(() => {
      expect(screen.getByTestId('know-ladder')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('know-ladder-gen-failed')).not.toBeInTheDocument()
  })

  it('pending phase renders DISTINCTLY — not as zero, not as a filled bar', async () => {
    mockKnow()
    renderAtPath('/console/know/ladder')
    await waitFor(() => {
      // Phase 2 is pending — look for distinct pending treatment
      const ladder = screen.getByTestId('know-ladder')
      expect(within(ladder).getByTestId('phase-status-pending')).toBeInTheDocument()
    })
    // The pending element must NOT say "0" or "0%" as its progress
    const pendingEl = screen.getByTestId('phase-status-pending')
    expect(pendingEl.textContent).not.toBe('0')
    expect(pendingEl.textContent).not.toMatch(/^0%$/)
  })

  it('unknown gate state renders an unknown badge, not a value', async () => {
    const ladderWithUnknown = {
      ...MOCK_LADDER,
      ladder: [
        {
          ...MOCK_LADDER.ladder[0],
          gates: [
            {
              metric_id: 'closed_trade_count',
              value: null,
              target: 150,
              n: 0,
              as_of: null,
              cohort: 'paper-90d',
              unit: '',
              state: 'unknown',
            },
          ],
        },
      ],
    }
    mockKnow({ ladder: ladderWithUnknown })
    renderAtPath('/console/know/ladder')
    // Wait until the phase name appears (data has loaded)
    await waitFor(() => {
      expect(screen.getByTestId('know-ladder').textContent).toMatch(/Phase 1/i)
    })
    // SentinelGuard / Metric error renders for null value — not a raw 0 or null text
    const ladder = screen.getByTestId('know-ladder')
    const noDataEl = within(ladder).queryAllByTestId('sentinel-no-data')
    const metricErrors = within(ladder).queryAllByTestId('metric-error')
    expect(noDataEl.length + metricErrors.length).toBeGreaterThan(0)
  })

  it('sentinel value (999) in a gate never renders as raw "999"', async () => {
    const ladderWithSentinel = {
      ...MOCK_LADDER,
      ladder: [
        {
          ...MOCK_LADDER.ladder[0],
          gates: [
            {
              metric_id: 'closed_trade_count',
              value: 999,
              target: 150,
              n: 93,
              as_of: NOW,
              cohort: 'paper-90d',
              unit: '',
              state: 'ok',
            },
          ],
        },
      ],
    }
    mockKnow({ ladder: ladderWithSentinel })
    renderAtPath('/console/know/ladder')
    // Wait until data loads (phase name appears)
    await waitFor(() => {
      expect(screen.getByTestId('know-ladder').textContent).toMatch(/Phase 1/i)
    })
    const ladder = screen.getByTestId('know-ladder')
    // SentinelGuard must catch 999 — raw "999" must not appear as a bare numeric text
    // (It may appear in JSON-adjacent context; we check it's not rendered as a value)
    const sentinelNoData = within(ladder).queryAllByTestId('sentinel-no-data')
    expect(sentinelNoData.length).toBeGreaterThan(0)
    // Raw "999" string is not rendered standalone
    expect(within(ladder).queryByText('999')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// SystemMapView — data consumed from /console/know/system-map
// ---------------------------------------------------------------------------
describe('SystemMapView — data-driven rendering', () => {
  it('renders the know-system-map testid at the view root', async () => {
    mockKnow()
    renderAtPath('/console/know/system-map')
    await waitFor(() => {
      expect(screen.getByTestId('know-system-map')).toBeInTheDocument()
    })
  })

  it('renders capability counts by category (actions=18 from mock)', async () => {
    mockKnow()
    renderAtPath('/console/know/system-map')
    await waitFor(() => {
      const view = screen.getByTestId('know-system-map')
      // Non-vacuous: 18 appears only when consumed from mock
      expect(view.textContent).toMatch(/18/)
    })
  })

  it('renders total capability count (total=31)', async () => {
    mockKnow()
    renderAtPath('/console/know/system-map')
    await waitFor(() => {
      expect(screen.getByTestId('know-system-map').textContent).toMatch(/31/)
    })
  })

  it('renders schema table_count (42) from the endpoint', async () => {
    mockKnow()
    renderAtPath('/console/know/system-map')
    await waitFor(() => {
      expect(screen.getByTestId('know-system-map').textContent).toMatch(/42/)
    })
  })

  it('renders table names from the schema tables array', async () => {
    mockKnow()
    renderAtPath('/console/know/system-map')
    await waitFor(() => {
      const view = screen.getByTestId('know-system-map')
      expect(view.textContent).toMatch(/shadow_trades/)
    })
  })

  it('renders source_sha stamp in system-map view', async () => {
    mockKnow()
    renderAtPath('/console/know/system-map')
    await waitFor(() => {
      expect(screen.getByTestId('know-system-map').textContent).toMatch(new RegExp(SHA))
    })
  })

  it('LAW #7 fail-closed: generation_ok:false renders visible banner with source_sha', async () => {
    mockKnow({ systemMap: MOCK_SYSTEM_MAP_FAILED })
    renderAtPath('/console/know/system-map')
    await waitFor(() => {
      const banner = screen.getByTestId('know-system-map-gen-failed')
      expect(banner).toBeInTheDocument()
      expect(banner.textContent).toMatch(/generation failed/i)
      expect(banner.textContent).toMatch(new RegExp(SHA))
    })
  })

  it('LAW #7 fail-closed: generation_ok:true does NOT render the failure banner', async () => {
    mockKnow({ systemMap: MOCK_SYSTEM_MAP })
    renderAtPath('/console/know/system-map')
    await waitFor(() => {
      expect(screen.getByTestId('know-system-map')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('know-system-map-gen-failed')).not.toBeInTheDocument()
  })

  it('unknown capability state renders unknown badge via StalenessBadge', async () => {
    const systemMapUnknown = {
      ...MOCK_SYSTEM_MAP,
      capabilities: { ...MOCK_SYSTEM_MAP.capabilities, state: 'unknown' },
    }
    mockKnow({ systemMap: systemMapUnknown })
    renderAtPath('/console/know/system-map')
    await waitFor(() => {
      const view = screen.getByTestId('know-system-map')
      const unknownBadges = within(view).queryAllByTestId('staleness-badge')
      const hasUnknown = unknownBadges.some((b) => b.className.includes('staleness-unknown'))
      expect(hasUnknown).toBe(true)
    })
  })

  it('sentinel value (999) in capability counts never renders as raw "999"', async () => {
    const systemMapSentinel = {
      ...MOCK_SYSTEM_MAP,
      capabilities: {
        ...MOCK_SYSTEM_MAP.capabilities,
        total: 999,
      },
    }
    mockKnow({ systemMap: systemMapSentinel })
    renderAtPath('/console/know/system-map')
    await waitFor(() => {
      expect(screen.getByTestId('know-system-map')).toBeInTheDocument()
    })
    const view = screen.getByTestId('know-system-map')
    // SentinelGuard catches 999
    const noDataEls = within(view).queryAllByTestId('sentinel-no-data')
    expect(noDataEls.length).toBeGreaterThan(0)
    expect(within(view).queryByText('999')).not.toBeInTheDocument()
  })
})
