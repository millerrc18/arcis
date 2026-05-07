/**
 * Attribution.jsx — T20 TanStack v5 queryFn arrow-wrap tests
 *
 * Verifies that the useQuery call in Attribution passes an arrow-function
 * queryFn (not a bare api.getAttributionStats reference), so TanStack v5
 * does not receive a QueryFunctionContext as the first arg to the api method.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { api } from '../api'

vi.mock('@tanstack/react-query', () => ({
  useQuery: vi.fn(),
}))

vi.mock('../config', () => ({
  IS_CLOUD: false,
  API_BASE: '',
  API_SECRET: '',
}))

vi.mock('../api', () => ({
  api: {
    getAttributionStats: vi.fn(),
  },
}))

vi.mock('../components/LoadingSpinner', () => ({
  default: () => null,
}))

vi.mock('../components/StatusBadge', () => ({
  default: () => null,
}))

vi.mock('recharts', () => ({
  BarChart: () => null,
  Bar: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  ResponsiveContainer: ({ children }) => children,
  Cell: () => null,
}))

import { useQuery } from '@tanstack/react-query'
import Attribution from './Attribution'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('Attribution — T20 queryFn arrow-wrap', () => {
  it('passes an arrow function as queryFn for attribution-stats (not a bare api ref)', () => {
    let attributionQueryFn = null
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'attribution-stats') {
        attributionQueryFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<Attribution />)

    expect(attributionQueryFn).not.toBeNull()
    expect(typeof attributionQueryFn).toBe('function')
    expect(attributionQueryFn).not.toBe(api.getAttributionStats)
  })

  it('all useQuery queryFn values are arrow functions, not bare api method refs', () => {
    const capturedOptions = []
    useQuery.mockImplementation((opts) => {
      capturedOptions.push(opts)
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<Attribution />)

    expect(capturedOptions.length).toBeGreaterThan(0)
    for (const opts of capturedOptions) {
      expect(typeof opts.queryFn).toBe('function')
      expect(opts.queryFn).not.toBe(api.getAttributionStats)
    }
  })
})
