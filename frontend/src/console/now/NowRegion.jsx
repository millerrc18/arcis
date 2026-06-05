/**
 * NowRegion — the NOW region body (T9, design §3.1).
 * Assembled from T7 primitives + T6 /api/console/now/* endpoints via TanStack Query.
 * Each section degrades honestly: missing data renders alarmed/unknown, never green.
 */
import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../../api'
import {
  GateHero,
  AttentionRow,
  SignalRow,
  PositionsSection,
  SinceBand,
  DevTeamStrip,
} from './components'

const SINCE_HOURS = 6

export default function NowRegion() {
  const gate = useQuery({
    queryKey: ['console-now-gate'],
    queryFn: () => fetchApi('/console/now/gate'),
  })
  const attention = useQuery({
    queryKey: ['console-now-attention'],
    queryFn: () => fetchApi('/console/now/attention'),
  })
  const signals = useQuery({
    queryKey: ['console-now-signals'],
    queryFn: () => fetchApi('/console/now/signals'),
  })
  const positions = useQuery({
    queryKey: ['console-now-positions'],
    queryFn: () => fetchApi('/console/now/positions'),
  })
  const since = useQuery({
    queryKey: ['console-now-since', SINCE_HOURS],
    queryFn: () => fetchApi(`/console/now/since?hours=${SINCE_HOURS}`),
  })
  const devteam = useQuery({
    queryKey: ['console-now-devteam'],
    queryFn: () => fetchApi('/console/now/devteam'),
  })

  return (
    <div data-testid="now-region">
      <GateHero data={gate.data} />
      <AttentionRow data={attention.data} />
      <SignalRow data={signals.data} />
      <PositionsSection data={positions.data} />
      <SinceBand data={since.data} />
      <DevTeamStrip data={devteam.data} />
    </div>
  )
}
