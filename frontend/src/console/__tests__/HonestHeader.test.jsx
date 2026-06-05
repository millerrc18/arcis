/**
 * HonestHeader tests (T8).
 * All values come from mocked API responses — never hardcoded.
 * PAUSE control must reflect state and fire POST on toggle (non-vacuous).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import HonestHeader from '../HonestHeader'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function renderHeader() {
  return render(
    <MemoryRouter>
      <HonestHeader />
    </MemoryRouter>
  )
}

// ---------------------------------------------------------------------------
// fetch mock baseline
// ---------------------------------------------------------------------------
const MOCK_HEADER = {
  version: 'v1.2.3',
  paper: true,
  bootcamp: false,
  market_state: 'OPEN',
  clock: '2026-06-05T14:30:00Z',
}

const MOCK_PAUSE_RUNNING = { paused: false }
const MOCK_PAUSE_PAUSED = { paused: true }

beforeEach(() => {
  vi.restoreAllMocks()
})

function mockFetch(headerData = MOCK_HEADER, pauseData = MOCK_PAUSE_RUNNING) {
  vi.stubGlobal('fetch', vi.fn((url) => {
    if (url.includes('/console/header')) {
      return Promise.resolve({
        ok: true,
        status: 200,
        text: () => Promise.resolve(JSON.stringify(headerData)),
      })
    }
    if (url.includes('/console/pause')) {
      return Promise.resolve({
        ok: true,
        status: 200,
        text: () => Promise.resolve(JSON.stringify(pauseData)),
      })
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      text: () => Promise.resolve('{}'),
    })
  }))
}

// ---------------------------------------------------------------------------
// Tests: renders API-driven values
// ---------------------------------------------------------------------------
describe('HonestHeader', () => {
  it('renders version from API response', async () => {
    mockFetch()
    renderHeader()
    await waitFor(() => {
      expect(screen.getByText(/v1\.2\.3/)).toBeInTheDocument()
    })
  })

  it('renders PAPER indicator from API response', async () => {
    mockFetch()
    renderHeader()
    await waitFor(() => {
      expect(screen.getByText(/PAPER/i)).toBeInTheDocument()
    })
  })

  it('renders bootcamp OFF when bootcamp is false', async () => {
    mockFetch()
    renderHeader()
    await waitFor(() => {
      expect(screen.getByText(/bootcamp\s*OFF/i)).toBeInTheDocument()
    })
  })

  it('renders bootcamp ON when bootcamp is true', async () => {
    mockFetch({ ...MOCK_HEADER, bootcamp: true })
    renderHeader()
    await waitFor(() => {
      expect(screen.getByText(/bootcamp\s*ON/i)).toBeInTheDocument()
    })
  })

  it('renders market state from API response', async () => {
    mockFetch()
    renderHeader()
    await waitFor(() => {
      expect(screen.getByText(/OPEN/)).toBeInTheDocument()
    })
  })

  it('renders StalenessBadge for the clock/market freshness', async () => {
    mockFetch()
    renderHeader()
    await waitFor(() => {
      expect(screen.getByTestId('staleness-badge')).toBeInTheDocument()
    })
  })

  it('does NOT hardcode version — shows API value not a literal placeholder', async () => {
    mockFetch({ ...MOCK_HEADER, version: 'v9.8.7' })
    renderHeader()
    await waitFor(() => {
      expect(screen.getByText(/v9\.8\.7/)).toBeInTheDocument()
    })
    expect(screen.queryByText(/v1\.2\.3/)).not.toBeInTheDocument()
  })

  // ---------------------------------------------------------------------------
  // PAUSE control — non-vacuous: must show state AND fire POST on toggle
  // ---------------------------------------------------------------------------
  it('shows RUNNING state when paused=false', async () => {
    mockFetch(MOCK_HEADER, { paused: false })
    renderHeader()
    await waitFor(() => {
      expect(screen.getByTestId('pause-control')).toBeInTheDocument()
    })
    const control = screen.getByTestId('pause-control')
    expect(control.textContent).toMatch(/running|resume/i)
  })

  it('shows PAUSED state when paused=true', async () => {
    mockFetch(MOCK_HEADER, { paused: true })
    renderHeader()
    await waitFor(() => {
      expect(screen.getByTestId('pause-control')).toBeInTheDocument()
    })
    const control = screen.getByTestId('pause-control')
    expect(control.textContent).toMatch(/paused|resume/i)
  })

  it('fires POST /api/console/pause with action=pause when running and toggled', async () => {
    const fetchMock = vi.fn((url, opts) => {
      if (url.includes('/console/header')) {
        return Promise.resolve({
          ok: true, status: 200,
          text: () => Promise.resolve(JSON.stringify(MOCK_HEADER)),
        })
      }
      if (url.includes('/console/pause')) {
        // GET returns running; POST returns paused
        if (!opts || opts.method !== 'POST') {
          return Promise.resolve({
            ok: true, status: 200,
            text: () => Promise.resolve(JSON.stringify({ paused: false })),
          })
        }
        return Promise.resolve({
          ok: true, status: 200,
          text: () => Promise.resolve(JSON.stringify({ paused: true })),
        })
      }
      return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve('{}') })
    })
    vi.stubGlobal('fetch', fetchMock)

    renderHeader()
    // Wait for header to load
    await waitFor(() => expect(screen.getByTestId('pause-control')).toBeInTheDocument())

    // Click the pause toggle button
    const btn = screen.getByTestId('pause-toggle-btn')
    fireEvent.click(btn)

    // Assert POST was fired with action=pause
    await waitFor(() => {
      const postCalls = fetchMock.mock.calls.filter(
        ([url, opts]) => url.includes('/console/pause') && opts?.method === 'POST'
      )
      expect(postCalls.length).toBeGreaterThan(0)
      const body = JSON.parse(postCalls[0][1].body)
      expect(body.action).toBe('pause')
    })
  })

  it('fires POST /api/console/pause with action=resume when paused and toggled', async () => {
    const fetchMock = vi.fn((url, opts) => {
      if (url.includes('/console/header')) {
        return Promise.resolve({
          ok: true, status: 200,
          text: () => Promise.resolve(JSON.stringify(MOCK_HEADER)),
        })
      }
      if (url.includes('/console/pause')) {
        if (!opts || opts.method !== 'POST') {
          return Promise.resolve({
            ok: true, status: 200,
            text: () => Promise.resolve(JSON.stringify({ paused: true })),
          })
        }
        return Promise.resolve({
          ok: true, status: 200,
          text: () => Promise.resolve(JSON.stringify({ paused: false })),
        })
      }
      return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve('{}') })
    })
    vi.stubGlobal('fetch', fetchMock)

    renderHeader()
    await waitFor(() => expect(screen.getByTestId('pause-control')).toBeInTheDocument())

    const btn = screen.getByTestId('pause-toggle-btn')
    fireEvent.click(btn)

    await waitFor(() => {
      const postCalls = fetchMock.mock.calls.filter(
        ([url, opts]) => url.includes('/console/pause') && opts?.method === 'POST'
      )
      expect(postCalls.length).toBeGreaterThan(0)
      const body = JSON.parse(postCalls[0][1].body)
      expect(body.action).toBe('resume')
    })
  })

  it('UI updates to reflect new pause state after POST', async () => {
    let pauseState = false
    const fetchMock = vi.fn((url, opts) => {
      if (url.includes('/console/header')) {
        return Promise.resolve({
          ok: true, status: 200,
          text: () => Promise.resolve(JSON.stringify(MOCK_HEADER)),
        })
      }
      if (url.includes('/console/pause')) {
        if (opts?.method === 'POST') {
          pauseState = true
          return Promise.resolve({
            ok: true, status: 200,
            text: () => Promise.resolve(JSON.stringify({ paused: true })),
          })
        }
        return Promise.resolve({
          ok: true, status: 200,
          text: () => Promise.resolve(JSON.stringify({ paused: pauseState })),
        })
      }
      return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve('{}') })
    })
    vi.stubGlobal('fetch', fetchMock)

    renderHeader()
    await waitFor(() => expect(screen.getByTestId('pause-control')).toBeInTheDocument())

    // Initially running
    expect(screen.getByTestId('pause-control').textContent).toMatch(/running/i)

    fireEvent.click(screen.getByTestId('pause-toggle-btn'))

    // After toggle, must show paused
    await waitFor(() => {
      expect(screen.getByTestId('pause-control').textContent).toMatch(/paused/i)
    })
  })
})
