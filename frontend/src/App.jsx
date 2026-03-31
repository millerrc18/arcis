import { useEffect } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query'
import { WebSocketProvider, useWebSocketContext } from './contexts/WebSocketContext'
import Layout from './components/Layout'
import ErrorBoundary from './components/ErrorBoundary'
import ToastContainer, { toast } from './components/Toast'
import AuthGate from './components/AuthGate'
import { IS_CLOUD } from './config'
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

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { refetchInterval: 30000, staleTime: 10000 },
  },
})

function CacheInvalidator() {
  const qc = useQueryClient()
  const { subscribe } = useWebSocketContext()

  useEffect(() => {
    return subscribe((msg) => {
      const msgType = msg.type
      if (msgType === 'scan_complete') {
        qc.invalidateQueries({ queryKey: ['scan'] })
        qc.invalidateQueries({ queryKey: ['status'] })
        toast('Scan complete', 'info')
      } else if (msgType === 'trade_opened') {
        qc.invalidateQueries({ queryKey: ['shadow'] })
        toast(`Trade opened: ${msg.data?.ticker || ''}`, 'info')
      } else if (msgType === 'trade_closed') {
        qc.invalidateQueries({ queryKey: ['shadow'] })
        const pnl = msg.data?.pnl_dollars
        const pnlType = pnl >= 0 ? 'success' : 'error'
        toast(`Trade closed: ${msg.data?.ticker || ''} $${pnl?.toFixed(2) || ''}`, pnlType)
      } else if (msgType === 'pnl_update') {
        qc.invalidateQueries({ queryKey: ['shadow'] })
      } else if (msgType === 'training_update') {
        qc.invalidateQueries({ queryKey: ['training'] })
        toast('Training update', 'info')
      } else if (msgType === 'system_status') {
        qc.invalidateQueries({ queryKey: ['status'] })
      }
    })
  }, [qc, subscribe])

  return null
}

export default function App() {
  const content = (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <WebSocketProvider>
          <CacheInvalidator />
          <BrowserRouter>
            <Routes>
              <Route element={<Layout />}>
                <Route index element={<Dashboard />} />
                <Route path="/packets" element={<Packets />} />
                <Route path="/shadow" element={<ShadowLedger />} />
                <Route path="/training" element={<Training />} />
                <Route path="/live" element={<LiveLedger />} />
                <Route path="/cto-report" element={<CTOReport />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/roadmap" element={<Roadmap />} />
                <Route path="/docs" element={<Docs />} />
                <Route path="/notes" element={<Notes />} />
                <Route path="/council" element={<Council />} />
                <Route path="/health" element={<Health />} />
                <Route path="/validation" element={<Validation />} />
                <Route path="/logs" element={<Logs />} />
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
