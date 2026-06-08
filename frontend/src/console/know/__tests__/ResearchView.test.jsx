/**
 * ResearchView tests (P3-T10 — Research corpus + AI-Council panel).
 *
 * Mirrors NowRegion test idiom: MemoryRouter + QueryClientProvider.
 * Non-vacuous: each assertion checks a value only present when the component
 * consumes the mocked response.
 *
 * Endpoint shapes mirrored from:
 *   /api/packets         — trades.py:363 → returns array directly
 *   /api/notes           — notes.py:48   → {notes: [...]}
 *   /api/research/digest — training.py:493 → row|{digest:null}
 *   /api/research/papers — training.py:477 → {papers:[...], count:N}
 *   /api/council/latest  — council.py:29  → session row|{session:null}
 *   /api/council/history — council.py:51  → array of session rows
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ResearchView from '../ResearchView'

// ---------------------------------------------------------------------------
// Mock payloads — REAL backend shapes
// ---------------------------------------------------------------------------
const NOW = '2026-06-08T14:00:00Z'

// /api/packets → array directly (trades.py:363-382)
const MOCK_PACKETS = [
  {
    recommendation_id: 'rec-001',
    ticker: 'AAPL',
    company_name: 'Apple Inc.',
    priority_score: 85,
    confidence_score: 7,
    event_risk_flag: 'none',
    entry_zone: '175-177',
    stop_level: '170',
    target_1: '185',
    target_2: '195',
    thesis_text: '<why_now>Strong momentum breakout</why_now>',
    created_at: NOW,
    shadow_pnl_dollars: null,
    shadow_pnl_pct: null,
  },
  {
    recommendation_id: 'rec-002',
    ticker: 'TSLA',
    company_name: 'Tesla Inc.',
    priority_score: 72,
    confidence_score: 6,
    event_risk_flag: 'earnings',
    entry_zone: '200-205',
    stop_level: '190',
    target_1: '220',
    target_2: '240',
    thesis_text: '<thesis>Oversold bounce setup</thesis>',
    created_at: NOW,
    shadow_pnl_dollars: 250,
    shadow_pnl_pct: 0.05,
  },
]

// /api/notes → {notes: [...]} (notes.py:48-60)
const MOCK_NOTES = {
  notes: [
    {
      note_id: 'note-001',
      title: 'Macro regime analysis',
      content: 'Fed pivot signals suggest rate cuts approaching',
      tags: ['macro', 'rates'],
      pinned: true,
      created_at: NOW,
      updated_at: NOW,
    },
    {
      note_id: 'note-002',
      title: 'AAPL thesis update',
      content: 'Services revenue continues to impress',
      tags: ['equity'],
      pinned: false,
      created_at: NOW,
      updated_at: NOW,
    },
  ],
}

// /api/research/digest → digest row or {digest: null} (training.py:493-501)
const MOCK_DIGEST = {
  id: 'digest-001',
  week_start: '2026-06-01',
  week_end: '2026-06-07',
  summary: 'This week momentum strategies outperformed value.',
  key_themes: '["rate sensitivity", "earnings beats"]',
  created_at: NOW,
}

// /api/research/papers → {papers: [...], count: N} (training.py:477-490)
const MOCK_PAPERS = {
  papers: [
    {
      id: 'paper-001',
      source: 'arxiv',
      title: 'Deep Reinforcement Learning for Trading',
      authors: 'Smith, J.',
      abstract: 'We propose a novel RL agent for equity trading.',
      url: 'https://arxiv.org/abs/example',
      published_date: '2026-06-01',
      relevance_score: 0.87,
      relevance_reason: 'Directly applicable to signal generation',
      actionable: true,
      collected_at: NOW,
    },
  ],
  count: 1,
}

// /api/council/latest → session row or {session: null} (council.py:29-48)
const MOCK_COUNCIL_LATEST = {
  session_id: 'sess-001',
  session_type: 'weekly_review',
  consensus: 'bullish',
  created_at: NOW,
  rounds_completed: 2,
  total_cost: 0.0245,
  trigger_reason: 'Scheduled weekly review',
  result_json: {
    votes: { direction: 'bullish', confidence_avg: 0.72 },
    agent_assessments: [
      {
        agent_name: 'tactical_operator',
        vote: 'increase_exposure',
        confidence_float: 0.8,
        key_reasoning: 'Breakout confirmed',
        key_risk: 'Earnings overhang',
      },
    ],
    summary: 'Council recommends increasing exposure given strong breadth.',
  },
  votes: [],
}

// /api/council/history → array of session rows (council.py:51-68)
const MOCK_COUNCIL_HISTORY = [
  {
    session_id: 'sess-001',
    session_type: 'weekly_review',
    consensus: 'bullish',
    created_at: NOW,
    rounds_completed: 2,
    total_cost: 0.0245,
  },
  {
    session_id: 'sess-000',
    session_type: 'weekly_review',
    consensus: 'neutral',
    created_at: '2026-06-01T14:00:00Z',
    rounds_completed: 1,
    total_cost: 0.0178,
  },
]

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

function mockResearch(overrides = {}) {
  const payloads = {
    packets: MOCK_PACKETS,
    notes: MOCK_NOTES,
    digest: MOCK_DIGEST,
    papers: MOCK_PAPERS,
    councilLatest: MOCK_COUNCIL_LATEST,
    councilHistory: MOCK_COUNCIL_HISTORY,
    ...overrides,
  }
  const fetchMock = vi.fn((url) => {
    if (url.includes('/api/packets')) return jsonResponse(payloads.packets)
    if (url.includes('/api/notes')) return jsonResponse(payloads.notes)
    if (url.includes('/api/research/digest')) return jsonResponse(payloads.digest)
    if (url.includes('/api/research/papers')) return jsonResponse(payloads.papers)
    if (url.includes('/api/council/latest')) return jsonResponse(payloads.councilLatest)
    if (url.includes('/api/council/history')) return jsonResponse(payloads.councilHistory)
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderResearch() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/console/know/research']}>
        <Routes>
          <Route path="/console/know/*" element={
            <div data-testid="know-region">
              <Routes>
                <Route path="research" element={<ResearchView />} />
              </Routes>
            </div>
          } />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// Root data-testid
// ---------------------------------------------------------------------------
describe('ResearchView — root testid', () => {
  it('renders data-testid="know-research" at the root', async () => {
    mockResearch()
    renderResearch()
    await waitFor(() => {
      expect(screen.getByTestId('know-research')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// Corpus — packets list
// ---------------------------------------------------------------------------
describe('ResearchView — packets corpus', () => {
  it('renders packets from /api/packets — AAPL appears only when consumed', async () => {
    mockResearch()
    renderResearch()
    await waitFor(() => {
      expect(screen.getAllByText(/^AAPL$/).length).toBeGreaterThan(0)
    })
  })

  it('renders TSLA packet', async () => {
    mockResearch()
    renderResearch()
    await waitFor(() => {
      expect(screen.getByText(/TSLA/)).toBeInTheDocument()
    })
  })

  it('renders honest empty state when packets array is empty', async () => {
    mockResearch({ packets: [] })
    renderResearch()
    await waitFor(() => {
      expect(screen.getByTestId('research-packets-empty')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// Corpus — notes list
// ---------------------------------------------------------------------------
describe('ResearchView — notes corpus', () => {
  it('renders notes from /api/notes — note title appears only when consumed', async () => {
    mockResearch()
    renderResearch()
    await waitFor(() => {
      expect(screen.getByText(/Macro regime analysis/)).toBeInTheDocument()
    })
  })

  it('renders honest empty state when notes array is empty', async () => {
    mockResearch({ notes: { notes: [] } })
    renderResearch()
    await waitFor(() => {
      expect(screen.getByTestId('research-notes-empty')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// Search filter — client-side
// ---------------------------------------------------------------------------
describe('ResearchView — search filter', () => {
  it('filtering by "AAPL" hides TSLA packet', async () => {
    mockResearch()
    renderResearch()
    await waitFor(() => {
      expect(screen.getByText(/TSLA/)).toBeInTheDocument()
    })
    const searchInput = screen.getByTestId('research-search-input')
    fireEvent.change(searchInput, { target: { value: 'AAPL' } })
    await waitFor(() => {
      expect(screen.queryByText(/TSLA/)).not.toBeInTheDocument()
    })
    // AAPL should still appear (packet ticker or note title)
    expect(screen.getAllByText(/AAPL/).length).toBeGreaterThan(0)
  })

  it('filtering by note title shows only matching note', async () => {
    mockResearch()
    renderResearch()
    await waitFor(() => {
      expect(screen.getByText(/AAPL thesis update/)).toBeInTheDocument()
    })
    const searchInput = screen.getByTestId('research-search-input')
    fireEvent.change(searchInput, { target: { value: 'macro' } })
    await waitFor(() => {
      expect(screen.queryByText(/AAPL thesis update/)).not.toBeInTheDocument()
    })
    expect(screen.getByText(/Macro regime analysis/)).toBeInTheDocument()
  })

  it('clearing the search restores all items', async () => {
    mockResearch()
    renderResearch()
    await waitFor(() => {
      expect(screen.getByText(/TSLA/)).toBeInTheDocument()
    })
    const searchInput = screen.getByTestId('research-search-input')
    fireEvent.change(searchInput, { target: { value: 'AAPL' } })
    await waitFor(() => {
      expect(screen.queryByText(/TSLA/)).not.toBeInTheDocument()
    })
    fireEvent.change(searchInput, { target: { value: '' } })
    await waitFor(() => {
      expect(screen.getByText(/TSLA/)).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// Weekly digest
// ---------------------------------------------------------------------------
describe('ResearchView — weekly digest', () => {
  it('renders digest summary when digest is present', async () => {
    mockResearch()
    renderResearch()
    await waitFor(() => {
      expect(screen.getByText(/momentum strategies outperformed/i)).toBeInTheDocument()
    })
  })

  it('renders honest "no digest yet" state when digest is null', async () => {
    mockResearch({ digest: { digest: null } })
    renderResearch()
    await waitFor(() => {
      expect(screen.getByTestId('research-digest-empty')).toBeInTheDocument()
    })
    const empty = screen.getByTestId('research-digest-empty')
    expect(empty.textContent).toMatch(/digest not yet synthesized|no digest yet/i)
  })

  it('renders papers from /api/research/papers', async () => {
    mockResearch()
    renderResearch()
    await waitFor(() => {
      expect(screen.getByText(/Deep Reinforcement Learning for Trading/)).toBeInTheDocument()
    })
  })

  it('renders honest empty state when papers array is empty', async () => {
    mockResearch({ papers: { papers: [], count: 0 } })
    renderResearch()
    await waitFor(() => {
      expect(screen.getByTestId('research-papers-empty')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// AI Council panel — nested inside ResearchView (NOT separate route)
// ---------------------------------------------------------------------------
describe('ResearchView — AI Council panel (nested)', () => {
  it('renders the council panel INSIDE the know-research container (not a separate route)', async () => {
    mockResearch()
    renderResearch()
    await waitFor(() => {
      const root = screen.getByTestId('know-research')
      const panel = within(root).getByTestId('research-council-panel')
      expect(panel).toBeInTheDocument()
    })
  })

  it('renders council consensus from /api/council/latest — bullish appears only when consumed', async () => {
    mockResearch()
    renderResearch()
    await waitFor(() => {
      const panel = screen.getByTestId('research-council-panel')
      expect(within(panel).getAllByText(/bullish/i).length).toBeGreaterThan(0)
    })
  })

  it('renders council session history from /api/council/history', async () => {
    mockResearch()
    renderResearch()
    await waitFor(() => {
      const panel = screen.getByTestId('research-council-panel')
      expect(within(panel).getByTestId('council-history-list')).toBeInTheDocument()
    })
  })

  it('renders honest empty state when council session is null', async () => {
    mockResearch({ councilLatest: { session: null } })
    renderResearch()
    await waitFor(() => {
      const panel = screen.getByTestId('research-council-panel')
      expect(within(panel).getByTestId('council-no-session')).toBeInTheDocument()
    })
  })

  it('renders honest empty council history when history is empty', async () => {
    mockResearch({ councilHistory: [] })
    renderResearch()
    await waitFor(() => {
      const panel = screen.getByTestId('research-council-panel')
      expect(within(panel).getByTestId('council-history-empty')).toBeInTheDocument()
    })
  })
})
