/**
 * Strategy page tests — T12 A4 meta consumption.
 * Sprint 3 / T12 fix — strategy-meta-badge renders from data._meta.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, useQuery: vi.fn() }
})

import { useQuery } from '@tanstack/react-query'
import Strategy from './Strategy'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const _strategyWithMeta = {
  trades: [
    {
      trade_id: 1,
      ticker: 'AAPL',
      pnl_dollars: 120.5,
      pnl_pct: 2.1,
      actual_exit_time: '2026-05-01T14:30:00Z',
      duration_days: 3,
      cumulative_pnl: 120.5,
      model_score: 75,
    },
  ],
  by_score_band: {},
  by_regime: {},
  drawdown_series: [],
  _meta: {
    cohort: 'trades.strategy',
    label: 'Strategy trades cohort',
    n: 1,
  },
}

const _strategyNoMeta = {
  trades: [
    {
      trade_id: 1,
      ticker: 'AAPL',
      pnl_dollars: 120.5,
      pnl_pct: 2.1,
      actual_exit_time: '2026-05-01T14:30:00Z',
      duration_days: 3,
      cumulative_pnl: 120.5,
      model_score: 75,
    },
  ],
  by_score_band: {},
  by_regime: {},
  drawdown_series: [],
}

beforeEach(() => {
  useQuery.mockReset()
})

describe('Strategy — T12 A4 meta badge', () => {
  it('renders strategy-meta-badge when data._meta is present', () => {
    useQuery.mockReturnValue({ data: _strategyWithMeta, isLoading: false, error: null })

    const { container } = wrap(<Strategy />)
    const badge = container.querySelector('[data-testid="strategy-meta-badge"]')
    expect(badge).not.toBeNull()
    expect(badge.textContent).toContain('n=1')
    expect(badge.textContent).toContain('strategy')
  })

  it('renders no strategy-meta-badge when data._meta is absent', () => {
    useQuery.mockReturnValue({ data: _strategyNoMeta, isLoading: false, error: null })

    const { container } = wrap(<Strategy />)
    const badge = container.querySelector('[data-testid="strategy-meta-badge"]')
    expect(badge).toBeNull()
  })
})
