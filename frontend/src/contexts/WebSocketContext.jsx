import { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react'
import { IS_CLOUD } from '../config'

const MAX_EVENTS = 100
const INITIAL_DELAY = 3000
const MAX_DELAY = 60000
const MAX_RETRIES = 5

const WebSocketContext = createContext(null)

export function WebSocketProvider({ children }) {
  const [events, setEvents] = useState([])
  const [connected, setConnected] = useState(false)
  const wsRef = useRef(null)
  const reconnectRef = useRef(null)
  const retriesRef = useRef(0)
  const subscribersRef = useRef(new Set())

  const subscribe = useCallback((callback) => {
    subscribersRef.current.add(callback)
    return () => subscribersRef.current.delete(callback)
  }, [])

  const clearEvents = useCallback(() => setEvents([]), [])

  useEffect(() => {
    if (IS_CLOUD) {
      console.debug('[WS] Disabled in cloud mode — static dashboard has no same-origin websocket endpoint')
      return undefined
    }

    function connect() {
      // Stop retrying after MAX_RETRIES — WebSocket endpoint likely doesn't exist
      if (retriesRef.current >= MAX_RETRIES) {
        console.debug('[WS] Max retries reached — WebSocket unavailable (cloud mode)')
        return
      }

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/live`)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        retriesRef.current = 0 // Reset on successful connection
      }

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          setEvents(prev => [msg, ...prev].slice(0, MAX_EVENTS))
          subscribersRef.current.forEach(cb => cb(msg))
        } catch {
          // ignore malformed messages
        }
      }

      ws.onclose = () => {
        setConnected(false)
        retriesRef.current += 1
        if (retriesRef.current < MAX_RETRIES) {
          const delay = Math.min(INITIAL_DELAY * Math.pow(2, retriesRef.current - 1), MAX_DELAY)
          reconnectRef.current = setTimeout(connect, delay)
        }
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
