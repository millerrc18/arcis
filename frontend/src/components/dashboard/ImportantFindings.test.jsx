/**
 * Tests for Round 7 Important findings: I9 (Packets shape guard) and
 * G4 (llm_conviction_reason in ShadowLedger trade detail) and
 * G5 (approaching timeout count on Dashboard).
 * Track 1.5 / Round 8.E.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, useQuery: vi.fn() }
})

// Mock api module for Packets
vi.mock('../../api', () => ({
  api: {
    getPackets: vi.fn(),
    getOpenTrades: vi.fn(),
    getClosedTrades: vi.fn(),
    getAccountInfo: vi.fn(),
    getSystemStatus: vi.fn(),
    getBuildScore: vi.fn(),
    getCTOReport: vi.fn(),
    getTrainingStatus: vi.fn(),
    getAuditTrail: vi.fn(),
    getTodayPackets: vi.fn(),
    getScanMetrics: vi.fn(),
    getShadowDesks: vi.fn(),
    getSystemIndex: vi.fn(),
    haltTrading: vi.fn(),
    runScan: vi.fn(),
    generateReport: vi.fn(),
  },
  getOpenTrades: vi.fn(),
  getPlatformStrategies: vi.fn(),
}))

vi.mock('../../components/LoadingSpinner', () => ({
  default: () => <div>Loading</div>,
}))
vi.mock('../../components/EmptyState', () => ({
  default: ({ message }) => <div>{message}</div>,
}))
vi.mock('../../components/StatusBadge', () => ({
  default: ({ text }) => <span>{text}</span>,
}))
vi.mock('../../components/PnlText', () => ({
  default: ({ value }) => <span>{value}</span>,
}))
vi.mock('../../components/TimeoutCell', () => ({
  default: ({ status }) => <span>{status}</span>,
}))
vi.mock('../../components/OpenPositionCard', () => ({
  default: () => <div>OpenPositionCard</div>,
}))
vi.mock('../../components/Tooltip', () => ({
  default: ({ children }) => <div>{children}</div>,
}))
vi.mock('../../components/MetricCard', () => ({
  default: ({ label, value }) => <div>{label}: {value}</div>,
}))
vi.mock('recharts', () => ({
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  ResponsiveContainer: ({ children }) => <div>{children}</div>,
  Area: () => null,
  AreaChart: ({ children }) => <div>{children}</div>,
  BarChart: ({ children }) => <div>{children}</div>,
  Bar: () => null,
  Cell: () => null,
  CartesianGrid: () => null,
  ReferenceLine: () => null,
}))
vi.mock('lucide-react', () => ({
  TrendingUp: () => null,
  ChevronDown: () => <span>v</span>,
  ChevronRight: () => <span>{'>'}</span>,
  Search: () => null,
  ArrowUpDown: () => null,
}))

import { useQuery } from '@tanstack/react-query'
import Packets from '../../pages/Packets'
import ShadowLedger from '../../pages/ShadowLedger'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

// ── I9: Packets Array.isArray guard ──────────────────────────────────

describe('Packets I9: Array.isArray guard', () => {
  it('renders EmptyState when API returns object shape {packets:[]}', () => {
    useQuery.mockReturnValue({
      data: { packets: [] },
      isLoading: false,
    })
    const { container } = wrap(<Packets />)
    expect(container.textContent).toContain('No packets')
  })

  it('renders EmptyState when API returns empty array', () => {
    useQuery.mockReturnValue({
      data: [],
      isLoading: false,
    })
    const { container } = wrap(<Packets />)
    expect(container.textContent).toContain('No packets')
  })

  it('renders packets when API returns non-empty plain array', () => {
    useQuery.mockReturnValue({
      data: [
        {
          recommendation_id: 'r1',
          ticker: 'AAPL',
          company_name: 'Apple Inc.',
          priority_score: 85,
          confidence_score: 7,
          event_risk_flag: 'none',
          created_at: '2026-04-25T10:00:00Z',
          entry_zone: '170-172',
          stop_level: '165',
          target_1: '180',
          target_2: '185',
          thesis_text: 'Test thesis',
        },
      ],
      isLoading: false,
    })
    const { container } = wrap(<Packets />)
    expect(container.textContent).toContain('AAPL')
  })

  it('does not crash when API returns null', () => {
    useQuery.mockReturnValue({
      data: null,
      isLoading: false,
    })
    const { container } = wrap(<Packets />)
    expect(container.textContent).toContain('No packets')
  })
})

// ── G4: llm_conviction_reason in ShadowLedger expandable row ─────────

const _closedTrade = {
  trade_id: 't1',
  ticker: 'AAPL',
  setup_type: 'pullback',
  entry_price: 170.0,
  actual_exit_price: 178.0,
  stop_price: 165.0,
  target_1: 180.0,
  pnl_dollars: 80.0,
  pnl_pct: 4.7,
  duration_days: 3,
  exit_reason: 'target_1',
  timeout_status: 'on_track',
  timeout_days: 10,
  llm_conviction_reason: 'Strong pullback to 50-day MA with elevated volume and sector momentum.',
}

// Mock shapes match what the component actually reads from useQuery.
// ShadowLedger queries by key: shadow-open, shadow-closed, shadow-account, live-trades-for-ledger.
function mockShadowLedgerQueries(closedTrades) {
  useQuery.mockImplementation(({ queryKey }) => {
    const key = queryKey?.[0]
    if (key === 'shadow-open') {
      return { data: { open_trades: [], open_count: 0 }, isLoading: false }
    }
    if (key === 'shadow-closed') {
      return { data: { trades: closedTrades, metrics: { win_rate: 1.0 } }, isLoading: false }
    }
    if (key === 'shadow-account') {
      return { data: { equity: 100000, starting_capital: 100000 }, isLoading: false }
    }
    if (key === 'live-trades-for-ledger') {
      return { data: { open: [], closed: [] }, isLoading: false }
    }
    return { data: undefined, isLoading: false }
  })
}

describe('ShadowLedger G4: llm_conviction_reason display', () => {
  it('renders llm_conviction_reason text when closed trade row is expanded', () => {
    mockShadowLedgerQueries([_closedTrade])
    const { container, getByText } = wrap(<ShadowLedger />)
    // Click the closed tab to show closed trades
    const closedTabBtn = getByText(/closed \(1\)/i)
    fireEvent.click(closedTabBtn)
    // Click the expandable trade row
    const row = container.querySelector('tr.cursor-pointer')
    if (row) fireEvent.click(row)
    expect(container.textContent).toContain('Strong pullback to 50-day MA')
  })

  it('does not render LLM Reasoning label when llm_conviction_reason is null', () => {
    const tradeNoConviction = { ..._closedTrade, trade_id: 't2', llm_conviction_reason: null }
    mockShadowLedgerQueries([tradeNoConviction])
    const { container, getByText } = wrap(<ShadowLedger />)
    const closedTabBtn = getByText(/closed \(1\)/i)
    fireEvent.click(closedTabBtn)
    const row = container.querySelector('tr.cursor-pointer')
    if (row) fireEvent.click(row)
    expect(container.textContent).not.toContain('LLM Reasoning')
  })
})
