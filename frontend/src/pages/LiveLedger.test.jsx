/**
 * LiveLedger tests — T6 formatter fix: equity thousands separator.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, useQuery: vi.fn() }
})

import { useQuery } from '@tanstack/react-query'
import LiveLedger from './LiveLedger'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  useQuery.mockReset()
})

describe('LiveLedger — T6 equity formatter', () => {
  it('renders equity with comma thousands separator for large values', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'live-summary') {
        return {
          data: { current_equity: 100000, starting_capital: 100000, total_pnl: 0, open_positions: 0 },
          isLoading: false,
        }
      }
      if (key === 'live-trades') {
        return { data: { open: [], closed: [] }, isLoading: false }
      }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<LiveLedger />)
    // Should render "100,000.00" with comma — not "100000.00"
    expect(container.textContent).toContain('100,000.00')
    expect(container.textContent).not.toContain('100000.00')
  })

  it('renders equity without comma for small values under 1000', () => {
    useQuery.mockImplementation((opts) => {
      const key = opts.queryKey?.[0]
      if (key === 'live-summary') {
        return {
          data: { current_equity: 500, starting_capital: 100000, total_pnl: -99500, open_positions: 0 },
          isLoading: false,
        }
      }
      if (key === 'live-trades') {
        return { data: { open: [], closed: [] }, isLoading: false }
      }
      return { data: undefined, isLoading: false }
    })

    const { container } = wrap(<LiveLedger />)
    expect(container.textContent).toContain('500.00')
  })
})
