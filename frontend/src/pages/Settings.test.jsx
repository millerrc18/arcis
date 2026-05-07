/**
 * Settings page tests — E3 SettingInput defense-in-depth precision clamp.
 * Sprint 3 / T11 — float32 noise defense.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, useQuery: vi.fn(), useMutation: vi.fn(), useQueryClient: vi.fn() }
})

vi.mock('../config', () => ({ IS_CLOUD: false }))

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

// Import only the SettingInput logic by pulling from the module.
// Settings.jsx exports default; we need to test SettingInput's behavior via
// the rendered output. We'll render Settings and target specific inputs.
import Settings from './Settings'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const _baseConfig = {
  risk: { planned_risk_pct_min: 0.005000000001, planned_risk_pct_max: 0.01 },
  shadow_trading: { max_positions: 5, enabled: true, timeout_days: 10 },
  strategies: { pullback: { timeout_days: 14 } },
  llm: { min_conviction_score: 70, enabled: true },
  scheduler: { scan_interval_minutes: 15 },
  live_trading: { ib: { shadow_mode: false, paper_routing: false, paper_routing_threshold: 80, port: 4002, client_id: 1 } },
}

// Settings query uses settings || config for nested reads; include the full shape.
const _baseSettings = {
  overrides: {},
  risk: { planned_risk_pct_min: 0.005000000001, planned_risk_pct_max: 0.01 },
  shadow_trading: { max_positions: 5, enabled: true, timeout_days: 10 },
  strategies: { pullback: { timeout_days: 14 } },
  llm: { min_conviction_score: 70, enabled: true },
  automation: { scan_interval_minutes: 15 },
  live_trading: { ib: { shadow_mode: false, paper_routing: false, paper_routing_threshold: 80, port: 4002, client_id: 1 } },
}

beforeEach(() => {
  useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
  useMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useQuery.mockReturnValue({ data: undefined, isLoading: false })
})

const IB_WHY_DISABLED = 'Effect requires local IB Gateway connection'

describe('F2.B IB toggle migration — visually-disabled with whyDisabled tooltip', () => {
  function setup() {
    useQuery.mockImplementation(({ queryKey }) => {
      if (queryKey[0] === 'config') return { data: _baseConfig, isLoading: false }
      if (queryKey[0] === 'settings') return { data: _baseSettings, isLoading: false }
      return { data: undefined, isLoading: false }
    })
  }

  it('shadow_mode toggle is rendered as disabled button', () => {
    setup()
    const { container } = wrap(<Settings />)
    const buttons = Array.from(container.querySelectorAll('button'))
    const shadowModeBtn = buttons.find(b => b.disabled && b.closest('[data-ib-key="live_trading.ib.shadow_mode"]'))
    expect(shadowModeBtn).toBeTruthy()
  })

  it('shadow_mode row shows whyDisabled text', () => {
    setup()
    const { getAllByText } = wrap(<Settings />)
    const matches = getAllByText(IB_WHY_DISABLED)
    expect(matches.length).toBeGreaterThanOrEqual(1)
  })

  it('paper_routing toggle is rendered as disabled button', () => {
    setup()
    const { container } = wrap(<Settings />)
    const buttons = Array.from(container.querySelectorAll('button'))
    const paperRoutingBtn = buttons.find(b => b.disabled && b.closest('[data-ib-key="live_trading.ib.paper_routing"]'))
    expect(paperRoutingBtn).toBeTruthy()
  })

  it('paper_routing row shows whyDisabled text', () => {
    setup()
    const { getAllByText } = wrap(<Settings />)
    const matches = getAllByText(IB_WHY_DISABLED)
    expect(matches.length).toBeGreaterThanOrEqual(2)
  })

  it('clicking shadow_mode disabled toggle does NOT fire onUpdate mutation', () => {
    const mutate = vi.fn()
    useMutation.mockReturnValue({ mutate, isPending: false })
    setup()
    const { container } = wrap(<Settings />)
    const disabledBtn = container.querySelector('[data-ib-key="live_trading.ib.shadow_mode"] button[disabled]')
    expect(disabledBtn).toBeTruthy()
    fireEvent.click(disabledBtn)
    expect(mutate).not.toHaveBeenCalled()
  })

  it('clicking paper_routing disabled toggle does NOT fire onUpdate mutation', () => {
    const mutate = vi.fn()
    useMutation.mockReturnValue({ mutate, isPending: false })
    setup()
    const { container } = wrap(<Settings />)
    const disabledBtn = container.querySelector('[data-ib-key="live_trading.ib.paper_routing"] button[disabled]')
    expect(disabledBtn).toBeTruthy()
    fireEvent.click(disabledBtn)
    expect(mutate).not.toHaveBeenCalled()
  })

  it('non-IB toggle (shadow_trading.enabled) remains functional — click fires mutation', () => {
    const mutate = vi.fn()
    useMutation.mockReturnValue({ mutate, isPending: false })
    setup()
    const { container } = wrap(<Settings />)
    const tradingToggles = Array.from(
      container.querySelectorAll('button.rounded-full')
    ).filter(b => !b.disabled)
    expect(tradingToggles.length).toBeGreaterThan(0)
    fireEvent.click(tradingToggles[0])
    expect(mutate).toHaveBeenCalled()
  })
})

describe('SettingInput — E3 float-precision clamp', () => {
  it('clamps initial float32 artifact: 0.005000000001 with step=0.001 renders 0.005', () => {
    useQuery.mockImplementation(({ queryKey }) => {
      if (queryKey[0] === 'config') return { data: _baseConfig, isLoading: false }
      if (queryKey[0] === 'settings') return { data: _baseSettings, isLoading: false }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<Settings />)
    const riskMinInput = Array.from(container.querySelectorAll('input[type="number"]'))
      .find(el => el.value === '0.005' || el.value === '0.005000000001')
    expect(riskMinInput).toBeTruthy()
    expect(riskMinInput.value).toBe('0.005')
  })

  it('onBlur: drift value 0.005000000001 typed → emits clamped 0.005', () => {
    const mutate = vi.fn()
    useMutation.mockReturnValue({ mutate, isPending: false })
    useQuery.mockImplementation(({ queryKey }) => {
      if (queryKey[0] === 'config') return { data: _baseConfig, isLoading: false }
      if (queryKey[0] === 'settings') return { data: _baseSettings, isLoading: false }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<Settings />)
    const riskMinInput = Array.from(container.querySelectorAll('input[type="number"]'))
      .find(el => parseFloat(el.value).toFixed(3) === '0.005')
    expect(riskMinInput).toBeTruthy()

    fireEvent.change(riskMinInput, { target: { value: '0.005000000001' } })
    fireEvent.blur(riskMinInput, { target: { value: '0.005000000001' } })

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({ value: 0.005 })
    )
  })

  it('onBlur: user types 0.006 (1 step from 0.005) → emits 0.006 unchanged', () => {
    const mutate = vi.fn()
    useMutation.mockReturnValue({ mutate, isPending: false })
    useQuery.mockImplementation(({ queryKey }) => {
      if (queryKey[0] === 'config') return { data: _baseConfig, isLoading: false }
      if (queryKey[0] === 'settings') return { data: _baseSettings, isLoading: false }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<Settings />)
    const riskMinInput = Array.from(container.querySelectorAll('input[type="number"]'))
      .find(el => parseFloat(el.value).toFixed(3) === '0.005')
    expect(riskMinInput).toBeTruthy()

    fireEvent.change(riskMinInput, { target: { value: '0.006' } })
    fireEvent.blur(riskMinInput, { target: { value: '0.006' } })

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({ value: 0.006 })
    )
  })
})
