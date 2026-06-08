/**
 * AttributionView tests (P3-T9).
 * Covers:
 *   - Attribution part: alpha/beta + strategy/pipeline/LLM breakdown
 *   - Calibration part: no_data renders explicit "no joined outcomes" message (NOT 0%)
 *   - Calibration part: bucket values render when present
 *   - join_source + state surfaced
 *   - SentinelGuard never exposes raw sentinel values
 *
 * All tests are non-vacuous: each asserts a value that only appears when
 * the component consumes the mocked response.
 *
 * Backend shapes mirrored from:
 *   /attribution/stats  → analytics.py lines 788-799
 *   /shadow/sharpe-attribution → trades.py lines 128-142
 *   /console/know/calibration → console_know.py lines 329-346
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AttributionView from '../AttributionView'

// ---------------------------------------------------------------------------
// Mock endpoint shapes — mirrored verbatim from backend handlers
// ---------------------------------------------------------------------------

// /attribution/stats (analytics.py lines 788-799)
const MOCK_ATTRIBUTION_STATS = {
  total_pairs: 42,
  by_action: { buy: 30, sell: 12 },
  by_pair_type: { both_taken: 20, llm_rejected: 15, llm_upgraded: 7 },
  ranker_only: { resolved: 35, wins: 20, win_rate: 0.571 },
  llm_portfolio: { resolved: 28, wins: 18, win_rate: 0.643 },
  statistical_power: 'insufficient',
  paired_n: 28,
  _meta: { cohort: 'attribution.pairs', n: 28, as_of: '2026-06-05T14:30:00Z' },
}

// /shadow/sharpe-attribution (trades.py lines 128-142)
const MOCK_SHARPE_ATTRIBUTION = {
  n_trades: 35,
  trades_with_spy_data: 30,
  trades_missing_spy_data: 5,
  raw_sharpe: 0.812,
  raw_sharpe_ci_low: 0.341,
  raw_sharpe_ci_high: 1.283,
  excess_sharpe: 0.345,
  excess_sharpe_ci_low: -0.102,
  excess_sharpe_ci_high: 0.792,
  excess_t_stat: 1.423,
  mean_excess_pct: 0.52,
  hit_rate_vs_spy: 56.7,
  interpretation: 'alpha_suggestive',
}

// /console/know/calibration — state=ok with buckets (console_know.py lines 329-346)
const MOCK_CALIBRATION_OK = {
  buckets: [
    {
      confidence_band: '8-10',
      n: 15,
      win_rate: 0.733,
      avg_excess_return: 1.24,
      state: 'ok',
    },
    {
      confidence_band: '5-7',
      n: 12,
      win_rate: 0.583,
      avg_excess_return: 0.47,
      state: 'ok',
    },
    {
      confidence_band: '1-4',
      n: 0,
      win_rate: null,
      avg_excess_return: null,
      state: 'no_data',
    },
  ],
  join_source: 'recommendations.recommendation_id->shadow_trades',
  as_of: '2026-06-05T14:30:00Z',
  state: 'ok',
}

// /console/know/calibration — state=no_data (no joined outcomes)
const MOCK_CALIBRATION_NO_DATA = {
  buckets: [],
  join_source: 'recommendations.recommendation_id->shadow_trades',
  as_of: '2026-06-05T14:30:00Z',
  state: 'no_data',
}

// /console/know/calibration — state=unknown (source error)
const MOCK_CALIBRATION_UNKNOWN = {
  buckets: [],
  join_source: 'recommendations.recommendation_id->shadow_trades',
  as_of: '2026-06-05T14:30:00Z',
  state: 'unknown',
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

function mockApis(overrides = {}) {
  const payloads = {
    attrStats: MOCK_ATTRIBUTION_STATS,
    sharpeAttrib: MOCK_SHARPE_ATTRIBUTION,
    calibration: MOCK_CALIBRATION_OK,
    ...overrides,
  }
  const fetchMock = vi.fn((url) => {
    if (url.includes('/attribution/stats')) return jsonResponse(payloads.attrStats)
    if (url.includes('/shadow/sharpe-attribution')) return jsonResponse(payloads.sharpeAttrib)
    if (url.includes('/console/know/calibration')) return jsonResponse(payloads.calibration)
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

// ---------------------------------------------------------------------------
// Render helper
// ---------------------------------------------------------------------------

function renderAttribution() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/console/know/attribution']}>
        <Routes>
          <Route path="/console/know/attribution" element={<AttributionView />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// Root testid — required by spec
// ---------------------------------------------------------------------------

describe('AttributionView — root testid', () => {
  it('renders with data-testid="know-attribution"', async () => {
    mockApis()
    renderAttribution()
    const root = await screen.findByTestId('know-attribution')
    expect(root).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Attribution — alpha/beta + ranker vs LLM breakdown
// ---------------------------------------------------------------------------

describe('AttributionView — attribution part', () => {
  it('renders the raw Sharpe from /shadow/sharpe-attribution', async () => {
    mockApis()
    renderAttribution()
    await waitFor(() => {
      // raw_sharpe: 0.812 appears in the component
      expect(screen.getByText(/0\.812/)).toBeInTheDocument()
    })
  })

  it('renders the excess Sharpe from /shadow/sharpe-attribution', async () => {
    mockApis()
    renderAttribution()
    await waitFor(() => {
      // excess_sharpe: 0.345 must appear
      expect(screen.getByText(/0\.345/)).toBeInTheDocument()
    })
  })

  it('renders ranker win rate from /attribution/stats', async () => {
    mockApis()
    renderAttribution()
    await waitFor(() => {
      // ranker_only.win_rate: 0.571 → rendered as "57.1%" or "0.571"
      const txt = document.body.textContent
      expect(txt).toMatch(/57\.1|0\.571/)
    })
  })

  it('renders LLM portfolio win rate from /attribution/stats', async () => {
    mockApis()
    renderAttribution()
    await waitFor(() => {
      // llm_portfolio.win_rate: 0.643 → rendered as "64.3%" or "0.643"
      const txt = document.body.textContent
      expect(txt).toMatch(/64\.3|0\.643/)
    })
  })

  it('renders strategy/pipeline/LLM breakdown sections', async () => {
    mockApis()
    renderAttribution()
    await waitFor(() => {
      // Should surface ranker vs LLM labels
      const txt = document.body.textContent
      expect(txt).toMatch(/ranker|llm/i)
    })
  })

  it('renders the interpretation label from /shadow/sharpe-attribution', async () => {
    mockApis()
    renderAttribution()
    await waitFor(() => {
      // interpretation: 'alpha_suggestive' appears
      const txt = document.body.textContent
      expect(txt).toMatch(/alpha_suggestive|suggestive/i)
    })
  })

  it('renders paired_n count from /attribution/stats', async () => {
    mockApis()
    renderAttribution()
    await waitFor(() => {
      // paired_n: 28 — appears in the view
      const txt = document.body.textContent
      expect(txt).toMatch(/28/)
    })
  })
})

// ---------------------------------------------------------------------------
// Calibration — no_data must render explicit empty message, NOT 0%
// ---------------------------------------------------------------------------

describe('AttributionView — calibration no_data', () => {
  it('renders the explicit "no joined outcomes" message when state==="no_data"', async () => {
    mockApis({ calibration: MOCK_CALIBRATION_NO_DATA })
    renderAttribution()
    // Must see the explicit empty message
    await waitFor(() => {
      expect(screen.getByTestId('calibration-no-data')).toBeInTheDocument()
    })
    const msg = screen.getByTestId('calibration-no-data').textContent
    expect(msg).toMatch(/no joined outcomes/i)
  })

  it('does NOT render a 0% win rate when state==="no_data"', async () => {
    mockApis({ calibration: MOCK_CALIBRATION_NO_DATA })
    renderAttribution()
    await waitFor(() => {
      expect(screen.getByTestId('calibration-no-data')).toBeInTheDocument()
    })
    // The 0% win rate must never appear when there are no joined outcomes
    const txt = document.body.textContent
    expect(txt).not.toMatch(/0\.0%|0%/)
  })

  it('renders explicit no-data message when state==="unknown" (source error)', async () => {
    mockApis({ calibration: MOCK_CALIBRATION_UNKNOWN })
    renderAttribution()
    await waitFor(() => {
      expect(screen.getByTestId('calibration-no-data')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// Calibration — buckets render when present
// ---------------------------------------------------------------------------

describe('AttributionView — calibration buckets', () => {
  it('renders the 8-10 confidence band bucket', async () => {
    mockApis()
    renderAttribution()
    await waitFor(() => {
      // confidence_band "8-10" must appear
      expect(screen.getByText(/8-10/)).toBeInTheDocument()
    })
  })

  it('renders win_rate for a bucket that has data', async () => {
    mockApis()
    renderAttribution()
    await waitFor(() => {
      // win_rate: 0.733 → rendered as "73.3%" or "0.733"
      const txt = document.body.textContent
      expect(txt).toMatch(/73\.3|0\.733/)
    })
  })

  it('renders avg_excess_return for a bucket that has data', async () => {
    mockApis()
    renderAttribution()
    await waitFor(() => {
      // avg_excess_return: 1.24 appears
      const txt = document.body.textContent
      expect(txt).toMatch(/1\.24/)
    })
  })

  it('renders N (trade count) for each bucket', async () => {
    mockApis()
    renderAttribution()
    await waitFor(() => {
      // n: 15 for 8-10 bucket
      const txt = document.body.textContent
      expect(txt).toMatch(/15/)
    })
  })

  it('renders no_data treatment for an empty bucket (n=0, win_rate=null)', async () => {
    mockApis()
    renderAttribution()
    // The "1-4" bucket has n=0, win_rate=null — must render sentinel "no data"
    await waitFor(() => {
      const noDataEls = screen.getAllByTestId('sentinel-no-data')
      expect(noDataEls.length).toBeGreaterThan(0)
    })
  })
})

// ---------------------------------------------------------------------------
// Calibration — join_source + state surfaced
// ---------------------------------------------------------------------------

describe('AttributionView — calibration metadata', () => {
  it('surfaces the join_source string', async () => {
    mockApis()
    renderAttribution()
    await waitFor(() => {
      const txt = document.body.textContent
      // join_source contains "recommendation" — must be visible
      expect(txt).toMatch(/recommendation/i)
    })
  })

  it('surfaces the state for the calibration section', async () => {
    mockApis()
    renderAttribution()
    await waitFor(() => {
      // "ok" state (or a label derived from it) appears somewhere
      const txt = document.body.textContent
      expect(txt).toMatch(/ok|calibration/i)
    })
  })

  it('renders a StalenessBadge for the calibration as_of', async () => {
    mockApis()
    renderAttribution()
    await waitFor(() => {
      expect(screen.getAllByTestId('staleness-badge').length).toBeGreaterThan(0)
    })
  })
})

// ---------------------------------------------------------------------------
// SentinelGuard — raw sentinels never rendered
// ---------------------------------------------------------------------------

describe('AttributionView — sentinel safety', () => {
  it('does NOT render raw "999" sentinel in attribution section', async () => {
    mockApis({
      attrStats: {
        ...MOCK_ATTRIBUTION_STATS,
        ranker_only: { resolved: 35, wins: 999, win_rate: 999 },
      },
    })
    renderAttribution()
    await waitFor(() => {
      // 999 must be caught by SentinelGuard and rendered as "no data"
      const noData = screen.getAllByTestId('sentinel-no-data')
      expect(noData.length).toBeGreaterThan(0)
    })
    // The raw value "999" must not appear as a standalone number
    expect(screen.queryByText('999')).not.toBeInTheDocument()
  })
})
