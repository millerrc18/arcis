/**
 * T18d — OpenPositionCard sign formatting tests
 *
 * Verifies that pnl_dollars renders with correct sign-dollar order:
 *   positive → +$200.00   (not $+200.00)
 *   negative → -$150.50   (not $-150.50 — the pre-fix bug)
 *   zero     → $0.00      (no sign prefix)
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import OpenPositionCard from '../../components/OpenPositionCard'

const baseTrade = {
  ticker: 'AAPL',
  direction: 'long',
  broker: 'alpaca',
  actual_entry_price: 150,
  current_price: 155,
  stop_price: 145,
  target_1: 165,
  pnl_pct: null,
  duration_days: 3,
  timeout_days: 8,
  max_favorable_excursion: null,
  max_adverse_excursion: null,
  setup_confidence: null,
  priority_score: null,
}

describe('OpenPositionCard — T18d sign formatting', () => {
  it('negative pnlDollars renders -$150.50 not $-150.50', () => {
    const { container } = render(
      <OpenPositionCard trade={{ ...baseTrade, pnl_dollars: -150.50 }} />
    )
    const text = container.textContent
    expect(text).toContain('-$150.50')
    expect(text).not.toContain('$-150.50')
    expect(text).not.toContain('+$-150.50')
  })

  it('positive pnlDollars renders +$200.00', () => {
    const { container } = render(
      <OpenPositionCard trade={{ ...baseTrade, pnl_dollars: 200.00 }} />
    )
    const text = container.textContent
    expect(text).toContain('+$200.00')
  })

  it('zero pnlDollars renders $0.00 with no sign prefix', () => {
    const { container } = render(
      <OpenPositionCard trade={{ ...baseTrade, pnl_dollars: 0 }} />
    )
    const text = container.textContent
    expect(text).toContain('$0.00')
    expect(text).not.toContain('+$0.00')
    expect(text).not.toContain('-$0.00')
  })
})
