/**
 * AttributionView — KNOW drill-down: Alpha Attribution + Calibration (P3-T9).
 *
 * Part 1 — ATTRIBUTION (SALVAGE):
 *   Consumes /attribution/stats (analytics.py lines 788-799) and
 *   /shadow/sharpe-attribution (trades.py lines 128-142).
 *   Renders alpha vs SPY-beta + ranker vs LLM breakdown.
 *
 * Part 2 — CALIBRATION (NEW):
 *   Consumes /console/know/calibration (console_know.py lines 297-346).
 *   Frozen contract: {buckets, join_source, as_of, state}.
 *   state==="no_data" or empty buckets → explicit "no joined outcomes yet" message,
 *   NEVER rendered as 0% win rate.
 */
import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../../api'
import Metric from '../components/Metric'
import SentinelGuard from '../components/SentinelGuard'
import StalenessBadge from '../components/StalenessBadge'
import { BackToOverview } from './components'

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
  gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
  gap: 12,
}

const META_STYLE = {
  fontSize: 10,
  fontFamily: 'var(--font-mono)',
  color: 'var(--arcis-text-muted, #71717a)',
  marginTop: 4,
}

// ---------------------------------------------------------------------------
// AttributionSection — alpha/beta + ranker vs LLM
// ---------------------------------------------------------------------------

function AttributionSection({ statsData, sharpeData }) {
  const stats = statsData || {}
  const sharpe = sharpeData || {}

  const totalPairs = stats.total_pairs ?? null
  const pairedN = stats.paired_n ?? null
  const ranker = stats.ranker_only || {}
  const llm = stats.llm_portfolio || {}
  const byAction = stats.by_action || {}
  const byPairType = stats.by_pair_type || {}
  const statPower = stats.statistical_power ?? null

  const rawSharpe = sharpe.raw_sharpe ?? null
  const excessSharpe = sharpe.excess_sharpe ?? null
  const excessTStat = sharpe.excess_t_stat ?? null
  const interpretation = sharpe.interpretation ?? null
  const hitRate = sharpe.hit_rate_vs_spy ?? null
  const nTrades = sharpe.n_trades ?? null

  const rankerWinRate = ranker.win_rate != null ? (ranker.win_rate * 100).toFixed(1) + '%' : null
  const llmWinRate = llm.win_rate != null ? (llm.win_rate * 100).toFixed(1) + '%' : null

  const nowIso = new Date().toISOString()
  const statsAsOf = stats._meta?.as_of ?? nowIso
  const statsN = stats._meta?.n ?? pairedN ?? 0
  const statsCohort = stats._meta?.cohort ?? 'attribution.pairs'

  return (
    <section style={SECTION_STYLE}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={SECTION_TITLE_STYLE}>Alpha Attribution</div>
        <StalenessBadge asOf={statsAsOf} maxAge={3600} />
      </div>

      {/* Sharpe metrics grid */}
      <div style={{ ...CARD_GRID_STYLE, marginBottom: 16 }}>
        <Metric
          label="Raw Sharpe"
          value={<SentinelGuard value={rawSharpe} />}
          cohort="trades.swing"
          n={nTrades ?? 0}
          asOf={statsAsOf}
        />
        <Metric
          label="Excess Sharpe vs SPY"
          value={<SentinelGuard value={excessSharpe} />}
          cohort="trades.swing"
          n={nTrades ?? 0}
          asOf={statsAsOf}
        />
        <Metric
          label="Excess t-stat"
          value={<SentinelGuard value={excessTStat} />}
          cohort="trades.swing"
          n={nTrades ?? 0}
          asOf={statsAsOf}
        />
        <Metric
          label="SPY hit rate %"
          value={<SentinelGuard value={hitRate} />}
          cohort="trades.swing"
          n={nTrades ?? 0}
          asOf={statsAsOf}
        />
      </div>

      {interpretation && (
        <div style={{ ...META_STYLE, marginBottom: 16, fontSize: 12 }}>
          Interpretation: <span style={{ color: 'var(--arcis-text-secondary, #a1a1aa)' }}>{interpretation}</span>
        </div>
      )}

      {/* Ranker vs LLM section */}
      <div style={SECTION_TITLE_STYLE}>Ranker vs LLM portfolio</div>
      <div style={{ ...CARD_GRID_STYLE, marginBottom: 16 }}>
        <Metric
          label="Ranker win rate"
          value={<SentinelGuard value={rankerWinRate} />}
          cohort={statsCohort}
          n={statsN}
          asOf={statsAsOf}
        />
        <Metric
          label="LLM portfolio win rate"
          value={<SentinelGuard value={llmWinRate} />}
          cohort={statsCohort}
          n={statsN}
          asOf={statsAsOf}
        />
        <Metric
          label="Paired N"
          value={<SentinelGuard value={pairedN} />}
          cohort={statsCohort}
          n={statsN}
          asOf={statsAsOf}
        />
        <Metric
          label="Statistical power"
          value={<SentinelGuard value={statPower} />}
          cohort={statsCohort}
          n={statsN}
          asOf={statsAsOf}
        />
      </div>

      {/* By action breakdown */}
      {Object.keys(byAction).length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={SECTION_TITLE_STYLE}>By LLM action</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {Object.entries(byAction).map(([action, count]) => (
              <div
                key={action}
                style={{
                  padding: '4px 10px',
                  border: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
                  borderRadius: 4,
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  color: 'var(--arcis-text-secondary, #a1a1aa)',
                  display: 'flex',
                  gap: 6,
                }}
              >
                <span>{action.replace(/_/g, ' ')}</span>
                <span style={{ color: 'var(--arcis-text-primary, #fff)', fontWeight: 600 }}>{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* By pair type breakdown */}
      {Object.keys(byPairType).length > 0 && (
        <div>
          <div style={SECTION_TITLE_STYLE}>By pair type</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {Object.entries(byPairType).map(([ptype, count]) => (
              <div
                key={ptype}
                style={{
                  padding: '4px 10px',
                  border: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
                  borderRadius: 4,
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  color: 'var(--arcis-text-secondary, #a1a1aa)',
                  display: 'flex',
                  gap: 6,
                }}
              >
                <span>{ptype.replace(/_/g, ' ')}</span>
                <span style={{ color: 'var(--arcis-text-primary, #fff)', fontWeight: 600 }}>{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ ...META_STYLE, marginTop: 12 }}>
        Total pairs: {totalPairs != null ? totalPairs : '--'}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// CalibrationSection — conviction bands → outcome calibration
// ---------------------------------------------------------------------------

function CalibrationSection({ calibData }) {
  const calib = calibData || {}
  const buckets = Array.isArray(calib.buckets) ? calib.buckets : []
  const joinSource = calib.join_source ?? null
  const asOf = calib.as_of ?? null
  const state = calib.state ?? 'unknown'

  const noData = state === 'no_data' || state === 'unknown' || buckets.length === 0

  return (
    <section style={SECTION_STYLE}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={SECTION_TITLE_STYLE}>Confidence calibration</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              fontSize: 10,
              fontFamily: 'var(--font-mono)',
              color: 'var(--arcis-text-muted, #71717a)',
              padding: '2px 6px',
              border: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
              borderRadius: 3,
            }}
          >
            {state}
          </span>
          <StalenessBadge asOf={asOf} maxAge={3600} />
        </div>
      </div>

      {/* join_source — surfaces the data provenance so degraded joins are visible */}
      {joinSource && (
        <div style={{ ...META_STYLE, marginBottom: 12, fontSize: 11 }}>
          source: {joinSource}
        </div>
      )}

      {/* no_data or unknown state — explicit empty message, NOT a 0% win rate */}
      {noData ? (
        <div
          data-testid="calibration-no-data"
          style={{
            padding: '16px',
            border: '1px dashed var(--arcis-text-muted, #71717a)',
            borderRadius: 6,
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            color: 'var(--arcis-text-muted, #71717a)',
            textAlign: 'center',
          }}
        >
          No joined outcomes yet — confidence calibration requires recommendation_id→outcome matches
        </div>
      ) : (
        <div style={CARD_GRID_STYLE}>
          {buckets.map((bucket) => (
            <div
              key={bucket.confidence_band}
              style={{
                padding: '12px 16px',
                border: '1px solid var(--arcis-border, rgba(255,255,255,0.08))',
                borderRadius: 6,
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
              }}
            >
              <div style={{ fontSize: 13, fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--arcis-text-primary, #fff)' }}>
                Confidence {bucket.confidence_band}
              </div>

              <Metric
                label="Win rate"
                value={
                  bucket.state === 'no_data' || bucket.win_rate == null
                    ? <SentinelGuard value={null} />
                    : <SentinelGuard value={(bucket.win_rate * 100).toFixed(1) + '%'} />
                }
                cohort="calibration.band"
                n={bucket.n}
                asOf={asOf ?? new Date().toISOString()}
              />

              <Metric
                label="Avg excess return"
                value={
                  bucket.state === 'no_data' || bucket.avg_excess_return == null
                    ? <SentinelGuard value={null} />
                    : <SentinelGuard value={bucket.avg_excess_return} />
                }
                cohort="calibration.band"
                n={bucket.n}
                asOf={asOf ?? new Date().toISOString()}
              />
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// AttributionView — top-level
// ---------------------------------------------------------------------------

export default function AttributionView() {
  const statsQuery = useQuery({
    queryKey: ['attribution-stats'],
    queryFn: () => fetchApi('/attribution/stats'),
  })

  const sharpeQuery = useQuery({
    queryKey: ['shadow-sharpe-attribution'],
    queryFn: () => fetchApi('/shadow/sharpe-attribution'),
  })

  const calibQuery = useQuery({
    queryKey: ['console-know-calibration'],
    queryFn: () => fetchApi('/console/know/calibration'),
  })

  return (
    <div>
      <BackToOverview />
      <div data-testid="know-attribution">
        <AttributionSection
          statsData={statsQuery.data}
          sharpeData={sharpeQuery.data}
        />
        <CalibrationSection calibData={calibQuery.data} />
      </div>
    </div>
  )
}
