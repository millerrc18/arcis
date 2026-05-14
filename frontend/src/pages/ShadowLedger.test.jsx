/**
 * ShadowLedger.test.jsx — T8 open-position count alignment.
 *
 * Tests:
 *  (a) Mock /api/shadow/open returning 28 rows → header shows 'open (28)'
 *  (b) Table renders 28 rows
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, useQuery: vi.fn() }
})

vi.mock('../config', () => ({
  IS_CLOUD: false,
  API_BASE: '',
  API_SECRET: '',
}))

vi.mock('../api', () => ({
  api: {
    getOpenTrades: vi.fn(),
    getClosedTrades: vi.fn(),
    getAccount: vi.fn(),
    getLiveTrades: vi.fn(),
  },
}))

import { useQuery } from '@tanstack/react-query'
import ShadowLedger from './ShadowLedger'

function buildOpenTrade(i) {
  return {
    trade_id: i,
    ticker: `TICK${i}`,
    status: 'open',
    desk: 'swing',
    pnl_dollars: 10 * i,
    pnl_pct: 0.5,
    entry_price: 100,
    duration_days: 2,
    created_at: '2026-05-01T10:00:00Z',
  }
}

const _28OpenTrades = Array.from({ length: 28 }, (_, i) => buildOpenTrade(i + 1))

function buildOpenData(trades) {
  return {
    open_trades: trades,
    trades: trades,
    open_count: trades.length,
    count: trades.length,
  }
}

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  useQuery.mockReset()
})

describe('ShadowLedger — T8 open-position count', () => {
  it('shows open (28) in tab header when API returns 28 open trades', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'shadow-open') {
        return { data: buildOpenData(_28OpenTrades), isLoading: false }
      }
      if (key === 'shadow-closed') {
        return { data: { trades: [], metrics: {} }, isLoading: false }
      }
      if (key === 'shadow-account') {
        return { data: { equity: 100000, open_positions: 28 }, isLoading: false }
      }
      return { data: undefined, isLoading: false }
    })

    wrap(<ShadowLedger />)
    const openTab = screen.getByRole('button', { name: /open \(28\)/i })
    expect(openTab).toBeTruthy()
  })

  it('renders 28 trade cards in the open tab when API returns 28 rows', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'shadow-open') {
        return { data: buildOpenData(_28OpenTrades), isLoading: false }
      }
      if (key === 'shadow-closed') {
        return { data: { trades: [], metrics: {} }, isLoading: false }
      }
      if (key === 'shadow-account') {
        return { data: { equity: 100000 }, isLoading: false }
      }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<ShadowLedger />)
    // The open tab is active by default; each trade renders a card
    // Count rendered ticker text occurrences (TICK1 through TICK28)
    const tickerMatches = container.querySelectorAll('[class*="font-medium"]')
    // At least the 28 ticker badges should be present
    expect(tickerMatches.length).toBeGreaterThanOrEqual(28)
  })

  it('uses swing desk by default (queryKey includes swing)', () => {
    const capturedKeys = []
    useQuery.mockImplementation((opts) => {
      capturedKeys.push(opts.queryKey)
      const key = opts.queryKey?.[0]
      if (key === 'shadow-open') {
        return { data: buildOpenData(_28OpenTrades), isLoading: false }
      }
      if (key === 'shadow-closed') {
        return { data: { trades: [], metrics: {} }, isLoading: false }
      }
      return { data: undefined, isLoading: false }
    })

    wrap(<ShadowLedger />)
    const openKey = capturedKeys.find(k => k[0] === 'shadow-open')
    expect(openKey).toBeDefined()
    // After the fix, ShadowLedger should pass 'swing' desk to match Dashboard behavior
    expect(openKey).toContain('swing')
  })
})
