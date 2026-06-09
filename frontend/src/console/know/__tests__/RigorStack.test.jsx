/**
 * RigorStack tests (P3-T8 + F6).
 * Three sub-views: Validation (PSR/DSR/PBO via /system/validation + /console/know/rigor-metrics),
 * Walkforward (OOS windows via /walkforward/runs + /windows + /trades),
 * Stress Test (scenarios via /stress-test/results).
 *
 * F6: /console/know/rigor-metrics (BARE path) — PSR/DSR/PBO envelopes.
 *
 * Mirrors NowRegion test idiom: MemoryRouter + QueryClientProvider, mock fetchApi.
 * Mocks mirror the REAL route handler shapes (read from walkforward.py + analytics.py).
 * Non-vacuous: mocked values appear only when the component consumes them.
 * Law #3: no raw sentinel ever renders.
 * Law #7: no-data states are honest (never green on empty).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import RigorStack from '../RigorStack'

// ---------------------------------------------------------------------------
// Mock payloads — shapes derived from actual route handlers
// ---------------------------------------------------------------------------
//
// /api/walkforward/runs (walkforward.py:63-93)
//   returns { runs: [...], count: N }
//   each run: { run_id, strategy_id, outcome_state, reason, pooled_sharpe,
//               pooled_mde, heavy_tail_flag, n_windows, n_windows_pass,
//               n_windows_fail, n_windows_inconclusive_data,
//               n_windows_inconclusive_power, n_windows_inconclusive_duration,
//               created_at, ... }
//
// /api/walkforward/runs/{run_id}/windows (walkforward.py:108-137)
//   returns { run_id, outcome_state, windows: [...], count: N }
//   each window: { window_index, n_trades, sharpe, mde, bootstrap_se, distinct_vix_tiers }
//
// /api/walkforward/runs/{run_id}/trades (walkforward.py:140-170)
//   returns { trades: [...], count: N }
//   each trade: { trade_id, window_index, ticker, entry_date, exit_date,
//                 pnl_pct, excess_return, exit_reason, hold_days, vix_at_entry,
//                 vix_tier, sharpe_observed, bootstrap_se, mde_value }
//
// /api/stress-test/results (analytics.py:921-943)
//   returns { results: [...], _meta: {...} }
//   each result: { result_id, scenario, start_date, end_date, total_trades,
//                  win_rate, max_drawdown_pct, calmar_ratio,
//                  monthly_returns_json, regime_breakdown_json, equity_curve_json,
//                  created_at }
//
// /api/system/validation (Validation.jsx: api.getValidation() → fetchApi('/system/validation'))
//   returns { overall_status, checks_passed, checks_warning, checks_failed,
//             checks_total, timestamp, categories: { [name]: [{status, name, detail}] } }

const NOW = '2026-06-08T10:00:00Z'

// ---------------------------------------------------------------------------
// F6: /console/know/rigor-metrics frozen backend contract shapes
// ---------------------------------------------------------------------------
const MOCK_RIGOR_METRICS_OK = {
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
  pbo: {
    value: null,
    n: 0,
    as_of: NOW,
    cohort: null,
    unit: '',
    state: 'insufficient_configs',
  },
  as_of: NOW,
}

const MOCK_RIGOR_METRICS_NO_DATA = {
  psr: { value: null, n: 0, as_of: null, cohort: null, unit: '', state: 'no_data' },
  dsr: { value: null, n: 0, as_of: null, cohort: null, unit: '', state: 'no_data' },
  pbo: { value: null, n: 0, as_of: null, cohort: null, unit: '', state: 'insufficient_configs' },
  as_of: null,
}

const MOCK_RUN_ID = 'run-abc-123-def'

const MOCK_WF_RUNS = {
  runs: [
    {
      run_id: MOCK_RUN_ID,
      strategy_id: 'pullback_v2',
      outcome_state: 'PASS',
      reason: 'All five criteria satisfied',
      pooled_sharpe: 1.423,
      pooled_mde: 0.082,
      heavy_tail_flag: false,
      heavy_tail_window_count: 0,
      n_windows: 8,
      n_windows_pass: 7,
      n_windows_fail: 1,
      n_windows_inconclusive_data: 0,
      n_windows_inconclusive_power: 0,
      n_windows_inconclusive_duration: 0,
      derived_from_source_type: 'historical',
      effective_universe_size: 50,
      max_drawdown_pct: 8.2,
      vix_tier_coverage: 3,
      gate_version: 'v1',
      excess_sharpe_min_used: 0.3,
      created_at: NOW,
    },
  ],
  count: 1,
}

const MOCK_WF_WINDOWS = {
  run_id: MOCK_RUN_ID,
  outcome_state: 'PASS',
  windows: [
    {
      window_index: 0,
      n_trades: 42,
      sharpe: 1.234,
      mde: 0.075,
      bootstrap_se: 0.031,
      distinct_vix_tiers: 2,
    },
    {
      window_index: 1,
      n_trades: 38,
      sharpe: 1.519,
      mde: 0.089,
      bootstrap_se: 0.028,
      distinct_vix_tiers: 3,
    },
  ],
  count: 2,
}

const MOCK_WF_TRADES = {
  trades: [
    {
      trade_id: 't-001',
      window_index: 0,
      ticker: 'NVDA',
      entry_date: '2023-01-10',
      exit_date: '2023-01-15',
      pnl_pct: 0.0312,
      excess_return: 0.0201,
      exit_reason: 'target_1_hit',
      hold_days: 5,
      vix_at_entry: 22.4,
      vix_tier: 'low',
      purged: 0,
      embargoed: 0,
      sharpe_observed: 1.2,
      bootstrap_se: 0.03,
      mde_value: 0.07,
    },
  ],
  count: 1,
}

const MOCK_STRESS = {
  results: [
    {
      result_id: 'stress-001',
      scenario: '2008_financial_crisis',
      start_date: '2008-09-01',
      end_date: '2009-03-31',
      total_trades: 120,
      win_rate: 0.48,
      max_drawdown_pct: 18.5,
      calmar_ratio: 0.72,
      monthly_returns_json: null,
      regime_breakdown_json: null,
      equity_curve_json: null,
      created_at: NOW,
    },
    {
      result_id: 'stress-002',
      scenario: '2020_covid_crash',
      start_date: '2020-02-01',
      end_date: '2020-04-30',
      total_trades: 88,
      win_rate: 0.53,
      max_drawdown_pct: 12.1,
      calmar_ratio: 1.05,
      monthly_returns_json: null,
      regime_breakdown_json: null,
      equity_curve_json: null,
      created_at: NOW,
    },
  ],
  _meta: { cohort: 'stress.scenario', n: 2 },
}

const MOCK_VALIDATION = {
  overall_status: 'healthy',
  checks_passed: 28,
  checks_warning: 2,
  checks_failed: 0,
  checks_total: 30,
  timestamp: NOW,
  categories: {
    database: [
      { status: 'pass', name: 'db_connection', detail: 'Connected' },
    ],
    trading: [
      { status: 'warn', name: 'heartbeat', detail: 'Heartbeat 12 min ago' },
    ],
  },
}

// ---------------------------------------------------------------------------
// fetch mock
// ---------------------------------------------------------------------------
function jsonResponse(data) {
  return Promise.resolve({
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify(data)),
  })
}

function mockRigor(overrides = {}) {
  const payloads = {
    wfRuns: MOCK_WF_RUNS,
    wfWindows: MOCK_WF_WINDOWS,
    wfTrades: MOCK_WF_TRADES,
    stress: MOCK_STRESS,
    validation: MOCK_VALIDATION,
    rigorMetrics: MOCK_RIGOR_METRICS_OK,
    ...overrides,
  }

  // F6: '/console/know/rigor-metrics' → fetchApi prepends /api → '/api/console/know/rigor-metrics'
  const fetchMock = vi.fn((url) => {
    if (url.includes('/walkforward/runs') && url.includes('/windows')) {
      return jsonResponse(payloads.wfWindows)
    }
    if (url.includes('/walkforward/runs') && url.includes('/trades')) {
      return jsonResponse(payloads.wfTrades)
    }
    if (url.includes('/walkforward/runs')) {
      return jsonResponse(payloads.wfRuns)
    }
    if (url.includes('/stress-test/results')) {
      return jsonResponse(payloads.stress)
    }
    if (url.includes('/system/validation')) {
      return jsonResponse(payloads.validation)
    }
    if (url.includes('/console/know/rigor-metrics')) {
      return jsonResponse(payloads.rigorMetrics)
    }
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderRigor(initialPath = '/console/know/rigor') {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/console/know/rigor" element={<RigorStack />} />
          <Route path="/console/know" element={<div>Know overview</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// Root structure
// ---------------------------------------------------------------------------
describe('RigorStack — root', () => {
  it('renders with data-testid="know-rigor" (shell contract)', () => {
    mockRigor()
    renderRigor()
    expect(screen.getByTestId('know-rigor')).toBeInTheDocument()
  })

  it('renders a back-to-Know-overview link', () => {
    mockRigor()
    renderRigor()
    const backLink = screen.getByTestId('know-back-link')
    expect(backLink).toBeInTheDocument()
    expect(backLink.getAttribute('href')).toMatch(/\/console\/know$/)
  })

  it('renders three sub-view tabs: Validation, Walkforward, Stress Test', () => {
    mockRigor()
    renderRigor()
    expect(screen.getByTestId('rigor-tab-validation')).toBeInTheDocument()
    expect(screen.getByTestId('rigor-tab-walkforward')).toBeInTheDocument()
    expect(screen.getByTestId('rigor-tab-stress')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Validation sub-view (default tab)
// ---------------------------------------------------------------------------
describe('RigorStack — Validation sub-view', () => {
  it('default tab is Validation and its content is visible', async () => {
    mockRigor()
    renderRigor()
    const panel = await screen.findByTestId('rigor-validation-panel')
    expect(panel).toBeInTheDocument()
  })

  it('renders overall_status from /system/validation', async () => {
    mockRigor()
    renderRigor()
    const panel = await screen.findByTestId('rigor-validation-panel')
    // overall_status = 'healthy' from mock — wait for query to resolve
    await waitFor(() => {
      expect(within(panel).getByText(/healthy/i)).toBeInTheDocument()
    })
  })

  it('renders checks_passed count (non-vacuous: value from mock)', async () => {
    mockRigor()
    renderRigor()
    const panel = await screen.findByTestId('rigor-validation-panel')
    // checks_passed = 28 in MOCK_VALIDATION — wait for query to resolve
    await waitFor(() => {
      expect(within(panel).getByText('28')).toBeInTheDocument()
    })
  })

  it('renders a StalenessBadge in the validation panel', async () => {
    mockRigor()
    renderRigor()
    const panel = await screen.findByTestId('rigor-validation-panel')
    await waitFor(() => {
      const badges = within(panel).getAllByTestId('staleness-badge')
      expect(badges.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('no-data: renders explicit empty state when validation returns no data', async () => {
    mockRigor({ validation: { overall_status: null, checks_total: 0, categories: {} } })
    renderRigor()
    const panel = await screen.findByTestId('rigor-validation-panel')
    await waitFor(() => {
      expect(within(panel).getByTestId('rigor-validation-no-data')).toBeInTheDocument()
    })
  })

  it('LAW #3: does not render raw sentinel values in validation panel', async () => {
    mockRigor()
    renderRigor()
    const panel = await screen.findByTestId('rigor-validation-panel')
    await waitFor(() => {
      expect(within(panel).queryByText('999')).not.toBeInTheDocument()
      expect(within(panel).queryByText('-1')).not.toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// Walkforward sub-view
// ---------------------------------------------------------------------------
describe('RigorStack — Walkforward sub-view', () => {
  it('clicking Walkforward tab shows its panel', async () => {
    mockRigor()
    renderRigor()
    fireEvent.click(screen.getByTestId('rigor-tab-walkforward'))
    const panel = await screen.findByTestId('rigor-walkforward-panel')
    expect(panel).toBeInTheDocument()
  })

  it('renders the latest run outcome state (non-vacuous: PASS from mock)', async () => {
    mockRigor()
    renderRigor()
    fireEvent.click(screen.getByTestId('rigor-tab-walkforward'))
    const panel = await screen.findByTestId('rigor-walkforward-panel')
    // outcome_state = 'PASS' from MOCK_WF_RUNS — wait for query to resolve
    await waitFor(() => {
      expect(within(panel).getByText(/PASS/)).toBeInTheDocument()
    })
  })

  it('renders pooled_sharpe from the run (non-vacuous: 1.423 from mock)', async () => {
    mockRigor()
    renderRigor()
    fireEvent.click(screen.getByTestId('rigor-tab-walkforward'))
    const panel = await screen.findByTestId('rigor-walkforward-panel')
    await waitFor(() => {
      expect(within(panel).getByText(/1\.42/)).toBeInTheDocument()
    })
  })

  it('renders per-window breakdown including sharpe value (non-vacuous: 1.234 from mock)', async () => {
    mockRigor()
    renderRigor()
    fireEvent.click(screen.getByTestId('rigor-tab-walkforward'))
    const panel = await screen.findByTestId('rigor-walkforward-panel')
    await waitFor(() => {
      // window_index=0 has sharpe=1.234
      expect(within(panel).getByText(/1\.234/)).toBeInTheDocument()
    })
  })

  it('renders a StalenessBadge in the walkforward panel', async () => {
    mockRigor()
    renderRigor()
    fireEvent.click(screen.getByTestId('rigor-tab-walkforward'))
    const panel = await screen.findByTestId('rigor-walkforward-panel')
    await waitFor(() => {
      const badges = within(panel).getAllByTestId('staleness-badge')
      expect(badges.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('no-data: renders explicit empty state when no runs returned', async () => {
    mockRigor({ wfRuns: { runs: [], count: 0 } })
    renderRigor()
    fireEvent.click(screen.getByTestId('rigor-tab-walkforward'))
    const panel = await screen.findByTestId('rigor-walkforward-panel')
    await waitFor(() => {
      expect(within(panel).getByTestId('rigor-walkforward-no-data')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// Stress Test sub-view
// ---------------------------------------------------------------------------
describe('RigorStack — Stress Test sub-view', () => {
  it('clicking Stress Test tab shows its panel', async () => {
    mockRigor()
    renderRigor()
    fireEvent.click(screen.getByTestId('rigor-tab-stress'))
    const panel = await screen.findByTestId('rigor-stress-panel')
    expect(panel).toBeInTheDocument()
  })

  it('renders scenario labels from mock results (non-vacuous: 2008 Financial Crisis)', async () => {
    mockRigor()
    renderRigor()
    fireEvent.click(screen.getByTestId('rigor-tab-stress'))
    const panel = await screen.findByTestId('rigor-stress-panel')
    await waitFor(() => {
      expect(within(panel).getByText(/2008 Financial Crisis/i)).toBeInTheDocument()
    })
  })

  it('renders win_rate from mock (non-vacuous: 48.0% from 0.48)', async () => {
    mockRigor()
    renderRigor()
    fireEvent.click(screen.getByTestId('rigor-tab-stress'))
    const panel = await screen.findByTestId('rigor-stress-panel')
    await waitFor(() => {
      expect(within(panel).getByText(/48\.0%/)).toBeInTheDocument()
    })
  })

  it('renders max_drawdown_pct (non-vacuous: 18.5% from mock)', async () => {
    mockRigor()
    renderRigor()
    fireEvent.click(screen.getByTestId('rigor-tab-stress'))
    const panel = await screen.findByTestId('rigor-stress-panel')
    await waitFor(() => {
      expect(within(panel).getByText(/18\.5%/)).toBeInTheDocument()
    })
  })

  it('renders a StalenessBadge in the stress panel', async () => {
    mockRigor()
    renderRigor()
    fireEvent.click(screen.getByTestId('rigor-tab-stress'))
    const panel = await screen.findByTestId('rigor-stress-panel')
    await waitFor(() => {
      const badges = within(panel).getAllByTestId('staleness-badge')
      expect(badges.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('no-data: renders explicit empty state when no stress results returned', async () => {
    mockRigor({ stress: { results: [], _meta: { n: 0 } } })
    renderRigor()
    fireEvent.click(screen.getByTestId('rigor-tab-stress'))
    const panel = await screen.findByTestId('rigor-stress-panel')
    await waitFor(() => {
      expect(within(panel).getByTestId('rigor-stress-no-data')).toBeInTheDocument()
    })
  })

  it('LAW #3: does not render raw sentinel values in stress panel', async () => {
    mockRigor()
    renderRigor()
    fireEvent.click(screen.getByTestId('rigor-tab-stress'))
    const panel = await screen.findByTestId('rigor-stress-panel')
    await waitFor(() => {
      expect(within(panel).queryByText('999')).not.toBeInTheDocument()
      expect(within(panel).queryByText('-1')).not.toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// F6: PSR / DSR / PBO rigor-metrics rendering in ValidationPanel
// ---------------------------------------------------------------------------
describe('RigorStack — F6 PSR/DSR/PBO rigor-metrics', () => {
  it('fetchApi is called with BARE path /console/know/rigor-metrics (no /api double-prefix)', async () => {
    const fetchMock = mockRigor()
    renderRigor()
    await screen.findByTestId('rigor-validation-panel')
    await waitFor(() => {
      const calls = fetchMock.mock.calls.map(([url]) => url)
      // fetchApi prepends /api, so bare '/console/know/rigor-metrics' → '/api/console/know/rigor-metrics'
      expect(calls.some((u) => u.startsWith('/api/console/know/rigor-metrics'))).toBe(true)
      // Must NOT use double-prefix
      expect(calls.some((u) => u.startsWith('/api/api/'))).toBe(false)
    })
  })

  it('renders PSR tile when state=ok (non-vacuous: 0.78 from mock)', async () => {
    mockRigor()
    renderRigor()
    const panel = await screen.findByTestId('rigor-validation-panel')
    await waitFor(() => {
      expect(within(panel).getByTestId('rigor-psr-tile')).toBeInTheDocument()
      expect(within(panel).getByText('0.78')).toBeInTheDocument()
    })
  })

  it('renders DSR tile when state=ok (non-vacuous: 0.91 from mock)', async () => {
    mockRigor()
    renderRigor()
    const panel = await screen.findByTestId('rigor-validation-panel')
    await waitFor(() => {
      expect(within(panel).getByTestId('rigor-dsr-tile')).toBeInTheDocument()
      expect(within(panel).getByText('0.91')).toBeInTheDocument()
    })
  })

  it('renders PBO tile with insufficient_configs honest label (not a fabricated number)', async () => {
    mockRigor()
    renderRigor()
    const panel = await screen.findByTestId('rigor-validation-panel')
    await waitFor(() => {
      expect(within(panel).getByTestId('rigor-pbo-tile')).toBeInTheDocument()
      expect(within(panel).getByText(/insufficient configs for PBO/i)).toBeInTheDocument()
    })
    // Must NOT render NaN or a raw object as text
    expect(within(panel).queryByText('NaN')).not.toBeInTheDocument()
    expect(within(panel).queryByText('[object Object]')).not.toBeInTheDocument()
  })

  it('PSR/DSR tiles show no_data state without fabricated zeros in the rigor tiles', async () => {
    mockRigor({ rigorMetrics: MOCK_RIGOR_METRICS_NO_DATA })
    renderRigor()
    const panel = await screen.findByTestId('rigor-validation-panel')
    await waitFor(() => {
      // Tiles still render but show no-data state
      expect(within(panel).getByTestId('rigor-psr-tile')).toBeInTheDocument()
      expect(within(panel).getByTestId('rigor-dsr-tile')).toBeInTheDocument()
    })
    // PSR and DSR tiles must not render a sentinel-value (they should be sentinel-no-data for null values)
    const psrTile = within(panel).getByTestId('rigor-psr-tile')
    const dsrTile = within(panel).getByTestId('rigor-dsr-tile')
    // sentinel-no-data (null value) must appear; sentinel-value (fabricated number) must not
    expect(within(psrTile).getByTestId('sentinel-no-data')).toBeInTheDocument()
    expect(within(dsrTile).getByTestId('sentinel-no-data')).toBeInTheDocument()
    expect(within(psrTile).queryByTestId('sentinel-value')).not.toBeInTheDocument()
    expect(within(dsrTile).queryByTestId('sentinel-value')).not.toBeInTheDocument()
  })

  it('LAW #3: no raw objects or NaN rendered in validation panel with rigor-metrics data', async () => {
    mockRigor()
    renderRigor()
    const panel = await screen.findByTestId('rigor-validation-panel')
    await waitFor(() => {
      expect(within(panel).queryByText('[object Object]')).not.toBeInTheDocument()
      expect(within(panel).queryByText('NaN')).not.toBeInTheDocument()
    })
  })
})
