/**
 * T18e — ActivityFeed.jsx:57 sign formatting (7th sibling site)
 *
 * Verifies that pnl_dollars in trade_closed events renders with the sign
 * BEFORE the dollar sign, matching the canonical pattern from LiveLedger /
 * ShadowLedger / OpenPositionCard. The original bug rendered `($-150.50)`
 * (sign inside dollar sign); the fix must produce `(-$150.50)`.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('@tanstack/react-query', () => ({
  useQuery: vi.fn(() => ({ data: undefined })),
}))

vi.mock('../../config', () => ({
  IS_CLOUD: false,
  API_BASE: '',
  API_SECRET: '',
}))

vi.mock('../../api', () => ({
  api: { getActivityFeed: vi.fn() },
}))

vi.mock('lucide-react', () => ({
  TrendingUp: () => null,
  TrendingDown: () => null,
  CheckCircle: () => null,
  XCircle: () => null,
  Brain: () => null,
  AlertTriangle: () => null,
  Shield: () => null,
  Database: () => null,
  Settings: () => null,
}))

const mockUseWebSocket = vi.fn()
vi.mock('../../hooks/useWebSocket', () => ({
  default: () => mockUseWebSocket(),
}))

import ActivityFeed from '../../components/ActivityFeed'

function makeTradeClosedEvent(pnl_dollars, pnl_pct = 1.5) {
  return {
    type: 'trade_closed',
    timestamp: new Date().toISOString(),
    data: { ticker: 'AAPL', pnl_pct, pnl_dollars },
  }
}

describe('ActivityFeed — T18e sign formatting', () => {
  it('renders pnl_dollars=-150.50 as -$150.50 (sign before dollar sign)', () => {
    mockUseWebSocket.mockReturnValue({
      events: [makeTradeClosedEvent(-150.50, -2.1)],
      connected: false,
      clearEvents: vi.fn(),
    })

    render(<ActivityFeed />)

    const text = screen.getByText(/Closed AAPL/)
    expect(text.textContent).toContain('-$150.50')
    expect(text.textContent).not.toContain('$-150.50')
  })

  it('renders pnl_dollars=200.00 as +$200.00 (sign before dollar sign)', () => {
    mockUseWebSocket.mockReturnValue({
      events: [makeTradeClosedEvent(200.00, 3.5)],
      connected: false,
      clearEvents: vi.fn(),
    })

    render(<ActivityFeed />)

    const text = screen.getByText(/Closed AAPL/)
    expect(text.textContent).toContain('+$200.00')
    expect(text.textContent).not.toContain('$+200.00')
  })

  it('renders pnl_dollars=0 as $0.00 with no sign prefix (no +$0.00)', () => {
    mockUseWebSocket.mockReturnValue({
      events: [makeTradeClosedEvent(0, 0)],
      connected: false,
      clearEvents: vi.fn(),
    })

    render(<ActivityFeed />)

    const text = screen.getByText(/Closed AAPL/)
    expect(text.textContent).toContain('$0.00')
    expect(text.textContent).not.toContain('+$0.00')
  })
})
