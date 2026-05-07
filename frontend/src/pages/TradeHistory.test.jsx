/**
 * TradeHistory page tests — T12 A4 meta consumption.
 * Sprint 3 / T12 — cohort badge renders from attribution._meta.
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
