/**
 * BrokerExceptionsPanel snapshot tests (Vitest + @testing-library/react).
 * Track 1.5 / Round 8.C — G1 observability gap.
 */
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, useQuery: vi.fn() }
})

import { useQuery } from '@tanstack/react-query'
import BrokerExceptionsPanel from './BrokerExceptionsPanel'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const _emptyData = {
  summary: { total_24h: 0, total_7d: 0, alert_qty_mismatch_count: 0, by_broker: {}, by_operation: {} },
  recent: { rows: [], count: 0, limit: 50, since_hours: 24 },
}

const _rowNormal = {
  id: 1,
  ticker: 'AAPL',
  operation: 'place_order',
  broker: 'alpaca',
  timestamp: '2026-04-25T10:00:00Z',
  exception_class: 'ConnectionError',
  exception_message: 'Connection timed out after 30s',
  recoverable: 1,
  outcome: 'persisted',
}

const _rowAlertQtyMismatch = {
  id: 2,
  ticker: 'CVS',
  operation: 'verify_fill',
  broker: 'alpaca',
  timestamp: '2026-04-25T11:00:00Z',
  exception_class: 'QtyMismatchError',
  exception_message: 'Filled 50 but expected 100',
  recoverable: 0,
  outcome: 'alert_qty_mismatch',
}

const _rowRecoverableFalse = {
  id: 3,
  ticker: 'MSFT',
  operation: 'cancel_order',
  broker: 'ibkr',
  timestamp: '2026-04-25T12:00:00Z',
  exception_class: 'APIError',
  exception_message: 'Order not found',
  recoverable: 0,
  outcome: 'persisted',
}

const _summaryWithData = {
  total_24h: 3,
  total_7d: 7,
  alert_qty_mismatch_count: 1,
  by_broker: { alpaca: 2, ibkr: 1 },
  by_operation: { place_order: 1, verify_fill: 1, cancel_order: 1 },
}

const _hasRowsData = {
  summary: _summaryWithData,
  recent: {
    rows: [_rowNormal, _rowAlertQtyMismatch, _rowRecoverableFalse],
    count: 3,
    limit: 50,
    since_hours: 24,
  },
}

describe('BrokerExceptionsPanel', () => {
  it('renders empty state when no exceptions in last 24h', () => {
    useQuery.mockReturnValue({ data: _emptyData, isLoading: false, isError: false })
    const { container } = wrap(<BrokerExceptionsPanel />)
    expect(container).toMatchSnapshot()
    expect(container.textContent).toContain('No broker exceptions in last 24h')
  })

  it('renders loading state while fetching', () => {
    useQuery.mockReturnValue({ data: undefined, isLoading: true, isError: false })
    const { container } = wrap(<BrokerExceptionsPanel />)
    expect(container).toMatchSnapshot()
    expect(container.textContent).toContain('Loading')
  })

  it('renders summary counts when rows present', () => {
    useQuery.mockReturnValue({ data: _hasRowsData, isLoading: false, isError: false })
    const { container } = wrap(<BrokerExceptionsPanel />)
    expect(container).toMatchSnapshot()
    const text = container.textContent
    expect(text).toContain('3')
    expect(text).toContain('24h')
  })

  it('renders ticker and operation for each row', () => {
    useQuery.mockReturnValue({ data: _hasRowsData, isLoading: false, isError: false })
    const { container } = wrap(<BrokerExceptionsPanel />)
    const text = container.textContent
    expect(text).toContain('AAPL')
    expect(text).toContain('place_order')
  })

  it('applies red border class on alert_qty_mismatch row', () => {
    useQuery.mockReturnValue({ data: _hasRowsData, isLoading: false, isError: false })
    const { container } = wrap(<BrokerExceptionsPanel />)
    expect(container.innerHTML).toContain('alert_qty_mismatch')
  })

  it('message is truncated to 80 chars', () => {
    const longMsg = 'A'.repeat(120)
    const rowLong = { ..._rowNormal, id: 10, exception_message: longMsg }
    const data = {
      summary: _summaryWithData,
      recent: { rows: [rowLong], count: 1, limit: 50, since_hours: 24 },
    }
    useQuery.mockReturnValue({ data, isLoading: false, isError: false })
    const { container } = wrap(<BrokerExceptionsPanel />)
    const text = container.textContent
    const msgText = longMsg.slice(0, 80)
    expect(text).toContain(msgText)
  })

  it('renders broker names from by_broker summary', () => {
    useQuery.mockReturnValue({ data: _hasRowsData, isLoading: false, isError: false })
    const { container } = wrap(<BrokerExceptionsPanel />)
    const text = container.textContent
    expect(text).toContain('alpaca')
    expect(text).toContain('ibkr')
  })
})
