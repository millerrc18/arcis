import { useQuery } from '@tanstack/react-query'
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  LineChart,
  Line,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import MetricCard from '../components/MetricCard'
import { TrendingUp, TrendingDown, Minus, AlertTriangle } from 'lucide-react'

const DIMENSION_LABELS = {
  performance: 'Performance',
  model_quality: 'Model Quality',
  data_asset: 'Data Asset',
  flywheel_velocity: 'Flywheel Velocity',
  defensibility: 'Defensibility',
}

const COMPONENT_LABELS = {
  gate_velocity: 'Gate Velocity',
  system_health: 'System Health',
  data_asset_value: 'Data Asset',
  model_quality: 'Model Quality',
  research_velocity: 'Research Velocity',
  reliability: 'Reliability',
}

function scoreColor(score) {
  if (score >= 70) return 'var(--teal-400)'
  if (score >= 40) return 'var(--amber-400)'
  return 'var(--danger)'
}

function overallColor(score) {
  if (score > 70) return 'var(--arcis-accent)'
  if (score > 50) return 'var(--arcis-warning)'
  return 'var(--arcis-danger)'
}

export default function Health() {
  const { data: hshsData, isLoading: hshsLoading } = useQuery({
    queryKey: ['hshs-live'],
    queryFn: api.getHSHS,
    refetchInterval: 60000,
  })
  const { data: buildData, isLoading: buildLoading } = useQuery({
    queryKey: ['build-score'],
    queryFn: api.getBuildScore,
    refetchInterval: 120000,
  })

  if (hshsLoading && buildLoading) return <LoadingSpinner />

  // HSHS data
  const hshsOverall = hshsData?.hshs ?? 0
  const dimensions = hshsData?.dimensions || {}
  const weights = hshsData?.weights || {}
  const phase = hshsData?.phase || 'early'
  const hasHshs = Object.keys(dimensions).length > 0

  // Build Score data
  const buildScore = buildData?.build_score ?? 0
  const buildDelta = buildData?.delta_7d
  const buildComponents = buildData?.components || {}
  const buildDecay = buildData?.decay_today
  const buildHistory = (buildData?.history_7d || []).map((v, i) => ({ day: `D${i + 1}`, score: v }))
  const dataDetail = buildData?.data_asset_detail || {}
  const phaseProgress = buildData?.phase_progress || {}
  const hasBuild = buildScore > 0 || Object.keys(buildComponents).length > 0

  const radarData = Object.entries(DIMENSION_LABELS).map(([key, label]) => ({
    dimension: label,
    score: dimensions[key] ?? 0,
    fullMark: 100,
  }))

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-xl font-medium" style={{ color: 'var(--slate-100)' }}>System Health</h2>
          <p className="text-sm mt-1" style={{ color: 'var(--slate-400)' }}>
            Build Score + HSHS composite from live cloud data.
          </p>
        </div>
        <div className="flex gap-2">
          <div className="px-3 py-1 rounded-full text-xs uppercase tracking-wide" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)', color: 'var(--slate-300)' }}>
            Phase: {phase}
          </div>
          {phaseProgress.pct_complete != null && (
            <div className="px-3 py-1 rounded-full text-xs" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)', color: 'var(--slate-300)' }}>
              Gate: {phaseProgress.trades_closed}/{phaseProgress.trades_required}
            </div>
          )}
        </div>
      </div>

      {/* Build Score hero section */}
      {hasBuild && (
        <div className="rounded-lg p-6" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
          <div className="flex flex-col lg:flex-row gap-6">
            {/* Score display */}
            <div className="flex flex-col items-center lg:items-start gap-1 min-w-[160px]">
              <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--slate-400)' }}>Build Score</div>
              <div className="text-6xl font-semibold" style={{ fontFamily: 'var(--font-mono)', color: scoreColor(buildScore) }}>
                {buildScore.toFixed(1)}
              </div>
              <div className="flex items-center gap-2 mt-1">
                {buildDelta != null && (
                  <span className="flex items-center gap-1 text-sm" style={{ color: buildDelta > 0 ? 'var(--success)' : buildDelta < 0 ? 'var(--danger)' : 'var(--slate-400)' }}>
                    {buildDelta > 0 ? <TrendingUp size={14} /> : buildDelta < 0 ? <TrendingDown size={14} /> : <Minus size={14} />}
                    {buildDelta > 0 ? '+' : ''}{buildDelta.toFixed(1)} 7d
                  </span>
                )}
                {buildDecay && (
                  <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full" style={{ background: 'rgba(239,68,68,0.15)', color: '#fca5a5' }}>
                    <AlertTriangle size={10} /> Decay
                  </span>
                )}
              </div>
            </div>

            {/* Component breakdown */}
            <div className="flex-1 grid grid-cols-2 md:grid-cols-3 gap-x-5 gap-y-3">
              {Object.entries(COMPONENT_LABELS).map(([key, label]) => {
                const val = buildComponents[key] ?? 0
                return (
                  <div key={key}>
                    <div className="flex justify-between text-xs mb-1">
                      <span style={{ color: 'var(--slate-400)' }}>{label}</span>
                      <span style={{ fontFamily: 'var(--font-mono)', color: scoreColor(val) }}>{val.toFixed(0)}</span>
                    </div>
                    <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--slate-600)' }}>
                      <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, val)}%`, background: scoreColor(val) }} />
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Sparkline */}
            {buildHistory.length > 1 && (
              <div className="flex flex-col items-center gap-2 min-w-[140px]">
                <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--slate-400)' }}>7-Day Trend</div>
                <ResponsiveContainer width={140} height={60}>
                  <LineChart data={buildHistory}>
                    <Line type="monotone" dataKey="score" stroke="var(--teal-400)" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          {/* Data asset detail */}
          {(dataDetail.quality || dataDetail.diversity || dataDetail.freshness) && (
            <div className="mt-4 pt-4 grid grid-cols-3 gap-4" style={{ borderTop: '1px solid var(--slate-600)' }}>
              <div>
                <div className="text-xs" style={{ color: 'var(--slate-400)' }}>Data Quality</div>
                <div className="text-lg font-medium" style={{ fontFamily: 'var(--font-mono)', color: scoreColor(dataDetail.quality || 0) }}>
                  {(dataDetail.quality || 0).toFixed(0)}
                </div>
              </div>
              <div>
                <div className="text-xs" style={{ color: 'var(--slate-400)' }}>Data Diversity</div>
                <div className="text-lg font-medium" style={{ fontFamily: 'var(--font-mono)', color: scoreColor(dataDetail.diversity || 0) }}>
                  {(dataDetail.diversity || 0).toFixed(0)}
                </div>
              </div>
              <div>
                <div className="text-xs" style={{ color: 'var(--slate-400)' }}>Data Freshness</div>
                <div className="text-lg font-medium" style={{ fontFamily: 'var(--font-mono)', color: scoreColor(dataDetail.freshness || 0) }}>
                  {(dataDetail.freshness || 0).toFixed(0)}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* HSHS section */}
      {!hasHshs ? (
        <div className="rounded-lg p-12 text-center" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
          <div className="text-sm" style={{ color: 'var(--slate-400)' }}>Collecting HSHS data...</div>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="rounded-lg p-6 lg:col-span-1" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
              <div className="text-xs uppercase tracking-wide mb-2" style={{ color: 'var(--slate-400)' }}>
                HSHS Composite
              </div>
              <div className="text-6xl font-semibold" style={{ fontFamily: 'var(--font-mono)', color: overallColor(hshsOverall) }}>
                {hshsOverall.toFixed(1)}
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
