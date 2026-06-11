/**
 * DECIDE region sub-components (P2-T5, design §3.2).
 * Built ENTIRELY from the T7 honesty primitives. Every displayed value
 * renders through <Metric> or <SentinelGuard>; every freshness through
 * <StalenessBadge>.
 *
 * Cards are CHALLENGE-AND-RESPONSE: evidence first, then the
 * intent/blast-radius/rollback contract, then the action verbs. Degradation
 * is rendered explicitly, never hidden (laws #3/#4).
 */
import Metric from '../components/Metric'
import SentinelGuard from '../components/SentinelGuard'
import StalenessBadge from '../components/StalenessBadge'

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

const SUBLABEL_STYLE = {
  fontSize: 10,
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  color: 'var(--arcis-text-muted, #71717a)',
  fontFamily: 'var(--font-mono)',
  fontWeight: 600,
}

const RISK_TIER_COLORS = {
  high: { color: 'var(--arcis-danger, #ef4444)', border: 'rgba(239,68,68,0.4)', bg: 'rgba(239,68,68,0.1)' },
  medium: { color: 'var(--arcis-warning, #f59e0b)', border: 'rgba(245,158,11,0.4)', bg: 'rgba(245,158,11,0.1)' },
  low: { color: 'var(--arcis-text-secondary, #a1a1aa)', border: 'rgba(161,161,170,0.4)', bg: 'rgba(161,161,170,0.1)' },
}

const RISK_TIER_ORDER = ['high', 'medium', 'low']

// ---------------------------------------------------------------------------
// DecisionCard — challenge-and-response card
// Contract item: {decision_key, decision_type, title, risk_tier,
//   evidence:{label, items:[{label,value}]}, intent, blast_radius, rollback,
//   as_of, source_state}
// ---------------------------------------------------------------------------
const ACTION_BUTTON_STYLE = {
  padding: '6px 14px',
  borderRadius: 'var(--radius-sm)',
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
  fontWeight: 600,
  cursor: 'pointer',
  border: '1px solid var(--arcis-border, rgba(255,255,255,0.12))',
  background: 'transparent',
  color: 'var(--arcis-text-primary, #fff)',
}

export function DecisionCard({ item, onAction }) {
  const evidence = item?.evidence ?? {}
  const evidenceItems = Array.isArray(evidence.items) ? evidence.items : []
  const tier = RISK_TIER_COLORS[item?.risk_tier] || RISK_TIER_COLORS.low
  const degraded = item?.source_state === 'degraded'

  return (
    <article
      data-testid="decision-card"
      data-decision-key={item?.decision_key}
      style={{
        padding: 16,
        marginBottom: 12,
        border: '1px solid var(--arcis-border, rgba(255,255,255,0.12))',
        borderRadius: 'var(--radius-sm)',
        background: 'var(--arcis-surface, rgba(255,255,255,0.02))',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span
            data-testid="risk-tier-badge"
            style={{
              padding: '2px 8px',
              borderRadius: 'var(--radius-sm)',
              fontSize: 10,
              fontWeight: 700,
              fontFamily: 'var(--font-mono)',
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              color: tier.color,
              background: tier.bg,
              border: `1px solid ${tier.border}`,
            }}
          >
            {item?.risk_tier || 'unknown'}
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 14,
              fontWeight: 600,
              color: 'var(--arcis-text-primary, #fff)',
            }}
          >
            {item?.title}
          </span>
        </div>
        <StalenessBadge asOf={item?.as_of} />
      </div>

      {degraded && (
        <div
          data-testid="decision-source-degraded"
          style={{
            marginBottom: 12,
            padding: '6px 10px',
            borderRadius: 'var(--radius-sm)',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--arcis-warning, #f59e0b)',
            background: 'rgba(245,158,11,0.1)',
            border: '1px solid rgba(245,158,11,0.4)',
          }}
        >
          source degraded — evidence may be incomplete
        </div>
      )}

      {/* (1) evidence block */}
      <div data-testid="decision-evidence" style={{ marginBottom: 12 }}>
        <div style={{ ...SUBLABEL_STYLE, marginBottom: 6 }}>{evidence.label || 'Evidence'}</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
          {evidenceItems.map((ev, i) => (
            <div key={`${ev?.label ?? ''}-${i}`} style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                  color: 'var(--arcis-text-secondary, #a1a1aa)',
                }}
              >
                {ev?.label}
              </span>
              <SentinelGuard value={ev?.value} />
            </div>
          ))}
        </div>
      </div>

      {/* (2) intent / blast-radius / rollback */}
      <div data-testid="decision-contract" style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <span style={{ ...SUBLABEL_STYLE, minWidth: 96 }}>Intent</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--arcis-text-primary, #fff)' }}>
            {item?.intent}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <span style={{ ...SUBLABEL_STYLE, minWidth: 96 }}>Blast-radius</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--arcis-text-primary, #fff)' }}>
            {item?.blast_radius}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <span style={{ ...SUBLABEL_STYLE, minWidth: 96 }}>Rollback</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--arcis-text-primary, #fff)' }}>
            {item?.rollback}
          </span>
        </div>
      </div>

      {/* (3) action verbs + drill-in */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <button
          type="button"
          onClick={() => onAction(item, 'approve')}
          style={{
            ...ACTION_BUTTON_STYLE,
            color: 'var(--arcis-success, #22c55e)',
            borderColor: 'rgba(34,197,94,0.4)',
          }}
        >
          Approve
        </button>
        <button
          type="button"
          onClick={() => onAction(item, 'reject')}
          style={{
            ...ACTION_BUTTON_STYLE,
            color: 'var(--arcis-danger, #ef4444)',
            borderColor: 'rgba(239,68,68,0.4)',
          }}
        >
          Reject
        </button>
        <button
          type="button"
          onClick={() => onAction(item, 'defer')}
          style={ACTION_BUTTON_STYLE}
        >
          Defer
        </button>
        <button
          type="button"
          data-testid="decision-drill-in"
          onClick={() => onAction(item, 'details')}
          style={{
            ...ACTION_BUTTON_STYLE,
            marginLeft: 'auto',
            color: 'var(--arcis-text-muted, #71717a)',
            border: 'none',
            textDecoration: 'underline',
          }}
        >
          Details
        </button>
      </div>
    </article>
  )
}

// ---------------------------------------------------------------------------
// PendingQueue — group by risk_tier high → medium → low
// Contract data: {items, count, degraded_sources, as_of}
// ---------------------------------------------------------------------------
export function PendingQueue({ data, onAction }) {
  const unavailable = data?.state === 'unavailable'
  const items = Array.isArray(data?.items) ? data.items : []
  const degradedSources = Array.isArray(data?.degraded_sources) ? data.degraded_sources : []

  return (
    <section data-testid="decide-pending" style={SECTION_STYLE}>
      <div style={SECTION_TITLE_STYLE}>Decisions waiting</div>

      {!unavailable && degradedSources.length > 0 && (
        <div
          data-testid="degraded-sources-banner"
          style={{
            marginBottom: 12,
            padding: '8px 12px',
            borderRadius: 'var(--radius-sm)',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            color: 'var(--arcis-warning, #f59e0b)',
            background: 'rgba(245,158,11,0.1)',
            border: '1px solid rgba(245,158,11,0.4)',
          }}
        >
          Degraded sources — decisions shown may be incomplete: {degradedSources.join(', ')}
        </div>
      )}

      {unavailable ? (
        // Law #4: an unreadable queue must NEVER render as "No decisions
        // waiting" (false-empty / false all-clear). Show it explicitly.
        <div
          data-testid="pending-unavailable"
          style={{
            padding: '8px 12px',
            borderRadius: 'var(--radius-sm)',
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            color: 'var(--arcis-danger, #ef4444)',
            background: 'rgba(239,68,68,0.08)',
            border: '1px solid rgba(239,68,68,0.4)',
          }}
        >
          decision queue unavailable — source unreachable (not shown as “all clear”)
        </div>
      ) : items.length === 0 ? (
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            color: 'var(--arcis-text-muted, #71717a)',
            fontStyle: 'italic',
          }}
        >
          No decisions waiting
        </div>
      ) : (
        RISK_TIER_ORDER.map((tier) => {
          const tierItems = items.filter((it) => it?.risk_tier === tier)
          if (tierItems.length === 0) return null
          return (
            <div key={tier} data-testid="risk-tier-group" data-risk-tier={tier} style={{ marginBottom: 12 }}>
              {tierItems.map((it) => (
                <DecisionCard key={it.decision_key} item={it} onAction={onAction} />
              ))}
            </div>
          )
        })
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// RecentlyDecided — trail + override-rate metric
// Contract data: {items:[{id,decision_key,decision_type,action,risk_tier,
//   reason,decided_by,decided_at,created_at}],
//   override_rate:{value,n,as_of,cohort,unit,state}, as_of}
// ---------------------------------------------------------------------------
export function RecentlyDecided({ data }) {
  const unavailable = data?.state === 'unavailable'
  const items = Array.isArray(data?.items) ? data.items : []
  const overrideRate = data?.override_rate ?? {}
  const noData = overrideRate.state === 'no_data' || overrideRate.value == null

  return (
    <section data-testid="decide-decided" style={SECTION_STYLE}>
      <div style={SECTION_TITLE_STYLE}>Recently decided</div>

      <div style={{ marginBottom: 16, maxWidth: 360 }}>
        {unavailable ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={SUBLABEL_STYLE}>Override rate</div>
            <div
              data-testid="override-rate-unavailable"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 18,
                fontWeight: 600,
                color: 'var(--arcis-danger, #ef4444)',
              }}
            >
              — unavailable
            </div>
          </div>
        ) : noData ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={SUBLABEL_STYLE}>Override rate</div>
            <div
              data-testid="override-rate-no-data"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 18,
                fontWeight: 600,
                color: 'var(--arcis-text-muted, #71717a)',
              }}
            >
              — no decisions yet
            </div>
          </div>
        ) : (
          <Metric
            label="Override rate"
            value={<SentinelGuard value={overrideRate.value} />}
            cohort={overrideRate.cohort}
            n={overrideRate.n}
            asOf={overrideRate.as_of}
          />
        )}
        <div
          style={{
            marginTop: 8,
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            fontStyle: 'italic',
            color: 'var(--arcis-text-muted, #71717a)',
          }}
        >
          an approver who never overrides has stopped reviewing
        </div>
      </div>

      {unavailable ? (
        // Law #4: an unreadable trail is not an empty trail.
        <div
          data-testid="decided-trail"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            color: 'var(--arcis-danger, #ef4444)',
            fontStyle: 'italic',
          }}
        >
          decided trail unavailable — source unreachable
        </div>
      ) : items.length === 0 ? (
        <div
          data-testid="decided-trail"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            color: 'var(--arcis-text-muted, #71717a)',
            fontStyle: 'italic',
          }}
        >
          no decisions recorded yet
        </div>
      ) : (
        <ul
          data-testid="decided-trail"
          style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 6 }}
        >
          {items.map((d) => (
            <li
              key={d.id ?? `${d.decision_key}-${d.decided_at}`}
              style={{
                display: 'flex',
                gap: 12,
                fontFamily: 'var(--font-mono)',
                fontSize: 13,
                color: 'var(--arcis-text-secondary, #a1a1aa)',
              }}
            >
              <span style={{ fontWeight: 600, minWidth: 72 }}>{d.action}</span>
              <span style={{ minWidth: 160 }}>{d.decision_type}</span>
              <StalenessBadge asOf={d.decided_at} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
