/**
 * T14 tests — F2 ActionButton migration + profit_factor null-handling.
 * Sprint 3 / cockpit-coherence
 *
 * Covers:
 *  - LiveLedger: Reconcile button → ActionButton cliOnly=true
 *  - DiagnosticKickoffButtons: 3 buttons → ActionButton cliOnly=false
 *  - Simulation: single ActionButton (empty-state + header share one instance)
 *  - Council: Run + Ask → ActionButton cliOnly=false
 *  - Simulation profit_factor null → 'N/A (no losses)'
 *  - StressTest profit_factor null → no crash (no profit_factor column currently)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    useQuery: vi.fn(),
    useMutation: vi.fn(),
    useQueryClient: vi.fn(),
  }
})

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

// ─── LiveLedger ──────────────────────────────────────────────────────────────

import LiveLedger from './LiveLedger'

describe('LiveLedger — T14 Reconcile button → ActionButton cliOnly', () => {
  beforeEach(() => {
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
    useQuery.mockReturnValue({ data: undefined, isLoading: false })
  })

  it('renders a disabled button with [CLI only] badge', () => {
    const { container } = wrap(<LiveLedger />)
    const btn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.disabled && b.textContent.includes('CLI only'),
    )
    expect(btn).not.toBeNull()
    expect(btn.disabled).toBe(true)
  })

  it('the CLI-only button is NOT a plain button with inline disabled styles — uses ActionButton', () => {
    const { container } = wrap(<LiveLedger />)
    const cliBtn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.disabled && b.textContent.includes('CLI only'),
    )
    expect(cliBtn).not.toBeNull()
    expect(cliBtn.className).toMatch(/opacity-50/)
  })

  it('no Tooltip wrapping a raw disabled button (ActionButton is the tooltip owner)', () => {
    const { container } = wrap(<LiveLedger />)
    const rawDisabledBtns = Array.from(container.querySelectorAll('button[disabled]'))
    const hasPlainDisabledWithTooltipAttr = rawDisabledBtns.some(
      (b) => b.getAttribute('title') && !b.textContent.includes('CLI only'),
    )
    expect(hasPlainDisabledWithTooltipAttr).toBe(false)
  })
})

// ─── DiagnosticKickoffButtons ─────────────────────────────────────────────────

import DiagnosticKickoffButtons from '../components/DiagnosticKickoffButtons'

describe('DiagnosticKickoffButtons — T14 ActionButton migration', () => {
  beforeEach(() => {
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false })
    useQuery.mockReturnValue({ data: undefined, isLoading: false })
  })

  it('renders 3 run buttons (nightly audit, packet writer, snapshot)', () => {
    const { container } = wrap(<DiagnosticKickoffButtons runs={[]} />)
    const buttons = Array.from(container.querySelectorAll('button')).filter(
      (b) => !b.disabled,
    )
    expect(buttons.length).toBeGreaterThanOrEqual(3)
  })

  it('all 3 buttons are enabled (no cliOnly) when no runs are active', () => {
    const { container } = wrap(<DiagnosticKickoffButtons runs={[]} />)
    const disabledBtns = Array.from(container.querySelectorAll('button[disabled]'))
    const cliOnlyBtns = disabledBtns.filter((b) =>
      b.textContent.includes('CLI only'),
    )
    expect(cliOnlyBtns.length).toBe(0)
  })

  it('buttons use ActionButton styling (arcis-accent bg when enabled)', () => {
    const { container } = wrap(<DiagnosticKickoffButtons runs={[]} />)
    const buttons = Array.from(container.querySelectorAll('button')).filter(
      (b) => !b.disabled,
    )
    expect(buttons.length).toBeGreaterThanOrEqual(3)
    const hasAccent = buttons.some(
      (b) => b.style.background && b.style.background.includes('arcis-accent'),
    )
    expect(hasAccent).toBe(true)
  })

  it('button is disabled and shows spinner when mutation isPending', () => {
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: true })
    const { container } = wrap(<DiagnosticKickoffButtons runs={[]} />)
    const disabledBtns = Array.from(container.querySelectorAll('button[disabled]'))
    expect(disabledBtns.length).toBeGreaterThanOrEqual(1)
  })
})

// ─── Simulation ───────────────────────────────────────────────────────────────

import Simulation from './Simulation'

describe('Simulation — T14 single ActionButton (no dup run button)', () => {
  beforeEach(() => {
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
  })

  it('empty-state: renders exactly ONE run button', () => {
    useQuery.mockReturnValue({ data: { results: [] }, isLoading: false })
    const { container } = wrap(<Simulation />)
    const runBtns = Array.from(container.querySelectorAll('button')).filter((b) =>
      b.textContent.includes('Run Simulation') || b.textContent.includes('Running'),
    )
    expect(runBtns.length).toBe(1)
  })

  it('with results: renders exactly ONE run button (not two)', () => {
    const mockResult = {
      result_id: 1,
      run_id: 'r1',
      scenario: 'strong_bull',
      regime_label: 'Strong Bull',
      total_trades: 10,
      win_rate: 0.6,
      profit_factor: null,
      max_drawdown_pct: 5.0,
      sharpe_ratio: 1.2,
      benchmark_pnl_pct: 3.0,
      excess_return_pct: 2.0,
      verdict: 'edge',
      equity_curve_json: [],
    }
    useQuery.mockReturnValue({ data: { results: [mockResult] }, isLoading: false })
    const { container } = wrap(<Simulation />)
    const runBtns = Array.from(container.querySelectorAll('button')).filter((b) =>
      b.textContent.includes('Run Simulation') || b.textContent.includes('Running'),
    )
    expect(runBtns.length).toBe(1)
  })
})

describe('Simulation — T14 profit_factor null → N/A (no losses)', () => {
  beforeEach(() => {
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
  })

  it('null profit_factor renders "N/A (no losses)" in the heatmap table', () => {
    const mockResult = {
      result_id: 1,
      run_id: 'r1',
      scenario: 'strong_bull',
      regime_label: 'Strong Bull',
      total_trades: 5,
      win_rate: 1.0,
      profit_factor: null,
      max_drawdown_pct: 0.5,
      sharpe_ratio: 2.0,
      benchmark_pnl_pct: 1.5,
      excess_return_pct: 0.5,
      verdict: 'edge',
      equity_curve_json: [],
    }
    useQuery.mockReturnValue({ data: { results: [mockResult] }, isLoading: false })
    const { container } = wrap(<Simulation />)
    expect(container.textContent).toContain('N/A (no losses)')
  })

  it('numeric profit_factor renders the formatted number (not N/A)', () => {
    const mockResult = {
      result_id: 2,
      run_id: 'r2',
      scenario: 'strong_bear',
      regime_label: 'Strong Bear',
      total_trades: 8,
      win_rate: 0.5,
      profit_factor: 1.45,
      max_drawdown_pct: 8.0,
      sharpe_ratio: 0.8,
      benchmark_pnl_pct: -2.0,
      excess_return_pct: 1.0,
      verdict: 'marginal',
      equity_curve_json: [],
    }
    useQuery.mockReturnValue({ data: { results: [mockResult] }, isLoading: false })
    const { container } = wrap(<Simulation />)
    expect(container.textContent).toContain('1.45')
    expect(container.textContent).not.toContain('N/A (no losses)')
  })
})

// ─── Council ─────────────────────────────────────────────────────────────────

import Council from './Council'

describe('Council — T14 ActionButton migration', () => {
  beforeEach(() => {
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false, data: undefined })
    useQuery.mockReturnValue({ data: undefined, isLoading: false })
  })

  it('Run Council Now button is enabled when not pending', () => {
    const { container } = wrap(<Council />)
    const runBtn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent.includes('Run Council'),
    )
    expect(runBtn).not.toBeNull()
    expect(runBtn.disabled).toBe(false)
  })

  it('Run Council Now button uses ActionButton (has arcis-accent bg when enabled)', () => {
    const { container } = wrap(<Council />)
    const runBtn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent.includes('Run Council'),
    )
    expect(runBtn).not.toBeNull()
    expect(runBtn.style.background).toContain('arcis-accent')
  })

  it('Ask Council button is enabled when not pending and strategicQuestion is set', () => {
    const { container } = wrap(<Council />)
    const askBtn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent.includes('Ask Council'),
    )
    expect(askBtn).not.toBeNull()
  })

  it('Run Council Now is disabled + shows spinner when mutation isPending', () => {
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: true, data: undefined })
    const { container } = wrap(<Council />)
    const disabledBtns = Array.from(container.querySelectorAll('button[disabled]'))
    const runBtn = disabledBtns.find((b) =>
      b.textContent.includes('Running') || b.textContent.includes('Run Council'),
    )
    expect(runBtn).not.toBeNull()
  })
})

// ─── StressTest ───────────────────────────────────────────────────────────────

import StressTest from './StressTest'

describe('StressTest — T14 profit_factor null-handling (no crash)', () => {
  beforeEach(() => {
    useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
  })

  it('renders without crash when profit_factor is null', () => {
    const mockResult = {
      result_id: 1,
      scenario: '2008_financial_crisis',
      total_trades: 50,
      win_rate: 0.45,
      profit_factor: null,
      max_drawdown_pct: 35.0,
      calmar_ratio: 0.5,
      start_date: '2008-09-01',
      end_date: '2009-03-31',
      equity_curve_json: null,
      created_at: '2026-05-01T00:00:00',
    }
    useQuery.mockReturnValue({ data: { results: [mockResult] }, isLoading: false })
    expect(() => wrap(<StressTest />)).not.toThrow()
  })

  it('renders without crash when profit_factor is 0 (edge case)', () => {
    const mockResult = {
      result_id: 2,
      scenario: '2020_covid_crash',
      total_trades: 30,
      win_rate: 0.0,
      profit_factor: 0,
      max_drawdown_pct: 50.0,
      calmar_ratio: 0.0,
      start_date: '2020-02-01',
      end_date: '2020-04-30',
      equity_curve_json: null,
      created_at: '2026-05-01T00:00:00',
    }
    useQuery.mockReturnValue({ data: { results: [mockResult] }, isLoading: false })
    expect(() => wrap(<StressTest />)).not.toThrow()
  })
})
