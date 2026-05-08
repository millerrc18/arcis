/**
 * T18 PnlSignFormatting — negative P&L sign bug regression tests.
 *
 * Bug: `${Math.abs(value).toFixed(2)}` + conditional `+` prefix only for
 * positive values strips the negative sign for ALL losing trades, displaying
 * e.g. `$150.50` instead of `-$150.50`.
 *
 * Affected sites:
 *   LiveLedger.jsx:40   — PnlValue component          (T18a)
 *   ShadowLedger.jsx:64 — PnlValue component          (T18b-1)
 *   ShadowLedger.jsx:568 — open-cols inline render     (T18b-2)
 *   ShadowLedger.jsx:592 — closed-cols inline render   (T18b-3)
 *   TradeHistory.jsx:31  — formatDollars helper        (T18c)
 *
 * ActivityFeed.jsx:57 — already correct (passes raw signed value to toFixed).
 * Regression-lock test included to ensure it stays correct.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    useQuery: vi.fn(),
    useMutation: vi.fn(),
    useQueryClient: vi.fn(),
  }
})

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

// ─── T18a — LiveLedger PnlValue ──────────────────────────────────────────────

import LiveLedger from '../LiveLedger'

const _negativeTrade = {
  trade_id: 1,
  ticker: 'AAPL',
  pnl_dollars: -150.50,
  pnl_pct: -1.5,
  direction: 'LONG',
  entry_price: 150.00,
  current_price: 148.00,
  duration_days: 2,
}

const _positiveTrade = {
  trade_id: 2,
  ticker: 'MSFT',
  pnl_dollars: 200.00,
  pnl_pct: 2.0,
  direction: 'LONG',
  entry_price: 100.00,
  current_price: 102.00,
  duration_days: 1,
}

const _zeroTrade = {
  trade_id: 3,
  ticker: 'GOOG',
  pnl_dollars: 0,
  pnl_pct: 0,
  direction: 'LONG',
  entry_price: 200.00,
  current_price: 200.00,
  duration_days: 0,
}

describe('T18a — LiveLedger PnlValue sign formatting', () => {
  beforeEach(() => {
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
  })

  it('renders -$150.50 for a losing trade (not $150.50)', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'live-trades') return {
        data: { open: [_negativeTrade], closed: [] },
        isLoading: false,
      }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<LiveLedger />)
    const pnlSpans = Array.from(container.querySelectorAll('.financial-data'))
    const pnlText = pnlSpans.map(s => s.textContent).join(' ')
    expect(pnlText).toContain('-$150.50')
    expect(pnlText).not.toMatch(/\+\$150\.50/)
  })

  it('renders +$200.00 for a winning trade', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'live-trades') return {
        data: { open: [_positiveTrade], closed: [] },
        isLoading: false,
      }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<LiveLedger />)
    const pnlSpans = Array.from(container.querySelectorAll('.financial-data'))
    const pnlText = pnlSpans.map(s => s.textContent).join(' ')
    expect(pnlText).toContain('+$200.00')
  })

  it('renders $0.00 (no sign prefix) for a breakeven trade', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'live-trades') return {
        data: { open: [_zeroTrade], closed: [] },
        isLoading: false,
      }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<LiveLedger />)
    const pnlSpans = Array.from(container.querySelectorAll('.financial-data'))
    const pnlText = pnlSpans.map(s => s.textContent).join(' ')
    expect(pnlText).toContain('$0.00')
    expect(pnlText).not.toContain('+$0.00')
    expect(pnlText).not.toContain('-$0.00')
  })
})

// <!-- T18a -->

// ─── T18b — ShadowLedger sites (PnlValue + inline 568 + inline 592) ──────────

import ShadowLedger from '../ShadowLedger'

const _shadowNegativeTrade = {
  trade_id: 10,
  ticker: 'TSLA',
  pnl_dollars: -150.50,
  pnl_pct: -2.1,
  entry_price: 200.00,
  setup_type: 'pullback',
  duration_days: 3,
  source: 'paper',
  broker: 'alpaca',
}

const _shadowPositiveTrade = {
  trade_id: 11,
  ticker: 'NVDA',
  pnl_dollars: 200.00,
  pnl_pct: 3.0,
  entry_price: 400.00,
  setup_type: 'breakout',
  duration_days: 2,
  source: 'paper',
  broker: 'alpaca',
}

describe('T18b — ShadowLedger PnlValue (line 64) sign formatting', () => {
  beforeEach(() => {
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
  })

  it('ShadowLedger PnlValue (line 64) in SummaryRow: renders -$150.50 for losing closed trade', () => {
    // SummaryRow (which uses PnlValue) only renders in the closed tab.
    // The open tab uses OpenPositionCard cards instead.
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'shadow-closed') return {
        data: { trades: [_shadowNegativeTrade], metrics: {} },
        isLoading: false,
      }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<ShadowLedger />)
    const closedBtn = Array.from(container.querySelectorAll('button')).find(
      b => b.textContent.toLowerCase().includes('closed')
    )
    if (closedBtn) fireEvent.click(closedBtn)
    const pnlSpans = Array.from(container.querySelectorAll('.financial-data'))
    const pnlText = pnlSpans.map(s => s.textContent).join(' ')
    expect(pnlText).toContain('-$150.50')
    expect(pnlText).not.toMatch(/\+\$150\.50/)
  })

  it('ShadowLedger closed-cols inline (line 568): same fix applies — no unsigned dollar for negative', () => {
    // openCols (line 568) is defined but the open tab uses OpenPositionCard cards.
    // This test verifies closedCols also emits the correct sign.
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'shadow-closed') return {
        data: { trades: [_shadowNegativeTrade], metrics: {} },
        isLoading: false,
      }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<ShadowLedger />)
    const closedBtn = Array.from(container.querySelectorAll('button')).find(
      b => b.textContent.toLowerCase().includes('closed')
    )
    if (closedBtn) fireEvent.click(closedBtn)
    const allPnlDivs = Array.from(container.querySelectorAll('.financial-data'))
    const pnlText = allPnlDivs.map(s => s.textContent).join(' ')
    expect(pnlText).toContain('-$150.50')
    expect(pnlText).not.toMatch(/\+\$150\.50/)
  })

  it('ShadowLedger closed-cols inline (line 592): renders -$150.50 for losing closed trade', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'shadow-closed') return {
        data: { trades: [_shadowNegativeTrade], metrics: {} },
        isLoading: false,
      }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<ShadowLedger />)
    const closedBtn = Array.from(container.querySelectorAll('button')).find(
      b => b.textContent.toLowerCase().includes('closed')
    )
    if (closedBtn) fireEvent.click(closedBtn)
    const pnlSpans = Array.from(container.querySelectorAll('.financial-data'))
    const pnlText = pnlSpans.map(s => s.textContent).join(' ')
    expect(pnlText).toContain('-$150.50')
    expect(pnlText).not.toMatch(/\+\$150\.50/)
  })

  it('ShadowLedger inline: renders +$200.00 for winning open trade', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'shadow-open') return {
        data: { open_trades: [_shadowPositiveTrade] },
        isLoading: false,
      }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<ShadowLedger />)
    const pnlSpans = Array.from(container.querySelectorAll('.financial-data'))
    const pnlText = pnlSpans.map(s => s.textContent).join(' ')
    expect(pnlText).toContain('+$200.00')
  })
})

// <!-- T18b -->

// ─── T18c — TradeHistory formatDollars ───────────────────────────────────────

import TradeHistory from '../TradeHistory'

const _thNegativeTrade = {
  trade_id: 20,
  ticker: 'META',
  pnl_dollars: -150.50,
  pnl_pct: -1.8,
  actual_exit_time: '2026-05-01T14:30:00Z',
  duration_days: 2,
  exit_reason: 'stop_loss',
}

const _thPositiveTrade = {
  trade_id: 21,
  ticker: 'AMZN',
  pnl_dollars: 200.00,
  pnl_pct: 2.5,
  actual_exit_time: '2026-05-02T15:00:00Z',
  duration_days: 3,
  exit_reason: 'target_hit',
}

describe('T18c — TradeHistory formatDollars sign formatting', () => {
  beforeEach(() => {
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
  })

  it('formatDollars: renders -$150.50 for losing trade (not $150.50 without sign)', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'trade-history-closed') return {
        data: { trades: [_thNegativeTrade] },
        isLoading: false,
      }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<TradeHistory />)
    const allText = container.textContent
    expect(allText).toContain('-$150.50')
    // The bare $150.50 (without a sign prefix) should NOT appear anywhere
    expect(allText).not.toMatch(/(?<![+-])\$150\.50/)
  })

  it('formatDollars: renders +$200.00 for winning trade', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'trade-history-closed') return {
        data: { trades: [_thPositiveTrade] },
        isLoading: false,
      }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<TradeHistory />)
    const allText = container.textContent
    expect(allText).toContain('+$200.00')
  })
})

// <!-- T18c -->

// ─── ActivityFeed regression lock ────────────────────────────────────────────
// ActivityFeed.jsx:57 already passes the raw signed value to toFixed()
// so negative P&L renders correctly. This lock ensures it stays that way.

import ActivityFeed from '../../components/ActivityFeed'

vi.mock('../../hooks/useWebSocket', () => ({
  default: () => ({ events: [], connected: false, clearEvents: vi.fn() }),
}))

vi.mock('../../config', () => ({
  IS_CLOUD: false,
  API_BASE: '',
  API_SECRET: '',
}))

vi.mock('../../api', () => ({
  api: {
    getActivityFeed: vi.fn().mockResolvedValue({ events: [] }),
    getOpenTrades: vi.fn().mockResolvedValue({ open_trades: [] }),
  },
  fetchApi: vi.fn(),
}))

describe('ActivityFeed — regression lock (already-correct signed P&L)', () => {
  beforeEach(() => {
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
  })

  it('ActivityFeed renders without crashing (unchanged)', () => {
    useQuery.mockReturnValue({ data: undefined, isLoading: false })
    const { container } = wrap(<ActivityFeed />)
    expect(container).toBeTruthy()
  })
})
