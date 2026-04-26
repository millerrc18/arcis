/**
 * Round 8.F follow-up tests — 3 deferred Important items from 8.E.
 * Track 1.5 / Round 8.F.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, useQuery: vi.fn(), useMutation: vi.fn(), useQueryClient: vi.fn() }
})

vi.mock('../../api', () => ({
  api: {
    getStatus: vi.fn(),
    getOpenTrades: vi.fn(),
    getClosedTrades: vi.fn(),
    getLatestAudit: vi.fn(),
    getCtoReport: vi.fn(),
    getConfig: vi.fn(),
    getAccount: vi.fn(),
    getBuildScore: vi.fn(),
    getScanMetrics: vi.fn(),
    getSystemIndex: vi.fn(),
    getTrainingStatus: vi.fn(),
    getShadowDesks: vi.fn().mockResolvedValue([]),
    getHaltStatus: vi.fn(),
    haltTrading: vi.fn(),
    resumeTrading: vi.fn(),
    triggerActionScan: vi.fn(),
    triggerCtoReport: vi.fn(),
    triggerCollectTraining: vi.fn(),
  },
  fetchApi: vi.fn(),
  getWalkforwardRuns: vi.fn(),
  getWalkforwardRun: vi.fn(),
  getWalkforwardRunWindows: vi.fn(),
  getWalkforwardRunTrades: vi.fn(),
  getPlatformStrategies: vi.fn(),
  getPlatformStrategyDetail: vi.fn(),
  getPlatformBacktestResults: vi.fn(),
  getPlatformBacktestTrades: vi.fn(),
  getPlatformPromotionEvents: vi.fn(),
}))

vi.mock('../../config', () => ({ IS_CLOUD: false }))
vi.mock('../../native', () => ({ hapticWarning: vi.fn(), hapticSuccess: vi.fn() }))
vi.mock('../../components/LoadingSpinner', () => ({ default: () => <div>Loading</div> }))
vi.mock('../../components/MetricCard', () => ({
  default: ({ label, value }) => <div data-testid="metric-card">{label}: {value}</div>,
}))
vi.mock('../../components/StatusBadge', () => ({ default: ({ text }) => <span>{text}</span> }))
vi.mock('../../components/PnlText', () => ({ default: ({ value }) => <span>{value}</span> }))
vi.mock('../../components/TimeoutCell', () => ({ default: ({ status }) => <span>{status}</span> }))
vi.mock('../../components/DataTable', () => ({ default: () => <div>DataTable</div> }))
vi.mock('../../components/ActivityFeed', () => ({ default: () => <div>ActivityFeed</div> }))
vi.mock('../../components/Tooltip', () => ({ default: ({ children }) => <div>{children}</div> }))
vi.mock('../../components/BacktestEquityChart', () => ({ default: () => <div>Chart</div> }))
vi.mock('../../components/dashboard/KPIStrip', () => ({ default: () => <div>KPIStrip</div> }))
vi.mock('../../components/dashboard/BrokerExceptionsPanel', () => ({ default: () => <div>BrokerExceptions</div> }))
vi.mock('../../components/dashboard/PreflightStatusCard', () => ({ default: () => <div>Preflight</div> }))
vi.mock('../../components/PlatformStatusWidget', () => ({ default: () => <div>PlatformStatus</div> }))
vi.mock('../../components/system/QuickStatsPanel', () => ({ default: () => <div>QuickStats</div> }))
vi.mock('../../components/system/SystemIndexPanel', () => ({ default: () => <div>SystemIndex</div> }))
vi.mock('../../components/system/WhatsNewPanel', () => ({ default: () => <div>WhatsNew</div> }))
vi.mock('react-router-dom', () => ({ Link: ({ children }) => <a>{children}</a> }))
vi.mock('recharts', () => ({
  XAxis: () => null, YAxis: () => null, Tooltip: () => null,
  ResponsiveContainer: ({ children }) => <div>{children}</div>,
  Area: () => null, AreaChart: ({ children }) => <div>{children}</div>,
  BarChart: ({ children }) => <div>{children}</div>,
  Bar: ({ children }) => <div>{children}</div>,
  Cell: () => null, CartesianGrid: () => null, ReferenceLine: () => null,
  LineChart: ({ children }) => <div>{children}</div>,
  Line: () => null, ComposedChart: ({ children }) => <div>{children}</div>,
}))
vi.mock('lucide-react', () => ({
  TrendingUp: () => null, TrendingDown: () => null, Minus: () => null,
  AlertTriangle: () => null, Zap: () => null,
  ChevronDown: () => <span>v</span>, ChevronUp: () => <span>^</span>,
  Clock: () => null, Target: () => null, Shield: () => null, Activity: () => null,
}))

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import WalkforwardResults from '../../pages/WalkforwardResults'
import StrategyResearch from '../../pages/StrategyResearch'
import Dashboard from '../../pages/Dashboard'
import TradeHistory from '../../pages/TradeHistory'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

function hasHardcodedColorClass(html) {
  const classAttrRegex = /class(?:Name)?="([^"]*)"/g
  let match
  while ((match = classAttrRegex.exec(html)) !== null) {
    const classes = match[1].split(/\s+/)
    for (const cls of classes) {
      if (/^(bg|text)-(slate|gray)-\d/.test(cls)) return true
    }
  }
  return false
}

beforeEach(() => {
  useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
  useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
})

describe('WalkforwardResults I1: no hardcoded Tailwind color classes', () => {
  it('renders empty state without hardcoded color class attributes', () => {
    useQuery.mockReturnValue({ data: { runs: [] }, isLoading: false, error: null })
    const { container } = wrap(<WalkforwardResults />)
    expect(hasHardcodedColorClass(container.innerHTML)).toBe(false)
  })

  it('renders run rows without hardcoded color classes when data is present', () => {
    useQuery.mockImplementation(({ queryKey }) => {
      if (queryKey?.[0] === 'wf-runs') {
        return {
          data: {
            runs: [{
              run_id: 'run-abc-1234',
              strategy_id: 'strategy-1',
              outcome_state: 'PASS',
              reason: 'all criteria met',
              pooled_sharpe: 1.5,
              pooled_mde: 0.3,
              n_windows_pass: 3, n_windows_fail: 0,
              n_windows_inconclusive_data: 0, n_windows_inconclusive_power: 0,
              heavy_tail_flag: false,
              derived_from_source_type: 'backtest',
              created_at: '2026-04-25T10:00:00Z',
            }],
          },
          isLoading: false,
          error: null,
        }
      }
      return { data: undefined, isLoading: false }
    })
    const { container } = wrap(<WalkforwardResults />)
    expect(hasHardcodedColorClass(container.innerHTML)).toBe(false)
  })
})

describe('StrategyResearch I2: no hardcoded Tailwind color classes', () => {
  it('renders loading state without hardcoded color classes', () => {
    useQuery.mockReturnValue({ data: undefined, isLoading: true })
    const { container } = wrap(<StrategyResearch />)
    expect(hasHardcodedColorClass(container.innerHTML)).toBe(false)
  })

  it('renders empty strategies without hardcoded color classes', () => {
    useQuery.mockReturnValue({ data: [], isLoading: false })
    const { container } = wrap(<StrategyResearch />)
    expect(hasHardcodedColorClass(container.innerHTML)).toBe(false)
  })

  it('renders strategy rows without hardcoded color classes', () => {
    useQuery.mockImplementation(({ queryKey }) => {
      if (queryKey?.[0] === 'platform-strategies') {
        return {
          data: [{
            strategy_id: 's1',
            display_name: 'Pullback v1',
            current_status: 'shadow_trading',
            last_dsr: 1.23,
            last_max_dd: 0.05,
            last_n_trades: 42,
            last_backtest_at: '2026-04-20T00:00:00Z',
          }],
          isLoading: false,
        }
      }
      return { data: undefined, isLoading: false }
    })
    const { container } = wrap(<StrategyResearch />)
    expect(hasHardcodedColorClass(container.innerHTML)).toBe(false)
  })
})

function mockDashboardQueries(approachingCount) {
  const openTrades = Array.from({ length: approachingCount }, (_, i) => ({
    trade_id: 't' + i,
    ticker: 'AAPL',
    timeout_status: 'approaching',
  }))

  useQuery.mockImplementation(({ queryKey }) => {
    const key = queryKey?.[0]
    if (key === 'shadow-open') return { data: { open_trades: openTrades, open_count: approachingCount } }
    if (key === 'shadow-closed') return { data: { trades: [], metrics: {} } }
    if (key === 'status') return { data: { model_version: 'v1', market_open: false }, isLoading: false }
    if (key === 'training-status') return { data: null }
    if (key === 'packets') return { data: [] }
    if (key === 'halt-status') return { data: { halted: false } }
    if (key === 'audit-latest') return { data: null }
    if (key === 'cto-report') return { data: null }
    if (key === 'config') return { data: { risk: { starting_capital: 100000 } } }
    if (key === 'shadow-account') return { data: { equity: 100000 } }
    if (key === 'build-score') return { data: null }
    if (key === 'scan-metrics') return { data: null }
    if (key === 'system-index') return { data: null, isLoading: false }
    if (key === 'kpis') return { data: null }
    return { data: undefined, isLoading: false }
  })
}

describe('Dashboard G5: Approaching Timeout MetricCard always visible', () => {
  it('renders Approaching Timeout MetricCard when count is 0', () => {
    mockDashboardQueries(0)
    const { getAllByTestId } = wrap(<Dashboard />)
    const cards = getAllByTestId('metric-card')
    const labels = cards.map(c => c.textContent)
    expect(labels.some(t => t.toLowerCase().includes('approaching timeout'))).toBe(true)
  })

  it('shows 0 in the Approaching Timeout card when no trades approaching', () => {
    mockDashboardQueries(0)
    const { getAllByTestId } = wrap(<Dashboard />)
    const cards = getAllByTestId('metric-card')
    const timeoutCard = cards.find(c => c.textContent.toLowerCase().includes('approaching timeout'))
    expect(timeoutCard).toBeTruthy()
    expect(timeoutCard.textContent).toContain('0')
  })

  it('shows correct count when trades are approaching timeout', () => {
    mockDashboardQueries(3)
    const { getAllByTestId } = wrap(<Dashboard />)
    const cards = getAllByTestId('metric-card')
    const timeoutCard = cards.find(c => c.textContent.toLowerCase().includes('approaching timeout'))
    expect(timeoutCard).toBeTruthy()
    expect(timeoutCard.textContent).toContain('3')
  })

  it('grid contains at least 5 MetricCards (lg:grid-cols-5)', () => {
    mockDashboardQueries(0)
    const { getAllByTestId } = wrap(<Dashboard />)
    const cards = getAllByTestId('metric-card')
    expect(cards.length).toBeGreaterThanOrEqual(5)
  })
})

// Use today's date so the trade falls into the today bucket and renders in RecentTradesTable.
function todayISO() {
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}T12:00:00Z`
}

const _closedTradeWithReason = {
  trade_id: 'th-t1',
  ticker: 'MSFT',
  pnl_dollars: 120.0,
  pnl_pct: 3.2,
  duration_days: 4,
  actual_exit_time: todayISO(),
  exit_reason: 'target_1',
  timeout_days: 10,
  timeout_status: 'on_track',
  timeout_progress_pct: 40,
  llm_conviction_reason: 'Breakout above resistance with high relative volume.',
}

const _closedTradeNoReason = {
  trade_id: 'th-t2',
  ticker: 'NVDA',
  pnl_dollars: -45.0,
  pnl_pct: -1.1,
  duration_days: 2,
  actual_exit_time: todayISO(),
  exit_reason: 'stop_loss',
  timeout_days: 10,
  timeout_status: 'on_track',
  timeout_progress_pct: 20,
  llm_conviction_reason: null,
}

function mockTradeHistoryQueries(trades) {
  useQuery.mockImplementation(({ queryKey }) => {
    const key = queryKey?.[0]
    if (key === 'trade-history-closed') {
      return { data: { trades }, isLoading: false }
    }
    if (key === 'sharpe-attribution') {
      return { data: null, isLoading: false }
    }
    return { data: undefined, isLoading: false }
  })
}

// ── PR-690 I7: anti-regression for Round-8.F backtick template-literal stripping ──
//
// The original Round-8.F commit (5d556bab) shipped Dashboard.jsx:443 + 445 with
// `${...}` collapsed to `{...}` — broken JSX that rendered raw expression text
// instead of interpolated values. The grep-based protection in the B1/B2 fix
// commit catches the SOURCE-side anti-pattern, but doesn't catch the RENDER-side
// regression. These tests assert that:
//   1. The Win Rate card renders as a percentage string (not raw expression text)
//   2. The Dashboard nowhere renders the literal token `closedData`, `toFixed(`,
//      or `training.dataset_total` — these would only appear if a template literal
//      regressed to literal-text in any current OR future MetricCard.

function mockDashboardQueriesForI7(winRate, datasetTotal) {
  useQuery.mockImplementation(({ queryKey }) => {
    const key = queryKey?.[0]
    if (key === 'shadow-open') return { data: { open_trades: [], open_count: 0 } }
    if (key === 'shadow-closed') return { data: { trades: [], metrics: { win_rate: winRate } } }
    if (key === 'status') return { data: { model_version: 'v1', market_open: false }, isLoading: false }
    if (key === 'training-status') return { data: { dataset_total: datasetTotal } }
    if (key === 'packets') return { data: [] }
    if (key === 'halt-status') return { data: { halted: false } }
    if (key === 'audit-latest') return { data: null }
    if (key === 'cto-report') return { data: null }
    if (key === 'config') return { data: { risk: { starting_capital: 100000 } } }
    if (key === 'shadow-account') return { data: { equity: 100000 } }
    if (key === 'build-score') return { data: null }
    if (key === 'scan-metrics') return { data: null }
    if (key === 'system-index') return { data: null, isLoading: false }
    if (key === 'kpis') return { data: null }
    return { data: undefined, isLoading: false }
  })
}

describe('Dashboard B1+B2 anti-regression: template literals must interpolate, not render as raw text', () => {
  it('Win Rate card renders as percentage string, not as raw template-literal source', () => {
    mockDashboardQueriesForI7(0.425, 1234)
    const { getAllByTestId } = wrap(<Dashboard />)
    const cards = getAllByTestId('metric-card')
    const winRateCard = cards.find(c => c.textContent.toLowerCase().includes('win rate'))
    expect(winRateCard).toBeTruthy()
    // Win rate of 0.425 should render as something like "42.5%"
    expect(winRateCard.textContent).toMatch(/\d+(\.\d+)?%/)
    // The Round-8.F regression rendered `{(closedData.metrics.win_rate * 100).toFixed(1)}%` as literal text.
    // None of these tokens should appear in a working render:
    expect(winRateCard.textContent).not.toContain('closedData')
    expect(winRateCard.textContent).not.toContain('toFixed(')
    expect(winRateCard.textContent).not.toContain('{(')
  })

  it('Dashboard container nowhere contains raw template-literal syntax (catches Win Rate + Model Version + future cards)', () => {
    // Stronger anti-regression: any MetricCard with a stripped-`$` template
    // literal would surface its source code in container.textContent. We match
    // the EXACT broken syntax patterns rather than naked identifiers — e.g.
    // `{(closedData` is the regression syntax (vs `${(closedData` working).
    // Naked `closedData` would false-positive when adjacent text like
    // "market closed" abuts a sibling element starting with "Data".
    mockDashboardQueriesForI7(0.425, 1234)
    const { container } = wrap(<Dashboard />)
    const text = container.textContent
    // Round-8.F regression syntax: `{(...).toFixed(...)}%` rendered as literal text
    expect(text).not.toContain('{(closedData')
    expect(text).not.toContain(').toFixed(')
    // Round-8.F regression syntax: `{training.dataset_total} examples` rendered as literal text
    expect(text).not.toContain('{training.dataset_total')
    expect(text).not.toContain('{training.')
  })
})

describe('TradeHistory G4-extension: llm_conviction_reason in expandable rows', () => {
  it('shows LLM Reasoning label when expanded row has llm_conviction_reason', () => {
    mockTradeHistoryQueries([_closedTradeWithReason])
    const { container } = wrap(<TradeHistory />)
    const rows = container.querySelectorAll('tr')
    rows.forEach(row => fireEvent.click(row))
    expect(container.textContent).toContain('LLM Reasoning')
  })

  it('shows the conviction reason text when row is expanded', () => {
    mockTradeHistoryQueries([_closedTradeWithReason])
    const { container } = wrap(<TradeHistory />)
    const rows = container.querySelectorAll('tr')
    rows.forEach(row => fireEvent.click(row))
    expect(container.textContent).toContain('Breakout above resistance with high relative volume.')
  })

  it('does not show LLM Reasoning when llm_conviction_reason is null', () => {
    mockTradeHistoryQueries([_closedTradeNoReason])
    const { container } = wrap(<TradeHistory />)
    const rows = container.querySelectorAll('tr')
    rows.forEach(row => fireEvent.click(row))
    expect(container.textContent).not.toContain('LLM Reasoning')
  })
})
