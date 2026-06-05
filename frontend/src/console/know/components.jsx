/**
 * KNOW region sub-components (P3-T4, design §3.3).
 * Overview synthesis cards + drill-down stub components.
 * Each stub carries its own data-testid for later task fill-in.
 */
import { Link } from 'react-router-dom'

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

const CARD_GRID_STYLE = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
  gap: 12,
}

const CARD_STYLE = {
  display: 'flex',
  flexDirection: 'column',
  gap: 6,
  padding: '14px 16px',
  border: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
  borderRadius: 6,
  background: 'var(--arcis-surface, #18181b)',
  textDecoration: 'none',
  color: 'inherit',
  cursor: 'pointer',
  transition: 'border-color 0.15s',
}

const PINNED_CARD_STYLE = {
  ...CARD_STYLE,
  borderColor: 'var(--arcis-accent, #6366f1)',
  background: 'rgba(99,102,241,0.06)',
}

const CARD_LABEL_STYLE = {
  fontSize: 13,
  fontFamily: 'var(--font-mono)',
  fontWeight: 600,
  color: 'var(--arcis-text-primary, #fff)',
}

const CARD_HINT_STYLE = {
  fontSize: 11,
  fontFamily: 'var(--font-mono)',
  color: 'var(--arcis-text-muted, #71717a)',
}

const PINNED_BADGE_STYLE = {
  display: 'inline-block',
  fontSize: 9,
  fontFamily: 'var(--font-mono)',
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.1em',
  color: 'var(--arcis-accent, #6366f1)',
  marginBottom: 2,
}

const BACK_LINK_STYLE = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  fontSize: 12,
  fontFamily: 'var(--font-mono)',
  color: 'var(--arcis-text-muted, #71717a)',
  textDecoration: 'none',
  padding: '8px 24px',
  borderBottom: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
}

const STUB_STYLE = {
  padding: 32,
  color: 'var(--arcis-text-muted, #71717a)',
  fontFamily: 'var(--font-mono)',
  fontSize: 13,
  textAlign: 'center',
}

// ---------------------------------------------------------------------------
// BackToOverview — back affordance rendered on every drill-down
// ---------------------------------------------------------------------------
export function BackToOverview() {
  return (
    <Link to="/console/know" data-testid="know-back-link" style={BACK_LINK_STYLE}>
      ← Know overview
    </Link>
  )
}

// ---------------------------------------------------------------------------
// KnowOverview — synthesis cards (3 pinned + 5 entry cards)
// ---------------------------------------------------------------------------
const PINNED_ITEMS = [
  { label: 'Fund ladder', to: '/console/know/ladder', hint: 'Live fund composition & transitions' },
  { label: 'Track record', to: '/console/know/track-record', hint: 'Audited performance history' },
  { label: 'Trade ledgers', to: '/console/know/ledgers', hint: 'Full trade log & P&L breakdown' },
]

const ENTRY_ITEMS = [
  { label: 'System map', to: '/console/know/system-map', hint: 'Architecture & component graph' },
  { label: 'Rigor stack', to: '/console/know/rigor', hint: 'Test coverage & quality gates' },
  { label: 'Attribution', to: '/console/know/attribution', hint: 'Alpha source decomposition' },
  { label: 'Research & calibration', to: '/console/know/research', hint: 'Signal calibration log' },
  { label: 'AI dev-team scorecards', to: '/console/know/scorecards', hint: 'Agent output quality metrics' },
]

export function KnowOverview() {
  return (
    <div data-testid="know-overview">
      <section style={SECTION_STYLE}>
        <div style={SECTION_TITLE_STYLE}>Pinned — first-class synthesis</div>
        <div style={CARD_GRID_STYLE}>
          {PINNED_ITEMS.map((item) => (
            <Link key={item.to} to={item.to} style={PINNED_CARD_STYLE}>
              <span style={PINNED_BADGE_STYLE}>pinned</span>
              <span style={CARD_LABEL_STYLE}>{item.label}</span>
              <span style={CARD_HINT_STYLE}>{item.hint}</span>
            </Link>
          ))}
        </div>
      </section>

      <section style={SECTION_STYLE}>
        <div style={SECTION_TITLE_STYLE}>Drill-down library</div>
        <div style={CARD_GRID_STYLE}>
          {ENTRY_ITEMS.map((item) => (
            <Link key={item.to} to={item.to} style={CARD_STYLE}>
              <span style={CARD_LABEL_STYLE}>{item.label}</span>
              <span style={CARD_HINT_STYLE}>{item.hint}</span>
            </Link>
          ))}
        </div>
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Drill-down stub components — later tasks fill these
// ---------------------------------------------------------------------------
function DrillStub({ testId, label }) {
  return (
    <div>
      <BackToOverview />
      <div data-testid={testId} style={STUB_STYLE}>
        {label} — coming soon
      </div>
    </div>
  )
}

export function LadderStub() {
  return <DrillStub testId="know-ladder" label="Fund ladder" />
}

export function TrackRecordStub() {
  return <DrillStub testId="know-track-record" label="Track record" />
}

export function LedgersStub() {
  return <DrillStub testId="know-ledgers" label="Trade ledgers" />
}

export function SystemMapStub() {
  return <DrillStub testId="know-system-map" label="System map" />
}

export function RigorStub() {
  return <DrillStub testId="know-rigor" label="Rigor stack" />
}

export function AttributionStub() {
  return <DrillStub testId="know-attribution" label="Attribution" />
}

export function ResearchStub() {
  return <DrillStub testId="know-research" label="Research & calibration" />
}

export function ScorecardsStub() {
  return <DrillStub testId="know-scorecards" label="AI dev-team scorecards" />
}
