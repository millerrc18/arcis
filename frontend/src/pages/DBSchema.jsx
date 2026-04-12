import { useCallback, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import {
  ReactFlow,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

const CLUSTERS = {
  trading: { color: '#22C55E', label: 'Trading', tables: [
    'shadow_trades', 'recommendations', 'trade_exits', 'bracket_orders',
    'trade_postmortems', 'position_snapshots', 'live_trades',
  ]},
  training: { color: '#8B5CF6', label: 'Training', tables: [
    'training_examples', 'training_runs', 'model_versions', 'holdout_results',
    'preference_pairs', 'contrastive_pairs', 'quality_scores',
  ]},
  data: { color: '#3B82F6', label: 'Data Collection', tables: [
    'options_chains', 'options_metrics', 'vix_term_structure', 'cboe_ratios',
    'macro_snapshots', 'google_trends', 'earnings_calendar', 'edgar_filings',
    'insider_transactions', 'short_interest', 'fed_communications', 'analyst_estimates',
  ]},
  system: { color: '#F59E0B', label: 'System', tables: [
    'activity_log', 'log_entries', 'command_queue', 'command_results',
    'config_overrides', 'scan_metrics', 'metric_snapshots',
  ]},
  intelligence: { color: '#6366F1', label: 'Intelligence', tables: [
    'council_sessions', 'council_votes', 'audit_reports', 'build_score_history',
    'hshs_snapshots', 'validation_checks',
  ]},
  enrichment: { color: '#EF4444', label: 'Enrichment', tables: [
    'feature_cache', 'enrichment_cache', 'news_cache', 'regime_history',
    'sector_snapshots', 'fundamental_snapshots',
  ]},
}

// Foreign key relationships (source → target)
const FK_EDGES = [
  ['shadow_trades', 'recommendations'],
  ['trade_exits', 'shadow_trades'],
  ['trade_postmortems', 'shadow_trades'],
  ['bracket_orders', 'shadow_trades'],
  ['position_snapshots', 'shadow_trades'],
  ['training_examples', 'shadow_trades'],
  ['quality_scores', 'training_examples'],
  ['holdout_results', 'model_versions'],
  ['council_votes', 'council_sessions'],
  ['build_score_history', 'hshs_snapshots'],
  ['command_results', 'command_queue'],
  ['live_trades', 'recommendations'],
]

/* Fix for #255 — cluster header nodes + larger, more readable table nodes */
function buildNodes(counts) {
  const nodes = []
  const clusterEntries = Object.entries(CLUSTERS)
  const clusterWidth = 220
  const cols = 3
  const rowSpacing = 54
  const headerHeight = 30

  clusterEntries.forEach(([clusterId, cluster], ci) => {
    const col = ci % cols
    const row = Math.floor(ci / cols)
    const baseX = col * 440
    const baseY = row * (cluster.tables.length * rowSpacing + 160)

    // Cluster header node
    nodes.push({
      id: `hdr-${clusterId}`,
      position: { x: baseX, y: baseY - headerHeight - 6 },
      data: { label: cluster.label },
      style: {
        background: 'transparent',
        border: 'none',
        padding: '4px 8px',
        fontSize: 12,
        fontWeight: 700,
        color: cluster.color,
        fontFamily: 'Inter, sans-serif',
        textTransform: 'uppercase',
        letterSpacing: '0.08em',
        pointerEvents: 'none',
      },
      selectable: false,
      draggable: false,
    })

    cluster.tables.forEach((table, ti) => {
      const count = counts?.[table]
      const countLabel = count != null ? (count >= 0 ? ` (${count.toLocaleString()})` : ' (err)') : ''
      nodes.push({
        id: table,
        position: { x: baseX, y: baseY + ti * rowSpacing },
        data: { label: `${table}${countLabel}` },
        style: {
          background: '#0C0C10',
          border: `2px solid ${cluster.color}`,
          borderRadius: 2,
          padding: '12px 16px',
          fontSize: 13,
          color: 'var(--arcis-text-primary)',
          fontFamily: "'JetBrains Mono', monospace",
          minWidth: clusterWidth,
          textAlign: 'left',
          lineHeight: 1.4,
        },
      })
    })
  })

  return nodes
}

/* Fix for #255 — thicker FK edges for readability */
function buildEdges() {
  return FK_EDGES.map(([source, target], i) => ({
    id: `fk-${i}`,
    source,
    target,
    type: 'smoothstep',
    animated: false,
    style: { stroke: '#64748B', strokeWidth: 1.5, strokeDasharray: '5 5' },
    labelStyle: { fill: '#94A3B8', fontSize: 11, fontFamily: 'Inter, sans-serif' },
    labelBgStyle: { fill: '#0F172A', fillOpacity: 0.85 },
  }))
}

export default function DBSchema() {
  const { data: counts } = useQuery({
    queryKey: ['table-counts'],
    queryFn: () => api.getTableCounts().catch(() => ({})),
    refetchInterval: 300000,
  })

  const nodes = useMemo(() => buildNodes(counts), [counts])
  const edges = useMemo(() => buildEdges(), [])

  const tableCount = counts ? Object.keys(counts).length : null
  const domainCount = Object.keys(CLUSTERS).length

  const [flowNodes, , onNodesChange] = useNodesState(nodes)
  const [flowEdges, , onEdgesChange] = useEdgesState(edges)

  const onInit = useCallback((instance) => {
    instance.fitView({ padding: 0.15 })
  }, [])

  return (
    <div className="space-y-4 md:space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: 'var(--arcis-text-primary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>DB Schema</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
            {tableCount != null ? `${tableCount} tables` : 'loading tables'} across {domainCount} domains — dashed lines show foreign keys, counts refresh every 5 min
          </p>
        </div>
        <div className="flex gap-3 flex-wrap">
          {Object.values(CLUSTERS).map(({ color, label }) => (
            <div key={label} className="flex items-center gap-1.5 text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: color }} />
              {label}
            </div>
          ))}
        </div>
      </div>

      <div className="arcis-card" style={{ height: 'calc(100vh - 180px)', padding: 0, overflow: 'hidden' }}>
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onInit={onInit}
          fitView
          nodesDraggable={false}
          nodesConnectable={false}
          proOptions={{ hideAttribution: true }}
          style={{ background: 'var(--arcis-bg-elevated)' }}
        >
          <Background color="#1E293B" gap={20} />
          <Controls
            style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 2 }}
          />
        </ReactFlow>
      </div>
    </div>
  )
}
