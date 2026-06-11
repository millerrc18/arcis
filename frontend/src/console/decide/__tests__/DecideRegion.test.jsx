/**
 * DecideRegion tests (P2-T5).
 * Mirrors the NOW region test idiom: mock fetchApi via a stubbed global fetch,
 * wrap in QueryClientProvider + MemoryRouter.
 *
 * Mocks use the FROZEN backend contract shapes verbatim (see brief):
 *   /console/decide/pending  → { items:[{decision_key,decision_type,title,
 *       risk_tier,evidence:{label,items:[{label,value}]},intent,blast_radius,
 *       rollback,as_of,source_state}], count, degraded_sources, as_of }
 *   /console/decide/action   ← { decision_key,decision_type,action,risk_tier,reason?,evidence? }
 *                            → { recorded:true, decision:{...}, as_of }
 *   /console/decide/decided  → { items:[{id,decision_key,decision_type,action,
 *       risk_tier,reason,decided_by,decided_at,created_at}],
 *       override_rate:{value,n,as_of,cohort,unit,state}, as_of }
 *
 * Non-vacuous: each assertion checks a value that only appears when the
 * component consumes the mocked response. The Approve test asserts the POST
 * actually fires with the correct body (not a no-op mock).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DecideRegion from '../DecideRegion'
import { DecisionCard, PendingQueue, RecentlyDecided } from '../components'

const NOW = '2026-06-05T14:30:00Z'

// --- frozen contract: a pending decision item ---------------------------------
function item(overrides = {}) {
  return {
    decision_key: 'promote-strat-42',
    decision_type: 'strategy_promotion',
    title: 'Promote strategy #42 to paper',
    risk_tier: 'high',
    evidence: {
      label: 'Backtest evidence',
      items: [
        { label: 'Sharpe', value: 1.4 },
        { label: 'Trades', value: 88 },
      ],
    },
    intent: 'Move strategy #42 from research to paper trading',
    blast_radius: 'Adds one paper book; no live capital',
    rollback: 'Demote back to research; close the paper book',
    as_of: NOW,
    source_state: 'ok',
    ...overrides,
  }
}

const MOCK_PENDING = {
  items: [
    item({ decision_key: 'promote-strat-42', risk_tier: 'high' }),
    item({ decision_key: 'widen-stop-7', risk_tier: 'medium', title: 'Widen stop on book 7' }),
    item({ decision_key: 'enable-collector-x', risk_tier: 'low', title: 'Enable collector X' }),
  ],
  count: 3,
  degraded_sources: [],
  as_of: NOW,
}

const MOCK_DECIDED = {
  items: [
    {
      id: 11,
      decision_key: 'promote-strat-9',
      decision_type: 'strategy_promotion',
      action: 'approve',
      risk_tier: 'high',
      reason: 'Sharpe cleared bar',
      decided_by: 'operator',
      decided_at: NOW,
      created_at: NOW,
    },
  ],
  override_rate: {
    value: 0.25,
    n: 8,
    as_of: NOW,
    cohort: 'decisions.all',
    unit: 'ratio',
    state: 'ok',
  },
  as_of: NOW,
}

// --- fetch mock: route /console/decide/* + capture the POST --------------------
function jsonResponse(data, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(JSON.stringify(data)),
  })
}

function mockDecide(overrides = {}) {
  const payloads = {
    pending: MOCK_PENDING,
    decided: MOCK_DECIDED,
    action: { recorded: true, decision: { decision_key: 'promote-strat-42', action: 'approve' }, as_of: NOW },
    ...overrides,
  }
  const fetchMock = vi.fn((url) => {
    if (url.includes('/console/decide/action')) return jsonResponse(payloads.action)
    if (url.includes('/console/decide/pending')) return jsonResponse(payloads.pending)
    if (url.includes('/console/decide/decided')) return jsonResponse(payloads.decided)
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderDecide() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DecideRegion />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

function renderInProviders(ui) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// DecideRegion shell
// ---------------------------------------------------------------------------
describe('DecideRegion — region shell', () => {
  it('renders inside the data-testid="decide-region" wrapper (shell-compatible)', async () => {
    mockDecide()
    renderDecide()
    expect(await screen.findByTestId('decide-region')).toBeInTheDocument()
  })

  it('queries both pending and decided endpoints', async () => {
    const fetchMock = mockDecide()
    renderDecide()
    await waitFor(() => {
      const urls = fetchMock.mock.calls.map(([u]) => u)
      expect(urls.some((u) => u.includes('/console/decide/pending'))).toBe(true)
      expect(urls.some((u) => u.includes('/console/decide/decided'))).toBe(true)
    })
  })
})

// ---------------------------------------------------------------------------
// DecisionCard — challenge-and-response
// ---------------------------------------------------------------------------
describe('DecisionCard — challenge-and-response', () => {
  it('renders the evidence block (label + each evidence item label/value)', () => {
    renderInProviders(<DecisionCard item={item()} onAction={() => {}} />)
    expect(screen.getByText(/Backtest evidence/)).toBeInTheDocument()
    expect(screen.getByText(/Sharpe/)).toBeInTheDocument()
    expect(screen.getByText(/Trades/)).toBeInTheDocument()
    // values go through SentinelGuard (real value, not a sentinel)
    const guarded = screen.getAllByTestId('sentinel-value')
    expect(guarded.length).toBeGreaterThanOrEqual(2)
  })

  it('renders the Intent / Blast-radius / Rollback section', () => {
    renderInProviders(<DecisionCard item={item()} onAction={() => {}} />)
    expect(screen.getByText(/Intent/i)).toBeInTheDocument()
    expect(screen.getByText(/Blast.?radius/i)).toBeInTheDocument()
    expect(screen.getByText(/Rollback/i)).toBeInTheDocument()
    expect(screen.getByText(/Move strategy #42 from research to paper trading/)).toBeInTheDocument()
    expect(screen.getByText(/Adds one paper book; no live capital/)).toBeInTheDocument()
    expect(screen.getByText(/Demote back to research/)).toBeInTheDocument()
  })

  it('renders Approve / Reject / Defer buttons that call onAction with the action verb', () => {
    const onAction = vi.fn()
    const it1 = item()
    renderInProviders(<DecisionCard item={it1} onAction={onAction} />)
    fireEvent.click(screen.getByRole('button', { name: /approve/i }))
    fireEvent.click(screen.getByRole('button', { name: /reject/i }))
    fireEvent.click(screen.getByRole('button', { name: /defer/i }))
    expect(onAction).toHaveBeenCalledWith(it1, 'approve')
    expect(onAction).toHaveBeenCalledWith(it1, 'reject')
    expect(onAction).toHaveBeenCalledWith(it1, 'defer')
  })

  it('shows the risk_tier badge and a StalenessBadge for as_of', () => {
    renderInProviders(<DecisionCard item={item({ risk_tier: 'high' })} onAction={() => {}} />)
    expect(screen.getByTestId('risk-tier-badge').textContent).toMatch(/high/i)
    expect(screen.getByTestId('staleness-badge')).toBeInTheDocument()
  })

  it('renders an explicit source-degraded note when source_state is degraded (never hidden)', () => {
    renderInProviders(<DecisionCard item={item({ source_state: 'degraded' })} onAction={() => {}} />)
    expect(screen.getByTestId('decision-source-degraded')).toBeInTheDocument()
  })

  it('does NOT render the degraded note when source_state is ok', () => {
    renderInProviders(<DecisionCard item={item({ source_state: 'ok' })} onAction={() => {}} />)
    expect(screen.queryByTestId('decision-source-degraded')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// PendingQueue — grouping + degraded banner + empty state
// ---------------------------------------------------------------------------
describe('PendingQueue', () => {
  it('groups items high → medium → low', () => {
    renderInProviders(<PendingQueue data={MOCK_PENDING} onAction={() => {}} />)
    const groups = screen.getAllByTestId('risk-tier-group')
    const order = groups.map((g) => g.getAttribute('data-risk-tier'))
    expect(order).toEqual(['high', 'medium', 'low'])
  })

  it('renders an honest banner naming the degraded sources when present', () => {
    const degraded = { ...MOCK_PENDING, degraded_sources: ['audit_reports', 'reconciliation'] }
    renderInProviders(<PendingQueue data={degraded} onAction={() => {}} />)
    const banner = screen.getByTestId('degraded-sources-banner')
    expect(banner.textContent).toMatch(/audit_reports/)
    expect(banner.textContent).toMatch(/reconciliation/)
  })

  it('does NOT render the degraded banner when degraded_sources is empty', () => {
    renderInProviders(<PendingQueue data={MOCK_PENDING} onAction={() => {}} />)
    expect(screen.queryByTestId('degraded-sources-banner')).not.toBeInTheDocument()
  })

  it('renders an explicit empty state when the queue is empty', () => {
    renderInProviders(<PendingQueue data={{ items: [], count: 0, degraded_sources: [], as_of: NOW }} onAction={() => {}} />)
    expect(screen.getByText(/No decisions waiting/i)).toBeInTheDocument()
  })

  it('renders an explicit "unavailable" state (NOT a false "No decisions waiting") when the source is down', () => {
    // Law #4 / 2026-06-11 PG-down: an unreadable queue must never look "all clear".
    renderInProviders(
      <PendingQueue
        data={{ items: [], count: 0, degraded_sources: ['all'], as_of: NOW, state: 'unavailable' }}
        onAction={() => {}}
      />
    )
    expect(screen.getByTestId('pending-unavailable')).toBeInTheDocument()
    expect(screen.queryByText(/No decisions waiting/i)).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// RecentlyDecided — trail + override rate (laws #3/#4)
// ---------------------------------------------------------------------------
describe('RecentlyDecided', () => {
  it('renders the decided trail (action · type · decided_at)', () => {
    renderInProviders(<RecentlyDecided data={MOCK_DECIDED} />)
    const trail = screen.getByTestId('decided-trail')
    expect(trail.textContent).toMatch(/approve/i)
    expect(trail.textContent).toMatch(/strategy_promotion/)
  })

  it('renders the override-rate via Metric (cohort/n/asOf) when state is ok', () => {
    renderInProviders(<RecentlyDecided data={MOCK_DECIDED} />)
    expect(screen.getByText(/Override rate/i)).toBeInTheDocument()
    expect(screen.getByText(/decisions\.all/)).toBeInTheDocument()
    expect(screen.getByText(/n=8/)).toBeInTheDocument()
  })

  it('shows an explicit no-data state (—) when override_rate.state is no_data (never 0)', () => {
    const noData = {
      ...MOCK_DECIDED,
      override_rate: { value: null, n: 0, as_of: NOW, cohort: 'decisions.all', unit: 'ratio', state: 'no_data' },
    }
    renderInProviders(<RecentlyDecided data={noData} />)
    expect(screen.getByTestId('override-rate-no-data')).toBeInTheDocument()
    expect(screen.getByTestId('override-rate-no-data').textContent).toMatch(/—|no decisions yet/i)
    // must NOT fabricate a 0
    expect(screen.queryByText(/^0$/)).not.toBeInTheDocument()
  })

  it('renders the reviewer-discipline caption', () => {
    renderInProviders(<RecentlyDecided data={MOCK_DECIDED} />)
    expect(screen.getByText(/an approver who never overrides has stopped reviewing/i)).toBeInTheDocument()
  })

  it('renders an explicit "unavailable" trail + override-rate (NOT a false empty) when the source is down', () => {
    // Law #4: an unreadable trail is not an empty trail; unknown override-rate is not "no decisions yet".
    const unavailable = {
      items: [],
      as_of: NOW,
      state: 'unavailable',
      override_rate: { value: null, n: 0, as_of: null, cohort: 'decisions.all', unit: 'ratio', state: 'unknown' },
    }
    renderInProviders(<RecentlyDecided data={unavailable} />)
    expect(screen.getByTestId('override-rate-unavailable')).toBeInTheDocument()
    expect(screen.queryByTestId('override-rate-no-data')).not.toBeInTheDocument()
    expect(screen.getByTestId('decided-trail').textContent).toMatch(/unavailable/i)
    expect(screen.getByTestId('decided-trail').textContent).not.toMatch(/no decisions recorded yet/i)
  })
})

// ---------------------------------------------------------------------------
// Integration: clicking Approve fires the POST with the correct body
// (non-vacuous — asserts the mutation actually calls fetch with the body)
// ---------------------------------------------------------------------------
describe('DecideRegion — action mutation', () => {
  it('clicking Approve POSTs /console/decide/action with decision_key + action=approve', async () => {
    const fetchMock = mockDecide()
    renderDecide()
    // wait for the first card to render
    const region = await screen.findByTestId('decide-region')
    await waitFor(() => {
      expect(within(region).getAllByRole('button', { name: /approve/i }).length).toBeGreaterThan(0)
    })
    const approveButtons = within(region).getAllByRole('button', { name: /approve/i })
    fireEvent.click(approveButtons[0])

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        ([url, opts]) => url.includes('/console/decide/action') && opts && opts.method === 'POST'
      )
      expect(postCall).toBeTruthy()
      const body = JSON.parse(postCall[1].body)
      expect(body.action).toBe('approve')
      expect(body.decision_key).toBe('promote-strat-42')
      expect(body.decision_type).toBe('strategy_promotion')
      expect(body.risk_tier).toBe('high')
    })
  })

  it('invalidates (refetches) pending + decided after a successful action', async () => {
    const fetchMock = mockDecide()
    renderDecide()
    const region = await screen.findByTestId('decide-region')
    await waitFor(() => {
      expect(within(region).getAllByRole('button', { name: /approve/i }).length).toBeGreaterThan(0)
    })
    const pendingCallsBefore = fetchMock.mock.calls.filter(([u]) => u.includes('/console/decide/pending')).length
    fireEvent.click(within(region).getAllByRole('button', { name: /approve/i })[0])
    await waitFor(() => {
      const pendingCallsAfter = fetchMock.mock.calls.filter(([u]) => u.includes('/console/decide/pending')).length
      expect(pendingCallsAfter).toBeGreaterThan(pendingCallsBefore)
    })
  })
})

// ---------------------------------------------------------------------------
// AsyncBoundary — DECIDE region loading/error vs no-data. Mirror of the NOW
// region describe block. Law-#4: first-load and unreachable-server states must
// NOT render as the no-data/"No decisions waiting" text. Regression guard for
// the 2026-06-11 incident pattern.
// ---------------------------------------------------------------------------
describe('DecideRegion — AsyncBoundary loading/error vs no-data', () => {
  it('renders "loading…" for a first-loading section (NOT "No decisions waiting")', async () => {
    const fetchMock = vi.fn((url) => {
      if (url.includes('/console/decide/pending')) return new Promise(() => {}) // never resolves
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDecide()
    await waitFor(() => {
      const loadings = screen.getAllByTestId('async-loading')
      expect(loadings.some((el) => /Decisions waiting/i.test(el.textContent))).toBe(true)
    })
    // crux: the section shows loading, so "No decisions waiting" must NOT appear
    expect(screen.queryByText(/No decisions waiting/i)).not.toBeInTheDocument()
  })

  it('renders "source unavailable" when a section fetch errors (NOT "No decisions waiting")', async () => {
    const fetchMock = vi.fn((url) => {
      if (url.includes('/console/decide/pending')) return Promise.reject(new Error('api server down'))
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)
    renderDecide()
    await waitFor(() => {
      const errors = screen.getAllByTestId('async-error')
      expect(errors.some((el) => /unavailable/i.test(el.textContent))).toBe(true)
    })
    expect(screen.queryByText(/No decisions waiting/i)).not.toBeInTheDocument()
  })
})
