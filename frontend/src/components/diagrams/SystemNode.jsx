import { Handle, Position } from '@xyflow/react'

const CATEGORY_COLORS = {
  data: 'var(--arcis-success)',
  ai: 'var(--arcis-accent)',
  risk: 'var(--arcis-danger)',
  training: 'var(--arcis-warning)',
  infra: 'var(--arcis-text-muted)',
}

export default function SystemNode({ data }) {
  const accentColor = CATEGORY_COLORS[data.category] || CATEGORY_COLORS.infra
  return (
    <div className="relative rounded-lg border px-3 py-2 min-w-[140px]"
         style={{ background: 'var(--arcis-bg-card)', borderColor: 'var(--arcis-border)' }}>
      <div className="absolute left-0 top-0 bottom-0 w-1 rounded-l-lg"
           style={{ background: accentColor }} />
      <div className="text-xs font-semibold pl-2" style={{ color: 'var(--arcis-text-primary)' }}>
        {data.label}
      </div>
      {data.subtitle && (
        <div className="text-[10px] mt-0.5 pl-2" style={{ color: 'var(--arcis-text-muted)' }}>
          {data.subtitle}
        </div>
      )}
      {data.badge && (
        <span className="text-[9px] px-1.5 py-0.5 rounded-full mt-1 ml-2 inline-block"
              style={{ background: accentColor + '22', color: accentColor }}>
          {data.badge}
        </span>
      )}
      <Handle type="target" position={Position.Top} style={{ background: 'var(--arcis-text-muted)' }} />
      <Handle type="source" position={Position.Bottom} style={{ background: 'var(--arcis-text-muted)' }} />
    </div>
  )
}
