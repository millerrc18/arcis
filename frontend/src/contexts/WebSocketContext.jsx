import { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react'

const MAX_EVENTS = 100
const RECONNECT_DELAY = 5000

const WebSocketContext = createContext(null)

export function WebSocketProvider({ children }) {
  const [events, setEvents] = useState([])
  const [connected, setConnected] = useState(false)
  const wsRef = useRef(null)
  const reconnectRef = useRef(null)
  const subscribersRef = useRef(new Set())

  const subscribe = useCallback((callback) => {
    subscribersRef.current.add(callback)
    return () => subscribersRef.current.delete(callback)
  }, [])

  const clearEvents = useCallback(() => setEvents([]), [])

  useEffect(() => {
    function connect() {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/live`)
      wsRef.current = ws

      ws.onopen = () => setConnected(true)

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          // Add to event buffer for ActivityFeed
          setEvents(prev => [msg, ...prev].slice(0, MAX_EVENTS))
          // Notify subscribers (cache invalidation, toasts, etc.)
          subscribersRef.current.forEach(cb => cb(msg))
        } catch {
          // ignore malformed messages
        }
      }

      ws.onclose = () => {
        setConnected(false)
        reconnectRef.current = setTimeout(connect, RECONNECT_DELAY)
      }

      ws.onerror = () => ws.close()
    }

    connect()
    return () => {
      if (wsRef.current) wsRef.current.close()
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
    }
  }, [])

  return (
    <WebSocketContext.Provider value={{ events, connected, clearEvents, subscribe }}>
      {children}
    </WebSocketContext.Provider>
  )
}

export function useWebSocketContext() {
  const ctx = useContext(WebSocketContext)
  if (!ctx) throw new Error('useWebSocketContext must be used within WebSocketProvider')
  return ctx
}
