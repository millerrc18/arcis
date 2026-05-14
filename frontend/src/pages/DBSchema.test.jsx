import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, useQuery: vi.fn() }
})

vi.mock('@xyflow/react', () => ({
  ReactFlow: ({ children }) => <div data-testid="react-flow">{children}</div>,
  Background: () => null,
  Controls: () => null,
  useNodesState: (nodes) => [nodes, null, vi.fn()],
  useEdgesState: (edges) => [edges, null, vi.fn()],
}))

import { useQuery } from '@tanstack/react-query'
import DBSchema from './DBSchema'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('DBSchema — C2 LoadingState migration', () => {
  it('isLoading=true renders loading spinner', () => {
    useQuery.mockReturnValue({ data: undefined, isLoading: true, isError: false })
    const { container } = wrap(<DBSchema />)
    expect(container.querySelector('[data-testid="loading-spinner"]')).toBeTruthy()
  })

  it('isError=true renders error card', () => {
    useQuery.mockReturnValue({ data: undefined, isLoading: false, isError: true, error: { message: 'Failed to load' } })
    const { container } = wrap(<DBSchema />)
    expect(container.querySelector('[data-testid="error-card"]')).toBeTruthy()
  })

  it('data loaded renders ReactFlow graph', () => {
    useQuery.mockReturnValue({ data: { counts: { shadow_trades: 100 }, registry_total: 76 }, isLoading: false, isError: false })
    const { container } = wrap(<DBSchema />)
    expect(container.querySelector('[data-testid="react-flow"]')).toBeTruthy()
  })
})

describe('DBSchema — P2 registry table count', () => {
  it('headline shows registry_total (76 tables) when data is loaded', () => {
    useQuery.mockReturnValue({ data: { counts: { shadow_trades: 100 }, registry_total: 76 }, isLoading: false, isError: false })
    const { container } = wrap(<DBSchema />)
    const subtitle = container.querySelector('p')
    expect(subtitle.textContent).toMatch(/76 tables/)
  })

  it('headline shows loading text when data is not yet available', () => {
    useQuery.mockReturnValue({ data: undefined, isLoading: true, isError: false })
    const { container } = wrap(<DBSchema />)
    const subtitle = container.querySelector('p')
    expect(subtitle.textContent).toMatch(/loading/)
  })
})
