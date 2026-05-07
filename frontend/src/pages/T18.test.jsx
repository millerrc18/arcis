/**
 * T18 — E1.A2 TanStack v5 queryFn arrow-wrap tests
 *
 * Verifies that all useQuery calls in Dashboard, ModelPerformance, StressTest, Training
 * pass an arrow-function queryFn (not a bare api method reference).
 *
 * Bare-ref queryFn causes TanStack Query v5 to pass the QueryFunctionContext as the
 * first argument, which corrupts URL params (e.g., desk=[object Object]).
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
    getStatus: vi.fn(),
    getTrainingStatus: vi.fn(),
    getHaltStatus: vi.fn(),
    getLatestAudit: vi.fn(),
    getConfig: vi.fn(),
    getBuildScore: vi.fn(),
    getSystemIndex: vi.fn(),
    getOpenTrades: vi.fn(),
    getClosedTrades: vi.fn(),
    getPackets: vi.fn(),
    getCtoReport: vi.fn(),
    getAccount: vi.fn(),
    getScanMetrics: vi.fn(),
    getModelPerformance: vi.fn(),
    getStressTestResults: vi.fn(),
    getTrainingVersions: vi.fn(),
    getDataCollectionStats: vi.fn(),
    getShadowDesks: vi.fn().mockResolvedValue([]),
    triggerActionScan: vi.fn(),
    triggerCtoReport: vi.fn(),
    triggerCollectTraining: vi.fn(),
    haltTrading: vi.fn(),
    resumeTrading: vi.fn(),
    submitCommand: vi.fn(),
    getCommandStatus: vi.fn(),
    triggerTrainPipeline: vi.fn(),
    triggerScore: vi.fn(),
  },
  fetchApi: vi.fn(),
}))

vi.mock('../native', () => ({
  hapticWarning: vi.fn(),
  hapticSuccess: vi.fn(),
}))

vi.mock('../components/MetricCard', () => ({ default: () => null }))
vi.mock('../components/LoadingSpinner', () => ({ default: () => null }))
vi.mock('../components/EmptyState', () => ({ default: () => null }))
vi.mock('../components/StatusBadge', () => ({ default: () => null }))
vi.mock('../components/DataTable', () => ({ default: () => null }))
vi.mock('../components/Tooltip', () => ({ default: ({ children }) => children }))
vi.mock('../components/PnlText', () => ({ default: () => null }))
vi.mock('../components/ActivityFeed', () => ({ default: () => null }))
vi.mock('../components/PlatformStatusWidget', () => ({ default: () => null }))
vi.mock('../components/system/QuickStatsPanel', () => ({ default: () => null }))
vi.mock('../components/system/SystemIndexPanel', () => ({ default: () => null }))
vi.mock('../components/system/WhatsNewPanel', () => ({ default: () => null }))
vi.mock('../components/dashboard/KPIStrip', () => ({ default: () => null }))
vi.mock('../components/dashboard/BrokerExceptionsPanel', () => ({ default: () => null }))
vi.mock('../components/dashboard/PreflightStatusCard', () => ({ default: () => null }))
vi.mock('../components/CollectorGrid', () => ({ default: () => null }))
vi.mock('../components/PipelineStatus', () => ({ default: () => null }))
vi.mock('../utils/formatTimestamp', () => ({
  formatRelativeTime: (v) => v,
  formatDate: (v) => v,
}))
vi.mock('react-router-dom', () => ({
  Link: ({ children }) => <a>{children}</a>,
}))
vi.mock('recharts', () => ({
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  ResponsiveContainer: ({ children }) => <div>{children}</div>,
  Area: () => null,
  AreaChart: ({ children }) => <div>{children}</div>,
  LineChart: ({ children }) => <div>{children}</div>,
  Line: () => null,
  Legend: () => null,
  CartesianGrid: () => null,
  ReferenceLine: () => null,
  BarChart: ({ children }) => <div>{children}</div>,
  Bar: () => null,
  Cell: () => null,
}))
vi.mock('lucide-react', () => ({
  TrendingUp: () => null,
  TrendingDown: () => null,
  Minus: () => null,
  AlertTriangle: () => null,
  Zap: () => null,
  ChevronDown: () => null,
  ChevronUp: () => null,
  ChevronRight: () => null,
  Search: () => null,
  ArrowUpDown: () => null,
}))

import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

// ─── Dashboard ───────────────────────────────────────────────────────────────

import Dashboard from './Dashboard'

describe('Dashboard — T18 queryFn arrow-wrap', () => {
  beforeEach(() => {
    api.getShadowDesks.mockResolvedValue([])
  })

  it('queryFn for status is an arrow function, not a bare api ref', () => {
    let capturedFn = null
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'status') {
        capturedFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<Dashboard />)

    expect(capturedFn).not.toBeNull()
    expect(typeof capturedFn).toBe('function')
    expect(capturedFn).not.toBe(api.getStatus)
  })

  it('queryFn for training-status is an arrow function, not a bare api ref', () => {
    let capturedFn = null
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'training-status') {
        capturedFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<Dashboard />)

    expect(capturedFn).not.toBeNull()
    expect(typeof capturedFn).toBe('function')
    expect(capturedFn).not.toBe(api.getTrainingStatus)
  })

  it('queryFn for halt-status is an arrow function, not a bare api ref', () => {
    let capturedFn = null
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'halt-status') {
        capturedFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<Dashboard />)

    expect(capturedFn).not.toBeNull()
    expect(typeof capturedFn).toBe('function')
    expect(capturedFn).not.toBe(api.getHaltStatus)
  })

  it('queryFn for audit-latest is an arrow function, not a bare api ref', () => {
    let capturedFn = null
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'audit-latest') {
        capturedFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<Dashboard />)

    expect(capturedFn).not.toBeNull()
    expect(typeof capturedFn).toBe('function')
    expect(capturedFn).not.toBe(api.getLatestAudit)
  })

  it('queryFn for config is an arrow function, not a bare api ref', () => {
    let capturedFn = null
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'config') {
        capturedFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<Dashboard />)

    expect(capturedFn).not.toBeNull()
    expect(typeof capturedFn).toBe('function')
    expect(capturedFn).not.toBe(api.getConfig)
  })

  it('queryFn for build-score is an arrow function, not a bare api ref', () => {
    let capturedFn = null
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'build-score') {
        capturedFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<Dashboard />)

    expect(capturedFn).not.toBeNull()
    expect(typeof capturedFn).toBe('function')
    expect(capturedFn).not.toBe(api.getBuildScore)
  })

  it('queryFn for system-index is an arrow function, not a bare api ref', () => {
    let capturedFn = null
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'system-index') {
        capturedFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<Dashboard />)

    expect(capturedFn).not.toBeNull()
    expect(typeof capturedFn).toBe('function')
    expect(capturedFn).not.toBe(api.getSystemIndex)
  })
})

// ─── ModelPerformance ─────────────────────────────────────────────────────────

import ModelPerformance from './ModelPerformance'

describe('ModelPerformance — T18 queryFn arrow-wrap', () => {
  it('queryFn for model-performance is an arrow function, not a bare api ref', () => {
    let capturedFn = null
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'model-performance') {
        capturedFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false, error: null }
    })

    render(<ModelPerformance />)

    expect(capturedFn).not.toBeNull()
    expect(typeof capturedFn).toBe('function')
    expect(capturedFn).not.toBe(api.getModelPerformance)
  })
})

// ─── StressTest ───────────────────────────────────────────────────────────────

import StressTest from './StressTest'

describe('StressTest — T18 queryFn arrow-wrap', () => {
  it('queryFn for stress-test-results is an arrow function, not a bare api ref', () => {
    let capturedFn = null
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'stress-test-results') {
        capturedFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<StressTest />)

    expect(capturedFn).not.toBeNull()
    expect(typeof capturedFn).toBe('function')
    expect(capturedFn).not.toBe(api.getStressTestResults)
  })
})

// ─── Training ─────────────────────────────────────────────────────────────────

import Training from './Training'

describe('Training — T18 queryFn arrow-wrap', () => {
  it('queryFn for training-status is an arrow function, not a bare api ref', () => {
    let capturedFn = null
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'training-status') {
        capturedFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<Training />)

    expect(capturedFn).not.toBeNull()
    expect(typeof capturedFn).toBe('function')
    expect(capturedFn).not.toBe(api.getTrainingStatus)
  })

  it('queryFn for training-versions is an arrow function, not a bare api ref', () => {
    let capturedFn = null
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'training-versions') {
        capturedFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<Training />)

    expect(capturedFn).not.toBeNull()
    expect(typeof capturedFn).toBe('function')
    expect(capturedFn).not.toBe(api.getTrainingVersions)
  })

  it('queryFn for data-collection-stats is an arrow function, not a bare api ref', () => {
    let capturedFn = null
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'data-collection-stats') {
        capturedFn = opts.queryFn
      }
      return { data: undefined, isLoading: false, isPending: false, isError: false }
    })

    render(<Training />)

    expect(capturedFn).not.toBeNull()
    expect(typeof capturedFn).toBe('function')
    expect(capturedFn).not.toBe(api.getDataCollectionStats)
  })
})
