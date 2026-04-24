import { useEffect } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query'
import { WebSocketProvider, useWebSocketContext } from './contexts/WebSocketContext'
import Layout from './components/Layout'
import ErrorBoundary from './components/ErrorBoundary'
import ToastContainer, { toast } from './components/Toast'
import AuthGate from './components/AuthGate'
import { IS_CLOUD } from './config'
import { configureStatusBar, onAppStateChange } from './native'
import Dashboard from './pages/Dashboard'
import Packets from './pages/Packets'
import ShadowLedger from './pages/ShadowLedger'
import Training from './pages/Training'
import LiveLedger from './pages/LiveLedger'
import CTOReport from './pages/CTOReport'
import Settings from './pages/Settings'
import Roadmap from './pages/Roadmap'
import Docs from './pages/Docs'
import Council from './pages/Council'
import Health from './pages/Health'
import Notes from './pages/Notes'
import Validation from './pages/Validation'
import Logs from './pages/Logs'
import Architecture from './pages/Architecture'
import DBSchema from './pages/DBSchema'
import Attribution from './pages/Attribution'
import StressTest from './pages/StressTest'
import Simulation from './pages/Simulation'
import ModelPerformance from './pages/ModelPerformance'
import Monitoring from './pages/Monitoring'
import Strategy from './pages/Strategy'
import TradeHistory from './pages/TradeHistory'
import Velocity from './pages/Velocity'
import StrategyResearch from './pages/StrategyResearch'
import WalkforwardResults from './pages/WalkforwardResults'
import Diagnostics from './pages/Diagnostics'

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
              <Route element={<Layout />}>
                <Route index element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
                <Route path="/packets" element={<ErrorBoundary><Packets /></ErrorBoundary>} />
                <Route path="/shadow" element={<ErrorBoundary><ShadowLedger /></ErrorBoundary>} />
                <Route path="/training" element={<ErrorBoundary><Training /></ErrorBoundary>} />
                <Route path="/live" element={<ErrorBoundary><LiveLedger /></ErrorBoundary>} />
                <Route path="/cto-report" element={<ErrorBoundary><CTOReport /></ErrorBoundary>} />
                <Route path="/settings" element={<ErrorBoundary><Settings /></ErrorBoundary>} />
                <Route path="/roadmap" element={<ErrorBoundary><Roadmap /></ErrorBoundary>} />
                <Route path="/docs" element={<ErrorBoundary><Docs /></ErrorBoundary>} />
                <Route path="/notes" element={<ErrorBoundary><Notes /></ErrorBoundary>} />
                <Route path="/council" element={<ErrorBoundary><Council /></ErrorBoundary>} />
                <Route path="/health" element={<ErrorBoundary><Health /></ErrorBoundary>} />
                <Route path="/validation" element={<ErrorBoundary><Validation /></ErrorBoundary>} />
                <Route path="/logs" element={<ErrorBoundary><Logs /></ErrorBoundary>} />
                <Route path="/architecture" element={<ErrorBoundary><Architecture /></ErrorBoundary>} />
                <Route path="/schema" element={<ErrorBoundary><DBSchema /></ErrorBoundary>} />
                <Route path="/attribution" element={<ErrorBoundary><Attribution /></ErrorBoundary>} />
                <Route path="/stress-test" element={<ErrorBoundary><StressTest /></ErrorBoundary>} />
                <Route path="/simulation" element={<ErrorBoundary><Simulation /></ErrorBoundary>} />
                <Route path="/model-performance" element={<ErrorBoundary><ModelPerformance /></ErrorBoundary>} />
                <Route path="/monitoring" element={<ErrorBoundary><Monitoring /></ErrorBoundary>} />
                <Route path="/strategy" element={<ErrorBoundary><Strategy /></ErrorBoundary>} />
                <Route path="/trade-history" element={<ErrorBoundary><TradeHistory /></ErrorBoundary>} />
                <Route path="/velocity" element={<ErrorBoundary><Velocity /></ErrorBoundary>} />
                <Route path="/research-platform" element={<ErrorBoundary><StrategyResearch /></ErrorBoundary>} />
                <Route path="/walkforward-results" element={<ErrorBoundary><WalkforwardResults /></ErrorBoundary>} />
                <Route path="/diagnostics" element={<ErrorBoundary><Diagnostics /></ErrorBoundary>} />
              </Route>
            </Routes>
          </BrowserRouter>
          <ToastContainer />
        </WebSocketProvider>
      </ErrorBoundary>
    </QueryClientProvider>
  )

  return IS_CLOUD ? <AuthGate>{content}</AuthGate> : content
}
