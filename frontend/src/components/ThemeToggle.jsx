import { useEffect, useState } from 'react'
import { Moon, Sun } from 'lucide-react'

export default function ThemeToggle() {
  const [theme, setTheme] = useState(() => localStorage.getItem('arcis-theme') || 'dark')

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('arcis-theme', theme)
  }, [theme])

  return (
    <button
      onClick={() => setTheme((current) => current === 'dark' ? 'light' : 'dark')}
      style={{
        background: 'transparent',
        border: '1px solid var(--arcis-border)',
        borderRadius: 'var(--radius-md)',
        color: 'var(--arcis-text-secondary)',
        padding: '6px',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
      title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
    >
      {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  )
}
