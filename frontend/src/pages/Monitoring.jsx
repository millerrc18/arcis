import { useQuery } from '@tanstack/react-query'
import {
  AreaChart,
  Area,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import { fetchApi } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import MetricCard from '../components/MetricCard'
import StatusBadge from '../components/StatusBadge'

function formatTime(ts) {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
  } catch {
    return ts.slice(11, 16)
  }
}

function pct(used, total) {
  if (used == null || total == null || total === 0) return null
  return Math.round((used / total) * 100)
}

export default function Monitoring() {
  const { data: history, isLoading } = useQuery({
    queryKey: ['monitoring-history'],
    queryFn: () => fetchApi('/monitoring/history?hours=24'),
    refetchInterval: 60000,
  })

  const { data: snapshot, isFetching: snapshotFetching } = useQuery({
    queryKey: ['monitoring-snapshot'],
    queryFn: () => fetchApi('/monitoring/snapshot'),
    refetchInterval: 300000,
  })

  if (isLoading) return <LoadingSpinner />

  // `history` is an array on success but /monitoring/history can return
  // { error: "..." } on failure. Coerce to [] to avoid "(e || []).map is not
  // a function" crashes when the API has a hiccup.
  const historyList = Array.isArray(history) ? history : []
  const latest = snapshot || (historyList.length > 0 ? historyList[historyList.length - 1] : null)
  const points = historyList.map(h => ({
    ...h,
    time: formatTime(h.timestamp),
    ram_pct: pct(h.ram_used_mb, h.ram_total_mb),
    disk_pct: pct(h.disk_used_gb, h.disk_total_gb),
    gpu_vram_pct: pct(h.gpu_vram_used_mb, h.gpu_vram_total_mb),
  }))

  const gpuPct = latest?.gpu_util_pct
  const cpuPct = latest?.cpu_pct
  const ramPct = pct(latest?.ram_used_mb, latest?.ram_total_mb)
  const diskPct = pct(latest?.disk_used_gb, latest?.disk_total_gb)
  const ollamaUp = latest?.ollama_status === 'running'

  const last10 = historyList.slice(-10).reverse()

  return (
    <div className="space-y-4 md:space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-xl font-medium" style={{ color: 'var(--arcis-text-primary)' }}>System Monitoring</h2>
        <p className="text-sm mt-1" style={{ color: 'var(--arcis-text-secondary)' }}>
          GPU, CPU, RAM, disk, and Ollama health snapshots.
        </p>
      </div>

      {/* Current metrics cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 md:gap-4">
        <MetricCard label="GPU" value={gpuPct != null ? `${Math.round(gpuPct)}%` : '--'} />
        <MetricCard label="CPU" value={cpuPct != null ? `${Math.round(cpuPct)}%` : '--'} />
        <MetricCard label="RAM" value={ramPct != null ? `${ramPct}%` : '--'} />
        <div data-testid="disk-status">
          <MetricCard label="Disk" value={diskPct != null ? `${diskPct}%` : '--'} />
        </div>
        <div className="arcis-card flex flex-col items-center justify-center gap-1" data-testid="ollama-status" style={{ padding: '12px' }}>
          <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--arcis-text-secondary)' }}>Ollama</div>
          <StatusBadge text={ollamaUp ? 'Running' : 'Offline'} variant={ollamaUp ? 'success' : 'danger'} />
          {latest?.ollama_model && (
            <div className="text-xs truncate max-w-full" style={{ color: 'var(--arcis-text-muted)', fontFamily: 'var(--font-mono)' }}>
              {latest.ollama_model}
            </div>
          )}
        </div>
      </div>

      {/* GPU utilization chart */}
      {points.length > 1 && (
        <div className="arcis-card" data-testid="resource-chart" style={{ padding: '20px' }}>
          <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)', letterSpacing: '0.06em' }}>
            GPU Utilization (24h)
          </h3>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={points}>
              <CartesianGrid stroke="var(--arcis-border)" strokeDasharray="3 3" />
              <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} unit="%" />
              <Tooltip
                contentStyle={{
                  background: 'var(--arcis-bg-surface)',
                  border: '1px solid var(--arcis-border)',
                  borderRadius: 3,
                  fontSize: 12,
                  color: 'var(--tooltip-text)',
                }}
              />
              <Area type="monotone" dataKey="gpu_util_pct" stroke="var(--arcis-accent)" fill="var(--arcis-accent)" fillOpacity={0.2} name="GPU %" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* CPU / RAM chart */}
      {points.length > 1 && (
        <div className="arcis-card" style={{ padding: '20px' }}>
          <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)', letterSpacing: '0.06em' }}>
            CPU + RAM (24h)
          </h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={points}>
              <CartesianGrid stroke="var(--arcis-border)" strokeDasharray="3 3" />
              <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: 'var(--arcis-text-muted)' }} unit="%" />
              <Tooltip
                contentStyle={{
                  background: 'var(--arcis-bg-surface)',
                  border: '1px solid var(--arcis-border)',
                  borderRadius: 3,
                  fontSize: 12,
                  color: 'var(--tooltip-text)',
                }}
              />
              <Line type="monotone" dataKey="cpu_pct" stroke="var(--arcis-accent)" strokeWidth={2} dot={false} name="CPU %" />
              <Line type="monotone" dataKey="ram_pct" stroke="var(--arcis-success)" strokeWidth={2} dot={false} name="RAM %" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Recent snapshots table */}
      <div className="arcis-card" data-testid="log-table" style={{ padding: '20px' }}>
        <h3 className="text-sm uppercase tracking-wide mb-3" style={{ color: 'var(--arcis-text-secondary)', letterSpacing: '0.06em' }}>
          Recent Snapshots
        </h3>
        {last10.length === 0 ? (
          <div className="text-sm text-center py-4" style={{ color: 'var(--arcis-text-muted)' }}>
            No snapshots yet. Data appears after the first collection cycle.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                  {['Time', 'GPU %', 'VRAM', 'Temp', 'CPU %', 'RAM %', 'Disk %', 'Ollama', 'RSS'].map(h => (
                    <th key={h} className="text-left py-2 px-2" style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--arcis-text-secondary)', fontWeight: 500 }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {last10.map((row, i) => (
                  <tr key={row.snapshot_id || i} style={{ borderBottom: '1px solid var(--arcis-border)' }}>
                    <td className="py-1.5 px-2" style={{ color: 'var(--arcis-text-primary)' }}>{formatTime(row.timestamp)}</td>
                    <td className="py-1.5 px-2" style={{ color: 'var(--arcis-text-primary)' }}>{row.gpu_util_pct != null ? `${Math.round(row.gpu_util_pct)}` : '--'}</td>
                    <td className="py-1.5 px-2" style={{ color: 'var(--arcis-text-primary)' }}>
                      {row.gpu_vram_used_mb != null ? `${Math.round(row.gpu_vram_used_mb)}/${Math.round(row.gpu_vram_total_mb || 0)}` : '--'}
                    </td>
                    <td className="py-1.5 px-2" style={{ color: 'var(--arcis-text-primary)' }}>{row.gpu_temp_c != null ? `${Math.round(row.gpu_temp_c)}C` : '--'}</td>
                    <td className="py-1.5 px-2" style={{ color: 'var(--arcis-text-primary)' }}>{row.cpu_pct != null ? `${Math.round(row.cpu_pct)}` : '--'}</td>
                    <td className="py-1.5 px-2" style={{ color: 'var(--arcis-text-primary)' }}>{pct(row.ram_used_mb, row.ram_total_mb) ?? '--'}</td>
                    <td className="py-1.5 px-2" style={{ color: 'var(--arcis-text-primary)' }}>{pct(row.disk_used_gb, row.disk_total_gb) ?? '--'}</td>
                    <td className="py-1.5 px-2">
                      <StatusBadge text={row.ollama_status === 'running' ? 'Up' : 'Down'} variant={row.ollama_status === 'running' ? 'success' : 'danger'} />
                    </td>
                    <td className="py-1.5 px-2" style={{ color: 'var(--arcis-text-muted)' }}>{row.python_rss_mb != null ? `${row.python_rss_mb}M` : '--'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
