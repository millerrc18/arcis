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
// Authoritative backend contract:
//   header  = {version, paper, bootcamp_off, market_open, server_clock}
//   pause   = {is_paused, paused_at, paused_by, reason, resumed_at, updated_at}
const MOCK_HEADER = {
  version: 'v1.2.3',
  paper: true,
  bootcamp_off: true,
  market_open: true,
  server_clock: '2026-06-05T14:30:00Z',
}

const MOCK_PAUSE_RUNNING = {
  is_paused: false,
  paused_at: null,
  paused_by: null,
  reason: null,
  resumed_at: '2026-06-05T14:00:00Z',
  updated_at: '2026-06-05T14:00:00Z',
}
const MOCK_PAUSE_PAUSED = {
  is_paused: true,
  paused_at: '2026-06-05T14:25:00Z',
  paused_by: 'operator',
  reason: 'manual',
  resumed_at: null,
  updated_at: '2026-06-05T14:25:00Z',
}

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

  it('renders bootcamp OFF when bootcamp_off is true', async () => {
    mockFetch()
    renderHeader()
    await waitFor(() => {
      expect(screen.getByText(/bootcamp\s*OFF/i)).toBeInTheDocument()
    })
  })

  it('renders bootcamp ON when bootcamp_off is false', async () => {
    mockFetch({ ...MOCK_HEADER, bootcamp_off: false })
    renderHeader()
    await waitFor(() => {
      expect(screen.getByText(/bootcamp\s*ON/i)).toBeInTheDocument()
    })
  })

  it('renders market Open when market_open is true', async () => {
    mockFetch()
    renderHeader()
    await waitFor(() => {
      expect(screen.getByText(/open/i)).toBeInTheDocument()
    })
  })

  it('renders market Closed when market_open is false', async () => {
    mockFetch({ ...MOCK_HEADER, market_open: false })
    renderHeader()
    await waitFor(() => {
      expect(screen.getByText(/closed/i)).toBeInTheDocument()
    })
  })

  it('renders StalenessBadge for the server_clock freshness', async () => {
    mockFetch()
    renderHeader()
    await waitFor(() => {
      expect(screen.getByTestId('staleness-badge')).toBeInTheDocument()
    })
  })

  it('consumes the REAL contract fields bootcamp_off/market_open/server_clock', async () => {
    // Authoritative contract: bootcamp_off=true => "bootcamp OFF",
    // market_open=true => "Open", server_clock drives the StalenessBadge asOf.
    mockFetch({
      version: 'v2.0.0',
      paper: true,
      bootcamp_off: true,
      market_open: true,
      server_clock: '2026-06-05T14:30:00Z',
    })
    renderHeader()
    await waitFor(() => {
      expect(screen.getByText(/bootcamp\s*OFF/i)).toBeInTheDocument()
    })
    const header = screen.getByTestId('honest-header')
    expect(header.textContent).toMatch(/open/i)
    // server_clock fresh => the staleness badge renders a non-unknown variant
    const badge = screen.getByTestId('staleness-badge')
    expect(badge.className).not.toContain('staleness-unknown')
    // The wrong/legacy fields must NOT be read (no stale OPEN/CLOSED literal mismatch)
    expect(header.textContent).not.toMatch(/undefined/i)
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
  it('shows RUNNING state when is_paused=false', async () => {
    mockFetch(MOCK_HEADER, MOCK_PAUSE_RUNNING)
    renderHeader()
    await waitFor(() => {
      expect(screen.getByTestId('pause-control')).toBeInTheDocument()
    })
    const control = screen.getByTestId('pause-control')
    expect(control.textContent).toMatch(/running/i)
    expect(control.textContent).not.toMatch(/paused/i)
  })

  it('shows PAUSED state when is_paused=true', async () => {
    mockFetch(MOCK_HEADER, MOCK_PAUSE_PAUSED)
    renderHeader()
    await waitFor(() => {
      expect(screen.getByTestId('pause-control')).toBeInTheDocument()
    })
    const control = screen.getByTestId('pause-control')
    expect(control.textContent).toMatch(/paused|resume/i)
  })

  // Law #4: a missing/unknown pause source must NEVER render green "RUNNING"
  // (false-green). Regression-locks the 2026-06-11 PG-down incident where the
  // backend now returns {is_paused: null, state: "unavailable"} (HTTP 200).
  it('does NOT show RUNNING (false-green) when pause source is unavailable', async () => {
    mockFetch(MOCK_HEADER, {
      is_paused: null,
      state: 'unavailable',
      paused_at: null,
      paused_by: null,
      reason: null,
      resumed_at: null,
      updated_at: null,
      detail: 'pause state source unavailable',
    })
    renderHeader()
    await waitFor(() => {
      expect(screen.getByTestId('pause-control')).toBeInTheDocument()
    })
    const control = screen.getByTestId('pause-control')
    // The crux: an unknown source is never rendered as the green RUNNING state.
    expect(control.textContent).not.toMatch(/running/i)
    // And no Pause/Resume toggle is offered for a state we cannot read.
    expect(screen.queryByTestId('pause-toggle-btn')).not.toBeInTheDocument()
    // An explicit unknown indicator is shown instead.
    expect(screen.getByTestId('pause-unknown')).toBeInTheDocument()
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
            text: () => Promise.resolve(JSON.stringify(MOCK_PAUSE_RUNNING)),
          })
        }
        return Promise.resolve({
          ok: true, status: 200,
          text: () => Promise.resolve(JSON.stringify(MOCK_PAUSE_PAUSED)),
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
            text: () => Promise.resolve(JSON.stringify(MOCK_PAUSE_PAUSED)),
          })
        }
        return Promise.resolve({
          ok: true, status: 200,
          text: () => Promise.resolve(JSON.stringify(MOCK_PAUSE_RUNNING)),
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
            text: () => Promise.resolve(JSON.stringify(MOCK_PAUSE_PAUSED)),
          })
        }
        return Promise.resolve({
          ok: true, status: 200,
          text: () => Promise.resolve(JSON.stringify(pauseState ? MOCK_PAUSE_PAUSED : MOCK_PAUSE_RUNNING)),
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
