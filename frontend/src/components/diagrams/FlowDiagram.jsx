import { ReactFlow, Background, Controls } from '@xyflow/react'
import '@xyflow/react/dist/style.css'

export default function FlowDiagram({
  nodes, edges, nodeTypes, onNodesChange, onEdgesChange,
  fitView = true, className = '', style = {}, children,
}) {
  return (
    <div className={`w-full rounded-lg border ${className}`}
         style={{ height: 600, background: 'var(--arcis-bg-secondary)', ...style }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView={fitView}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={16} size={1} color="var(--arcis-border)" />
        <Controls position="bottom-right" />
        {children}
      </ReactFlow>
    </div>
  )
}
