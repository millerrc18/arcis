import { useState, useRef, useEffect } from 'react'

export default function Tooltip({ content, children, delay = 300, interactive = false }) {
  const [visible, setVisible] = useState(false)
  const [position, setPosition] = useState({ top: 0, left: 0 })
  const timeoutRef = useRef(null)
  const triggerRef = useRef(null)
  const tooltipRef = useRef(null)

  const show = () => {
    clearTimeout(timeoutRef.current)
    timeoutRef.current = setTimeout(() => {
      if (triggerRef.current) {
        const rect = triggerRef.current.getBoundingClientRect()
        setPosition({
          top: rect.top - 8,
          left: rect.left + rect.width / 2,
        })
      }
      setVisible(true)
    }, delay)
  }

  const hide = () => {
    clearTimeout(timeoutRef.current)
    timeoutRef.current = setTimeout(() => {
      setVisible(false)
    }, interactive ? 300 : 0)
  }

  useEffect(() => {
    return () => clearTimeout(timeoutRef.current)
  }, [])

  return (
    <span
      ref={triggerRef}
      onMouseEnter={show}
      onMouseLeave={hide}
      style={{ display: 'inline-block' }}
    >
      {children}
      {visible && (
        <div
          ref={tooltipRef}
          data-tooltip-surface
          onMouseEnter={interactive ? () => clearTimeout(timeoutRef.current) : undefined}
          onMouseLeave={interactive ? hide : undefined}
          style={{
            position: 'fixed',
            top: position.top,
            left: position.left,
            transform: 'translate(-50%, -100%)',
            background: 'var(--arcis-bg-primary)',
            border: '1px solid var(--arcis-border)',
            borderRadius: 'var(--radius-lg)',
            padding: '0.5rem 0.75rem',
            fontSize: '0.75rem',
            lineHeight: '1.4',
            color: 'var(--arcis-text-primary)',
            maxWidth: '300px',
            zIndex: 50,
            pointerEvents: interactive ? 'auto' : 'none',
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          }}
        >
          {content}
        </div>
      )}
    </span>
  )
}
