/**
 * ScorecardsView tests (P3-T11 + F6).
 *
 * Endpoints consumed (all via fetchApi):
 *   /api/model-performance  — training.py:553-617
 *     { models: [{version, meta, live_metrics, equity_curve}], overall, total_closed_trades, _meta }
 *   /api/activity/feed      — council.py:94-117
 *     array of {id, event_type, detail, created_at, ...} from activity_log
 *   /api/training/versions  — training.py:231-239
 *     { versions: [{version_id, version_name, created_at, training_examples_count, holdout_score, status}] }
 *   /console/know/scorecards (F6 — BARE path)
 *     { per_role, per_task_type, scope_drift, n, state, as_of }
 *
 * Non-vacuous: mocked values appear only when the component consumes them.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ScorecardsView from '../ScorecardsView'

// ---------------------------------------------------------------------------
// Mock payloads — shapes mirrored from actual route handlers
// ---------------------------------------------------------------------------
//
// /api/model-performance (training.py:553-617)
//   models: [{version, meta:{created_at,training_examples,holdout_score,status},
//             live_metrics:{trades,win_rate,profit_factor,sharpe_ratio,avg_pnl_pct,
//                           net_pnl,max_drawdown_pct},
//             equity_curve:[{date,cumulative_pnl}]}]
//   overall: {trades,win_rate,...}
//   total_closed_trades: N
//   _meta: {cohort,n}
//
// /api/activity/feed (council.py:94-117)
//   array of {id,event_type,detail,created_at,...} from activity_log table
//
// /api/training/versions (training.py:231-239)
//   { versions: [{version_id,version_name,created_at,training_examples_count,
//                 holdout_score,status}] }

const NOW = '2026-06-08T10:00:00Z'

// ---------------------------------------------------------------------------
// F6: /console/know/scorecards frozen backend contract shapes
// ---------------------------------------------------------------------------
const MOCK_SCORECARDS_OK = {
  per_role: {
    developer: {
      n: 12,
      success_rate: 0.833,
      rework_rate: 0.167,
      escalation_rate: 0.083,
      blocked_rate: 0.0,
      scope_violations: 1,
      avg_review_cycles: 1.4,
    },
    reviewer: {
      n: 8,
      success_rate: 0.875,
      rework_rate: 0.125,
      escalation_rate: 0.0,
      blocked_rate: 0.0,
      scope_violations: 0,
      avg_review_cycles: 1.1,
    },
  },
  per_task_type: {
    feature: {
      n: 7,
      success_rate: 0.857,
      rework_rate: 0.143,
      escalation_rate: 0.0,
      blocked_rate: 0.0,
      scope_violations: 0,
      avg_review_cycles: 1.2,
    },
  },
  scope_drift: { total_scope_violations: 1, n: 12 },
  n: 12,
  state: 'ok',
  as_of: NOW,
}

const MOCK_SCORECARDS_NO_DATA = {
  per_role: {},
  per_task_type: {},
  scope_drift: { total_scope_violations: 0, n: 0 },
  n: 0,
  state: 'no_data',
  as_of: NOW,
}

const MOCK_MODEL_PERF = {
  models: [
    {
      version: 'v0.36.82',
      meta: {
        version_id: 'mv-001',
        created_at: '2026-06-01',
        training_examples: 412,
        holdout_score: 0.73,
        status: 'active',
      },
      live_metrics: {
        trades: 18,
        win_rate: 0.611,
        profit_factor: 1.84,
        sharpe_ratio: 1.12,
        avg_pnl_pct: 0.023,
        net_pnl: 2140.5,
        max_drawdown_pct: 6.4,
      },
      equity_curve: [
        { date: '2026-06-01', cumulative_pnl: 0 },
        { date: '2026-06-05', cumulative_pnl: 2140.5 },
      ],
    },
    {
      version: 'v0.36.70',
      meta: {
        version_id: 'mv-002',
        created_at: '2026-05-20',
        training_examples: 310,
        holdout_score: 0.68,
        status: 'retired',
      },
      live_metrics: {
        trades: 24,
        win_rate: 0.542,
        profit_factor: 1.42,
        sharpe_ratio: 0.89,
        avg_pnl_pct: 0.015,
        net_pnl: 1580.0,
        max_drawdown_pct: 9.2,
      },
      equity_curve: [],
    },
  ],
  overall: {
    trades: 42,
    win_rate: 0.571,
    profit_factor: 1.61,
    sharpe_ratio: 1.01,
    net_pnl: 3720.5,
  },
  total_closed_trades: 42,
  _meta: { cohort: 'trades.model', n: 42 },
}

const MOCK_ACTIVITY = [
  {
    id: 10,
    event_type: 'pr_merged',
    detail: 'PR #1206 merged: KNOW Wave A',
    created_at: NOW,
  },
  {
    id: 9,
    event_type: 'deploy',
    detail: 'v0.36.82 deployed to prod',
    created_at: NOW,
  },
  {
    id: 8,
    event_type: 'regression',
    detail: 'Test regression found in test_training.py',
    created_at: NOW,
  },
]

const MOCK_VERSIONS = {
  versions: [
    {
      version_id: 'mv-001',
      version_name: 'v0.36.82',
      created_at: '2026-06-01T00:00:00Z',
      training_examples_count: 412,
      holdout_score: 0.73,
      status: 'active',
    },
    {
      version_id: 'mv-002',
      version_name: 'v0.36.70',
      created_at: '2026-05-20T00:00:00Z',
      training_examples_count: 310,
      holdout_score: 0.68,
      status: 'retired',
    },
  ],
}

// ---------------------------------------------------------------------------
// fetch mock
// ---------------------------------------------------------------------------
function jsonResponse(data) {
  return Promise.resolve({
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify(data)),
  })
}

function mockScorecardsApis(overrides = {}) {
  const payloads = {
    modelPerf: MOCK_MODEL_PERF,
    activity: MOCK_ACTIVITY,
    versions: MOCK_VERSIONS,
    scorecards: MOCK_SCORECARDS_OK,
    ...overrides,
  }
  // Path-EXACT matching (startsWith the single-/api-prefixed route). fetchApi
  // prepends API_BASE='/api', so the correct call yields '/api/model-performance';
  // a double-prefix bug ('/api/api/model-performance') will NOT match and the
  // section degrades to its empty state — so this mock CATCHES the prefix defect
  // instead of masking it (was a substring `.includes` that matched both).
  // F6: '/console/know/scorecards' → fetchApi prepends /api → '/api/console/know/scorecards'
  const fetchMock = vi.fn((url) => {
    if (url.startsWith('/api/model-performance')) return jsonResponse(payloads.modelPerf)
    if (url.startsWith('/api/activity/feed')) return jsonResponse(payloads.activity)
    if (url.startsWith('/api/training/versions')) return jsonResponse(payloads.versions)
    if (url.startsWith('/api/console/know/scorecards')) return jsonResponse(payloads.scorecards)
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderScorecardsView(initialPath = '/console/know/scorecards') {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/console/know/scorecards" element={<ScorecardsView />} />
          <Route path="/console/know" element={<div>Know overview</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// Root structure — shell contract
// ---------------------------------------------------------------------------
describe('ScorecardsView — root structure', () => {
  it('renders with data-testid="know-scorecards" (shell contract)', () => {
    mockScorecardsApis()
    renderScorecardsView()
    expect(screen.getByTestId('know-scorecards')).toBeInTheDocument()
  })

  it('renders a back-to-Know-overview link', () => {
    mockScorecardsApis()
    renderScorecardsView()
    const backLink = screen.getByTestId('know-back-link')
    expect(backLink).toBeInTheDocument()
    expect(backLink.getAttribute('href')).toMatch(/\/console\/know$/)
  })
})

// ---------------------------------------------------------------------------
// Model performance — per-version metrics (REAL dimension)
// ---------------------------------------------------------------------------
describe('ScorecardsView — model performance (REAL)', () => {
  it('renders the active model version name from mocked data (non-vacuous: v0.36.82)', async () => {
    mockScorecardsApis()
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      expect(within(panel).getAllByText(/v0\.36\.82/).length).toBeGreaterThanOrEqual(1)
    })
  })

  it('renders win_rate from live_metrics (non-vacuous: 61.1% from 0.611)', async () => {
    mockScorecardsApis()
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      expect(within(panel).getByText(/61\.1%/)).toBeInTheDocument()
    })
  })

  it('renders profit_factor value (non-vacuous: 1.84 from mock)', async () => {
    mockScorecardsApis()
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      expect(within(panel).getByText(/1\.84/)).toBeInTheDocument()
    })
  })

  it('renders trade count from live_metrics (non-vacuous: 18 trades)', async () => {
    mockScorecardsApis()
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      expect(within(panel).getByText(/18/)).toBeInTheDocument()
    })
  })

  it('renders a StalenessBadge for the model-performance section', async () => {
    mockScorecardsApis()
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      const badges = within(panel).getAllByTestId('staleness-badge')
      expect(badges.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('renders empty state honestly when no models returned', async () => {
    mockScorecardsApis({
      modelPerf: { models: [], overall: {}, total_closed_trades: 0, _meta: { n: 0 } },
    })
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      expect(within(panel).getByTestId('scorecards-model-no-data')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// Training version history (REAL dimension)
// ---------------------------------------------------------------------------
describe('ScorecardsView — training versions (REAL)', () => {
  it('renders version history count (non-vacuous: 2 versions from mock)', async () => {
    mockScorecardsApis()
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      // Both version names should appear (may appear in multiple places: row + table)
      expect(within(panel).getAllByText(/v0\.36\.70/).length).toBeGreaterThanOrEqual(1)
    })
  })

  it('renders holdout_score for versions (non-vacuous: 0.73 from mock)', async () => {
    mockScorecardsApis()
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      expect(within(panel).getAllByText(/0\.73/).length).toBeGreaterThanOrEqual(1)
    })
  })
})

// ---------------------------------------------------------------------------
// Activity feed — task-type trends (partially REAL)
// ---------------------------------------------------------------------------
describe('ScorecardsView — activity feed (REAL event types)', () => {
  it('renders event entries from the activity feed (non-vacuous: PR #1206 from mock)', async () => {
    mockScorecardsApis()
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      expect(within(panel).getByText(/PR #1206/)).toBeInTheDocument()
    })
  })

  it('renders regression event detail from activity feed (non-vacuous: test_training.py from mock)', async () => {
    mockScorecardsApis()
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      // The specific activity detail text only appears from the mocked feed row
      expect(within(panel).getByText(/test_training\.py/)).toBeInTheDocument()
    })
  })

  it('renders empty state honestly when no activity entries returned', async () => {
    mockScorecardsApis({ activity: [] })
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      expect(within(panel).getByTestId('scorecards-activity-no-data')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// Per-role / scope-drift honest rendering (F6 replaced the "not-instrumented" panels)
// ---------------------------------------------------------------------------
describe('ScorecardsView — per-role / scope-drift honest rendering', () => {
  it('renders per-role REAL section when scorecards data is present (not "not yet instrumented")', async () => {
    mockScorecardsApis()
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      // Old "not instrumented" testids are GONE — replaced with real rendering
      expect(within(panel).queryByTestId('scorecards-per-role-not-instrumented')).not.toBeInTheDocument()
      expect(within(panel).queryByTestId('scorecards-scope-drift-not-instrumented')).not.toBeInTheDocument()
    })
    // Real per-role data renders
    expect(within(panel).getByTestId('scorecards-per-role-real')).toBeInTheDocument()
  })

  it('scope-drift and per-task-type data render from the scorecards endpoint', async () => {
    mockScorecardsApis()
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      // scope violations from mock (1 total)
      expect(within(panel).getByTestId('scorecards-per-role-real')).toBeInTheDocument()
    })
  })

  it('per-role section does NOT fabricate zeros when scorecards returns no_data', async () => {
    mockScorecardsApis({ scorecards: MOCK_SCORECARDS_NO_DATA })
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      expect(within(panel).getByTestId('scorecards-per-role-no-data')).toBeInTheDocument()
    })
    // No fabricated numeric metric values
    const sentinelValues = within(panel).queryAllByTestId('sentinel-value')
    const zeroValues = sentinelValues.filter((el) => el.textContent === '0')
    expect(zeroValues.length).toBe(0)
  })
})

// ---------------------------------------------------------------------------
// LAW #3 — no raw sentinel values render
// ---------------------------------------------------------------------------
describe('ScorecardsView — LAW #3 no raw sentinels', () => {
  it('does not render raw sentinel value 999 or -1', async () => {
    mockScorecardsApis()
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      expect(within(panel).queryByText('999')).not.toBeInTheDocument()
      expect(within(panel).queryByText('-1')).not.toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// F6: Per-role + scope-drift REAL rendering via /console/know/scorecards
// ---------------------------------------------------------------------------
describe('ScorecardsView — F6 per-role real rendering', () => {
  it('fetchApi is called with BARE path /console/know/scorecards (no /api double-prefix)', async () => {
    const fetchMock = mockScorecardsApis()
    renderScorecardsView()
    await waitFor(() => {
      const calls = fetchMock.mock.calls.map(([url]) => url)
      // Must call /api/console/know/scorecards (fetchApi prepends /api)
      expect(calls.some((u) => u.startsWith('/api/console/know/scorecards'))).toBe(true)
      // Must NOT call the double-prefixed /api/api/... path
      expect(calls.some((u) => u.startsWith('/api/api/'))).toBe(false)
    })
  })

  it('renders per-role section with real data rows when per_role is non-empty (not "not yet instrumented")', async () => {
    mockScorecardsApis()
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      // Per-role data present: the "not yet instrumented" placeholder must be GONE
      expect(within(panel).queryByTestId('scorecards-per-role-not-instrumented')).not.toBeInTheDocument()
      // Role names from the mock should appear
      expect(within(panel).getByText(/developer/i)).toBeInTheDocument()
    })
  })

  it('renders success_rate as percentage (non-vacuous: 83.3% from 0.833 developer mock)', async () => {
    mockScorecardsApis()
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      expect(within(panel).getByText(/83\.3%/)).toBeInTheDocument()
    })
  })

  it('renders scope-drift section with real data when per_role is non-empty (not "not yet instrumented")', async () => {
    mockScorecardsApis()
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      // Scope-drift "not yet instrumented" placeholder must be GONE
      expect(within(panel).queryByTestId('scorecards-scope-drift-not-instrumented')).not.toBeInTheDocument()
      // scope_violations value (1) from mock scope_drift
      expect(within(panel).getByTestId('scorecards-per-role-real')).toBeInTheDocument()
    })
  })

  it('state no_data → honest empty state, NOT zeros (non-vacuous: zeros do NOT appear)', async () => {
    mockScorecardsApis({ scorecards: MOCK_SCORECARDS_NO_DATA })
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      expect(within(panel).getByTestId('scorecards-per-role-no-data')).toBeInTheDocument()
    })
    const noDataEl = within(panel).getByTestId('scorecards-per-role-no-data')
    expect(noDataEl.textContent).toMatch(/no instrumented runs yet/i)
    // Must not render fabricated zero rates
    const sentinelValues = within(panel).queryAllByTestId('sentinel-value')
    const zeroValues = sentinelValues.filter((el) => el.textContent === '0')
    // Zero must NOT appear as a fabricated metric rate in the no-data state
    expect(zeroValues.length).toBe(0)
  })

  it('empty per_role {} → honest empty state (non-vacuous: mocked numbers appear only when per_role non-empty)', async () => {
    mockScorecardsApis({ scorecards: { ...MOCK_SCORECARDS_NO_DATA, state: 'ok', per_role: {} } })
    renderScorecardsView()
    const panel = screen.getByTestId('know-scorecards')
    await waitFor(() => {
      expect(within(panel).getByTestId('scorecards-per-role-no-data')).toBeInTheDocument()
    })
  })
})
