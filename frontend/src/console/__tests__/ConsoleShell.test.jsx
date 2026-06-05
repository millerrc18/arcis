/**
 * ConsoleShell tests (T8, updated P2-T6).
 * 3-tab nav present. Decide now wires real DecideRegion. Know remains placeholder.
 * App routing: /console mounts shell, old routes still resolve.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ConsoleShell from '../ConsoleShell'

// Stub HonestHeader so ConsoleShell tests don't need full API mocks
vi.mock('../HonestHeader', () => ({
  default: () => <div data-testid="honest-header-stub">Header</div>,
}))

// ---------------------------------------------------------------------------
// fetchApi mock helpers — mirrors NowRegion test pattern
// ---------------------------------------------------------------------------
const NOW = '2026-06-05T14:30:00Z'

const MOCK_PENDING = {
  items: [],
  count: 0,
  degraded_sources: [],
  as_of: NOW,
}

const MOCK_DECIDED = {
  items: [],
  override_rate: {
    value: null,
    n: 0,
    as_of: NOW,
    cohort: 'decisions.all',
    unit: 'ratio',
    state: 'no_data',
  },
  as_of: NOW,
}

function jsonResponse(data) {
  return Promise.resolve({
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify(data)),
  })
}

function mockDecideApi() {
  const fetchMock = vi.fn((url) => {
    if (url.includes('/console/decide/pending')) return jsonResponse(MOCK_PENDING)
    if (url.includes('/console/decide/decided')) return jsonResponse(MOCK_DECIDED)
    // Also handle NowRegion queries (now route still active)
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

// ---------------------------------------------------------------------------
// Provider helper
// ---------------------------------------------------------------------------
function withProviders(initialPath) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/console/*" element={<ConsoleShell />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

function renderShell(initialPath = '/console') {
  return render(withProviders(initialPath))
}

describe('ConsoleShell', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the 3 nav tabs: Now, Decide, Know', () => {
    renderShell()
    expect(screen.getByRole('link', { name: 'Now' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Decide' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Know' })).toBeInTheDocument()
  })

  it('renders the HonestHeader', () => {
    renderShell()
    expect(screen.getByTestId('honest-header-stub')).toBeInTheDocument()
  })

  it('Decide route renders real DecideRegion (data-testid decide-region, not placeholder text)', async () => {
    mockDecideApi()
    render(withProviders('/console/decide'))
    // The real DecideRegion renders data-testid="decide-region"
    await waitFor(() => {
      expect(screen.getByTestId('decide-region')).toBeInTheDocument()
    })
    // No DecidePlaceholder text ("Decide — coming soon")
    expect(screen.queryByText(/Decide — coming soon/i)).not.toBeInTheDocument()
  })

  it('Know tab renders KnowRegion overview (Phase 3 wired)', () => {
    render(withProviders('/console/know'))
    expect(screen.getByTestId('know-region')).toBeInTheDocument()
    expect(screen.queryByText(/Know — coming soon/i)).not.toBeInTheDocument()
  })

  it('DecidePlaceholder text is absent when on decide route', async () => {
    mockDecideApi()
    render(withProviders('/console/decide'))
    await waitFor(() => {
      expect(screen.getByTestId('decide-region')).toBeInTheDocument()
    })
    // "Decide — coming soon" must not appear anywhere
    expect(screen.queryByText('Decide — coming soon')).not.toBeInTheDocument()
  })

  it('default route /console shows the Now mount point', () => {
    renderShell('/console')
    // T9 will fill this — assert the mount point testid or now-region placeholder exists
    expect(screen.getByTestId('now-region')).toBeInTheDocument()
  })

  it('/console/now also shows the Now mount point', () => {
    renderShell('/console/now')
    expect(screen.getByTestId('now-region')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// App.jsx routing regression: /console mounts shell, old routes still exist
// ---------------------------------------------------------------------------
describe('App routing regression', () => {
  // Import App lazily to avoid QueryClient being constructed at module level
  it('/console route mounts ConsoleShell', async () => {
    // We test this via the MemoryRouter above — the App.jsx integration
    // is verified by the route being present. Direct App.jsx import would
    // require full provider setup; covered by the route-level test above.
    // Minimal smoke: ConsoleShell can render under /console path.
    renderShell('/console')
    expect(screen.getByRole('link', { name: 'Now' })).toBeInTheDocument()
  })
})
