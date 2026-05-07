/**
 * IBShadow.jsx — T17 TanStack v5 queryFn arrow-wrap tests
 *
 * Verifies that all useQuery calls in IBShadow pass an arrow-function
 * queryFn (not a bare api method reference) for the getIBShadowSummary query.
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
    getIBShadowSummary: vi.fn(),
    getIBShadowLog: vi.fn(),
  },
}))

vi.mock('../components/MetricCard', () => ({
  default: () => null,
}))

vi.mock('../components/LoadingSpinner', () => ({
  default: () => null,
}))

vi.mock('../components/EmptyState', () => ({
  default: () => null,
}))

import { useQuery } from '@tanstack/react-query'
import IBShadow from './IBShadow'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('IBShadow — T17 queryFn arrow-wrap', () => {
  it('passes an arrow function as queryFn for ib-shadow-summary (not a bare api ref)', () => {
    let summaryQueryFn = null
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'ib-shadow-summary') {
        summaryQueryFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<IBShadow />)

    expect(summaryQueryFn).not.toBeNull()
    expect(typeof summaryQueryFn).toBe('function')
    expect(summaryQueryFn).not.toBe(api.getIBShadowSummary)
  })

  it('all useQuery queryFn values are arrow functions, not bare api method refs', () => {
    const capturedOptions = []
    useQuery.mockImplementation((opts) => {
      capturedOptions.push(opts)
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<IBShadow />)

    expect(capturedOptions.length).toBeGreaterThan(0)
    for (const opts of capturedOptions) {
      expect(typeof opts.queryFn).toBe('function')
      expect(opts.queryFn).not.toBe(api.getIBShadowSummary)
    }
  })
})
