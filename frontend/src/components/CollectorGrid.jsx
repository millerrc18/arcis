/**
 * Data Collectors grid for Training page.
 * Shows 12 collector cards with freshness indicators.
 *
 * Called by: pages/Training.jsx
 */

import { formatRelativeTime } from '../utils/formatTimestamp'

const COLLECTOR_NAMES = {
  options_chains: 'Options Chains',
  options_metrics: 'Options Metrics',
  vix_term_structure: 'VIX Term Structure',
  cboe_ratios: 'CBOE Put/Call Ratios',
  macro_snapshots: 'FRED Macro Data',
  google_trends: 'Google Trends',
  earnings_calendar: 'Earnings Calendar',
  edgar_filings: 'SEC EDGAR Filings',
  insider_transactions: 'Insider Transactions',
  fed_communications: 'Fed Communications',
  analyst_estimates: 'Analyst Estimates',
  short_interest: 'Short Interest',
}

function relativeDate(dateStr) {
  if (!dateStr) return 'Never'
  return formatRelativeTime(dateStr)
}

function freshnessColor(dateStr) {
  if (!dateStr) return 'var(--arcis-danger)'
  const days = (Date.now() - new Date(dateStr).getTime()) / 86400000
  if (days <= 1.5) return 'var(--arcis-success)'
  if (days <= 7) return 'var(--arcis-warning)'
  return 'var(--arcis-danger)'
}

function freshnessLabel(dateStr) {
  if (!dateStr) return 'No data'
  const days = (Date.now() - new Date(dateStr).getTime()) / 86400000
  if (days <= 1.5) return 'Fresh'
  if (days <= 7) return 'Stale'
  return 'Outdated'
}

export default function CollectorGrid({ stats }) {
  if (!stats) return null
  return (
    <div>
      <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>Data Collectors</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {Object.entries(COLLECTOR_NAMES).map(([key, name]) => {
          const s = stats[key]
          const records = s?.total_records ?? 0
          const latest = s?.latest_collection
          const coverage = s?.coverage_count
          return (
            <div key={key} className="arcis-card" style={{ padding: '12px' }}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-medium" style={{ color: 'var(--arcis-text-primary)' }}>{name}</span>
                <span className="flex items-center gap-1.5">
                  <span className="inline-block w-2 h-2 rounded-full" style={{ background: freshnessColor(latest) }} />
                  <span className="text-xs" style={{ color: freshnessColor(latest) }}>{freshnessLabel(latest)}</span>
                </span>
              </div>
              {records > 0 ? (
                <>
                  <div className="financial-data text-lg" style={{ color: 'var(--arcis-text-primary)' }}>{records.toLocaleString()}</div>
                  <div className="flex items-center gap-2 text-xs mt-1" style={{ color: 'var(--arcis-text-muted)' }}>
                    <span>{relativeDate(latest)}</span>
                    {coverage != null && <span>{coverage} tickers</span>}
                  </div>
                </>
              ) : (
                <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-muted)' }}>No data collected yet</div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
