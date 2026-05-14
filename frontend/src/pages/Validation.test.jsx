/**
 * Validation page tests — T9 empty-state fix.
 * When the backend returns an empty response (no validation runs yet),
 * the page must render an empty-state message, not stay on LoadingSpinner.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, useQuery: vi.fn(), useQueryClient: vi.fn() }
})

vi.mock('../api', () => ({
  api: {
    getValidation: vi.fn(),
    runValidation: vi.fn(),
    submitCommand: vi.fn(),
    getCommandStatus: vi.fn(),
  },
}))

import { useQuery, useQueryClient } from '@tanstack/react-query'
import Validation from './Validation'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
  useQuery.mockReset()
})

describe('Validation — T9 empty-state render', () => {
  it('renders "No validation runs yet" when API returns empty object and isLoading=false', () => {
    useQuery.mockReturnValue({ data: {}, isLoading: false })

    const { container } = wrap(<Validation />)

    expect(container.textContent).toContain('No validation runs yet')
    // Must NOT be stuck on loading spinner text
    expect(container.textContent).not.toContain('LOADING...')
  })

  it('renders "No validation runs yet" when API returns null and isLoading=false', () => {
    useQuery.mockReturnValue({ data: null, isLoading: false })

    const { container } = wrap(<Validation />)

    expect(container.textContent).toContain('No validation runs yet')
    expect(container.textContent).not.toContain('LOADING...')
  })

  it('renders LoadingSpinner while isLoading=true', () => {
    useQuery.mockReturnValue({ data: undefined, isLoading: true })

    const { container } = wrap(<Validation />)

    // LoadingSpinner renders "LOADING..." text (no data-testid on the component)
    expect(container.textContent).toContain('LOADING...')
  })

  it('renders category cards when categories are present in data', () => {
    useQuery.mockReturnValue({
      data: {
        overall_status: 'healthy',
        checks_passed: 5,
        checks_warning: 0,
        checks_failed: 0,
        checks_total: 5,
        categories: {
          database: [{ name: 'db-check', status: 'pass', detail: 'ok' }],
        },
      },
      isLoading: false,
    })

    const { container } = wrap(<Validation />)

    // Should NOT show empty state
    expect(container.textContent).not.toContain('No validation runs yet')
    // Should show the category
    expect(container.querySelector('[data-testid="validation-category-database"]')).toBeTruthy()
  })
})

describe('CTOReport — T9 default days=30', () => {
  it('CTOReport default days is 30 not 365', async () => {
    // Dynamically import CTOReport to check its default state
    vi.mock('./CTOReport', async (importOriginal) => importOriginal())
    const { default: CTOReport } = await import('./CTOReport')

    const queryCalls = []
    useQuery.mockImplementation((opts) => {
      queryCalls.push(opts)
      return { data: undefined, isLoading: true, error: null }
    })

    wrap(<CTOReport />)

    const ctoCall = queryCalls.find(c => c.queryKey?.[0] === 'cto-report')
    expect(ctoCall).toBeTruthy()
    expect(ctoCall.queryKey[1]).toBe(30)
  })
})
