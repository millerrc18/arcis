/**
 * T21 — E1.B2 TanStack v5 queryFn arrow-wrap tests
 *
 * Verifies that all useQuery calls in LiveLedger, Council, Simulation, ShadowLedger
 * pass an arrow-function queryFn (not a bare api method reference).
 *
 * These are the regression sources for the desk=[object Object] URL bug (audit
 * findings 03-C1 + 05-C3): when queryFn is a bare ref, TanStack Query v5 passes
 * the QueryFunctionContext as the first argument, which becomes the `desk` param
 * and is serialized as `[object Object]` in the URL.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { api } from '../api'

vi.mock('@tanstack/react-query', () => ({
  useQuery: vi.fn(),
  useQueryClient: vi.fn(),
  useMutation: vi.fn(),
}))

vi.mock('../config', () => ({
  IS_CLOUD: false,
  API_BASE: '',
  API_SECRET: '',
}))

vi.mock('../api', () => ({
  api: {
    getLiveSummary: vi.fn(),
    getLiveTrades: vi.fn(),
    getCouncilLatest: vi.fn(),
    getCouncilHistory: vi.fn(),
    getSimulationResults: vi.fn(),
    getOpenTrades: vi.fn(),
    getClosedTrades: vi.fn(),
    getAccount: vi.fn(),
    runSimulation: vi.fn(),
    triggerReconcile: vi.fn(),
    runCouncil: vi.fn(),
    askCouncil: vi.fn(),
    updateSettings: vi.fn(),
  },
}))

vi.mock('../components/MetricCard', () => ({ default: () => null }))
vi.mock('../components/LoadingSpinner', () => ({ default: () => null }))
vi.mock('../components/EmptyState', () => ({ default: () => null }))
vi.mock('../components/ActionButton', () => ({ default: (props) => <button disabled={props.disabled}>{props.label}</button> }))
vi.mock('../components/TimeoutCell', () => ({ default: () => null }))
vi.mock('../components/StatusBadge', () => ({ default: () => null }))
vi.mock('../utils/formatTimestamp', () => ({ formatTimestamp: (v) => v }))
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
  LineChart: ({ children }) => <div>{children}</div>,
  Line: () => null,
  Legend: () => null,
}))
vi.mock('lucide-react', () => ({
  TrendingUp: () => null,
  ChevronDown: () => null,
  ChevronRight: () => null,
  Search: () => null,
  ArrowUpDown: () => null,
}))

import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

// ─── LiveLedger ──────────────────────────────────────────────────────────────

import LiveLedger from './LiveLedger'

describe('LiveLedger — T21 queryFn arrow-wrap', () => {
  it('queryFn for live-summary is an arrow function, not a bare api ref', () => {
    let summaryQueryFn = null
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'live-summary') {
        summaryQueryFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<LiveLedger />)

    expect(summaryQueryFn).not.toBeNull()
    expect(typeof summaryQueryFn).toBe('function')
    expect(summaryQueryFn).not.toBe(api.getLiveSummary)
  })

  it('queryFn for live-trades is an arrow function, not a bare api ref', () => {
    let tradesQueryFn = null
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'live-trades') {
        tradesQueryFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<LiveLedger />)

    expect(tradesQueryFn).not.toBeNull()
    expect(typeof tradesQueryFn).toBe('function')
    expect(tradesQueryFn).not.toBe(api.getLiveTrades)
  })
})

// ─── Council ─────────────────────────────────────────────────────────────────

import Council from './Council'

describe('Council — T21 queryFn arrow-wrap', () => {
  it('queryFn for council-latest is an arrow function, not a bare api ref', () => {
    let latestQueryFn = null
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false, data: undefined })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'council-latest') {
        latestQueryFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<Council />)

    expect(latestQueryFn).not.toBeNull()
    expect(typeof latestQueryFn).toBe('function')
    expect(latestQueryFn).not.toBe(api.getCouncilLatest)
  })
})

// ─── Simulation ───────────────────────────────────────────────────────────────

import Simulation from './Simulation'

describe('Simulation — T21 queryFn arrow-wrap', () => {
  it('queryFn for simulation-results is an arrow function, not a bare api ref', () => {
    let simQueryFn = null
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'simulation-results') {
        simQueryFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<Simulation />)

    expect(simQueryFn).not.toBeNull()
    expect(typeof simQueryFn).toBe('function')
    expect(simQueryFn).not.toBe(api.getSimulationResults)
  })
})

// ─── ShadowLedger ────────────────────────────────────────────────────────────

import ShadowLedger from './ShadowLedger'

describe('ShadowLedger — T21 queryFn arrow-wrap (primary bug sites: 03-C1 + 05-C3)', () => {
  it('queryFn for shadow-open is an arrow function, not bare api.getOpenTrades (L476 bug fix)', () => {
    let openQueryFn = null
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'shadow-open') {
        openQueryFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<ShadowLedger />)

    expect(openQueryFn).not.toBeNull()
    expect(typeof openQueryFn).toBe('function')
    expect(openQueryFn).not.toBe(api.getOpenTrades)
  })

  it('queryFn for shadow-account is an arrow function, not bare api.getAccount (L478 bug fix)', () => {
    let accountQueryFn = null
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'shadow-account') {
        accountQueryFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<ShadowLedger />)

    expect(accountQueryFn).not.toBeNull()
    expect(typeof accountQueryFn).toBe('function')
    expect(accountQueryFn).not.toBe(api.getAccount)
  })

  it('queryFn for live-trades-for-ledger is an arrow function, not bare api.getLiveTrades (L481 bug fix)', () => {
    let liveQueryFn = null
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'live-trades-for-ledger') {
        liveQueryFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<ShadowLedger />)

    expect(liveQueryFn).not.toBeNull()
    expect(typeof liveQueryFn).toBe('function')
    expect(liveQueryFn).not.toBe(api.getLiveTrades)
  })
})
