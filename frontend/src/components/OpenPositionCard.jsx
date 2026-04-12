import { useState } from 'react'

// Open-position monitor card (DB-2 Task 3). Replaces flat table rows for
// open trades with a richer layout: current price vs entry, stop/target
// progress gauge, days held + timeout remaining, MFE/MAE, bracket status,
// conviction at entry, and a close button. Works for both paper (shadow)
// and live trades — the only difference is where price updates come from,
// and that's already handled server-side (current_price enriched on the
// live ledger endpoint).

function fmt$(v, digits = 2) {
  if (v == null || Number.isNaN(v)) return '--'
  return `$${Number(v).toFixed(digits)}`
}

function fmtPct(v, digits = 2) {
  if (v == null || Number.isNaN(v)) return '--'
  const sign = v >= 0 ? '+' : ''
  return `${sign}${Number(v).toFixed(digits)}%`
}

function safeNumber(v) {
  if (v == null) return null
  const n = typeof v === 'number' ? v : parseFloat(v)
  return Number.isFinite(n) ? n : null
}

// Gauge: where current price sits between stop and target. 0 = at stop, 100 = at target.
function progressPct(entry, stop, target, current) {
  if (entry == null || current == null) return null
  const lo = stop ?? entry
  const hi = target ?? entry
  if (hi === lo) return null
  const pct = ((current - lo) / (hi - lo)) * 100
  return Math.max(0, Math.min(100, pct))
}

function ProgressGauge({ stop, entry, target, current }) {
  const pct = progressPct(entry, stop, target, current)
  if (pct == null) return null
  const entryMark = progressPct(entry, stop, target, entry) ?? 0
  return (
    <div className="mt-2">
      <div className="relative h-2 rounded-full" style={{ background: 'var(--arcis-bg-elevated)', overflow: 'hidden' }}>
        <div className="absolute inset-y-0 left-0" style={{
          width: `${pct}%`,
          background: pct >= entryMark ? 'var(--arcis-success)' : 'var(--arcis-danger)',
          opacity: 0.8,
        }} />
        <div className="absolute top-0 bottom-0" style={{
          left: `${entryMark}%`,
          width: 2,
          background: 'var(--arcis-text-primary)',
          opacity: 0.6,
        }} />
      </div>
      <div className="flex justify-between text-xs mt-1" style={{ color: 'var(--arcis-text-muted)', fontFamily: 'var(--font-mono)' }}>
        <span>{fmt$(stop)} stop</span>
        <span>{fmt$(entry)} entry</span>
        <span>{fmt$(target)} target</span>
      </div>
    </div>
  )
}

function BracketStatus({ trade }) {
  const hasStop = safeNumber(trade.stop_price) != null
  const hasTarget = safeNumber(trade.target_1) != null
  if (hasStop && hasTarget) return <span style={{ color: 'var(--arcis-success)' }}>bracket ok</span>
  if (!hasStop && !hasTarget) return <span style={{ color: 'var(--arcis-danger)' }}>no bracket</span>
  return <span style={{ color: 'var(--arcis-warning)' }}>partial</span>
}

export default function OpenPositionCard({ trade, onClose }) {
  const [busy, setBusy] = useState(false)
  const entry = safeNumber(trade.actual_entry_price) ?? safeNumber(trade.entry_price)
  const current = safeNumber(trade.current_price)
  const stop = safeNumber(trade.stop_price)
  const target = safeNumber(trade.target_1)
  const pnlDollars = safeNumber(trade.pnl_dollars)
  const pnlPct = safeNumber(trade.pnl_pct)
  const daysHeld = safeNumber(trade.duration_days)
  const timeoutDays = safeNumber(trade.timeout_days) ?? 8
  const daysRemaining = daysHeld != null ? Math.max(0, timeoutDays - daysHeld) : null
  const mfe = safeNumber(trade.max_favorable_excursion)
  const mae = safeNumber(trade.max_adverse_excursion)
  const conviction = safeNumber(trade.setup_confidence) ?? safeNumber(trade.priority_score)
  const broker = trade.broker || 'alpaca'
  const isPos = pnlDollars != null && pnlDollars >= 0

  async function handleClose() {
    if (!onClose || busy) return
    setBusy(true)
    try { await onClose(trade) } finally { setBusy(false) }
  }

  return (
    <div className="arcis-card" style={{ padding: '14px' }}>
      <div className="flex items-start justify-between mb-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-medium text-base" style={{ fontFamily: 'var(--font-mono)' }}>{trade.ticker}</span>
            <span className="text-xs uppercase tracking-wide px-1.5 py-0.5 rounded" style={{
              background: 'var(--arcis-bg-elevated)',
              color: 'var(--arcis-text-muted)',
            }}>
              {trade.direction || 'long'}
            </span>
            <span className="text-xs uppercase tracking-wide px-1.5 py-0.5 rounded" style={{
              background: broker === 'ib' ? 'rgba(59,130,246,0.15)' : 'rgba(168,85,247,0.15)',
              color: broker === 'ib' ? '#60a5fa' : '#c084fc',
            }}>
              {broker}
            </span>
          </div>
          <div className="text-xs mt-0.5" style={{ color: 'var(--arcis-text-muted)' }}>
            {current != null ? `${fmt$(current)} (now)` : 'price pending'} vs {fmt$(entry)} entry
          </div>
        </div>
        <div className="text-right">
          <div className="financial-data text-lg" style={{ color: isPos ? 'var(--arcis-success)' : 'var(--arcis-danger)' }}>
            {pnlDollars != null ? (isPos ? '+' : '') + fmt$(pnlDollars).replace('$', '$') : '--'}
          </div>
          <div className="text-xs" style={{ color: isPos ? 'var(--arcis-success)' : 'var(--arcis-danger)' }}>
            {fmtPct(pnlPct)}
          </div>
        </div>
      </div>

      <ProgressGauge stop={stop} entry={entry} target={target} current={current ?? entry} />

      <div className="grid grid-cols-4 gap-3 mt-3 text-xs">
        <div>
          <div style={{ color: 'var(--arcis-text-muted)' }}>Days held</div>
          <div style={{ fontFamily: 'var(--font-mono)' }}>
            {daysHeld != null ? `${daysHeld}d` : '--'}
            {daysRemaining != null && <span style={{ color: 'var(--arcis-text-muted)' }}> / {daysRemaining} left</span>}
          </div>
        </div>
        <div>
          <div style={{ color: 'var(--arcis-text-muted)' }}>MFE / MAE</div>
          <div style={{ fontFamily: 'var(--font-mono)' }}>
            <span style={{ color: 'var(--arcis-success)' }}>{mfe != null ? fmtPct(mfe) : '--'}</span>
            {' / '}
            <span style={{ color: 'var(--arcis-danger)' }}>{mae != null ? fmtPct(mae) : '--'}</span>
          </div>
        </div>
        <div>
          <div style={{ color: 'var(--arcis-text-muted)' }}>Bracket</div>
          <div style={{ fontFamily: 'var(--font-mono)' }}><BracketStatus trade={trade} /></div>
        </div>
        <div>
          <div style={{ color: 'var(--arcis-text-muted)' }}>Conviction</div>
          <div style={{ fontFamily: 'var(--font-mono)' }}>{conviction != null ? conviction.toFixed(0) : '--'}</div>
        </div>
      </div>

      {onClose && (
        <div className="flex justify-end mt-3">
          <button
            onClick={handleClose}
            disabled={busy}
            className="px-3 py-1 text-xs"
            style={{
              borderRadius: 'var(--radius-sm)',
              background: 'var(--arcis-bg-elevated)',
              border: '1px solid var(--arcis-border)',
              color: busy ? 'var(--arcis-text-muted)' : 'var(--arcis-danger)',
              cursor: busy ? 'wait' : 'pointer',
            }}
          >
            {busy ? 'Closing...' : 'Close position'}
          </button>
        </div>
      )}
    </div>
  )
}
