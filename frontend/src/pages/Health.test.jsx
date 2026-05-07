/**
 * Health page tests — E8 IB-status feature flag.
 * Sprint 3 / T11 — IS_CLOUD gates getIBStatus useQuery.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, useQuery: vi.fn() }
})

// IS_CLOUD will be controlled per test via vi.doMock + dynamic import.
// For the static import approach, we mock the module and use a mutable ref.
let _IS_CLOUD = false
vi.mock('../config', () => ({
  get IS_CLOUD() { return _IS_CLOUD },
}))

import { useQuery } from '@tanstack/react-query'
import Health from './Health'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const _hshsData = {
  hshs: 72.5,
  dimensions: { performance: 80, model_quality: 70, data_asset: 75, flywheel_velocity: 65, defensibility: 72 },
  weights: { performance: 0.3, model_quality: 0.2, data_asset: 0.2, flywheel_velocity: 0.15, defensibility: 0.15 },
  phase: 'growth',
}

const _buildData = {
  build_score: 65.0,
  components: { gate_velocity: 60, system_health: 70, data_asset_value: 65, model_quality: 68, research_velocity: 62, reliability: 66 },
  history_7d: [60, 61, 62, 63, 64, 65, 65],
  phase_progress: {},
  data_asset_detail: {},
}

beforeEach(() => {
  _IS_CLOUD = false
  useQuery.mockReset()
})

describe('Health — E8 IB-status feature flag', () => {
  it('IS_CLOUD=true → getIBStatus useQuery called with enabled=false (fetch not fired)', () => {
    _IS_CLOUD = true
    const queryCalls = []
    useQuery.mockImplementation((opts) => {
      queryCalls.push(opts)
      const key = opts.queryKey?.[0]
      if (key === 'hshs-live') return { data: _hshsData, isLoading: false }
      if (key === 'build-score') return { data: _buildData, isLoading: false }
      if (key === 'training-history') return { data: { versions: [] }, isLoading: false }
      if (key === 'ib-status') return { data: undefined, isLoading: false }
      return { data: undefined, isLoading: false }
    })

    wrap(<Health />)

    const ibCall = queryCalls.find(c => c.queryKey?.[0] === 'ib-status')
    expect(ibCall).toBeTruthy()
    expect(ibCall.enabled).toBe(false)
  })

  it('IS_CLOUD=true && no ibData → renders "Not available in cloud mode" banner', () => {
    _IS_CLOUD = true
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'hshs-live') return { data: _hshsData, isLoading: false }
      if (key === 'build-score') return { data: _buildData, isLoading: false }
      if (key === 'training-history') return { data: { versions: [] }, isLoading: false }
      if (key === 'ib-status') return { data: undefined, isLoading: false }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<Health />)
    expect(container.textContent).toContain('Not available in cloud mode')
  })

  it('IS_CLOUD=false → getIBStatus useQuery called with enabled=true (fetch fires)', () => {
    _IS_CLOUD = false
    const queryCalls = []
    useQuery.mockImplementation((opts) => {
      queryCalls.push(opts)
      const key = opts.queryKey?.[0]
      if (key === 'hshs-live') return { data: _hshsData, isLoading: false }
      if (key === 'build-score') return { data: _buildData, isLoading: false }
      if (key === 'training-history') return { data: { versions: [] }, isLoading: false }
      if (key === 'ib-status') return { data: undefined, isLoading: false }
      return { data: undefined, isLoading: false }
    })

    wrap(<Health />)

    const ibCall = queryCalls.find(c => c.queryKey?.[0] === 'ib-status')
    expect(ibCall).toBeTruthy()
    expect(ibCall.enabled).toBe(true)
  })
})

describe('Health — C2 LoadingState migration', () => {
  it('hasHshs=false renders EmptyState via LoadingState (not bare arcis-card with muted text)', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'hshs-live') return { data: { hshs: 0, dimensions: {}, weights: {}, phase: 'early' }, isLoading: false, isError: false }
      if (key === 'build-score') return { data: _buildData, isLoading: false, isError: false }
      if (key === 'training-history') return { data: { versions: [] }, isLoading: false, isError: false }
      return { data: undefined, isLoading: false, isError: false }
    })
    const { container } = wrap(<Health />)
    const emptyState = container.querySelector('.flex.items-center.justify-center')
    expect(emptyState).toBeTruthy()
    expect(container.textContent).toContain('Collecting HSHS data...')
  })

  it('hshsLoading=true AND buildLoading=true renders loading spinner via LoadingState', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'hshs-live') return { data: undefined, isLoading: true, isError: false }
      if (key === 'build-score') return { data: undefined, isLoading: true, isError: false }
      if (key === 'training-history') return { data: undefined, isLoading: false, isError: false }
      return { data: undefined, isLoading: false, isError: false }
    })
    const { container } = wrap(<Health />)
    expect(container.querySelector('[data-testid="loading-spinner"]')).toBeTruthy()
  })
})
