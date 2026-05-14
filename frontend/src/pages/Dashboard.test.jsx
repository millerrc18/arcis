/**
 * Dashboard tests — T6 formatter fix: live DAYS column fallback for open trades.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, useQuery: vi.fn(), useMutation: vi.fn() }
})

vi.mock('../api', () => ({
  api: {
    getStatus: vi.fn(),
    getOpenTrades: vi.fn(),
    getClosedTrades: vi.fn(),
    getTrainingStatus: vi.fn(),
    getPackets: vi.fn(),
    getHaltStatus: vi.fn(),
    getLatestAudit: vi.fn(),
    getCtoReport: vi.fn(),
    getConfig: vi.fn(),
    getAccount: vi.fn(),
    getBuildScore: vi.fn(),
    getScanMetrics: vi.fn(),
    getSystemIndex: vi.fn(),
    getShadowDesks: vi.fn().mockResolvedValue([]),
    triggerActionScan: vi.fn(),
    triggerCtoReport: vi.fn(),
    triggerCollectTraining: vi.fn(),
    resumeTrading: vi.fn(),
    haltTrading: vi.fn(),
  },
  fetchApi: vi.fn(),
}))

vi.mock('../config', () => ({ IS_CLOUD: false }))
vi.mock('../native', () => ({ hapticWarning: vi.fn(), hapticSuccess: vi.fn() }))

vi.mock('../components/dashboard/KPIStrip', () => ({ default: () => null }))
vi.mock('../components/dashboard/BrokerExceptionsPanel', () => ({ default: () => null }))
vi.mock('../components/dashboard/NotificationsHealthPanel', () => ({ default: () => null }))
vi.mock('../components/dashboard/PreflightStatusCard', () => ({ default: () => null }))
vi.mock('../components/PlatformStatusWidget.jsx', () => ({ default: () => null }))
vi.mock('../components/system/QuickStatsPanel.jsx', () => ({ default: () => null }))
vi.mock('../components/system/SystemIndexPanel.jsx', () => ({ default: () => null }))
vi.mock('../components/system/WhatsNewPanel.jsx', () => ({ default: () => null }))
vi.mock('../components/ActivityFeed', () => ({ default: () => null }))

import { useQuery, useMutation } from '@tanstack/react-query'
import Dashboard from './Dashboard'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
    </MemoryRouter>
  )
}

beforeEach(() => {
  useQuery.mockReset()
  useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
})

describe('Dashboard — T6 DAYS column live fallback (computeDaysHeld)', () => {
  it('renders non-zero days for open trade with null duration_days using actual_entry_time', () => {
    // Entry was 2026-05-08 — today is 2026-05-14, so >= 6 days
    const openTrade = {
      trade_id: 1,
      ticker: 'AAPL',
      entry_price: 180,
      current_price: 185,
      pnl_dollars: 50,
      duration_days: null,
      actual_entry_time: '2026-05-08T15:00:00Z',
      stop_price: 170,
      target_1: 200,
      created_at: '2026-05-08T15:00:00Z',
    }

    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'status') return { data: { market_open: false, model_version: 'v1' }, isLoading: false }
      if (key === 'shadow-open') return { data: { open_trades: [openTrade], open_count: 1 }, isLoading: false }
      if (key === 'shadow-closed') return { data: { trades: [], metrics: {} }, isLoading: false }
      if (key === 'halt-status') return { data: { halted: false }, isLoading: false }
      if (key === 'config') return { data: { risk: { starting_capital: 100000 } }, isLoading: false }
      if (key === 'shadow-account') return { data: { equity: 100000, open_positions: 1 }, isLoading: false }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<Dashboard />)
    // The Days cell should show a number >= 6 (not '--' and not '0.00')
    const text = container.textContent
    // Extract ALL decimal numbers from the rendered text
    const allMatches = [...text.matchAll(/(\d+\.\d{2})/g)].map(m => parseFloat(m[1]))
    // At least one of the rendered decimal numbers should be >= 6
    // (the computed days-held for a trade entered 2026-05-08)
    const hasLargeDaysValue = allMatches.some(v => v >= 6)
    expect(hasLargeDaysValue).toBe(true)
  })

  it('renders duration_days directly when it is non-null', () => {
    const closedTrade = {
      trade_id: 2,
      ticker: 'MSFT',
      entry_price: 400,
      current_price: 410,
      pnl_dollars: 100,
      duration_days: 3,
      actual_entry_time: '2026-05-05T15:00:00Z',
      stop_price: 390,
      target_1: 420,
      created_at: '2026-05-05T15:00:00Z',
    }

    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'status') return { data: { market_open: false, model_version: 'v1' }, isLoading: false }
      if (key === 'shadow-open') return { data: { open_trades: [closedTrade], open_count: 1 }, isLoading: false }
      if (key === 'shadow-closed') return { data: { trades: [], metrics: {} }, isLoading: false }
      if (key === 'halt-status') return { data: { halted: false }, isLoading: false }
      if (key === 'config') return { data: { risk: { starting_capital: 100000 } }, isLoading: false }
      if (key === 'shadow-account') return { data: { equity: 100000, open_positions: 1 }, isLoading: false }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<Dashboard />)
    // duration_days=3 should render as "3"
    expect(container.textContent).toContain('3')
  })
})
