/**
 * ResearchView — Research corpus + AI-Council panel drill-down (P3-T10).
 *
 * Consumes existing endpoints:
 *   GET /api/packets           — thesis/signal packets (array directly)
 *   GET /api/notes             — user notes {notes: [...]}
 *   GET /api/research/digest   — weekly digest row | {digest: null}
 *   GET /api/research/papers   — {papers: [...], count: N}
 *   GET /api/council/latest    — council session row | {session: null}
 *   GET /api/council/history   — array of session rows
 *
 * Design laws:
 *   - Honest empty states — never fabricate content
 *   - Council is a PANEL (not its own route)
 *   - Client-side search filter across packets + notes
 */
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../../api'
import AsyncBoundary from '../components/AsyncBoundary'
import StalenessBadge from '../components/StalenessBadge'
import { BackToOverview } from './components'

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
const SECTION_STYLE = {
  padding: '16px 24px',
  borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
}

const SECTION_TITLE_STYLE = {
  fontSize: 11,
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  color: 'var(--arcis-text-muted, #71717a)',
  fontFamily: 'var(--font-mono)',
  fontWeight: 600,
  marginBottom: 12,
}

const CARD_STYLE = {
  padding: '12px 16px',
  border: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
  borderRadius: 6,
  background: 'var(--arcis-surface, #18181b)',
  marginBottom: 8,
}

const TICKER_STYLE = {
  fontFamily: 'var(--font-mono)',
  fontWeight: 700,
  fontSize: 14,
  color: 'var(--arcis-text-primary, #fff)',
  marginRight: 8,
}

const META_STYLE = {
  fontSize: 11,
  fontFamily: 'var(--font-mono)',
  color: 'var(--arcis-text-muted, #71717a)',
}

const NOTE_TITLE_STYLE = {
  fontFamily: 'var(--font-mono)',
  fontWeight: 600,
  fontSize: 13,
  color: 'var(--arcis-text-primary, #fff)',
}

const EMPTY_STYLE = {
  padding: '16px 0',
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
  color: 'var(--arcis-text-muted, #71717a)',
}

const PANEL_STYLE = {
  padding: '16px 24px',
  border: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
  borderRadius: 6,
  background: 'var(--arcis-surface, #18181b)',
  margin: '16px 24px',
}

const CONSENSUS_BADGE_BASE = {
  display: 'inline-block',
  padding: '2px 8px',
  borderRadius: 4,
  fontSize: 10,
  fontFamily: 'var(--font-mono)',
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
}

function consensusBadgeStyle(consensus) {
  if (consensus === 'bullish') return { ...CONSENSUS_BADGE_BASE, color: 'var(--arcis-success, #22c55e)', background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.3)' }
  if (consensus === 'bearish') return { ...CONSENSUS_BADGE_BASE, color: 'var(--arcis-danger, #ef4444)', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)' }
  return { ...CONSENSUS_BADGE_BASE, color: 'var(--arcis-text-muted, #71717a)', background: 'rgba(113,113,122,0.15)', border: '1px dashed var(--arcis-text-muted, #71717a)' }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function formatShortDate(iso) {
  if (!iso) return ''
  return (iso || '').slice(0, 10)
}

// Strip system-prompt prefix from thesis_text (same logic as Packets.jsx)
const ANALYSIS_START_TAGS = [
  '<why_now>', '<thesis>', '<setup_analysis>', '<analysis>', '<assessment>',
  '<pullback_analysis>', '<mean_reversion_analysis>',
]
function cleanAnalysis(text) {
  if (!text) return ''
  let earliest = -1
  for (const tag of ANALYSIS_START_TAGS) {
    const i = text.indexOf(tag)
    if (i !== -1 && (earliest === -1 || i < earliest)) earliest = i
  }
  return (earliest === -1 ? text : text.slice(earliest)).trim()
}

// ---------------------------------------------------------------------------
// CouncilPanel — compact council panel inside ResearchView
// ---------------------------------------------------------------------------
function CouncilPanel() {
  const latestQuery = useQuery({
    queryKey: ['research-council-latest'],
    queryFn: () => fetchApi('/council/latest'),
  })
  const historyQuery = useQuery({
    queryKey: ['research-council-history'],
    queryFn: () => fetchApi('/council/history?days=30'),
  })

  // council/latest: session row directly OR {session: null}
  const raw = latestQuery.data
  const session = raw?.session_id ? raw : (raw?.session ?? null)
  const sessions = Array.isArray(historyQuery.data) ? historyQuery.data : []

  const consensus = session?.consensus ?? session?.result_json?.votes?.direction ?? null
  const confidenceAvg = session?.result_json?.votes?.confidence_avg ?? null
  const summary = session?.result_json?.summary ?? null
  const roundsCompleted = session?.rounds_completed ?? session?.result_json?.session_meta?.rounds_completed ?? null
  const asOf = session?.created_at ?? null

  return (
    <div data-testid="research-council-panel" style={PANEL_STYLE}>
      <div style={{ ...SECTION_TITLE_STYLE, marginBottom: 12 }}>AI Council</div>

      <AsyncBoundary query={latestQuery} label="Council session">
        {!session ? (
          <div data-testid="council-no-session" style={EMPTY_STYLE}>
            No council session yet — run the council to populate.
          </div>
        ) : (
          <div style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
              {consensus && (
                <span style={consensusBadgeStyle(consensus)}>{consensus}</span>
              )}
              {confidenceAvg != null && (
                <span style={META_STYLE}>conf: {(confidenceAvg * 100).toFixed(0)}%</span>
              )}
              {roundsCompleted != null && (
                <span style={META_STYLE}>rounds: {roundsCompleted}</span>
              )}
              {asOf && <StalenessBadge asOf={asOf} maxAge={7 * 24 * 3600} />}
            </div>
            {summary && (
              <div style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-muted, #71717a)', lineHeight: 1.6, marginTop: 8 }}>
                {summary}
              </div>
            )}
          </div>
        )}
      </AsyncBoundary>

      <div style={{ ...SECTION_TITLE_STYLE, marginTop: 12 }}>Recent sessions</div>
      <AsyncBoundary query={historyQuery} label="Council history">
        {sessions.length === 0 ? (
          <div data-testid="council-history-empty" style={EMPTY_STYLE}>
            No historical sessions.
          </div>
        ) : (
          <ul data-testid="council-history-list" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {sessions.slice(0, 5).map((s, i) => {
              const c = s.consensus ?? null
              return (
                <li
                  key={s.session_id ?? i}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    padding: '6px 0',
                    borderBottom: i < sessions.length - 1 ? '1px solid var(--arcis-border, rgba(255,255,255,0.08))' : 'none',
                  }}
                >
                  <span style={META_STYLE}>{formatShortDate(s.created_at)}</span>
                  <span style={META_STYLE}>{s.session_type ?? 'session'}</span>
                  {c && <span style={consensusBadgeStyle(c)}>{c}</span>}
                </li>
              )
            })}
          </ul>
        )}
      </AsyncBoundary>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ResearchView
// ---------------------------------------------------------------------------
export default function ResearchView() {
  const [search, setSearch] = useState('')

  const packetsQuery = useQuery({
    queryKey: ['research-packets'],
    queryFn: () => fetchApi('/packets'),
  })
  const notesQuery = useQuery({
    queryKey: ['research-notes'],
    queryFn: () => fetchApi('/notes'),
  })
  const digestQuery = useQuery({
    queryKey: ['research-digest'],
    queryFn: () => fetchApi('/research/digest'),
  })
  const papersQuery = useQuery({
    queryKey: ['research-papers'],
    queryFn: () => fetchApi('/research/papers'),
  })

  // Shape normalisation
  const allPackets = Array.isArray(packetsQuery.data) ? packetsQuery.data : []
  const allNotes = Array.isArray(notesQuery.data?.notes) ? notesQuery.data.notes : []
  const papers = Array.isArray(papersQuery.data?.papers) ? papersQuery.data.papers : []

  // /api/research/digest returns the row directly OR {digest: null}
  const digestRaw = digestQuery.data
  const digest = digestRaw?.id ? digestRaw : null

  // Client-side search filter across packets + notes
  const term = search.trim().toLowerCase()
  const filteredPackets = useMemo(() => {
    if (!term) return allPackets
    return allPackets.filter((p) => {
      const hay = `${p.ticker ?? ''} ${p.company_name ?? ''} ${cleanAnalysis(p.thesis_text ?? '')}`.toLowerCase()
      return hay.includes(term)
    })
  }, [allPackets, term])

  const filteredNotes = useMemo(() => {
    if (!term) return allNotes
    return allNotes.filter((n) => {
      const hay = `${n.title ?? ''} ${n.content ?? ''} ${(n.tags ?? []).join(' ')}`.toLowerCase()
      return hay.includes(term)
    })
  }, [allNotes, term])

  return (
    <div data-testid="know-research">
      <BackToOverview />

      {/* Search bar */}
      <section style={SECTION_STYLE}>
        <div style={{ ...SECTION_TITLE_STYLE, marginBottom: 8 }}>Research corpus</div>
        <input
          data-testid="research-search-input"
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search packets, notes..."
          style={{
            padding: '6px 12px',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            background: 'var(--arcis-surface, #18181b)',
            border: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
            borderRadius: 4,
            color: 'var(--arcis-text-primary, #fff)',
            outline: 'none',
            width: 280,
          }}
        />
      </section>

      {/* Packets */}
      <AsyncBoundary query={packetsQuery} label="Signal packets">
        <section style={SECTION_STYLE}>
          <div style={SECTION_TITLE_STYLE}>Signal packets</div>
          {filteredPackets.length === 0 ? (
            <div data-testid="research-packets-empty" style={EMPTY_STYLE}>
              {allPackets.length === 0 ? 'No packets in corpus.' : 'No packets match this search.'}
            </div>
          ) : (
            <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {filteredPackets.map((p, i) => (
                <li key={p.recommendation_id ?? i} style={CARD_STYLE}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={TICKER_STYLE}>{p.ticker}</span>
                    {p.company_name && (
                      <span style={META_STYLE}>{p.company_name}</span>
                    )}
                    <span style={META_STYLE}>score: {(p.priority_score ?? 0).toFixed(0)}</span>
                    <span style={{ flex: 1 }} />
                    <span style={META_STYLE}>{formatShortDate(p.created_at)}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </AsyncBoundary>

      {/* Notes */}
      <AsyncBoundary query={notesQuery} label="Notes">
        <section style={SECTION_STYLE}>
          <div style={SECTION_TITLE_STYLE}>Notes</div>
          {filteredNotes.length === 0 ? (
            <div data-testid="research-notes-empty" style={EMPTY_STYLE}>
              {allNotes.length === 0 ? 'No notes yet.' : 'No notes match this search.'}
            </div>
          ) : (
            <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {filteredNotes.map((n, i) => (
                <li key={n.note_id ?? i} style={CARD_STYLE}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    {n.pinned && (
                      <span style={{ fontSize: 9, fontFamily: 'var(--font-mono)', fontWeight: 700, textTransform: 'uppercase', color: 'var(--arcis-accent, #6366f1)' }}>pinned</span>
                    )}
                    <span style={NOTE_TITLE_STYLE}>{n.title}</span>
                    <span style={{ flex: 1 }} />
                    <span style={META_STYLE}>{formatShortDate(n.updated_at ?? n.created_at)}</span>
                  </div>
                  {(n.tags ?? []).length > 0 && (
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
                      {n.tags.map((tag) => (
                        <span key={tag} style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-muted, #71717a)', background: 'rgba(113,113,122,0.15)', padding: '1px 6px', borderRadius: 3 }}>
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </AsyncBoundary>

      {/* Weekly digest */}
      <AsyncBoundary query={digestQuery} label="Weekly digest">
        <section style={SECTION_STYLE}>
          <div style={SECTION_TITLE_STYLE}>Weekly digest</div>
          {!digest ? (
            <div data-testid="research-digest-empty" style={EMPTY_STYLE}>
              Digest not yet synthesized.
            </div>
          ) : (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                {digest.week_start && digest.week_end && (
                  <span style={META_STYLE}>{digest.week_start} — {digest.week_end}</span>
                )}
                {digest.created_at && <StalenessBadge asOf={digest.created_at} maxAge={7 * 24 * 3600} />}
              </div>
              {digest.summary && (
                <div style={{ fontSize: 13, fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-muted, #71717a)', lineHeight: 1.6 }}>
                  {digest.summary}
                </div>
              )}
            </div>
          )}
        </section>
      </AsyncBoundary>

      {/* Research papers */}
      <AsyncBoundary query={papersQuery} label="Research papers">
        <section style={SECTION_STYLE}>
          <div style={SECTION_TITLE_STYLE}>Research papers</div>
          {papers.length === 0 ? (
            <div data-testid="research-papers-empty" style={EMPTY_STYLE}>
              No recent papers.
            </div>
          ) : (
            <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {papers.map((p, i) => (
                <li key={p.id ?? i} style={CARD_STYLE}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                    <div style={{ flex: 1 }}>
                      {p.url ? (
                        <a
                          href={p.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 600, color: 'var(--arcis-accent, #6366f1)', textDecoration: 'none' }}
                        >
                          {p.title}
                        </a>
                      ) : (
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 600, color: 'var(--arcis-text-primary, #fff)' }}>{p.title}</span>
                      )}
                      {p.authors && <div style={META_STYLE}>{p.authors}</div>}
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
                      <span style={META_STYLE}>score: {p.relevance_score != null ? p.relevance_score.toFixed(2) : '--'}</span>
                      <span style={META_STYLE}>{formatShortDate(p.published_date)}</span>
                    </div>
                  </div>
                  {p.relevance_reason && (
                    <div style={{ ...META_STYLE, marginTop: 6, lineHeight: 1.5 }}>{p.relevance_reason}</div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </AsyncBoundary>

      {/* AI Council panel */}
      <CouncilPanel />
    </div>
  )
}
