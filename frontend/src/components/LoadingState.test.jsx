import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react'
import LoadingState from './LoadingState.jsx'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('LoadingState — C1 shared loading state component', () => {
  it('isLoading=true renders spinner and loadingMessage', () => {
    render(
      <LoadingState isLoading={true} isError={false} isEmpty={false} loadingMessage="Fetching data...">
        <div>children</div>
      </LoadingState>
    )
    expect(screen.getByText('Fetching data...')).toBeInTheDocument()
    expect(screen.queryByText('children')).not.toBeInTheDocument()
    expect(screen.getByTestId('loading-spinner')).toBeInTheDocument()
  })

  it('isError=true renders error card with message, retry button; click calls retry; button disabled for retryDisabledFor ms then re-enables', () => {
    vi.useFakeTimers()
    const retryFn = vi.fn()

    render(
      <LoadingState
        isLoading={false}
        isError={true}
        error={{ message: 'Something went wrong' }}
        retry={retryFn}
        retryDisabledFor={2000}
        isEmpty={false}
      >
        <div>children</div>
      </LoadingState>
    )

    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    expect(screen.queryByText('children')).not.toBeInTheDocument()

    const retryBtn = screen.getByRole('button', { name: /retry/i })
    expect(retryBtn).not.toBeDisabled()

    fireEvent.click(retryBtn)
    expect(retryFn).toHaveBeenCalledTimes(1)
    expect(retryBtn).toBeDisabled()

    act(() => {
      vi.advanceTimersByTime(1999)
    })
    expect(retryBtn).toBeDisabled()

    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(retryBtn).not.toBeDisabled()
  })

  it('isEmpty=true renders empty card with emptyMessage', () => {
    render(
      <LoadingState isLoading={false} isError={false} isEmpty={true} emptyMessage="No trades found">
        <div>children</div>
      </LoadingState>
    )
    expect(screen.getByText('No trades found')).toBeInTheDocument()
    expect(screen.queryByText('children')).not.toBeInTheDocument()
  })

  it('data path renders children when not loading, error, or empty', () => {
    render(
      <LoadingState isLoading={false} isError={false} isEmpty={false}>
        <div data-testid="data-content">data here</div>
      </LoadingState>
    )
    expect(screen.getByTestId('data-content')).toBeInTheDocument()
    expect(screen.queryByTestId('loading-spinner')).not.toBeInTheDocument()
  })

  it('compact=true renders inline without card wrapper', () => {
    render(
      <LoadingState isLoading={false} isError={true} error={{ message: 'Err' }} retry={() => {}} isEmpty={false} compact={true}>
        <div>children</div>
      </LoadingState>
    )
    const card = document.querySelector('[data-testid="error-card"]')
    expect(card).toBeNull()
    expect(screen.getByTestId('error-inline')).toBeInTheDocument()
  })
})
