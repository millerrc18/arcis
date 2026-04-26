# B10 — Dashboard wiring audit (Pass 1 design)

> **Operator addition (2026-04-25):** Added during Pass 1 review immediately after B9 was scoped. Rationale: "while we're touching the dashboard for B9, audit all the wiring to ensure everything is tidy." This task is an audit / investigation that produces a finding list; Pass 2 then triages the findings into fix tasks (likely scope-limited to critical + important; cleanup deferred).

## Pass 1 scope (this task — audit only)

Inventory all dashboard pages, the backend routes feeding them, and the data integrity of each surface. Produce a categorized finding list; **do not fix** in Pass 1. Pass 2 dispatches per-finding fix tasks per operator triage.

## The 28 dashboard pages

`frontend/src/pages/*.jsx`:

| Page | File | Likely backend route(s) |
|---|---|---|
| Dashboard (home) | `Dashboard.jsx` | `/api/system/...`, `/api/shadow/stats` |
| Live Ledger | `LiveLedger.jsx` | `/api/trades/live`, `/api/live/...` |
| Shadow Ledger | `ShadowLedger.jsx` | `/api/shadow/...`, `/api/trades/shadow` |
| Trade History | `TradeHistory.jsx` | `/api/trades/closed`, `/api/shadow/sharpe-attribution` |
| Council | `Council.jsx` | `/api/council/...` |
| Packets | `Packets.jsx` | `/api/packets/...` |
| Walkforward Results | `WalkforwardResults.jsx` | `/api/walkforward/...` |
| Strategy | `Strategy.jsx` | `/api/strategy/...` |
| Strategy Research | `StrategyResearch.jsx` | `/api/research/...` |
| Attribution | `Attribution.jsx` | `/api/shadow/attribution` |
| Velocity | `Velocity.jsx` | `/api/velocity/...` |
| Diagnostics | `Diagnostics.jsx` | `/api/diagnostics/...` |
| Training | `Training.jsx` | `/api/training/status` |
| Model Performance | `ModelPerformance.jsx` | `/api/training/model-performance` |
| CTO Report | `CTOReport.jsx` | `/api/analytics/cto-report` |
| Health | `Health.jsx` | `/api/system/health`, `/api/analytics/health-hshs` |
| Monitoring | `Monitoring.jsx` | `/api/system/...` |
| Logs | `Logs.jsx` | `/api/logs/...` |
| Settings | `Settings.jsx` | `/api/system/config` |
| IB Shadow | `IBShadow.jsx` | `/api/ib_shadow/...` |
| Simulation | `Simulation.jsx` | `/api/simulation/...` |
| Stress Test | `StressTest.jsx` | `/api/stress/...` |
| Validation | `Validation.jsx` | `/api/validation/...` |
| Architecture | `Architecture.jsx` | static + `/api/system/index` |
| DB Schema | `DBSchema.jsx` | `/api/schema/...` |
| Notes | `Notes.jsx` | `/api/notes/...` |
| Roadmap | `Roadmap.jsx` | static markdown |
| Docs | `Docs.jsx` | static markdown links |

(Exact route paths to be confirmed during Pass 2 audit dispatch — Pass 1 design lays out the shape.)

## Audit checklist (Pass 2 will execute)

Per page, check:

### Backend / API checks

- [ ] **Endpoint exists** — `Grep` the page's `useQuery` calls; for each endpoint, confirm a route in `src/api/cloud_routes/` and `src/api/routes/`.
- [ ] **Endpoint returns 200** — sanity-check via local dev server with a fixture DB.
- [ ] **Response shape matches** — TypeScript-style type check between API response and frontend's expected type. (Frontend uses JSX, no TS — but TanStack Query has runtime types; check for shape mismatches via console errors.)
- [ ] **Auth required where appropriate** — fix/632 (commit `e129190`) added auth to walkforward + platform GET routes; verify cloud routes consistently require auth where data is sensitive.
- [ ] **Error handling** — does the page degrade gracefully when the API errors? (Show "couldn't load X" vs blank screen vs crash.)

### Frontend / UX checks

- [ ] **Page renders without console errors** — `npm run dev` + browser DevTools.
- [ ] **Loading state present** — TanStack Query `isLoading` handled with a spinner / skeleton.
- [ ] **Empty state present** — what does the page show with zero rows? (Critical for current post-archive DB state with empty `shadow_trades`.)
- [ ] **Mobile responsive** — sidebar collapses; main content reflows. (MASTER.md notes mobile-responsive sidebar; this audit confirms.)
- [ ] **Dark/light toggle** — every page works in both modes (palette adherence).
- [ ] **Stale data indicators** — does the page show "last updated at ..." for time-sensitive surfaces?

### Cross-cutting checks

- [ ] **`useQuery` cache keys** — are they namespaced consistently? (Inconsistent keys cause duplicate fetches.)
- [ ] **Polling intervals** — pages with auto-refresh set `refetchInterval` reasonably (not too aggressive, not too lax).
- [ ] **Hardcoded URLs** — search for `https://halcyonlab.app` or `localhost:8000` in source — should all go through a base-URL helper.
- [ ] **Dead routes** — any endpoint in `src/api/cloud_routes/` with zero callers from frontend? (Candidates for deletion.)
- [ ] **Dead components** — any `frontend/src/components/*.jsx` with zero importers? (Same.)

### Data-quality checks (specific to today's archive context)

- [ ] **Empty-DB rendering** — current DB has 0 shadow_trades, 25 attribution_trades. Pages should not crash on this state. Specifically check: Dashboard, LiveLedger, ShadowLedger, TradeHistory, Attribution, Velocity, ModelPerformance, CTOReport.
- [ ] **Archive-aware analytics** — pages that show historical stats (Trade History, CTO Report, etc.) should either pull from the archive DB OR honestly show "no data this cycle" without faking values.
- [ ] **`instrumentation_version` filtering** (post-B5) — pages that compute Sharpe, win rate, etc. should filter to `instrumentation_version >= 3` once the column lands. Audit identifies which pages need that filter.

## Pass 2 dispatch shape

The Pass 1 audit produces a finding list categorized:

- **🔴 Critical (Pass 2 must fix)** — broken pages, broken endpoints, error-cascading interactions
- **🟡 Important (Pass 2 should fix)** — visible UX issues, missing empty/loading states, console errors
- **🟢 Cleanup (Pass 2 can defer)** — dead routes, dead components, hardcoded URLs, polish

Pass 2 dispatches **one developer task per Critical + Important finding.** Cleanup findings collected into a follow-up sprint or addressed as drive-by during other work.

## Investigation method (Pass 1 audit dispatch)

Pass 2 will start with a single **Audit Dispatch** task that produces the finding list:

1. `npm run dev` to launch the frontend locally.
2. Click through every page systematically. Capture screenshots + console output.
3. For each page, run the checklist above.
4. Output: `docs/sprints/track_1_5_pass2_dashboard_audit.md` with a findings table + screenshots in a sibling `dashboard_audit_screenshots/` directory.
5. From that output, the operator approves Pass 2 fix scope (Critical → Important → Cleanup as time permits).

This is a 1-hour audit + variable-time fix work. The audit itself is bounded; the fix work depends on what's found.

## Risk: scope creep

The user's instinct to "check the wiring" while touching the dashboard is correct, but a comprehensive audit can balloon into "rewrite the dashboard." Risk-mitigation:

- **Pass 2 scope cap**: only Critical + Important. Cleanup defers explicitly.
- **No new features** during this audit — only fixes for things that are broken. Tab-bar redesigns, new charts, etc. are out of scope.
- **Time budget**: if the audit's fix list exceeds 5 hours of agent time, Pass 2 cuts it down to top-N by operator judgment. The B1-B8 work and Mon's preflight take priority.

## Coordination with B9

B9 surfaces the new B8 timeout column on Live Ledger + Shadow Ledger + Trade History. B10's audit MUST run AFTER B9's changes land OR include B9's changes in its baseline (otherwise B10 reports "missing timeout column" as a finding, which is wrong). Recommended Pass 2 ordering:

1. B8 (schema + writer)
2. B9 (API + frontend)
3. B10 audit dispatch (audits the now-current state, including B9's additions)
4. B10 fix dispatches (per-finding tasks)

## Scope fence

Pass 1: audit checklist documented (this file). No implementation, no inventory beyond file paths.

Pass 2 audit dispatch: produces finding list. May edit no production code beyond sample-fix illustrations in the audit report.

Pass 2 fix dispatches: per-finding, each with its own scope fence per the standard sprint pattern.

## Pass 2 commit message template (for the audit task itself)

```
docs(dashboard): audit findings list — Track 1.5 / B10 audit pass

Captures the state of all 28 dashboard pages: backend route presence,
frontend rendering, console errors, mobile responsiveness, empty/loading
states, dead routes, dead components.

Findings categorized: Critical / Important / Cleanup. Operator triages
which findings get Pass 2 fix dispatches.

Closes Track 1.5 / B10 audit pass; opens Track 1.5 / B10.{1..N} fix tasks.
```
