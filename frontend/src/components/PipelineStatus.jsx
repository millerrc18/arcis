/**
 * Training Pipeline Status card for Training page.
 * Shows active model, quality, format compliance, leakage, quadrants.
 *
 * Called by: pages/Training.jsx
 */
import StatusBadge from './StatusBadge'

export default function PipelineStatus({ status }) {
  if (!status) return null
  if (!status.format_compliance && !status.quality && !status.quadrant_distribution) return null

  return (
    <div className="arcis-card">
      <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>Pipeline Status</h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        {/* Active model */}
        <div>
          <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>Active Model</div>
          <div className="flex items-center gap-2 mt-1">
            <span className="font-medium" style={{ color: 'var(--arcis-text-primary)' }}>{status.model_version || 'base'}</span>
            <StatusBadge text={status.model_status || 'active'} variant={status.model_status === 'active' ? 'success' : 'neutral'} />
          </div>
          {status.holdout_score != null && (
            <div className="text-xs financial-data mt-0.5" style={{ color: 'var(--arcis-text-secondary)' }}>Holdout: {status.holdout_score.toFixed(3)}</div>
          )}
        </div>
        {/* Quality */}
        {status.quality && (
          <div>
            <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>Avg Process Score</div>
            <div className="financial-data text-lg mt-1" style={{ color: 'var(--arcis-text-primary)' }}>
              {status.quality.avg_process_score != null ? status.quality.avg_process_score.toFixed(2) : '--'}
            </div>
          </div>
        )}
        {/* Format compliance */}
        {status.format_compliance && (
          <div>
            <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>Format Compliance</div>
            <div className="text-xs mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
              XML: {status.format_compliance.xml ?? 0} | Plain: {status.format_compliance.plain_text ?? 0}
            </div>
          </div>
        )}
        {/* Leakage */}
        {status.quality && (
          <div>
            <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>Leakage Test</div>
            <div className="flex items-center gap-2 mt-1">
              <span className="financial-data" style={{ color: 'var(--arcis-text-primary)' }}>
                {status.quality.leakage_accuracy != null ? status.quality.leakage_accuracy.toFixed(3) : '--'}
              </span>
              {status.quality.leakage_accuracy != null && (
                <StatusBadge
                  text={status.quality.leakage_accuracy < 0.55 ? 'OK' : status.quality.leakage_accuracy < 0.6 ? 'Marginal' : 'Leaking'}
                  variant={status.quality.leakage_accuracy < 0.55 ? 'success' : status.quality.leakage_accuracy < 0.6 ? 'warning' : 'danger'}
                />
              )}
            </div>
          </div>
        )}
      </div>
      {/* Quadrant distribution */}
      {status.quadrant_distribution && (
        <div className="mt-4 pt-3" style={{ borderTop: '1px solid var(--arcis-border)' }}>
          <div className="text-xs mb-2" style={{ color: 'var(--arcis-text-muted)' }}>Quadrant Distribution</div>
          <div className="grid grid-cols-2 gap-2 max-w-xs text-xs">
            {[
              ['Good Process + Good Outcome', status.quadrant_distribution.good_good, 'var(--arcis-success)'],
              ['Good Process + Bad Outcome', status.quadrant_distribution.good_bad, 'var(--arcis-accent)'],
              ['Bad Process + Good Outcome', status.quadrant_distribution.bad_good, 'var(--arcis-warning)'],
              ['Bad Process + Bad Outcome', status.quadrant_distribution.bad_bad, 'var(--arcis-danger)'],
            ].map(([label, count, color]) => (
              <div key={label} className="flex items-center justify-between px-2 py-1.5 rounded" style={{ background: 'var(--arcis-bg-primary)' }}>
                <span style={{ color: 'var(--arcis-text-secondary)' }}>{label.split('+')[0].trim()}<br />{label.split('+')[1]?.trim()}</span>
                <span className="financial-data text-lg" style={{ color }}>{count ?? 0}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
