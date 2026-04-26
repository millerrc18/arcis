/**
 * Dark-mode token tests for system sub-components and PlatformStatusWidget.
 * Track 1.5 / Round 8.E — I4 (QuickStatsPanel/SystemIndexPanel dark mode)
 * + I5 (PlatformStatusWidget dark mode) findings.
 *
 * Verifies that no hardcoded Tailwind dark: variants remain in the
 * rendered output — components must use arcis CSS variable tokens instead.
 */
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, useQuery: vi.fn() }
})
vi.mock('../../api', () => ({ api: {}, getPlatformStrategies: vi.fn() }))
vi.mock('react-router-dom', () => ({ Link: ({ children }) => children }))

import { useQuery } from '@tanstack/react-query'
import QuickStatsPanel from './QuickStatsPanel'
import SystemIndexPanel from './SystemIndexPanel'
import PlatformStatusWidget from '../PlatformStatusWidget'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const _systemIndexData = {
  counts: { total: 5, needs_review: 1 },
  states: [
    {
      name: 'shadow_trade_cohort',
      category: 'trading',
      live: { status: 'ok', result: { value: 35 } },
      delta_since_last_view: 2,
    },
    {
      name: 'strategy_registry_state',
      category: 'research',
      live: { status: 'ok', result: { value: 3 } },
      delta_since_last_view: null,
    },
    {
      name: 'training_corpus',
      category: 'model',
      live: { status: 'ok', result: { value: 120 } },
      delta_since_last_view: 5,
    },
    {
      name: 'bootcamp_mode',
      category: 'system',
      live: { status: 'ok', result: { enabled: true } },
      delta_since_last_view: null,
    },
  ],
  actions: [],
  systems: [],
  decisions: [],
}

// ── QuickStatsPanel ───────────────────────────────────────────────────

describe('QuickStatsPanel dark mode tokens', () => {
  it('loading state uses arcis CSS var, not dark:bg-slate class', () => {
    const { container } = render(<QuickStatsPanel data={null} isLoading={true} />)
    expect(container.innerHTML).not.toContain('dark:bg-slate')
  })

  it('data state uses arcis CSS var, not dark:bg-slate class', () => {
    const { container } = render(
      <QuickStatsPanel data={_systemIndexData} isLoading={false} />
    )
    expect(container.innerHTML).not.toContain('dark:bg-slate')
  })

  it('data state uses arcis CSS var, not dark:border-slate class', () => {
    const { container } = render(
      <QuickStatsPanel data={_systemIndexData} isLoading={false} />
    )
    expect(container.innerHTML).not.toContain('dark:border-slate')
  })

  it('renders stat values from data', () => {
    const { container } = render(
      <QuickStatsPanel data={_systemIndexData} isLoading={false} />
    )
    expect(container.textContent).toContain('35')
  })

  it('renders null when data is null and not loading', () => {
    const { container } = render(<QuickStatsPanel data={null} isLoading={false} />)
    expect(container.firstChild).toBeNull()
  })
})

// ── SystemIndexPanel ─────────────────────────────────────────────────

describe('SystemIndexPanel dark mode tokens', () => {
  it('loading state uses arcis CSS var, not dark:bg-slate class', () => {
    const { container } = render(<SystemIndexPanel data={null} isLoading={true} />)
    expect(container.innerHTML).not.toContain('dark:bg-slate')
  })

  it('empty state uses arcis CSS var, not dark:bg-slate class', () => {
    const { container } = render(
      <SystemIndexPanel data={{ states: [], actions: [], systems: [], decisions: [] }} isLoading={false} />
    )
    expect(container.innerHTML).not.toContain('dark:bg-slate')
  })

  it('data state uses arcis CSS var, not dark:bg-slate class', () => {
    const { container } = wrap(
      <SystemIndexPanel data={_systemIndexData} isLoading={false} />
    )
    expect(container.innerHTML).not.toContain('dark:bg-slate')
  })
})

// ── PlatformStatusWidget ─────────────────────────────────────────────

describe('PlatformStatusWidget dark mode tokens', () => {
  it('uses arcis CSS var, not dark:bg-slate class when strategies present', () => {
    useQuery.mockReturnValue({
      data: [
        { strategy_id: 's1', current_status: 'shadow_trading', last_backtest_at: '2026-04-01T00:00:00Z' },
        { strategy_id: 's2', current_status: 'backtested', last_backtest_at: null },
      ],
      isLoading: false,
    })
    const { container } = wrap(<PlatformStatusWidget />)
    expect(container.innerHTML).not.toContain('dark:bg-slate')
  })

  it('does not use bg-white class when strategies present', () => {
    useQuery.mockReturnValue({
      data: [
        { strategy_id: 's1', current_status: 'production', last_backtest_at: '2026-04-01T00:00:00Z' },
      ],
      isLoading: false,
    })
    const { container } = wrap(<PlatformStatusWidget />)
    expect(container.innerHTML).not.toContain('bg-white')
  })
})
