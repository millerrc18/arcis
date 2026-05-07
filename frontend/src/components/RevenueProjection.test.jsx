/**
 * RevenueProjection.jsx — T17 TanStack v5 queryFn arrow-wrap tests
 *
 * Verifies that all useQuery calls in RevenueProjection pass an arrow-function
 * queryFn (not a bare api method reference), so TanStack v5 does not receive
 * a QueryFunctionContext as the first arg to the api method.
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
    getProjectionsLive: vi.fn(),
  },
}))

import { useQuery } from '@tanstack/react-query'
import RevenueProjection from './RevenueProjection'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('RevenueProjection — T17 queryFn arrow-wrap', () => {
  it('passes an arrow function as queryFn for projections-live (not a bare api method ref)', () => {
    let projectionsQueryFn = null
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'projections-live') {
        projectionsQueryFn = opts.queryFn
      }
      return { data: undefined, isPending: false, isError: false }
    })

    render(<RevenueProjection />)

    expect(projectionsQueryFn).not.toBeNull()
    expect(typeof projectionsQueryFn).toBe('function')
    expect(projectionsQueryFn).not.toBe(api.getProjectionsLive)
  })

  it('all useQuery queryFn values are arrow functions, not bare api method refs', () => {
    const capturedOptions = []
    useQuery.mockImplementation((opts) => {
      capturedOptions.push(opts)
      return { data: undefined, isPending: false, isError: false }
    })

    render(<RevenueProjection />)

    expect(capturedOptions.length).toBeGreaterThan(0)
    for (const opts of capturedOptions) {
      expect(typeof opts.queryFn).toBe('function')
      expect(opts.queryFn).not.toBe(api.getProjectionsLive)
    }
  })
})
