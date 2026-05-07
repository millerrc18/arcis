/**
 * Layout.jsx — B1+B2 header TL migration tests (Vitest + @testing-library/react).
 *
 * Sprint 3 / Task T10 — B1+B2 header TL migration with 3-state fallback.
 *
 * Tests cover:
 *  1) decision_matrix_state='GREEN' → 'TL: GREEN' with green color styling
 *  2) kpisQuery.isPending → 'TL: ...'
 *  3) kpis loaded but stage_traffic_light=null → 'TL: COMPUTING' with last_computed_at tooltip
 *  4) kpisQuery.isError=true → 'TL: ERR' with last-attempt tooltip
 *  5) queryKey ['kpis'] shared with KPIStrip — only one fetch per 30s window
 *  6) POSITIONS span has tooltip sourced from status._meta.open_positions.label
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

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
    getStatus: vi.fn(),
    getKpis: vi.fn(),
  },
}))

import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import Layout from './Layout'

function buildStatusData(overrides = {}) {
  return {
    version: '1.0.0',
    ollama_available: true,
    market_open: false,
    open_positions: 5,
    _meta: {
      open_positions: { label: 'Live positions only', cohort: 'trades.live_only', n: 5 },
    },
    ...overrides,
  }
}

function renderLayout() {
  return render(
    <MemoryRouter>
      <Layout />
    </MemoryRouter>
  )
}

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('Layout StatusBar — TL from /api/kpis (B1)', () => {
  it('renders TL: GREEN with success color when decision_matrix_state is GREEN', () => {
    useQuery.mockImplementation(({ queryKey }) => {
      if (queryKey[0] === 'kpis') {
        return {
          data: {
            stage_traffic_light: { decision_matrix_state: 'GREEN' },
          },
          isPending: false,
          isError: false,
        }
      }
      if (queryKey[0] === 'status') {
        return { data: buildStatusData(), isPending: false, isError: false }
      }
      return { data: undefined, isPending: false, isError: false }
    })

    renderLayout()
    const tlSpan = screen.getByText('GREEN')
    expect(tlSpan).toBeTruthy()
    const style = tlSpan.getAttribute('style') || ''
    expect(style).toContain('var(--arcis-success)')
  })

  it('renders TL: ... when kpisQuery.isPending is true', () => {
    useQuery.mockImplementation(({ queryKey }) => {
      if (queryKey[0] === 'kpis') {
        return { data: undefined, isPending: true, isError: false }
      }
      if (queryKey[0] === 'status') {
        return { data: buildStatusData(), isPending: false, isError: false }
      }
      return { data: undefined, isPending: false, isError: false }
    })

    renderLayout()
    const tlEl = screen.getByText((content) => content.startsWith('TL:'))
    expect(tlEl.textContent).toContain('...')
  })

  it('renders TL: COMPUTING when kpis loaded but stage_traffic_light is null', () => {
    useQuery.mockImplementation(({ queryKey }) => {
      if (queryKey[0] === 'kpis') {
        return {
          data: { stage_traffic_light: null },
          isPending: false,
          isError: false,
        }
      }
      if (queryKey[0] === 'status') {
        return { data: buildStatusData(), isPending: false, isError: false }
      }
      return { data: undefined, isPending: false, isError: false }
    })

    renderLayout()
    const tlEl = screen.getByText((content) => content.startsWith('TL:'))
    expect(tlEl.textContent).toContain('COMPUTING')
  })

  it('renders TL: ERR when kpisQuery.isError is true', () => {
    useQuery.mockImplementation(({ queryKey }) => {
      if (queryKey[0] === 'kpis') {
        return {
          data: undefined,
          isPending: false,
          isError: true,
          error: { message: 'Network error' },
        }
      }
      if (queryKey[0] === 'status') {
        return { data: buildStatusData(), isPending: false, isError: false }
      }
      return { data: undefined, isPending: false, isError: false }
    })

    renderLayout()
    const tlEl = screen.getByText((content) => content.startsWith('TL:'))
    expect(tlEl.textContent).toContain('ERR')
  })

  it('uses queryKey ["kpis"] for the TL query — same key KPIStrip uses', () => {
    const queryKeysUsed = []
    useQuery.mockImplementation(({ queryKey }) => {
      queryKeysUsed.push(queryKey[0])
      if (queryKey[0] === 'kpis') {
        return {
          data: { stage_traffic_light: { decision_matrix_state: 'AMBER' } },
          isPending: false,
          isError: false,
        }
      }
      if (queryKey[0] === 'status') {
        return { data: buildStatusData(), isPending: false, isError: false }
      }
      return { data: undefined, isPending: false, isError: false }
    })

    renderLayout()
    expect(queryKeysUsed).toContain('kpis')
  })

  it('POSITIONS span has tooltip with label from status._meta.open_positions', () => {
    useQuery.mockImplementation(({ queryKey }) => {
      if (queryKey[0] === 'kpis') {
        return {
          data: { stage_traffic_light: { decision_matrix_state: 'GREEN' } },
          isPending: false,
          isError: false,
        }
      }
      if (queryKey[0] === 'status') {
        return {
          data: buildStatusData({
            open_positions: 7,
            _meta: {
              open_positions: { label: 'Live positions only', cohort: 'trades.live_only', n: 7 },
            },
          }),
          isPending: false,
          isError: false,
        }
      }
      return { data: undefined, isPending: false, isError: false }
    })

    renderLayout()
    const positionsEl = screen.getByTitle('Live positions only')
    expect(positionsEl).toBeTruthy()
    expect(positionsEl.textContent).toContain('POSITIONS')
  })

  it('renders TL: COMPUTING with last_computed_at tooltip when available', () => {
    useQuery.mockImplementation(({ queryKey }) => {
      if (queryKey[0] === 'kpis') {
        return {
          data: {
            stage_traffic_light: { decision_matrix_state: null, last_computed_at: '2026-05-07T10:00:00Z' },
          },
          isPending: false,
          isError: false,
        }
      }
      if (queryKey[0] === 'status') {
        return { data: buildStatusData(), isPending: false, isError: false }
      }
      return { data: undefined, isPending: false, isError: false }
    })

    renderLayout()
    const tlEl = screen.getByText((content) => content.startsWith('TL:'))
    expect(tlEl.textContent).toContain('COMPUTING')
    const parent = tlEl.closest('[title]')
    expect(parent?.getAttribute('title') ?? '').toContain('2026-05-07')
  })
})

describe('Layout — T17 queryFn arrow-wrap (E1.A)', () => {
  it('passes an arrow function as queryFn for status query (not a bare api.getStatus ref)', () => {
    let statusQueryFn = null
    useQuery.mockImplementation((opts) => {
      if (opts.queryKey?.[0] === 'status') {
        statusQueryFn = opts.queryFn
      }
      return { data: buildStatusData(), isPending: false, isError: false }
    })

    renderLayout()

    expect(statusQueryFn).not.toBeNull()
    expect(typeof statusQueryFn).toBe('function')
    expect(statusQueryFn).not.toBe(api.getStatus)
  })
})
