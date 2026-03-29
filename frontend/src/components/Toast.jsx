import { useState, useEffect, useCallback } from 'react'

let addToastGlobal = null

export function useToast() {
  return { addToast: addToastGlobal }
}

export function toast(message, type = 'info') {
  if (addToastGlobal) addToastGlobal({ message, type })
}

const colorMap = {
  success: { bg: 'rgba(16, 185, 129, 0.2)', border: 'var(--success)', text: 'var(--teal-200)' },
  error: { bg: 'rgba(239, 68, 68, 0.2)', border: 'var(--danger)', text: '#fca5a5' },
  info: { bg: 'rgba(59, 130, 246, 0.2)', border: 'var(--info)', text: '#93c5fd' },
  warning: { bg: 'rgba(245, 158, 11, 0.2)', border: 'var(--warning)', text: 'var(--amber-200)' },
}

export default function ToastContainer() {
  const [toasts, setToasts] = useState([])

  const addToast = useCallback(({ message, type = 'info' }) => {
    const id = Date.now() + Math.random()
    setToasts(prev => [...prev, { id, message, type }])
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, 5000)
  }, [])

  useEffect(() => {
    addToastGlobal = addToast
    return () => { addToastGlobal = null }
  }, [addToast])

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
      {toasts.map(t => {
        const c = colorMap[t.type] || colorMap.info
        return (
          <div key={t.id}
            className="px-4 py-3 rounded text-sm shadow-lg"
            style={{ background: c.bg, border: `1px solid ${c.border}`, color: c.text }}
          >
            {t.message}
          </div>
        )
      })}
    </div>
  )
}
