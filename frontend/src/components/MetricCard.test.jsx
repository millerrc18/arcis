/**
 * MetricCard sign-aware prefix formatting tests.
 *
 * T18 sibling-fix: aggregate-stat MetricCards (Avg Loss, Total P&L, Expectancy
 * across ShadowLedger, LiveLedger, ModelPerformance) were rendering negative
 * dollar amounts as `$-6.55` (sign after prefix) instead of `-$6.55` (sign
 * before prefix). The fix moves a leading `+`/`-` sign before the prefix when
 * value is a numeric-shaped string. Non-numeric leading-dash strings ("--")
 * pass through unchanged.
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import MetricCard from './MetricCard'

describe('MetricCard sign-aware prefix formatting (T18 sibling-fix)', () => {
  it('renders unsigned value with prefix unchanged', () => {
    const { container } = render(<MetricCard label="Avg Gain" value="6.55" prefix="$" />)
    expect(container.textContent).toContain('$6.55')
    expect(container.textContent).not.toContain('$-')
  })

  it('moves leading minus before prefix for negative numeric value', () => {
    const { container } = render(<MetricCard label="Avg Loss" value="-6.55" prefix="$" />)
    expect(container.textContent).toContain('-$6.55')
    expect(container.textContent).not.toContain('$-6.55')
  })

  it('moves leading plus before prefix for explicitly positive value', () => {
    const { container } = render(<MetricCard label="Total P&L" value="+150.50" prefix="$" />)
    expect(container.textContent).toContain('+$150.50')
    expect(container.textContent).not.toContain('$+150.50')
  })

  it('passes through non-numeric leading-dash strings unchanged', () => {
    const { container } = render(<MetricCard label="Pending" value="--" prefix="$" />)
    expect(container.textContent).toContain('$--')
  })

  it('handles zero correctly without sign manipulation', () => {
    const { container } = render(<MetricCard label="Avg Loss" value="0.00" prefix="$" />)
    expect(container.textContent).toContain('$0.00')
  })

  it('preserves no-prefix behavior for negative values', () => {
    const { container } = render(<MetricCard label="Delta" value="-6.55" />)
    expect(container.textContent).toContain('-6.55')
  })

  it('keeps suffix after the value', () => {
    const { container } = render(<MetricCard label="Loss" value="-6.55" prefix="$" suffix=" USD" />)
    expect(container.textContent).toContain('-$6.55 USD')
  })

  it('renders comma-separated negative values correctly', () => {
    const { container } = render(<MetricCard label="Drawdown" value="-1,234.56" prefix="$" />)
    expect(container.textContent).toContain('-$1,234.56')
  })
})
