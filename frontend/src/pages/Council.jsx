import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { api } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import StatusBadge from '../components/StatusBadge'

const AGENT_META = {
  tactical_operator: { emoji: '⚡', label: 'Tactical' },
  strategic_architect: { emoji: '🏗️', label: 'Strategic' },
  red_team: { emoji: '🔴', label: 'Red Team' },
  innovation_engine: { emoji: '💡', label: 'Innovation' },
  macro_navigator: { emoji: '🌍', label: 'Macro' },
}

const DIRECTION_VARIANTS = {
  bullish: 'success',
  neutral: 'neutral',
  bearish: 'danger',
}

const DIRECTION_COLORS = {
  bullish: '#34d399',
  neutral: '#94a3b8',
  bearish: '#ef4444',
}

function normalizeConfidence(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return null
  return num > 1 ? num / 10 : num
}

function inferDirection(agent) {
  if (agent?.direction) return agent.direction
  if (agent?.vote === 'increase_exposure') return 'bullish'
  if (agent?.vote === 'reduce_exposure') return 'bearish'
  return 'neutral'
}

function normalizeAgents(rawAgents) {
  return (rawAgents || []).map((agent, index) => {
    const agentKey = agent.agent_name || agent.agent || `agent_${index}`
    const meta = AGENT_META[agentKey] || { emoji: '•', label: agentKey.replace(/_/g, ' ') }
    const confidence = normalizeConfidence(agent.confidence_float ?? agent.confidence)
    return {
      id: agent.vote_id || agent.agent || agent.agent_name || index,
      agentKey,
      displayName: `${meta.emoji} ${meta.label}`,
      direction: inferDirection(agent),
      confidence,
      reasoning: agent.key_reasoning || agent.recommendation || '',
      risk: agent.key_risk || (Array.isArray(agent.risk_flags) ? agent.risk_flags[0] : ''),
      recommendation: agent.recommendation || '',
    }
  })
}

function buildConsensusLabel(agents) {
  const counts = { bullish: 0, neutral: 0, bearish: 0 }
  agents.forEach((agent) => {
    counts[agent.direction] = (counts[agent.direction] || 0) + 1
  })
  const ordered = Object.values(counts).sort((a, b) => b - a)
  const lead = ordered[0] || 0
  const next = ordered[1] || 0
  if (lead === 5) return '5-0 Unanimous'
  if (lead === 4) return '4-1 Strong'
  if (lead === 3) return '3-2 Majority'
  return 'No Consensus'
}

function formatAdjustment(value) {
  if (value == null) return '--'
  if (typeof value === 'number') return value.toFixed(3)
  return String(value)
}

function DirectionBadge({ direction }) {
  const label = (direction || 'neutral').toUpperCase()
  return <StatusBadge text={label} variant={DIRECTION_VARIANTS[direction] || 'neutral'} />
}

function AgentCard({ agent }) {
  return (
    <div className="rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
      <div className="flex items-center justify-between gap-3">
        <div className="font-medium text-sm" style={{ color: 'var(--slate-100)' }}>{agent.displayName}</div>
        <DirectionBadge direction={agent.direction} />
      </div>
      <div className="text-xs mt-3" style={{ color: 'var(--slate-400)' }}>
        Confidence: <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--slate-100)' }}>
          {agent.confidence != null ? `${(agent.confidence * 100).toFixed(0)}%` : '--'}
        </span>
      </div>
      {agent.reasoning && (
        <p className="text-sm mt-3 leading-relaxed" style={{ color: 'var(--slate-300)' }}>
          {agent.reasoning}
        </p>
      )}
      {agent.risk && (
        <div className="mt-3 text-xs" style={{ color: '#fca5a5' }}>
          Risk: {agent.risk}
        </div>
      )}
    </div>
  )
}

function DirectionDistribution({ agents }) {
  if (!agents.length) return null
  const counts = { bullish: 0, neutral: 0, bearish: 0 }
  agents.forEach((agent) => {
    counts[agent.direction] = (counts[agent.direction] || 0) + 1
  })
  const data = Object.entries(counts).map(([direction, count]) => ({
    direction,
    label: direction[0].toUpperCase() + direction.slice(1),
    count,
  }))

  return (
    <div className="rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
      <h4 className="text-xs uppercase tracking-wide mb-3" style={{ color: 'var(--slate-400)' }}>
        Direction Split
      </h4>
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={data}>
          <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'var(--slate-400)' }} />
          <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--slate-400)' }} />
          <Tooltip
            contentStyle={{
              background: 'var(--slate-700)',
              border: '1px solid var(--slate-600)',
              borderRadius: 8,
              fontSize: 12,
            }}
          />
          <Bar dataKey="count" radius={[4, 4, 0, 0]}>
            {data.map((entry) => (
              <Cell key={entry.direction} fill={DIRECTION_COLORS[entry.direction] || 'var(--slate-400)'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function AdjustmentTable({ adjustments }) {
  const rows = Object.entries(adjustments || {})
  if (!rows.length) return null

  return (
    <div className="rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
      <h4 className="text-xs uppercase tracking-wide mb-3" style={{ color: 'var(--slate-400)' }}>
        Parameter Adjustments
      </h4>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ color: 'var(--slate-400)' }}>
              <th className="text-left py-2 font-medium">Parameter</th>
              <th className="text-left py-2 font-medium">Previous</th>
              <th className="text-left py-2 font-medium">Recommended</th>
              <th className="text-left py-2 font-medium">Applied</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([name, values]) => (
              <tr key={name} style={{ borderTop: '1px solid var(--slate-600)' }}>
                <td className="py-2" style={{ color: 'var(--slate-100)' }}>{name}</td>
                <td className="py-2" style={{ fontFamily: 'var(--font-mono)', color: 'var(--slate-300)' }}>{formatAdjustment(values.previous)}</td>
                <td className="py-2" style={{ fontFamily: 'var(--font-mono)', color: 'var(--slate-300)' }}>{formatAdjustment(values.recommended)}</td>
                <td className="py-2" style={{ fontFamily: 'var(--font-mono)', color: 'var(--slate-100)' }}>{formatAdjustment(values.applied)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ExpandableSessionRow({ session, isLatest }) {
  const [expanded, setExpanded] = useState(false)
  const { data, isLoading } = useQuery({
    queryKey: ['council-session', session.session_id],
    queryFn: () => api.getCouncilSession(session.session_id),
    enabled: expanded && Boolean(session.session_id),
  })

  const detailSession = data?.session || session
  const agents = normalizeAgents(detailSession?.result_json?.agent_assessments || data?.votes || [])
  const adjustments = detailSession?.result_json?.parameter_adjustments || {}
  const consensusLabel = buildConsensusLabel(agents)
  const timestamp = session.created_at ? new Date(session.created_at).toLocaleString() : '--'

  return (
    <div className="rounded-lg" style={{ border: '1px solid var(--slate-600)' }}>
      <button
        onClick={() => setExpanded((value) => !value)}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left"
        style={{ background: isLatest ? 'rgba(20, 184, 166, 0.08)' : 'transparent' }}
      >
        <div className="flex items-center gap-3">
          {expanded ? <ChevronDown size={14} style={{ color: 'var(--slate-400)' }} /> : <ChevronRight size={14} style={{ color: 'var(--slate-400)' }} />}
          <div>
            <div className="text-sm font-medium" style={{ color: 'var(--slate-100)' }}>
              {session.session_type || 'session'}
            </div>
            <div className="text-xs mt-1" style={{ color: 'var(--slate-400)' }}>{timestamp}</div>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-wrap justify-end">
          <DirectionBadge direction={session.consensus || detailSession?.result_json?.votes?.direction} />
          <span className="text-xs" style={{ color: 'var(--slate-400)' }}>{consensusLabel}</span>
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-4">
          {isLoading ? (
            <LoadingSpinner />
          ) : (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="rounded-lg p-3" style={{ background: 'var(--slate-800)' }}>
                  <div className="text-xs" style={{ color: 'var(--slate-400)' }}>Consensus</div>
                  <div className="text-sm mt-1" style={{ color: 'var(--slate-100)' }}>{consensusLabel}</div>
                </div>
                <div className="rounded-lg p-3" style={{ background: 'var(--slate-800)' }}>
                  <div className="text-xs" style={{ color: 'var(--slate-400)' }}>Rounds</div>
                  <div className="text-sm mt-1" style={{ color: 'var(--slate-100)' }}>{detailSession.rounds_completed ?? detailSession.result_json?.session_meta?.rounds_completed ?? '--'}</div>
                </div>
                <div className="rounded-lg p-3" style={{ background: 'var(--slate-800)' }}>
                  <div className="text-xs" style={{ color: 'var(--slate-400)' }}>Confidence</div>
                  <div className="text-sm mt-1" style={{ color: 'var(--slate-100)' }}>
                    {detailSession.result_json?.votes?.confidence_avg != null
                      ? `${(detailSession.result_json.votes.confidence_avg * 100).toFixed(0)}%`
                      : '--'}
                  </div>
                </div>
                <div className="rounded-lg p-3" style={{ background: 'var(--slate-800)' }}>
                  <div className="text-xs" style={{ color: 'var(--slate-400)' }}>Cost</div>
                  <div className="text-sm mt-1" style={{ color: 'var(--slate-100)' }}>
                    {detailSession.total_cost != null ? `$${Number(detailSession.total_cost).toFixed(4)}` : '--'}
                  </div>
                </div>
              </div>

              <DirectionDistribution agents={agents} />
              <AdjustmentTable adjustments={adjustments} />

              {agents.length > 0 && (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                  {agents.map((agent) => (
                    <AgentCard key={agent.id} agent={agent} />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

export default function Council() {
  const queryClient = useQueryClient()
  const [strategicQuestion, setStrategicQuestion] = useState('')
  const { data: latest, isLoading } = useQuery({
    queryKey: ['council-latest'],
    queryFn: api.getCouncilLatest,
    refetchInterval: 60000,
  })
  const { data: history } = useQuery({
    queryKey: ['council-history'],
    queryFn: () => api.getCouncilHistory(30),
    refetchInterval: 60000,
  })

  const runCouncil = useMutation({
    mutationFn: api.triggerCouncil,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['council-latest'] })
      queryClient.invalidateQueries({ queryKey: ['council-history'] })
    },
  })

  const askStrategic = useMutation({
    mutationFn: api.askCouncilStrategic,
  })

  const session = latest?.session || latest || {}
  const latestAgents = useMemo(
    () => normalizeAgents(session?.result_json?.agent_assessments || session?.votes || []),
    [session],
  )
  const consensusLabel = buildConsensusLabel(latestAgents)
  const adjustments = session?.result_json?.parameter_adjustments || {}
  const sessions = history?.sessions || history || []

  if (isLoading) return <LoadingSpinner />

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-xl font-medium" style={{ color: 'var(--slate-100)' }}>Advisory Council</h2>
          <p className="text-sm mt-1" style={{ color: 'var(--slate-400)' }}>
            Five-agent vote-first council with conditional Round 2 and tracked parameter changes.
          </p>
        </div>
        <button
          onClick={() => runCouncil.mutate()}
          disabled={runCouncil.isPending}
          className="px-4 py-2 rounded-lg font-medium text-sm text-white disabled:opacity-50"
          style={{ background: 'var(--teal-500)' }}
        >
          {runCouncil.isPending ? 'Running...' : 'Run Council Now'}
        </button>
      </div>

      <div className="rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="text-sm font-medium" style={{ color: 'var(--slate-100)' }}>Ask A Strategic Question</div>
          <div className="text-xs" style={{ color: 'var(--slate-400)' }}>
            Founder-style question routed to the council strategic endpoint.
          </div>
        </div>
        <div className="mt-3 flex flex-col md:flex-row gap-3">
          <input
            type="text"
            value={strategicQuestion}
            onChange={(event) => setStrategicQuestion(event.target.value)}
            placeholder="What should the council evaluate next?"
            className="flex-1 px-3 py-2 rounded-lg text-sm"
            style={{ background: 'var(--slate-800)', border: '1px solid var(--slate-600)', color: 'var(--slate-100)' }}
          />
          <button
            onClick={() => askStrategic.mutate(strategicQuestion)}
            disabled={askStrategic.isPending || !strategicQuestion.trim()}
            className="px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
            style={{ background: 'var(--slate-800)', border: '1px solid var(--slate-600)', color: 'var(--slate-100)' }}
          >
            {askStrategic.isPending ? 'Sending...' : 'Ask Council'}
          </button>
        </div>
        {askStrategic.data && (
          <div className="mt-3 text-sm rounded-lg px-3 py-2" style={{ background: 'rgba(148, 163, 184, 0.12)', color: 'var(--slate-300)' }}>
            {askStrategic.data.message || askStrategic.data.error || 'Request sent.'}
          </div>
        )}
      </div>

      {latestAgents.length > 0 ? (
        <>
          <div className="rounded-lg p-6" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
            <div className="flex items-center justify-between gap-4 flex-wrap">
              <div>
                <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--slate-400)' }}>Latest Consensus</div>
                <div className="mt-2 flex items-center gap-3">
                  <DirectionBadge direction={session.consensus || session.result_json?.votes?.direction} />
                  <span className="text-lg font-medium" style={{ color: 'var(--slate-100)' }}>{consensusLabel}</span>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <div className="text-xs" style={{ color: 'var(--slate-400)' }}>Confidence</div>
                  <div className="text-sm mt-1" style={{ fontFamily: 'var(--font-mono)', color: 'var(--slate-100)' }}>
                    {session.result_json?.votes?.confidence_avg != null
                      ? `${(session.result_json.votes.confidence_avg * 100).toFixed(0)}%`
                      : '--'}
                  </div>
                </div>
                <div>
                  <div className="text-xs" style={{ color: 'var(--slate-400)' }}>Rounds</div>
                  <div className="text-sm mt-1" style={{ fontFamily: 'var(--font-mono)', color: 'var(--slate-100)' }}>
                    {session.rounds_completed ?? session.result_json?.session_meta?.rounds_completed ?? '--'}
                  </div>
                </div>
              </div>
            </div>

            {session.trigger_reason && (
              <p className="text-sm mt-4" style={{ color: 'var(--slate-300)' }}>{session.trigger_reason}</p>
            )}
          </div>

          <DirectionDistribution agents={latestAgents} />
          <AdjustmentTable adjustments={adjustments} />

          <div>
            <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--slate-400)' }}>
              Agent Assessments ({latestAgents.length})
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {latestAgents.map((agent) => (
                <AgentCard key={agent.id} agent={agent} />
              ))}
            </div>
          </div>
        </>
      ) : (
        <div className="rounded-lg p-12 text-center" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
          <div className="text-sm" style={{ color: 'var(--slate-400)' }}>
            No council session yet. Run the council to populate the dashboard.
          </div>
        </div>
      )}

      <div className="rounded-lg p-4" style={{ background: 'var(--slate-700)', border: '1px solid var(--slate-600)' }}>
        <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--slate-400)' }}>
          Session History
        </h3>
        {sessions.length > 0 ? (
          <div className="space-y-3">
            {sessions.map((entry, index) => (
              <ExpandableSessionRow key={entry.session_id || index} session={entry} isLatest={index === 0} />
            ))}
          </div>
        ) : (
          <div className="text-center py-6 text-sm" style={{ color: 'var(--slate-400)' }}>
            No historical sessions yet.
          </div>
        )}
      </div>
    </div>
  )
}
