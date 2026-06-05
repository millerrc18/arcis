/**
 * KnowRegion tests (P3-T4).
 * Tests: overview renders pinned synthesis cards + drill-down entry links;
 * nested routing to child stubs; back-to-overview; ConsoleShell regression.
 *
 * Mirrors NowRegion/DecideRegion test idiom: MemoryRouter + QueryClientProvider.
 * Non-vacuous: each assertion checks a value only present when the component
 * renders the expected structure.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import KnowRegion from '../KnowRegion'
import ConsoleShell from '../../ConsoleShell'

// ---------------------------------------------------------------------------
// Provider helpers
// ---------------------------------------------------------------------------
function renderKnow(initialPath = '/console/know') {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/console/know/*" element={<KnowRegion />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

function renderShell(initialPath = '/console/know') {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/console/*" element={<ConsoleShell />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

// Stub HonestHeader for ConsoleShell tests
vi.mock('../../HonestHeader', () => ({
  default: () => <div data-testid="honest-header-stub">Header</div>,
}))

// fetchApi mock — ConsoleShell test needs minimal mocks for other regions
function jsonResponse(data) {
  return Promise.resolve({
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify(data)),
  })
}

function mockAllApis() {
  vi.stubGlobal('fetch', vi.fn(() => jsonResponse({})))
}

beforeEach(() => {
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// KnowRegion — overview (index route)
// ---------------------------------------------------------------------------
describe('KnowRegion — overview', () => {
  it('renders the know-region root with data-testid="know-region"', () => {
    renderKnow()
    expect(screen.getByTestId('know-region')).toBeInTheDocument()
  })

  it('renders the three pinned synthesis cards: Fund ladder, Track record, Trade ledgers', () => {
    renderKnow()
    expect(screen.getByTestId('know-overview')).toBeInTheDocument()
    expect(screen.getByText(/Fund ladder/i)).toBeInTheDocument()
    expect(screen.getByText(/Track record/i)).toBeInTheDocument()
    expect(screen.getByText(/Trade ledgers/i)).toBeInTheDocument()
  })

  it('renders entry links/cards to all drill-down routes', () => {
    renderKnow()
    // Pinned first-class drill-downs
    expect(screen.getByRole('link', { name: /Fund ladder/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Track record/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Trade ledgers/i })).toBeInTheDocument()
    // Secondary drill-downs
    expect(screen.getByRole('link', { name: /System map/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Rigor stack/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Attribution/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Research/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Scorecards/i })).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// KnowRegion — nested routing to drill-down stubs
// ---------------------------------------------------------------------------
describe('KnowRegion — nested drill-down routing', () => {
  it('navigating to /console/know/ladder renders the ladder stub (data-testid="know-ladder")', () => {
    renderKnow('/console/know/ladder')
    expect(screen.getByTestId('know-ladder')).toBeInTheDocument()
  })

  it('navigating to /console/know/track-record renders the track-record stub (data-testid="know-track-record")', () => {
    renderKnow('/console/know/track-record')
    expect(screen.getByTestId('know-track-record')).toBeInTheDocument()
  })

  it('navigating to /console/know/ledgers renders the ledgers stub (data-testid="know-ledgers")', () => {
    renderKnow('/console/know/ledgers')
    expect(screen.getByTestId('know-ledgers')).toBeInTheDocument()
  })

  it('navigating to /console/know/system-map renders the system-map stub (data-testid="know-system-map")', () => {
    renderKnow('/console/know/system-map')
    expect(screen.getByTestId('know-system-map')).toBeInTheDocument()
  })

  it('navigating to /console/know/rigor renders the rigor stub (data-testid="know-rigor")', () => {
    renderKnow('/console/know/rigor')
    expect(screen.getByTestId('know-rigor')).toBeInTheDocument()
  })

  it('navigating to /console/know/attribution renders the attribution stub (data-testid="know-attribution")', () => {
    renderKnow('/console/know/attribution')
    expect(screen.getByTestId('know-attribution')).toBeInTheDocument()
  })

  it('navigating to /console/know/research renders the research stub (data-testid="know-research")', () => {
    renderKnow('/console/know/research')
    expect(screen.getByTestId('know-research')).toBeInTheDocument()
  })

  it('navigating to /console/know/scorecards renders the scorecards stub (data-testid="know-scorecards")', () => {
    renderKnow('/console/know/scorecards')
    expect(screen.getByTestId('know-scorecards')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// KnowRegion — back-to-overview affordance
// ---------------------------------------------------------------------------
describe('KnowRegion — back-to-overview', () => {
  it('drill-down stubs render a back-to-Know-overview link', () => {
    renderKnow('/console/know/ladder')
    // A link that navigates back to the overview
    const backLink = screen.getByTestId('know-back-link')
    expect(backLink).toBeInTheDocument()
    expect(backLink.getAttribute('href')).toMatch(/\/console\/know$/)
  })
})

// ---------------------------------------------------------------------------
// ConsoleShell regression — KnowRegion replaces placeholder; other routes intact
// ---------------------------------------------------------------------------
describe('ConsoleShell — Know route regression', () => {
  it('Know route renders KnowRegion (data-testid="know-region"), NOT the placeholder text', () => {
    mockAllApis()
    renderShell('/console/know')
    expect(screen.getByTestId('know-region')).toBeInTheDocument()
    expect(screen.queryByText(/Know — coming soon/i)).not.toBeInTheDocument()
  })

  it('Now route still renders data-testid="now-region"', () => {
    mockAllApis()
    renderShell('/console/now')
    expect(screen.getByTestId('now-region')).toBeInTheDocument()
  })

  it('Decide route still renders data-testid="decide-region"', async () => {
    mockAllApis()
    renderShell('/console/decide')
    await waitFor(() => {
      expect(screen.getByTestId('decide-region')).toBeInTheDocument()
    })
  })
})
