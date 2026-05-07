/**
 * T19 — E1.A3 TanStack v5 queryFn arrow-wrap tests
 *
 * Verifies that all useQuery calls in Docs, Validation, and TradeHistory
 * pass an arrow-function queryFn (not a bare api method reference).
 *
 * Bare refs cause TanStack Query v5 to pass the QueryFunctionContext as the
 * first argument (e.g. `desk` param in getSharpeAttribution), which gets
 * serialized as `[object Object]` in the URL — the primary bug fixed here.
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
    getDocsList: vi.fn(),
    getDoc: vi.fn(),
    getValidation: vi.fn(),
    getClosedTrades: vi.fn(),
    getSharpeAttribution: vi.fn(),
    runValidation: vi.fn(),
    submitCommand: vi.fn(),
    getCommandStatus: vi.fn(),
  },
}))

vi.mock('../components/LoadingSpinner', () => ({ default: () => null }))
vi.mock('../components/TimeoutCell', () => ({ default: () => null }))
vi.mock('../components/Tooltip', () => ({ default: ({ children }) => <>{children}</> }))
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
  ComposedChart: ({ children }) => <div>{children}</div>,
}))
vi.mock('lucide-react', () => ({
  Search: () => null,
  ArrowLeft: () => null,
  FileText: () => null,
  TrendingUp: () => null,
  TrendingDown: () => null,
  Clock: () => null,
  Target: () => null,
  Shield: () => null,
  Activity: () => null,
}))

import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

// ─── Docs ─────────────────────────────────────────────────────────────────────

import Docs from './Docs'

describe('Docs — T19 queryFn arrow-wrap', () => {
  it('queryFn for docs-list is an arrow function, not a bare api ref', () => {
    let docsListQueryFn = null
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'docs-list') {
        docsListQueryFn = opts.queryFn
      }
      return { data: undefined, isLoading: false }
    })

    render(<Docs />)

    expect(docsListQueryFn).not.toBeNull()
    expect(typeof docsListQueryFn).toBe('function')
    expect(docsListQueryFn).not.toBe(api.getDocsList)
  })
})

// ─── Validation ───────────────────────────────────────────────────────────────

import Validation from './Validation'

describe('Validation — T19 queryFn arrow-wrap', () => {
  it('queryFn for validation is an arrow function, not a bare api ref', () => {
    let validationQueryFn = null
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'validation') {
        validationQueryFn = opts.queryFn
      }
      return { data: undefined, isLoading: false }
    })

    render(<Validation />)

    expect(validationQueryFn).not.toBeNull()
    expect(typeof validationQueryFn).toBe('function')
    expect(validationQueryFn).not.toBe(api.getValidation)
  })
})

// ─── TradeHistory ─────────────────────────────────────────────────────────────

import TradeHistory from './TradeHistory'

describe('TradeHistory — T19 queryFn arrow-wrap (primary bug: getSharpeAttribution bare ref)', () => {
  it('queryFn for sharpe-attribution is an arrow function, not bare api.getSharpeAttribution', () => {
    let attributionQueryFn = null
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'sharpe-attribution') {
        attributionQueryFn = opts.queryFn
      }
      return { data: undefined, isLoading: false }
    })

    render(<TradeHistory />)

    expect(attributionQueryFn).not.toBeNull()
    expect(typeof attributionQueryFn).toBe('function')
    expect(attributionQueryFn).not.toBe(api.getSharpeAttribution)
  })
})
