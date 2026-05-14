/**
 * TradeHistory page tests — T12 A4 meta consumption + T8 undefined wins/losses fix.
 * Sprint 3 / T12 — cohort badge renders from attribution._meta.
 * Sprint 6 / T8 — no 'undefinedW / undefinedL' when wins/losses are undefined.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, useQuery: vi.fn() }
})

import { useQuery } from '@tanstack/react-query'
import TradeHistory from './TradeHistory'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const _closedData = {
  trades: [
    {
      trade_id: 1,
      ticker: 'AAPL',
      pnl_dollars: 120.5,
      pnl_pct: 2.1,
      actual_exit_time: '2026-05-01T14:30:00Z',
      duration_days: 3,
      exit_reason: 'target_hit',
    },
    {
      trade_id: 2,
      ticker: 'MSFT',
      pnl_dollars: -45.0,
      pnl_pct: -0.9,
      actual_exit_time: '2026-05-02T15:00:00Z',
      duration_days: 5,
      exit_reason: 'stop_loss',
    },
  ],
}

const _attribution = {
  n_trades: 2,
  raw_sharpe: 0.42,
  excess_sharpe: 0.38,
  excess_sharpe_ci_low: 0.1,
  excess_sharpe_ci_high: 0.66,
  excess_t_stat: 1.8,
  hit_rate_vs_spy: 55.0,
  interpretation: 'alpha_suggestive',
  _meta: {
    sharpe_ratio: { cohort: 'kpi.canonical', label: 'Instrumented + quarantine-filtered', n: 2 },
  },
}

const _attributionNoMeta = {
  n_trades: 2,
  raw_sharpe: 0.42,
  excess_sharpe: 0.38,
  excess_sharpe_ci_low: 0.1,
  excess_sharpe_ci_high: 0.66,
  excess_t_stat: 1.8,
  hit_rate_vs_spy: 55.0,
  interpretation: 'alpha_suggestive',
}

beforeEach(() => {
  useQuery.mockReset()
})

describe('TradeHistory — T12 A4 meta badge', () => {
  it('renders cohort badge from attribution._meta.sharpe_ratio when present', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'trade-history-closed') return { data: _closedData, isLoading: false }
      if (key === 'sharpe-attribution') return { data: _attribution, isLoading: false }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<TradeHistory />)
    const badge = container.querySelector('[data-testid="attribution-meta-badge"]')
    expect(badge).not.toBeNull()
    expect(badge.textContent).toContain('n=2')
    expect(badge.textContent).toContain('canonical')
  })

  it('renders no cohort badge when _meta is absent from attribution', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'trade-history-closed') return { data: _closedData, isLoading: false }
      if (key === 'sharpe-attribution') return { data: _attributionNoMeta, isLoading: false }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<TradeHistory />)
    const badge = container.querySelector('[data-testid="attribution-meta-badge"]')
    expect(badge).toBeNull()
  })
})

// Closed data where all trades have pnl_dollars=null (open/unrealized) — triggers the
// wins/losses undefined bug because metrics([]) returns {count:0, wr:0, ...} without wins/losses
const _openOnlyClosedData = {
  trades: [
    {
      trade_id: 3,
      ticker: 'GOOG',
      pnl_dollars: null,
      pnl_pct: null,
      actual_exit_time: null,
      duration_days: 1,
      exit_reason: null,
    },
  ],
}

describe('TradeHistory — T8 undefined wins/losses fix', () => {
  it('never renders the literal string "undefined" in the DOM when all trades are open', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'trade-history-closed') return { data: _openOnlyClosedData, isLoading: false }
      if (key === 'sharpe-attribution') return { data: undefined, isLoading: false }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<TradeHistory />)
    expect(container.textContent).not.toContain('undefined')
  })

  it('shows numeric W/L subtitle in all-time stats (not undefinedW / undefinedL)', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'trade-history-closed') return { data: _closedData, isLoading: false }
      if (key === 'sharpe-attribution') return { data: undefined, isLoading: false }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<TradeHistory />)
    // _closedData has 1 win (AAPL +120.5) and 1 loss (MSFT -45), so subtitle should be "1W / 1L"
    expect(container.textContent).toContain('1W / 1L')
  })
})
