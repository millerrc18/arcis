/**
 * DecideRegion — the DECIDE region body (P2-T5, design §3.2).
 * Assembled from T7 primitives + the shipped /console/decide/* endpoints via
 * TanStack Query. Mirrors the NOW region's fetchApi + useQuery idiom.
 *
 * Pending decisions are challenge-and-response cards; acting on one POSTs to
 * /console/decide/action and invalidates BOTH query keys so the queue and the
 * decided-trail refetch.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchApi } from '../../api'
import { PendingQueue, RecentlyDecided } from './components'

export default function DecideRegion() {
  const queryClient = useQueryClient()

  const pending = useQuery({
    queryKey: ['console-decide-pending'],
    queryFn: () => fetchApi('/console/decide/pending'),
  })
  const decided = useQuery({
    queryKey: ['console-decide-decided'],
    queryFn: () => fetchApi('/console/decide/decided'),
  })

  const actionMutation = useMutation({
    mutationFn: ({ decision_key, decision_type, action, risk_tier, reason, evidence }) =>
      fetchApi('/console/decide/action', {
        method: 'POST',
        body: JSON.stringify({ decision_key, decision_type, action, risk_tier, reason, evidence }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['console-decide-pending'] })
      queryClient.invalidateQueries({ queryKey: ['console-decide-decided'] })
    },
  })

  const handleAction = (item, action) => {
    if (action !== 'approve' && action !== 'reject' && action !== 'defer') return
    actionMutation.mutate({
      decision_key: item.decision_key,
      decision_type: item.decision_type,
      action,
      risk_tier: item.risk_tier,
      reason: undefined,
      evidence: item.evidence,
    })
  }

  return (
    <div data-testid="decide-region">
      <PendingQueue data={pending.data} onAction={handleAction} />
      <RecentlyDecided data={decided.data} />
    </div>
  )
}
