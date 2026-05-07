import { useState } from 'react'
import Tooltip from './Tooltip.jsx'

async function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return { success: true, mode: 'clipboard' }
    } catch (err) {
      // fall through to non-secure-context fallback
    }
  }
  return { success: false, mode: 'manual', hint: 'Press Ctrl+C to copy' }
}

export default function ActionButton({
  cliOnly = false,
  cliCommand,
  whyDisabled,
  onClick,
  pending = false,
  children,
}) {
  const [copyHint, setCopyHint] = useState('')

  if (cliOnly) {
    const tooltipContent = (
      <div>
        {whyDisabled && <div>{whyDisabled}</div>}
        {whyDisabled && <hr style={{ margin: '0.25rem 0', borderColor: 'var(--arcis-border)' }} />}
        <pre
          onClick={(e) => { window.getSelection().selectAllChildren(e.currentTarget) }}
          style={{ fontFamily: 'monospace', margin: '0.25rem 0', cursor: 'pointer', whiteSpace: 'pre-wrap' }}
        >{cliCommand}</pre>
        <button
          onClick={async () => {
            const r = await copyToClipboard(cliCommand)
            setCopyHint(r.success ? 'Copied!' : r.hint)
          }}
          style={{
            marginTop: '0.25rem',
            padding: '0.125rem 0.5rem',
            fontSize: '0.7rem',
            borderRadius: 'var(--radius-sm)',
            background: 'var(--arcis-border)',
            color: 'var(--arcis-text-primary)',
            cursor: 'pointer',
          }}
        >
          Copy
        </button>
        {copyHint && <span style={{ marginLeft: '0.5rem', fontSize: '0.7rem' }}>{copyHint}</span>}
      </div>
    )

    return (
      <Tooltip content={tooltipContent}>
        <button
          disabled
          className="px-3 py-1.5 text-xs rounded opacity-50 cursor-not-allowed"
          style={{ background: 'var(--arcis-border)', color: 'var(--arcis-text-secondary)' }}
        >
          {children} <span>[CLI only]</span>
        </button>
      </Tooltip>
    )
  }

  return (
    <button
      disabled={pending}
      onClick={pending ? undefined : onClick}
      className="px-3 py-1.5 text-xs rounded"
      style={{
        background: pending ? 'var(--arcis-border)' : 'var(--arcis-accent)',
        color: 'var(--arcis-text-primary)',
        cursor: pending ? 'not-allowed' : 'pointer',
        opacity: pending ? 0.7 : 1,
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.375rem',
      }}
    >
      {pending && (
        <span
          role="status"
          className="animate-spin"
          style={{
            display: 'inline-block',
            width: '0.75rem',
            height: '0.75rem',
            border: '2px solid currentColor',
            borderTopColor: 'transparent',
            borderRadius: '50%',
          }}
        />
      )}
      {children}
    </button>
  )
}
