import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query'
import { WebSocketProvider, useWebSocketContext } from './contexts/WebSocketContext'
import ErrorBoundary from './components/ErrorBoundary'
import ToastContainer, { toast } from './components/Toast'
import AuthGate from './components/AuthGate'
import { IS_CLOUD } from './config'
import { configureStatusBar, onAppStateChange } from './native'
import ConsoleShell from './console/ConsoleShell'

// staleTime 5s: dashboard values age fast; refetchInterval 30s for most
// queries means ~25s staleness window at most. retry: 2 with exponential
// backoff handles transient Render cold-starts without silent failures.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchInterval: 30000,
      staleTime: 5000,
      retry: 2,
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
      refetchOnWindowFocus: true,
    },
  },
})

const SCAN_QUERY_KEYS = [
  ['scan'],
  ['scan-metrics'],
  ['packets'],
  ['status'],
]

const LIVE_TRADE_QUERY_KEYS = [
  ['shadow-open'],
  ['shadow-account'],
  ['live-trades'],
  ['live-summary'],
  ['live-trades-for-ledger'],
]

const CLOSED_TRADE_QUERY_KEYS = [
  ['shadow-closed'],
  ['trade-history-closed'],
  ['sharpe-attribution'],
]

const TRAINING_QUERY_KEYS = [
  ['training-status'],
  ['training-versions'],
  ['data-collection-stats'],
]

function invalidateQueryKeys(qc, queryKeys) {
  for (const queryKey of queryKeys) {
    qc.invalidateQueries({ queryKey })
  }
}

function CacheInvalidator() {
  const qc = useQueryClient()
  const { subscribe } = useWebSocketContext()

  useEffect(() => {
    return subscribe((msg) => {
      const msgType = msg.type
      if (msgType === 'scan_complete') {
        invalidateQueryKeys(qc, SCAN_QUERY_KEYS)
        toast('Scan complete', 'info')
      } else if (msgType === 'trade_opened') {
        invalidateQueryKeys(qc, LIVE_TRADE_QUERY_KEYS)
        toast(`Trade opened: ${msg.data?.ticker || ''}`, 'info')
      } else if (msgType === 'trade_closed') {
        invalidateQueryKeys(qc, [...LIVE_TRADE_QUERY_KEYS, ...CLOSED_TRADE_QUERY_KEYS])
        const pnl = msg.data?.pnl_dollars
        const pnlType = pnl >= 0 ? 'success' : 'error'
        toast(`Trade closed: ${msg.data?.ticker || ''} $${pnl?.toFixed(2) || ''}`, pnlType)
      } else if (msgType === 'pnl_update') {
        invalidateQueryKeys(qc, LIVE_TRADE_QUERY_KEYS)
      } else if (msgType === 'training_update') {
        invalidateQueryKeys(qc, TRAINING_QUERY_KEYS)
        toast('Training update', 'info')
      } else if (msgType === 'system_status') {
        qc.invalidateQueries({ queryKey: ['status'] })
      }
    })
  }, [qc, subscribe])

  return null
}

export default function App() {
  useEffect(() => { configureStatusBar(); }, []);

  useEffect(() => {
    const cleanup = onAppStateChange(({ isActive }) => {
      if (isActive) queryClient.invalidateQueries();
    });
    return cleanup;
  }, []);

  const content = (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <WebSocketProvider>
          <CacheInvalidator />
          <BrowserRouter>
            <Routes>
              <Route path="/console/*" element={<ConsoleShell />} />
              {/* Old 28-page dashboard retired 2026-06-10 (chore/retire-old-dashboard).
                  /console is the sole UI; every legacy path redirects into it. */}
              <Route path="*" element={<Navigate to="/console" replace />} />
            </Routes>
          </BrowserRouter>
          <ToastContainer />
        </WebSocketProvider>
      </ErrorBoundary>
    </QueryClientProvider>
  )

  return IS_CLOUD ? <AuthGate>{content}</AuthGate> : content
}
