import { useWebSocketContext } from '../contexts/WebSocketContext'

export default function useWebSocket() {
  const { events, connected, clearEvents } = useWebSocketContext()
  return { events, connected, clearEvents }
}
