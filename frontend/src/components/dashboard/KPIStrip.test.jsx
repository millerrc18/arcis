/**
 * KPIStrip snapshot tests (Vitest + @testing-library/react).
 * Track 1.5 / Round 8.B — 5-KPI hero strip.
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import KPIStrip from './KPIStrip'

const _kpisGreen = {
  n_trades: 160,
  n_minimum_trl: 150,
  as_of: '2026-04-25T12:00:00Z',
  instrumentation_pct: 100.0,
  rf_adjusted_excess_sharpe: { value: 6.14, p_value: 0.03, ci_lower: 0.11, ci_upper: 12.17, status: 'green' },
  spy_relative_sharpe: { value: 2.10, p_value: 0.05, ci_lower: 0.05, ci_upper: 4.15, status: 'green' },
  win_rate: { value: 0.69, n_wins: 110, n_losses: 50, status: 'green' },
  stage_traffic_light: { status: 'green', S: 6.14, t_stat: 2.17, ci_lower: 0.11, decision_matrix_state: 'GREEN' },
  promotion_gate: { votes_passed: 4, votes_total: 5, status: 'green', caption: '4/5 methods passed' },
}

const _kpisAmber = {
  n_trades: 35,
  n_minimum_trl: 150,
  as_of: '2026-04-25T12:00:00Z',
  instrumentation_pct: 85.7,
  rf_adjusted_excess_sharpe: { value: 6.14, p_value: 0.43, ci_lower: -0.85, ci_upper: 13.13, status: 'amber' },
  spy_relative_sharpe: { value: 2.10, p_value: 0.43, ci_lower: -0.85, ci_upper: 5.05, status: 'amber' },
  win_rate: { value: 0.50, n_wins: 18, n_losses: 17, status: 'amber' },
  stage_traffic_light: { status: 'amber', S: 6.14, t_stat: 1.10, ci_lower: -0.85, decision_matrix_state: 'HOLD' },
  promotion_gate: { votes_passed: null, votes_total: 5, status: 'blue', caption: 'MinTRL: gate not yet evaluable (N=35, need 150)' },
}

const _kpisRed = {
  n_trades: 35,
  n_minimum_trl: 150,
  as_of: '2026-04-25T12:00:00Z',
  instrumentation_pct: 40.0,
  rf_adjusted_excess_sharpe: { value: -1.5, p_value: 0.02, ci_lower: -3.0, ci_upper: -0.1, status: 'red' },
  spy_relative_sharpe: { value: -1.0, p_value: 0.05, ci_lower: -2.5, ci_upper: 0.5, status: 'red' },
  win_rate: { value: 0.40, n_wins: 14, n_losses: 21, status: 'red' },
  stage_traffic_light: { status: 'red', S: -1.5, t_stat: -2.1, ci_lower: -3.0, decision_matrix_state: 'HALT' },
  promotion_gate: { votes_passed: null, votes_total: 5, status: 'blue', caption: 'MinTRL: gate not yet evaluable (N=35, need 150)' },
}

const _kpisEmpty = {
  n_trades: 0,
  n_minimum_trl: 150,
  as_of: '2026-04-25T12:00:00Z',
  instrumentation_pct: null,
  rf_adjusted_excess_sharpe: { value: null, p_value: null, ci_lower: null, ci_upper: null, status: 'unknown' },
  spy_relative_sharpe: { value: null, p_value: null, ci_lower: null, ci_upper: null, status: 'unknown' },
  win_rate: { value: null, n_wins: 0, n_losses: 0, status: 'unknown' },
  stage_traffic_light: { status: 'unknown', S: null, t_stat: null, ci_lower: null, decision_matrix_state: 'HALT' },
  promotion_gate: { votes_passed: null, votes_total: 5, status: 'blue', caption: 'MinTRL: gate not yet evaluable — no closed trades yet' },
}

describe('KPIStrip', () => {
  it('renders 5 KPI cards from green fixture', () => {
    const { container } = render(<KPIStrip kpis={_kpisGreen} />)
    expect(container).toMatchSnapshot()
    const text = container.textContent
    expect(text).toContain('rf-Adj Excess Sharpe')
    expect(text).toContain('SPY-Relative Sharpe')
    expect(text).toContain('Win Rate')
    expect(text).toContain('Stage Traffic Light')
    expect(text).toContain('Promotion Gate')
  })

  it('renders amber status pill on amber fixture', () => {
    const { container } = render(<KPIStrip kpis={_kpisAmber} />)
    expect(container).toMatchSnapshot()
    expect(container.innerHTML).toContain('amber')
  })

  it('renders red status pill on red fixture', () => {
    const { container } = render(<KPIStrip kpis={_kpisRed} />)
    expect(container).toMatchSnapshot()
    expect(container.innerHTML).toContain('red')
  })

  it('renders blue pill for promotion gate below MinTRL', () => {
    const { container } = render(<KPIStrip kpis={_kpisAmber} />)
    const text = container.textContent
    expect(text).toContain('MinTRL')
  })

  it('renders empty-DB state with no closed trades caption', () => {
    const { container } = render(<KPIStrip kpis={_kpisEmpty} />)
    expect(container).toMatchSnapshot()
    const text = container.textContent
    expect(text).toContain('no closed trades')
  })

  it('renders N caption below each card', () => {
    const { container } = render(<KPIStrip kpis={_kpisGreen} />)
    const text = container.textContent
    expect(text).toContain('N=160')
  })

  it('renders instrumentation badge when pct is present', () => {
    const { container } = render(<KPIStrip kpis={_kpisGreen} />)
    const text = container.textContent
    expect(text).toContain('v3')
  })

  it('renders Stage-2 progress bar in promotion gate card', () => {
    const { container } = render(<KPIStrip kpis={_kpisAmber} />)
    const text = container.textContent
    expect(text).toContain('35')
    expect(text).toContain('150')
  })

  it('renders loading skeleton when kpis is null', () => {
    const { container } = render(<KPIStrip kpis={null} />)
    expect(container).toMatchSnapshot()
    expect(container.textContent).toContain('Loading')
  })
})
