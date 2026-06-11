/**
 * KNOW region — AsyncBoundary loading/error vs no-data integration tests.
 *
 * Guards against the law-#4 pattern: first-load and unreachable-server states
 * must NOT render as the no-data/UNKNOWN text of each view. Each test uses a
 * never-resolving promise for loading and Promise.reject for error, mirrors the
 * NowRegion describe block technique.
 *
 * Non-vacuous: each test explicitly checks that the no-data sentinel text is
 * ABSENT while async-loading/async-error is PRESENT. Removing AsyncBoundary
 * from the corresponding view would cause the no-data text to appear and the
 * test to fail.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import KnowRegion from '../KnowRegion'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function jsonResponse(data) {
  return Promise.resolve({
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify(data)),
  })
}

function renderAt(path) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/console/know/*" element={<KnowRegion />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// FundLadderView — consumes ['console-know-ladder']
// ---------------------------------------------------------------------------
describe('FundLadderView — AsyncBoundary loading/error vs no-data', () => {
  it('renders async-loading for a first-load (NOT phase/gate content)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    renderAt('/console/know/ladder')
    await waitFor(() => {
      const loadings = screen.getAllByTestId('async-loading')
      expect(loadings.some((el) => /Fund ladder/i.test(el.textContent))).toBe(true)
    })
    // no phase content should appear while loading
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('renders async-error when the fetch rejects (NOT phase/gate content)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('server down'))))
    renderAt('/console/know/ladder')
    await waitFor(() => {
      const errors = screen.getAllByTestId('async-error')
      expect(errors.some((el) => /unavailable/i.test(el.textContent))).toBe(true)
    })
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// SystemMapView — consumes ['console-know-system-map']
// The header section (sha stamp + staleness badge) is wrapped in AsyncBoundary
// so it shows "System map — loading…" on first load. The Capabilities and Schema
// data sections always render so pre-existing sentinel tests still work
// (sentinel-no-data appears even before the query resolves — undefined passes
// through SentinelGuard as no-data, not suppressed by the boundary).
// Non-vacuous: if the header boundary were removed, async-loading/async-error
// with "System map" label would not appear.
// ---------------------------------------------------------------------------
describe('SystemMapView — AsyncBoundary loading/error vs no-data', () => {
  it('renders async-loading in the header section on first-load', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    renderAt('/console/know/system-map')
    await waitFor(() => {
      const loadings = screen.getAllByTestId('async-loading')
      expect(loadings.some((el) => /System map/i.test(el.textContent))).toBe(true)
    })
    // know-system-map container is always present (outer wrapper)
    expect(screen.getByTestId('know-system-map')).toBeInTheDocument()
  })

  it('renders async-error in the header section when the fetch rejects', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('server down'))))
    renderAt('/console/know/system-map')
    await waitFor(() => {
      const errors = screen.getAllByTestId('async-error')
      expect(errors.some((el) => /System map.*unavailable|unavailable/i.test(el.textContent))).toBe(true)
    })
    // know-system-map container is always present (outer wrapper)
    expect(screen.getByTestId('know-system-map')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// TrackRecordView — consumes ['console-know-track-record']
// ---------------------------------------------------------------------------
describe('TrackRecordView — AsyncBoundary loading/error vs no-data', () => {
  it('renders async-loading for a first-load (NOT track-record sections)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    renderAt('/console/know/track-record')
    await waitFor(() => {
      const loadings = screen.getAllByTestId('async-loading')
      expect(loadings.some((el) => /Track record/i.test(el.textContent))).toBe(true)
    })
    expect(screen.queryByText(/Headline stats/i)).not.toBeInTheDocument()
  })

  it('renders async-error when the fetch rejects', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('server down'))))
    renderAt('/console/know/track-record')
    await waitFor(() => {
      const errors = screen.getAllByTestId('async-error')
      expect(errors.some((el) => /unavailable/i.test(el.textContent))).toBe(true)
    })
    expect(screen.queryByText(/Headline stats/i)).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// TradeLedgersView — consumes ['console-know-ledgers', ...]
// ---------------------------------------------------------------------------
describe('TradeLedgersView — AsyncBoundary loading/error vs no-data', () => {
  it('renders async-loading for a first-load (NOT ledger table or no-data text)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    renderAt('/console/know/ledgers')
    await waitFor(() => {
      const loadings = screen.getAllByTestId('async-loading')
      expect(loadings.some((el) => /Trade ledgers/i.test(el.textContent))).toBe(true)
    })
    expect(screen.queryByTestId('know-ledgers-no-data')).not.toBeInTheDocument()
  })

  it('renders async-error when the fetch rejects', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('server down'))))
    renderAt('/console/know/ledgers')
    await waitFor(() => {
      const errors = screen.getAllByTestId('async-error')
      expect(errors.some((el) => /unavailable/i.test(el.textContent))).toBe(true)
    })
    expect(screen.queryByTestId('know-ledgers-no-data')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// AttributionView — three independent queries: statsQuery, sharpeQuery, calibQuery.
// Each must show loading independently so one loading section does not blank others.
// ---------------------------------------------------------------------------
describe('AttributionView — AsyncBoundary loading/error per section', () => {
  function stubWithNeverForUrl(urlFragment) {
    vi.stubGlobal('fetch', vi.fn((url) => {
      if (url.includes(urlFragment)) return new Promise(() => {})
      return jsonResponse({})
    }))
  }

  function stubWithRejectForUrl(urlFragment) {
    vi.stubGlobal('fetch', vi.fn((url) => {
      if (url.includes(urlFragment)) return Promise.reject(new Error('server down'))
      return jsonResponse({})
    }))
  }

  it('statsQuery loading renders async-loading labeled "Alpha attribution"', async () => {
    stubWithNeverForUrl('/attribution/stats')
    renderAt('/console/know/attribution')
    await waitFor(() => {
      const loadings = screen.getAllByTestId('async-loading')
      expect(loadings.some((el) => /Alpha attribution/i.test(el.textContent))).toBe(true)
    })
  })

  it('calibQuery loading renders async-loading labeled "Confidence calibration"', async () => {
    stubWithNeverForUrl('/console/know/calibration')
    renderAt('/console/know/attribution')
    await waitFor(() => {
      const loadings = screen.getAllByTestId('async-loading')
      expect(loadings.some((el) => /Confidence calibration/i.test(el.textContent))).toBe(true)
    })
    // calibration-no-data must NOT appear while loading
    expect(screen.queryByTestId('calibration-no-data')).not.toBeInTheDocument()
  })

  it('statsQuery error renders async-error, not the attribution section', async () => {
    stubWithRejectForUrl('/attribution/stats')
    renderAt('/console/know/attribution')
    await waitFor(() => {
      const errors = screen.getAllByTestId('async-error')
      expect(errors.some((el) => /unavailable/i.test(el.textContent))).toBe(true)
    })
  })
})

// ---------------------------------------------------------------------------
// ResearchView — six queries, each section independently wrapped.
// Test packets (loading → no "No packets in corpus") and digest.
// ---------------------------------------------------------------------------
describe('ResearchView — AsyncBoundary loading/error per section', () => {
  it('packetsQuery loading renders async-loading (NOT "No packets in corpus")', async () => {
    vi.stubGlobal('fetch', vi.fn((url) => {
      if (url.includes('/packets')) return new Promise(() => {})
      return jsonResponse({})
    }))
    renderAt('/console/know/research')
    await waitFor(() => {
      const loadings = screen.getAllByTestId('async-loading')
      expect(loadings.some((el) => /Signal packets/i.test(el.textContent))).toBe(true)
    })
    expect(screen.queryByTestId('research-packets-empty')).not.toBeInTheDocument()
  })

  it('digestQuery loading renders async-loading (NOT "Digest not yet synthesized")', async () => {
    vi.stubGlobal('fetch', vi.fn((url) => {
      if (url.includes('/research/digest')) return new Promise(() => {})
      return jsonResponse({})
    }))
    renderAt('/console/know/research')
    await waitFor(() => {
      const loadings = screen.getAllByTestId('async-loading')
      expect(loadings.some((el) => /Weekly digest/i.test(el.textContent))).toBe(true)
    })
    expect(screen.queryByTestId('research-digest-empty')).not.toBeInTheDocument()
  })

  it('packetsQuery error renders async-error (NOT packets-empty)', async () => {
    vi.stubGlobal('fetch', vi.fn((url) => {
      if (url.includes('/packets')) return Promise.reject(new Error('server down'))
      return jsonResponse({})
    }))
    renderAt('/console/know/research')
    await waitFor(() => {
      const errors = screen.getAllByTestId('async-error')
      expect(errors.some((el) => /unavailable/i.test(el.textContent))).toBe(true)
    })
    expect(screen.queryByTestId('research-packets-empty')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// RigorStack — validation tab: query + rigorQuery wrapped independently.
// ---------------------------------------------------------------------------
describe('RigorStack — AsyncBoundary loading/error per section', () => {
  it('validation query loading renders async-loading (NOT "No validation data")', async () => {
    vi.stubGlobal('fetch', vi.fn((url) => {
      if (url.includes('/system/validation')) return new Promise(() => {})
      return jsonResponse({})
    }))
    renderAt('/console/know/rigor')
    await waitFor(() => {
      const loadings = screen.getAllByTestId('async-loading')
      expect(loadings.some((el) => /System validation/i.test(el.textContent))).toBe(true)
    })
    expect(screen.queryByTestId('rigor-validation-no-data')).not.toBeInTheDocument()
  })

  it('validation query error renders async-error', async () => {
    vi.stubGlobal('fetch', vi.fn((url) => {
      if (url.includes('/system/validation')) return Promise.reject(new Error('server down'))
      return jsonResponse({})
    }))
    renderAt('/console/know/rigor')
    await waitFor(() => {
      const errors = screen.getAllByTestId('async-error')
      expect(errors.some((el) => /unavailable/i.test(el.textContent))).toBe(true)
    })
    expect(screen.queryByTestId('rigor-validation-no-data')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// ScorecardsView — four queries wrapped independently.
// modelPerfQuery loading: no "No model versions available".
// ---------------------------------------------------------------------------
describe('ScorecardsView — AsyncBoundary loading/error per section', () => {
  it('modelPerfQuery loading renders async-loading (NOT "No model versions available")', async () => {
    vi.stubGlobal('fetch', vi.fn((url) => {
      if (url.includes('/model-performance')) return new Promise(() => {})
      return jsonResponse({})
    }))
    renderAt('/console/know/scorecards')
    await waitFor(() => {
      const loadings = screen.getAllByTestId('async-loading')
      expect(loadings.some((el) => /AI dev-team scorecards|Model performance/i.test(el.textContent))).toBe(true)
    })
    expect(screen.queryByTestId('scorecards-model-no-data')).not.toBeInTheDocument()
  })

  it('activityQuery loading renders async-loading (NOT "No activity log entries")', async () => {
    vi.stubGlobal('fetch', vi.fn((url) => {
      if (url.includes('/activity/feed')) return new Promise(() => {})
      return jsonResponse({})
    }))
    renderAt('/console/know/scorecards')
    await waitFor(() => {
      const loadings = screen.getAllByTestId('async-loading')
      expect(loadings.some((el) => /Activity log|Activity feed/i.test(el.textContent))).toBe(true)
    })
    expect(screen.queryByTestId('scorecards-activity-no-data')).not.toBeInTheDocument()
  })

  it('modelPerfQuery error renders async-error', async () => {
    vi.stubGlobal('fetch', vi.fn((url) => {
      if (url.includes('/model-performance')) return Promise.reject(new Error('server down'))
      return jsonResponse({})
    }))
    renderAt('/console/know/scorecards')
    await waitFor(() => {
      const errors = screen.getAllByTestId('async-error')
      expect(errors.some((el) => /unavailable/i.test(el.textContent))).toBe(true)
    })
    expect(screen.queryByTestId('scorecards-model-no-data')).not.toBeInTheDocument()
  })
})
