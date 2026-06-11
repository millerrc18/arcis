import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import AsyncBoundary from '../AsyncBoundary'

function Child() {
  return <div data-testid="child">CHILD</div>
}

describe('AsyncBoundary', () => {
  it('renders "loading…" (NOT children) on first load — isPending with no data', () => {
    render(
      <AsyncBoundary query={{ isPending: true, isError: false, data: undefined }} label="Sig">
        <Child />
      </AsyncBoundary>
    )
    expect(screen.getByTestId('async-loading').textContent).toMatch(/loading/i)
    // Crux: a first-load flash must NOT show the child's UNKNOWN/no-data state.
    expect(screen.queryByTestId('child')).not.toBeInTheDocument()
  })

  it('renders "source unavailable" (NOT children) on isError', () => {
    render(
      <AsyncBoundary query={{ isPending: false, isError: true, data: undefined }} label="Sig">
        <Child />
      </AsyncBoundary>
    )
    expect(screen.getByTestId('async-error').textContent).toMatch(/unavailable/i)
    expect(screen.queryByTestId('child')).not.toBeInTheDocument()
  })

  it('renders children once data is present (resolved — even honest-degraded data)', () => {
    render(
      <AsyncBoundary query={{ isPending: false, isError: false, data: { signals: {} } }}>
        <Child />
      </AsyncBoundary>
    )
    expect(screen.getByTestId('child')).toBeInTheDocument()
    expect(screen.queryByTestId('async-loading')).not.toBeInTheDocument()
  })

  it('does NOT flash loading on a background refetch (data present, isFetching)', () => {
    render(
      <AsyncBoundary query={{ isPending: false, isFetching: true, isError: false, data: { ok: 1 } }}>
        <Child />
      </AsyncBoundary>
    )
    expect(screen.getByTestId('child')).toBeInTheDocument()
    expect(screen.queryByTestId('async-loading')).not.toBeInTheDocument()
  })

  it('error takes precedence over stale data — never shows stale data as healthy', () => {
    render(
      <AsyncBoundary query={{ isPending: false, isError: true, data: { ok: 1 } }} label="X">
        <Child />
      </AsyncBoundary>
    )
    expect(screen.getByTestId('async-error')).toBeInTheDocument()
    expect(screen.queryByTestId('child')).not.toBeInTheDocument()
  })

  it('includes the label in the loading text', () => {
    render(
      <AsyncBoundary query={{ isPending: true, isError: false, data: undefined }} label="Integrity">
        <Child />
      </AsyncBoundary>
    )
    expect(screen.getByTestId('async-loading').textContent).toMatch(/Integrity/)
  })
})
