import {
  MiniMap,
  useNodesState,
  useEdgesState,
} from '@xyflow/react'
import FlowDiagram from '../components/diagrams/FlowDiagram'
import SystemNode from '../components/diagrams/SystemNode'

/* Fix for #255 — improved node styling for readability */
const nodeStyle = (bg, border) => ({
  background: bg,
  border: `2px solid ${border}`,
  borderRadius: 2,
  padding: '14px 20px',
  fontSize: 13,
  color: 'var(--arcis-text-primary)',
  fontFamily: 'Inter, sans-serif',
  minWidth: 150,
  textAlign: 'center',
  lineHeight: 1.4,
})

/* Fix for #255 — group header nodes are visually distinct */
const groupHeaderStyle = (color) => ({
  background: 'transparent',
  border: 'none',
  borderRadius: 0,
  padding: '4px 8px',
  fontSize: 12,
  fontWeight: 700,
  color: color,
  fontFamily: 'Inter, sans-serif',
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  pointerEvents: 'none',
})

const BLUE = '#3B82F6'
const PROCESSING = '#6366F1'
const GREEN = '#22C55E'
const AMBER = '#F59E0B'
const RED = '#EF4444'
const PURPLE = '#8B5CF6'
const SLATE = '#1E293B'

/* Fix for #255 — added group headers, increased spacing for larger nodes */
const initialNodes = [
  // Group headers
  { id: 'hdr-data', position: { x: 50, y: -28 }, data: { label: 'Data Sources' }, style: groupHeaderStyle(BLUE), selectable: false, draggable: false },
  { id: 'hdr-proc', position: { x: 150, y: 95 }, data: { label: 'Processing' }, style: groupHeaderStyle(PROCESSING), selectable: false, draggable: false },
  { id: 'hdr-decision', position: { x: 100, y: 230 }, data: { label: 'Decision & Risk' }, style: groupHeaderStyle(AMBER), selectable: false, draggable: false },
  { id: 'hdr-exec', position: { x: 200, y: 370 }, data: { label: 'Execution' }, style: groupHeaderStyle(GREEN), selectable: false, draggable: false },
  { id: 'hdr-train', position: { x: 50, y: 500 }, data: { label: 'Training Flywheel' }, style: groupHeaderStyle(PURPLE), selectable: false, draggable: false },
  { id: 'hdr-infra', position: { x: 100, y: 640 }, data: { label: 'Infrastructure' }, style: groupHeaderStyle('#94A3B8'), selectable: false, draggable: false },

  // Row 1: Data Sources
  { id: 'universe', position: { x: 50, y: 0 }, data: { label: 'Universe\nS&P 100' }, style: nodeStyle(SLATE, BLUE) },
  { id: 'yfinance', position: { x: 250, y: 0 }, data: { label: 'yfinance\nOHLCV + Options' }, style: nodeStyle(SLATE, BLUE) },
  { id: 'edgar', position: { x: 450, y: 0 }, data: { label: 'SEC EDGAR\nFundamentals' }, style: nodeStyle(SLATE, BLUE) },
  { id: 'finnhub', position: { x: 650, y: 0 }, data: { label: 'Finnhub\nNews + Insiders' }, style: nodeStyle(SLATE, BLUE) },
  { id: 'fred', position: { x: 850, y: 0 }, data: { label: 'FRED\n34+ Macro Series' }, style: nodeStyle(SLATE, BLUE) },

  // Row 2: Processing
  { id: 'features', position: { x: 150, y: 130 }, data: { label: 'Feature Engine\nTechnicals + Regime + Sector' }, style: nodeStyle(SLATE, PROCESSING) },
  { id: 'enrichment', position: { x: 450, y: 130 }, data: { label: 'Data Enrichment\n7 Sources + PEAD' }, style: nodeStyle(SLATE, PROCESSING) },
  { id: 'collectors', position: { x: 750, y: 130 }, data: { label: '12 Overnight\nCollectors' }, style: nodeStyle(SLATE, PROCESSING) },

  // Row 3: Decision & Risk
  { id: 'scoring', position: { x: 100, y: 265 }, data: { label: 'Ranking\nScore 0-100' }, style: nodeStyle(SLATE, AMBER) },
  { id: 'traffic_light', position: { x: 300, y: 265 }, data: { label: 'Traffic Light\nRegime Gate' }, style: nodeStyle(SLATE, AMBER) },
  { id: 'risk', position: { x: 500, y: 265 }, data: { label: 'Risk Governor\n8 Checks + Kill Switch' }, style: nodeStyle(SLATE, RED) },
  { id: 'llm', position: { x: 750, y: 265 }, data: { label: 'halcyon-v1\nPacket Writer' }, style: nodeStyle(SLATE, PURPLE) },

  // Row 4: Execution
  { id: 'shadow', position: { x: 200, y: 400 }, data: { label: 'Shadow Execution\nAlpaca Brackets' }, style: nodeStyle(SLATE, GREEN) },
  { id: 'live', position: { x: 450, y: 400 }, data: { label: 'Live Execution\nAlpaca Paper/Live' }, style: nodeStyle(SLATE, GREEN) },
  { id: 'reconcile', position: { x: 700, y: 400 }, data: { label: 'Reconciliation\nEvery 15 min' }, style: nodeStyle(SLATE, GREEN) },

  // Row 5: Training Flywheel
  { id: 'blinding', position: { x: 50, y: 535 }, data: { label: 'Self-Blinding\nGeneration' }, style: nodeStyle(SLATE, PURPLE) },
  { id: 'quality', position: { x: 250, y: 535 }, data: { label: 'Quality Scoring\nLLM-as-Judge' }, style: nodeStyle(SLATE, PURPLE) },
  { id: 'leakage', position: { x: 450, y: 535 }, data: { label: 'Leakage\nDetection' }, style: nodeStyle(SLATE, PURPLE) },
  { id: 'curriculum', position: { x: 650, y: 535 }, data: { label: 'Curriculum SFT\n3-Stage Training' }, style: nodeStyle(SLATE, PURPLE) },
  { id: 'eval', position: { x: 850, y: 535 }, data: { label: 'A/B Eval\n+ Holdout' }, style: nodeStyle(SLATE, PURPLE) },

  // Row 6: Infrastructure
  { id: 'scheduler', position: { x: 100, y: 670 }, data: { label: 'Watch Loop\n24/7 Scheduler' }, style: nodeStyle(SLATE, '#64748B') },
  { id: 'dashboard', position: { x: 350, y: 670 }, data: { label: 'Arcis Dashboard\n16 Pages' }, style: nodeStyle(SLATE, '#64748B') },
  { id: 'telegram', position: { x: 600, y: 670 }, data: { label: 'Telegram\nNotifications' }, style: nodeStyle(SLATE, '#64748B') },
  { id: 'render', position: { x: 830, y: 670 }, data: { label: 'Render\nCloud Deploy' }, style: nodeStyle(SLATE, '#64748B') },
]

/* Fix for #255 — thicker edges and readable labels */
const edgeDefaults = { type: 'smoothstep', animated: true, style: { stroke: '#64748B', strokeWidth: 2 }, labelStyle: { fill: '#94A3B8', fontSize: 11, fontFamily: 'Inter, sans-serif' }, labelBgStyle: { fill: '#0F172A', fillOpacity: 0.85 } }

const initialEdges = [
  // Data → Processing
  { id: 'e1', source: 'universe', target: 'features', ...edgeDefaults },
  { id: 'e2', source: 'yfinance', target: 'features', ...edgeDefaults },
  { id: 'e3', source: 'edgar', target: 'enrichment', ...edgeDefaults },
  { id: 'e4', source: 'finnhub', target: 'enrichment', ...edgeDefaults },
  { id: 'e5', source: 'fred', target: 'enrichment', ...edgeDefaults },
  { id: 'e5b', source: 'yfinance', target: 'collectors', ...edgeDefaults },

  // Processing → Decision
  { id: 'e6', source: 'features', target: 'scoring', ...edgeDefaults },
  { id: 'e7', source: 'enrichment', target: 'scoring', ...edgeDefaults },
  { id: 'e8', source: 'scoring', target: 'traffic_light', ...edgeDefaults },
  { id: 'e9', source: 'traffic_light', target: 'risk', ...edgeDefaults },
  { id: 'e10', source: 'risk', target: 'llm', ...edgeDefaults },

  // Decision → Execution
  { id: 'e11', source: 'risk', target: 'shadow', ...edgeDefaults },
  { id: 'e12', source: 'risk', target: 'live', ...edgeDefaults },
  { id: 'e13', source: 'shadow', target: 'reconcile', ...edgeDefaults },
  { id: 'e14', source: 'live', target: 'reconcile', ...edgeDefaults },

  // Execution → Training
  { id: 'e15', source: 'shadow', target: 'blinding', ...edgeDefaults, style: { ...edgeDefaults.style, stroke: PURPLE, strokeDasharray: '5 5' } },
  { id: 'e16', source: 'blinding', target: 'quality', ...edgeDefaults },
  { id: 'e17', source: 'quality', target: 'leakage', ...edgeDefaults },
  { id: 'e18', source: 'leakage', target: 'curriculum', ...edgeDefaults },
  { id: 'e19', source: 'curriculum', target: 'eval', ...edgeDefaults },
  { id: 'e20', source: 'eval', target: 'llm', ...edgeDefaults, style: { ...edgeDefaults.style, stroke: PURPLE, strokeDasharray: '5 5' } },

  // Infrastructure connections
  { id: 'e21', source: 'scheduler', target: 'features', ...edgeDefaults, style: { ...edgeDefaults.style, stroke: '#475569', strokeDasharray: '3 3' } },
  { id: 'e22', source: 'dashboard', target: 'render', ...edgeDefaults, style: { ...edgeDefaults.style, stroke: '#475569', strokeDasharray: '3 3' } },
]

const legendItems = [
  { color: BLUE, label: 'Data Sources' },
  { color: PROCESSING, label: 'Processing' },
  { color: AMBER, label: 'Decision' },
  { color: RED, label: 'Risk' },
  { color: GREEN, label: 'Execution' },
  { color: PURPLE, label: 'Training' },
  { color: '#64748B', label: 'Infrastructure' },
]

const nodeTypes = { system: SystemNode }

export default function Architecture() {
  const [nodes, , onNodesChange] = useNodesState(initialNodes)
  const [edges, , onEdgesChange] = useEdgesState(initialEdges)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: 'var(--arcis-text-primary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>System Architecture</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
            Interactive pipeline diagram — drag nodes, scroll to zoom
          </p>
        </div>
        <div className="flex gap-3 flex-wrap">
          {legendItems.map(({ color, label }) => (
            <div key={label} className="flex items-center gap-1.5 text-xs" style={{ color: 'var(--arcis-text-secondary)' }}>
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: color }} />
              {label}
            </div>
          ))}
        </div>
      </div>

      <FlowDiagram
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        className="arcis-card"
        style={{ height: 'calc(100vh - 180px)', padding: 0, overflow: 'hidden', background: 'var(--arcis-bg-elevated)' }}
      >
        <MiniMap
          style={{ background: 'var(--arcis-bg-surface)', border: '1px solid var(--arcis-border)', borderRadius: 2 }}
          nodeColor="#3B82F6"
          maskColor="rgba(5, 5, 7, 0.7)"
        />
      </FlowDiagram>
    </div>
  )
}
