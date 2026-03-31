import { useQuery } from '@tanstack/react-query'
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from 'recharts'
import { api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import MetricCard from '../components/MetricCard'

const DIMENSION_LABELS = {
  performance: 'Performance',
  model_quality: 'Model Quality',
  data_asset: 'Data Asset',
  flywheel_velocity: 'Flywheel Velocity',
  defensibility: 'Defensibility',
}

function overallColor(score) {
  if (score > 70) return 'var(--arcis-accent)'
  if (score > 50) return 'var(--arcis-warning)'
  return 'var(--arcis-danger)'
}

export default function Health() {
  const { data, isLoading } = useQuery({
    queryKey: ['hshs-live'],
    queryFn: api.getHSHS,
    refetchInterval: 60000,
  })

  if (isLoading) return <LoadingSpinner />

  const overall = data?.hshs ?? 0
  const dimensions = data?.dimensions || {}
  const weights = data?.weights || {}
  const phase = data?.phase || 'early'
  const hasData = Object.keys(dimensions).length > 0

  const radarData = Object.entries(DIMENSION_LABELS).map(([key, label]) => ({
    dimension: label,
    score: dimensions[key] ?? 0,
    fullMark: 100,
  }))

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)' }}>System Health</h2>
          <p className="text-sm mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
            Live Arcis System Health Score from the latest cloud data.
          </p>
        </div>
        <div className="px-3 py-1 rounded-full text-xs uppercase tracking-wide" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', color: 'var(--arcis-text-secondary)' }}>
          Phase: {phase}
        </div>
      </div>

      {!hasData ? (
        <div className="rounded-lg p-12 text-center" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
          <div className="text-sm" style={{ color: 'var(--arcis-text-secondary)' }}>Collecting data...</div>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="rounded-lg p-6 lg:col-span-1" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
              <div className="text-xs uppercase tracking-wide mb-2" style={{ color: 'var(--arcis-text-secondary)' }}>
                Composite Score
              </div>
              <div className="text-6xl font-semibold" style={{ fontFamily: 'var(--font-mono)', color: overallColor(overall) }}>
                {overall.toFixed(1)}
              </div>
              <div className="text-sm mt-3" style={{ color: 'var(--arcis-text-secondary)' }}>Out of 100</div>
              <div className="mt-4 text-xs uppercase tracking-wide" style={{ color: 'var(--arcis-text-muted)' }}>
                Phase Weights
              </div>
              <div className="mt-3 space-y-2">
                {Object.entries(DIMENSION_LABELS).map(([key, label]) => (
                  <div key={key} className="flex items-center justify-between text-sm">
                    <span style={{ color: 'var(--arcis-text-secondary)' }}>{label}</span>
                    <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-primary)' }}>
                      {weights[key] != null ? `${(weights[key] * 100).toFixed(0)}%` : '--'}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-lg p-4 lg:col-span-2" style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)' }}>
              <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>
                HSHS Radar
              </h3>
              <ResponsiveContainer width="100%" height={320}>
                <RadarChart data={radarData} cx="50%" cy="50%" outerRadius="72%">
                  <PolarGrid stroke="var(--arcis-border)" />
                  <PolarAngleAxis dataKey="dimension" tick={{ fontSize: 11, fill: 'var(--arcis-text-secondary)' }} />
                  <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} />
                  <Radar dataKey="score" stroke="var(--arcis-accent)" fill="var(--arcis-accent)" fillOpacity={0.2} />
                  <Tooltip
                    contentStyle={{
                      background: 'var(--arcis-bg-surface)',
                      border: '1px solid var(--arcis-border)',
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {Object.entries(DIMENSION_LABELS).map(([key, label]) => (
              <MetricCard key={key} label={label} value={(dimensions[key] ?? 0).toFixed(0)} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
