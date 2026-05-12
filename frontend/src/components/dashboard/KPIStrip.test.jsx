/**
 * KPIStrip snapshot tests (Vitest + @testing-library/react).
 * Track 1.5 / Round 8.B — 5-KPI hero strip.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, act, fireEvent } from '@testing-library/react'
import KPIStrip, { KPICard } from './KPIStrip'

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
    expect(text).toContain('Total P&L')
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

  it('renders MinTRL caption in TrafficLight tooltip when below MinTRL', () => {
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

  it('renders TrafficLight vote count in tooltip when promotion_gate has votes_passed', () => {
    const { container } = render(<KPIStrip kpis={_kpisGreen} />)
    const text = container.textContent
    expect(text).toContain('4/5')
  })

  it('renders loading skeleton when kpis is null', () => {
    const { container } = render(<KPIStrip kpis={null} />)
    expect(container).toMatchSnapshot()
    expect(container.textContent).toContain('Loading')
  })

  it('renders explicit error state when KPI query fails', () => {
    const { container } = render(<KPIStrip kpis={null} error />)
    expect(container.textContent).toContain('KPI data unavailable')
  })

  it('tolerates partial KPI payloads without crashing', () => {
    const partial = {
      n_trades: 7,
      promotion_gate: { status: 'blue', caption: 'waiting on more trades' },
    }
    const { container } = render(<KPIStrip kpis={partial} />)
    expect(container.textContent).toContain('Total P&L')
    expect(container.textContent).toContain('rf-Adj Excess Sharpe')
    expect(container.textContent).toContain('Stage Traffic Light')
  })
})

describe('KPICard meta prop', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders cohort badge with n= and last dot-segment when meta is defined', () => {
    const meta = { cohort: 'kpi.canonical', label: 'Fully instrumented (v3)', n: 5 }
    const { container } = render(
      <KPICard title="Test" value="1.23" status="green" meta={meta} />
    )
    expect(container.textContent).toContain('n=5 · canonical')
  })

  it('shows full label in tooltip when meta is defined and badge is hovered', () => {
    vi.useFakeTimers()
    const meta = { cohort: 'kpi.canonical', label: 'Fully instrumented (v3)', n: 5 }
    const { container } = render(
      <KPICard title="Test" value="1.23" status="green" meta={meta} />
    )
    const badge = container.querySelector('[data-testid="kpi-meta-badge"]')
    fireEvent.mouseEnter(badge)
    act(() => { vi.runAllTimers() })
    expect(container.textContent).toContain('Fully instrumented (v3)')
  })

  it('renders no badge when meta is undefined (backwards-compat)', () => {
    const { container } = render(
      <KPICard title="Test" value="1.23" status="green" />
    )
    expect(container.querySelector('[data-testid="kpi-meta-badge"]')).toBeNull()
  })
})

describe('KPIStrip _meta envelope wiring', () => {
  it('renders kpi-meta-badge on rf-Adj card when _meta.rf_adjusted_excess_sharpe is present', () => {
    const kpisWithMeta = {
      ..._kpisGreen,
      _meta: {
        rf_adjusted_excess_sharpe: { cohort: 'kpi.canonical', label: 'Instrumented + quarantine-filtered', n: 160 },
      },
    }
    const { container } = render(<KPIStrip kpis={kpisWithMeta} />)
    const badges = container.querySelectorAll('[data-testid="kpi-meta-badge"]')
    expect(badges.length).toBeGreaterThanOrEqual(1)
    const badgeTexts = Array.from(badges).map(b => b.textContent)
    expect(badgeTexts.some(t => t.includes('n=160') && t.includes('canonical'))).toBe(true)
  })

  it('renders kpi-meta-badge on win-rate card when _meta.win_rate is present', () => {
    const kpisWithMeta = {
      ..._kpisGreen,
      _meta: {
        win_rate: { cohort: 'kpi.canonical', label: 'Instrumented + quarantine-filtered', n: 160 },
      },
    }
    const { container } = render(<KPIStrip kpis={kpisWithMeta} />)
    const badges = container.querySelectorAll('[data-testid="kpi-meta-badge"]')
    expect(badges.length).toBeGreaterThanOrEqual(1)
    const badgeTexts = Array.from(badges).map(b => b.textContent)
    expect(badgeTexts.some(t => t.includes('n=160') && t.includes('canonical'))).toBe(true)
  })

  it('renders two kpi-meta-badges when both rf_adjusted and win_rate meta are present', () => {
    const kpisWithBothMeta = {
      ..._kpisGreen,
      _meta: {
        rf_adjusted_excess_sharpe: { cohort: 'kpi.canonical', label: 'Rf-adj cohort', n: 160 },
        win_rate: { cohort: 'kpi.canonical', label: 'Win-rate cohort', n: 160 },
      },
    }
    const { container } = render(<KPIStrip kpis={kpisWithBothMeta} />)
    const badges = container.querySelectorAll('[data-testid="kpi-meta-badge"]')
    expect(badges.length).toBe(2)
  })

  it('renders no kpi-meta-badges when _meta is absent from kpis', () => {
    const { container } = render(<KPIStrip kpis={_kpisGreen} />)
    const badges = container.querySelectorAll('[data-testid="kpi-meta-badge"]')
    expect(badges.length).toBe(0)
  })
})

describe('TotalPnlDollarsCard (T12)', () => {
  const _kpisWithPnl = {
    ..._kpisGreen,
    total_pnl_dollars: 1234.56,
    _meta: {
      total_pnl_dollars: { cohort: 'kpi.canonical', label: 'Fully instrumented (v3)', n: 160 },
    },
  }

  it('renders Total P&L card with formatted dollar value and meta badge', () => {
    const { container } = render(<KPIStrip kpis={_kpisWithPnl} />)
    const text = container.textContent
    expect(text).toContain('Total P&L')
    expect(text).toContain('$1,234.56')
    const badges = container.querySelectorAll('[data-testid="kpi-meta-badge"]')
    expect(badges.length).toBeGreaterThanOrEqual(1)
    const badgeTexts = Array.from(badges).map(b => b.textContent)
    expect(badgeTexts.some(t => t.includes('n=160'))).toBe(true)
  })

  it('does not render PromotionGateCard and shows vote count in TrafficLight tooltip area', () => {
    const { container } = render(<KPIStrip kpis={_kpisWithPnl} />)
    const text = container.textContent
    expect(text).not.toContain('Promotion Gate')
    expect(text).toContain('Stage Traffic Light')
    expect(text).toContain('4/5')
  })
})

describe('TotalPnlDollarsCard negative and zero cases (T6)', () => {
  it('KPIStrip renders negative total_pnl_dollars with red color and minus sign', () => {
    const kpis = { ..._kpisGreen, total_pnl_dollars: -1234.56 }
    const { container } = render(<KPIStrip kpis={kpis} />)
    expect(container.textContent).toContain('Total P&L')
    expect(container.textContent).toContain('$-1,234.56')
    expect(container.innerHTML).toContain('kpi-pill--red')
  })

  it('KPIStrip renders zero total_pnl_dollars as neutral', () => {
    const kpis = { ..._kpisGreen, total_pnl_dollars: 0 }
    const { container } = render(<KPIStrip kpis={kpis} />)
    expect(container.textContent).toContain('Total P&L')
    expect(container.textContent).toContain('$0.00')
    expect(container.innerHTML).not.toContain('kpi-pill--red')
  })

  it('KPIStrip renders large negative total_pnl_dollars with thousands separator', () => {
    const kpis = { ..._kpisGreen, total_pnl_dollars: -12345.67 }
    const { container } = render(<KPIStrip kpis={kpis} />)
    expect(container.textContent).toContain('Total P&L')
    expect(container.textContent).toContain('$-12,345.67')
    expect(container.innerHTML).toContain('kpi-pill--red')
  })
})
