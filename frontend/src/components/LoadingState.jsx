import { useState, useEffect } from 'react'
import LoadingSpinner from './LoadingSpinner.jsx'
import EmptyState from './EmptyState.jsx'

export default function LoadingState({
  isLoading,
  isError,
  error,
  retry,
  retryDisabledFor = 0,
  isEmpty,
  loadingMessage,
  emptyMessage,
  compact = false,
  children,
}) {
  const [retryDisabled, setRetryDisabled] = useState(false)

  useEffect(() => {
    if (!retryDisabled) return
    const timer = setTimeout(() => setRetryDisabled(false), retryDisabledFor)
    return () => clearTimeout(timer)
  }, [retryDisabled, retryDisabledFor])

  function handleRetry() {
    if (retry) retry()
    if (retryDisabledFor > 0) setRetryDisabled(true)
  }

  if (isLoading) {
    return (
      <div data-testid="loading-spinner">
        <LoadingSpinner />
        {loadingMessage && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--arcis-text-muted)', textAlign: 'center' }}>
            {loadingMessage}
          </div>
        )}
      </div>
    )
  }

  if (isError) {
    if (compact) {
      return (
        <div data-testid="error-inline" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--arcis-text-muted)' }}>
            {error?.message}
          </span>
          <button
            onClick={handleRetry}
            disabled={retryDisabled}
            style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}
          >
            Retry
          </button>
        </div>
      )
    }
    return (
      <div data-testid="error-card" style={{ padding: '16px', border: '1px solid var(--arcis-border)', borderRadius: 4 }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--arcis-text-muted)', marginBottom: 8 }}>
          {error?.message}
        </div>
        <button
          onClick={handleRetry}
          disabled={retryDisabled}
          style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}
        >
          Retry
        </button>
      </div>
    )
  }

  if (isEmpty) {
    return <EmptyState message={emptyMessage} />
  }

  return <>{children}</>
}
