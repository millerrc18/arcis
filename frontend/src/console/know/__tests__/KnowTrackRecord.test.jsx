/**
 * KnowTrackRecord tests (P3-T7).
 * TDD — written before TrackRecordView / TradeLedgersView implementation.
 * Non-vacuous: each stat value appears in assertions only when the component
 * actually consumes the mocked response.
 *
 * Contracts consumed (verbatim from spec):
 *   GET /console/know/track-record
 *   GET /console/know/ledgers?status=open|closed|all&q=<search>&limit=N
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import KnowRegion from '../KnowRegion'

// ---------------------------------------------------------------------------
// Frozen backend contract shapes (verbatim from spec)
// ---------------------------------------------------------------------------
const NOW = '2026-06-05T14:30:00Z'

const MOCK_TRACK_RECORD = {
  metrics: {
    rf_adjusted_sharpe: {
      value: 1.42,
      n: 120,
      as_of: NOW,
      cohort: 'paper-90d',
      unit: '',
      state: 'ok',
    },
    excess_sharpe_vs_spy: {
      value: 0.31,
      n: 120,
      as_of: NOW,
      cohort: 'paper-90d',
      unit: '',
      state: 'ok',
    },
    win_rate: {
      value: 0.58,
      n: 120,
      as_of: NOW,
      cohort: 'paper-90d',
      unit: '',
      state: 'ok',
    },
    max_drawdown: {
      value: 0.12,
      n: 120,
      as_of: NOW,
      cohort: 'paper-90d',
      unit: '',
      state: 'ok',
    },
    closed_trade_count: {
      value: 87,
      n: 120,
      as_of: NOW,
      cohort: 'paper-90d',
      unit: '',
      state: 'ok',
    },
    psr: {
      value: 0.78,
      n: 120,
      as_of: NOW,
      cohort: 'paper-90d',
      unit: '',
      state: 'ok',
    },
    dsr: {
      value: 0.91,
      n: 120,
      as_of: NOW,
      cohort: 'paper-90d',
      unit: '',
      state: 'ok',
    },
    profit_factor: {
      value: 1.65,
      n: 120,
      as_of: NOW,
      cohort: 'paper-90d',
      unit: '',
      state: 'ok',
    },
    expectancy: {
      value: 42.5,
      n: 120,
      as_of: NOW,
      cohort: 'paper-90d',
      unit: '',
      state: 'ok',
    },
  },
  unavailable: [],
  equity_curve: [
    { t: '2026-03-01', equity: 100000 },
    { t: '2026-04-01', equity: 104200 },
    { t: '2026-05-01', equity: 108750 },
  ],
  cto_report_link: '/api/cto-report',
  as_of: NOW,
}

const MOCK_TRACK_RECORD_NO_DATA_METRIC = {
  ...MOCK_TRACK_RECORD,
  metrics: {
    ...MOCK_TRACK_RECORD.metrics,
    // no_data state — must not render 0 or blank
    rf_adjusted_sharpe: {
      value: null,
      n: 0,
      as_of: null,
      cohort: null,
      unit: '',
      state: 'no_data',
    },
  },
}

const MOCK_TRACK_RECORD_NULL_CURVE = {
  ...MOCK_TRACK_RECORD,
  equity_curve: null,
}

const MOCK_LEDGERS_OPEN = {
  rows: [
    {
      trade_id: 't1',
      ticker: 'AAPL',
      pnl_dollars: 125.5,
      pnl_pct: 0.84,
      status: 'open',
    },
    {
      trade_id: 't2',
      ticker: 'MSFT',
      pnl_dollars: -42.0,
      pnl_pct: -0.21,
      status: 'open',
    },
  ],
  n: 2,
  status: 'open',
  as_of: NOW,
  state: 'ok',
}

const MOCK_LEDGERS_CLOSED = {
  rows: [
    {
      trade_id: 't3',
      ticker: 'NVDA',
      pnl_dollars: 310.0,
      pnl_pct: 2.1,
      status: 'closed',
    },
  ],
  n: 1,
  status: 'closed',
  as_of: NOW,
  state: 'ok',
}

const MOCK_LEDGERS_ALL = {
  rows: [
    ...MOCK_LEDGERS_OPEN.rows,
    ...MOCK_LEDGERS_CLOSED.rows,
  ],
  n: 3,
  status: 'all',
  as_of: NOW,
  state: 'ok',
}

const MOCK_LEDGERS_SEARCH = {
  rows: [
    {
      trade_id: 't2',
      ticker: 'MSFT',
      pnl_dollars: -42.0,
      pnl_pct: -0.21,
      status: 'open',
    },
  ],
  n: 1,
  status: 'open',
  as_of: NOW,
  state: 'ok',
}

const MOCK_LEDGERS_NO_DATA = {
  rows: [],
  n: 0,
  status: 'open',
  as_of: NOW,
  state: 'no_data',
}

const MOCK_LEDGERS_SENTINEL = {
  rows: [
    {
      trade_id: 't5',
      ticker: 'TSLA',
      pnl_dollars: 999,  // sentinel value
      pnl_pct: -1,       // sentinel value
      status: 'open',
    },
  ],
  n: 1,
  status: 'open',
  as_of: NOW,
  state: 'ok',
}

// ---------------------------------------------------------------------------
// Fetch mock helpers
// ---------------------------------------------------------------------------
function jsonResponse(data) {
  return Promise.resolve({
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify(data)),
  })
}

function mockKnow({ trackRecord = MOCK_TRACK_RECORD, ledgers = null } = {}) {
  const fetchMock = vi.fn((url) => {
    if (url.includes('/console/know/track-record')) return jsonResponse(trackRecord)
    if (url.includes('/console/know/ledgers')) {
      // If a fixed ledgers override is provided, always return it
      if (ledgers !== null) return jsonResponse(ledgers)
      const urlObj = new URL(url, 'http://localhost')
      const status = urlObj.searchParams.get('status') || 'open'
      const q = urlObj.searchParams.get('q') || ''
      if (q) return jsonResponse(MOCK_LEDGERS_SEARCH)
      if (status === 'closed') return jsonResponse(MOCK_LEDGERS_CLOSED)
      if (status === 'all') return jsonResponse(MOCK_LEDGERS_ALL)
      return jsonResponse(MOCK_LEDGERS_OPEN)
    }
    // Other KNOW endpoints
    if (url.includes('/console/know/ladder')) return jsonResponse({ ladder: [], generation_ok: true, source_sha: '', as_of: NOW })
    if (url.includes('/console/know/system-map')) return jsonResponse({ generation_ok: true, source_sha: '', as_of: NOW })
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

// ---------------------------------------------------------------------------
// Render helpers
// ---------------------------------------------------------------------------
function renderKnow(initialPath = '/console/know/track-record') {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
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
// TrackRecordView — headline metrics
// ---------------------------------------------------------------------------
describe('TrackRecordView — headline metrics', () => {
  it('renders data-testid="know-track-record" container', async () => {
    mockKnow()
    renderKnow('/console/know/track-record')
    await waitFor(() => {
      expect(screen.getByTestId('know-track-record')).toBeInTheDocument()
    })
  })

  it('renders the Sharpe metric with cohort/n/asOf via Metric primitive (non-vacuous: 1.42)', async () => {
    mockKnow()
    renderKnow('/console/know/track-record')
    const view = await screen.findByTestId('know-track-record')
    await waitFor(() => {
      expect(within(view).getByText('1.42')).toBeInTheDocument()
    })
    // Metric renders cohort · n=N · asOf line
    expect(within(view).getAllByText(/paper-90d/).length).toBeGreaterThan(0)
    expect(within(view).getAllByText(/n=120/).length).toBeGreaterThan(0)
  })

  it('renders all 8 headline stats: Sharpe, excess-Sharpe, PSR, win rate, profit factor, max DD, expectancy, closed-trade count', async () => {
    mockKnow()
    renderKnow('/console/know/track-record')
    const view = await screen.findByTestId('know-track-record')
    await waitFor(() => {
      // Each metric card has data-testid="metric-card" or label text
      expect(within(view).getAllByText(/rf_adjusted_sharpe/i).length).toBeGreaterThan(0)
      expect(within(view).getAllByText(/excess_sharpe_vs_spy/i).length).toBeGreaterThan(0)
      expect(within(view).getAllByText(/psr/i).length).toBeGreaterThan(0)
      expect(within(view).getAllByText(/win_rate/i).length).toBeGreaterThan(0)
      expect(within(view).getAllByText(/profit_factor/i).length).toBeGreaterThan(0)
      expect(within(view).getAllByText(/max_drawdown/i).length).toBeGreaterThan(0)
      expect(within(view).getAllByText(/expectancy/i).length).toBeGreaterThan(0)
      expect(within(view).getAllByText(/closed_trade_count/i).length).toBeGreaterThan(0)
    })
  })

  it('renders the mocked Sharpe value (1.42) — proves non-vacuousness', async () => {
    mockKnow()
    renderKnow('/console/know/track-record')
    const view = await screen.findByTestId('know-track-record')
    await waitFor(() => {
      expect(within(view).getByText('1.42')).toBeInTheDocument()
    })
  })

  it('no_data state: renders no-data treatment, NOT zero (law: no_data ≠ zero)', async () => {
    mockKnow({ trackRecord: MOCK_TRACK_RECORD_NO_DATA_METRIC })
    renderKnow('/console/know/track-record')
    const view = await screen.findByTestId('know-track-record')
    await waitFor(() => {
      // When state is no_data with null cohort/n/asOf, Metric renders metric-error
      // or SentinelGuard renders no-data — not the literal value "0"
      const metricErrors = within(view).queryAllByTestId('metric-error')
      const sentinelNoDatas = within(view).queryAllByTestId('sentinel-no-data')
      expect(metricErrors.length + sentinelNoDatas.length).toBeGreaterThan(0)
    })
    // Zero must not appear as the Sharpe value (no_data ≠ zero)
    // There shouldn't be a sentinel-value showing "0" in place of the missing Sharpe
    const sentinelValues = screen.queryAllByTestId('sentinel-value')
    const zeroValues = sentinelValues.filter(el => el.textContent === '0')
    expect(zeroValues.length).toBe(0)
  })

  it('stat with missing cohort renders metric-error (Metric primitive guard)', async () => {
    const noCohortRecord = {
      ...MOCK_TRACK_RECORD,
      metrics: {
        ...MOCK_TRACK_RECORD.metrics,
        rf_adjusted_sharpe: {
          value: 1.42,
          n: 120,
          as_of: NOW,
          cohort: null,   // missing cohort — Metric must render error
          unit: '',
          state: 'ok',
        },
      },
    }
    mockKnow({ trackRecord: noCohortRecord })
    renderKnow('/console/know/track-record')
    const view = await screen.findByTestId('know-track-record')
    await waitFor(() => {
      expect(within(view).getByTestId('metric-error')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// TrackRecordView — unavailable list
// ---------------------------------------------------------------------------
describe('TrackRecordView — unavailable metrics', () => {
  it('F6: DSR is in metrics dict — "dsr not available" item does NOT appear in the UI', async () => {
    mockKnow()
    renderKnow('/console/know/track-record')
    const view = await screen.findByTestId('know-track-record')
    // Give queries time to resolve
    await waitFor(() => {
      // Unavailable section for dsr must be absent — backend moved dsr from unavailable to metrics
      expect(within(view).queryByTestId('know-track-record-unavailable-dsr')).not.toBeInTheDocument()
    })
  })

  it('F6: no "dsr not available" text rendered when dsr is in the metrics dict (not in unavailable [])', async () => {
    mockKnow()
    renderKnow('/console/know/track-record')
    const view = await screen.findByTestId('know-track-record')
    await waitFor(() => {
      // unavailable array is [] so the whole "Not available" section is absent
      expect(within(view).queryByTestId('know-track-record-unavailable-dsr')).not.toBeInTheDocument()
      // The text "dsr: not available" must not appear
      expect(within(view).queryByText(/dsr.*not available/i)).not.toBeInTheDocument()
    })
  })

  it('F6: DSR is rendered as a headline metric TILE (value 0.91, label dsr) — workstream #1 end-to-end', async () => {
    mockKnow()
    renderKnow('/console/know/track-record')
    const view = await screen.findByTestId('know-track-record')
    await waitFor(() => {
      // 'dsr' is now in HEADLINE_STAT_IDS, so the backend-delivered dsr metric
      // renders as a real tile (label + value), not silently dropped.
      expect(within(view).getAllByText(/dsr/i).length).toBeGreaterThan(0)
      expect(within(view).getByText('0.91')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// TrackRecordView — equity curve
// ---------------------------------------------------------------------------
describe('TrackRecordView — equity curve', () => {
  it('renders equity curve chart when equity_curve is present', async () => {
    mockKnow()
    renderKnow('/console/know/track-record')
    const view = await screen.findByTestId('know-track-record')
    await waitFor(() => {
      expect(within(view).getByTestId('know-track-record-equity-curve')).toBeInTheDocument()
    })
  })

  it('renders honest empty state when equity_curve is null', async () => {
    mockKnow({ trackRecord: MOCK_TRACK_RECORD_NULL_CURVE })
    renderKnow('/console/know/track-record')
    const view = await screen.findByTestId('know-track-record')
    await waitFor(() => {
      expect(within(view).getByTestId('know-track-record-no-curve')).toBeInTheDocument()
    })
    // Must NOT render the chart container when curve is null
    expect(within(view).queryByTestId('know-track-record-equity-curve')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// TrackRecordView — CTO report link
// ---------------------------------------------------------------------------
describe('TrackRecordView — CTO report link', () => {
  it('renders a link to the CTO report via cto_report_link', async () => {
    mockKnow()
    renderKnow('/console/know/track-record')
    const view = await screen.findByTestId('know-track-record')
    await waitFor(() => {
      const link = within(view).getByTestId('know-track-record-cto-link')
      expect(link).toBeInTheDocument()
      expect(link.getAttribute('href')).toBe('/api/cto-report')
    })
  })
})

// ---------------------------------------------------------------------------
// TradeLedgersView — container + tab rendering
// ---------------------------------------------------------------------------
describe('TradeLedgersView — container', () => {
  it('renders data-testid="know-ledgers" container', async () => {
    mockKnow()
    renderKnow('/console/know/ledgers')
    await waitFor(() => {
      expect(screen.getByTestId('know-ledgers')).toBeInTheDocument()
    })
  })

  it('renders open trades rows for default tab (AAPL, MSFT)', async () => {
    mockKnow()
    renderKnow('/console/know/ledgers')
    const view = await screen.findByTestId('know-ledgers')
    await waitFor(() => {
      expect(within(view).getByText('AAPL')).toBeInTheDocument()
      expect(within(view).getByText('MSFT')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// TradeLedgersView — tab switching drives status param
// ---------------------------------------------------------------------------
describe('TradeLedgersView — tab switching', () => {
  it('clicking "closed" tab fetches /console/know/ledgers with status=closed', async () => {
    const fetchMock = mockKnow()
    renderKnow('/console/know/ledgers')
    await screen.findByTestId('know-ledgers')

    // Click the "closed" tab
    const closedTab = await screen.findByTestId('know-ledgers-tab-closed')
    fireEvent.click(closedTab)

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map(([url]) => url)
      const closedCalls = calls.filter(u => u.includes('/console/know/ledgers') && u.includes('status=closed'))
      expect(closedCalls.length).toBeGreaterThan(0)
    })
  })

  it('clicking "all" tab fetches /console/know/ledgers with status=all and shows NVDA from closed', async () => {
    const fetchMock = mockKnow()
    renderKnow('/console/know/ledgers')
    await screen.findByTestId('know-ledgers')

    const allTab = await screen.findByTestId('know-ledgers-tab-all')
    fireEvent.click(allTab)

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map(([url]) => url)
      const allCalls = calls.filter(u => u.includes('/console/know/ledgers') && u.includes('status=all'))
      expect(allCalls.length).toBeGreaterThan(0)
    })

    const view = screen.getByTestId('know-ledgers')
    await waitFor(() => {
      expect(within(view).getByText('NVDA')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// TradeLedgersView — search box drives q param
// ---------------------------------------------------------------------------
describe('TradeLedgersView — search', () => {
  it('typing in the search box fetches with q param', async () => {
    const fetchMock = mockKnow()
    renderKnow('/console/know/ledgers')
    await screen.findByTestId('know-ledgers')

    const searchBox = await screen.findByTestId('know-ledgers-search')
    fireEvent.change(searchBox, { target: { value: 'MSFT' } })

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map(([url]) => url)
      const searchCalls = calls.filter(u => u.includes('/console/know/ledgers') && u.includes('q=MSFT'))
      expect(searchCalls.length).toBeGreaterThan(0)
    })
  })
})

// ---------------------------------------------------------------------------
// TradeLedgersView — StalenessBadge on as_of
// ---------------------------------------------------------------------------
describe('TradeLedgersView — staleness badge', () => {
  it('renders a StalenessBadge on the ledger as_of field', async () => {
    mockKnow()
    renderKnow('/console/know/ledgers')
    const view = await screen.findByTestId('know-ledgers')
    await waitFor(() => {
      expect(within(view).getByTestId('staleness-badge')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// TradeLedgersView — no_data state treatment
// ---------------------------------------------------------------------------
describe('TradeLedgersView — no_data state', () => {
  it('renders honest no-data state when state=no_data (not an empty table with 0)', async () => {
    mockKnow({ ledgers: MOCK_LEDGERS_NO_DATA })
    renderKnow('/console/know/ledgers')
    const view = await screen.findByTestId('know-ledgers')
    await waitFor(() => {
      expect(within(view).getByTestId('know-ledgers-no-data')).toBeInTheDocument()
    })
    // Must not render "0 trades" or similar fabricated zero
    expect(within(view).queryByText(/^0$/)).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// SentinelGuard path — no raw sentinel in ledger rows
// ---------------------------------------------------------------------------
describe('TradeLedgersView — SentinelGuard', () => {
  it('does NOT render raw sentinel value 999 or -1 in ledger row fields', async () => {
    mockKnow({ ledgers: MOCK_LEDGERS_SENTINEL })
    renderKnow('/console/know/ledgers')
    const view = await screen.findByTestId('know-ledgers')
    await waitFor(() => {
      expect(within(view).getByText('TSLA')).toBeInTheDocument()
    })
    // SentinelGuard renders "no data" for 999 / -1, not the raw number
    const sentinelNoDatas = within(view).queryAllByTestId('sentinel-no-data')
    expect(sentinelNoDatas.length).toBeGreaterThan(0)
    expect(within(view).queryByText('999')).not.toBeInTheDocument()
    expect(within(view).queryByText('-1')).not.toBeInTheDocument()
  })
})
