# Track 1.5 / B10 — Dashboard wiring audit (2026-04-25)

## Summary

- Pages audited: 28
- Critical findings: 5
- Important findings: 9
- Cleanup findings: 7
- Future-need findings: 4

---

## Findings by category

### Critical (must fix before merge)

#### C1: Monitoring — cloud route returns `{snapshots:[]}` but frontend expects bare array

- **File:** `frontend/src/pages/Monitoring.jsx:51`, `src/api/cloud_routes/analytics.py:924`
- **Issue:** `GET /api/monitoring/history` in cloud_routes returns `{"snapshots": [...]}`. The frontend does `Array.isArray(history) ? history : []` — this is always false for the cloud shape, so `historyList` is permanently `[]` in cloud mode. The page loads but shows an empty chart for all history.
- **Evidence:**
  - Cloud route: `return {"snapshots": [dict(r) for r in rows]}`
  - Frontend: `const historyList = Array.isArray(history) ? history : []`
  - Local route (`src/api/routes/system.py:652`): `return [dict(r) for r in rows]` — returns plain array, works fine locally.
- **Recommended fix:** Change cloud route to return plain array to match local route: `return [dict(r) for r in rows]`. Or update frontend: `const historyList = Array.isArray(history) ? history : (history?.snapshots || [])`.

---

#### C2: IBShadow page — `/ib-shadow/*` routes absent from local API

- **File:** `frontend/src/pages/IBShadow.jsx:57-65`, `src/api/routes/`
- **Issue:** `api.getIBShadowSummary()` and `api.getIBShadowLog()` call `/ib-shadow/summary` and `/ib-shadow/log`. These routes only exist in `src/api/cloud_routes/ib_shadow.py`. There is no corresponding handler in `src/api/routes/`. In local mode, both queries fail with 404/500 → the page shows an error or empty spinner.
- **Evidence:** `grep -rn "ib-shadow" src/api/routes/` returns nothing. Route exists only in `cloud_routes/ib_shadow.py:22,58`.
- **Recommended fix:** Add `/ib-shadow/summary` and `/ib-shadow/log` routes to `src/api/routes/` (mirror the cloud route logic against the local SQLite `ib_shadow_log` table).

---

#### C3: Strategy page — `/strategy-detail/{type}` route absent from local API

- **File:** `frontend/src/pages/Strategy.jsx:25`, `src/api/routes/`
- **Issue:** `api.getStrategyDetail(selectedStrategy)` calls `/strategy-detail/{type}`. This route only exists in `src/api/cloud_routes/analytics.py:749`. No equivalent in `src/api/routes/`. Local mode returns 404.
- **Evidence:** `grep -rn "strategy-detail" src/api/routes/` returns nothing. Route only in `cloud_routes/analytics.py:749`.
- **Recommended fix:** Add `/strategy-detail/{strategy_type}` to `src/api/routes/system.py` or a new module, using the SQLite-backed logic from the cloud route.

---

#### C4: Dashboard — missing `system/index` route in local API

- **File:** `frontend/src/pages/Dashboard.jsx:231`, `src/api/routes/`
- **Issue:** `api.getSystemIndex()` calls `/system/index`. This endpoint is only in `src/api/cloud_routes/system_index.py:264`. No local counterpart. In local mode the QuickStatsPanel and SystemIndexPanel components receive undefined data and render nothing, silently.
- **Evidence:** `grep -rn "system/index" src/api/routes/` returns nothing.
- **Recommended fix:** Add `/system/index` and `/system/index/{name}/mark-reviewed` to local routes (the cloud route computes from `capability_registry` table which also exists in local SQLite).

---

#### C5: RevenueProjection / Roadmap — `/projections/live` route absent from local API

- **File:** `frontend/src/components/RevenueProjection.jsx:86`, `src/api/routes/`
- **Issue:** `api.getProjectionsLive()` calls `/projections/live`. Only exists in `src/api/cloud_routes/trades.py:563`. Not in local routes. `RevenueProjection` renders gracefully when `live` is undefined (falls back to sliders), but the "Live" mode button is silently broken locally.
- **Evidence:** `grep -rn "projections/live" src/api/routes/` returns nothing. Cloud only.
- **Recommended fix:** Add `/projections/live` to local routes or accept local-only degradation and document it.

---

### Important (should fix)

#### I1: WalkforwardResults — no dark/light theme support (hardcoded Tailwind light colors)

- **File:** `frontend/src/pages/WalkforwardResults.jsx`
- **Issue:** Page uses raw Tailwind classes: `bg-slate-50`, `bg-slate-100`, `bg-slate-200`, `bg-slate-800`, `text-slate-600`, `text-white`. These are fixed colors, not CSS variable tokens. In dark mode the page has a split appearance (some areas use `var(--arcis-*)` tokens from other components; this page does not). The table is unreadable in dark mode.
- **Evidence:** `grep -n "bg-slate\|text-slate\|bg-white" WalkforwardResults.jsx` shows 12 occurrences — all hardcoded.
- **Recommended fix:** Replace raw color classes with `var(--arcis-bg-surface)`, `var(--arcis-text-primary)`, etc., matching the rest of the dashboard.

---

#### I2: StrategyResearch — no dark/light theme support (hardcoded gray classes)

- **File:** `frontend/src/pages/StrategyResearch.jsx`
- **Issue:** Same as I1 — page uses `bg-gray-50`, `bg-gray-100`, `text-gray-500`, `text-gray-600` throughout. Not themed.
- **Evidence:** 20+ occurrences of raw gray classes.
- **Recommended fix:** Replace with arcis token classes.

---

#### I3: Diagnostics — no dark/light theme support (hardcoded gray classes)

- **File:** `frontend/src/pages/Diagnostics.jsx`
- **Issue:** `text-gray-500`, `bg-red-50`, `border-red-200`, `text-red-700`, `bg-gray-50` hardcoded. Error banner and inline text unreadable in dark mode.
- **Evidence:** Multiple occurrences throughout the file.
- **Recommended fix:** Replace with arcis token variables.

---

#### I4: QuickStatsPanel / SystemIndexPanel — dark mode partial mismatch

- **File:** `frontend/src/components/system/QuickStatsPanel.jsx`, `SystemIndexPanel.jsx`, `SystemIndexCard.jsx`, `CapabilityDetailModal.jsx`, `WhatsNewPanel.jsx`
- **Issue:** All five system sub-components use `dark:bg-slate-800`, `dark:border-slate-700`, `dark:text-slate-300` (Tailwind dark-mode classes) rather than the project's CSS-variable token system (`var(--arcis-bg-surface)`). This creates a visual discrepancy on the Dashboard page in dark mode — the system panels look lighter/different from the rest of the dashboard.
- **Recommended fix:** Migrate to arcis token classes like all other components.

---

#### I5: PlatformStatusWidget — dark mode mismatch (hardcoded `bg-white dark:bg-slate-800`)

- **File:** `frontend/src/components/PlatformStatusWidget.jsx:39`
- **Issue:** `<div className="bg-white dark:bg-slate-800 rounded shadow p-4">` — uses Tailwind dark-mode class instead of arcis tokens.
- **Recommended fix:** Replace with `style={{ background: 'var(--arcis-bg-surface)', ... }}`.

---

#### I6: Settings — dark mode partial mismatch (Tailwind mixed with arcis tokens)

- **File:** `frontend/src/pages/Settings.jsx`
- **Issue:** Several elements use raw `bg-gray-*` or `bg-white` in combination with arcis tokens, causing visual inconsistency in dark mode.
- **Evidence:** Confirmed by `grep -n "bg-white\|bg-slate\|text-gray" Settings.jsx`.
- **Recommended fix:** Audit and standardize to arcis tokens.

---

#### I7: Dashboard — `useState` used as `useEffect` for desk list fetch

- **File:** `frontend/src/pages/Dashboard.jsx:235-241`
- **Issue:** The desk-filter list is populated using `useState(() => { api.getShadowDesks()... })`. This is a misuse of the `useState` initializer — the function runs once on mount but is not reactive. The correct pattern is `useEffect`. While it works for initial load, it silently prevents re-fetching if the component re-mounts or if desks change.
- **Evidence:**
  ```js
  useState(() => {
    api.getShadowDesks().then(desks => {
      if (Array.isArray(desks)) { setResearchDesks(desks.filter(...)) }
    }).catch(() => {})
  })
  ```
- **Recommended fix:** Replace with `useEffect(() => { api.getShadowDesks().then(...) }, [])`.

---

#### I8: Monitoring — hardcoded `localhost:8000` in informational text

- **File:** `frontend/src/pages/Monitoring.jsx:79`
- **Issue:** `"View on your local machine at localhost:8000"` hardcoded in the cloud-mode message. Should use the base URL helper or at minimum be configurable.
- **Evidence:** Confirmed by grep.
- **Recommended fix:** Use `${window.location.origin}` or the `API_BASE` config constant.

---

#### I9: Packets — empty-DB renders EmptyState but empty-array check may mask API errors

- **File:** `frontend/src/pages/Packets.jsx:62-65`
- **Issue:** `(!packets || packets.length === 0)` correctly shows `<EmptyState>` for zero packets. However, if the API returns `{packets: []}` instead of a plain array, `packets` would be an object, `packets.length` would be `undefined`, and the empty state would still show — but this would mask a shape mismatch. The local route returns a plain array but the shape should be verified. Minor risk, no crash.
- **Recommended fix:** Verify both local and cloud routes return the same shape (plain array vs `{packets: []}`), add `Array.isArray(packets)` guard.

---

### Cleanup (can defer)

#### CL1: `BacktestEquityChart` component — only imported by StrategyResearch, no direct render

- **File:** `frontend/src/components/BacktestEquityChart.jsx`
- **Issue:** Imported in `StrategyResearch.jsx` but a scan of the file shows it is imported but its render usage should be verified. Not a dead component, but worth confirming it is actually rendered.
- **Recommended fix:** Confirm render path; if unused, remove the import.

---

#### CL2: Dead backend route candidate — `/api/traffic-light/current`

- **File:** `src/api/cloud_routes/analytics.py:225`
- **Issue:** The `/api/traffic-light/current` route exists in cloud_routes but no frontend page, component, or api.js function calls it. Zero callers found.
- **Evidence:** `grep -rn "traffic-light\|trafficLight\|getTraffic" frontend/src/` returns no matches in pages or api.js.
- **Recommended fix:** Mark as dead route candidate for deletion after confirming no other caller (mobile app, scripts).

---

#### CL3: Dead backend route candidate — `/api/projections/live` (local)

- **File:** `src/api/cloud_routes/trades.py:563`
- **Issue:** Only one caller in `RevenueProjection.jsx`, which is only used on the Roadmap page. The Roadmap page is static content with a single API call to `getCtoReport`. The live projection feature is "nice to have" but the page functions completely without it. The endpoint is not in local routes at all (C5 above).
- **Recommended fix:** If the local route is not added, document that `live` mode in RevenueProjection only works in cloud deployment.

---

#### CL4: `Toast` component — unused component file, replaced by inline toast state

- **File:** `frontend/src/components/Toast.jsx`
- **Issue:** `Toast.jsx` exports `ToastContainer` (used in `App.jsx`) and a `toast` singleton function. Multiple pages (Dashboard, Training) use their own `useState`-based inline toast rather than the global `toast()` helper from this component. The component itself is not dead (App.jsx uses it), but the global `toast()` export is unused in pages.
- **Recommended fix:** Standardize pages to use the global `toast()` helper from `Toast.jsx` or document that inline toast is the pattern.

---

#### CL5: WalkforwardResults / StrategyResearch / Diagnostics — no mobile responsive layout

- **File:** `frontend/src/pages/WalkforwardResults.jsx`, `StrategyResearch.jsx`, `Diagnostics.jsx`
- **Issue:** These three pages use wide fixed tables without `overflow-x-auto` wrappers or responsive column hiding. On 375px viewport, tables will overflow the viewport.
- **Recommended fix:** Wrap tables in `<div className="overflow-x-auto">`.

---

#### CL6: `QuickStatsPanel` — receives `data` and `isLoading` as props from Dashboard but Dashboard passes `systemIndex` data; prop name is clear but redundant data passing could use query directly

- **File:** `frontend/src/pages/Dashboard.jsx:231`, `frontend/src/components/system/QuickStatsPanel.jsx`
- **Issue:** Minor architecture cleanup — QuickStatsPanel accepts data as props instead of calling `useQuery` itself, which means Dashboard owns a query it doesn't render directly. This is functional but creates coupling. Low priority.
- **Recommended fix:** Move the `useQuery` call inside QuickStatsPanel.

---

#### CL7: Monitoring — double-fetch of `/monitoring/snapshot` (direct `fetchApi` + `api.getMonitoringSnapshot` in api.js)

- **File:** `frontend/src/pages/Monitoring.jsx:42`
- **Issue:** Uses `fetchApi('/monitoring/snapshot')` directly, bypassing the `api.getMonitoringSnapshot` wrapper defined in `api.js:182`. Minor consistency issue.
- **Recommended fix:** Replace with `api.getMonitoringSnapshot()`.

---

### Future-need (out of scope for Pass 2)

#### F1: Dashboard, TradeHistory, ShadowLedger, Velocity, Attribution — instrumentation_version filtering needed

- **Pages:** Dashboard, TradeHistory, ShadowLedger, Velocity, Attribution, CTOReport
- **Issue:** All pages computing Sharpe, win rate, and aggregate metrics pull from `shadow_trades` without filtering to `instrumentation_version >= 3`. Once the analytics query migration happens, these pages need the filter applied.
- **Future task:** After analytics query migration, add `instrumentation_version >= 3` filter to `/shadow/closed`, `/shadow/metrics`, `/shadow/sharpe-attribution` queries used by these pages.

---

#### F2: Strategy page — `instrumentation_version` filtering also needed

- **Page:** Strategy
- **Issue:** `/strategy-detail/{type}` aggregates historical trade performance without `instrumentation_version` filter.
- **Future task:** Add filter when analytics migration lands.

---

#### F3: Velocity — `time_to_mfe_days` column not yet in schema

- **File:** `frontend/src/pages/Velocity.jsx:59`
- **Issue:** Page references `t.time_to_mfe_days` and explicitly falls back: `const mfeDays = t.time_to_mfe_days ?? t.duration_days`. The page handles this gracefully with a comment noting the column hasn't landed yet. Once the column is added to `shadow_trades`, the scatter chart will auto-populate.
- **Future task:** Add `time_to_mfe_days` to `shadow_trades` schema (already tracked per page comment).

---

#### F4: Council — `askCouncilStrategic` uses POST `/council/strategic` which exists only in cloud_routes

- **File:** `frontend/src/pages/Council.jsx:305`, `src/api/cloud_routes/council.py:110`
- **Issue:** Strategic Q&A mutation calls `/council/strategic` (POST). This route is in `cloud_routes/council.py:110` but not in `src/api/routes/council.py`. In local mode the button submits but gets a 404. Not critical (the primary council view works fine), but the feature is dead locally.
- **Future task:** Add `/council/strategic` to local routes or document as cloud-only feature.

---

## Per-page summary table

| Page | Backend route OK? | Empty-DB safe? | Mobile? | Dark/light? | Findings |
|---|---|---|---|---|---|
| Dashboard | Partial (C4: system/index local missing) | Yes (uses `|| []` guards) | Yes | Yes | C4, I7 |
| LiveLedger | Yes (post-B9) | Yes (EmptyState shown) | Yes | Yes | — |
| ShadowLedger | Yes | Yes (EmptyState for each section) | Yes | Yes | F1 |
| TradeHistory | Yes | Yes (`analysis = null` guard) | Yes | Yes | F1 |
| Council | Partial (F4: strategic POST local missing) | Yes (shows empty sessions list) | Yes | Yes | F4 |
| Packets | Yes | Yes (EmptyState) | Yes | Yes | I9 |
| WalkforwardResults | Yes | Yes (`runs = Array.isArray...`) | No (CL5) | No (I1) | I1, CL5 |
| Strategy | No (C3: local route missing) | N/A | Yes | Yes | C3, F2 |
| StrategyResearch | Yes | Yes (explicit empty state) | No (CL5) | No (I2) | I2, CL5 |
| Attribution | Yes | Yes (shows "0 paired trades" copy) | Yes | Yes | F1 |
| Velocity | Yes | Yes (gated message, no crash) | Yes | Yes | F3 |
| Diagnostics | Yes | Yes (`runs = data?.runs || []`) | No (CL5) | No (I3) | I3, CL5 |
| Training | Yes | Yes (null guards throughout) | Yes | Yes | — |
| ModelPerformance | Yes | Yes (`data?.models || []`) | Yes | Yes | — |
| CTOReport | Yes | Yes (EmptyState + error branch) | Yes | Yes | F1 |
| Health | Partial (no `/ib/status` in cloud_routes) | Yes | Yes | Yes | — |
| Monitoring | Yes (both) | Yes (empty chart) | Yes | Yes | C1, I8, CL7 |
| Logs | Yes | Yes (`logs = logData?.logs || []`) | Yes | Yes | — |
| Settings | Yes | Yes | Yes | Partial (I6) | I6 |
| IBShadow | No (C2: local routes missing) | Has explicit empty state | Yes | Yes | C2 |
| Simulation | Yes | Yes (`data?.results || []`) | Yes | Yes | — |
| StressTest | Yes | Yes (`data?.results || []`) | Yes | Yes | — |
| Validation | Yes | Yes (shows unchecked state) | Yes | Yes | — |
| Architecture | Yes (static — no API calls) | N/A | Yes | Yes | — |
| DBSchema | Yes | Yes (shows 0 counts) | Yes | Yes | — |
| Notes | Yes | Yes (`notes = data?.notes || []`) | Yes | Yes | — |
| Roadmap | Yes (ctoData optional) | Yes (kpis default to 0) | Yes | Yes | C5 |
| Docs | Yes | Yes (empty list shown) | Yes | Yes | — |

**Notes on Health page:** `api.getIBStatus()` calls `/ib/status`, which exists in local routes (`src/api/routes/ib_status.py:25`) but is NOT in `cloud_routes/`. In cloud mode the IB status card gets a 404. This is a minor cloud-only gap, severity Important but left unranked since the page loads correctly otherwise and IB is a local-only integration.

---

## Dead component audit

All 25 components in `frontend/src/components/*.jsx` have at least one importer. No completely dead components found. The following have single importers or constrained use:

| Component | Importers | Status |
|---|---|---|
| `BacktestEquityChart.jsx` | StrategyResearch only | Live (single use) |
| `RevenueProjection.jsx` | Roadmap only | Live (single use) |
| `PlatformStatusWidget.jsx` | Dashboard only | Live |
| `ActivityFeed.jsx` | Dashboard only | Live |
| `DiagnosticKickoffButtons.jsx` | Diagnostics only | Live |
| `DiagnosticRunTable.jsx` | Diagnostics only | Live |
| `DiagnosticRunDetail.jsx` | Diagnostics only | Live |
| `Toast.jsx` | App.jsx (container) | Live — but `toast()` global export is unused (CL4) |
| `OpenPositionCard.jsx` | ShadowLedger only | Live |
| `TimeoutCell.jsx` | ShadowLedger, LiveLedger, TradeHistory | Live (B9 instrumented) |
| `AuthGate.jsx` | App.jsx | Live |
| `CollectorGrid.jsx` | Training only | Live |
| `PipelineStatus.jsx` | Training only | Live |

---

## Pass 2 dispatch recommendation

Round 8 fix tasks (suggested scope, one developer dispatch each after operator triage):

| Priority | Task ID | Scope | Effort |
|---|---|---|---|
| P0 | R8-A | Fix `monitoring/history` cloud route shape mismatch (C1) | 15 min — change one return statement in cloud_routes/analytics.py |
| P0 | R8-B | Add `/ib-shadow/*` routes to local API (C2) | 1h — mirror cloud_routes/ib_shadow.py against SQLite |
| P0 | R8-C | Add `/strategy-detail/{type}` to local API (C3) | 1h — mirror cloud_routes/analytics.py strategy-detail handler |
| P0 | R8-D | Add `/system/index` and mark-reviewed routes to local API (C4) | 2h — system_index.py is complex; may need simplification for local mode |
| P1 | R8-E | Add `/projections/live` to local API or document cloud-only (C5) | 30 min |
| P1 | R8-F | Fix WalkforwardResults, StrategyResearch, Diagnostics dark mode (I1/I2/I3) | 1h each — replace hardcoded Tailwind classes with arcis tokens |
| P1 | R8-G | Fix system sub-components dark mode (I4, I5) — QuickStatsPanel, SystemIndexPanel, PlatformStatusWidget | 1h — replace `dark:bg-slate-*` classes with `var(--arcis-*)` tokens |
| P1 | R8-H | Fix Dashboard `useState` misuse for desk fetch (I7) | 15 min — replace with `useEffect` |
| P2 | R8-I | Add `overflow-x-auto` to WalkforwardResults, StrategyResearch, Diagnostics tables (CL5) | 30 min |
| P2 | R8-J | Fix Monitoring.jsx hardcoded `localhost:8000` (I8) | 5 min |
| Defer | R8-K | Add `instrumentation_version >= 3` filter to analytics queries (F1/F2) | Depends on analytics migration landing — block on that task |
| Defer | R8-L | Add `time_to_mfe_days` column to schema (F3) | Already tracked per code comment |
| Defer | R8-M | Add `/council/strategic` to local routes (F4) | Low priority — cosmetic in local dev |
