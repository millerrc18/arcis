import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import StatusBadge from '../components/StatusBadge'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

export default function Attribution() {
  const { data, isLoading } = useQuery({
    queryKey: ['attribution-stats'],
    queryFn: api.getAttributionStats,
    refetchInterval: 120000,
  })

  if (isLoading) return <LoadingSpinner />

  const stats = data || {}
  const total = stats.total_pairs || 0
  const ranker = stats.ranker_only || {}
  const llm = stats.llm_portfolio || {}
  const byAction = stats.by_action || {}
  const byPair = stats.by_pair_type || {}
  const power = stats.statistical_power || 'insufficient'

  const comparisonData = [
    { name: 'Ranker Only', winRate: (ranker.win_rate || 0) * 100, fill: 'var(--arcis-text-secondary)' },
    { name: 'LLM Portfolio', winRate: (llm.win_rate || 0) * 100, fill: 'var(--arcis-accent)' },
  ]

  const pairData = Object.entries(byPair).map(([type, count]) => ({
    name: type.replace(/_/g, ' '),
    count,
  }))

  const powerColor = power === 'adequate' ? 'var(--arcis-success)' : power === 'low' ? 'var(--amber-400)' : 'var(--arcis-danger)'
  const powerLabel = power === 'adequate' ? 'Adequate (200+)' : power === 'low' ? 'Low (50-200)' : `Insufficient (${total}/200)`

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text)' }}>Alpha Attribution</h2>
        <StatusBadge
          text={powerLabel}
          variant={power === 'adequate' ? 'success' : power === 'low' ? 'warning' : 'danger'}
        />
      </div>

      <div className="arcis-card" style={{ padding: '16px' }}>
        <h3 className="text-sm uppercase tracking-wide mb-2" style={{ color: 'var(--arcis-text-secondary)' }}>
          Does the LLM add alpha?
        </h3>
        <p className="text-sm" style={{ color: 'var(--arcis-text-muted)' }}>
          {total < 50
            ? `Only ${total} paired trades logged. Need 200+ for statistical significance (McNemar's test at 80% power). Keep trading.`
            : total < 200
              ? `${total} paired trades — gaining statistical power. Need 200+ for definitive answer.`
              : `${total} paired trades — sufficient for alpha attribution analysis.`
          }
        </p>
      </div>

      {/* Key metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="arcis-card" style={{ padding: '12px' }}>
          <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Total Pairs</div>
          <div className="text-2xl font-bold" style={{ fontFamily: 'var(--font-mono)' }}>{total}</div>
        </div>
        <div className="arcis-card" style={{ padding: '12px' }}>
          <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Ranker Win Rate</div>
          <div className="text-2xl font-bold" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-text-secondary)' }}>
            {ranker.win_rate != null ? `${(ranker.win_rate * 100).toFixed(1)}%` : '--'}
          </div>
          <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>{ranker.resolved || 0} resolved</div>
        </div>
        <div className="arcis-card" style={{ padding: '12px' }}>
          <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>LLM Win Rate</div>
          <div className="text-2xl font-bold" style={{ fontFamily: 'var(--font-mono)', color: 'var(--arcis-accent)' }}>
            {llm.win_rate != null ? `${(llm.win_rate * 100).toFixed(1)}%` : '--'}
          </div>
          <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>{llm.resolved || 0} resolved</div>
        </div>
        <div className="arcis-card" style={{ padding: '12px' }}>
          <div className="text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>Statistical Power</div>
          <div className="text-lg font-bold" style={{ fontFamily: 'var(--font-mono)', color: powerColor }}>
            {power === 'adequate' ? 'Adequate' : power === 'low' ? 'Low' : 'Insufficient'}
          </div>
          <div className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>Target: 200 pairs</div>
        </div>
      </div>

      {/* Win rate comparison chart */}
      {(ranker.resolved > 0 || llm.resolved > 0) && (
        <div className="arcis-card">
          <h3 className="text-sm uppercase tracking-wide mb-4" style={{ color: 'var(--arcis-text-secondary)' }}>Win Rate Comparison</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={comparisonData} layout="vertical">
              <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11, fill: 'var(--arcis-text-muted)' }} />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 12, fill: 'var(--arcis-text-secondary)' }} width={100} />
              <Tooltip contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', borderRadius: 8, fontSize: 12 }} />
              <Bar dataKey="winRate" name="Win Rate %">
                {comparisonData.map((entry, i) => (
                  <Cell key={i} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Category breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="arcis-card">
          <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>By LLM Action</h3>
          <div className="space-y-2">
            {Object.entries(byAction).map(([action, count]) => (
              <div key={action} className="flex justify-between text-sm">
                <span style={{ color: 'var(--arcis-text-secondary)' }}>{action.replace(/_/g, ' ')}</span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>{count}</span>
              </div>
            ))}
            {Object.keys(byAction).length === 0 && (
              <p className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>No data yet</p>
            )}
          </div>
        </div>

        <div className="arcis-card">
          <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)' }}>By Pair Type</h3>
          {pairData.length > 0 ? (
            <ResponsiveContainer width="100%" height={150}>
              <BarChart data={pairData}>
                <XAxis dataKey="name" tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} />
                <YAxis tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} />
                <Tooltip contentStyle={{ background: 'var(--arcis-bg-elevated)', border: '1px solid var(--arcis-border)', borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="count" fill="var(--arcis-accent)" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-xs" style={{ color: 'var(--arcis-text-muted)' }}>No data yet</p>
          )}
        </div>
      </div>

      {/* Methodology note */}
      <div className="arcis-card" style={{ padding: '16px' }}>
        <h3 className="text-sm uppercase tracking-wide mb-2" style={{ color: 'var(--arcis-text-secondary)' }}>Methodology</h3>
        <div className="text-xs space-y-1" style={{ color: 'var(--arcis-text-muted)' }}>
          <p>Every packet-worthy candidate is logged BEFORE LLM processing. The ranker-only outcome simulates what would happen with mechanical brackets (2% target, 3% stop, 7-day timeout).</p>
          <p>Three pair types: <strong>both_taken</strong> (LLM agreed), <strong>llm_rejected</strong> (LLM passed), <strong>llm_upgraded</strong> (LLM added conviction). The most informative category is llm_rejected — trades the ranker would take but the LLM skipped.</p>
          <p>Statistical test: McNemar's test requires 200+ paired trades for 10% alpha detection at 80% power. At 50 trades, power is only 28%.</p>
        </div>
      </div>
    </div>
  )
}
