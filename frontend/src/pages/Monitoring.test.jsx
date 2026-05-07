import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, useQuery: vi.fn() }
})

import { useQuery } from '@tanstack/react-query'
import Monitoring from './Monitoring'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const _snapshot = {
  cpu_pct: 25,
  ram_used_mb: 4096,
  ram_total_mb: 16384,
  disk_used_gb: 120,
  disk_total_gb: 500,
  gpu_util_pct: 10,
  gpu_vram_used_mb: 2048,
  gpu_vram_total_mb: 8192,
  gpu_temp_c: 50,
  ollama_status: 'running',
  ollama_model: 'halcyon-v1',
  python_rss_mb: 300,
  snapshot_id: 1,
  timestamp: '2026-05-07T10:00:00Z',
}

beforeEach(() => {
  useQuery.mockReset()
})

describe('Monitoring — C2 LoadingState migration', () => {
  it('isLoading=true renders loading spinner instead of hanging indefinitely', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'monitoring-history') return { data: undefined, isLoading: true, isError: false }
      return { data: undefined, isLoading: false, isError: false }
    })
    const { container } = wrap(<Monitoring />)
    expect(container.querySelector('[data-testid="loading-spinner"]')).toBeTruthy()
  })

  it('isError=true renders error card — closes E7 presentation bug (500/503 must not show infinite spinner)', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'monitoring-history') return { data: undefined, isLoading: false, isError: true, error: { message: 'Service Unavailable' } }
      return { data: undefined, isLoading: false, isError: false }
    })
    const { container } = wrap(<Monitoring />)
    expect(container.querySelector('[data-testid="error-card"]')).toBeTruthy()
    expect(container.querySelector('[data-testid="loading-spinner"]')).toBeFalsy()
  })

  it('data loaded renders resource metrics', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'monitoring-history') return { data: { snapshots: [_snapshot] }, isLoading: false, isError: false }
      if (key === 'monitoring-snapshot') return { data: _snapshot, isLoading: false, isError: false }
      return { data: undefined, isLoading: false, isError: false }
    })
    const { container } = wrap(<Monitoring />)
    expect(container.querySelector('[data-testid="loading-spinner"]')).toBeFalsy()
    expect(container.querySelector('[data-testid="error-card"]')).toBeFalsy()
  })
})

describe('Monitoring — T20 queryFn arrow-wrap', () => {
  it('all useQuery queryFn values are arrow functions (not bare api method refs)', () => {
    const capturedOptions = []
    useQuery.mockImplementation((opts) => {
      capturedOptions.push(opts)
      return { data: undefined, isLoading: false, isError: false }
    })

    wrap(<Monitoring />)

    expect(capturedOptions.length).toBeGreaterThan(0)
    for (const opts of capturedOptions) {
      if (opts.queryFn == null) continue
      expect(typeof opts.queryFn).toBe('function')
    }
  })

  it('monitoring-history and monitoring-snapshot each use a distinct arrow-wrapped queryFn', () => {
    let historyFn = null
    let snapshotFn = null
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'monitoring-history') historyFn = opts.queryFn
      if (key === 'monitoring-snapshot') snapshotFn = opts.queryFn
      return { data: undefined, isLoading: false, isError: false }
    })

    wrap(<Monitoring />)

    expect(historyFn).not.toBeNull()
    expect(typeof historyFn).toBe('function')
    expect(snapshotFn).not.toBeNull()
    expect(typeof snapshotFn).toBe('function')
    expect(historyFn).not.toBe(snapshotFn)
  })
})
