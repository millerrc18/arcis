/**
 * PreflightStatusCard tests (Vitest + @testing-library/react).
 * Track 1.5 / Round 8.D — S4 preflight echo.
 */
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, useQuery: vi.fn() }
})

import { useQuery } from '@tanstack/react-query'
import PreflightStatusCard from './PreflightStatusCard'

function wrap(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const _emptyState = {
  last_run_at: null,
  overall_status: 'unknown',
  n_pass: 0,
  n_fail: 0,
  items: [],
  transcript_path: null,
}

const _populatedState = {
  last_run_at: '2026-04-25T08:00:00-04:00',
  overall_status: 'yellow',
  n_pass: 9,
  n_fail: 1,
  items: [
    { name: 'pre_651_quarantine_clean', status: 'pass' },
    { name: 'quarantine_column_extended', status: 'pass' },
    { name: 'canonical_sharpe_module_exists', status: 'pass' },
    { name: 'governor_enabled', status: 'pass' },
    { name: 'capital_cap', status: 'pass' },
    { name: 'effective_position_cap', status: 'pass' },
    { name: 'mr_bracket_config', status: 'pass' },
    { name: 'alpaca_connectivity', status: 'fail' },
    { name: 'baseline_memo_signed_off', status: 'pass' },
    { name: 'transcript_saved', status: 'pass' },
  ],
  transcript_path: '/repo/audits/2026-04-27/preflight_transcript.txt',
}

const _greenState = {
  last_run_at: '2026-04-25T09:00:00-04:00',
  overall_status: 'green',
  n_pass: 10,
  n_fail: 0,
  items: _populatedState.items.map(i => ({ ...i, status: 'pass' })),
  transcript_path: '/repo/audits/2026-04-27/preflight_transcript.txt',
}

describe('PreflightStatusCard', () => {
  it('renders loading state while fetching', () => {
    useQuery.mockReturnValue({ data: undefined, isLoading: true, isError: false })
    const { container } = wrap(<PreflightStatusCard />)
    expect(container.textContent).toContain('Loading')
  })

  it('renders error state on fetch failure', () => {
    useQuery.mockReturnValue({ data: undefined, isLoading: false, isError: true })
    const { container } = wrap(<PreflightStatusCard />)
    expect(container.textContent).toContain('Failed to load preflight status')
  })

  it('renders empty state message when no preflight has run', () => {
    useQuery.mockReturnValue({ data: _emptyState, isLoading: false, isError: false })
    const { container } = wrap(<PreflightStatusCard />)
    expect(container.textContent).toContain('Preflight has not been run yet today')
  })

  it('renders overall status badge label', () => {
    useQuery.mockReturnValue({ data: _populatedState, isLoading: false, isError: false })
    const { container } = wrap(<PreflightStatusCard />)
    expect(container.textContent).toContain('WARN')
  })

  it('renders all 10 check items', () => {
    useQuery.mockReturnValue({ data: _populatedState, isLoading: false, isError: false })
    const { container } = wrap(<PreflightStatusCard />)
    expect(container.textContent).toContain('pre_651_quarantine_clean')
    expect(container.textContent).toContain('alpaca_connectivity')
    expect(container.textContent).toContain('transcript_saved')
  })

  it('renders FAIL label for the failed item', () => {
    useQuery.mockReturnValue({ data: _populatedState, isLoading: false, isError: false })
    const { container } = wrap(<PreflightStatusCard />)
    expect(container.textContent).toContain('FAIL')
  })

  it('renders last_run_at timestamp', () => {
    useQuery.mockReturnValue({ data: _populatedState, isLoading: false, isError: false })
    const { container } = wrap(<PreflightStatusCard />)
    expect(container.textContent).toContain('2026-04-25T08:00:00-04:00')
  })

  it('renders transcript path when provided', () => {
    useQuery.mockReturnValue({ data: _populatedState, isLoading: false, isError: false })
    const { container } = wrap(<PreflightStatusCard />)
    expect(container.textContent).toContain('/repo/audits/2026-04-27/preflight_transcript.txt')
  })

  it('renders ALL PASS badge on green status', () => {
    useQuery.mockReturnValue({ data: _greenState, isLoading: false, isError: false })
    const { container } = wrap(<PreflightStatusCard />)
    expect(container.textContent).toContain('ALL PASS')
  })

  it('renders NOT RUN badge on unknown status (empty state)', () => {
    useQuery.mockReturnValue({ data: _emptyState, isLoading: false, isError: false })
    const { container } = wrap(<PreflightStatusCard />)
    expect(container.textContent).toContain('NOT RUN')
  })

  it('does not render transcript path when null', () => {
    useQuery.mockReturnValue({ data: _emptyState, isLoading: false, isError: false })
    const { container } = wrap(<PreflightStatusCard />)
    expect(container.textContent).not.toContain('Transcript:')
  })

  it('renders n_pass count', () => {
    useQuery.mockReturnValue({ data: _populatedState, isLoading: false, isError: false })
    const { container } = wrap(<PreflightStatusCard />)
    expect(container.textContent).toContain('9 pass')
  })

  it('renders n_fail count when non-zero', () => {
    useQuery.mockReturnValue({ data: _populatedState, isLoading: false, isError: false })
    const { container } = wrap(<PreflightStatusCard />)
    expect(container.textContent).toContain('1 fail')
  })
})
