# Changelog

> **See also:** [`RELEASES.md`](RELEASES.md) — release-process narrative + path-to-v1.0.0 dashboard. This file is the per-change log (Keep-a-Changelog format); RELEASES.md is the process/release-history companion. They are deliberately kept separate (DD-25).

## [Unreleased]

### Added — Conviction denormalized onto shadow_trades (`rec_confidence_score` / `rec_llm_conviction`)

The 2026-06-12 trading health check showed the desk's `recommendations.confidence_score` is **predictive of win-rate** (high ≥8 wins ~50% vs ~12% low) but the trade record dropped it — conviction-vs-outcome calibration was only reconstructable via a `recommendation_id` join. This wires it onto the trade row.

- **Schema (`src/schema/registry.py`):** two new nullable columns on `shadow_trades` — `rec_confidence_score` (REAL) and `rec_llm_conviction` (INTEGER) — denormalized from the source recommendation. Distinct from `setup_confidence` (0–1 feature-classifier scale; intentionally untouched — `confidence_score` is the ~7–9 LLM scale, conflating them would corrupt the Telegram card render).
- **Population (`src/journal/store.py`):** `insert_shadow_trade` — the single choke point all creation paths route through — now calls `_attach_recommendation_conviction()`, which copies the recommendation's conviction onto the trade at insert. **Fully defensive:** any lookup failure leaves the columns NULL and can never break an insert; no-op when there's no `recommendation_id` (orphan/backfilled trades) or the value is already set. One small SELECT per creation (a few/day — negligible).
- **Tests (`tests/journal/test_store_conviction.py`, 6):** 5 hermetic unit tests (populate / no-rec-id no-op / already-set no-op / defensive-on-error / missing-recommendation) + 1 hermetic round-trip through `insert_shadow_trade` (temp SQLite, cutover disabled so it can never touch a live PG). verify-by-mutation: the populate assertions fail if the helper is unwired.
- **Deploy:** registry-driven schema sync (`postgres.create_all_tables`) added the columns to prod PG **before** this code deployed (nullable `ADD COLUMN`, non-blocking) + a one-time backfill of historical rows via the `recommendation_id` join; then restart-validate the watch loop. NULL for the existing orphan/no-recommendation trades.

### Fixed — Test-isolation: local pytest routed `connect_db` to PROD PG under the cutover gate

`connect_db`'s cutover gate (`ARCIS_PG_CUTOVER_ENABLED=1`, loaded from `.env`) routes **every** call by `DATABASE_URL` — **not** `TEST_DATABASE_URL`. The conftest's P0 guard accepts a run as safe whenever `TEST_DATABASE_URL` is set, but with cutover on, `connect_db` still used the `.env`'s prod `DATABASE_URL` — so local pytest silently routed every `connect_db()` to **prod PG (host 5433)**, not the test PG (5434). Read-mostly tests were harmless, but a writing test would have hit prod (and the conviction round-trip test did `INSERT`/`DELETE` against prod before it was made hermetic — cleaned up, prod verified pollution-free). CI is unaffected (it sets no cutover / no prod `DATABASE_URL`).

- **Fix (`tests/conftest.py::pytest_configure`):** after the P0 guard passes, when a safe `TEST_DATABASE_URL` is set, align `DATABASE_URL` to it — so the cutover gate routes `connect_db` to the **test** PG, never prod. One-line env alignment, captured by the existing `_PRECOLLECT_ENV` snapshot so it survives collection scrubs.
- **Validated:** post-fix, pytest `connect_db` hits the test PG (confirmed by content — `rec_*` columns + row count, since `inet_server_port()` reports the container-internal 5432 for both containers and can't distinguish them). `tests/shadow_trading/ tests/test_reconcile.py` = **302 passed, 1 pre-existing failure** (`test_get_strategies_by_status_resolves_none_to_config`, fails on prod and test PG alike) — no new failures, aligning local with CI's already-green test-PG behavior.
- Note: the P0 guard's prod-detector keys on port **5433** (correct — prod's host port) / `halcyon_app:`; raw `python` scripts (data ops) still correctly reach prod via the cutover gate — only pytest is redirected.

### Fixed — Stale test `test_site5_bracket_failure_persists_continues` depended on test-DB state (not a production bug)

`open_shadow_trade`'s atomic duplicate-check runs a raw `connect_db()` SELECT (engine-aware since v0.36.15). The test patched the higher-level `get_open_shadow_trade_for_ticker` but **not** the atomic connection, and used ticker `"AAPL"` — which has an open trade in the test PG. So the dup-check (`executor.py:650`) short-circuited *before* the bracket logic and `log_and_persist(operation='place_bracket_order')` was never reached (`ops == []`).

- **NOT a silent-failure** — the bracket-failure persistence (`executor.py:875`) and the dup-check are both correct. The test was stale (predates the engine-aware dup-check that sibling sites 7/9 already mock via `_no_dup_conn_mock`). Found during the 2026-06-12 trading health check; surfaced by PR #1215 QA.
- **Fix:** site5 now mocks `executor.connect_db` like its siblings, so it deterministically reaches and asserts the real bracket-failure-persistence path. Full file 17/17 green.
- **Known latent fragility (follow-up):** sites 4/8/10 (and 6) call `open_shadow_trade` without the dup-conn mock — green today, but would RED if their ticker gains an open trade in the test PG. A test-robustness pass should add the same mock.

### Fixed — Closed the NaN-pnl persist class: a non-finite price could be saved as `pnl_dollars` (2026-06-12 data-integrity incident)

During the 2026-06-10 PG/data outage the market-data fetch returned a `NaN` close price, and the stuck-trade pnl helpers only guarded `None` / `<= 0` — but `float('nan')` raises nothing and `nan <= 0` is `False`, so the `NaN` flowed straight into `pnl_dollars` / `actual_exit_price` and was persisted to `shadow_trades` (trade `b9c0255d` AAPL). A `NaN` poisons every naive `SUM(pnl_dollars)` aggregate (e.g. a weekly P&L total) — `NaN + anything = NaN`. A sibling-search found a *second* live path (mr-timeout exit) with the same exposure, so the fix closes the whole class at three layers:

- **Source (`src/risk/price_utils.py`):** `_get_current_price_safe` now rejects non-finite/non-positive prices on **both** branches (`if price:` alone let NaN through — `nan` is truthy), returning `None` so the live exit path skips rather than deriving a NaN pnl (the `order_lifecycle.py:548` `is None` guard already handles this).
- **Reconcile helpers (`src/shadow_trading/reconcile.py`):** `_resolve_stuck_pnl`, `_estimate_exit_pnl`, and `_default_current_price_provider` reject non-finite entry **or** exit prices via `math.isfinite`, returning the existing `None` / `(None, None, None)` "UNKNOWN" sentinel.
- **Boundary backstop (`src/journal/store.py`):** `close_shadow_trade` — the single choke point every close routes through — coerces a non-finite `exit_price`/`pnl_dollars`/`pnl_pct` to `None` (with a warning) before persisting, making a saved NaN pnl **structurally impossible** regardless of upstream path.
- **Tests:** `test_reconcile_nan_pnl_guard.py` (8) + `test_nan_pnl_persist_backstop.py` (5) — verify-by-mutation: every NaN/inf case fails on pre-fix code (helpers returned `(nan, nan, nan)`; the boundary persisted NaN); happy-path cases prove the guards are transparent for finite prices. 1 pre-existing env-dependent failure in `test_reconcile_dispatch_db_path::test_get_strategies_by_status_resolves_none_to_config` is unrelated — fails identically on `main`, never references this diff.
- **Data corrections (operational, same incident):** the single poisoned row, AAPL `b9c0255d` (entry order `canceled`, `filled_qty=0` → never a position), re-classified `closed`/`reconciled_stale`/`NaN` → `cancelled`/`entry_unfilled`/`NULL` per the canonical taxonomy. Separately finalized a 17-day-stale `needs_manual_review` row, GOOG `e5684e9b` (05-26 bracket, 8-of-9 partial fill) — confirmed via Alpaca it was liquidated 06-02 @ $361.00 (**no live exposure**); set `closed`/`reconciled`, −$173.36 realized. Zero NaN/inf pnl rows remain in `shadow_trades`.

### Fixed — Morning watchlist (and 5 sibling digest callers) crashed daily on `enqueue_for_email_digest` with no connection

`src/notifications/email_digest.py::enqueue_for_email_digest()` defaulted `conn=None` and passed it straight to `DigestQueue(conn)`, so a caller that didn't inject a connection hit `'NoneType' object has no attribute 'execute'` in `DigestQueue.enqueue`. **6 of 7 production callers** call it without a `conn` (morning-watchlist via `reports.py`, plus the overnight / recap / scan / watchlist / watch routers) — only `auditor.py` injects one. Result: the **morning watchlist failed every morning** (08–09 ET, PG-independent — observed 2026-06-09/10/11). The per-caller email-routing tests *mocked* `enqueue_for_email_digest`, so they passed while production crashed (a vacuous-coverage gap).

- **Fix at the source:** `enqueue_for_email_digest` now **self-connects** via `connect_db()` when `conn is None` (and commits/closes through the `with` block); callers that want to share a transaction still inject a `conn` (e.g. `auditor.py`). This fixes all 6 conn-less callers at once and prevents recurrence.
- **Tests:** real verify-by-mutation — `tests/notifications/test_email_digest_module.py` adds a conn=None self-connect test (fails pre-fix with the exact `AttributeError`) + an injected-conn test (must NOT self-connect, preserving the auditor transaction-sharing path). Full notifications suite + `test_repo_structure` green.

### Added — Console `AsyncBoundary`: distinguish loading / error / no-data (law-#4 refinement)

The console collapsed three distinct TanStack-Query states into one UNKNOWN/no-data render, so every section flashed UNKNOWN for ~1s on first paint (data undefined while the first fetch is in flight) and an unreachable API server looked identical to genuinely-empty data. (This was the root cause of the "integrity signals showing UNKNOWN" observation — the first-load flash, not a render bug; the signals render correctly in steady state.)

- **`frontend/src/console/components/AsyncBoundary.jsx`** — wraps a query result: `isError` → "source unavailable"; first load (`isPending`, no data) → "loading…"; resolved (data present, even honest-degraded) → render children (which keep their own honest no-data/UNKNOWN render). Loading/error are muted, **never green** (law #4 holds). After #1210/#1211 the backend returns 200-honest-degraded (not 5xx) on a DB hiccup, so `isError` now means the API **server** is unreachable — a distinct, rarer state.
- Wired console-wide: NOW (6 sections), DECIDE (2), KNOW (~19 query consumers across 5 files; multi-query views wrap each section independently; nav/tabs stay outside the boundary; now-redundant inline "Loading…" states removed). `ScorecardsView` per-role `scorecardsQuery` intentionally unwrapped (its `scIsSettled` guard already prevents the flash; minor error-state gap documented as a follow-up).
- Tests: `AsyncBoundary` (6, all states + no refetch-flash) + NOW/DECIDE/KNOW loading-error integration (non-vacuous). Full frontend suite 260. Dual-Opus SOUND (verified the wraps are transparent for resolved data — no query/URL/formatter/field changed). Browser-verified: NOW shows "Integrity / liveness — loading…" on first paint instead of the UNKNOWN flash, then renders the signals.

## [v0.37.0] - 2026-06-11 — Founder Operating Console: `/console` replaces the 28-page dashboard (+ DB-down hardening & heartbeat watchdog)

**Release summary:** Replaces the legacy 28-page React dashboard with the 3-region **Founder Operating Console** (NOW · DECIDE · KNOW) — single-source metrics with honest no-data/degraded states (9 design laws), a challenge-and-response veto queue (law #8, record-only), and derive-from-source legibility + analytics (fund ladder, system map, track record, rigor stack, attribution/calibration, research corpus, AI-dev scorecards). The old dashboard was retired (#1209 — `/console` is now the sole UI); every console read endpoint degrades to an honest `unknown`/`unavailable` state — never a 500 — on a DB hiccup (#1210/#1211); and an independent `ArcisHeartbeatMonitor` watchdog pages Telegram if prod PG or the watch-loop heartbeat goes down, so an outage can't go unnoticed. Spans Phase 0 (#1200) + #1202→#1211; the SQLite/PG single-source backend is preserved; the PAPER-only / bootcamp-OFF desk reality is rendered honestly throughout. Operator ops: Docker Desktop auto-start enabled; see `docs/operator-guide.md`.

### Added — Heartbeat/PG-down alert watchdog + DECIDE law-#4 degrade (incident follow-ups)

Robustness follow-ups from the 2026-06-11 pre-market PG-down incident (prod PG 5433 down ~21h, unnoticed, because Docker Desktop hadn't auto-started after a reboot and the crash-looping watch loop couldn't send its own alert):

- **`scripts/heartbeat_monitor.py` — an independent down-alert watchdog.** Detects (a) prod PG 5433 unreachable (raw TCP socket — no DB driver) and (b) the watch-loop heartbeat (`data/watchdog.txt`) stale/missing, then pages Telegram (HTTP — no PG, no watch loop) so a future outage can't go unnoticed for 21h. Deliberately self-contained so it works *because* the desk is degraded: edge-triggered + de-duped (pages once on DOWN after `--fail-threshold` consecutive bad checks for anti-flap; once again on RECOVERED), state in `data/heartbeat_monitor_state.json`. Self-loads `ROOT/.env` + `sys.path` so it sends from any cwd. Registered as the `ArcisHeartbeatMonitor` Windows scheduled task (every 10 min + at-logon); real Telegram delivery verified via `--test-alert`.
- **DECIDE endpoints degrade honestly (law #4 — mirrors the gate+pause fix below).** `GET /api/console/decide/pending` and `/decided` now wrap their service reads at the route boundary — on a full source failure (cutover PG down; `connect_db` raises *before* the service's per-source `degraded_sources` try/finally) they return HTTP 200 with `state: "unavailable"` (pending: `degraded_sources: ["all"]`; decided: `override_rate.state: "unknown"`), never a 500. Frontend `PendingQueue`/`RecentlyDecided` render an explicit **"unavailable"** state — never the false-empty "No decisions waiting" / "no decisions recorded yet" (an unreadable queue is not an empty one).
- **Recurrence prevention (ops, no code):** Docker Desktop "start on login" enabled (its Task-Manager startup entry was disabled). See `docs/operator-guide.md`.
- TDD (RED→GREEN, verify-by-mutation); tests +3 backend (DECIDE) +2 frontend (DECIDE) +9 (monitor). Backend 63 + frontend 231 green.

### Fixed — Console NOW gate + PAUSE degrade honestly when the DB source is down (law #4)

Now that `/console` is the sole UI, a Postgres hiccup must not break the cockpit. The 2026-06-11 pre-market PG-down incident (Docker Desktop hadn't auto-started after a reboot) surfaced that two console read endpoints let `psycopg2.OperationalError` propagate → HTTP 500, while their sibling NOW endpoints (`/now/signals`, `/now/positions`) already degrade to an honest `unknown` state.

- **`GET /api/console/now/gate`** now wraps `_fetch_closed_trades()` — on any source failure it returns HTTP 200 with every gate metric in an explicit `state: "unknown"` envelope (rendered by the existing `<Metric>` "missing required context" path), never a 500. Targets remain present so the bar shell renders honestly.
- **`GET /api/console/pause`** now wraps `read_pause_state()` — on a source failure it returns `{is_paused: null, state: "unavailable", …}` (HTTP 200). `is_paused` is **null (unknown), not false** — a false "RUNNING" on a missing source is the never-green-on-missing violation. `read_pause_state()` itself stays pure (raises); the guard lives at the route boundary. The scan/executor gate `is_paused()` independently fails **closed**, so a paused desk never silently resumes while the source is down.
- **`HonestHeader` (frontend)** no longer renders the green "RUNNING" state (or a Pause/Resume toggle) when the pause source is unavailable — it shows an explicit muted **"pause n/a"** indicator. Verified in a live browser (forced-unavailable → "PAUSE N/A", no false-green) and by a real-render vitest.
- Backend untouched elsewhere; TDD (RED→GREEN, verify-by-mutation that `read_pause_state` raises without the guard). Tests: backend `tests/api/test_console_now.py` + `test_console_pause_route.py` (+3), frontend `HonestHeader.test.jsx` (+1) — full suites green (backend 70 incl. structure, frontend 229).
- Ops follow-up (separate): Docker Desktop "start on login" **enabled** to stop the recurrence (a reboot was silently downing the desk's sole write target); a heartbeat/PG-down alert remains open.

### Removed — Old 28-page dashboard retired; `/console` is now the sole UI

The Founder Operating Console (NOW · DECIDE · KNOW) reached parity across Phases 1–3 + the analytics follow-ups, so the legacy React dashboard it replaced has been deleted — the deliberate *"delete the old app only once the console is complete"* cutover.

- **Deleted 100 files** — all of `frontend/src/pages/*` (28 page components + 19 co-located tests) and the 35 now-orphaned shared widgets those pages used: `frontend/src/components/Layout.jsx` (the 28-link nav), the entire `components/{dashboard,system,diagrams}/` trees, and 23 standalone widgets (`BacktestEquityChart`, `KPIStrip`, `MetricCard`, `DataTable`, `ShadowLedger`-harness tests, …) plus their tests/snapshots. The safe-to-delete set was computed by **transitive import-reachability** from the post-cutover keep-roots — `/console` is provably page-independent (0 pages reachable from it), and only `ErrorBoundary`, `Toast`, `AuthGate` survive as shared app infra (the console carries its own `src/console/components/` primitives).
- **`frontend/src/App.jsx` rewired** — the `<Route element={<Layout/>}>` tree (28 routes) is gone; `/console/*` is the only mounted route and every legacy path (`/`, `/shadow`, `/training`, …) redirects into it via `<Route path="*" element={<Navigate to="/console" replace />} />` (the specific `/console/*` route outranks the catch-all, so no redirect loop). All app-level providers (QueryClient, WebSocket cache-invalidation, Toasts, ErrorBoundary, AuthGate) are preserved — infrastructure, not dashboard-specific.
- **Backend API untouched** — runtime `src/` is byte-identical to `main`; the console consumes the same cloud routes the old pages did (`/walkforward`, `/attribution`, `/packets`, …). Only the old *frontend* was retired.
- **`tests/test_repo_structure.py::test_dashboard_routes_have_pages`** updated to validate `/console` route resolution and exclude the `Navigate` redirect built-in; the `./pages/` guard re-arms automatically if a page is ever reintroduced.
- **Verified:** `vite build` clean (650 modules, zero missing imports), frontend suite **228 passing** (14 files), `test_repo_structure.py` **27 passing**. Browser-verified `/`→`/console/now` and legacy `/shadow`→`/console/now` redirects; NOW/DECIDE/KNOW all render with **0 console errors**. (Two pre-existing backend 500s — `/api/console/pause`, `/api/console/now/gate` — are unrelated to this frontend-only change [`src/` unchanged] and render as honest `DEGRADED`/`UNKNOWN` states; noted as a separate local-env data follow-up.)

### Added — Founder Console KNOW analytics completion (DSR + dev-team scorecard instrumentation + PSR/DSR/PBO rigor)

Closes the honest "unavailable" / "not yet instrumented" gaps the KNOW region shipped with — building the real data paths (or honest no-data scaffolds where the data genuinely doesn't exist yet). No rewrite; augments existing modules.

- **DSR in the track record** — `/console/know/track-record` now computes the Deflated Sharpe Ratio: `n_trials = SUM(n_params_searched)` from `trials_registry` (Bailey-López de Prado — counts every parameter combination, *not* `COUNT(*)`), wrapping the existing `src/methods/psr.py::dsr`. `dsr` removed from `unavailable` and rendered as a real headline tile (honest `no_data` when `n_trials<1` or <5 trades). Metric-envelope helpers extracted to `src/api/cloud_routes/console_know_metrics.py`.
- **AI dev-team scorecard instrumentation (genuinely new)** — a `agent_task_outcomes` table (registry; `sync_to_postgres=True`, WIPE-classified, count-pin 83→84), `src/console/agent_outcomes.py` (`record_agent_outcome` + `get_agent_scorecards` + a `python -m src.console.agent_outcomes record …` CLI), and an "Outcome Instrumentation" hook added to the `arcis:code` skill so the PM records per-task/per-review outcomes. `GET /console/know/scorecards` + the frontend per-role / per-task-type / scope-drift panels replace the "not yet instrumented" placeholders. **Forward-looking by design**: the table starts empty (no historical backfill exists) and the UI honestly shows "no instrumented runs yet" until instrumented coding-team runs populate it — never fabricated.
- **PSR/DSR/PBO rigor metrics** — `src/console/rigor_metrics.py` builds an N-config × T-period returns matrix from `backtest_trades` (by config, aligned on trade-sequence index) and wraps `src/methods/pbo.py::pbo`; `GET /console/know/rigor-metrics` serves PSR/DSR/PBO as canonical envelopes, surfaced as tiles in the RigorStack Validation panel. **PBO honestly degrades to `insufficient_configs`** today (0 distinct backtested configs in the DB — CSCV needs ≥2 configs × ≥8 periods); the plumbing flips to a real value the moment a param-sweep persists configs. No fabricated PBO.
- **CI anti-drift / honesty:** every new metric is single-sourced (laws #1/#3/#4) — insufficient/empty data renders an explicit honest state, never a zero; new endpoints fail-closed to `unknown` on source error. Backend 167 + frontend 468 tests.

### Added — Founder Operating Console, Phase 3 KNOW · Wave B (salvage drill-downs — completes KNOW)

Second wave of the KNOW region: the analytics drill-downs salvaged into the console under overview→drill-down. All frontend — consumes existing backend routes (and the Wave-A `/console/know/calibration`) verbatim; no new backend, no new tables. The old `frontend/src/pages/*` originals are retained (salvage adapts the rendering). Completes the KNOW region.

- **Rigor stack (`frontend/src/console/know/RigorStack.jsx`)** — Validation / Walkforward (OOS windows) / Stress Test sub-views, consuming `/walkforward/runs(+windows/trades)`, `/stress-test/results`, `/system/validation`. (Dedicated PSR/DSR/PBO rigor metrics shown in track record; a per-metric rigor endpoint is a noted follow-up — the panel honestly shows the validation checks the endpoint provides.)
- **Attribution + calibration (`frontend/src/console/know/AttributionView.jsx`)** — alpha vs SPY-beta + strategy/pipeline/LLM breakdown (`/attribution/stats`, `/shadow/sharpe-attribution`), plus the **outcome-tagged calibration view** ("do high-conviction theses win?") consuming the Wave-A `/console/know/calibration`; `no_data` renders an explicit "no joined outcomes yet" message (never a fabricated 0% win rate); `join_source`/`state` surfaced.
- **Research & calibration corpus (`frontend/src/console/know/ResearchView.jsx`)** — searchable thesis/packet/notes corpus (`/packets`, `/notes`), the weekly "what we learned" digest (`/research/digest`, honest "not yet synthesized" empty state) + papers (`/research/papers`), and the **AI Council demoted to a panel** (§5: panel inside KNOW, not its own page) (`/council/latest`, `/council/history`).
- **AI dev-team scorecards (`frontend/src/console/know/ScorecardsView.jsx`)** — per-model-version win-rate/profit-factor/Sharpe (`/model-performance`), training version history (`/training/versions`), and the dev-activity feed (`/activity/feed`). Per-role (Planner/Developer/Reviewer) and scope-drift/trajectory signals render an explicit **"not yet instrumented"** state (the `activity_log` carries no agent-role column yet) — never fabricated, flagged as a future instrumentation task.

Every displayed number flows through the render-boundary primitives; honest no-data/empty states throughout (no_data ≠ zero). With KNOW complete, the new `/console` (NOW + DECIDE + KNOW) reaches feature parity with the old 28-page dashboard, which can now be retired in a separate step.

### Added — Founder Operating Console, Phase 3 KNOW · Wave A (derived views + pinned analytics)

First wave of the KNOW region (legibility + analytics; spec §3.3) — the new **derive-from-source** engineering (law #7) plus the operator's daily-reliance pins. Builds on the Phase-1 metric registry + render-boundary primitives + console shell; the old dashboard stays untouched (salvage = adapt into the console, originals retained). No new tables.

- **Fund-ladder derivation (`src/console/fund_ladder.py`)** — Phase 1→6 ladder **derived** from trades + versions (replaces the hand-maintained Roadmap that drifted). Live gate progress computed via the metric registry; fail-closed (`generation_ok: false` + per-gate `unknown` on source failure, never a silently stale snapshot); git-SHA-stamped; future phases render `pending` (distinct from zero).
- **System-map derivation (`src/console/system_map.py`)** — architecture/capability/schema summary **derived** from the capability registry (`ensure_bootstrapped` + `list_actions/states/systems/decisions`) and `src/schema/registry.TABLES` — counts computed, never typed; fail-closed per section; SHA-stamped.
- **CI anti-drift guards (`tests/test_console_derived_drift.py`)** — oracle-derived, merge-blocking (generalize the #88 capability-registry guard): system-map table/capability counts must equal the live registries; fund-ladder gate ids must exist in `gate_targets` ∩ the metric registry; both must fail closed. Makes "CI-asserted against source" (law #7) real.
- **`console_know` router (`src/api/cloud_routes/console_know.py`)** — `/api/console/know/{ladder, system-map, track-record, ledgers, calibration}`. Track-record headline stats (Sharpe, excess-Sharpe vs SPY, PSR, win rate, profit factor, max DD, expectancy, closed-trade count) single-sourced via the metric registry / existing pure helpers (DSR honestly listed `unavailable` — needs an `n_trials` source, not computed ad-hoc); calibration reuses the existing `cto_report._compute_confidence_calibration` (recommendation→trade→P&L join), fail-closed to `no_data` (empty buckets, never zeros).
- **KNOW region frontend (`frontend/src/console/know/`)** — overview→drill-down shell (law #6; replaces the placeholder tab), the fund-ladder + system-map drill-downs (fail-closed UI: a `generation_ok: false` payload renders a visible "generation failed / stale as of `<sha>`" banner, never fabricated numbers), and the pinned **track record** (CTO synthesis + equity curve, salvaged `BacktestEquityChart`) + **trade ledgers** (open/closed/all, searchable, salvaged `ShadowLedger`/`TradeHistory`). Every number through the render-boundary primitives.

Wave B (rigor stack, attribution + calibration view, research corpus + AI-Council panel, AI-dev scorecards — mostly frontend salvage against existing routes) is a follow-up run.

### Fixed

- **`test_connect_db_complete_coverage` allowlist drift** — the `sqlite3.connect` guardrail allowlist was line-pinned `(file, line_no)` and had drifted RED on `main`: `watch.py`'s backup pair shifted (1671/1672→1715/1716, Phase-1 PAUSE gate), `tradingstate` shifted (176→190, #134), and `scripts/_clean_slate/sqlite_retire.py` (#95, 3 legit sites) was never added. Converted the allowlist to **content-keyed `(file, snippet)`** matching so unrelated edits no longer drift it, re-covered all 33 current legitimate sites, and added `test_no_dead_allowlist_entries` to stop the allowlist rotting (how the old `engine_helpers.py:61` entry went dead). Verified by mutation: drift-proof (line shifts still pass) and still catches new raw-connect violations.

### Added — Founder Operating Console, Phase 2 (DECIDE region)

Second phase of the founder operating console: the **DECIDE** region — the human-on-the-loop veto queue (spec §3.2). Builds on the Phase-1 metric registry + render-boundary primitives + console shell; the old dashboard stays untouched.

- **Decision-queue service (`src/console/decisions.py`)** — the §8 unified pending-gate feed, aggregated live from **real** sources: strategy promotions (`strategy_promotion_events` gate proposals + evidence), capital-advance gate (derived from the Phase-1 `/now/gate` metrics-vs-targets), auditor halts (`audit_reports` recommendations, distinct from the header PAUSE). Model-challenger and AI-dev-team merge-asks have **no queryable pending store** and degrade explicitly (`source_state="degraded"`, zero items, named in `degraded_sources`) — never fabricated. Plus `record_decision` (audit-logged verdict), the "recently decided" trail, and an honest `override_rate` (null when no decisions — "an approver who never overrides has stopped reviewing").
- **LLM-authority boundary (law #8 / FINSABER):** decisions **record the human verdict + audit-log only** — nothing here auto-executes or touches live money; `AUTO_RUN_TIERS={'low'}` is defined but no auto-run is wired (wiring a verdict into an actual promotion/execution pipeline is explicitly a later phase). Medium/high route to the human.
- **DECIDE endpoints (`src/api/cloud_routes/console_decide.py`)** — `GET /api/console/decide/pending`, `POST /api/console/decide/action` (approve/reject/defer; 409 on a duplicate verdict, 422 on invalid action/tier), `GET /api/console/decide/decided` (trail + override-rate envelope).
- **DECIDE frontend (`frontend/src/console/decide/`)** — challenge-and-response cards (evidence-that-cleared-the-gate → Intent · Blast-radius · Rollback → Approve/Reject/Defer + drill-in), risk-tiered (high→medium→low), an honest degraded-source banner, and the recently-decided trail + override-rate. Wired into the ConsoleShell DECIDE tab (replacing the Phase-1 placeholder). Every number flows through the render-boundary primitives.
- **Single-source pending count (law #1):** Phase-1's `/now/attention` now reads the **same** decision-queue service, so NOW's "N decisions waiting" chip equals the DECIDE queue length (closes the Phase-1 parity gap). Gate targets consolidated into `src/console/gate_targets.py` (one definition for `/now/gate` and the capital-advance source).

### Changed

- `src/schema/registry.py` — `console_decisions` table (decided-outcome trail; `sync_to_postgres=True`); pending feed is aggregated live, not stored.
- `scripts/_clean_slate/classification.py` — `console_decisions` classified WIPE; `EXPECTED_REGISTRY_COUNT` 82→83.

### Added — Founder Operating Console, Phase 1 (backend foundation + NOW region)

First phase of the founder operating console (spec: `docs/superpowers/specs/2026-06-04-founder-console-design.md`). Stands up a new `/console` region **alongside** the existing dashboard (the old `frontend/` pages are untouched; cutover is region-by-region at parity). Phase-0 prerequisites #134/#135 landed first (PR #1200).

- **Metric registry (`src/metrics/`)** — server-side single-source metric layer (design law #1). `MetricDef` + duplicate-rejecting `register()` + `compute_metric`/`compute_all` returning a canonical envelope `{value, n, as_of, cohort, unit, state}`; sentinels (999/NaN/-1/∞) and missing data surface as a `state` flag, never as a raw value (laws #2/#3). Wraps the existing `kpis_compute` math (no re-derivation) and registers the gate metrics (closed-trade count, excess-Sharpe vs SPY, Sharpe t-stat, max drawdown).
- **Reconciliation break-event retention** — `reconciliation_breaks` table + `src/shadow_trading/break_events.py` (`record_break`/`get_break_events`), emitted at the reconciler's detection points **before** auto-backfill erases the evidence, so the console surfaces the break-*rate* over time, not post-backfill state (law #9).
- **Graceful global PAUSE** — `src/console/pause.py` (`console_pause_state` table) + `GET`/`POST /api/console/pause`. Blocks new autonomous actions at the watch-loop scan gate (`watch.py:_run_scan`) and the executor new-trade entry while keeping positions/monitoring/reconciliation running; audit-logged; distinct from the governor hard-kill. `is_paused()` **fails closed** on a DB read error (operator decision 2026-06-05) so a paused desk never silently resumes.
- **NOW-region + honest-header endpoints (`src/api/cloud_routes/console_now.py`)** — `/api/console/header` (version + PAPER/bootcamp-OFF from config, market state, clock — never narrated); `/now/gate`, `/now/signals` (heartbeat/data-feed/reconciliation/risk-limits, each with `as_of`, alarmed/unknown on absence — never green on missing, law #4), `/now/positions` (canonical TradingState source), `/now/attention` (pending-decision count + desk-healthy), `/now/since`, `/now/devteam`.
- **Frontend render-boundary primitives (`frontend/src/console/components/`)** — `<Metric>` (requires cohort/N/as-of or errors), `<SentinelGuard>` (true-0 distinct from no-data), `<StalenessBadge>` (degrades; never green on missing) — honesty enforced structurally (§8).
- **Console shell + NOW region (`frontend/src/console/`)** — new `/console` route subtree (Now/Decide/Know nav; Decide/Know are placeholders this phase), `HonestHeader` carrying the global PAUSE control, and the assembled NOW region (gate hero, two-tier attention row, integrity-signal row, positions, "since you last looked" delta band, AI dev-team strip) — every number rendered through the honesty primitives.

### Changed

- `scripts/_clean_slate/classification.py` — classified the two new console tables into the clean-slate WIPE partition (per-run runtime state); `EXPECTED_REGISTRY_COUNT` 80→82, WIPE 53→55.
- `src/schema/registry.py` — `reconciliation_breaks` + `console_pause_state` registered with `sync_to_postgres=True` so they exist in the canonical PG book the console + watch-loop read.

## [v0.36.85] — 2026-06-03 — W21 capstone: clean-slate-wipe script + full test suite (#95)

Built (but did NOT run) the W21 capstone: a destructive, **dry-run-by-default**,
ProdGuard-gated, backup-first prod clean-slate-wipe script that resets the platform
to a proven-sound stable release. EXECUTION stays operator-gated (the script never
runs a real wipe in this PR — no `ARCIS_ALLOW_PROD_PG=1`, prod PG 5433 untouched).

### Added

- **`scripts/clean_slate_wipe.py`** — the capstone script. Decorated public entry
  point `clean_slate_wipe(*, dsn, confirm=False, ...)` with `@safe_op(mutates=True)`
  → `@prod_guard(dsn_param='dsn')` (NO `@safety_window` — the `market_hours` config
  key does not exist). Phase 0-7 orchestration: live-schema+FK reconciliation,
  broker-flat HARD gate, already-clean short-circuit, backup+verify-restore,
  single-transaction `TRUNCATE ... RESTART IDENTITY CASCADE` of the 53-table WIPE
  set (27 KEEP tables preserved), watch-loop re-check at the TRUNCATE boundary,
  fsync'd `WIPE_COMMITTED.marker`, SQLite archive-then-empty, DB + config
  post-verify, atomic `manifest.json`, operator banner + dotenv CLI.
- **`scripts/_clean_slate/`** — `classification.py` (reviewed WIPE/KEEP frozensets +
  `EXPECTED_FK_EDGES` + `assert_partition_complete()` pinning `len(registry.TABLES)==80`),
  `live_schema.py` (authoritative live reconciliation), `backup.py` (pg_dump +
  verify + fresh-ephemeral-DB restore-compare), `sqlite_retire.py`
  (archive-fsync-then-empty), `config_verify.py` (read-only config/Ollama assertion),
  `_errors.py` (CleanSlateAbort / BackupVerifyError).
- **`tests/scripts/test_clean_slate_*.py`** (6 files, 44 tests) — verify-by-mutation
  throughout: partition completeness + count-pin, live-schema/FK drift aborts,
  backup REFUSE/shortfall/excess/divergence paths + ephemeral-DB lifecycle,
  dry-run/ProdGuard/TRUNCATE/watch-loop-re-check/broker/already-clean/config-pending,
  interrupted-run forensic-marker safe re-entry, full E2E rehearsal against a 5434
  scratch DB. All DB tests use the 5434 test server + fresh ephemeral DBs; prod 5433
  is never touched.
- **`docs/runbooks/clean_slate_wipe.md`** — operator runbook + manifest schema.

### Fixed

- **Windows `fsync(O_RDONLY)` → EBADF portability bug** (`scripts/_clean_slate/sqlite_retire.py`).
  `os.fsync()` on a read-only descriptor raises `OSError [Errno 9] Bad file descriptor`
  on Windows; the archive-fsync now opens `O_RDWR` and tolerates a platform fsync
  failure (the bytes are already flushed by VACUUM INTO / copy2).

### Notes

- The live-schema FK reconciliation asserts the live wipe-touching FK set is a
  **subset** of the 6 modeled edges (no unexpected/CASCADE-reachable edge), rather
  than requiring physical presence: `src.schema.postgres.create_all_tables` (the prod
  provisioning path) does NOT emit FK constraints, so a faithfully-provisioned prod PG
  has zero of the 6 edges physically present. A *missing* modeled edge is not a CASCADE
  hazard (fewer edges => CASCADE reaches strictly less); only an *unexpected* edge aborts.

## [v0.36.84] — 2026-06-02 — Sim-gate honesty pass + 3 PG-cutover orphan-source fixes (#132)

Certified the lifecycle simulator's clean-close OCO path (was XFAILED). Driving the
real `check_and_manage_open_trades` against a real PG surfaced **three genuine
production regressions** in the trade-close path — all the same root cause: psycopg2's
`RealDictCursor` returns timestamp columns as native `datetime` objects (the
`connect_db` PG shim restored SQLite's *access* shape but not its *string-typed value*
contract), so SQLite-era string operations on those fields break. The full lifecycle
gate (`run_full_gate()`) now returns **STABLE**, unblocking the #95 capstone gate.

### Fixed

- **Postmortem datetime crash → orphan source (#132)** (`src/evaluation/postmortem.py`).
  `generate_postmortem` sliced `actual_entry_time[:10]` to extract the date; on a
  PG-native datetime this raised `'datetime.datetime' object is not subscriptable`,
  aborting `check_and_manage_open_trades` mid-close → the broker position stayed open
  ("close-didn't-clear" → orphan). Now `str()`-coerces before slicing.
- **days_open phantom-timeout → orphan source (#132)** (`src/shadow_trading/order_lifecycle.py`).
  `datetime.fromisoformat(actual_entry_time)` raised `TypeError` on a PG-native datetime
  and defaulted `days_open=999`, force-closing every PG-read trade as a phantom
  `timeout` on the first manage cycle (DB-closed / broker-open split). Now handles a
  native datetime directly and normalizes naive timestamps to ET.
- **SPY-benchmark `.replace` crash silently disabled attribution (#132)**
  (`src/analytics/spy_benchmark.py`). `entry_iso.replace("Z", "+00:00")` on a datetime
  invoked `datetime.replace(year="Z", …)` → `'str' object cannot be interpreted as an
  integer`; fail-open returned `None`, disabling SPY attribution on every closed trade.
  New `_iso_to_date` helper accepts datetime/date/string.
- **Reconcile/close sibling sites — same anti-pattern, surfaced by dual-Opus QA's
  sibling search (#132)**. The reviewers grepped the close/reconcile path for the same
  bug and found three more:
  - `src/shadow_trading/reconcile.py` — the "skip trades < 1 h old" safety guard did
    `datetime.fromisoformat(created_at)` inline → `TypeError` on a PG datetime →
    `except: pass` → the guard was **silently defeated under PG**, so a freshly-opened
    trade could be force-closed `reconciled_stale` on a transient Alpaca blip (an
    orphan-adjacent path). Extracted to a tested `_raw_ts_within_seconds` helper
    (datetime/string/naive-aware). **Important.**
  - `src/shadow_trading/reconcile.py` (days-held) and `src/journal/store.py`
    (`time_to_target_days`) — same datetime-vs-string pattern, silently dropping a
    data-quality field under PG. Both hardened. (Cosmetic.)

### Changed

- **Lifecycle harness neutral-price fix (#132)** (`src/simulation/lifecycle/wiring.py`).
  The sim pinned `_get_current_price_safe` to a flat `100.0` (fake_md `base_price`), which
  sits below the drifted rec band's stop and tripped a spurious stop-out before the OCO
  fill. Now returns the midpoint of the open bracket's held legs (always strictly inside
  `(stop, target)`), so the OCO `fill_leg` is the sole exit. Also patches
  `spy_return_over_range → None` in the sim so the gate stays network-free.
- **Clean-close keystone test un-XFAILED + exit_reason set corrected to canonical vocab**
  (`tests/simulation/lifecycle/test_scenario.py`). Stale gate disclosures updated
  (`verdict.py`, `simulation/lifecycle/__init__.py`).

### Follow-ups filed

- Systemic audit of all `connect_db`-over-PG readers for string-ops-on-datetime/Decimal
  (the three fixed sites are unlikely to be the only ones); consider type-coercion at the
  `CompatRow`/`_RowFactoryCursor` shim layer (foundation-class, own PR + dual-Opus QA).

## [v0.36.83] — 2026-06-02 — Cleanup-2: drawdown 30-day window (#51) + dangling-FK root-cause (#77)

The last two Phase-4 hotfix-backlog items.

### Fixed

- **Drawdown circuit-breaker now evaluates a 30-day rolling window (#51)**
  (`src/evaluation/auditor.py`). The deterministic drawdown check (`_check_drawdown`)
  was fed the `days=1` audit snapshot, but its `_DRAWDOWN_MIN_SAMPLE = 50` guard is
  unreachable in a single day's closes — so the CRITICAL drawdown flag effectively
  never fired (an inert safety net). `_collect_deterministic_precheck_flags` now
  generates a `days=30` `cto_report` for the drawdown check specifically (the audit
  `cto_data` stays `days=1` for the LLM narrative + today's-trade checks).
  Verify-by-mutation integration test added.

### Investigated / documented

- **Dangling-FK root cause (#77) — sim-artifact data, not a rec-flow bug; closed.**
  The 18 `rejected_buying_power` shadow_trades whose `recommendation_id`s are absent
  from `recommendations` all carry the synthetic placeholder id `rec-4` (ticker NVDA),
  dated 5/27–5/28 — simulator/test rows that leaked into prod `shadow_trades` during
  the green-gate testing window, NOT real rejected trades referencing pruned/missing
  recommendations (real recs are UUIDs; `recommendations` is not pruned). The genuine
  dangling-FK signal is 0; v0.36.41's validator exclusion already handles them; no
  recurrence since sim was isolated to the 5434 test PG. The 18 cosmetic rows are left
  in place (validator-excluded); root cause recorded, task closed.

## [v0.36.82] — 2026-06-02 — Forward-fix: PG self-heal must skip non-owned tables, not halt (#129)

v0.36.81's PG self-heal crash-looped the watch loop on startup against the live
**split-ownership** prod schema (#92). Restarting onto v0.36.81 (pre-market
2026-06-02) was the first real restart since the hotfix merged, and it exposed a
latent fatal bug: `create_all_tables` issues `ALTER` / `CREATE INDEX` on tables
owned by role `halcyon` (e.g. `recommendations`), which `halcyon_app` cannot
modify → `psycopg2.errors.InsufficientPrivilege: must be owner of table …` →
the existing fatal `[WATCH] SCHEMA CREATION FAILED … cannot continue` → `sys.exit(1)`
→ NSSM relaunch every ~60–90 s, heartbeat frozen. Deployed code was rolled back
to v0.36.80 to restore service; this release is the forward-fix.

### Fixed

- **Watch-loop PG self-heal no longer halts on benign cross-role ownership**
  (`src/scheduler/watch.py` `_ensure_all_tables`). The Postgres self-heal call now
  catches `psycopg2.errors.InsufficientPrivilege` and **skips** it (logged as
  "tables owned by another role skipped (expected)") — mirroring
  `src/startup_checks.py:337`. Phase-1 `CREATE TABLE IF NOT EXISTS` already
  commits first, so the self-heal still provisions any genuinely-missing table
  (its purpose); only the no-op `ALTER`/`INDEX` on owner-managed tables is skipped.
  A genuinely-unreachable PG still raises `OperationalError`, which keeps the
  fail-fast fatal contract (the watch loop cannot run without its sole write target).
  Verify-by-mutation test added in `tests/scheduler/test_watch_schema_ensure.py`.

## [v0.36.81] — 2026-06-02 — Watch-loop startup schema-ensure is Postgres-aware (PG self-heal)

Makes the watch loop's startup schema-ensure self-heal the **Postgres** registry
schema after a wipe, closing the post-cutover drift class that put the live loop
in a ~66s ERROR loop on 2026-06-02 (`notifications_digest_queue` +
`notifications_sent` absent on the prod PG, fixed manually at the time).

### Fixed

- **Watch-loop PG schema self-heal** (`src/scheduler/watch.py`,
  `WatchLoop._ensure_all_tables`): post-cutover the loop runs against PG 5433
  (`DATABASE_URL` set), but the startup ensure called **only** the SQLite path
  (`src.schema.sqlite.create_all_tables(DB_PATH)`), so the PG schema was never
  registry-synced by the running system — after the post-#124 prod wipe it
  drifted and the loop errored continuously. The ensure now mirrors
  `connect_db`'s PG-mode predicate (a postgres-scheme `DATABASE_URL`) and, before
  the existing SQLite ensure, idempotently ensures the registry schema on PG via
  `src.schema.postgres.create_all_tables(..., connect_timeout=5,
  lock_timeout_ms=10000)`. The PG ensure runs inside the **same** `try/except` as
  the SQLite ensure, so a PG-ensure failure follows the existing fatal contract
  (critical log + Telegram + `sys.exit(1)` → NSSM restart-retry); the fast
  connect/lock timeouts make a down/locked PG fail fast rather than hang the
  loop. The SQLite ensure, `ensure_columns`, docs population, and the halt block
  are unchanged.

### Tests

- `tests/scheduler/test_watch_schema_ensure.py`: verify-by-mutation against the
  5434 **test** PG — drops `notifications_digest_queue`, runs
  `_ensure_all_tables()` with `DATABASE_URL` pointed at 5434, and asserts the
  table is re-created. Reverting the fix leaves the table dropped (assertion
  fails), proving the test bites. Guards on `:5434` and skips when
  `TEST_DATABASE_URL` is unset so it never touches prod 5433.

## [v0.36.80] — 2026-06-02 — HealthProbe/TradingState timezone + heartbeat-path hotfix

Fixes three timezone/path defects in the observability tools (`healthprobe` + `tradingstate`)
that made HealthProbe **under-report**, surfaced by a live health check on 2026-06-02 (the
probe reported "0 recent errors" + "DEGRADED" while the system was actually healthy with a
live error loop firing every ~66s).

### Fixed

- **HealthProbe error-recency timezone** (`src/tools/healthprobe/checks.py`): `arcis.log`
  timestamps are ET wall-clock (naive) but were tagged `timezone.utc` before the 15-minute
  window comparison. During EDT (UTC−4) every real entry landed ~4h outside the window, so
  `recent_error_count` always reported 0 even while errors fired continuously. The parsed
  timestamps are now interpreted in `America/New_York`. The benign tz-aware heartbeat path
  (`data/watchdog.txt`, written with a `-04:00` offset) is unchanged.
- **HealthProbe heartbeat sources** (`src/tools/healthprobe/core.py`): `ArcisDashboard` and
  `ArcisOllamaWatchdog` pointed `_HEARTBEAT_SOURCES` at `logs/dashboard-stdout.log` and
  `logs/ollama_watchdog.out.log`, neither of which exists → false `STALE(file_missing)` →
  false `DEGRADED` for two healthy services. There is no dashboard heartbeat file, and the
  only ollama-watchdog log is written event-only (mtime days-stale when healthy), so neither
  is a valid freshness source. Both services now rely on their existing port-listening
  liveness probe; only `ArcisWatchLoop` retains a genuine ISO heartbeat. Error-recency
  scanning is likewise scoped to `arcis.log` (the only real log target).
- **TradingState audit-freshness timezone** (`src/tools/tradingstate/core.py`):
  `audit_reports.created_at` is written by the auditor as `datetime.now(America/New_York)`
  (registry type TEXT, tz-aware ISO in normal operation). When a **naive** value reaches the
  staleness check (a naive `timestamp` column or an offset-less ISO string), it was tagged
  `timezone.utc`, inflating the age ~4h during EDT and reporting a fresh governor verdict as
  `stale=True` (ties to the two-layer-staleness false-halt class). Naive values are now
  interpreted in `America/New_York`; the tz-aware path and the corrupt-string fail-loud path
  are unchanged.

### Tests

- `tests/tools/test_healthprobe_integration.py`: added `TestRecentErrorTimezone` (ET-local
  error 5 min ago counts; 30 min ago does not) and rewrote `TestHeartbeatFilenameMapping` to
  assert Dashboard/Ollama use port liveness (heartbeat `None`) with no stdout files present,
  and that a down port still yields DEGRADED.
- `tests/tools/test_tradingstate_integration.py`: added `TestAuditCreatedAtTimezone`
  (naive-ET datetime + naive-ET ISO string near the 36h boundary stay fresh; genuinely-old
  stays stale; tz-aware path unaffected).
- Each fix carries a verify-by-mutation case proven to fail on the pre-fix code.

## [v0.36.79] — 2026-06-01 — Test-determinism + isolation cleanup (task 128)

Test-determinism + isolation cleanup per `docs/audits/2026-05-30-test-determinism/plan.md`.
Fixes the cataloged root causes of the suite's time- and order-dependent flakes and keeps
the full suite deterministic by default. Net effect vs `origin/main` in the fixed-order
full-suite baseline: 25 failed / 7 errors → the determinism fixtures resolve ~22 of those
plus all 7 errors.

### Fixed

- **Deterministic policy-clock seam** (T1): `src/notifications/policy.py` gains an
  injectable `_now_et_provider` hook (module stays import-pure); an autouse conftest
  fixture pins the policy/telegram/telegram_commands clocks to a fixed daytime instant,
  with an opt-in `freeze_quiet_hours` fixture for the digest path. De-flakes the
  quiet-hours alert tests.
- **Registry-driven digest-queue provisioning** (T2): the notifications test fixtures
  provision `notifications_digest_queue` from the schema registry so the quiet-hours
  digest path is exercised deterministically.
- **Class-A day/time de-flake** (T4): clock seam extended to
  `src/notifications/telegram_commands.py` (Sunday-review reminders) + now-relative seeds
  in the attribution resolver test.
- **Lifecycle env-scrub relocation** (T5): `src/simulation/lifecycle/bootstrap.py` no
  longer scrubs `os.environ` as an import side-effect; the scrub now runs inside a
  self-restoring `scoped_scrub()` wrapped by `run_smoke`/`run_full_gate`. Fixes the
  `connect_db(None)` TypeError AND a collection-poisoning that crashed `src.training.*`
  imports under certain orderings.
- **Class-C order-isolation** (T6): conftest autouse fixtures restore reimport-prone
  `src.training.*` module identity and clear the `/api/cto-report` memo between tests;
  subprocess env-scrub in the pg-guard collect helper; now-relative dashboard seeds.
  Five of the six cataloged Class-C tests are un-skipped and proven order-robust by a
  scoped ≥3-seed randomized proof.

### Changed

- **Test order deterministic by default**: `pytest.ini` sets `addopts = -p no:randomly`.
  `pytest-randomly` (pin bumped to `<5.0`) + `pytest-forked` stay installed for opt-in
  scoped order-robustness proofs (`-o addopts= --randomly-seed=N`).

### Notes

- The lifecycle smoke-tier `run_smoke` tests and one Class-C test
  (`test_self_blinding::test_stage2`) remain skipped: they hit a pre-existing
  organic-scenario / full-suite state-leak tail (including a `PYTHONHASHSEED`-sensitive
  axis) that is out of scope for the determinism sprint. Tracked for a follow-up kin.

## [v0.36.78] — 2026-05-29 — Phase 5: codebase + docs consolidation

Phase 5 unified-design campaign (`docs/audits/2026-05-27-phase-5-unified/`):
codebase + docs consolidation across PR-A … PR-F. Entries are grouped by PR
below; the per-PR `<!-- PR-X entries -->` conflict-avoidance markers (DD-37)
were unified into this single versioned block by PR-F T33. Tag cut by the
coordinator at T39 (versioning-policy.md §3).

### PR-A — boundary-touch standards + repo-root structure rules

#### Added

- **Phase 5 PR-A — boundary-touch standards + PR template** (`chore(phase-5/pr-a)`):

- **Phase 5 PR-A — boundary-touch standards + PR template** (`chore(phase-5/pr-a)`):
  Created `.github/PULL_REQUEST_TEMPLATE.md` (none existed previously) carrying
  the 6-item boundary-touch self-check verbatim per master-spec §6.5, cross-
  linked to the canonical `docs/standards/boundary-touch-tests.md`. The
  standards doc itself was already authoritative as of v0.36.59 (#103); this
  PR completes DD-39 by closing the template-side gap so every reviewer sees
  the checklist on every PR.
- **Phase 5 PR-A — two new repo-root structure rules** in
  `tests/test_repo_structure.py`:
  - `test_no_underscore_scratch_at_repo_root` — forbids `_*.py` REPL scratch
    at repo root (excludes `__init__.py` / `__main__.py`).
  - `test_no_sqlite_at_repo_root` — forbids `*.sqlite` / `*.sqlite3` /
    `*.sqlite-journal` / `*.db` at repo root; runtime DB lives at
    `C:/arcis/data/ai_research_desk.sqlite3` per `CLAUDE.md:26`.
  Both rules paired with `tmp_path`-anchored sentinel tests
  (`test_repo_root_underscore_scratch_rule_detects_violation` /
  `..._sqlite_rule_detects_violation`) that prove non-vacuousness without
  writing to the real repo root.

#### Removed

- 17 `_*.py` REPL-scratch files at repo root: `_a.py`, `_audit.py`,
  `_ck.py`, `_f.py`, `_p.py`, `_q.py`, `_t1.py`, `_t1b.py`, `_t1c.py`,
  `_t1d.py`, `_t1e.py`, `_t1e0.py`, `_t1f.py`, `_t1h.py`, `_t1i.py`,
  `_t1i2.py`, `_v.py` (all gitignored via `/_*.py`, 32 days stale, no
  in-repo consumers).
- `_582_operator_action.sql` — historical one-shot for #582 (long-closed),
  gitignored via `/_*.sql`.
- `--db-path` (0-byte git-tracked CLI typo artifact whose filename is the
  literal `--db-path` flag).
- `ai_research_desk.sqlite3` (0-byte) moved from repo root to
  `archive/sqlite-debris-2026-05-27/` — was a violation of `CLAUDE.md:26`;
  canonical runtime DB at `C:/arcis/data/ai_research_desk.sqlite3` (566 MB,
  82 tables) is untouched.

### PR-B — Render decommission + cloud_routes SQLite-only

#### Added

- 2 regression-lock sentinels at `tests/` root (T8 commit `7d708598`):
  - `tests/test_cloud_app_removed.py` — locks `src/api/cloud_app.py` deletion;
    follows canonical `tests/test_render_sync_removed.py` shape with
    verify-by-mutation evidence (sabotage cycle documented in T8 commit body).
  - `tests/test_no_database_url_branch.py` — locks DATABASE_URL strip from all
    `cloud_routes/` modules; same verify-by-mutation shape.
- 9 SQLite-only routing verification tests added during T6/T7 dependent-test
  expansion (each carries verify-by-mutation docstring per memory
  `feedback_vacuous_test_pattern`):
  - `tests/api/test_broker_exceptions_route.py::TestPostgresRouting` (T6):
    `test_recent_uses_sqlite_regardless_of_database_url`,
    `test_summary_uses_sqlite_regardless_of_database_url`,
    `test_recent_uses_sqlite_when_database_url_unset`,
    `test_summary_uses_sqlite_when_database_url_unset`
  - `tests/api/test_commands_route.py` (T6):
    `test_expire_stale_calls_helper_unconditionally`
  - `tests/api/test_kpis.py::TestFetchClosedTradesPostgresRouting` (T6):
    `test_uses_sqlite_regardless_of_database_url`,
    `test_get_kpis_uses_sqlite_data`
  - `tests/api/test_preflight_route.py::TestSQLiteOnlyRouting` (T7):
    `test_sqlite_is_sole_path_regardless_of_database_url_env`,
    `test_empty_state_when_no_transcript`

#### Changed

- `src/api/cloud_routes/` modules now SQLite-only (no `DATABASE_URL` gating).
  7 modules + `__init__.py` updated across two batches:
  - T6 batch 1 (commit `2abe0fcb`): `platform.py`, `broker_exceptions.py`,
    `commands.py`, `kpis_compute.py`
  - T7 batch 2 (commit `bdde5cf9`): `notifications.py`, `preflight.py`,
    `walkforward.py` + `__init__.py` docstring updated to reflect single-mode
    SQLite routing
- 7 tier-2 test files redirected from `src.api.cloud_app` to `src.api.app`
  (T4c commit `fa95d4a7`): `tests/test_version.py` (2 dedicated cloud_app
  test fns dropped), `tests/test_security.py`,
  `tests/platform/test_platform_api.py`,
  `tests/test_dashboard_gate_kpi_route.py`,
  `tests/test_phase_d_auth_and_safety.py`,
  `tests/test_safety_oneliners.py`,
  `tests/test_tier_1c_orphan_routes.py`
- `scripts/render_architecture_doc.py` line 120 `route_files` list — dropped
  `cloud_app.py` entry (T4c commit `fa95d4a7`)

#### Removed

- `src/api/cloud_app.py` — standalone Render FastAPI entry point (T4 commit
  `b7984155`)
- `render.yaml` — Render deployment manifest (T4 commit `b7984155`)
- `requirements-cloud.txt` — Render-specific dependency list (T4 commit
  `b7984155`)
- `scripts/render_init_db.py` — Render DB-init helper (T4 commit `b7984155`)
- 4 dedicated cloud_app test files (T4b commit `c2f7c4de`, 1924 lines removed):
  `tests/test_cloud_app.py` (1186L), `tests/test_cloud_auth.py` (77L),
  `tests/test_cloud_requirements_imports.py` (624L),
  `tests/test_capability_registry_imports.py` (37L)
- `scripts/check_cloud_deploy_imports.py` — cloud_app import-graph validator
  (T4b commit `c2f7c4de`, 309L)
- `test_cloud_app_imports_covered_by_requirements_cloud` function from
  `tests/test_repo_structure.py` (T4b commit `c2f7c4de`; ~50L)
- 2 tier-2 test files with heavy cloud_app-internal patches (T4d commit
  `b7c2d1ff`; kin #10 + #11 filed for rewrites):
  `tests/api/test_status.py` (400L), `tests/test_shadow_desk_filter.py` (294L)

#### Skipped (deferred — kin #13)

- T5: deletion of `scripts/render_to_local_migrate.py` deferred to a dedicated
  follow-up PR. Script houses load-bearing `apply_ownership_reconciliation`
  function (the 2026-05-14 restart-loop incident fix; see memory
  `feedback_drop_schema_grant_pattern`). Proper migration requires moving the
  function to `scripts/_shared_migration_utils.py` first; kin task #13 tracks
  the dedicated PR.

### PR-C — structure-debt refactor (#65): 7 oversized modules split

#### Changed

- **Structure-debt refactor (#65)** — 7 oversized modules split, all behavior-preserving
  (public APIs re-exported at original import paths):
  - `src/shadow_trading/executor.py` 3093→1231L — extracted `order_lifecycle.py` (1640L,
    check_and_manage_open_trades + open_live_trade + _retry_exit) + `reconciliation_engine.py`
    (405L, reconciliation primitives) [T10 commit `cbc3149c`; DD-37 §3]
  - `src/training/trainer.py` 1463→1339L — extracted `trainer_checkpoint.py` (235L, 6
    GPU0-launch / checkpoint-stop / PID-tracking helpers: _training_subprocess_env,
    _assert_gpu0_identity, _wait_for_training_proc, _write_training_pid,
    _resolve_tracked_pid, _launch_and_wait_training) [T12 commit `55b60eb8`; DD-37 §3]
  - `src/cli/commands.py` 1531→90L (pure re-export facade) — split by command domain into
    `commands_data.py` (523L, 17 data/shadow-trading/live-trading cmd_* fns) +
    `commands_training.py` (496L, 30 training/evaluation/model/council cmd_* fns) +
    `commands_ops.py` (546L, 14 system/config/startup/notifications cmd_* fns + 5 startup
    helpers) [T13 commit `3e23c885`, T13-fix commit `2665e8bc`; DD-40 corrected — false
    decorator/audit_log premise removed per kin #19]
  - `src/risk/governor.py` 949→931L — extracted `governor_audit.py` (83L,
    audit_entry_suppression_reason + _AUDIT_ENTRY_SUPPRESSION_LOOKBACK_HOURS);
    `src/api/routes/system.py` 723→370L — extracted `system_status.py` (455L, 13
    read-only dashboard-data endpoints) [T14 commit `d419a74d`; DD-37 §3]
  - `src/services/scan_service.py` 517→220L — extracted `_scan_service_impl.py` (473L,
    3 phase helpers: _phase_collect / _phase_score / _phase_persist per DA9) [T15 commit
    `75912347`; DD-37 §3]
  - `src/notifications/email_digest.py` 1236→354L — extracted `email_digest_render.py`
    (735L, render_digest orchestrator + 3 per-tier HTML builders + data collectors) +
    `email_digest_handover.py` (223L, handover-logic helpers); render_digest + preview_tier
    re-exported from email_digest.py [T16 commit `4627601c`; DD-08c / DA11]
  - `src/notifications/telegram.py` 1662→821L — extracted `telegram_delivery.py` (1128L,
    notify_* alert builders + 4 payload dataclasses + 14 email-tier stubs). Transport core +
    policy dispatcher + config validator stay in telegram.py so the session-autouse conftest
    null-router (telegram._send_single) is preserved with ZERO conftest change; moved notify_*
    use the late-binding `_tg.send_telegram`/`_tg._html_escape` seam. XSS source-AST-scan
    (tests/notifications/test_html_escape_siblings.py) relocated to telegram_delivery.py and
    proven non-vacuous (iterates the moved notify_* + catches an injected unescaped f-string).
    [T11 commit `1bdfb931`; DD-08c; operator Option-A test-retarget authorized — see kin #17]

#### Added

- `tests/cli/test_cli_split_integrity.py` — re-export import-identity sentinel (verifies
  `src.cli.commands.cmd_X IS src.cli.commands_<cat>.cmd_X` for all 61 exported commands)
  + `--help` dispatch smoke per sub-module (subprocess exit-0 + command present); non-
  vacuous verify-by-mutation documented in commit body [T13 commit `3e23c885`; DD-37]

### Removed (known_violations.json entries, files now under 400L)

- `scan_service.py` (517→220L), `src/api/routes/system.py` (723→370L),
  `src/cli/commands.py` (1531→90L), `src/notifications/email_digest.py` (1236→354L)
  — all dropped below the 400L threshold post-split; entries pruned from
  `config/known_violations.json` by their respective tasks (T13–T16)

#### Deferred (Phase-6 sub-targets)

- Files still >400L post-split, grandfathered in known_violations.json with sub-target
  notes: `order_lifecycle.py` (1640L — decompose check_and_manage_open_trades 771L +
  open_live_trade 409L), `email_digest_render.py` (735L — optional 4th collect module if
  it grows), `telegram_delivery.py` (1128L — split notify_* by category if it grows), and
  `executor.py` (1231L) / `telegram.py` (821L) / `governor.py` (931L) / `trainer.py`
  (1339L) whose residual bulk is large single functions (e.g. governor check_trade 267L)
  that need their own decomposition tasks. T11 (telegram split) LANDED in this PR (commit
  `1bdfb931`) — NOT deferred; kin #22 is therefore closed.

### PR-D — CollectorResult Big Bang (#72)

#### Changed

- **Phase 5 PR-D — CollectorResult Big Bang (#72)** — 21 data-collection collectors
  migrated from 8 heterogeneous dict shapes to the unified `CollectorResult` frozen
  dataclass (`src/data_collection/result.py`, DD-12/DD-13/DD-14/DD-15 r3). Migrated
  collectors (T18 + T20–T25):
  `macro`, `edgar` (collector), `options`, `options_metrics`, `analyst`,
  `filings_sentiment`, `insider`, `fed`, `press_releases`, `cboe`,
  `company_executive`, `docs`, `institutional_ownership`, `price_target`,
  `research`, `retention`, `short_interest`, `short_volume_finra`,
  `stock_financials`, `trends`, `vix`.
  (`edgar_historical` was NOT migrated — it is a doc-resolution helper, not a
  collector, per kin #24.)

- **CollectorResult contract** (`src/data_collection/result.py`):
  - Frozen dataclass with fields `collector_name`, `status` (`"ok" | "partial" |
    "failed"`), `primary_count`, `errors`, `metadata`.
  - Three classmethods: `ok_from_count(name, count, **metadata)`,
    `partial(name, count, errors, **metadata)`, `failed(name, errors)`.
  - `.is_healthy` property — `True` for `"ok"` or `"partial"`; `False` for
    `"failed"`. Health is expressed via `.is_healthy`, never via object truthiness
    (DD-15 r3: `CollectorResult` is always object-truthy, including when status is
    `"failed"`, to preserve `if result:` compat during the migration window).
  - `aggregate_results(name, results)` merges per-ticker results (Shape F /
    `press_releases`).

- **Consumers made dual-mode during migration window** — the following call sites
  accept both the old dict shape and `CollectorResult` until T19 flips `_safe_run`:
  `overnight._is_collector_error`, `_run_plan_gated_collector`,
  `fundamentals_refresh`, `research`/`retention` seams,
  `cli`/`api` `_collector_result_is_failed`.

- **T19 (NEXT, not this PR)** — `_safe_run` in `src/scheduler/watch.py` will be
  flipped to return `CollectorResult` directly, routing status to
  `_capability_health` (`ok` → `ok`, `partial` → `degraded`, `failed` → `down`).
  After T19 lands, `CLAUDE.md §207` "done-flag" pattern is:
  `result = self._safe_run(...); if result.is_healthy: self._done = True`.

### PR-E — test audit (#102): vacuous-test removal + boundary-touch suite

#### Removed

- **Phase 5 PR-E — test audit (#102)** — removed 2 empirically-confirmed vacuous
  tests (each proven by a PASSED-while-broken experiment in
  `docs/audits/2026-05-28-test-audit/pass-b-empirical.md` §4):
  - `tests/test_watch_strategy_gate.py::test_notify_gate_proposal_does_not_raise`
    — H4 "does-not-raise" over a log-only-stub SUT (`_notify_gate_proposal`); a
    no-op body satisfies the assertion, so it locked no regression. Sibling
    `test_notify_gate_proposal_helper_exists` retains symbol-presence coverage.
  - `tests/trading/test_ib_broker_helpers.py::test_handle_ib_error_does_not_raise`
    — H4 "does-not-raise" over a classify+log stub SUT (`handle_ib_error`).
    Sibling `test_ib_broker_helpers_module_imports` retains symbol-presence coverage.

#### Added

- **6-seam boundary-touch test suite (DD-19, +23 tests)** — boundary-complete
  coverage of the codebase's external seams per
  `docs/standards/boundary-touch-tests.md`. Each test drives both sides of the
  seam with real artifacts (no mocks at the seam) and is proven
  would-fail-if-impl-deleted:
  - DB — `tests/api/test_cloud_routes_db_seam.py` (real SQLite; `get_closed_shadow_trades` row shape + quarantine filter)
  - LLM — `tests/llm/test_ollama_shutdown_boundary.py` (real localhost HTTP server; `OllamaWatchdog._is_healthy` health tuple)
  - HTTP — `tests/safety/test_safe_op_http_boundary.py` (real `@safe_op` over real HTTP; dry-run short-circuit + error logging)
  - NSSM — `tests/scheduler/test_healthprobe_nssm_filenames.py` (real `ArcisConfig` path getters; `_service_verdict` matrix)
  - ripgrep — `tests/tools/test_symbolfind_ripgrep_boundary.py` (real `rg` subprocess + JSON parse)
  - Broker — `tests/trading/test_broker_adapter_boundary.py` (real dataclass field-shape locks + real `_verify_submitted` guard path)
- **Two-pass audit receipt** — `docs/audits/2026-05-28-test-audit/` (Pass A heuristic
  candidates, Pass B empirical DELETION_LIST, README overview). Net test count
  6,989 → 7,010 (SQLite floor 5,467 held).

### PR-E2 — suite green-gate (#102b)

#### Added

- **Phase 5 PR-E2 — suite green-gate sentinel (#102b, T43)** (`feat(green-gate)`):
  Added `tests/test_suite_integrity.py` (the T43 CI sentinel) plus enforcement
  hooks in `tests/conftest.py`. Policy (DD-42 §46): every test must PASS or carry
  a skip reason in an allowlisted category — `platform`, `optional-dep`,
  `engine-aware`, `tracked-upstream-bug (#N)`, or
  `integration(authoritative-coverage:<job>)`. Mechanism:
  - `pytest.ini`: `xfail_strict = true` — a stale xfail that XPASSes becomes a
    hard FAILURE.
  - `pytest_runtest_logreport` collects skips that ACTUALLY FIRED (excluding
    xfails); `pytest_sessionfinish` fails the run if any fired skip lacks an
    allowlisted reason (sets exitstatus before reporting; ASCII-safe offender
    print so non-ASCII reasons can't crash sessionfinish on cp1252 stdout).
  - The allowlist matcher is semantic (accepts the 5 category keywords + common
    env/dependency/engine gate phrasings; rejects the broke/deferred/run-manually
    anti-pattern with precedence) and ships with 23 non-vacuity self-tests.
    End-to-end mutation-verified: an injected unjustified skip turns the run RED.
- **`.gitattributes`** pinning `*.sh` and `scripts/hooks/**` to `eol=lf` — bash
  fails ("syntax error near unexpected token") on CRLF, which Windows
  `core.autocrlf=true` was producing for the pre-push hook + its tests. Scoped
  to shell scripts; no repo-wide renormalization.

#### Fixed

- **Suite green-gate drive (#102b, T40–T44)**: drove the full PG-aware suite to
  GREEN — every test passes or carries a DD-42-justified skip; zero failures;
  zero xpass. ~23 genuine failures root-caused across waves, including two real
  product/SUT bugs:
  - `src/schema/sqlite.py` `ensure_columns`: SQLite refuses `ALTER ADD COLUMN
    ... NOT NULL` without a DEFAULT on a populated table, so NOT-NULL-no-default
    registry columns (e.g. `training_examples.instruction`) silently failed to
    migrate onto legacy DBs. Now synthesizes a type-appropriate migration
    default. (Extracted `_migration_default` / `_retry_deferred_indexes` helpers
    to keep the function under the 60-line limit.)
  - `src/email/digest_builder.py` `build_premarket_digest`: rendered the council
    `confidence_weighted_score` 0–1 fraction directly as `"{:.0f}%"`, so a 0.73
    confidence printed as **"1%"** instead of **"73%"** in the operator's
    pre-market brief. Now multiplies fractions ([0,1]) by 100 (matches
    `scheduler/reports.py`).
  - `src/notifications/email_digest.py`: `INSERT OR IGNORE` → `engine_aware_upsert`
    (PG-safety, wave 5a).
  - `src/tools/tradingstate/core.py`: `sqlite3.Error/OperationalError` →
    engine-agnostic `DBError`/`DBOperationalError`; fixed a nested-tuple
    `except (DBError, ...)` that raised `TypeError`.
  - `scripts/archive_bootcamp_2026_04_24.py`: removed the Render-swept
    `sync_state` table reference and a hardcoded `len(TABLES) != 68` tripwire
    that fired on legitimate registry growth.
- **Stale-test repairs** (assertions preserved/strengthened, not weakened): PR-C
  refactor-retargets (`phantom_close`/`live_trading`/`executor_import`/broker
  partial-swallow → post-split module locations + the v0.36.28 SELL-side guard),
  notification tests re-pointed to the `safe_send` dispatch boundary, fixture
  bugs (`macro_snapshots` UNIQUE seed, missing FK parents), now-relative seed
  dates (walkforward staleness), sample-size-guard alignment (auditor), and
  patch-namespace corrections. The T43 gate also caught and forced fixes to four
  line-number-based allowlists that earlier waves' edits had shifted.
- Restored `test_site18` (live `open_live_trade` bracket-failure persist path —
  previously over-deleted) with a working harness, and made the `delete_insert`
  cascade test non-vacuous (real FK-`ON DELETE CASCADE` exercise on both engines)
  instead of a `pass` stub.

#### Changed

- **CI `.github/workflows/pg-tests.yml`**: added a bootstrapped `postgres5434`
  service + a 5434-bootstrap step (so the 24 module-level `TEST_DATABASE_URL`
  readers and SIM-DSN tests connect to a real PG), and `pytest-asyncio` to both
  jobs' installs.
- **`tests/conftest.py`**: snapshot/restore `os.environ` across collection (undoes
  the lifecycle bootstrap's import-time scrub that poisoned `TEST_DATABASE_URL`
  session-wide) + a per-test reset of the enricher rate-limit module-global
  (a freezegun-future timestamp there caused a full-suite `time.sleep` hang).
- **DD-42 §46 amended** with category 5 `integration(authoritative-coverage:<job>)`
  (`docs/audits/2026-05-27-phase-5-unified/design-decisions.md`) — covers the 15
  `tests/simulation/lifecycle/` scenario tests authoritatively exercised by the
  nightly `lifecycle-full-gate` CI job.
- **Known residual (tracked, GitHub #1192)**: 6 order-dependent test-isolation
  defects (pass in isolation, fail only in full-suite ordering via leaked
  process-global state) carry DD-42 category-4 `tracked-upstream-bug (#1192)`
  skips. Not product bugs or regressions; per-victim bisection is scoped in #1192.

### PR-F — docs consolidation + v0.36.78 version cut (T31–T36)

#### Changed

- **T31 — README rewrite** (commit `88e5f9b4`): rewrote `README.md` as the
  operator-facing overview (DD-35) — quick-start, repo layout, and the
  authoritative SQLite test floor 5,467 (closes the floor-drift remediation,
  DD-26). Version badge bumped to `v0.36.78` (T33).
- **T32 — MASTER.md §2 + DIRECTORY regen** (commit `69db7c55`): MASTER §2 now
  documents the rolling-window test-floor model; `DIRECTORY.md` regenerated from
  HEAD via `scripts/generate_directory.py` (DD-28); the generator's
  git-tracked-file filter was repaired so it no longer ingests untracked
  worktree debris; de-hardcoded annotations point at `len(TABLES)` for the
  authoritative table count (= 80).
- **T33 — CLAUDE.md / CHANGELOG.md / RELEASES.md consolidation + v0.36.78 cut**:
  - `CLAUDE.md` delta-only (DD-27): de-hardcoded the schema-table count
    (`70` → authoritative `len(TABLES)`), added the two new PR-A repo-root
    structure rules + the T0a boundary-touch standards note; §207 done-flag
    contract re-verified intact.
  - `CHANGELOG.md`: added the RELEASES.md cross-link header (DD-25), unified the
    six per-PR `<!-- PR-X entries -->` conflict-avoidance markers (DD-37) into
    this single versioned `## [v0.36.78]` block, and left `## [Unreleased]`
    empty.
  - `RELEASES.md`: added the CHANGELOG.md cross-link header (DD-25; the two
    files remain separate).
  - **v0.36.78 version cut** (policy-consistent, `docs/versioning-policy.md`):
    bumped `src/version.py` `VERSION` `v0.36.72` → `v0.36.78` + comment block,
    the README version badge, and the `tests/test_version.py` version-lock
    literals. Coupling trace per versioning-policy.md §42 / #631: the frontend
    `Layout.jsx` version fallback is the literal placeholder `'unknown'`
    (post-#631-15), NOT a hardcoded version constant — so no frontend change is
    coupled to this cut. Tag cut by the coordinator at T39.

#### Added

- **T34 — audits archive sweep**: stale audit/receipt subdirectories swept into
  the dated `archive/` hierarchy per the audits-archive policy (visual-verify
  `.png` hierarchies preserved with their parent receipts, DD-31).
- **T35 — module-docstring header sweep**: standard `Called by/Calls/Owns
  tables/Config keys/Tests` headers backfilled across modules surfaced by
  `tests/test_repo_structure.py::test_all_modules_have_standard_docstring`.
- **T36 — phase-close sentinels**: regression-lock sentinels added for the
  post-Phase-5 invariants (known_violations freshness + audits-archive policy +
  CollectorResult `_safe_run` contract, DD-32).

#### Decisions

- Phase 5 unified-design decisions log: `docs/audits/2026-05-27-phase-5-unified/design-decisions.md`
  (DD-25 keep CHANGELOG/RELEASES separate; DD-27 CLAUDE delta-only; DD-37 marker
  unification at PR-F; DD-39 boundary-touch standards).

### PR-G — phase-5 close-out (T37–T39)

#### Added

- **T37 — three non-grandfathered phase-5 close-out sentinels** (commit
  `48bfe9f6`; DD-32 / DD-37 §3) locking the post-Phase-5 invariants. Each is
  proven non-vacuous by a `tmp_path` negative dry-run (fails when its constraint
  is violated):
  - **known_violations freshness** — no `config/known_violations.json` entry may
    refer to a file currently under the 400-line threshold.
  - **docs/audits archive policy** — no audit/receipt subdirectory older than
    three sprints may remain at the `docs/audits/` top level (must be swept into
    the dated `archive/` hierarchy).
  - **CollectorResult `_safe_run` contract** — `src/scheduler/watch.py`
    `_safe_run` is locked to the `CollectorResult` return contract (PR-D #72
    follow-through).

#### Removed

- **T37 — known_violations.json enabling prune** (commit `48bfe9f6`): the two
  now-undersized rows the freshness sentinel would otherwise flag were pruned:
  - `src/api/cloud_routes/kpis_compute.py` — `401 → 366L` (fell under threshold
    via the PR-B SQLite-only strip).
  - `src/training/backfill.py` — stale entry corrected (`343 → 344L`,
    already below threshold; entry removed).
  KC-6 cloud_routes leftovers and the grandfathered >400L PR-C residuals
  (`order_lifecycle.py`, `telegram_delivery.py`, `executor.py`, `telegram.py`,
  `governor.py`, `trainer.py`, `email_digest_render.py`) are intentionally
  retained with Phase-6 sub-target notes.

#### Docs

- **T38 — this CHANGELOG `### PR-G` sub-section** added to the `## [v0.36.78]`
  block (DD-37: the per-PR `<!-- PR-X entries -->` conflict-avoidance markers
  were unified to `### PR-X` sub-sections by PR-F T33, so PR-G uses a `### PR-G`
  sub-section rather than a re-introduced marker).
- **T39 — RELEASES.md v0.36.78 phase-5 close receipt** added (see `RELEASES.md`;
  CHANGELOG and RELEASES remain deliberately separate per DD-25).

#### Decisions

- **Phase-5 Cleanup-1 kin subsumption** (T39) — the two internal attack-plan
  Cleanup-1 follow-up kins are resolved at Phase-5 close:
  - **Cleanup-1 kin-125 (lazy-import)** — the "6 tests need lazy-import" cleanup
    is subsumed/closed at Phase-5 end; the actual lazy-import refactor is a
    tracked follow-up **deferred to Phase-6** (NOT a green-gate blocker — the
    affected `tests/training/test_pass_c.py` skips are sklearn optional-dep
    skips, DD-42 §46-justified).
  - **Cleanup-1 kin-126 (walkforward)** — the "2 walkforward stale-row tests"
    cleanup was **already absorbed by PR-E2 (T44)**; closed-by-PR-E2, not
    re-handled here.
  (These are internal Cleanup-1 attack-plan kins, distinct from the unrelated
  GitHub bug issues; deliberately referenced WITHOUT the `#NNN` form so no
  unrelated issue is auto-closed or cross-referenced.)

## [v0.36.72] — 2026-05-27 — TradingState GPU_METRICS text=date hotfix (#124b)

### Fixed

- **#124b — TradingState GPU_METRICS text=date type mismatch fixed** (`fix(#124b)`):
  `GPU_METRICS_PG` in `src/tools/tradingstate/queries.py` cast `metric_date::date`
  before comparing with `CURRENT_DATE`. Root cause: `schedule_metrics.metric_date`
  is stored as `TEXT` (writer uses `date.today().isoformat()`), but `CURRENT_DATE`
  is PG type `date`; no implicit `text = date` cast exists in PostgreSQL
  (`UndefinedFunction` error). Sibling-search confirmed no other occurrences.
  `GPU_METRICS_SQLITE` forked from `GPU_METRICS_PG` to preserve the original
  `=` comparison (correct for SQLite where both `metric_date` TEXT and
  `CURRENT_DATE` return text). Fast-follow on v0.36.71 (cleanup-1 baseline).

## [v0.36.71] — 2026-05-27 — Cleanup Sprint 1 — observability + backtest CLI + sim/test infra (#112/113/114/118/119/120/121/122/123/124)

Spec/plan: `docs/audits/cleanup-1/`. Ten-fix bundled backlog sweep landing as
one PR with one commit per fix plus a sibling-search consolidation commit and
the integration commit. Dual-Opus QA gate ran on the bundle, not per-commit.
Discipline (operator-stated): architect autonomy + batching + sibling-search +
verify-by-mutation + no-out-of-scope-deferral.

### Cluster A — observability accuracy

- **#119 — `paths.logs_runtime` config drift fixed** (`fix(#119)`):
  `config/arcis_config.yaml` `paths.logs_runtime` corrected from
  `C:/arcis/logs` to repo-local canonical `C:/arcis/halcyon-lab/logs`.
  Architect-locked option (b) — config + docs only; runtime log files
  NOT physically moved (would risk watch-loop downtime).
  Doc sweep: `CLAUDE.md`, `src/training/training_control.py:31` comment.
  Audit-doc historical receipts under `docs/audits/2026-*/` preserved
  intentionally. Known Consideration: `TRAINING_PID_FILE` derivation at
  `training_control.py:35-37` still computes the legacy
  `C:/arcis/logs/training.pid` path; the comment was updated but the
  runtime derivation was deliberately NOT changed (would drift to
  rejected option (a)). Filed for follow-up.
- **#120 — HealthProbe heartbeat filenames mapped to NSSM-actual filenames**
  (`fix(#120)`): `_HEARTBEAT_SOURCES` + `_LOG_SOURCES` in
  `src/tools/healthprobe/core.py` updated from stale `arcis-dashboard.log` /
  `arcis-ollama-watchdog.log` to NSSM-produced `dashboard-stdout.log` /
  `ollama_watchdog.out.log`. Eliminates false-DEGRADED noise on the
  Dashboard + Ollama services. Sibling-fix in `nssm.py:121-123` rolled
  into the cleanup commit.
- **#122 — `ArcisWatchLoop` staleness threshold bumped 60 → 900s**
  (`fix(#122)`): `_DEFAULT_STALENESS['ArcisWatchLoop']` increased to
  900 seconds (15 minutes). Addresses 2 false-positive wedge diagnoses
  during normal 14-min LLM scan cycles (per
  `feedback_wedge_vs_long_iteration`). V2 enhancement: per-task
  intra-iteration heartbeat lets threshold drop back to 60s — deferred.
  Other services' thresholds unchanged.
- **#123 — Live-monitor agent 4-point wedge protocol + golden cases**
  (`docs(#123)`): `.claude/plugins/arcis/agents/live-monitor.md` and
  `.claude/plugins/arcis/commands/operate.md` updated with the 4-point
  wedge-diagnostic protocol (staleness > 20 min + arcis.log silence > 20
  min + no in-progress markers + p99 baseline comparison). New
  `OUTPUT FORMAT` field `historical_baseline_min` per `service_state[]`
  entry. New CONSTRAINT: "MUST NOT declare wedge unless ALL FOUR met."
  Golden cases at `docs/agent-tests/live-monitor-golden.md` encode the
  2026-05-26 11:14 ET misdiagnosis regression case and a true-wedge case
  with explicit `EXPECTED_VERDICT` markers. Sibling: same 4-point list
  byte-equivalent across live-monitor.md, operate.md, and
  `watchloop-wedged.md` runbook.
- **#124 — TradingState structured error envelope on UndefinedTable**
  (`fix(#124)`): `src/tools/tradingstate/core.py` `_pg_snapshot` and
  `_sqlite_snapshot` now wrap individual `cur.execute()` calls in
  targeted try/except for `psycopg2.errors.UndefinedTable` and
  `sqlite3.OperationalError` (no-such-table). Missing-table conditions
  produce `{field: None, errors: {field: {error_type, error_message,
  table_name}}}` rather than crash or silent-empty. Closes the
  silent-failure anti-pattern class that masked the morning-wedge
  misdiagnosis. Other DB error types still propagate.

### Cluster B — backtest CLI plumbing

- **#118 — `scripts/run_backtest.py --with-walkforward` deprecated**
  (`chore(#118)`): the flag now emits a deprecation message and exits
  non-zero. Argparse entry retained so `--help` exposes the deprecation.
  Default mode unchanged. Architect-locked option (b) — deprecate, do
  NOT update the call-site (`/arcis:strategy backtest` is the canonical
  surface). Three out-of-scope string-literal hits in `src/platform/`
  (`promotion.py:529` operator-visible error message, `backtest_persist.py:62`,
  `__init__.py:23`) rolled into the cleanup commit.

### Cluster E — sim/test infra trio

- **#112 — `test_trainer_stub.py` env-drift fixed via lazy import**
  (`fix(#112)`): production module import moved inside a pytest fixture
  so conftest env injection lands before `DB_PATH` resolution. Removed
  the corresponding `--ignore=...test_trainer_stub.py` flag from
  `.github/workflows/lifecycle-smoke.yml`. Architect-locked: test-side
  fix only — production code in `src/training/` untouched.
- **#113 — lifecycle-smoke CI timeout tightened 600 → 480s**
  (`chore(#113)`): 300s target NOT achieved this pass — 480s is the
  honest residual. Bottleneck identified: `test_no_conn_leak_smoke_accumulator`
  with `SIM_LEAK_LOOP_ITERATIONS=3` default. Follow-up: session-scoped
  `run_smoke()` fixture caching could collapse ~9 independent invocations
  to ~1; deferred per discipline ("don't trade smoke coverage for runtime").
- **#114 — sim per-fault matrix T10/T11/T12 added** (`test(#114)`):
  new `tests/simulation/lifecycle/test_per_fault_matrix.py` with 13
  tests covering broker-submit timeout (T10), virtual-clock drift (T11),
  and market-data feed gap (T12). Each fault includes a verify-by-mutation
  hook proving the test reaches the production code path. T11
  `_now`-mutation pattern matches the existing offset-naive convention.

### Cluster F — tooling

- **#121 — py-spy admin stack-dump wrapper** (`feat(#121)`): new
  `scripts/dump_watchloop.ps1` elevates via `Start-Process -Verb RunAs`,
  invokes `py-spy dump --pid <N>`, captures dump output under the
  corrected `logs_runtime` path (`C:/arcis/halcyon-lab/logs`). New
  operator runbook at `docs/runbooks/stack-dump.md` covers when to use,
  prerequisites (`pip install py-spy`), and how to interpret the output.

### Sibling-search consolidation commit

- **`chore(cleanup-1): finish sibling-search sweep`** — five
  out-of-scope hits flagged during Wave-1+2 sibling-searches, fixed in
  one coherent commit:
  1. `src/platform/promotion.py:529` — operator-visible error message
     updated from "run with --with-walkforward first" to canonical
     `/arcis:strategy backtest <id>` advice.
  2. `src/platform/backtest_persist.py:62` — comment updated.
  3. `src/platform/__init__.py:23` — tool description updated.
  4. `src/tools/processmanager/nssm.py:121-123` — `_resolve_log_evidence_path`
     filename map updated to match #120 (same anti-pattern).
  5. `.claude/plugins/arcis/skills/operate/runbooks/watchloop-wedged.md` —
     4-point protocol mirrored byte-equivalent to live-monitor.md +
     operate.md (sibling of #123).

### Tests

Net-add: **+27 new tests** across the sprint (Wave 1: 19; Wave 2: 5;
sibling cleanup: 1; +2 baseline test fixture updates for thresholds).
Total collected: **6,997** (well above the 5,467 CI floor).

### Known Considerations / follow-ups

- `TRAINING_PID_FILE` derivation discrepancy (see #119 entry above).
- `scan_service.py` grew from 440 → 517 lines past its grandfathered
  tolerance — pre-existing on `main`, not introduced this sprint;
  `config/known_violations.json` entry should be updated or the file
  split in a future cleanup.
- lifecycle-smoke session-scoped `run_smoke()` fixture caching (#113
  follow-up).
- Six tests under `tests/` import `src.training` modules at module
  scope; safe in CI today because lifecycle-smoke is scoped, but
  vulnerable to env-drift if collection order changes — applying the
  #112 lazy-import pattern would harden them.

## [v0.36.70] — 2026-05-27 — Arcis Strategy Skill (#110) — research-desk capstone

Spec/plan: `docs/audits/2026-05-26-arcis-strategy/`. New `/arcis:strategy` skill
with 4 verbs (ideate / backtest / analyze / status). Composes db-investigator +
git-historian + research-team (domain-lead + specialist + cross-domain-analyst)
into a single research workflow. Adds `provenance_kind` column on
`backtest_results` for three-state outcome preservation at the data layer (DA1).

#### Added

- **Skill: `/arcis:strategy` ships with 4 verbs.** New plugin skill at
  `.claude/plugins/arcis/skills/strategy/` with companion orchestrator at
  `.claude/plugins/arcis/commands/strategy.md`. Verbs:
  - `ideate <theme>` — dispatches db-investigator + git-historian +
    research-domain-lead (Wave A) then research-cross-domain-analyst
    (Wave B, suppressible via `--no-cross-domain`); writes a structured
    ideation report to `docs/strategy-ideation/<date>-<slug>.md`.
  - `backtest <strategy_id> [--quick]` — default invokes the full
    walkforward stack (`backtest_engine.run_backtest()` per IS+OOS window
    → `walkforward_runner.run_walkforward()` → `persist_run_result()`)
    with R2 purging + R8 firewall + spec-snapshot binding (DA2) + Phase
    B5.5 file-lock (DA5). `--quick` runs a single in-sample slice with a
    ⚠ banner and writes a `quick_in_sample` `backtest_results` row.
  - `analyze <run_id|result_id>` — resolves to either `walkforward_results`
    or `backtest_results`; computes DSR + PSR (López de Prado 2018) and
    CSCV PBO when ≥2 prior backtest rows for the strategy exist;
    preserves `outcome_state` verbatim (no boolean collapse — DA1).
  - `status [strategy_id]` — read-only snapshot of FS specs, registry
    rows, recent backtest + walkforward runs, trials_registry N_eff,
    FS ↔ DB drift, active runs (DA12), and orphans (DA1/DA4).
- **Schema migration** — adds non-null `provenance_kind` column on
  `backtest_results` with CHECK constraint over
  `{quick_in_sample, wf_is_window, wf_is_window_orphan_partial_run}`
  (DA1 three-state outcome preservation at the data layer).
- **Skill references** under `.claude/plugins/arcis/skills/strategy/references/`:
  - `verb-conventions.md` — argument parsing, tool envelope contract,
    operator-facing error envelopes.
  - `rigor-stack-integration.md` — how `backtest` + `analyze` compose
    with `src/platform/rigor/` (R2 + R8 + DSR + PSR + CSCV).
  - `statistical-rigor.md` — DSR/PSR/PBO mechanics, T<30 guard,
    N_eff family-variance fallback.
  - `error-envelopes.md` — verbatim §10.x operator-facing prose for the
    18 refuse/incomplete paths.
  - `golden-transcripts.md` — 5 happy-path transcripts cited from §11
    of the design spec (T7).
- **Audit-event coverage** — every verb emits bracket events
  (`arcis_strategy.<verb>.started` and `.completed`) into
  `data/logs/tool-execution.log` keyed by `session_id`. `backtest`
  additionally emits `.confirmed` (with `prompt_hash` + `option_text`),
  `.wf_partial` (on mid-run failure), `.wf_complete` (post-runner),
  `.prod_pg_refused`, `.db_path_blocked`, `.concurrent_refused`,
  `.r8_violation`, and `.spec_snapshot_path`. `status` is read-only —
  emits NO audit event.

#### Changed

- **`backtest_results` insert contract** — `persist_backtest_result()`
  now requires `provenance_kind=` as a kwarg; schema CHECK refuses NULL.
  All historical callers — `scripts/run_backtest.py`, the engine entry
  point, the per-window IS slice in `walkforward_runner.py` — pass the
  correct literal (`quick_in_sample`, `wf_is_window`, or
  `wf_is_window_orphan_partial_run`). See DA1 in the design spec.

#### Documentation

- New spec/plan/decision artifacts under
  `docs/audits/2026-05-26-arcis-strategy/`:
  - `specs/2026-05-26-arcis-strategy-design.md` (~2970 lines) — full
    design including §11 golden transcripts, §12 manual-verification
    checklist (29 items), §13 implementation discipline, and §14 open
    questions.
  - `plans/2026-05-26-arcis-strategy-plan.json` — task graph used by the
    PM-orchestrated implementation pass.
  - `decisions/design_decisions.json` — DD1-DD22 operator-confirmed
    decisions locked at design time.

## [v0.36.69] — 2026-05-26 — Email Consolidation PR 1 (#115)

Spec/plan: `docs/audits/2026-05-26-email-consolidation/`. Three-tier email
aggregator (`preopen` / `postclose` / `weekly`) wired alongside the legacy
`digest_builder` paths, gated by `email.dual_write_hold_over.mode` (default
`shadow`). PR 2 deletes the legacy paths once `digest-handover-check` reports
`status=PASS`.

### Added

- **New CLI commands** (T15):
  - `python -m src.main digest-preview --tier {preopen,postclose,weekly} [--pending] [--dry-run]`
  - `python -m src.main digest-handover-check [--window-days N] [--compare-window 7d]`
  - Exit code: `0` on PASS, `1` on FAIL.
- **New YAML config keys** (under `email:`):
  - `tier_times.{preopen,postclose,weekly}` — wall-clock dispatch times.
  - `tiers.<tier>.{enabled,send_when_empty}`.
  - `dual_write_hold_over.{mode,shadow_output_dir,enabled}` — `mode` ∈ `{shadow, time_aligned, off}`.
  - `digest_truncation.{top_k_per_section,overflow_strategy,overflow_attach_format}` (DD-05/DD-19).
  - `holidays.{skip_preopen_on_market_holidays,skip_postclose_on_market_holidays}` (DD-23).
- **New test files** (all under `tests/notifications/`):
  - `test_email_digest_module.py`, `test_email_digest_render_daily.py`,
    `test_email_digest_render_weekly.py`, `test_email_digest_holdover.py`,
    `test_email_digest_crash_recovery.py`, `test_email_digest_dst.py`,
    `test_email_digest_opt_out.py`, `test_email_digest_coverage_matrix.py`,
    `test_email_digest_holiday.py` (T17),
    `test_email_digest_handover.py` (T17).
- **Holiday-aware suppression in `flush_tier`** (T17, DD-23) — preopen and
  postclose tiers skip dispatch when `is_market_holiday()` returns True AND
  the per-tier `skip_*_on_market_holidays` config flag is True (default).
  Weekly tier is unaffected.
- **Real `handover_check` tripwire logic** (T17, DA-MAJ-7 + DA-MAJ-11) —
  PR 2 merge gate. Returns `{status, tripwires, details}` with six
  tripwires: abandoned-rows-under-threshold, preopen/postclose-flushed,
  weekly-flushed, shadow-files-present, and the optional
  `row_id_inclusion_check` when `compare_window='7d'` is passed.

### Changed

- **`send_email` signature** (T2) — accepts `html_body` + `attachments` for
  HTML-multipart digest dispatch with overflow attachment.
- **`DigestQueue.flush()` contract** (T4/T16) — recovers orphaned
  `in_progress` rows on the next flush tick; honors retry-attempt exhaustion
  by marking abandoned with `flush_error` populated.
- **Scheduler dispatch** (T8, watch.py) — `_check_digest_schedule` invokes
  `email_digest.flush_tier(tier=...)` at each tier's wall-clock window.
  The legacy `_check_legacy_digest_schedule` continues firing the four old
  branches gated by `dual_write_hold_over.mode`.

### Deprecated

- **Old digest_builder paths** (`src/email/digest_builder.py` —
  `build_premarket_digest`, `build_midday_digest`, `build_eod_digest`,
  `build_evening_digest`). Scheduled for deletion in PR 2 once the
  `digest-handover-check` CLI reports `status=PASS`.
- **Saturday email branches** — subsumed by the weekly tier (DD-12).
  Saturday training-report + Saturday CTO-report flow through
  `weekly_digest_content` payloads aggregated at Sun 18:00 ET.
- **`email_mode=full_stream`** and **`email_mode=daily_summary`** —
  redundant with the new tiered aggregator; will be removed in PR 2.

### Fixed

- **Dead `run_saturday_reports`** (F-MAJ-1, T11) — deleted from
  `src/scheduler/reports.py`; never invoked from any scheduler tick after
  the digest_builder Saturday branches landed.

## [v0.36.68] — 2026-05-26 — `/arcis:periodic-discipline` meta-skill — plugin infrastructure drift auditing (#111)

### Added

- **Skill: `/arcis:periodic-discipline` ships with 4 verbs** (#111). New plugin meta-skill at
  `.claude/plugins/arcis/skills/periodic-discipline/`. Audits the Arcis plugin ecosystem for
  drift — stale skills, dead memory, broken tools — without adding any new Python tools, agents,
  or schema tables (operator constraint DD11: zero `src/tools/` additions).
  - **4 verbs**:
    - `audit-skills` — scans all SKILL.md files for stale runbook references, broken tool citations,
      and verb/allowlist drift. Runbook: `audits/audit-skills.md`.
    - `curate-memory` — reviews `.claude/memory/` entries for accuracy against current code state,
      flags stale invariants. Runbook: `audits/curate-memory.md`. Local-only verb (mutates memory
      files; not safe to run in CI).
    - `test-tools` — validates that every Tier 1+2+3 tool CLI is reachable, `--help` passes, and
      smoke-test contracts are satisfied. Runbook: `audits/test-tools.md`.
    - `full` — orchestrates all three audit verbs in sequence; produces a consolidated findings
      report at `data/periodic-discipline/reports/`. Local-only verb. Runbook: `audits/full.md`.
  - **Composition only** — composes existing 13 Tier 1+2+3 tools plus the
    `research-cross-domain-analyst` agent. No new Python modules, no new schema tables.
  - **3 reference docs**: `references/findings-schema.md` (structured finding envelope format),
    `references/lockfile.md` (per-run lockfile preventing concurrent audit runs),
    `references/scanners.md` (catalogue of 9 scanner functions used across verbs).
  - **Allowlist** (`allowlist.yaml`) — 1-entry seed (advisory:placeholder); 26 lines of inline
    namespace documentation. Edit to suppress known false positives; each entry requires a `reason`
    field.

- **CI cron workflow** (`.github/workflows/periodic-discipline.yml`):
  - Two scheduled jobs: `audit-skills` (every Monday 07:00 UTC) and `test-tools` (every Thursday
    07:00 UTC). `curate-memory` and `full` are local-only and not scheduled.
  - Three-state outcome: GREEN-clean (no findings), GREEN-findings (findings present, posted to
    job summary, exit 0), RED-crashed (scanner itself crashed, exit 1). Compliant with
    `feedback_audit_workflow_constraints`: `permissions: contents: read` only, no blanket
    `continue-on-error: true`.
  - `workflow_parity` scanner — self-validating check that asserts the workflow YAML jobs match
    the verbs listed in each runbook's bash invocation block. Prevents workflow + runbook from
    drifting independently.

### Tests

- New `tests/skills/` directory (with `__init__.py`) — first tests for plugin skill runbooks.
- `tests/skills/test_periodic_discipline.py` — 17 acceptance tests covering verb presence,
  allowlist format, report-path invariants, findings-schema envelope shape, lockfile protocol,
  and scanner catalogue completeness.
- `tests/skills/test_periodic_discipline_boundary.py` — 6 test functions / 54 pytest-collected
  cases (parametrized over tool list) covering local-only verb restriction, empty-findings exit
  codes, and concurrent-run lockfile guard.
- `tests/tools/test_workflow_parity_scanner.py` — 5 tests for the `workflow_parity` scanner
  covering YAML ↔ runbook parity, job-name extraction, and drift-detection logic.
- **Tests: 28 test functions added (79 collected when parametrized)**: `tests/skills/test_periodic_discipline.py`
  (17 functions / 20 collected), `tests/skills/test_periodic_discipline_boundary.py` (6 functions /
  54 collected via 13-tool parametrization), `tests/tools/test_workflow_parity_scanner.py` (5 functions /
  5 collected). All vacuous-test-discipline verified via `TestVacuousCheckVerification` class.

## [v0.36.67] — 2026-05-26 — `/arcis:operate` skill — incident response + change orchestration (#109)

### Added

- **Skill: `/arcis:operate` ships with 4 verbs + 5 runbooks** (#109). New plugin skill at
  `.claude/plugins/arcis/skills/operate/` and orchestrator command at
  `.claude/plugins/arcis/commands/operate.md`. Operator-facing surface:
  - **4 verbs**: `triage <symptom>` (diagnostic agent dispatch + cross-agent finding
    composition), `act <action>` (operator-confirmed mutation via Action Authorization
    Matrix with Safety Window Gate at 21:30-22:30 ET), `status` (fast snapshot,
    target <30s), `runbook <name> [--dry-run]` (named procedures with frontmatter
    validator + abandonment recovery).
  - **5 v1 runbooks**: `watchloop-wedged` (mutating, NSSM restart), `pg-tests-red`
    (diagnostic, ci+db cross-agent), `training-failed` (diagnostic, branch on
    crash/corpus/not-started/stale), `gpu-degraded` (mutating, VRAM recovery via
    Ollama-watchdog restart), `data-anomaly` (diagnostic, A/B/C/D categorization).
  - **2 reference docs**: `references/action-authorization-matrix.md` (5 verified
    actions; 3 presumed CLIs `force-broker-poll`/`post-pr-summary`/`regenerate-stale-audit`
    REMOVED at impl-time after `--help` probe failed); `references/error-envelopes.md`
    (9 error classes including §10.9 audit-write-failure).
  - **Composes** the 13 Tier 1+2+3 tools (#105/#106/#107) and 4 investigator agents
    (#108: db/ci/git/live) into one workflow.

### Changed

- **`src/tools/_execution_log.py`** — added stdin-driven `if __name__ == "__main__"` CLI
  block (~22 LOC) so the orchestrator can write audit events via subprocess with
  injection-safe JSON-on-stdin (DA3 mitigation per spec §14 OQ#7).

### Tests

- `tests/test_operate_runbook_data_anomaly.py` — 12 acceptance tests (frontmatter,
  ABCD categorization, no-deferral language, rollback diagnostic-only, abandonment).
- `tests/test_operate_error_envelopes_ref.py` — 5 acceptance tests (9 sections,
  audit-write-failure §10.9 present, trigger/output/audit/exit pattern, UTF-8).
- `tests/test_operate_action_authorization_matrix.py` — 6 acceptance tests
  (7-column header, cell count, verification enum, auth_class enum, UTF-8,
  no leftover unverified-presumed rows).

## [v0.36.66] — 2026-05-25 — Multi-GPU parser fix in _collect_gpu_metrics (#117 hotfix)

### Fixed

- **`_collect_gpu_metrics()` multi-GPU support (#117)** — the watchloop was silently
  dropping all GPU metrics on the dual-GPU dev rig (RTX 3090 + RTX 3060) because the
  nvidia-smi CSV output contains TWO rows but `.strip().split(",")` collapsed them into
  9 fields, the `float()` on `"91.65\n0"` raised `ValueError`, and the broad
  `except Exception` swallowed it. Now splits by newlines first (`splitlines()`), uses
  the first row (primary training GPU = RTX 3090 per `project_gpu_upgrade.md`);
  single-GPU consumers are unaffected.

### Changed

- **`_collect_gpu_metrics()` exception handling tightened** — removed the bare
  `Exception` catch that was masking parse errors silently. Now only catches
  `FileNotFoundError` + `TimeoutExpired` (subprocess failure modes) AND
  `ValueError`/`IndexError` with `logger.warning` first, so parse drift is visible
  going forward rather than being dropped to debug-only logging.

### Tests

- 4 new tests in `tests/monitoring/test_system_metrics.py`:
  - `test_collect_gpu_metrics_multi_gpu_uses_first_row` — dual-GPU stdout parsed via first row; all 5 fields correct.
  - `test_collect_gpu_metrics_single_gpu_unchanged` — single-GPU consumers unaffected.
  - `test_collect_gpu_metrics_value_error_returns_none_with_warning` — malformed stdout returns `_gpu_none()` AND emits `logger.warning`.
  - `test_collect_gpu_metrics_committed_baseline_matches` — regression-lock using the verbatim `stdout` from the committed ContractCheck baseline; all 5 keys non-None post-fix.

### References

- `src/monitoring/system_metrics.py:33-59` — `_collect_gpu_metrics()` fix
- `data/contracts/nvidia-smi-watchloop/2026-05-26T02-23-36Z.json` — ContractCheck baseline that surfaced this bug (`parse_ok: false` because the watchloop's parser shape didn't match live dual-GPU output)

### Surfaced by

- **#107** (ContractCheck v1's first baseline). The 2-line stdout was committed as a forensic artifact precisely to enable this hotfix to be regression-tested against the captured live state.

### Added — #108 specialized investigator agents (no version bump; docs-only)

No version bump: this PR adds 4 investigator-class agent prompts + 4 golden-question
reference files + agent-conventions.md addenda. All capabilities land via auto-discovery
(no plugin.json update required — confirmed by spec §8 DD-8). `src/version.py`,
`pyproject.toml`, and `plugin.json` are NOT modified.

- **`db-investigator`** (`.claude/plugins/arcis/agents/db-investigator.md`) — READ-ONLY
  DB forensics agent composing DBQuery + CapabilityRegistryQuery + SymbolFind + LogTail
  via Bash subprocess. Surface (4-6 calls) / deep (15-30 calls) investigation modes.
  First-in-class consumer of the Tier 1+2 tool surface. NEVER issues mutating SQL
  (DBQuery enforces read-only at the tool layer; agent CONSTRAINTS repeats intent).

- **`ci-investigator`** (`.claude/plugins/arcis/agents/ci-investigator.md`) — CI failure
  classifier (REAL / TEST / FLAKY / STALE-BASE) composing CIInvestigate + PRComments +
  SymbolFind + LogTail. CAN MUTATE via `PRComments.post` but only with explicit TARGET_PR
  in DYNAMIC CONTEXT (TARGET-PR-SCOPING guardrail). Repost-idempotent via DA4: SHA-256
  fingerprint footer (`<!-- [fingerprint:<8-hex>] -->`) appended to every post; pre-post
  `prcomments read` scan; `ALLOW_REPOST=false` default; `post_status=skipped_duplicate`
  when matching fingerprint found. Uses stdin-pipe pattern (`cat <<'EOF' | ... --body-file
  -`) per §2.3.2 — NEVER `--body STRING` to avoid shell-escaping risk.

- **`git-historian`** (`.claude/plugins/arcis/agents/git-historian.md`) — READ-ONLY
  temporal archaeology via direct git CLI + SymbolFind + PRComments.read. No commits,
  push, reset, or rebase allowed (enforced by CONSTRAINTS enumeration). Refactors to #107
  GitArchaeology Tier 3 when that tool lands (DD-10).

- **`live-monitor`** (`.claude/plugins/arcis/agents/live-monitor.md`) — READ-ONLY
  observational snapshot composing ProcessManager.status (ONLY — NOT restart/start/stop) +
  HealthProbe + LogTail + TradingState + CIInvestigate. NEVER issues restart/start/stop
  (that boundary belongs to #109 `arcis:operate`). Captures ET wall-clock as Workflow Step
  0 via `TZ='America/New_York' date` for overnight-window evaluation (21:30-22:30 ET
  restart recommendations forbidden per `feedback_no_restart_during_overnight_window`).

- **4 golden-question reference files** at `.claude/plugins/arcis/docs/agent-tests/`:
  `db-investigator-golden.md`, `ci-investigator-golden.md`, `git-historian-golden.md`,
  `live-monitor-golden.md` (3-5 questions each). Document expected response shape
  (sections, citation density, classification correctness) for #111 skill-audit baseline.
  Includes DA4 repost-refusal case for ci-investigator (no TARGET_PR → refuse post →
  return markdown for manual posting).

- **`agent-conventions.md` addenda** (`.claude/plugins/arcis/docs/agent-conventions.md`):
  - §Naming Addendum (DD-1): investigator-class bare-name exception — `db-investigator`
    etc. intentionally omit the `arcis-` prefix because they are cross-skill assets
    consumed by #109/#110/#111 and the operator directly.
  - §maxTurns Addendum (DD-2/DD-17): `maxTurns: 60` precedent established by
    `coding-rigor-reviewer.md`. Turn-50 budget-stop: at turn ≥50 the agent STOPS issuing
    new tool calls and reserves remaining turns for OUTPUT FORMAT composition.
    `coverage_assessment` is a REQUIRED field on ALL FOUR investigator-class OUTPUT
    FORMATs.
  - §Bash-subprocess Tool Invocation Appendix: DA1 worktree-portable cwd via
    `cd "$(git rev-parse --show-toplevel)"` + optional `WORKTREE_PATH` DYNAMIC CONTEXT
    override (replaces hardcoded `cd C:/arcis/halcyon-lab`); DA2 mandatory per-call Bash
    `timeout` parameter with tiered defaults (60000ms standard / 90000ms heavy-query /
    120000ms full-gate); §2.3.1 single-quote convention for shell safety; §2.3.2 stdin-
    pipe pattern (`cat <<'EOF' | ... --body-file -`).
  - §5 OUTPUT FORMAT Addendum (DD-11): registered investigator-class custom-tag enum —
    `<db_report>`, `<ci_report>`, `<git_report>`, `<live_report>`. Domain-semantic tags
    (refactoring to `<findings>` would lose meaning). DA6 `coverage_assessment` field
    required on all four.
  - §Cross-Cutting-Conventions Appendix: DA3 empty-result classification (empty primary
    collection = `informational` severity, never silently dropped); DA5 JSONB/TEXT
    200-char truncation rule (`*_jsonb`/`*_detail`/`*_payload`/`*_body` columns truncated
    at ≤200 chars with `[truncated]` marker); DA4 fingerprint-footer convention for
    repost-idempotent posters.

- **First-time encoding of `feedback_complete_efforts_no_deferral`** operator memory
  directly in agent prompts (EPISTEMIC LENS section, per DD-13): "If during the
  investigation you discover an adjacent issue, DOCUMENT IT INSIDE this report — do not
  punt to out of scope." This ensures the directive shapes the agent's cognitive frame
  during findings-generation, not just as a rule in CONSTRAINTS.

#### Cross-cutting conventions applied to all 4 agents

| Convention | Code | Description |
|---|---|---|
| Worktree-portable cwd | DA1 | `cd "$(git rev-parse --show-toplevel)"` + optional `WORKTREE_PATH` override |
| Mandatory per-call timeout | DA2 | 60000ms standard / 90000ms heavy-query / 120000ms full-gate; no implicit 120s ceiling |
| Empty-result classification | DA3 | Empty primary collection → `informational` severity, explicitly documented |
| ci-investigator repost-idempotency | DA4 | SHA-256 fingerprint footer + pre-post scan + `ALLOW_REPOST=false` + `skipped_duplicate` status |
| JSONB/TEXT truncation | DA5 | `*_jsonb`/`*_detail`/`*_payload`/`*_body` ≤200 chars + `[truncated]` marker |
| Turn-50 budget-stop | DA6 | Stop new tool calls at turn ≥50; mandatory `coverage_assessment` field on all 4 OUTPUT FORMATs |

## [v0.36.65] — 2026-05-25 — Tier 3 meta-quality tools (#107): ContractCheck v1, GitArchaeology v1, DocConsistency v1

Three new subpackages under `src/tools/`, all read-only (every public op decorated
`@safe_op(name="X", mutates=False)`). Builds on the Tier 1+2 foundation; shares
`_config.py` (ContractsConfig extension), `_subprocess.py` (2 new error classes,
lru_cache maxsize 4→6), `_safety.py`, `_cli_envelope.py`, and `_execution_log.py`
unchanged.

### Added

- **ContractCheck v1** (`src/tools/contractcheck/`) — forensic drift detector for
  pinned external-CLI invocations. v1 instruments the watchloop's `nvidia-smi` call
  (`config/arcis_config.yaml:175-201`). Three public ops: `record(name)` captures a
  live baseline (written atomically to `data/contracts/<name>/<timestamp>.json` +
  `latest_ref.txt`); `verify(name)` compares a fresh live invocation against the
  committed baseline per per-field `NormalizeRule` (tolerance / mask_regex / ignore);
  `diff(name, baseline_a, baseline_b)` compares two stored baselines. Verdicts:
  `PASS` / `DRIFT` / `INVOCATION_FAILED`. All ops decorated
  `@safe_op(name="contractcheck", mutates=False)`.

  DA-enforced behaviors:
  - **DA1** recalibrated tolerances in `config/arcis_config.yaml:175-201`:
    `gpu_util_pct:5.0`, `gpu_vram_used_mb:2048.0`, `gpu_temp_c:10.0`,
    `gpu_power_w:50.0` (wider than R1 draft; narrower than full idle→load range).
  - **DA2** `at_capture_redact` PII sanitization applied at `record()` time AND
    re-applied at `verify()` time to live stdout before comparison (baseline-redacted
    vs live-redacted always comparable).

- **GitArchaeology v1** (`src/tools/gitarchaeology/`) — read-only wrapper over the
  7 most common git CLI ops. 7 public ops: `log`, `blame`, `show`, `diff`,
  `rev_list`, `merge_base`, `tag_l`. All decorated
  `@safe_op(name="gitarchaeology", mutates=False)`. Mutating ops (`commit`, `push`,
  `rebase`, etc.) are rejected at argparse level (exit 2 / `invalid choice`). Primary
  client: `git-historian` agent (#108). Helper split:
  `src/tools/gitarchaeology/_helpers.py` (internal `_git()` dispatcher) +
  `src/tools/gitarchaeology/_errors.py` (typed error hierarchy).

  DA-enforced behaviors:
  - **DA3** explicit `maxsplit` in `log()` tab-splitter (subject field preserves
    embedded tabs); paired `format=` / `format_columns=` kwargs (missing `format_columns`
    when `format=` is set raises `GitArgError` before any subprocess); `GitParseError`
    raised on malformed output with `offending_line` / `expected_columns` / `op` fields.
  - **DA4** per-op `MAX_OUTPUT_BYTES` post-invocation check in `_git()` raises
    `GitOutputTruncatedError` with `partial_output` (codepoint-boundary-safe) +
    `original_size_bytes`; `blame()` pre-invocation 5000-line gate raises `GitArgError`
    for files exceeding the limit without `start_line`/`end_line`; CLI accepts
    `--max-output-bytes N`.

- **DocConsistency v1** (`src/tools/docconsistency/`) — scans `docs/`, `CHANGELOG.md`,
  `README.md` for inline `file.py:line` refs and verifies each refers to a file that
  exists with at least that many lines. v1: **class (a) file:line existence only**.
  Classes (b) API signature drift, (c) docstring-vs-code drift, (d) symbol-existence
  drift are explicitly deferred to v2 (see Open follow-up below). One public op:
  `scan(targets=None)` returns `refs_found`, `refs_verified_ok`, `refs_allowlisted`,
  `findings` list. Per-finding fields: `file`, `line`, `ref_path`, `ref_line`,
  `severity`. Age filter: `docs/audits/**` files older than 30 days excluded from
  default scan (override with `--target`). Allowlist at
  `data/docconsistency-allowlist.yaml`. Op decorated
  `@safe_op(name="docconsistency", mutates=False)`.

### References

- `src/tools/contractcheck/core.py` — ContractCheck record/verify/diff + error classes
- `src/tools/gitarchaeology/core.py` — GitArchaeology 7 ops + MAX_OUTPUT_BYTES constants
- `src/tools/gitarchaeology/_helpers.py` — internal `_git()` dispatcher + size governance
- `src/tools/gitarchaeology/_errors.py` — typed error hierarchy (GitMissingError,
  GitInvocationError, GitArgError, GitParseError, GitOutputTruncatedError)
- `src/tools/docconsistency/core.py` — DocConsistency scan + pattern matchers + allowlist
- `config/arcis_config.yaml:175-201` — nvidia-smi-watchloop contract definition (DA1
  recalibrated tolerances; DA2 at_capture_redact annotation guide)
- `data/contracts/nvidia-smi-watchloop/2026-05-26T02-23-36Z.json` — committed baseline
  (recorded T5); `parse_ok: false` because dual-GPU stdout produces two rows that the
  single-value CSV parser merges awkwardly (see Open follow-up #117)

### Tests

- **25 ContractCheck tests** in `tests/tools/test_contractcheck_integration.py`;
  line coverage ≥95% on `src/tools/contractcheck/core.py`.
- **40 GitArchaeology tests** in `tests/tools/test_gitarchaeology_integration.py`;
  line coverage ≥96% on `src/tools/gitarchaeology/` subpackage.
- **27 DocConsistency tests** in `tests/tools/test_docconsistency_integration.py`;
  line coverage ≥97% on `src/tools/docconsistency/core.py`.
- **92 new tests total**. Full tools suite: 276 passed, 0 failed (11 deselected:
  tradingstate tests requiring live DB).

### Open follow-up

- **#117** `Restore [N/A]/multi-GPU defense in system_metrics.py:36-56 nvidia-smi
  parser` — **latent bug surfaced by ContractCheck's first baseline**.
  `data/contracts/nvidia-smi-watchloop/2026-05-26T02-23-36Z.json` shows
  `"parse_ok": false` because the operator's dual-GPU rig produces TWO rows of
  nvidia-smi CSV output (`stdout: "1, 2817, 24576, 67, 91.65\n0, 93, 12288, 57,
  8.31\n"`). The single-row CSV parser merges them awkwardly into a single
  `gpu_power_w` value of `"91.65\n0"`. The v0.36.29 `[N/A]` defense that originally
  lived in `src/scheduler/vram_manager.py` was deleted by the overnight-handoff-removal
  refactor (witnessed by `tests/test_overnight_handoff_removed.py:25-32`). Fixing the
  multi-GPU parser is **out of scope for #107** — it is filed as **#117** and
  ContractCheck shipping with this drift signal on is the correct outcome (the tool's
  job is to make the gap visible; closing the gap is #117's job).

- **§11.3 deferrals** — DocConsistency v2: class (b) API signature drift, class (c)
  docstring-vs-code drift, class (d) symbol-existence drift (3 separate follow-up
  efforts per spec §11.3).

- **§11.4 deferrals** — GitArchaeology displacement of 4 direct-`git` sites in
  `src/` and 4 in `scripts/` left in place; broader displacement is a separate effort
  per spec §11.4.

- **§11.5 deferrals** — ContractCheck periodic wiring (#111 will add scheduled
  invocation of verify); currently opt-in CLI only per spec §11.5.

## [v0.36.64] — 2026-05-25 — Sim conn-lifecycle leak fix + PROD audit (#100)

### Fixed

- sim test-harness: connection-lifecycle leak (#100). Back-to-back smoke /
  full_gate runs no longer accumulate idle-in-txn / idle-stale PG backends.
  Primary fix: Oracle.assert_all() now rolls back self.conn in a try/finally
  per invariant, so a half-aborted transaction from check N cannot poison
  check N+1. Secondary fix: 7 cursor sites in oracle/_checks_db.py,
  oracle/_checks_signal.py, and scenario.py converted to
  `with conn.cursor() as cur:`. Plus 2 autocommit cursor sites in
  entrypoints/full_gate.py and entrypoints/smoke.py (operator-added expansion).

### Added

- `src/simulation/lifecycle/_leak_detector.py` — pure-query helper that
  snapshots pg_stat_activity. Supports `application_name_filter` for
  single-tenant isolation. Prints operator-readable recovery hint to
  stderr when the test PG is at max_connections (the exact failure mode
  the helper is designed to diagnose).
- `tests/simulation/lifecycle/test_no_conn_leak.py` — inner-mechanism
  witness test (PRIMARY) + 3x-loop accumulator backstop. Env var
  `SIM_LEAK_LOOP_ITERATIONS` opts the backstop into stress mode.
- `docs/audits/2026-05-24-sim-conn-leak/audits/2026-05-24-prod-leak-audit.md` —
  PROD code-path audit (document-only). Three follow-up tasks filed:
  #100-followup-A (bracket_attach.py:126 LEAK on exception path, P2),
  #100-followup-B (broker_exception_logger.py:51 explicit close discipline, P2),
  #100-followup-C (watch.py:1495 _check_row_counts PARTIAL — no close on except
  branch, P3, batch with watch.py audit).

### Unchanged (explicit)

- PROD watch-loop conn pool behavior is bit-for-bit identical.
- `prod_guard.install_prod_guard()` sentinel and monkeypatch untouched.
- `Oracle` signature is unchanged.

## [v0.36.63] — 2026-05-25 — Tier 2 Tools (#106): five composable Python-API + CLI tools (first mutating tools)

Implements Arcis #106 Tier 2 tools building on the #104 safety foundation + #105 Tier 1 patterns. Introduces the **first mutating tools** in the suite (ProcessManager start/stop/restart, PRComments post), with corresponding @safety_window first-production-consumer (no_restart_overnight) and secret-leak pre-flight (PRCommentLeakError + new `secret_leak_block` audit kind).

### Added — five tools

- **ProcessManager** (`src/tools/processmanager/`) — nssm wrapper for the 3 Arcis services. POSITIVE 7-state vocabulary (`SERVICE_RUNNING`/`STARTING`/`STOPPING`/`PAUSED`/`PAUSE_PENDING`/`CONTINUE_PENDING`/`STOPPED`/`UNKNOWN`) — does NOT inherit `archive_bootcamp_2026_04_24.py:157-169` NEGATIVE-style parse. `restart` is the FIRST production consumer of `@safety_window('no_restart_overnight')`. **DA2 sustained-running wait-and-verify (DD-16):** after first `RUNNING` observation, polls 3 more 1s intervals; any non-`RUNNING` observation resets the consecutive-counter (catches NSSM AppRestartDelay flap where a crashing-then-relaunched service shows transient `RUNNING`). Overall deadline 33s. Log-evidence check happens AFTER sustained-running confirmation, not during. PID-scoped `taskkill /f /t /pid <pid>` (NEVER `/im`, NEVER `Stop-Process -Name`) per `ollama_watchdog.py:226-227` discipline.

- **HealthProbe** (`src/tools/healthprobe/`) — composite read-only check: NSSM state + heartbeat freshness + port reachability + recent ERROR count. Per-service staleness defaults 60s (watch_loop) / 30s (ollama_watchdog) / 300s (dashboard). Verdict matrix worst-of `OK` / `DEGRADED` / `DOWN`. Imports `nssm_status` from ProcessManager (Tier-2 → Tier-2 read-only inheritance) and `tail` from Tier 1 v0.36.62 logtail (FB3 hard dependency — no fallback).

- **PRComments** (`src/tools/prcomments/`) — greenfield `gh pr comment` wrapper with content-based **secret-leak pre-flight** (`PRCommentLeakError`). Uses `gh pr comment --body-file -` via stdin pipe (DD-14 — never `--body STRING` to avoid shell-escaping risk). FB6: gh >= 2.0 documented (not pre-flighted); auth failure surfaced as `GhCommandFailedError` with hint kwarg; rate-limit stderr passthrough verbatim (no retry/backoff). NO `@safety_window` (GitHub writes are low-risk + rate-limited).

- **CapabilityRegistryQuery** (`src/tools/capabilityregistry/`) — pure-registry inspection via `dataclasses.asdict(src.schema.registry.TABLES)`. V1 — no DBQuery composition (Tier 3 ContractCheck deferred). The PERMITTED EXCEPTION (`from src.schema.registry import TABLES`) to the §2.2 forbidden-imports list applies ONLY here (DD-13).

- **TestPatternScan** (`src/tools/testpatternscan/`) — AST-based static analyzer for 4 test anti-patterns. Defaults: `vacuous` + `patch_drift` ON; `mock_only` + `side_effect_unreached` opt-in via `--kinds`. **DA4 PURE-AST resolver (DD-5):** PatchDriftRule uses `importlib.util.find_spec` (import-free) + `ast.parse` of `.origin` file + top-level name collection — NEVER `importlib.import_module`, NEVER `__import__`. Scanning a test that patches `src.api.app.X` does NOT trigger `load_dotenv` / DB connections / FastAPI app instantiation (verified by poison-trap test).

### Added — foundation helpers

- **`src/tools/_secrets.py`** — content-based secret scanner. 15 high-confidence patterns (DA3-extended: `ghp_` / `github_pat_` / `gho_` / `ghs_` / `ghu_` / `glpat-` / `sk-` / `sk_live_` / `pk_live_` / `xox*` / JWT 3-segment / `password=` / `Authorization: Bearer` / PEM / `AKIA`) + high-entropy fallback (40+ char base64-like) catching AWS secret access keys + unknown vendor tokens. Returns 3-tuple `(is_leak, redacted_preview, kind)` where `kind ∈ {'known_prefix', 'high_entropy_unknown', 'none'}`. T1 cycle-1 Security fix: always runs the high-entropy fallback after the known-prefix loop (defense-in-depth — multi-match bodies get BOTH regions redacted).

- **`src/tools/_subprocess.py`** — shared `run(args, *, timeout, check, input_data)` wrapper enforcing `capture_output=True`, `text=True`, `encoding='utf-8'`, NEVER `shell=True`. Cached `resolve_exe(name)` via `@lru_cache(maxsize=4)` with `NssmMissingError` / `GhMissingError` install hints (gh hint includes ≥ 2.0 requirement).

### Added — config

- **`paths.watchdog_heartbeat`** (DD-10/FB2) — new explicit config key, default `C:/arcis/halcyon-lab/data/watchdog.txt`. Replaces the would-be-wrong `cfg.paths.db_canonical.parent / 'watchdog.txt'` (which resolves to `C:/arcis/data/watchdog.txt`, NOT the actual NSSM AppDirectory). Decouples ProcessManager.restart + HealthProbe.heartbeat from `db_canonical.parent` derivation and from `scripts/statusline.py:38-55`'s `_resolve_data_root()` discovery walk. Statusline can opt-in post-merge.

### Extended

- **`_VALID_RESULTS`** in `src/tools/_execution_log.py` gains `'secret_leak_block'` — emitted by PRComments.post on `PRCommentLeakError`. `tests/tools/test_execution_log.py` parametrize extended atomically + new `test_valid_results_frozenset_exhaustive` asserts the frozenset equals the exact 6-element literal (FB1 drift detector).

### Test coverage

- 178 tests in `tests/tools/` (was 101 at v0.36.62 ship), +77 new across the 7 task deliverables.
- Real-seam smoke tests (FB5/DD-15) with `@pytest.mark.skipif(shutil.which('X') is None)` gates:
  - `test_processmanager_real_nssm_smoke` — verifies real `nssm.exe status` parses against `_STATE_MAP`
  - `test_prcomments_real_gh_smoke` — verifies real `gh pr view --json comments` JSON maps to `PRComment` dataclass
- DA2 flap-detection test uses canned `[RUNNING, STOPPED, RUNNING, RUNNING, RUNNING]` sequence; asserts `elapsed_s > 5s` AND consecutive-counter reset on STOPPED AND log-evidence check happens AFTER sustained-running.
- DA4 side-effect-safety test installs poison-traps on `dotenv.load_dotenv`, `sqlite3.connect`, `psycopg2.connect` + asserts `DATABASE_URL` env unchanged after scanning a test that `@patch('src.api.app.X')`.

### Anti-patterns explicitly NOT inherited (DD-8)

| Anti-pattern | Cited at | Tier-2 alternative |
|---|---|---|
| `_sc_query_running` (no-timeout + bare `except`) | `src/scheduler/watch.py:130-147` | `_subprocess.run(..., timeout=N)` + typed errors |
| Double-soft swallow wrapping `_sc_query_running` | `src/scheduler/watch.py:1161-1163` | Typed errors propagate all the way up |
| Silent `FileNotFoundError` on missing nssm | `scripts/archive_bootcamp_2026_04_24.py:166` | `NssmMissingError(SubprocessError)` with install hint |
| NEGATIVE state parse (`'SERVICE_STOPPED' not in stdout`) | `scripts/archive_bootcamp_2026_04_24.py:157-169` | POSITIVE `_STATE_MAP` iteration (7-state vocab) |
| Kill-by-name (`taskkill /im`) | (already avoided) | PID-scoped only (mirrors `ollama_watchdog.py:180-260`) |
| CWD-relative `Path('data/watchdog.txt')` + discovery-walk read | `src/scheduler/watch.py:1722-1734` + `scripts/statusline.py:38-55` | `cfg.paths.watchdog_heartbeat` (DD-10) — explicit config key |

### References

- Spec: `docs/audits/2026-05-24-tier2-tools/specs/2026-05-24-tier2-tools-design.md`
- Plan: `docs/audits/2026-05-24-tier2-tools/plans/2026-05-24-tier2-tools.md`
- Foundation: v0.36.57 #104 (`_config.py`, `_safety.py`, `_execution_log.py`) + v0.36.62 #105 (`_db.py`, `_cli_envelope.py`, `logtail`, `dbquery`, `tradingstate`, `symbolfind`, `ciinvestigate`)
- Memory: `feedback_complete_efforts_no_deferral` (all review-driven changes addressed in this PR — T1 cycle-1 Security fix for multi-match leak landed in the same sprint, no follow-up deferred)

## [v0.36.62] — 2026-05-24 — Tier 1 Tools (#105): five composable Python-API + CLI tools

Implements Arcis #105 Tier 1 tools building on the v0.36.57 #104 foundation (`_config.py`, `_safety.py`, `_execution_log.py`). Five tools, each shipped as a per-tool subpackage callable via Python API or `python -m src.tools.<name>` CLI.

### Added

- **Five composable tools** under `src/tools/`:
  - `dbquery/` — read-only `SELECT`/`WITH` executor with server-side cursor streaming (`named_cursor='dbquery_stream'`, `fetchmany(limit+1)` with `truncated` flag) for jsonb safety. Two-layer read-only: regex (`^\s*(SELECT|WITH)\s` pre-connect) + `pg_connect(read_only=True)`. `@safe_op` OUTER + `@prod_guard` INNER. CLI `--help` carries KC2 operator-trust + jsonb warnings.
  - `logtail/` — multi-line-aware backward tail with NSSM-rotation-safe semantics (DA5: `os.fstat` before + after read; size shrink → `LogTailError('file rotated/truncated mid-read; retry')`). Default `log_path` = `cfg.paths.logs_runtime / 'arcis.log'`. `--level` respects hierarchy; `--grep` matches joined entry text.
  - `ciinvestigate/` — `gh run view` wrapper with **atomic write** (`tempfile + fsync + os.replace` — Windows NTFS handles concurrent writers as atomic refusal) + **corrupt-cache self-heal** (`JSONDecodeError → unlink + refetch + WARNING`) + **`updatedAt`-validated cache freshness** (DA3 — `gh run rerun` mutates `conclusion`/`jobs`/`updatedAt`; head-check detects this on every cache hit). Cache: `data/cache/ci-investigate/<run_id>.json`.
  - `symbolfind/` — `rg --json --type py`-backed Python symbol lookup. `kind='def'` (class/def line + module-level constant assignment), `'use'` (references minus def lines), `'any'` (union dedup by `(file, line)`). `re.escape(symbol)` prevents regex injection; `--` argv sentinel for defense-in-depth against future flag-shaped paths. Fails fast with `winget install BurntSushi.ripgrep.MSVC` hint when rg missing.
  - `tradingstate/` — single-shot snapshot: open positions + most-recent audit + GPU health. **DA2 snapshot consistency**: all 3 PG queries on a SINGLE connection with `isolation_level='REPEATABLE READ'` — guarantees point-in-time view even under concurrent watch-loop writes. SQLite fallback on `psycopg2.OperationalError`. Missing GPU metrics yield `None` (NOT `False`) — distinguishes "not measured" from "measured failing".

- **Per-tool subpackage layout** (`src/tools/<name>/{__init__.py, __main__.py, core.py, ...}`) — Tier 2 inherits.

- **Sub-module-when-needed pattern (§4.8)** — TradingState splits into `core.py` (Python API + decorators, ≤300 LOC) + `queries.py` (SQL constants for PG + SQLite variants) + `render.py` (3-section markdown, ≤200 LOC). DBQuery/LogTail/CIInvestigate/SymbolFind do NOT split (cores ≤500 LOC). Tier 2 ShadowClose/PromoteModel/Postmortem will split.

- **`src/tools/_db.py`** — thin psycopg2 `pg_connect` contextmanager supporting `read_only`, `isolation_level='REPEATABLE READ'`, `named_cursor`, `timeout` kwargs. Always `RealDictCursor`. Does NOT couple to `src.config` / `src.utils.db` (spec §2.2 forbidden-imports).

- **`src/tools/_cli_envelope.py`** — shared `run_cli` helper for `--json` error envelope (DA6). Schema: `{"error": {"type": "<ExceptionClassName>", "message": "<sanitized>", "tool": "<tool_name>"}}` to stdout + `sys.exit(1)`. Message routed through `src.utils.secret_redact.sanitize_error` per spec §4.4 (Audit #414 precedent).

- **Tool cache convention** — `data/cache/<tool-name>/`. CIInvestigate writes `<run_id>.json` atomically.

- **Decorator contract (§4.7)** — `@safe_op` OUTER; `@prod_guard` (and Tier 2's `@safety_window`) INNER. Each guard writes its OWN terminal-state event (`'prod_guard_block'`, `'safety_window_block'`); `@safe_op` does NOT double-log `SafetyError` subclasses (verified at `src/tools/_safety.py:146-147`). Every tool's integration test asserts: `prod_guard_block` present AND zero duplicate `'error'` events.

### Fixed

- **`src/tools/_execution_log.py`** — extend `_sanitize_dsn` to handle libpq key=value form (`host=... password=PASSWORD`) via new `_LIBPQ_PASSWORD_RE`. Pre-existing T1 weakness: the URL-only `_DSN_PASSWORD_RE` left libpq-form passwords verbatim in `data/logs/tool-execution.log` when operators passed `--dsn` to T1+ tools. Now redacted while preserving `host`/`port`/`user` for diagnostics. New unit + integration tests pin the contract.

### CLI conventions established for Tier 1+ tools

- argparse, long-form flags, `--json` boolean toggle.
- Under `--json`, errors are emitted as a JSON envelope to stdout + exit 1; without `--json`, traceback prints to stderr as usual.
- `subprocess.TimeoutExpired` is wrapped as the tool's own error class (SymbolFindError, CIInvestigateError) per spec contract; `from None` suppresses argv disclosure via chained traceback.

### Test coverage

- 101 tests in `tests/tools/` (was 56 in v0.36.61): 7 DBQuery, 7 LogTail, 9 CIInvestigate (incl. DA1 concurrent-writers + corrupt-cache + DA3 rerun-invalidation), 8 SymbolFind, 6 TradingState integration + 4 TradingState CLI, 5 `_db.py`, 3 `_cli_envelope.py`, plus pre-existing 56.
- Schema-drift discipline locked: zero `opened_at` / `overall_verdict` substrings in `src/tools/tradingstate/` + tests (the canonical F3/F4 regression).
- Decorator-contract: every `@prod_guard`-decorated tool (DBQuery, TradingState) has an integration test asserting exactly-one terminal-state event under prod-DSN signature.

### References

- Spec: `docs/audits/2026-05-24-tier1-tools/specs/2026-05-24-tier1-tools-design.md`
- Plan: `docs/audits/2026-05-24-tier1-tools/plans/2026-05-24-tier1-tools.md`
- Foundation: v0.36.57 #104 (`_config.py`, `_safety.py`, `_execution_log.py`)
- Memory: `feedback_complete_efforts_no_deferral` (all review-driven changes addressed in this PR, no deferral)

## [v0.36.61] — 2026-05-24 — Deferred-test cleanup (#92 follow-up): test_version.py + test_schema.py mock-target drift

Closes the two pre-existing test failures the v0.36.60 PR (#1172) deferred to "Out of scope". The deferral was the trigger for the operator's new `feedback_complete_efforts_no_deferral` memory ("within an effort deliver ALL of it OR scope the effort smaller; never punt sub-items to operator-memory"); this PR fixes the deferred items directly per that standard.

### What ships

- **`tests/test_version.py`** — 3 assertions hardcoded `"v0.36.50"` had been broken on `main` since v0.36.51. Refactored to use two module-level constants (`_EXPECTED_VERSION = "v0.36.61"`, `_EXPECTED_BARE_SEMVER = "0.36.61"`) so every future release PR is a 2-line bump alongside the `src/version.py` change. Updated the module docstring to document the version-lock intent (the test deliberately fails on version drift to force the PR author to also update CHANGELOG).

- **`tests/test_schema.py::test_fetch_closed_trades_*`** — both tests patched `src.api.cloud_routes.kpis_compute.get_closed_shadow_trades` but `_fetch_closed_trades` dispatches via `DATABASE_URL` env: when set (operator's runtime env), it calls `_fetch_closed_trades_from_postgres` and the original mock was a no-op. Tests reported `psycopg2.errors.UndefinedTable: relation "shadow_trades" does not exist` locally because the mock never intercepted the actual call — a classic `feedback_vacuous_test_pattern` (the mock was theatrical). Replaced both with `@pytest.mark.parametrize` over both dispatch branches:
  - `sqlite` variant: `monkeypatch.delenv("DATABASE_URL", raising=False)` + patches `get_closed_shadow_trades`
  - `postgres` variant: `monkeypatch.setenv("DATABASE_URL", ...)` + patches `_fetch_closed_trades_from_postgres`
  Each variant patches exactly one path (not both), so mock-target drift in EITHER dispatch branch surfaces immediately as the function attempting a real DB query against missing fixtures rather than passing vacuously. Locks both branches against the same class of drift.

### Why this exists at all

- v0.36.60 PR body had an "Out of scope (pre-existing failures surfaced during testing)" section listing these two items. Operator wrote `feedback_complete_efforts_no_deferral` in response, noting both were inside-the-effort work that should not have been deferred (the test_version.py fix is literally one line of arithmetic; the test_schema.py is a vacuous-test bug fix matching `feedback_vacuous_test_pattern` already-encoded rigor).

### What this PR is NOT

- **Not a refactor of the version-lock pattern.** Some projects derive the test assertion from `src.version.VERSION` itself, making the test self-syncing. That's a richer design but loses the "force the author to acknowledge the bump" property. Keeping the literal-assert pattern; just lifted the literal to a module-level constant.
- **Not a redesign of `_fetch_closed_trades` dispatch.** The function continues to dispatch on `DATABASE_URL` env; the parametrize covers both branches without changing the production code.

### References

- Memory `feedback_complete_efforts_no_deferral` — the standard this PR enforces
- Memory `feedback_vacuous_test_pattern` — the bug class this PR closes for `test_fetch_closed_trades_*`
- PR #1172 (v0.36.60) — the parent PR that deferred these items

## [v0.36.60] — 2026-05-24 — PG table-ownership fix (#92): 5 tables + 2 sequences transferred to halcyon_app, restore-drift wire-up added

Fourth of the `project_w21_attack_order` phase-4 wedges (after v0.36.55 #101 CI hygiene, v0.36.57 #104 tooling foundation, v0.36.59 #103 reviewer prompts). "Same failure class as 2026-05-14 DROP SCHEMA permission-denied loop. Quick `ALTER TABLE … OWNER TO halcyon_app`. High-impact safety fix." — operator's brief for #92.

### Background

On 2026-05-14, `DROP SCHEMA public CASCADE; CREATE SCHEMA public` followed by `psql -U halcyon -f snapshot.sql` left all restored tables owned by the `halcyon` superuser instead of the runtime app role `halcyon_app`. The immediate watch-loop restart loop was patched via the GRANT block in memory `feedback_drop_schema_grant_pattern`, but five tables silently kept the wrong owner. Discovery query on 2026-05-24 confirmed: `recommendations`, `shadow_trades`, `sync_state`, `traffic_light_state`, `vix_term_structure` were still owned by `halcyon`; two associated SERIAL sequences (`traffic_light_state_id_seq`, `vix_term_structure_id_seq`) had drifted alongside.

The existing workaround in `tests/test_cutover_pg_schema_migrate.py::test_cutover_migrate_ok_not_yellow_on_ownership` documented this as "EXPECTED + non-actionable" — that workaround is now defense-in-depth, since the historical cases are fixed at the source.

### What ships

- **NEW `schema/migrations/2026-05-24_table_ownership_fix.sql`** — one-shot migration. `ALTER TABLE OWNER TO halcyon_app` for the 5 tables, `ALTER SEQUENCE OWNER TO halcyon_app` for the 2 sequences, plus the load-bearing GRANT + ALTER DEFAULT PRIVILEGES block from `feedback_drop_schema_grant_pattern` (idempotent re-apply). Operator-gated: NOT auto-applied by the runtime. Apply via `docker exec -i halcyon-pg psql -U halcyon -d halcyon < schema/migrations/2026-05-24_table_ownership_fix.sql`. Establishes `schema/migrations/` as the convention for future versioned schema operations.

- **`scripts/render_to_local_migrate.py`** — NEW function `apply_ownership_reconciliation(dest_url)` discovers misowned tables/sequences and ALTERs them, then applies the GRANT block. Wired into `run_migration()` immediately after `create_all_tables()` so any future render→local restore (the 2026-05-14 code path) cannot leave ownership skewed. Upfront role/privilege checks: raises if `halcyon_app` role missing (silent no-op would mask misconfiguration); cleanly skips with WARN if current user lacks superuser or halcyon_app membership; conditionally skips `halcyon_readonly` GRANTs when that role is absent (ephemeral test PG topology). Idempotent.

- **NEW `tests/test_table_ownership.py`** — two regression-lock test classes:
  - `TestOwnershipReconciliationEphemeral` — boundary-touch test against the docker-compose.test.yml PG (port 5434). Creates the prod-mirror role topology, drops misowned tables, drives `apply_ownership_reconciliation()`, asserts the policy holds. Four tests covering tables, sequences (drift independently from tables — separately regression-locked), idempotency, and hard-fail when halcyon_app role missing. Conforms to `docs/standards/boundary-touch-tests.md` (the v0.36.59 standard): real PG, no mocks at the seam, assertions on actual `pg_tables` state.
  - `TestLiveOwnershipPolicy` — skip-unless-flagged policy assertion (`ARCIS_LIVE_OWNERSHIP_CHECK=1` + `ARCIS_ALLOW_PROD_PG_IN_TESTS=1`). Operator-run on-demand against the runtime PG; RED pre-migration, GREEN post-migration.

- **`tests/test_cutover_pg_schema_migrate.py`** — updated docstring on `test_cutover_migrate_ok_not_yellow_on_ownership` citing v0.36.60 resolution of the five historical cases. The test stays as defense-in-depth for any FUTURE drift.

### Application procedure (operator-gated)

1. Verify discovery on live PG: `docker exec halcyon-pg psql -U halcyon -d halcyon -t -c "SELECT tablename, tableowner FROM pg_tables WHERE schemaname='public' AND tableowner != 'halcyon_app';"` — expect the 5 tables.
2. Apply migration as halcyon superuser: `docker exec -i halcyon-pg psql -U halcyon -d halcyon < schema/migrations/2026-05-24_table_ownership_fix.sql`.
3. Re-run discovery query — expect zero rows.
4. (Optional) `ARCIS_LIVE_OWNERSHIP_CHECK=1 ARCIS_ALLOW_PROD_PG_IN_TESTS=1 pytest tests/test_table_ownership.py::TestLiveOwnershipPolicy -v` for explicit confirmation.

### What this PR is NOT

- **Not a runtime-applied auto-migration.** ALTER OWNER requires superuser (the runtime role `halcyon_app` cannot reclaim ownership of tables it doesn't own); the migration MUST be operator-run as halcyon.
- **Not a startup self-heal.** Per operator decision, the prevention layer lives in `render_to_local_migrate.py` only — adding runtime self-heal would require the runtime to run as halcyon superuser, contradicting least-privilege.
- **Not a CI-runnable live check.** `TestLiveOwnershipPolicy` is skip-unless-flagged precisely because the conftest P0 guard (born from the 2026-05-14 / 2026-05-17 prod-wipe incidents) refuses pytest against prod-PG signatures by default.

### References

- Memory `feedback_drop_schema_grant_pattern` — 2026-05-14 incident + the GRANT block (this PR completes its scope by adding the ownership half)
- Memory `project_w21_attack_order` — phase-4b sequencing (after #101/#104/#103, before #100/#86/#51/#77)
- `docs/standards/boundary-touch-tests.md` (v0.36.59) — followed for `TestOwnershipReconciliationEphemeral`
- 2026-05-14 incident pattern: DROP SCHEMA + restore-as-superuser leaves wrong owner → permission-denied restart loop

## [v0.36.59] — 2026-05-24 — Reviewer-prompt + standards doc (#103): boundary-touch + vacuous-test + sibling-search discipline formalized

Third of four phase-4 early wedges per `project_w21_attack_order` (after v0.36.55 #101 CI hygiene + v0.36.57 #104 tooling foundation). "Half-day work, no infra dependency. Would have caught all 3 v0.36.51-53 bugs at review time. Every phase-4 hotfix benefits from sharper reviewer prompts." — operator's brief for #103.

### What ships

- **NEW `docs/standards/boundary-touch-tests.md`** — single-file standards doc covering the boundary-touch test discipline, the vacuous-test anti-pattern, the empirical-verification gold standard (subprocess-remove-impl-and-rerun), and the sibling-search principle. Authoritative for `.claude/plugins/arcis/agents/coding-{qa,security,rigor}-reviewer.md`. Cites the v0.36.51-53 mock-coverage-gap chain as cases-that-would-have-been-caught, and `tests/tools/test_safe_op_integration.py` from v0.36.57 #104 as the canonical positive example. Includes a 7-row "when this applies" table + pre-merge checklist.

- **`.claude/plugins/arcis/agents/coding-qa-reviewer.md`** — adds new workflow step 4 (Test rigor check) + step 5 (Sibling-search check), each citing the standards doc. Step 4 enumerates four concrete sub-checks (mock target resolution, method/attribute name resolution, vacuous-test detection, boundary-touch coverage) with the gold-standard question made explicit. CONSTRAINTS section adds non-negotiable enforcement language: "A 'passing' PR with vacuous tests or unresolved mock targets is a `must_fix` finding even if every spec requirement is technically met."

- **`.claude/plugins/arcis/agents/coding-security-reviewer.md`** — adds new workflow step 5 (Sibling-search on every finding). Includes four concrete grep recipes per vulnerability class (injection, access control, secrets exposure, hardcoded credentials). CONSTRAINTS section adds the "incomplete finding without sibling-search" rule with explicit suggested marker text.

- **NEW (imported from user-cache) `.claude/plugins/arcis/agents/coding-rigor-reviewer.md`** — 264-line elaborate C1–C7 advisory PR-comment rubric was sitting only in the user-cache at `~/.claude/plugins/cache/halcyon-local/arcis/0.1.0/agents/`, never committed to the repo. Imported as source-of-truth (this PR captures the cache/repo divergence). Augmented with:
  - **C5.5** Vacuous-test detection (mocks `side_effect` or asserts `_not_called()` but the branch never reached → `BLOCKER`)
  - **C5.6** Boundary-touch coverage when composed contracts are introduced (decorators / pipelines / schema mirrors → at least one real-composition test or `ADVISORY` / `BLOCKER` for safety-critical seams)
  - Three-form sibling-search regex in step 3, with the historical-miss-rate note (`from X|import X|X.` catches the dotted-attribute-string `@patch` decorator references the single-form grep misses ~30% of)

### Why this lands NOW (before #105 Tier 1 tools)

Per the operator's brief: "Every phase-4 hotfix benefits from sharper reviewer prompts." The remaining phase-4 backlog (#92 / #100 / #86 / #51 / #77 plus the Tier 1+ tooling track #105 onward) will be reviewed by the same three reviewer agents. Each downstream hotfix now gets the boundary-touch + vacuous-test + sibling-search checks for free, without needing to embed reminders in every dispatch prompt.

### What this PR is NOT

- **Not a runtime change.** Zero `src/*.py` edits, zero test edits, zero schema edits. Pure prompt + docs.
- **Not a hookify rule.** The hookify-rule version of "enforce vacuous-test detection" would be a separate task (PreToolUse on test edits), out of scope here.
- **Not a backfill audit.** v0.36.51-53 already shipped. The discipline applies prospectively — future PRs are reviewed against it, past PRs are not retroactively re-reviewed.

### Cache-vs-repo discovery

The `coding-rigor-reviewer.md` existed only in `~/.claude/plugins/cache/halcyon-local/arcis/0.1.0/agents/` — not in `.claude/plugins/arcis/agents/`. Without this PR, edits to the cache copy would silently get reverted on the next plugin-publish cycle. Committing it captures the divergence; future edits land in the repo and propagate to cache via the normal flow.

### References

- Memory `feedback_vacuous_test_pattern` — gold-standard question + empirical verification, v0.36.22 + #94 T18 origin cases
- Memory `feedback_review_sibling_search` — PR #690 origin + PR #1055 three-form regex
- Memory `feedback_strict_rigor_no_handwave` — operator-stated "rather take a full day than hand wave"
- v0.36.51 / v0.36.52 / v0.36.53 CHANGELOG entries — the bugs the discipline targets
- v0.36.57 #104 CHANGELOG entry — anticipated this standards doc formalization

## [v0.36.57] — 2026-05-24 — Tooling foundation (#104): central `arcis_config.yaml` + safety primitives (SafeOp / SafetyWindowGuard / ProdGuard) + JSON-lines tool-execution audit log

Foundation for the entire Tier 1+ tool suite (#105 onward). **No tools are built in this PR** — pure infrastructure that future tools import. Gap-fill between v0.36.56 (gpu_health writer restore) and v0.36.58 (#118 venv wrapper-PID escape) — the operator's #104 brief explicitly reserved v0.36.57 for this task at the time those PRs merged out-of-sequence.

Per `project_w21_attack_order` this is the second of four phase-4 early wedges (after #101 CI hygiene). Once it lands, #105 Tier 1 tools (DBQuery, LogTail, CIInvestigate, SymbolFind, TradingState) can launch in a future session against this foundation.

### What ships

- **`config/arcis_config.yaml`** — single source of truth for paths, ports, NSSM service names, safety windows, and prod-PG DSN signatures. Replaces the (previously diffuse) need for tool code to hardcode `C:/arcis/data/...` paths, `5433` ports, `ArcisWatchLoop` service names, the `21:30–22:30 ET` no-restart window, and the prod DSN signature list. Three concerns deliberately separate from `settings.local.yaml` (which is APPLICATION config — risk parameters, broker keys, council settings): tooling config encodes invariants of the dev box / deploy topology, application config is per-strategy. Schema cross-references each source memory (`reference_local_ports`, `feedback_no_restart_during_overnight_window`, `reference_watch_loop_management`) in YAML comments for operator-readable provenance.

- **`src/tools/_config.py`** — pydantic-based loader for `arcis_config.yaml`. Lean by design (no `.env` coupling, no FastAPI dependency) so it loads in isolation during pytest collection. `load_arcis_config(path=None) → ArcisConfig` is the only public API; `ArcisConfigError` wraps `FileNotFoundError` / `yaml.YAMLError` / `pydantic.ValidationError` so callers catch ONE class. The keystone boundary-touch test (`test_load_arcis_config_pg_signatures_match_prod_guard`) cross-asserts equality between `pg.prod_dsn_signatures` and `src/simulation/lifecycle/prod_guard.py:_PROD_SIGNATURES` — drift between the two is the single-source-of-truth violation this loader prevents.

- **`src/tools/_safety.py`** — three composable decorators:
  - `@safe_op(name=..., mutates=...)` — dry-run dispatch + audit-log every call. For `mutates=True` tools without `confirm=True`, returns a `DryRunResult` WITHOUT calling the wrapped function (function bodies only see the real-execution path). `DryRunResult` is a frozen dataclass with `__repr__` (operator-readable multi-line) + `to_json()` (parent-agent consumption) — operator-confirmed Q1 default during build (this thread).
  - `@safety_window("window_name", now_et=...)` — refuses ops inside operator-declared safety windows (e.g., `no_restart_overnight` 21:30–22:30 ET) unless `emergency=True` is passed (logged with `emergency=True` in params for grep-ability later). **Pluggable clock seam** per the #97 simulator's freezegun pattern — operator-confirmed Q2. Cross-midnight windows handled (`22:00–06:00` etc.).
  - `@prod_guard(dsn_param=...)` — rejects DSNs matching `pg.prod_dsn_signatures` unless **both** `ARCIS_ALLOW_PROD_PG=1` env AND `confirm=True` kwarg are set (env alone OR confirm alone is rejected — defense in depth). Generalizes `src/simulation/lifecycle/prod_guard.py`'s monkeypatch-on-psycopg2 pattern to a per-tool decorator usable by any DSN-taking tool.

- **`src/tools/_execution_log.py`** — JSON-lines tool-call audit at `data/logs/tool-execution.log` (operator-confirmed Q3 — co-located with NSSM service logs). Every event: timestamp (ISO 8601 with America/New_York offset, per the operator's ET-default discipline), tool_name, sanitized params, result (`success` / `dry_run` / `safety_window_block` / `prod_guard_block` / `error`), duration_ms, optional session_id. Sanitization handles two patterns: secret-keyed values (`password`, `api_key`, `token`, `secret`, `bot_token`, `access_key`) are wholesale-redacted; DSN-shaped values are partial-redacted (preserve scheme/user/host/db, redact password). Rotation at 10 MB to `.log.1` (one keep-back) mirrors NSSM service log rotation policy.

### Verification — boundary-touch discipline

**51 tests across 4 files:**
- `tests/tools/test_config.py` (10 tests) — loader, schema validation, secret-key drift cross-check
- `tests/tools/test_execution_log.py` (15 tests) — event shape, secret sanitization, ET-offset timestamp, rotation, all 5 result kinds
- `tests/tools/test_safety.py` (21 tests) — `DryRunResult` shape, SafeOp dry-run/confirm/error/log states, SafetyWindowGuard block/allow/emergency-bypass/cross-midnight, ProdGuard rejection/test-DSN-allow/env+confirm-bypass-defense-in-depth
- `tests/tools/test_safe_op_integration.py` (5 tests) — **the keystone boundary-touch test** the operator's #104 brief asked for: a fake tool composed with all three decorators driven through each of the 5 terminal states (dry-run / safety-block / prod-block / confirmed-success / emergency-bypass), asserting on the REAL audit-log file contents at each step. Critical invariant: SafetyError-class exceptions from inner guards do NOT double-log via safe_op's except clause — they propagate cleanly so the audit shows ONE specific `safety_window_block` or `prod_guard_block` event per blocked call, not a duplicate `error`.

The integration test is the discipline the operator's brief framed as "test the REAL behavior, not just 'the decorator is applied'" — single-primitive tests verify each guard in isolation; the integration test verifies the composition. Anticipates the standard #103 (boundary-touch-tests) will formalize.

### Disclosure — pre-existing structural violation surfaced

`src/scheduler/ollama_watchdog.py` is at 411 lines (max 400). Verified pre-existing as of `a8ea0977` (this PR's branch base = the v0.36.55 main HEAD). NOT introduced by #104. Added to `config/known_violations.json` with rationale: file grew past the limit during the #94 dual-GPU re-cutover (`ArcisOllamaWatchdog` NSSM service + GPU1 partition + crash-escalation + model-tag fallback chain re-introduced in v0.36.52). Refactor candidates: extract `_check_gpu_partition_health()` helper module, or pull model-resolution into a tiny `_model_resolution.py`. Real split deferred — out of scope for tooling-foundation work + watchdog is tightly coupled around poll-loop invariants.

### Follow-ups unlocked

- **#105 Tier 1 tools** (DBQuery, LogTail, CIInvestigate, SymbolFind, TradingState) can now import these primitives. Estimated ~1 day per attack-order.
- **#106 Tier 2 tools** + **#108 specialized agents** + **#109 `arcis:operate` skill** all inherit the safety + audit-log discipline from this foundation.

### Read first when extending the tool suite

- `feedback_audit_workflow_constraints` (least-privilege + crash-vs-finding distinction — generalizes to any future security/audit workflow)
- `feedback_strict_rigor_no_handwave` (verification mandatory: tests assert on REAL behavior, not decorator presence)
- `reference_local_ports` (8080 = EnterpriseDB; bind 127.0.0.1 explicitly)
- `feedback_no_restart_during_overnight_window` (the safety-window source of truth)
- `reference_watch_loop_management` (NSSM service names)

## [v0.36.58] — 2026-05-24 — Fix Windows venv wrapper-PID escape in `_launch_and_wait_training` — closes #94 phase-3 hard-kill GPU0-leak risk (#118)

Companion fix to v0.36.56. The 2026-05-24 GPU0 partition smoke (PR #1168 / `scripts/gpu0_training_partition_smoke.py`) observed a **40-PID gap** between `subprocess.Popen.pid` (3408480) and the smoke subprocess's `os.getpid()` (3408520). Investigation confirmed `.venv\Scripts\python.exe` on Windows is a thin launcher shim that re-execs the real interpreter as a CHILD `python.exe`. `_write_training_pid(proc.pid)` was therefore recording the **wrapper PID, not the GPU-using child**, creating a hard-kill silent-leak hazard: `training_control._cooperative_then_hard_stop` calls `proc.terminate()` (= `TerminateProcess` on Windows) which does NOT cascade to children. The GPU-using child could survive a "successful" training-stop with VRAM allocated until manual intervention. Cooperative-stop path was always fine because the child python itself watches `ARCIS_STOP_FLAG` directly — the leak surfaces only when cooperative-stop times out and hard-kill fires.

Operator gated #94 phase-3 close on resolving this (memory `project_w21_attack_order` #118). Hard-kill GPU0 leak risk is the last hard-gate concern; partition under load was validated by v0.36.56's smoke harness.

### What ships

- **`src/training/trainer.py`** — new `_resolve_tracked_pid(popen_pid, settle_timeout_s=5.0)` helper consults `psutil` post-Popen-settle and returns the actual GPU-using child PID when the launcher pattern is in play:
    - exactly 1 python child → return child PID (Windows venv case — the canonical fix)
    - 0 python children → return `popen_pid` (Linux/Mac/non-venv Windows — no-op preserved)
    - >1 python children → loud WARNING + fall back to `popen_pid` (operator can investigate; preserve pre-fix behavior so the anomaly is visible)
    - `psutil.NoSuchProcess` / `AccessDenied` / `ZombieProcess` → return `popen_pid` (caller's stale-pidfile path handles)
  `_launch_and_wait_training` now writes the resolved pid to `training.pid`. The settle timeout is bounded to 5s with 0.2s poll cadence so most cases resolve in <1s; never blocks launch indefinitely. Empirical compatibility check: child python has identical `cmdline` + `CUDA_VISIBLE_DEVICES=0` to the wrapper, so `training_control._is_tracked_training_proc(child_pid)` validates the same way it validated the wrapper pre-fix. The fix is transparent to the cooperative-stop path AND correctly targets the GPU-using process on the hard-kill path.

- **`tests/test_trainer_pid_resolution.py`** (NEW, 10 tests) — locks the resolution invariant:
    - canonical case (1 python child)
    - `python.exe` / `python3.13` name-prefix discipline
    - filter rejects non-python children
    - no-op fallback when zero children (Linux/Mac)
    - settle timeout enforces ≤1.5s wall-clock when no children appear (prevents launch latency regression)
    - operator-observability WARNING on multiple children
    - parametrized graceful-failure on `psutil.NoSuchProcess` / `AccessDenied` / `ZombieProcess`
    - end-to-end Windows-venv subprocess integration test (skipif non-Windows or no venv)

  10/10 pass on this box.

### Why this slipped past #94's 6+ reviews

`scripts/gpu_placement_smoke.py` (the existing T7 cutover gate) validated **Ollama-on-GPU1 placement** by launching `ollama serve` and checking nvidia-smi compute-apps. It did NOT exercise the **training-on-GPU0 launch path** because the upstream `_launch_and_wait_training` requires a fine-tune-eligible corpus (blocked by `HOLDOUT EMPTY` since 2026-05-22 — see #117). The wrapper-PID escape is invisible to the cooperative-stop path (which is what production hits 99% of the time) and the existing test fixtures use bare mocks for Popen so the wrapper-vs-child distinction never appeared. The v0.36.56 smoke harness (which exercises the production launch helpers directly with a torch CUDA tensor) is what surfaced the gap. **The fix is locked by 10 regression tests including a real Windows-venv subprocess integration test.**

## [v0.36.56] — 2026-05-24 — Restore `gpu_health_training_ok` writer dropped in v0.36.50 squash + GPU0 partition smoke harness (#94 follow-up)

Hotfix surfaced during the 2026-05-23 → 2026-05-24 overnight observation gate for the dual-GPU re-cutover. Phase-3 of the #94 design called for `gpu_health_training_ok` to be emitted from each of the three training-lifecycle handlers (evening launch + morning stop + market-open stop). The T8 telemetry commit (`27ddc305`, 2026-05-21) wired this up; the v0.36.50 squash (`25655cf0`, 2026-05-22) stripped the helper method AND all three call sites, leaving only the read side. As a result the metric never wrote post-cutover, and `schedule_metrics` showed no `gpu_health_training_ok` rows for 2026-05-22 / 23 / 24 — masking observability of training-lifecycle health.

### What ships

- **`src/scheduler/watch.py` — restore `_emit_training_health` helper + 3 call sites.** Re-adds the 18 lines stripped by the squash. Both `upsert_daily_metric("gpu_health_training_ok", 1.0, ...)` and `safe_send("gpu_health", direction="training", success=True, ...)` are wrapped in try/except so a transient metrics-backend failure or Telegram dispatch error can never crash the training-lifecycle handler. The metric carries the lifecycle phase in its `details` JSON (`"evening training launched"` / `"morning training stop"` / `"market-open training stop"`) so downstream readers can disambiguate. Idempotent on `(metric_date, metric_name)` — repeated emits on the same date UPDATE the same row.
- **`tests/test_gpu_health_telemetry.py` — 6 new writer-side regression-lock tests.** `test_emit_training_health_writes_metric` asserts `upsert_daily_metric` is called with the right key + value + detail. `test_emit_training_health_metric_exception_swallowed` and `test_emit_training_health_safe_send_exception_swallowed` lock the best-effort invariant — telemetry failures must not cascade into a missed overnight launch. Parametrized `test_training_lifecycle_runner_emits_health` asserts all three lifecycle runners call `_emit_training_health` with the right detail string. These locks would have caught the regression at squash review time. The original T8 writer-tests at `tests/scheduler/test_gpu_health_telemetry.py` were also dropped in the squash; this file is reader-only post-rename. 21/21 tests pass (15 reader + 6 new writer).
- **`scripts/gpu0_training_partition_smoke.py` — NEW operator-runnable GPU0 partition smoke harness.** Complementary to `scripts/gpu_placement_smoke.py` (which gates Ollama-on-GPU1 at cutover). Imports `trainer._assert_gpu0_identity`, `trainer._training_subprocess_env`, and `trainer._launch_and_wait_training` so the smoke exercises the SAME GPU0-pinning code path as production overnight training, but allocates a 4 GB CUDA tensor for 90s instead of fine-tuning. Live `nvidia-smi --query-compute-apps` monitor every 5s confirms smoke on GPU0 + Ollama on GPU1 throughout. Exit codes documented in module docstring (0/10/20/30/40). Used today to validate the dual-GPU partition under load when the upstream HOLDOUT EMPTY gate prevented an organic training cycle from exercising the path. Reuses the v0.36.51 `gpu_uuid` not `gpu_index` lesson (inlined the helper to avoid `scripts/__init__.py` package-import dependency).

### Why this slipped past #94's 6+ reviews

The squash combined 18 separate task commits (T1-T18) into the single v0.36.50 release. The T8 telemetry-emit additions to `_run_evening_training` / `_run_morning_training_stop` / `_run_market_open_training_stop` were lost when those methods were independently modified by other tasks (T9 rename to `_run_evening_training_launch`, T10/T11 stop_training_bounded signature changes). Same boundary-pattern as the v0.36.51-53 hotfix chain: a sufficiently complex multi-task PR can drop work at squash time without any individual reviewer seeing the deletion. Without writer-side tests pinning the `_emit_training_health` call sites, no test caught the regression. Locked in this PR via the 6 new writer-regression tests.

### Follow-ups filed (memory: `project_w21_attack_order`)

- **#117 corpus-stale-since-5/22** — `[OVERNIGHT] Collected 0 training examples` since 2026-05-22, causing HOLDOUT EMPTY skip on every overnight cycle. Independent of #94 partition. Operator-authorized investigation today.
- **#118 wrapper-PID escape** — `_write_training_pid(proc.pid)` writes the Windows venv launcher wrapper PID, not the actual GPU-using child python (40-PID gap observed in smoke). `stop_training_bounded` hard-kill (`TerminateProcess`) hits wrapper only — child keeps VRAM. Cooperative-stop path is unaffected (child watches `ARCIS_STOP_FLAG` directly). Operator gated #94 phase-3 close on resolving this.

## [v0.36.55] — 2026-05-23 — CI workflow hygiene (#101): PR-only path filter on lifecycle-smoke + installed-packages cache + training-requirements relocation closes the auto-submission parser issue at the source

W21 phase-4 first early-wedge per the operator's attack-order (memory: `project_w21_attack_order`). Lands BEFORE the remaining hotfix backlog (#92 / #100 / #86 / #51 / #77) so each downstream PR benefits from the optimized CI throughput. No application-code changes — pure workflow surgery + one repo-layout move.

**QA history on this PR:** the first iteration (commit `d4b504c3`) added a `.github/workflows/dependency-submission.yml` using `pypa/gh-action-pip-audit` to replace the failing GitHub auto-submission. The Opus QA review caught a load-bearing-claim failure: `pypa/gh-action-pip-audit` is a *vulnerability scanner*, NOT a dependency-submission action. Verified against the action's own `action.yml` description and v1.1.0 README (zero references to dep-graph / submission / dependabot). Operator chose Path (c) over the QA's recommended Path (a): relocate `requirements-training.txt` OUT of GitHub's auto-submission scan range — a root-cause fix that lets the existing auto-submission run cleanly on the base `requirements.txt`. Dep-submission.yml dropped from this PR; vuln-audit work filed as #116 (post-#101 follow-up) with two locked-in design constraints (memory: `feedback_audit_workflow_constraints`).

### What ships

- **lifecycle-smoke.yml — PR-trigger path filter, push:main unfiltered safety net.** `on.pull_request` now restricts to `paths: ['src/simulation/**', 'tests/simulation/**', '.github/workflows/lifecycle-smoke.yml']` — most PRs don't touch the simulation pipeline, so the ~9.5min smoke job is now skipped on those. `on.push: branches: [main]` deliberately has NO `paths:` filter — every merge to main still runs the smoke as the safety net for upstream-refactor breakage. The smoke imports from `src/shadow_trading`, `src/schema`, `src/scheduler`, `src/risk`, `src/cost_model`, `src/llm`, `src/data_ingestion`, `src/universe`, `src/journal` — all upstream of `src/simulation/` at import time; a refactor to any of them that breaks the lifecycle would otherwise only be caught by the nightly lifecycle-full-gate, leaving a 24h reliability window during which #95 wipe-gate trust degrades. The asymmetry is intentional per the operator's strict-rigor policy: catch upstream-refactor regressions at MERGE TIME, not 24h later.

- **pg-tests.yml + lifecycle-smoke.yml — installed-packages cache (`env.pythonLocation`).** Both workflows now add an `actions/cache@v4` step keyed on `${{ runner.os }}-python3.12-pkgs-${{ hashFiles('requirements.txt') }}` with path `${{ env.pythonLocation }}` (the setup-python install root — captures site-packages + .pth files + entry-point scripts). Complementary to setup-python's existing `cache: 'pip'` (caches the wheel download cache at `~/.cache/pip`): the two together give cold-miss ~60-90s + warm-hit ~5s for the dep-install step. Key includes `python3.12` (so a future 3.13 bump doesn't poison the cache — `.so` files are cpython-version-specific) and `hashFiles('requirements.txt')` ONLY — `requirements-cloud.txt` (server-only) and `training/requirements.txt` (training-only, volatile unsloth git+URL, NOT installed in these CI jobs) would force unnecessary cold-cache rebuilds if hashed. The lifecycle-full-gate job inside pg-tests.yml gets the same cache step (shared key means it can share entries with the pg-tests job when requirements.txt matches).

- **`requirements-training.txt` → `training/requirements.txt` — root-cause sidestep for the auto-submission parser.** GitHub's auto-generated "Automatic Dependency Submission (Python)" workflow scans ALL `requirements*.txt` files in the **repo root** unconditionally. The training file at the repo root contained `unsloth[cu128-torch260] @ git+https://github.com/unslothai/unsloth.git` — a git+URL with extras + master-tracking ref that breaks the upstream parser. Result: submit-pypi RED on every push during 2026-05-23 cutover-hotfix chain (PRs 1163, 1164, 1165, 1166); 1162's eventual green was opportunistic, not stable (verified via `gh pr view` statusCheckRollup). Moving the file to `training/` (mirrors `src/training/` semantically — co-locates training-only deps with training-only code) puts it outside the auto-submission's default scan range. The auto-submission now sees only the clean base `requirements.txt` and runs cleanly on every push. **No new YAML files, no `gh api` settings flip post-merge, no replacement workflow needed.** The fix is permanent and survives any future churn of the training file (operator can swap unsloth git+URL → tagged release whenever, no CI re-tuning required). References updated: `scripts/generate_directory.py` (annotation dict key), `scripts/overnight_train.py` (install-instruction comment), `tests/test_dep_health_hardening.py` (test reads the file path), `tests/test_stop_callback.py` (module docstring), `.github/workflows/pg-tests.yml` + `.github/workflows/lifecycle-smoke.yml` (cache-step comments), `training/requirements.txt` itself (self-reference at top).

- **lifecycle-full-gate cadence — confirmed already correctly gated.** Brief item #2 was a verify-only step — the `lifecycle-full-gate` job inside `pg-tests.yml` already has `if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'` (no per-PR fire). Confirmed via PR 1162 status checks where it shows SKIPPED on `pull_request` events. The cache step is the only change to that job; the cadence guard was already correct from v0.36.54's #97 work.

### Net effect

- ~50 dep-install runs/week × ~75s = ~62 min/week → cache warm-hit ~95% = ~7 min/week (**~55 min/week saved**)
- lifecycle-smoke skipped on ~70% of PRs at PR-trigger time = **~95 min/week saved**
- submit-pypi no longer RED on every PR — fewer wasted ~3min flickers; operator no longer needs to disable it post-merge
- **Estimated total: ~600 min/month saved (~50% reduction), no security visibility regression, no new YAML to maintain**

### Verification on first PR after merge

1. First `lifecycle-smoke` + `pg-tests` runs after merge: cache MISS (cold). Install ~60-90s as before.
2. Re-trigger workflows (re-run from UI or push another commit): cache HIT. Install drops to ~3-5s. Confirm via the "Cache" step log line: `Cache restored from key: Linux-python3.12-pkgs-<hash>`.
3. Touch `requirements.txt` (add a trailing newline): cache MISS (different hash). Revert: cache HIT. Confirms invalidation works.
4. PR touching only docs / non-sim code: `lifecycle-smoke` SKIPS at PR-trigger time. Merge-to-main re-runs it as the safety net.
5. `submit-pypi` check on the next push:main after this PR merges: GREEN (auto-submission now scans only the clean base requirements.txt; no unsloth URL to choke on). The "Automatic Dependency Submission (Python)" workflow continues to populate the Insights → Dependency Graph view as before.

### Follow-ups filed

- **#116 — Add PR-time vulnerability scanning (vuln-audit follow-up from #101 QA).** Two locked-in design constraints per the operator's audit-workflow discipline (memory: `feedback_audit_workflow_constraints`):
  - `permissions: contents: read` ONLY (least-privilege; reject any template that hands write perm without action-doc justification)
  - NO blanket `continue-on-error: true` (workflow RED only on scan crashes; vuln-findings surface via job-summary in 3 distinct states: "no vulns" / "vulns found (N — see Dependabot)" / "scan crashed")

**Read first when modifying CI workflows:** `feedback_use_coding_team_skill` (this is a single-tracker hotfix, direct dispatch fine), `feedback_strict_rigor_no_handwave` (verification steps above are mandatory before claiming the savings), and `feedback_audit_workflow_constraints` (governs any future security/audit workflow PR).

## [v0.36.54] — 2026-05-23 — Sim gate-completion (#97): organic open→exit→reconcile lifecycle + provenance guard + honest STABLE verdict

Closes the #97 "lifecycle simulator gate-completion" sprint. The simulator's STABLE verdict was previously certifying synthetic hand-written rows — ScenarioRunner crafted clean `recommendations`/`shadow_trades` rows and called `submit_order`/`fill_entry` directly on the fake, so the 9 oracle invariants asserted on rows the runner itself wrote, NEVER touching the real `executor.open_shadow_trade`, `check_and_manage_open_trades`, or `reconcile_all_paper_trades` — exactly the machinery where every motivating production bug lives (orphans, phantom closes, close-didn't-clear). #95's destructive clean-slate wipe is hard-gated on a STABLE verdict from this organic lifecycle, so the prior tautology was a real risk. This release replaces it with a runtime-provenance-guarded organic drive.

- **T9 KEYSTONE — organic open→exit→reconcile ScenarioRunner.** `src/simulation/lifecycle/scenario.py` is rewritten to drive the REAL inline scan path across multiple virtual ticks under `freeze_at(clock)`: TICK A calls `self.watch_loop._run_scan()` directly (real prod scan → features → packet → LLM → governor → `executor.open_shadow_trade` → `reconcile_all_paper_trades`); ADVANCE clock; TICK B fires `fake.fill_leg(symbol, leg='take_profit')` then `executor.check_and_manage_open_trades(sim_dsn, 'paper')` + `reconcile_all_paper_trades(dry_run=False)`. The synthetic raw-INSERT path (`_insert_recommendation`/`_insert_shadow_trade`/`_open_trade`/`_close_trade`) is REMOVED — every row now arrives via the real prod code path.
- **T8 — runtime provenance guard.** `src/simulation/lifecycle/provenance.py:assert_real_path_executed` asserts THREE properties before the oracle certifies anything: (1) all 5 patched seams invoked ≥ 1 (`fetch_ohlcv`, `fetch_spy`, `generate`, `get_account`, `submit_order`); (2) every open `shadow_trade` row's `order_type` ∈ `{bracket, simple_with_stop}` — an executor-only artifact the runner never sets; (3) RUNTIME DSN identity: `oracle_conn.dsn == primed_dsn == 5434 sim signature` (never prod), and the written column set covers the inv9-hashed columns. A green-but-hollow STABLE is now structurally impossible — if a future refactor makes any wiring patch silently miss, the guard raises `ProvenanceError` and the gate fails.
- **T5 — wiring layer for organic patches.** `src/simulation/lifecycle/wiring.py` exposes `prime_config`, `build_watch_config`, and `install_organic_patches(fake_tc, fake_md, fake_llm, universe)`. The latter rebinds 10 module-level symbols across 9 modules (alpaca_adapter._get_trading_client, market_data.{fetch_ohlcv, fetch_spy_benchmark}, packet_writer.{generate, is_llm_available}, sp100.get_sp100_universe, journal.store.uuid, trading.broker_factory.get_live_broker, executor._get_current_price_safe, risk.price_utils._get_current_price_safe) with try/except → undo() rollback for leak-resistance. `_assert_sim_dsn` is a hard prod-isolation guard (refuses any DSN without `:5434/`).
- **T7 §3.4 — deterministic recommendation_id under sim.** stdlib `uuid.uuid4()` draws from `os.urandom` and is NOT seedable, breaking `inv9` equality across two seeded sim runs. Wiring's 5th patch installs a module-local `_DeterministicUuidStub` (counter-based, replaces `journal.store.uuid` only — global stdlib `uuid` is untouched, verified by a negative test).
- **T1–T4 + T6 — fakes + clock seam regression-lock.** `FakeTradingClient.get_account` + `FakeAccount` + `calls` Counter (T1); `fill_on_submit` + `fill_listener` + OCO leg fill (T2); `FakeMarketData.fetch_ohlcv` + `fetch_spy_benchmark` + counter (T3); `freeze_at` regression-lock proving freezegun's module-level `datetime` rebind covers both `src.scheduler.watch` and `src.scheduler.universe_scanner` namespaces with NO shim built (T4); ranker-candidate + tie-break + reconcile-seam build-spike (T6 — surfaces the PROD ranker tie-break instability as a T13 residual blind-spot; fakes side-step via distinct 95/85/80 scores).
- **T13 — honest STABLE verdict + residual blind-spots.** `src/simulation/lifecycle/verdict.py` rewrites the blind-spots section so STABLE explicitly certifies what's exercised (organic open path + provenance guard + reconcile-when-gone + teardown discipline + determinism of recommendation_id/actual_shares/pnl_dollars) and enumerates 10 residual blind-spots verbatim (clean-close xfail, packet_worthy_threshold relaxation, ranker tie-break, T10/T11/T12 deferrals, synthetic-accounting-side CapitalLedger feed, overnight subprocess handlers, actual_shares NULL at open time, real-fill latency/concurrency/regimes excluded). `classify()`/`INTEGRITY_INVARIANTS` rules UNCHANGED — zero-tolerance preserved.
- **T14 — entrypoints wired to organic runner.** `src/simulation/lifecycle/entrypoints/smoke.py` + `full_gate.py` + the package docstring now drive the rewritten organic `ScenarioRunner`. The CI `lifecycle-smoke.yml` workflow gains a `postgres-test` service block (postgres:16-alpine, test/test/halcyon, host 5434→container 5432) because smoke.py's organic runner requires PG (T9 writes through real prod scan path → connect_db(None) → PG under `ARCIS_PG_CUTOVER_ENABLED=1`).
- **Operator #98 review hardening.** `bootstrap._scrub_environment` now re-pins TEST_DATABASE_URL to SIM_DATABASE_URL after scrub (24 fallback-pattern fixtures previously resolved to empty). `SYNTHETIC_EXIT_REASONS` constant extracted to `src/shadow_trading/reconcile.py` (the prod source-of-truth); oracle invariant 3 imports + queries via the constant + parameterized SQL (no more drift between prod and the oracle). `canonical_snapshot_hash` switches from `repr(tuple(row))` to `json.dumps(list(row), sort_keys=True, default=str)` — documented canonical form, stable across CPython rebuilds. `install_prod_guard()` is now idempotent (`_lifecycle_guarded` sentinel; second call is a no-op).
- **Deferred to #97 follow-ups** (disclosed in T13's verdict): **T9b** — exit-detection fake↔executor `.filled_avg_price` OCO contract drift (clean-close test xfailed with `strict=False`); **T10** — full inv9 organic-determinism end-to-end (gated on T9b); **T11** — organic governor-REJECT scenario (drives sacred risk governor reject branch); **T12** — per-fault matrix with first-principles invariant binding. The deferred work is gated on, not blocking, the v0.36.54 release of the organic-open certification.
- **What this release unblocks:** STABLE now legitimately certifies the organic open path (provenance-guarded), the reconcile-when-gone resolution (zero orphans), and teardown discipline. The #95 destructive clean-slate wipe gate is closer to legitimate (the open-path arm certifies; the close-path arm completes when T9b lands). #97 follow-up backlog (#86, #92, T9b/T10/T11/T12) is the path to full STABLE on the open→close lifecycle.

## [v0.36.53] — 2026-05-23 — Cutover follow-ups: boundary tests + install-watchdog subcommand + runbook addendum

Post-cutover cleanup of three loose ends from the v0.36.50→.51→.52 hotfix chain. **No functional/runtime change to the live system** — these are test-coverage closures, an ergonomic CLI addition, and a doc fix. Filed as a hotfix per the operator's per-fix versioning standard.

- **Boundary-touch regression tests for the v0.36.52 fix.** `tests/test_ollama_watchdog.py` had `safe_send` mocked as a bare `MagicMock`, so the kwarg-shape bug it caused (`message=` vs `event=`/`detail=`) couldn't have been caught by any of the 25 existing tests. Added `test_emit_unhealthy_uses_correct_safe_send_kwargs` (asserts `event`, `detail` present; `message` absent; `force=True` retained) — same intent as the QA on PR #1165 flagged. Also added `test_init_expected_model_tag_fallback_chain` (parametrized across all four branches: explicit override → `llm.expected_model_tag` → `llm.model` → `arcis:v1.0.0` default), so future refactors of the fallback chain can't silently drop a branch. Closes the *third* iteration of the mock-coverage-gap pattern (gpu_index, model-tag default, safe_send kwargs) — the QA from PR #1162 originally called this out as "boundary-touch test per integration surface" and it deserved closing.
- **`install-watchdog` subcommand for `scripts/install_service.ps1`.** The `install` subcommand runs `Invoke-Install` (ArcisWatchLoop) AND `Invoke-WatchdogInstall` (ArcisOllamaWatchdog) in sequence; if `ArcisWatchLoop` already exists (every dual-GPU re-cutover scenario), `nssm install` exits non-zero on the first command and the script bails before reaching the watchdog. The new `install-watchdog` subcommand installs ONLY the watchdog. The original `install` is unchanged for fresh boxes.
- **`docs/operator-guide.md` Step 2 addendum.** Documents the `ArcisWatchLoop`-already-exists case explicitly, alongside the existing `ArcisOllamaWatchdog`-already-exists recovery. Future operators running the cutover on a live system get a clearer path.

## [v0.36.52] — 2026-05-23 — Hotfix: ArcisOllamaWatchdog model-tag default + safe_send kwargs

Second hotfix unblocking the operator-gated dual-GPU cutover. After installing the watchdog from v0.36.50 code, two bugs in `src/scheduler/ollama_watchdog.py` caused a tight crash loop and silent alert failures.

- **Wrong default model tag.** `_DEFAULT_MODEL_TAG = "halcyon-v1"` was stale from before the platform's `arcis:v1.0.0` rebrand. The actual model store contains `arcis:v1.0.0`, `halcyon-v1.0.0:latest`, `halcyonlatest:latest` — none of them match `halcyon-v1`. The watchdog's MAJOR-4 invariant check (`/api/tags` must contain the expected tag) failed every poll, the watchdog restarted Ollama every cycle, and `_emit_unhealthy(missing_model_tag)` fired continuously. Fix: `__init__` now uses a fallback chain — explicit override → `llm.expected_model_tag` config → **`llm.model` config (DRY with the LLM client)** → hardcoded default, with the default bumped to `arcis:v1.0.0` as a last-resort floor. The watchdog now tracks whatever model the LLM client uses, without requiring a separate config key.
- **`safe_send` kwarg mismatch.** `_emit_unhealthy` called `safe_send("system_event", message=..., severity=..., force=True)`, but `notify_system_event(event, detail="")` accepts neither `message=` nor `severity=`. (Severity *is* consumed by `safe_send` itself — popped at `telegram.py:1609` — but `message=` is forwarded to `notify_system_event` and raises `TypeError`.) The watchdog's alerts were silently failing every poll. Fix: replace `message=` with `event=` (the title kwarg `notify_system_event` accepts) and pass `detail=detail` (the body kwarg).

**Why both slipped past #94's 6+ reviews:** `tests/test_ollama_watchdog.py` mocked `load_config` to return `{"llm": {"base_url": ...}}` with no `model` key, so the test path also hit `_DEFAULT_MODEL_TAG = "halcyon-v1"` and matched the test's mocked `/api/tags` — circularly green. `safe_send` was mocked with `MagicMock`, so the kwarg shape was never validated against the real signature. Same mock-coverage-gap shape as v0.36.51's `gpu_index` field bug.

Test helper updated: `_make_watchdog()` now includes `"model": "halcyon-v1"` in its mock config so the new fallback chain resolves to the same tag the existing `/api/tags` fixtures use — no test-case changes needed.

## [v0.36.51] — 2026-05-23 — Hotfix: gpu_placement_smoke.py field bug (driver 596.36 compat)

Unblocks the operator-gated dual-GPU cutover. Phase 2 of the smoke gate queried `nvidia-smi --query-compute-apps=gpu_index,...`, but `gpu_index` is **not** a valid field for `--query-compute-apps` on driver 596.36 (per `--help-query-compute-apps`; valid fields are `timestamp, gpu_name, gpu_bus_id, gpu_serial, gpu_uuid, pid, process_name, used_memory`). Every cutover attempt failed with `Field "gpu_index" is not a valid field to query.` — `_query_compute_apps_indexed()` raised `RuntimeError` and `run_smoke()` exited 1.

- **`scripts/gpu_placement_smoke.py`** — `_query_compute_apps_indexed()` now queries `gpu_uuid` (a valid field on every driver) and cross-references to GPU index via a new helper `_query_gpu_index_by_uuid()`. The helper reuses the same `--query-gpu=index,name,uuid` shape that Phase 1's identity check already runs, so no new mock fixtures are required for the identity-PASS path. `check_placement()`'s API is unchanged — it still consumes dicts with a resolved `gpu_index` key.
- **`tests/test_gpu_placement_smoke.py`** — the two compute-apps mock fixtures (`_NVIDIASMI_COMPUTE_APPS_GPU1`, `_NVIDIASMI_COMPUTE_APPS_GPU0`) now lead with the matching UUID (`GPU-bbbb-2222` / `GPU-aaaa-1111`) instead of the integer index. The three test cases (PASS / identity-flip / placement-fail) still drive `subprocess.run` via the same `_fake_run` branch logic.

**Why this slipped past #94's 6+ reviews:** every unit test in `tests/test_gpu_placement_smoke.py` patches `subprocess.run` with canned outputs. The mocked tests asserted the script *parses* nvidia-smi output correctly, but never asserted the *query string itself* is valid against a real driver — a classic mock-coverage gap. The bug only surfaced when the operator tried to run the script during the live cutover.

## [v0.36.50] — 2026-05-22 — Dual-GPU re-cutover (static partition: GPU0=training, GPU1=Ollama)

Replaces the overnight VRAM handoff pattern with a permanent static GPU partition.
Training (`src/training/trainer.py`) is pinned to GPU0 (RTX 3090, 24 GB) via `CUDA_VISIBLE_DEVICES=0`.
Ollama inference is pinned to GPU1 (RTX 3060, 12 GB) via the new `ArcisOllamaWatchdog` NSSM service.

- **Static GPU partition** — GPU0 reserved for training, GPU1 reserved for Ollama; partition is enforced by env-pin in both trainer and watchdog, not by a runtime handoff protocol
- **ArcisOllamaWatchdog NSSM service** (`src/scheduler/ollama_watchdog.py`) — replaces the PowerShell watchdog script; installed via `scripts/install_service.ps1 install`; carries `CUDA_VISIBLE_DEVICES=1`, `CUDA_DEVICE_ORDER=PCI_BUS_ID`, `OLLAMA_MODELS` in `AppEnvironmentExtra`; crash-escalation via `AppThrottle=30s` + `AppRestartDelay=15s`; no `DependOnService` (avoids SCM cache wedge)
- **Training-lifecycle handlers** (`training_start`, `training_stop`) replace the retired VRAM handoff handlers (`request_vram_for_training`, `release_vram_after_training`) in the watch-loop scheduler
- **Telemetry rename** — `vram_handoff_*` metric keys renamed to `gpu_health_*`; 30-day dual-read bridge emits both names for dashboard continuity during transition
- **GPU identity preflight** (MAJOR-5) — trainer asserts `index0==RTX 3090` via `nvidia-smi` before launching a training subprocess; exits before CUDA init if the identity check fails (guards against BIOS/driver index flip after physical reseating)
- **`scripts/gpu_placement_smoke.py`** — two-phase operator-runnable gate: Phase 1 identity check (index0=3090, index1=3060), Phase 2 placement check (Ollama VRAM on GPU1 only); must PASS before live cutover proceeds
- **Runtime liveness monitor** (`src/scheduler/runtime_liveness_monitor.py`) — periodic liveness ticks for `ArcisOllamaWatchdog`; detects silent crashes between watchdog poll cycles
- **No-DependOnService startup guard** — watch loop startup does not declare SCM `DependOnService` on `ArcisOllamaWatchdog`; ordering is handled at install time only
- **Operator-gated cutover runbook** — full live activation sequence, GPU identity/placement verification, and two-path rollback (clean + mid-overnight pre-revert teardown) documented in `docs/operator-guide.md` §"Dual-GPU Cutover Runbook"

Cutover is operator-gated (Phase 3); code is landed but NOT yet live. See the runbook in `docs/operator-guide.md` for the activation sequence.

## [v0.36.49] — 2026-05-22 — Capability registry refresh (19 → 80) + anti-drift CI guards

The capability registry (the platform's live capability ledger at `GET /api/system/index`)
had frozen in mid-April at 19 entries while ~95 subsystems went unregistered, with only a
frozen `assert total >= 18` as a guard — so drift was invisible.

- Refreshed the ledger to **80 fully-wired entries**: 18 data collectors (SYSTEMs with
  table-freshness health-checks), 16 watch-loop handlers (ACTIONs with a real
  `scripts/run_watch_handler.py` CLI kickoff + Draft-7 input schemas), 11 governor gates
  (DECISIONs) + `risk_governor` SYSTEM + drawdown DECISION, and 14 trimmed heterogeneous
  family entries (execution/exits, scan→LLM→council, training, evaluation/audit,
  notifications/attribution).
- Added **5 hard structural anti-drift CI guards** that derive the expected set from live
  code (so a new feature skipping registration fails CI): A (ALL_HANDLERS→ACTIONs),
  B (collectors→SYSTEMs), C (GOVERNOR_GATES→DECISIONs via definition-enumeration),
  D (every `@register_*`/`register_*(` module is in CAPABILITY_MODULES — both forms),
  E (per-capability-package presence guard). The frozen `>= 18` floor is raised to `>= 80`.
- The ~11 deferred modules are recorded in `docs/audits/2026-05-21-capability-registry/deferred_backlog.md`.

Built via the design→code multi-agent pipeline (feasibility PASS, devil's-advocate CONCERNS
resolved); merged after two independent Opus QA reviews both returned SOUND.

## [v0.36.48] — 2026-05-21 — Startup auto-migrates the LOCAL cutover Postgres (not dead Render)

Root-cause fix for the 2026-05-21 incident where `notifications_sent` +
`notifications_digest_queue` silently vanished from the live local PG (160
"relation does not exist" errors) and were never recreated.

The 2026-05-18 PG cutover repointed runtime *writes* to the local PG
(`ARCIS_PG_CUTOVER_ENABLED=1` + `DATABASE_URL=localhost:5433`), but startup
*schema management* (`_check_render_postgres`) still targeted
`config.render.database_url` — the decommissioned Render PG. So the local PG
schema was unmanaged: drift was never auto-fixed, and startup logged
`Postgres auto-migrate failed: ...render.com` against a server that no longer
exists.

- New `_check_cutover_postgres`: when the cutover gate is on, auto-migrates
  `DATABASE_URL` (the local PG) via the idempotent `create_all_tables` — the
  same self-heal the SQLite path already does.
- `_check_render_postgres` now no-ops when the cutover is active (Render is
  decommissioned; migrating it just fails noisily).
- Fixed a latent per-startup index DROP/recreate thrash: the drift comparison
  now normalizes ASC/DESC ordering qualifiers (Postgres stores ordering in
  `indoption`, not `attname`), so an ordered index like
  `idx_notifications_sent_event_recent` is no longer falsely seen as drifted
  on every boot.
- Severity tiers for the new check: `critical` when the cutover PG (the sole
  write target) is unreachable; `ok` (with a note) for the expected role-
  ownership split where a subset of tables are owned by another role and can't
  be reconciled by the runtime user; `warn` for other DDL errors.

Verified against the live local PG. Does not require a restart to be correct
now (the 2 missing tables were manually recreated 2026-05-21); takes effect as
a permanent self-heal on the next startup. The live table-ownership split is
tracked separately.

## [v0.36.47] — 2026-05-21 — Audit-alert email throttle (stop the per-restart flood)

`check_escalation` emailed the operator for every flag on every audit run with no
dedup. The daily auditor re-runs on each watch-loop restart, so a persistent flag
(notably the false 112% drawdown) re-spammed the operator every cycle (2026-05-21
email flood; ~14 emails). Added `_audit_email_throttled`: each flag CATEGORY is
emailed at most once per 24h via the restart-safe `notifications_dedup` table
(reusing `platform_events._already_notified_recently_db`). Category — not the LLM
`description` (whose wording varies per run) — is the dedup key, so a persistent
issue alerts once/day instead of every cycle. Fail-open: a throttle-check error
never suppresses a real alert. Applies to both CRITICAL and ALERT severities.

## [v0.36.46] — 2026-05-21 — Drawdown audit false-positive: measure vs capital, exclude synthetic closes

The deterministic+LLM auditor fired a CRITICAL "catastrophic drawdown of 112.1% …
systematic execution failure" while the real book drawdown was ~1.3% of the $100k
capital. Root cause in `cto_report._compute_trade_summary`: `max_drawdown_pct` was
computed as peak-to-trough dollars divided by **peak cumulative P&L** (a tiny,
volatile denominator) instead of by starting capital, and the equity curve included
synthetic/orphan closes (62 `reconciled_stale` + others out of 133 "trades").

Fix: `max_drawdown_pct = max_dd / starting_capital * 100`, and exclude
`EXCLUDED_FROM_OUTCOME_STATS` exit_reasons (reconciled_stale / position_already_closed
/ duplicate_orphan_backfill) from the drawdown curve — the same filter the other
outcome metrics already document. No change to win-rate/expectancy/trade counts
(scoped to the drawdown that tripped the flag). Real drawdown now reads ~1% and the
false CRITICAL clears. The full 30-day-rolling-window rework remains task #51.


## [v0.36.45] — 2026-05-21 — Liquidate-on-stale: clear "close-didn't-clear" shares so they can't re-orphan

Operator hit "no trades today despite strong setups." Root cause was the orphan
backlog saturating the per-sector correlation caps (max 3/sector): 19 open
positions, 13 of them orphans — the governor correctly refused new Health-Care/
Industrials/Tech setups because those sectors were full of un-attributed lingering
positions, not real conviction trades.

Investigation traced the orphan engine to two stacked bugs:
- **Source** — a phantom `stop_loss` close (executor misread a bracket parent/leg
  fill as an exit, recording a stop-out at the *entry* price while selling **0**
  shares). **Already fixed by v0.36.28** — reconciled-orphan creation collapsed
  `30 → 28 → 5 → 7 → 1 → 0` (none since the fix).
- **Amplifier (this fix)** — when the reconciler detects a live Alpaca position
  whose DB row was closed within the recent-close window (a "close-didn't-clear"),
  v0.36.40 stopped *re-backfilling* it, but the shares **persisted at the broker
  forever** (logged as `skipped`), keeping the orphan exposure alive and clogging
  the sector caps. The literal `reconciled_stale` close never sees a held position
  (stale = local-has / broker-doesn't), so the gap lived at the detector.

`reconcile.py` now **liquidates** a close-didn't-clear position: `_liquidate_if_held`
cancels the protective legs, market-SELLs the **broker-held qty** (never DB
`planned_shares` — avoids the AVGO 6-vs-4 over-sell trap), and only records success
once the position is *confirmed* cleared. If the sell can't be confirmed it leaves
the row for the next cycle rather than declaring a close it can't back — never
closing while shares are still held. Applied to both paper and live detectors;
new `liquidated` field in the reconcile result. Also realigned a stale
`test_reconcile_stale_without_yfinance` assertion to v0.36.30's NULL-pnl behavior.

Operator separately liquidated the 5 legacy reconciled phantoms (AVGO/BAC/DUK/FDX/UNP,
net +$21) to unblock trading the same day; the 8 real bracket trades with NULL
recommendation_id (attribution gap) were left untouched.


## [v0.36.44] — 2026-05-21 — VRAM handoff: skip the /im kill on the CUDA-wedge path

Last night's 18:54 evening handoff to training failed: the graceful unload
(`ollama stop` + keep_alive=0, already in `_unload_ollama`) didn't free VRAM, the
PID-based kill (taskkill /pid → Stop-Process → wmic) ran but VRAM stayed held, then
the legacy `/im` fallback **hung for its full 10s timeout**. Root cause: the Ollama
model-runner was wedged in a CUDA syscall — a process stuck in a kernel-mode GPU
driver call can't be terminated until the call returns, so no kill method works. It
self-cleared by the 05:16 morning handoff (inference healthy). No training run was
lost (training was non-viable anyway — HOLDOUT EMPTY).

### Fixed

- `src/scheduler/vram_manager.py` — in `_kill_ollama_processes`, when the PID-based
  kill ran but `nvidia-smi` shows Ollama **still** holding VRAM (the wedge
  signature), return instead of falling back to `/im`. `/im` can't kill a wedged
  process and only blocks for its timeout + muddies the logs; the caller's
  retry + `torch.cuda.empty_cache` loop already waits for the driver to reclaim VRAM.
  The `/im` fallback is preserved for the legitimate case where nvidia-smi found no
  Ollama GPU process (nvidia-smi missing / Ollama crashed without a tracked app).

Note: the graceful unload and escalating PID-kill were already in place; this only
trims a useless 10s hang on the wedge path. The wedge itself is an external
Ollama/GPU-driver condition that the existing retry + recovery already absorb.

TDD: `tests/test_vram_manager_pid_kill.py::test_kill_ollama_processes_skips_im_when_wedged_after_pid_kill`
(+ 3 existing kill-path tests still green).


## [v0.36.43] — 2026-05-21 — price_target plan-gate off (403, not entitled on fundamental-1)

The overnight comprehensive collection logged `price_targets: 0/102 tickers landed
data (plan-gate open but no rows returned — endpoint may be broken)`. Not a broken
endpoint: the live Finnhub `/stock/price-target` returns **HTTP 403 "You don't have
access to this resource"** on the fundamental-1 plan (verified 2026-05-21; the
sibling `/stock/executive` and `/stock/metric` return 200, so it's a per-endpoint
entitlement gap, not a bad key). WA2 (Sprint 6 Wave A) had gated it open on the
assumption the paid plan covered it, so the collector made 102 calls that all 403'd
and were masked as "0 rows."

### Fixed

- `src/data_enrichment/finnhub_plan.py` — removed `price_target` from
  `_FEATURE_MATRIX["fundamental-1"]` so the plan-gate closes and the collector skips
  cleanly (mirrors the v0.36.25 `filings_sentiment` removal). Re-add only if the plan
  upgrades to entitle the endpoint.
- `tests/test_finnhub_plan_runtime_coverage.py` — inverted the WA2 test to
  `test_price_target_not_supported_on_fundamental_1` (regression-locks the 403
  reality), and populated `_REVERSE_INVARIANT_ALLOWLIST` with `price_target` +
  `filings_sentiment` (gated-off features whose collector call-sites remain by
  design). This also clears a pre-existing failure of the reverse-invariant test.

Note (latent, not fixed here): the YAML fallback Finnhub key is stale/invalid (401);
the system works only because `.env` supplies the valid key. If the env var ever
fails to load, all Finnhub silently fails on the bad key.


## [v0.36.42] — 2026-05-20 — reconcile_live_trades: orphan recent-close parity with paper path

`reconcile_live_trades` had the same orphan-backfill cycle bug fixed in the paper
path by v0.36.40, but **unguarded**: ticker-only match against `source='live' AND
status='open'`, then backfill with no recent-close check. A live position lingering
after a close was re-discovered as an orphan and backfilled as a duplicate
NULL-rec_id row. Currently dormant (CLI-invoked only; `trading.ib_enabled=false` so
Alpaca-only) but a footgun once live trading scales up.

### Fixed

- `src/shadow_trading/reconcile.py` — `_has_recent_close` is now parameterized:
  `source` ('paper'|'live') and an **optional** `desk` (None = no desk filter). The
  live caller passes `source='live', desk=None` to mirror the live tracked-query
  (which is desk-agnostic), so a recent close on any desk is honoured. Broker stays
  `alpaca`-scoped — IB orphans remain intentionally unguarded (Wave 5 brief). The
  paper path is unchanged (positional `desk`, `source` defaults to 'paper').
- `reconcile_live_trades` orphan detection now skips lingering "close-didn't-clear"
  tickers (with a `[RECONCILE-LIVE]` warning) instead of backfilling duplicates.

TDD: `tests/shadow_trading/test_reconcile_live_recent_close_parity_v0_36_42.py`
(helper source/desk params, + behavioral reconcile_live_trades: recent-close→not
backfilled, genuine orphan→backfilled, >window→backfillable, + wiring lock).


## [v0.36.41] — 2026-05-20 — system_validator: db_orphaned_fk excludes rejected_* records

The `db_orphaned_fk` check counted shadow_trades whose (non-NULL) `recommendation_id`
doesn't resolve to a `recommendations` row. On the live DB that was **461/461
`rejected_buying_power` records** — trades rejected for buying power, recorded for
dashboard visibility (`executor.py` `_check_paper_buying_power`) with the scan's
recommendation_id, but the recommendation row is only persisted for **taken** trades.
So every rejected record has a dangling FK *by design*; they are not orphaned
positions. The warning was 100% false signal, masking the genuine count (zero, after
v0.36.40).

### Fixed

- `src/evaluation/system_validator.py` — the `db_orphaned_fk` query now adds
  `AND COALESCE(st.order_type, '') NOT LIKE 'rejected%'`. Live count drops 461 → 0
  (no genuine dangling-FK orphans remain). Note: the corpus-starving reconciler
  orphans are a *different* population (NULL rec_id) that this check never measured;
  they are addressed by v0.36.40.

TDD: `tests/evaluation/test_system_validator_orphan_fk_exclude_rejected_v0_36_41.py`
(behavioral: rejected→pass, genuine non-rejected→warn, mixed→pass, + content-lock).


## [v0.36.40] — 2026-05-20 — reconciler: recent-close window kills the orphan-backfill cycle

Exhaustive orphan-source investigation (`docs/audits/2026-W21-orphan-source`) found
the true orphan source is **closes that don't clear the Alpaca position** (phantom-
close / `reconciled_stale` $0 close / sticky paper position): the position lingers,
the next 09:01 reconcile re-discovers it as an "orphan" (ticker-only / status-narrow
matching), and backfills a duplicate NULL-rec_id row — which then `reconciled_stale`-
closes and repeats. These featureless/synthetic rows are correctly skipped by the
training pipeline, so the cycle **starved the training corpus**; lingering positions
also **consume Alpaca buying power** (→ the 474 `rejected_buying_power` records).

The cycle peaked at 30/day (05-04/05) and the v0.36.28 phantom-close fix + Wave 5
guard tapered it to ~1/day — but a residual leaked because the Wave 5 guard only
skipped re-backfill for `reconciled_stale` closes within **6 hours**.

### Fixed

- `src/shadow_trading/reconcile.py` — new `_has_recent_close(...)` helper +
  `_RECENT_CLOSE_WINDOW_HOURS = 24`. A ticker with a paper/alpaca shadow_trade
  closed within 24h (ANY exit_reason) is treated as a lingering "close-didn't-clear"
  position, **not** a fresh orphan:
  - **Detection step:** excluded from `orphaned[]` before backfill + a
    `[RECONCILE-PAPER] … close-didn't-clear` WARNING surfaces the real underlying
    issue (a close that isn't clearing the Alpaca position).
  - **Backfill step:** the narrow Wave 5 guard (`reconciled_stale`-only / `6 * 3600`)
    is replaced by the same helper — generalized to any exit_reason over 24h, kept
    as defense-in-depth. Alpaca-paper-scoped; IB orphans unaffected.

Why 24h and not order-id matching: Alpaca **position** dicts carry no order-id (only
symbol/qty/avg_entry_price/market_value/P&L), so a recent-close TIME window is the
available discriminator. 24h covers the next-morning 09:01 re-discovery the 6h guard
missed while still surfacing genuinely-old positions for backfill.

TDD: `tests/shadow_trading/test_reconcile_recent_close_window_v0_36_40.py` (9 tests —
window boundary, any-exit-reason, >6h re-discovery, genuine-orphan preserved, desk
scoping, + wiring locks).


## [v0.36.39] — 2026-05-20 — system_validator: gut Render + fix PG-cutover false warnings

Today's 16:30 EOD validation returned CRITICAL (41P / **15W / 1F**). Investigation
found the noise was almost entirely validator bugs from the one-DB cutover, not
real system problems.

### Gutted (Render hosting deprecated post-cutover 2026-05-18)

- `src/evaluation/system_validator.py` — removed `api_render_config`,
  `api_render_connection` (the 1 FAIL → permanent false CRITICAL), and
  `api_cloud_healthz` (hit the deprecated onrender.com cloud API). NOTE: this
  guts RENDER-HOSTING checks only — the PostgreSQL ENGINE (now the local Docker
  runtime DB) is validated by `_check_database` and is unaffected.

### Fixed — PG-cutover false "not accessible" warnings

- **Transaction-abort cascade:** the curriculum query used column `stage` but the
  real column is `curriculum_stage` → `UndefinedColumn` on PG → aborted the
  transaction with no rollback → `model_versions` / `last_retrain` / `canary` /
  `quality_drift` all then false-failed as "not accessible" (they exist with
  data). Fixed the column + added `conn.rollback()` in `_safe_query`.
- **Datetime slice:** `row[0][:19]` sliced a PG `datetime` (PG returns datetime
  objects for `MAX(created_at)`, not strings) → TypeError → `activity_log` /
  `council_sessions` false "not accessible". Wrapped all 7 timestamp slices in
  `str()` (sibling-search across the file).
- **research_docs:** collector date-column map used `created_at`; the column is
  `updated_at`.

Verified live against the Docker PG: `training_model_version`,
`scheduler_activity`, `scheduler_council`, `collector_research_docs` all flip
from false-warn to PASS.

### Not touched (genuine signals, not validator bugs)

Thin training corpus (90 examples), no quality scores / canary / released model,
**560 shadow_trades with invalid/NULL recommendation_id** (orphan class, audit
F-8/F-9), 5 zombie trades past the 8-day timeout, short_interest empty. These are
real and remain visible.

### Tests

- `tests/test_system_validator_cutover_v0_36_39.py` (5): render/cloud checks gone;
  `_safe_query` rolls back on failure; curriculum uses `curriculum_stage`; no bare
  timestamp slice on fetched values; research_docs uses `updated_at`. Existing
  validator suite (54) green.


## [v0.36.38] — 2026-05-20 — wire 3 dead-weight Finnhub collectors

W21 collector-wiring deliverable. We pay for `company_executive`,
`stock_financials`, and `price_target` on the Finnhub plan but had no collectors
— the capacity was dead weight. Built via the coding-team skill (PM orchestrator
+ Planner + 3 parallel worktree developers + dual-independent-Opus-QA merge
gate). Table count 77 → 80.

### Added

- **`company_executives` table + `company_executive_collector.py`** — Finnhub
  `/stock/executive`. One row per executive (name/position/age/since/
  compensation/currency); UNIQUE (ticker, name, position). `compensation` is
  BIGINT (exec comp can exceed int32). Skips executives with no name.
- **`stock_financials` table + `stock_financials_collector.py`** — Finnhub
  `/stock/metric?metric=all`. Curated snapshot (pe/pb/ps, ev_ebitda, roe/roa,
  margins, debt_to_equity, current_ratio, dividend_yield, market_cap, 52w
  hi/lo) keyed by (ticker, as_of_date). Every metric field tolerates a missing
  key (Finnhub omits per-ticker).
- **`price_targets` table + `price_target_collector.py`** — Finnhub
  `/stock/price-target` (target high/low/mean/median). Keyed by (ticker,
  as_of_date). Dedicated full-universe snapshot, distinct from
  `analyst_estimates`' opportunistic price-target columns.
- All three wired into `src/scheduler/overnight.py` via `_run_plan_gated_collector`
  (capabilities already present in the `fundamental-1` matrix — no
  `finnhub_plan.py` edit). Each: plan-gate first (no API call when unsupported),
  `CollectorConfigError` on missing key, idempotent upsert; overnight-layer
  mass-failure detection via the wrapper.

### Tests

- 12 new tests across `tests/data_collection/test_{company_executive,stock_financials,price_target}_collector.py`:
  plan-gated API call + row write + UPSERT idempotency; plan=free → no API call;
  schema-discipline (table/columns/unique index); plus edge cases (empty
  payload, missing-name skip). Full data_collection suite: 69 passed, 9 skipped.

### Schema

- 3 new `TableDef`s in `src/schema/registry.py` (single source of truth).
  SQLite via `validate-schema --fix`; runtime Postgres (Docker) tables created
  at watch-loop startup schema-ensure on deploy. Render PG migration N/A
  (Render offline post-cutover).

### Notes

- `known_violations.json` scoped to this sprint's footprint only
  (overnight.py + its 2 functions); pre-existing structure debt in unrelated
  files remains deferred to the #65 sweep.
- Out of scope: F-24 collector-contract refactor (next).


## [v0.36.37] — 2026-05-20 — F-20: FRED/macro failures visible (debug → warning)

W21 audit F-20 (HIGH), collector series. `macro.py` logged every FRED
fetch/parse failure at `logger.debug` (lines 100, 111, 137, 155). Production
runs at INFO/WARNING, so a FRED outage produced **zero** operator-visible
signal — macro enrichment silently returned None, LLM packets degraded, nobody
knew (12-hour silent-degradation class; sibling of the v0.36.23 macro outage).

### Fixed

- `src/data_enrichment/macro.py` — promoted all four FRED error paths
  (`_fetch_series` retry-exhausted + parse-error; `_fetch_cpi_yoy`
  retry-exhausted + parse-error) from `debug` to `warning`, with a `[MACRO]`
  prefix. No remaining `logger.debug` error paths in the module.

### Tests

- `tests/data_collection/test_macro_fred_logging_v0_36_37.py` (4): each error
  path asserts a WARNING is emitted (retry-exhausted + parse-error, for both
  `_fetch_series` and `_fetch_cpi_yoy`).

### Deferred

The audit also suggested a per-task `last_success_at` staleness tracker
(WARNING when >24h stale regardless of per-call log level) — larger
cross-collector enhancement, folded into the F-24 collector-contract work.


## [v0.36.36] — 2026-05-20 — F-7: FINRA short-volume surfaces mass failure

W21 lifecycle-audit finding F-7 (CRITICAL), first of the collector hotfix
series. `collect_finra_short_volume` returned a success-shaped dict regardless
of how many SP100 tickers it matched (`short_volume_finra.py:185-192`). If the
FINRA CDN serves a malformed / empty / format-drifted file, the collector
matches 0 SP100 tickers, `_is_collector_error` treats it as success, and
`short_volume_daily` silently goes stale — feature enrichment loses
short-volume context with no operator signal. Same anti-pattern as v0.36.26
(institutional/filings/press_releases) and v0.36.25 (6-day institutional
staleness).

Note: this is the **FINRA** collector (`short_volume_finra.py`), which was
*succeeding* in production (101 tickers). It is distinct from
`short_interest_collector.py`, which already raises on mass failure (v0.36.26).
F-7 is a latent defensive fix against future CDN drift.

### Fixed

- `src/data_collection/short_volume_finra.py` — raise
  `CollectorPartialFailureError` when `tickers_collected == 0` against a healthy
  universe (`len(sp100) >= _MASS_FAILURE_MIN_UNIVERSE = 10`). A degenerate tiny
  universe is not alarmed (avoids false positives).

### Tests

- `tests/data_collection/test_short_volume_finra_mass_failure_v0_36_36.py` (3):
  mass-failure raises on 0 matched; partial/normal collection does not raise;
  tiny universe (<10) does not alarm. Existing FINRA suite (11) still green.


## [v0.36.35] — 2026-05-20 — restore overnight training on multi-GPU desktop topology

Found during a deep-dive into recurring VRAM handoff failures (operator
flagged "VRAM handoff failed again"). Three fixes (A+B+C) that together restore
overnight training, which had effectively stopped since the 2026-05-10 GPU
upgrade (only 1 successful training handoff since). Bundled as one version
because none is useful alone — training stays broken until all three land.

### (A) Root cause — VRAM clear check measures the wrong thing

`get_vram_used_mb()` reads only **GPU[0]**'s total memory
(`split("\n")[0]`). On the host, GPU[0] is the **RTX 3090**, which also drives
the Windows desktop — `dwm.exe`, Chrome, VS Code, Docker, Steam, etc. hold an
irreducible **~2.6 GB** baseline that cannot be freed without closing the
desktop. The handoff clear-thresholds (1500 MB inference / 2500 MB training)
were written for the original **headless single RTX 3060** (docstring). The
2026-05-10 GPU upgrade put the models on the display GPU, so the desktop floor
permanently exceeds both thresholds and `_wait_for_vram_clear()` could **never
pass** — every handoff escalated (needlessly killed Ollama) and FAILED.

Impact: only **1 successful training handoff** since the upgrade; overnight
training was effectively not running. Confirmed both directions
(evening training handoff 2026-05-19 18:54, morning inference 05:18).

### Fixed

- `src/scheduler/vram_manager.py` — new `_model_pids_on_gpu(name_substr, pid)`
  and `_wait_for_model_release(...)`: gate the handoff on whether the **model
  process** (Ollama by name, or the training subprocess by PID) still appears
  in `nvidia-smi --query-compute-apps`, instead of total-GPU-VRAM-vs-threshold.
  Immune to desktop VRAM and GPU topology.
- `handoff_to_training` now waits for the Ollama process to leave the GPU;
  `handoff_to_inference` waits for the training PID to leave, and its escalation
  force-kills the **training** process (the real VRAM holder) rather than
  Ollama (which it is about to load — the prior escalation was a no-op).
- `get_vram_used_mb()` retained for informational logging only.

### (B) Fixed — Ollama restart full-path (`[WinError 2]`)

After a failed handoff the manager restarts Ollama via
`subprocess.Popen(["ollama", "serve"])`. Under the NSSM service context the
user PATH is absent, so this raised `[WinError 2] cannot find the file`
(2026-05-19 18:54) — Ollama never recovered from the handoff path.

- `src/scheduler/vram_manager.py` — new `_find_ollama()` (mirrors
  `_find_nvidia_smi`): `shutil.which` → `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`
  → `C:\Program Files\Ollama\ollama.exe`. Resolved once in `__init__`
  (`self._ollama`), used at every `ollama` exec site; falls back to the bare
  name when unresolved (unchanged behavior on PATH-equipped hosts).

### (C) Fixed — trainer Modelfile crash (`'str' has no attribute as_posix`)

`_find_gguf()` returns a `str` (its declared contract), but `run_fine_tune`
called `gguf_path.as_posix()` on it — crashing **every** fine-tune at the
Modelfile-write step.

- `src/training/trainer.py` — new `_modelfile_content(gguf_path)` wraps the path
  in `Path(...)` before `.as_posix()`; call site uses it. Works for str or Path.

### Tests

- `tests/test_vram_manager_per_process_clear_v0_36_35.py` (7): per-process
  release detection ignores desktop VRAM, by-name and by-PID matching, no-smi
  shortcut, and both handoffs succeed despite a 2611 MB desktop floor.
- Updated `test_handoff_to_training_fails_when_ollama_wont_release` and
  `test_handoff_to_inference_escalates_by_killing_training` to the corrected
  per-process semantics (the old tests asserted the now-removed total-VRAM gate).
- `tests/test_vram_manager_ollama_path_v0_36_35.py` (5): `_find_ollama`
  resolution order + manager fallback (B).
- `tests/test_trainer_modelfile_v0_36_35.py` (3): str input no longer crashes,
  backslash normalization, Path input (C).

### Known limitation

If a training subprocess is orphaned by a watch-loop restart (handle lost),
`handoff_to_inference` can't identify it by PID; tracked for post-freeze.


## [v0.36.34] — 2026-05-20 — guard initialize_database backfill against startup crash

Found during a 10:49 ET health check. The watch-loop restart at 10:55:55
logged a fatal startup error before recovering on an NSSM retry:

    psycopg2.errors.UndefinedTable: relation "shadow_trades" does not exist
    File "src/main.py", line 337, in main → initialize_database()
    File "src/journal/store.py", line 99 → UPDATE shadow_trades ...

### Root cause

`main.py:337` calls `initialize_database()` UNCONDITIONALLY, before the
subcommand dispatch (`args.func(args)` at line 339). So every
`python -m src.main <cmd>` — including the `startup` that NSSM runs for the
watch loop — executes the journal init first.

`initialize_database` ensures the schema with the SQLite-specific helpers
(`src.schema.sqlite.create_all_tables` / `ensure_columns`), then runs a
best-effort data migration:

    UPDATE shadow_trades SET actual_exit_time = COALESCE(updated_at, created_at)
    WHERE status = 'closed' AND actual_exit_time IS NULL

Under the cutover gate (`ARCIS_PG_CUTOVER_ENABLED=1`) `connect_db` reroutes
that UPDATE to Postgres — a backend whose schema this function never ensured
(it ensured SQLite). The PG schema IS ensured, but by the `startup` handler
that runs AFTER line 337. So any moment PG transiently lacks the table or the
connection hiccups (e.g. the simultaneous double-launch on a restart), the
UNGUARDED UPDATE raises and crashes the entire watch-loop launch. The 10:55:55
attempt only survived because NSSM's retry happened to succeed; a restart
without a lucky retry would have stayed down.

### Fixed

- `src/journal/store.py` — wrapped the `UPDATE shadow_trades` backfill in a
  `try/except DBError`, logging a WARNING and continuing. The backfill is
  optional (dashboard visibility only); making startup depend on it succeeding
  was the bug. It now retries on the next startup once the schema exists.
- `src/journal/store.py` — import `DBError` (`= (sqlite3.Error, psycopg2.Error)`)
  from `src.utils.db` so both SQLite- and Postgres-class failures are caught.

### Scope / sibling-search

The four sibling `init_*` functions (`init_council_tables`,
`init_value_tables`, `init_training_tables`, `init_quality_drift_tables`) were
checked: none run a post-create data migration — their DML lives in separate,
lazily-called functions. `initialize_database` is the only one with a
post-create migration AND the only function `main.py` calls before dispatch.
Fix is correctly scoped to it.

### Tests

`tests/test_initialize_database_backfill_guard_v0_36_34.py` (5): backfill
failure (sqlite + psycopg2 UndefinedTable) does not propagate, emits a
WARNING, still runs + commits on the happy path, and an AST source-lock that
the UPDATE stays inside a try/except.

### Deploy note

Two-layer staleness applies (see v0.36.31 incident): this fix is loaded only
after the watch loop is restarted onto the v0.36.34 tree. The running loop is
unaffected until then; the guard matters for the NEXT restart.


## [v0.36.33] — 2026-05-19 — institutional_holdings.total_shares BIGINT (v0.36.25 follow-up)

Surfaced during tonight's overnight cycle: the institutional_ownership
collector — fixed in v0.36.25 to hit the correct `/stock/ownership`
endpoint — now returns real data and failed to store it:

    [COLLECT] institutional_ownership: FAILED -- {'error': 'integer out of range'}

### Root cause

`institutional_holdings.total_shares` was `INTEGER` (PG int32, max
2,147,483,647). The collector sums `share` across ALL institutional holders
of a ticker (`institutional_ownership_collector.py:73-81`). For a megacap
this exceeds int32 — verified: AAPL aggregates to **9,893,657,756 shares**
across 8,184 holders (4.6× the int32 ceiling).

SQLite never hit this (dynamic typing stores full int64 in INTEGER affinity);
the strict PG `integer` overflowed. This is a clean follow-on from v0.36.25
— the bug only became reachable once the URL fix started returning data.

### Fixed

- `src/schema/registry.py` — `total_shares` ColumnDef `INTEGER` → `BIGINT`.
- `src/schema/postgres.py` — added `"BIGINT": "BIGINT"` to `_TYPE_MAP`
  (first BIGINT column in the registry).
- PG migration applied: `ALTER TABLE institutional_holdings ALTER COLUMN
  total_shares TYPE bigint`.
- Verified end-to-end: `collect_institutional_ownership('AAPL')` now stores
  `total_shares=9893657756` successfully.

### No restart required

The collector computes an unbounded Python int and the upsert sends it to
PG, which now accepts bigint. The running watch loop's in-memory registry
version is irrelevant to the INSERT — the next overnight cycle's
institutional_ownership collector succeeds because the PG column is migrated.
(Also avoids a restart inside the 21:30–22:30 ET overnight window.)

### Tests

NEW `tests/test_institutional_holdings_bigint_v0_36_33.py` (3 tests):
- registry ColumnDef for total_shares is BIGINT
- `_TYPE_MAP["BIGINT"] == "BIGINT"`
- `_aggregate_holders` produces a total_shares > int32 max (proves the
  overflow scenario is real, not hypothetical)

All 3 green + `tests/test_schema.py` (48) pass = 51.


## [v0.36.32] — 2026-05-19 — W21 audit F-3: phantom-close drift anomaly alarm

Third of three hotfixes from the W21 lifecycle audit. F-3 adds the alarm
that would have caught v0.36.28 in week 1 instead of week 36.

### Root cause

`src/shadow_trading/exit_reconciliation.py::_check_trade` checked timeout
exits only for `duration_days < timeout_days`. A phantom-close (v0.36.28,
where exit_price was set to the entry-order fill) passes that check silently
— the position exits at ~entry price on a multi-day hold and looks like a
normal flat day. The reconciliation pass is the natural detection point but
had no drift check.

### Fixed

NEW `_is_phantom_drift_anomaly(row)` flags price-based exits
(timeout/target_1/target_2/stop_loss) where `duration_days >= 1` AND the
exit/entry price drift is below `_PHANTOM_DRIFT_TOLERANCE`. Wired into
`_check_trade` as a first-class anomaly condition (returns True regardless
of the per-reason check). Added `actual_entry_price, entry_price` to the
reconciliation SELECT.

### Threshold calibration — NOT the audit's recommended 5 bps

The W21 audit recommended a 5 bps drift threshold. **Verification against
the real data showed 5 bps would have MISSED the canonical bug:** the AMD
`dcd090be` phantom had entry=$439.80, exit=$440.72 → drift = 0.92/439.80 =
**21 bps**, above the 5 bps floor. We use **50 bps (0.5%)** instead:

- Catches AMD (21 bps) with margin.
- Genuine multi-day (>= 1 trading day) holds essentially never move < 0.5%.
- A flag is an anomaly-LOG entry (not a halt), so modest false-positive
  tolerance is acceptable.

This is the kind of "verify the recommendation against the actual data"
rigor that the audit's own lens-11 (mock-divergence) advocates — the spec
was directionally right but its specific number wouldn't have worked.

### Tests

NEW `tests/test_exit_reconciliation_zero_drift_v0_36_32.py` (8 tests):
- AMD phantom (21 bps, 10-day) → flagged
- genuine 5% multi-day move → not flagged
- exact zero-drift multi-day → flagged
- intraday (duration < 1) flat → not flagged
- NULL exit price → not flagged (fail-safe)
- non-price exit reason (reconciled_stale) → not flagged
- stop_loss phantom (2.5 bps) → flagged
- `_check_trade` end-to-end: phantom timeout flagged even though it passes
  the legacy `duration < timeout` check

UPDATED `tests/scheduler/test_exit_reconciliation.py` (3 fixtures): the
pre-F-3 fixtures used `exit_price == entry_price == 100.0` on multi-day
holds — the exact phantom signature. Updated to realistic exit prices
(108.0). This both fixes the tests AND proves F-3 doesn't false-positive
on realistic data.

All 34 green (8 new + 26 existing exit_reconciliation).

### Audit cross-ref

Finding F-3 (CRITICAL) in `docs/design/2026-W21-lifecycle-audit/audit-findings.md`.
This completes the 3 top-CRITICAL W21-audit hotfixes (F-1 v0.36.30, F-2
v0.36.31, F-3 v0.36.32). Remaining CRITICAL findings F-4 through F-9 are
Wave 1 of the post-freeze priority roadmap.


## [v0.36.31] — 2026-05-19 — W21 audit F-2: model-win-rate precheck small-sample guard

Second of three hotfixes from the W21 lifecycle audit. F-2 is the
deterministic-precheck twin of the v0.36.27 small-sample bug.

### Root cause

`src/evaluation/auditor.py::_check_model_win_rate` line 509:
`if trades < 2 or win_rate > 0: continue`. So when a model version had
`trades >= 2 AND win_rate == 0`, a CRITICAL flag fired ("Block promotion
and new entry exposure for this model").

v0.36.27 added `_LLM_AUDIT_MIN_SAMPLE=10` to gate the LLM *narrative*, but
the deterministic prechecks (`_append_deterministic_prechecks`) run
unconditionally — so this precheck was never gated. A 2-loss day for any
model version (arcis:v1.0.0 hit exactly this on 2026-05-18, see the v0.36.22
CHANGELOG note) fires CRITICAL → `audit_entry_suppression` reads the audit
output and suppresses all new entries → trading desk dark on noise →
false-CRITICAL Telegram. The exact issue v0.36.27 chased, in a sibling path.

Same small-sample-extrapolation class as v0.36.22 (drawdown, guarded at 50)
and v0.36.27 (LLM narrative, guarded at 10).

### Fixed

- NEW `_MODEL_WIN_RATE_MIN_SAMPLE = 10` (mirrors `_LLM_AUDIT_MIN_SAMPLE`).
- Gate changed: `if trades < _MODEL_WIN_RATE_MIN_SAMPLE or win_rate > 0`.
- Sibling-search confirmed: the only ungated precheck. `_check_drawdown`
  already guards at `_DRAWDOWN_MIN_SAMPLE=50` (v0.36.22); the LLM narrative
  at `_LLM_AUDIT_MIN_SAMPLE=10` (v0.36.27). No other `trades < N` thresholds.

### Tests

NEW `tests/test_auditor_model_winrate_sample_v0_36_31.py` (5 tests):
- trades=2, win_rate=0 → no flag (the 2026-05-18 false-positive case)
- trades=9 → no flag (one below threshold)
- trades=10, win_rate=0 → flag (real broken-model signal at threshold)
- trades=20, win_rate=0.3 → no flag (non-zero win rate)
- consistency: `_MODEL_WIN_RATE_MIN_SAMPLE == _LLM_AUDIT_MIN_SAMPLE == 10`

All 5 green. Auditor sample-guard suite (LLM + drawdown + bootcamp + this)
= 19 passed.

### Audit cross-ref

Finding F-2 (CRITICAL) in `docs/design/2026-W21-lifecycle-audit/audit-findings.md`.


## [v0.36.30] — 2026-05-19 — W21 audit F-1: reconcile phantom-$0 stale close

First of three hotfixes closing CRITICAL findings from the W21 lifecycle
audit (`docs/design/2026-W21-lifecycle-audit/`). F-1 is a sibling of the
v0.36.28 phantom-close pattern, alive in the reconciler's stale-close path.

### Root cause

`src/shadow_trading/reconcile.py::_estimate_exit_pnl` returned the literal
`(0.0, 0.0, 0.0)` on ANY exception (yfinance rate limit, delisting,
network). The stale-close paths at `reconcile.py:349` (live) and
`reconcile.py:863` (paper) then wrote `exit_price=$0, pnl=$0, pnl_pct=0`
to closed shadow_trades.

Same phantom-state class as v0.36.28:
- v0.36.28 phantom: $440.72 entry → $440.72 exit (entry-fill-as-exit)
- F-1 phantom:      $440.72 entry → $0.00 exit  (zero-as-exit)

The sibling helper `_resolve_stuck_pnl` (reconcile.py:108-155) already
returns `None` on unknown price — F-1 mirrors that correct pattern.

### Impact

`reconciled_stale` IS in the audit's `_UNMEASURABLE_EXIT_REASONS` allowlist,
so today this doesn't corrupt the training corpus. But it corrupts the live
dashboard, daily audit aggregates, and any KPI that doesn't read the
unmeasured-allowlist. Risk escalates to corpus poisoning if a future PR
forgets to allowlist a new exit-reason.

### Fixed

- `_estimate_exit_pnl` returns `(None, None, None)` on failure.
- Both stale-close call sites init `exit_price, pnl_dollars, pnl_pct = None,
  None, None` (was `0.0, 0.0, 0.0`), and emit a WARN when the close is
  UNKNOWN so the operator sees it.
- `close_shadow_trade` receives None → writes NULL pnl (= "unmeasured").
- Log lines changed `if pnl_dollars != 0.0` → `if pnl_dollars is not None`.
- Telegram `notify_trade_closed` payloads coerce None → 0.0 for display
  only (DB keeps NULL); the `reconciled_stale` exit-reason makes context clear.

### Tests

NEW `tests/test_reconcile_phantom_pnl_v0_36_30.py` (4 tests):
- fetch failure → `(None, None, None)`
- empty data → `(None, None, None)`
- success path → real pnl preserved (regression-proof)
- explicit anti-pattern lock: failure must NOT return `(0.0, 0.0, 0.0)`

All 4 green. Reconcile sweep (`tests/shadow_trading/` + exit_overshoot) =
245 passed, 2 pre-existing failures (test_reconcile_dispatch_db_path mock
signature, unrelated).

### Audit cross-ref

Finding F-1 in `docs/design/2026-W21-lifecycle-audit/audit-findings.md`.
Sibling phantom-state surfaces F-4, F-5, F-14 remain (Wave 1 of priority
roadmap). This hotfix closes F-1 only.


## [v0.36.29] — 2026-05-19 — W21 execution cleanup: nvidia-smi `[N/A]` memory parse (v0.36.24 follow-up)

v0.36.24 introduced PID-based Ollama-killing via
`nvidia-smi --query-compute-apps=pid,process_name,used_memory` to fix the
2-night VRAM-handoff cascade. Two nights later (2026-05-19 18:50 ET handoff)
the fix **failed to fire** on the operator's RTX 3090+3060 system.

### Root cause

`_get_gpu_processes()` parsed the third column as `int(parts[2])`, with a
`ValueError` fallthrough that `continue`-d on the row. On the operator's
hardware, Ollama's `ollama.exe` shows up TWICE (once per GPU) with **`[N/A]`**
literal for the memory column (the documented `MiB` value isn't surfaced via
WDDM for some Windows processes — Ollama's runner is a known case).

```
2195136, C:\Users\mille\AppData\Local\Programs\Ollama\ollama.exe, [N/A]
2195136, C:\Users\mille\AppData\Local\Programs\Ollama\ollama.exe, [N/A]
```

`int("[N/A]")` raised ValueError → both rows skipped → ollama-filter empty →
fallthrough to legacy `taskkill /f /im ollama.exe` (which is the broken path
v0.36.24 was supposed to replace). Net effect: v0.36.24 was a no-op on this
hardware. Training missed another night.

### Fixed

`src/scheduler/vram_manager.py::_get_gpu_processes`:

- Treat non-integer `used_memory` as `None` (don't skip the row). Process
  identification doesn't require the memory column — only PID and name do.
- Updated return-type docs: `used_mb: int | None`.

`src/scheduler/vram_manager.py::_kill_ollama_processes`:

- Dedupe Ollama PIDs before killing. Multi-GPU systems list the same process
  once per GPU.
- Log line accommodates `None` memory (`memory=[N/A]` instead of `NoneMB`).
- Verification pass also dedupes by PID.

### Tests

NEW `tests/test_vram_manager_na_memory.py` (4 tests):

- `test_get_gpu_processes_handles_na_memory` — pins the contract using the
  ACTUAL nvidia-smi output captured from the live system on 2026-05-19. The
  v0.36.24 test mocked an `int` memory value, which is how the `[N/A]` case
  slipped through review. TDD lesson encoded: pin the real output format,
  not the documented one.
- `test_get_gpu_processes_preserves_int_memory_when_present` — backward-compat
  for the `int` case.
- `test_kill_ollama_processes_finds_ollama_when_memory_is_na` — end-to-end:
  feeds real nvidia-smi output, asserts `taskkill /f /t /pid 2195136` fires.
- `test_kill_ollama_processes_dedupes_pids` — duplicated Ollama rows kill
  the PID only once.

All 4 green. Existing `tests/test_vram_manager_pid_kill.py` (v0.36.24, 11
tests) and `tests/test_vram_manager.py` (21 tests) still pass. **Total 36/36.**

### Operator action

`nssm restart ArcisWatchLoop` to pick up the fix. Per memory
`feedback_no_restart_during_overnight_window`, restart any time except
21:30–22:30 ET. Tonight's 18:50 ET training handoff already missed; next
opportunity is 2026-05-20 18:50 ET (Wed).

### Open follow-up (NOT in this PR)

`subprocess.Popen(["ollama", "serve"])` at `vram_manager.py:266,340` fails with
`[WinError 2]` because `ollama` is not on the LocalSystem PATH the NSSM
service inherits. Pre-existing; surfaced again in the 5-19 18:54 log as
"Failed to restart Ollama". Workaround already exists (the Ollama tray app at
PID 27336 auto-respawns the daemon). Proper fix: use absolute path
`C:\Users\mille\AppData\Local\Programs\Ollama\ollama.exe` in the Popen call,
or add to LocalSystem PATH via NSSM. Tracked for post-freeze.


## [v0.36.28] — 2026-05-19 — W21 execution cleanup: phantom-close bug in bracket-exit detection (HIGHEST-IMPACT W21 FIX)

Discovered while chasing today's audit-finding false alarm to its root.
Operator session expanded into a full lifecycle trace via Alpaca's order
history API. Design team reviewed the proposed fix before implementation.

### Root cause

Three converging code paths in `src/shadow_trading/executor.py` interpreted
the bracket-PARENT order's `status='filled'` as an exit signal. For Alpaca
OCO bracket orders, the "parent" IS the BUY entry order — `parent_status=
'filled'` is the NORMAL state of every open bracket position, not an exit
signal.

The shared helper `_close_from_broker_fill` (line 1361) writes the order's
`filled_avg_price` as `actual_exit_price` — when called with a BUY's fill,
it writes the **entry** fill as the **exit** price.

The three sites that mis-routed:

1. **Primary site** at `executor.py:1865-1869`: `if parent_status in
   FILLED_ORDER_STATUSES: ... bracket_exit=True`. When `days_open >=
   timeout_days`, the timeout-exit path gated by `if not bracket_exit:`
   then skipped the SELL submission entirely. shadow_trade marked closed,
   Alpaca position stayed open, reconciler later discovered it as an
   "orphan" and created a duplicate row.

2. **Sibling site** at `executor.py:1430-1434` (`_retry_exit` pre-check):
   `pending_order_id = exit_order_id or alpaca_order_id`. When exit_order_id
   is None, fell back to the BUY parent.

3. **Sibling site** at `executor.py:2007-2009` (pre-exit cancel-race): same
   fallback chain via `_pending_oid`.

### Smoking gun

AMD trade `dcd090be` (rec=b166279f, order_type='bracket'):
- shadow_trades: `actual_entry_price=$439.80, actual_exit_price=$440.72,
  pnl=$1.84` (closed 2026-05-18 09:04 ET, exit_reason='timeout')
- Alpaca order history (queried live via REST API): BUY filled 2026-05-08
  16:10 UTC @ $440.72. **No SELL of AMD between 5-08 entry and 5-18
  14:03 stop-fill** ($418.50, the eventual close of the orphan-backfilled
  AMD #4 with pnl=-$44.44).

The recorded exit price ($440.72) is exactly the BUY's filled_avg_price.

### Population audit (run before fix)

8 bracket+timeout closes since 2026-04-13 (bug ship date, commit
`baa8466d`):
- 7 confirmed phantoms (paired orphan-backfill within 24h)
- 1 possibly-legit (MO -$17.85, no orphan pair)
- Phantom-pnl distortion in audit: +$1.82 total (clusters near break-even
  by definition)
- Hidden real losses on orphan cousins (not attributed to recommendations):
  AMD -$44.44, C -$25.50, AMZN -$167.43, ETN -$118.80 — total -$356.17
- 3 still-open positions traceable to phantom cascade: UNP, FDX, AVGO —
  all have correct OCO protection from their orphan-backfills; no
  "shadow_closed but Alpaca open" mismatch to recover

### Fix (defense-in-depth, covers all 3 sites)

**Architectural — side guard in shared helper** (`executor.py:1361`):

```python
side = str(filled_order.get("side") or "").lower()
if "sell" not in side:
    logger.error(...)  # critical
    return
```

Refuses to close-from-fill when the order is a BUY. Catches all three
call sites in one line. Future call sites that mis-route are visible via
the critical log.

**Direct removal** (`executor.py:1865-1869`): deleted the parent-status
branch. The legs check immediately below correctly handles real exits
(stop or target SELL leg actually firing). Replaced with a comment block
documenting the incident for future readers.

### Recovery (NOT in this PR)

- Historical pnl-distortion is minimal (+$1.82) — leave alone.
- The 3 still-open orphans (UNP/FDX/AVGO) have correct OCO protection.
  No still-open mismatches require manual action.
- Tomorrow's overnight cycle continues to use orphan-backfill for any
  positions that already exist on Alpaca without shadow_trade rows —
  same recovery mechanism, just no more new phantoms entering the queue.

### Tests

NEW `tests/test_phantom_close_v0_36_28.py` (7 tests):

- `_close_from_broker_fill` refuses BUY orders (the guard)
- `_close_from_broker_fill` processes SELL orders correctly
- `_close_from_broker_fill` refuses missing side (fail-safe)
- `_close_from_broker_fill` accepts SELL/Sell/sell case variants
- Source-code lock: `parent_status in FILLED_ORDER_STATUSES` must not
  appear in active code (regression-proof against re-introduction)
- Source-code lock: `_close_from_broker_fill` must contain a side-check
- Source-code lock: legs check (`legs = order_status.get("legs", [])`)
  must remain intact

All 7 green. Broader sweep: `tests/shadow_trading/` + `tests/test_exit_overshoot_bundle.py` + `tests/test_bracket_orders.py` = **250 passed**, 7 skipped, 2 pre-existing failures unrelated to this change.

### Design-team review (artifacts in `docs/design/v0.36.28/`)

- Codebase-analyst confirmed the sibling-bug count (2 additional sites
  beyond my initial diagnosis) and verified the Alpaca legs contract.
- Devils-advocate verdict: PROCEED WITH MODIFICATIONS. Specific modifications adopted: (1) defense-in-depth via the helper guard, (2) population audit before fix, (3) explicit recovery-plan separation. Edge-case concerns (empty-legs race, partial-fill legs) were flagged but determined non-blocking — these are pre-existing behaviors not introduced by the fix.

### Operator action

The fix takes effect on next `nssm restart ArcisWatchLoop`. Per
`feedback_no_restart_during_overnight_window`, the 21:30–22:30 ET window
should be avoided. Restart before 21:25 ET or after 22:30 ET.


## [v0.36.27] — 2026-05-19 — W21 execution cleanup: LLM auditor sample-size guard

W21 continuation. Operator received the second false-positive CRITICAL audit
Telegram in 24 hours, this time *"100% of trades executed with scores below 70,
all resulting in immediate stop losses, indicating complete failure of the
scoring/selection..."* off **N=3 closes today**.

Investigation: today's 3 closes (KO +$217.52 reconciled_stale, C -$25.50 stop,
AMZN -$167.43 stop) all had `recommendation_id = None` because they came from
the pullback-strategy path that doesn't write the rec_id back into shadow_trades
(separate bug, queued as v0.36.28). With NULL rec_ids, the CTO report's
`_compute_by_score_band` defaulted `score = 0` (line 374), so all 3 sorted into
the `below_70` bucket. The LLM saw "100% in below_70 band" and panicked.

Actual P&L today: **+$24.59** (1W / 2L), not catastrophic. Normal day-by-day variance.

This is the SECOND day in a row the LLM auditor extrapolated catastrophe from
a tiny sample:

  - 2026-05-18: "0% win rate vs 57% for base model, negative expectancy" off
    N=2 trades attributed to arcis:v1.0.0 — real 10-trade window: 4W/6L (40%).
  - 2026-05-19: "100% below 70 score" off N=3 trades with NULL rec_id.

### Fixed

NEW `_LLM_AUDIT_MIN_SAMPLE = 10` constant + guard in `run_daily_audit` at
`src/evaluation/auditor.py:120-148`. When `trade_summary.trades_closed < 10`,
the `generate_training_example(AUDITOR_SYSTEM_PROMPT, ...)` LLM call is
skipped and replaced with a deterministic low-volume summary:

```
"Low-volume day (N closes, threshold 10). LLM narrative suppressed to
 avoid small-sample extrapolation. Deterministic checks below."
```

Critical design decision: the **deterministic prechecks still run** —
`_append_deterministic_prechecks` is called unconditionally below the LLM
gate. Those checks have their own per-check sample guards (v0.36.22's
drawdown ceiling guard, etc.). This way the deterministic surface stays
sharp while the LLM commentary stops manufacturing false alarms.

10 is a conservative floor — catches the worst cases (N≤3) without
suppressing the LLM on normal trading days (SP100 swing typically 5-20
closes/day). A per-model-subgroup sample guard (yesterday's case) is
queued for post-freeze.

### Tests

NEW `tests/evaluation/test_auditor_llm_sample_size_guard.py` (5 tests):

- `test_low_sample_skips_llm_narrative` — N=3 → LLM not called, prechecks
  still run, summary mentions "low/sample/small"
- `test_zero_sample_skips_llm_narrative` — N=0 → safe, no crash, prechecks
  run
- `test_sufficient_sample_invokes_llm_narrative` — N=15 → LLM called
- `test_exact_threshold_invokes_llm_narrative` — N=10 (exactly threshold) → LLM called
- `test_one_below_threshold_skips_llm_narrative` — N=9 → LLM not called

All 5 green. Existing auditor tests (drawdown sample-size guard + bootcamp
flag): 9/9 still pass. **Total 14/14.**

### Operator action

The fix takes effect on next `nssm restart ArcisWatchLoop`. v0.36.28
(pullback rec_id backfill) lands immediately after — bundle both restarts
into one. Per `feedback_no_restart_during_overnight_window`, restart before
21:25 ET (overnight cycle begins 21:30 ET).


## [v0.36.26] — 2026-05-19 — W21 execution cleanup: silent-success → CollectorPartialFailureError

W21 continuation. Closes the bug-hiding pattern that masked v0.36.25's
two broken Finnhub collectors for 6 days. CLAUDE.md's "Surface mass
failures" rule was already on the books; this PR enforces it for the
plan-gated batch collectors.

### Root cause — bug-hiding by construction

Pre-v0.36.26 each plan-gated wrapper in `src/scheduler/overnight.py`
(institutional_ownership / filings_sentiment / press_releases at lines
~750-794) counted `tickers_with_data = N` after a per-ticker loop.
When N=0 the result `{"tickers_with_data": 0}` looked indistinguishable
from a healthy run to `_is_collector_error`, so the scheduler reported
`[COLLECT] X: success` even when every API call had silently failed.

This is how PRs #1082 and #1083 endpoint regressions ran undetected for
6 days: `/stock/institutional-ownership` returned 302→404, every per-
ticker call swallowed the JSON parse error and returned None, the loop
counted 0 successes, and `_is_collector_error({"tickers_with_data": 0})`
returned False.

### Fixed

NEW helper `_run_plan_gated_collector(...)` in `src/scheduler/overnight.py`:

1. Checks `finnhub_plan_supports(capability, config)` **before** the loop.
   - Gate closed → returns the literal string `"skipped: plan-gated"`,
     caught by the existing logging branch which emits
     `[COLLECT] X: skipped`. **No per-ticker API calls are made when the
     plan doesn't support the capability** (eliminates the wasted-ratelimit
     case where 100 Nones at the gate consumed quota for nothing).
   - Gate open → runs the loop counting both `tickers_with_data` and
     `tickers_attempted`.

2. After the loop, if `tickers_attempted >= 10` and `tickers_with_data == 0`,
   raises `CollectorPartialFailureError`. The wrapping try/except stores
   `{"error": ...}`, `_is_collector_error` then classifies it correctly, and
   the scheduler logs `[COLLECT] X: FAILED`.

Design notes:

- **Threshold is `== 0`, not CLAUDE.md's `<50%`.** The collectors targeted
  here (filings, press_releases) are sparse-data — many SP100 tickers
  legitimately have no new data on a given night. 50/100 is a normal
  press_releases night. `0/100` is unambiguous mass failure regardless of
  expected density.

- **`>= 10` floor** prevents false-positives on small test universes.
  SP100 (~100 tickers) always satisfies this.

- **Wired into all three plan-gated wrappers** (lines 750-794 of
  `run_data_collection`). press_releases is included even though it's
  currently working — it had the same silent-success construction.

### Tests

NEW `tests/scheduler/test_overnight_plan_gated_mass_failure.py` (8 tests):

- gate-closed: result is `"skipped: plan-gated"` string, collector not called
- gate-open + 0/100 → raises CollectorPartialFailureError
- gate-open + 30/100 → returns dict, no raise
- small universe (3 tickers) → no raise even on 0 (test fixture size)
- gate-open + 1/100 → no raise (1 success counts as not-mass-failure)
- `_is_collector_error` correctly handles new result shapes: `"skipped: ..."`,
  `{"tickers_with_data": N, ...}`, `{"error": ...}` (3 tests)

All 8 green. Wider sweep: `tests/scheduler/` = 114 pass.


## [v0.36.25] — 2026-05-19 — W21 execution cleanup: Finnhub collectors silently broken since cutover

W21 continuation. Agent-B investigation of the morning health-check's
"4 empty collector tables" finding exposed two collectors that had been
silently returning None for every S&P 100 ticker since they landed
2026-05-13 (PRs #1082, #1083). The scheduler reported `[COLLECT] X: success`
each night because the inner collectors swallowed the error and returned
None, and the outer wrapper treats None as "skipped, not failed."

### institutional_ownership_collector — wrong endpoint URL

`/stock/institutional-ownership` returns HTTP 302 → 404 (HTML body).
`resp.json()` then died parsing `<` with `Expecting value: line 1
column 1`. The except clause logged a warning and returned None.

Live probe with the production API key confirmed: **`/stock/ownership`**
is the correct endpoint, returns
`{"ownership": [{"name": ..., "share": ..., "filingDate": ..., "change": ...}, ...], "symbol": ...}`
with ~8000 holders per ticker. The existing `_aggregate_holders` parser
uses exactly these field names — **no JSON re-mapping needed**.

Fix: one-line URL change in `_fetch_finnhub_ownership` at
`src/data_collection/institutional_ownership_collector.py:43`.

### filings_sentiment_collector — endpoint returns `{}`

Live probes:
- `/stock/filings-sentiment` returns body `{}` (broken or deprecated)
- `/stock/sentiment` returns 404
- `/news-sentiment` returns news sentiment (different concept, not filings)

No working alternative endpoint found. Until a working URL/params combo
is confirmed with Finnhub support, plan-gate the collector off via
`_FEATURE_MATRIX` to stop wasted API quota (100% of S&P 100 nightly
calls were wasted since 2026-05-13).

Fix: removed `filings_sentiment` from the `fundamental-1` set in
`src/data_enrichment/finnhub_plan.py`. The collector now returns None
without making the HTTP request.

### Tests

- NEW `tests/data_collection/test_finnhub_endpoint_fix.py` (3 tests):
  - active code in `institutional_ownership_collector` must reference
    `/stock/ownership` (with comment/docstring allowlisting)
  - the deprecated `/stock/institutional-ownership` URL must not appear
    as active code
  - `filings_sentiment` must NOT be in `_FEATURE_MATRIX["fundamental-1"]`
  - `institutional_ownership` MUST remain in the matrix (URL bug, not plan-gate bug)

- UPDATED `tests/data_collection/test_filings_sentiment_collector.py`:
  `test_plan_fundamental_1_makes_api_call_and_writes_row` →
  `test_plan_fundamental_1_is_gated_off_after_v0_36_25`. The previous
  test expected the paid plan to enable the collector; the new test pins
  the intentional gated-off state and asserts no HTTP call is made.

Sweep: 55 pass + 2 skip across `tests/data_collection/`, related
filings/institutional, and `tests/data_enrichment/`.

### Operator action

No runtime restart required for v0.36.25 — the collectors only run
during the overnight cycle, and the watch loop reads the plan-gate
each call. Effective on next overnight cycle.

### Open follow-ups

- Re-probe Finnhub for a working filings-sentiment endpoint (their
  docs may have updated paths; their support can confirm). When found,
  fix `_fetch_finnhub_filings_sentiment` URL and re-add to
  `_FEATURE_MATRIX["fundamental-1"]`.
- Adjust the morning health-check probe to stop flagging
  `filings_sentiment` as "empty unexpectedly" until the endpoint is
  restored.


## [v0.36.24] — 2026-05-19 — W21 execution cleanup: VRAM handoff PID-based Ollama kill

W21 continuation. Morning health check on 2026-05-19 surfaced the VRAM
handoff bug that has been blocking the training pipeline since at least
2026-05-18. Training has not run since 2026-05-15 (last successful handoff);
the model `arcis:v1.0.0` has been serving inference off ~5-day-old weights.

### Root cause — taskkill /im fails on wedged Ollama runner

`_kill_ollama_processes` in `src/scheduler/vram_manager.py` used
`taskkill /f /im ollama.exe` + `taskkill /f /im ollama_llama_server.exe`,
each with a 10s timeout. When an Ollama runner is wedged in a CUDA syscall,
the process is unresponsive to `/im` signals, the kill command times out at
10s, the function returns, and VRAM stays held.

Observed failures (`logs/arcis.log`):

| Date | Phase | Failure |
|---|---|---|
| 2026-05-18 18:50 ET | handoff to training | VRAM stuck at 4686MB after `Unloaded model` returned 200 OK; taskkill timed out; 3 retries exhausted; **training did not run that night**. |
| 2026-05-19 05:18 ET | handoff to inference | VRAM stuck at 2673MB (same hung Ollama from night before); taskkill timed out; recovered accidentally via `_reload_ollama` in `overnight.py:987`. |

The handoff-to-training path has no equivalent accidental-recovery fallback,
so every evening handoff that hits this state silently skips training.

### Fixed

`src/scheduler/vram_manager.py`:

1. **`_get_gpu_processes()` (NEW)** — parses
   `nvidia-smi --query-compute-apps=pid,process_name,used_memory`
   to find the actual VRAM-holding PIDs. Returns `[{pid, name, used_mb}, ...]`.
   Safe under nvidia-smi absence (returns `[]`) and timeouts.

2. **`_kill_pid(pid)` (NEW)** — Windows kill escalation:
   1. `taskkill /f /t /pid <PID>` (kills process tree, not just the named binary)
   2. PowerShell `Stop-Process -Id <PID> -Force`
   3. `wmic process where ProcessId=<PID> delete`
   Each step has a 10s timeout. Returns True on first success.
   Linux path: `kill -9 <PID>`.

3. **`_kill_ollama_processes()` (REWRITTEN)** — now:
   - Strategy A: `_get_gpu_processes()` → filter to ollama-named PIDs → `_kill_pid` each. Verify with second nvidia-smi poll. Returns if clean.
   - Strategy B (fallback): legacy `/im`-based kill (for nvidia-smi missing / no GPU apps / runner crashed without freeing VRAM).
   - Explicit safety: a `python.exe` PID holding GPU memory (e.g. training subprocess) is **never** killed — only processes whose name contains "ollama".

### Tests

NEW `tests/test_vram_manager_pid_kill.py` (11 tests):

- `_get_gpu_processes` CSV parsing, empty, no-nvidia-smi, timeout (4 tests)
- `_kill_pid` escalation through all three Windows tools (4 tests)
- `_kill_ollama_processes`: uses PID when GPU apps present, falls back to /im when not, ignores non-ollama processes (3 tests)

All 11 green. Existing `tests/test_vram_manager.py` 21 tests also still pass — total 32/32.

### Operator action

The fix takes effect on next `nssm restart ArcisWatchLoop`. Per
`feedback_no_restart_during_overnight_window`, avoid restarting between
21:30–22:30 ET (overnight kickoff window). Recommended timing: any time
before 21:25 ET tonight so the new code is in place for the 18:50 ET
training handoff... wait, training handoff already passed before this
fix was written. **Tonight's training handoff is at 18:50 ET 2026-05-19.**
Restart before then.

### Open follow-ups (deferred per operator)

- `_get_gpu_processes` could log per-PID VRAM attribution on every poll
  to make future debugging easier (currently only the running totals are logged).
- The dual-GPU (RTX 3090 + RTX 3060) question is unresolved. `nvidia-smi`
  shows both devices, but `project_gpu_upgrade.md` describes only the 3090.
  Confirm intent post-freeze.
- The `train.py` `UnicodeDecodeError` on `gptoss.jinja` (the original
  surface symptom Agent A flagged) is **already fixed** by `PYTHONUTF8=1`
  in `_training_subprocess_env()` since commit `df92c454` (2026-05-16).
  No code change needed there; the VRAM bug above is the actual blocker.


## [v0.36.23] — 2026-05-19 — W21 execution cleanup: macro_snapshots UNIQUE index + dedupe

W21 continuation. Morning health check on 2026-05-19 surfaced 31+ consecutive
`[MACRO] DB error on <series>: there is no unique or exclusion constraint
matching the ON CONFLICT specification` WARNs in the watch loop (UNRATE,
T10Y2Y, VIXCLS, WALCL, M2SL, PCE, JTSJOL, ICSA, etc.). `macro_snapshots` was
stale 7 days (last 2026-05-12).

### Root cause — registry / PG index uniqueness mismatch

`macro_snapshots.sync_conflict_col` is set to `'series_id, collected_date'`
in the registry, so `engine_aware_upsert(action='ignore')` generates
`INSERT ... ON CONFLICT (series_id, collected_date) DO NOTHING` on PG.
PostgreSQL requires the ON CONFLICT target to be backed by a UNIQUE
constraint or PRIMARY KEY.

The registry's `idx_macro_snapshots_series` IndexDef was declared
**non-unique** (`unique=False`, the dataclass default). So:

- PG actual index: non-unique → every macro upsert hit
  `IntegrityError: no unique or exclusion constraint matching the ON CONFLICT
  specification`.
- SQLite actual index: non-unique → same logical bug, but SQLite is
  permissive enough that the bare INSERT path didn't error — instead, it
  **silently accumulated 233 duplicate rows** across 214 (series_id, collected_date)
  groups from 2026-05-05 onward.

Pre-cutover this was masked because everything ran on SQLite (silent dups).
Post-cutover the PG-strict behavior surfaced it as visible WARNs, but the
collector had been silently broken on PG since the cutover.

### Fixed

1. **Registry update** — `src/schema/registry.py:1208` IndexDef now
   `unique=True` with an inline comment documenting the incident.
2. **PG migration** — atomic transaction in `validate-schema --fix` path:
   ```
   DELETE duplicates keeping max(id) per (series_id, collected_date)
   DROP INDEX idx_macro_snapshots_series  -- non-unique
   CREATE UNIQUE INDEX idx_macro_snapshots_series ON macro_snapshots (series_id, collected_date)
   ```
   - Before: 728 rows, 214 duplicate groups
   - Deleted: 233 rows
   - After: 495 rows, 0 duplicate groups
3. **SQLite migration** — same dedupe applied to
   `C:/arcis/data/ai_research_desk.sqlite3`. `validate-schema --fix`
   recreated the index as UNIQUE.
4. **Post-fix verification** — manual `collect_macro_snapshots()` run
   succeeded: 31 series collected, 5 notable changes detected
   (T10Y2Y +14.9%, RRPONTSYD +534.9%, WTI -7.5%, ICSA +5.5%, BBB OAS -5.1%).

### Tests

NEW `tests/schema/test_macro_snapshots_unique_index.py` (2 tests):

- `test_macro_snapshots_upsert_index_is_unique` — asserts the IndexDef
  has `unique=True`, with detailed failure message tying the bug to its
  PG manifestation.
- `test_macro_snapshots_sync_conflict_matches_unique_index` — generalizes
  the contract: every table with a multi-column `sync_conflict_col` must
  have a matching UNIQUE index. Catches the same bug class if it
  reappears for any other table.

Both green. Broader sweep: schema + data_collection = 110 passed / 9 skipped.

### Operator action (already done in-session)

- `nssm restart ArcisWatchLoop` is NOT strictly required — the runtime
  upsert path reads `sync_conflict_col` from the registry and the PG
  schema now backs it correctly; in-flight macro collector calls will
  succeed on next overnight. Restart recommended at next natural window
  to align the in-process VERSION with disk.


## [v0.36.22] — 2026-05-18 — W21 execution cleanup: drawdown audit sample-size guard

W21 continuation. Operator received a Telegram CRITICAL alert from the
auditor: *"Max drawdown is 32.6%, above the deterministic audit ceiling."*

### Root cause — sample-size sensitivity

`_check_drawdown` in `src/evaluation/auditor.py:407-423` flags CRITICAL when
`max_drawdown_pct >= 25` with no sample-size consideration. The drawdown
metric in `cto_report._compute_trade_summary` (`cto_report.py:290-302`) is
peak-to-trough on the cumulative-P&L path over the audit window
(default `days=1`).

On small samples, a single outsized loser hitting after the cumulative peak
trivially trips the ceiling — the metric becomes **order-dependent** and
stops measuring strategy risk. Today's trigger:

- 16 closed trades (`days=1`)
- NEE single stop-loss: **-$206.97**
- Cumulative P&L path peaked at ~$635 before NEE, recovered to $605.66 by EOD
- `max_drawdown_dollars = $206.97`, `max_drawdown_pct = 32.6%`

Today's actual strategy stats: win rate **50%**, Sharpe **2.35**, expectancy
**+$30.43/trade**, profit factor **~3.0**. A strong day flagged CRITICAL
because of a single bad trade in a small window.

### Fixed

`src/evaluation/auditor.py` — added `_DRAWDOWN_MIN_SAMPLE = 50` constant
and a sample-size guard. When `trade_summary["trades_closed"] < 50`, the
drawdown check returns without flagging regardless of value:

```python
if trades_closed < _DRAWDOWN_MIN_SAMPLE:
    return
if drawdown < 25:
    return
```

50 is a conservative floor — by ~50 closes the cumulative path is robust
to single-trade outliers.

### Queued for post-W21-freeze

The proper long-term fix is switching the drawdown check to a fixed
30-day rolling window (rather than the variable audit window). This is the
conventional usage of max-drawdown — peak-to-trough on a multi-period
equity curve, not a single trading session. Tracked in tasks for
post-freeze cleanup.

### Tests

NEW `tests/evaluation/test_auditor_drawdown_sample_size.py` (7 tests):

- `test_drawdown_suppressed_below_sample_threshold` — empirical 16-trade /
  32.6% case is suppressed.
- `test_drawdown_suppressed_below_sample_threshold_extreme_value` — even
  99% DD on 20 trades is suppressed.
- `test_drawdown_fires_above_sample_threshold` — 60 trades + 30% DD fires.
- `test_drawdown_below_ceiling_above_sample_threshold` — 60 trades + 20% DD
  is below ceiling (no flag).
- `test_drawdown_at_exact_threshold_boundary` — at exactly 50 trades the
  check still applies.
- `test_drawdown_one_below_threshold_suppressed` — at 49 trades it doesn't.
- `test_drawdown_missing_data_no_crash` — missing trade_summary fields
  return safely.

All 7 pass locally.


## [v0.36.21] — 2026-05-18 — W21 execution cleanup: SPA fallback handler 500-vs-401 regression

W21 continuation. Operator reported "the dashboard might be having an issue
with the API — looks like everything" (every panel showing "failed to load").

### Root cause

`_spa_fallback_404` in `src/api/app.py:241-250` (introduced 2026-05-14 by
commit `b45085c1` — "feat(dashboard): bundle morning hotfixes #142-#147")
is registered as the global handler for **every** `StarletteHTTPException`.
The handler correctly serves `index.html` for 404s on SPA routes, but for
all other status codes it does `raise exc`. Raising inside an exception
handler bubbles to uvicorn → uvicorn returns **HTTP 500**.

Effect chain:
1. Bearer token in browser localStorage expires (24h `SESSION_MAX_MS` in
   `frontend/src/api.js:6`).
2. SPA calls `/api/kpis` (or any authed endpoint).
3. `verify_auth` raises `HTTPException(401, "Invalid or missing API token")`.
4. `_spa_fallback_404` catches the 401, path `/api/kpis` doesn't match the
   SPA-serve condition, falls through to `raise exc`.
5. uvicorn returns 500 with the literal text "Internal Server Error".
6. Frontend `fetchApi` at `frontend/src/api.js:33` only triggers the re-auth
   redirect on `res.status === 401`. Sees 500, throws "API error: 500" to
   the panel.
7. Every dashboard panel renders "failed to load" while the user is silently
   signed out — no AuthGate redirect, no path back to a working state without
   a hard reload.

### Fixed

`src/api/app.py:251-255` — the SPA fallback handler now returns a
`JSONResponse` mirroring FastAPI's default `HTTPException` response shape
(`{"detail": exc.detail}` with the real `status_code`), instead of re-raising:

```python
return JSONResponse(
    status_code=exc.status_code,
    content={"detail": exc.detail},
    headers=getattr(exc, "headers", None) or None,
)
```

This restores 401 visibility for the frontend, which triggers the AuthGate
re-auth flow.

### Tests

NEW `tests/api/test_spa_fallback_handler.py` (4 tests):

- `test_unauthed_api_call_returns_401_not_500` — missing bearer on `/api/*`
  returns **401**, body is `application/json` with `{"detail": ...}`.
- `test_unauthed_api_call_with_bad_token_returns_401` — invalid bearer on
  `/api/*` returns **401**, not 500.
- `test_authed_api_call_still_works` — valid bearer still returns 200
  (didn't break the working path).
- `test_healthz_unaffected` — `/healthz` is still unauthenticated and 200.

### Operator action required

After this PR merges, the dashboard NSSM service (`ArcisDashboard`) needs
a restart to pick up the fix. The watch-loop (`ArcisWatchLoop`) does not
serve the dashboard API and doesn't need a restart for this fix.

Once restarted, operators with expired tokens will see the AuthGate prompt
again instead of broken panels.


## [v0.36.20] — 2026-05-18 — W21 execution cleanup: FINRA short-volume pre-overnight fix

W21 pre-overnight de-risk. Manual pre-flight of every overnight task before
the 21:30 ET scheduled run caught two bugs in `collect_finra_short_volume()`
(v0.36.13 stopgap) that would have failed at first invocation.

### Fixed

`src/data_collection/short_volume_finra.py` — two PG-runtime bugs:

1. **TypeError on universe lookup.** Pre-fix called
   `get_sp100_at(target_date)` passing a `date` object; `get_sp100_at()`
   expects an ISO string (`date.fromisoformat()` internally). Would have
   raised `TypeError: fromisoformat: argument must be str` at the first
   overnight run.

2. **UniverseDataMissing on T+1 anchor.** Even with the ISO-fix,
   `get_sp100_at()` raised `UniverseDataMissing: as_of=2026-05-15 is
   after latest covered date 2026-04-28` because the membership table
   (`data/reference/sp100_history.json`) was 3 weeks stale and the
   collector pulls T+1. PIT is for backtesting; daily collectors want
   current-membership.

Fix: switched the import + call site from `src.universe.pit.get_sp100_at`
to `src.universe.sp100.get_sp100_universe`. Aligns with the T10 migration
allowlist policy in `tests/test_pit_universe_discipline.py` (live-runtime
sites use current membership; only backtest/sim/training-backfill use
PIT). Added the file to the allowlist with rationale.

Pre-flight result post-fix:
```
{'tickers_collected': 101, 'rows_inserted': 101,
 'target_date': '2026-05-15', 'source': 'finra'}
```

### Other pre-overnight de-risk verified (no code change)

- **FED scraper** (`scripts/scrape_fed_speeches.py`) — manual pre-flight
  succeeded, 4 speeches collected. v0.36.13 multi-strategy parser fix
  validated in production.
- **build_score manual trigger** — `model_quality=100.0`, no IndexError.
  v0.36.18 array-bounds fix validated.
- **Stuck-trade cleanup** — UPS `cdb246c7-…-3bb7babbf6c8` resolved as
  partial-fill exit at $99.40 (24/39 shares filled, pnl=-$240.48 / -5.65%,
  exit_reason `qty_mismatch_partial_fill` — already in
  `_UNMEASURABLE_EXIT_REASONS` so excluded from outcome stats). ETN
  `90f28c15` closed as overshoot exit ($381.27, pnl=-$118.80 / -5.67%).
  `needs_manual_review` count: 1 → 0.

### Tests

- `tests/data_collection/test_short_volume_finra_universe_fix.py` (NEW,
  2 tests) — regression-locks for both the bug class (active code call
  site walks line-by-line skipping comments + docstrings) and the import
  line.
- `tests/data_collection/test_short_volume_finra.py` (5 mocks updated)
  — `get_sp100_at` → `get_sp100_universe`, return type `set` → `list`
  (matching `set(get_sp100_universe())` wrapping in source).
- `tests/test_pit_universe_discipline.py` allowlist — added
  `src/data_collection/short_volume_finra.py` with rationale.
- `tests/test_version.py` — bumped to v0.36.20.


## [v0.36.19] — 2026-05-18 — W21 execution cleanup: P4-1 (test-file fallback sweep)

W21 continuation. Closes P4-1 — proactive sweep of test files using the
broken `TEST_DATABASE_URL or DATABASE_URL` fallback pattern that caused
P0 incident #159 (PG wipe on 2026-05-17, see v0.36.14 entry).

### Fixed (21 test files)

Each file's PG-URL assignment changed from:
```python
TEST_PG_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", ""
)
```
to:
```python
TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
```

This eliminates the fallback to `DATABASE_URL` (which on the operator's
machine points at the local prod halcyon-pg via `.env`). Tests now skip
cleanly when `TEST_DATABASE_URL` is unset, rather than falling through
to the v0.36.14 pg_wrapper second-line defense that raises `pytest.fail`.

Both code paths and operator-facing skip messages updated:
- Code: `TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")`
- Skip message: `"TEST_DATABASE_URL not set or not postgres://"` (was
  `"TEST_DATABASE_URL / DATABASE_URL not set or not postgres://"`)

### Files modified

21 files in `tests/`, all converted via deterministic regex substitution
with dry-run preview. Verified by running the parametrized test suite —
sqlite variants pass, postgres variants skip cleanly. Sample run:
`22 passed, 17 skipped in 0.69s`.

- `tests/council/test_protocol.py`
- `tests/council/test_value_tracker.py`
- `tests/data_collection/test_analyst_collector.py`
- `tests/data_collection/test_edgar_collector.py`
- `tests/data_collection/test_insider_collector.py`
- `tests/data_enrichment/test_staleness.py`
- `tests/evaluation/test_build_score.py`
- `tests/platform/rigor/test_walkforward_runner.py`
- `tests/platform/rigor/test_walkforward_universe.py`
- `tests/test_api_routes_system_date_now.py`
- `tests/test_council_context_date_now.py`
- `tests/test_db_engine_aware_upsert.py`
- `tests/test_db_wrapper_rewrite.py`
- `tests/test_edgar_collector_introspection.py`
- `tests/test_event_risk_score_introspection.py`
- `tests/test_ib_status_date_now.py`
- `tests/test_ib_status_uptime_window.py`
- `tests/test_model_monitor_introspection.py`
- `tests/test_retention_introspection.py`
- `tests/test_schema_validator_engine_aware.py`
- `tests/test_startup_checks_introspection.py`

### Added

- `tests/test_p4_1_fallback_pattern_gone.py` — codebase-wide regression-
  lock that fails if any test file (outside the documented allowlist)
  reintroduces the broken fallback pattern. Allowlist: `conftest.py`
  (docstring warning), `test_conftest_pg_guard.py` (guard's own test
  fixture), and this file itself (its docstring contains the example).

### Sibling-search

- `grep -rln 'TEST_DATABASE_URL.*or.*DATABASE_URL' tests/ --include="*.py"`
  now returns only the 3 allowlisted files. Pattern fully swept.
- v0.36.14's pg_wrapper second-line defense remains as belt-and-suspenders
  — if a future test reintroduces the pattern AND TEST_DATABASE_URL
  accidentally matches a prod URL, the guard will still pytest.fail.

### Note on layered defenses

This is the third layer of defense against this class of bug:
1. v0.36.14 pytest_configure P0 guard — refuses pytest if env var
   matches prod signatures
2. v0.36.14 pg_wrapper second-line defense — pytest.fail at fixture
   entry time if the env var was mutated mid-session to match prod
3. v0.36.19 (this) — eliminate the source of the issue by ensuring
   test files never construct the fallback in the first place


## [v0.36.18] — 2026-05-18 — W21 execution cleanup: P1-NEW-3 + P2-3

Two more W21 cleanup items closed. P1-NEW-4 (ghost positions) auto-resolved
by the reconciler — no code change needed; marked closed in the inventory.

### Fixed

#### P1-NEW-3: cutover-gate WARN fires on every connect_db call

**Bug:** `_warn_db_path_ignored_once` in `src/utils/db.py` used
`id(db_path)` (Python object memory address) as the dedup key. Different
callers passed freshly-instantiated string objects with different ids
even when the path value was identical — and forward-slash vs
backslash variants of the same path always have different ids. Result:
the "_once" function fired 570 times in 1 hour of normal operation.

**Fix:** dedup by `os.path.normpath(str(db_path)).lower()`. Different
str instances with the same value collapse to one key. Backslash and
forward-slash variants of the same path collapse to one key.

3 regression-lock tests in `tests/utils/test_warn_db_path_dedup.py`.

#### P2-3: `[BuildScore] model_quality error: list index out of range` daily

**Bug:** `_score_model_quality()` in `src/evaluation/build_score.py`:
```sql
SELECT SUM(llm_success), SUM(llm_total) FROM scan_metrics WHERE ...
```

On PG (psycopg2 RealDictCursor), both un-aliased `SUM()` columns are
named `sum`, so the row dict has only one entry. Indexing `row[1]`
then raises `IndexError: list index out of range`. Fired daily at
~16:45 ET in build-score computation.

**Fix:** alias the SUMs (`AS success_sum`, `AS total_sum`), access by
name. Works on both SQLite and PG.

2 regression-lock tests in `tests/evaluation/test_build_score_model_quality_pg_compat.py`.

### Closed without code change

- **P1-NEW-4** (5 stale ghost positions): auto-resolved by the reconciler
  between 09:07-09:32 ET. BMY/BK/COP/CVX/DIS all closed properly with
  exit_reason='unknown' or 'reconciled_stale'. The 1-hour safety guard
  didn't actually block closure (it was for IB outages, not Alpaca). No
  code work needed; inventory entry marked closed.

### Sibling-search

- `grep -rn "id(.*)" src/utils/db.py | grep -v "id(self)"` — no other
  "_once" warn functions use `id()` for dedup. Only the cutover-gate
  variant had this bug.
- `grep -rn "SELECT SUM(.*), SUM(.*)" src/` — no other queries select
  multiple un-aliased SUMs in the same row. The P2-3 pattern was unique.


## [v0.36.17] — 2026-05-18 — W21 execution cleanup: P1-NEW-1 + P1-NEW-2 + P2-1

W21 continuation. Bundles three independent fixes discovered during the
market-open log inspection at 09:30 ET (operator memory:
`feedback_week_of_2026_05_18_no_features_only_cleanup`).

### Fixed

#### P1-NEW-1: Reconciler creates duplicate orphan-backfill on race condition

**Bug:** When a shadow_trade transitions briefly to `exit_failed` state
(e.g., after a premature exit attempt collides with an active OCO
bracket), the reconciler's orphan-check at
`src/shadow_trading/reconcile.py:566` filtered by `status='open'` only.
A second reconciler cycle scanning during that brief window saw the
broker position with no matching tracked trade and created a duplicate
shadow_trade.

**Reproduction (ETN 2026-05-18 09:31-09:32 ET):**
- 09:02 — Original `415531e1` closed as timeout
- 09:07 — Reconciler orphan-backfilled `90f28c15` with active OCO
- 09:31 — Watch loop tried `place_exit` on `90f28c15`; Alpaca rejected
  ("insufficient qty — all 5 shares held by bracket")
- 09:31 — `90f28c15` marked `exit_failed retry=1`
- 09:32:09 — Reconciler scan saw broker has ETN, didn't see `90f28c15`
  in tracked_map (filtered out), marked as orphan, created
  duplicate `465b63ed`
- 09:32:16 — "Premature exit revert" reset `90f28c15` to open
- **Result:** 2 open ETN shadow_trades for 1 broker position

**Fix:** extend the orphan-check tracked-status set to include
`'exit_failed'` and `'exit_pending'`. These represent
trades-with-positions-at-broker that just haven't settled their exit.
The `'submission_uncertain'` state is intentionally excluded (handled
by its own resolver; `test_uncertain_trade_marked_failed_when_alpaca_has_no_position`
regression-guards that).

**Data cleanup applied (committed):** ETN's `465b63ed` (no OID, never had
a bracket) closed with new vocab `'duplicate_orphan_backfill'`.
Canonical `90f28c15` (active OCO `b93cc89c`) reverted from
`needs_manual_review` to `open`.

#### P1-NEW-2: `coerce_exit_reason()` silently drops 'position_already_closed'

**Bug:** When Alpaca returns 'position already closed at broker
(qty=0)', the executor sets `exit_reason='position_already_closed'`.
`coerce_exit_reason()` didn't recognize this vocab term and silently
mapped to `'unknown'`, losing the broker-side signal.

**Fix:** added `'position_already_closed'` to `CONTROLLED_VOCAB`.
Also added to `EXCLUDED_FROM_OUTCOME_STATS` (same rationale as
`reconciled_stale` — no real fill on our side) and to
`_UNMEASURABLE_EXIT_REASONS` in both `cto_report.py` and
`model_monitor.py` (same audit-filter rationale).

#### P2-1: `scan_service.py` reads nonexistent regime keys

**Bug:** `src/services/scan_service.py:405` constructed the Telegram
trade-open payload with
`regime_at_entry=feat.get("regime") or feat.get("market_regime")`. The
enricher writes the regime label to `feat["traffic_light"]["regime_label"]`
(3-label vocab) and `feat["regime_label"]` (5-label vocab) — never to
`"regime"` or `"market_regime"`. Result: `regime_at_entry` was NULL
in every Telegram trade-open notification even on healthy enrichment
runs. See v0.36.13 T6 Path B followup audit
(`docs/audits/2026-05-17-v0.36.13-training-page/regime_capture_followup.md`)
for the full investigation that surfaced this.

**Fix:** read `feat["traffic_light"]["regime_label"]` first (preferred
3-label vocab), fall back to `feat["regime_label"]` (5-label) for
hermetic test compatibility.

### Added

- `'duplicate_orphan_backfill'` to `CONTROLLED_VOCAB` and
  `EXCLUDED_FROM_OUTCOME_STATS` for cleanup ops on the P1-NEW-1 class.
- 13 regression-lock tests across:
  - `tests/shadow_trading/test_reconcile_orphan_status_tracking.py` (2)
  - `tests/services/test_scan_service_regime_keys.py` (2)
  - `tests/shadow_trading/test_exit_reason_w21_vocab_additions.py` (6)
  - `tests/shadow_trading/test_executor_begin_immediate_engine_aware.py` (3, from v0.36.15)

### Sibling-search

- `grep -rn "status = 'open' AND desk" src/` — only the orphan-check
  site had this narrow filter. Other queries already use broader
  status sets.
- `grep -rn "feat.get..regime..." src/` — only `scan_service.py:405`
  had the nonexistent-key ternary. No siblings.


## [v0.36.16] — 2026-05-18 — W21 execution cleanup: P1-1 (archaeology + script PG-compat)

W21 continuation. P0-1 + P0-2 shipped in v0.36.15; this release closes
P1-1 (sentinel-999 cleanup) plus the two PG-compat bugs in the cleanup
script that were blocking it from running.

### Fixed (script PG-compat — two bugs that prevented `backfill_v0.36.13_archaeology.py` from running against PG)

1. **Raw psycopg2 connection has no top-level `execute()` method.** Script
   relied on the sqlite3.Connection convenience method. On PG, every
   `conn.execute(...)` raised `AttributeError`. Fix: wrap psycopg2 in
   `PostgresConnectionWrapper` from `src.utils.db` (the same wrapper
   used everywhere else in the codebase). `cursor_factory=RealDictCursor`
   set so the wrapper's row-key access works.

2. **Regime-table probe aborted the PG transaction on missing relations.**
   Original probe: `SELECT 1 FROM <name> LIMIT 1` in a try/except. On PG,
   the failed query aborts the surrounding transaction, cascading every
   subsequent query to `current transaction is aborted, commands ignored
   until end of transaction block`. Fix: query `information_schema.tables`
   instead (succeeds regardless of whether the candidate exists, no tx
   abort). SQLite fallback path preserved for hermetic test environments.

### Data cleanup applied

- 14 trades with `exit_reason='unknown'` and `duration_days=999` → cleared
  (`duration_days` → NULL, `actual_entry_time` → NULL). Exit reasons remain
  `'unknown'` per spec discipline (no fabricated outcomes).
- 0 trades with `exit_reason='manual'` and `duration_days=999` (the 3
  manual entries from the original spec had already been cleared in a
  prior session).
- 555 `regime_at_entry IS NULL` rows reported but untouched (P2-2 work).

### Added

- `tests/scripts/test_backfill_v0_36_13_archaeology_pg_compat.py` — 3
  regression-locks for the two script fixes:
  - Asserts `PostgresConnectionWrapper` is imported
  - Asserts `RealDictCursor` is used in psycopg2.connect()
  - Asserts the regime probe uses `information_schema.tables`

### Sibling-search

- `grep -rn "SELECT 1 FROM .*LIMIT 1" scripts/` — only this script had the
  pattern. No other recovery scripts at risk of the tx-abort cascade.
- `grep -rn "psycopg2.connect" scripts/` — confirmed all PG-touching
  scripts either wrap with `PostgresConnectionWrapper` or use `cursor()`
  explicitly. No siblings.


## [v0.36.15] — 2026-05-18 — W21 execution cleanup: P0-1 + P0-2

**Context:** Week of 2026-05-18 is dedicated to trading-execution-error cleanup
(no new features). This release closes the first two P0 items from the
inventory at `docs/audits/2026-W21-execution-cleanup/inventory.md`.

### P0-1: 18 open positions reconciled (broker ↔ DB linkage restored)

After yesterday's PG wipe + SQLite restore, 12 of 18 open positions showed
NULL `alpaca_order_id` in the restored DB. The watch-loop reconciler
(running on v0.36.14 post-restart) closed 5 ghost positions, orphan-
backfilled 9+ active ones with fresh OCO brackets, and surfaced the
remaining DB-blind cases.

**Recovery:** new one-shot script `scripts/recovery/backfill_alpaca_order_id_post_wipe_2026_05_18.py`
queries Alpaca per-ticker, validates qty match against DB planned_shares,
and backfills `shadow_trades.alpaca_order_id` when broker has exactly one
active OCO. Qty-mismatch tickers (AVGO 6→4, KO 55→20) are SKIPPED rather
than silently papered over — they remain as P1 partial-exit reconciliation
work. 6 unambiguous backfills committed (BAC, COST, DUK, FDX, JNJ, UNP).

**Final state:** 16 of 18 open positions have full DB→broker OID linkage.

### P0-2: SQLite-only `BEGIN IMMEDIATE` → engine-aware (executor.py)

`src/shadow_trading/executor.py:665` unconditionally executed
`BEGIN IMMEDIATE` for the atomic duplicate-check, throwing
`syntax error at or near "IMMEDIATE"` on PG ~18 times in 7 days of logs
since the PG cutover. The exception-handler fallback was running correctly
(via `get_open_shadow_trade_for_ticker`), but the noisy warnings muddied
operator signal and the SQLite-native atomic check was silently disabled
on PG.

**Fix:** detect `PostgresConnectionWrapper` via `isinstance()` and skip
`BEGIN IMMEDIATE` on PG. PG's default READ COMMITTED isolation provides
equivalent SELECT semantics for the single-statement uniqueness check.
The two `_dup_conn.rollback()` calls that paired with the BEGIN are
likewise guarded.

**Sibling-search:** grep confirms `BEGIN IMMEDIATE`/`BEGIN EXCLUSIVE` only
appears at `src/shadow_trading/executor.py:665` (the fix site) — no
other sites carry the same SQLite-only dialect leak.

### Test fixture fix (collateral)

`tests/shadow_trading/test_broker_partial_swallow_upgrades.py` had two
tests (site7, site9) that inadvertently passed by relying on the OLD
`BEGIN IMMEDIATE` syntax-error to skip the in-block SELECT. With the
engine-aware fix, the SELECT now runs cleanly on both engines — meaning
the in-block dup-check is no longer silently bypassed. The two affected
tests now patch `src.shadow_trading.executor.connect_db` to return a
controlled mock so test outcomes don't depend on real DB state. New
helper `_no_dup_conn_mock()` documents the patching pattern.

### Added

- `scripts/recovery/backfill_alpaca_order_id_post_wipe_2026_05_18.py`
  — one-shot recovery script with --dry-run/--commit + qty validation
- `tests/shadow_trading/test_executor_begin_immediate_engine_aware.py`
  — 3 regression-locks pinning the engine-aware guard pattern
- `docs/audits/2026-W21-execution-cleanup/inventory.md` — full inventory
  of execution-layer issues; updated to mark P0-1 closed inline


## [v0.36.14] — 2026-05-18 — PG-wipe prevention (P0 incident #159)

PATCH hotfix closing two layered safety defects that allowed
`tests/notifications/test_platform_events.py` to silently DROP ~80 production
tables on 2026-05-17 21:28:34 UTC.

### Incident

A coding-team developer agent dispatched yesterday during the v0.36.13
sprint collected `tests/notifications/test_platform_events.py` as part of a
broader pytest sweep. That file's `@pytest.fixture(autouse=True)` body
auto-constructed `TEST_DATABASE_URL=postgresql://halcyon:$DOCKER_PG_PASSWORD@127.0.0.1:5433/halcyon`
on the assumption that port 5433 hosts a Docker test PG. In this operator's
deployment, port 5433 hosts the PRODUCTION halcyon database (per `.env`
`DATABASE_URL=postgresql://halcyon_app:...@localhost:5433/halcyon`).

The `pg_wrapper` fixture in `tests/conftest.py` then connected to the
constructed URL, ran the test, and on teardown executed
`DROP TABLE IF EXISTS {name} CASCADE` for every sync-eligible table in
`src/schema/registry.py` — wiping ~80 tables across ~3 seconds. The
`pytest_configure` P0 guard caught DATABASE_URL leakage to prod but did
not check TEST_DATABASE_URL because no test was expected to *set* that env
var itself.

The watch loop ran into a void for ~14.5 hours (2026-05-17 17:28 ET →
2026-05-18 08:00 ET restart and beyond) before the operator noticed via
the dashboard.

### Fixed

- **`tests/notifications/test_platform_events.py`** — the `autouse`
  fixture `_load_test_database_url_from_env` no longer constructs a
  TEST_DATABASE_URL. The fixture body is now a no-op with a long
  docstring documenting the incident. The right home for
  TEST_DATABASE_URL is operator environment, not test fixtures.
- **`tests/conftest.py` P0 guard (`pytest_configure`)** — extended to
  ALSO check `TEST_DATABASE_URL` against the prod signatures
  (`localhost:5433`, `127.0.0.1:5433`, `halcyon_app:`). Refuses pytest
  with a loud, operator-friendly explanation if either env var matches
  prod. The `_PROD_SIGNATURES` constant and `_is_prod_pg_url()` helper
  are now module-level for reuse.
- **`tests/conftest.py` pg_wrapper fixture** — added a second-line
  defense: if `TEST_DATABASE_URL` matches prod signatures at
  fixture-entry time (catches autouse fixtures or test modules that
  mutate env AFTER pytest_configure ran), the fixture calls
  `pytest.fail()` with a clear message instead of connecting.

### Sibling-search receipt

- `tests/monitoring/test_alert_silence.py` — has the fallback pattern
  `os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")`
  but it is gated behind `pytest.mark.skipif` requiring `TEST_DATABASE_URL`
  explicitly. The new pytest_configure guard now catches the prod-URL
  case BEFORE that fallback would fire.
- `tests/test_conftest_pg_guard.py` — the guard's own regression-lock
  test. Updated to cover the TEST_DATABASE_URL extension. (See test
  diff for the new assertions.)
- No other test file was found to construct a TEST_DATABASE_URL pointing
  at port 5433. The grep `grep -rn "DOCKER_PG_PASSWORD.*5433" tests/`
  matched only the one fixture this commit removes.

### Operator follow-up (RECOVERY — out of this PR's code scope)

PG halcyon database currently has 3 tables (analyst_estimates,
build_score_history, sync_state). 77 missing. SQLite at
`C:\arcis\data\ai_research_desk.sqlite3` is intact (588 trades, 18 open
positions, 75 training_examples, 3,969 notifications). Recovery steps
documented in `docs/audits/2026-05-18-pg-wipe-incident-159/recovery.md`
(forthcoming).


## [v0.36.13] — 2026-05-17 — Training Page + Audit Hardening

Six-track PATCH bundle resolving training-page blank charts, FED scraper
breakage, Finnhub entitlement loss, four recurring false-positive audit
alerts, duration-sentinel data archaeology, and forensic logging for the
`regime_at_entry` NULL class on live scans.

Root cause shared across all tracks: **legacy data archaeology + writer/reader
contract drift**. The deterministic audit added in v0.36.11 was correctly
surfacing symptoms; the underlying anomalies were data-quality issues, not
model degradation.

---

### Track (a) — Training outcome bucketing fix

Three stacked bugs in the training pipeline that silently dropped 48 of 88
closed trades and produced empty Training-page outcome distribution charts.

#### Fixed

- **`src/training/data_collector.py:311`** — `SELECT st.*, r.*` had 11 column
  collisions: `ticker, target_1, target_2, setup_type, setup_confidence,
  max_favorable_excursion, max_adverse_excursion, created_at, updated_at,
  llm_timeout_days, recommendation_id`. For 48 of 88 closed trades with
  `recommendation_id=NULL` (post-MO/BK manual cleanups), the LEFT JOIN missed
  and `r.ticker=NULL` overrode `st.ticker`. Every such trade was logged as
  `[TRAINING] Skipping None trade_id=...` and dropped — half the corpus
  silently lost. Rewritten to explicit column list with
  `r.created_at AS scan_created_at` alias; downstream callers updated to
  prefer `scan_created_at` for rec_date semantic, falling back to `st.created_at`.
- **`_classify_outcome`** — returned LOSS for `reconciled_stale` / `unknown` /
  `manual` / `qty_mismatch_partial_fill` trades (pnl=$0, not > 0). Added
  `_UNMEASURED_EXIT_REASONS = frozenset({"reconciled_stale", "unknown",
  "manual", "qty_mismatch_partial_fill"})` and `UNMEASURED` classification.
  The main training loop now skips UNMEASURED trades before the Stage-1 LLM
  call — 63 closed trades no longer generate "why this was a bad trade" theses
  for outcomes we never measured.

  **Note for future maintainers:** `_UNMEASURED_EXIT_REASONS` in
  `src/training/data_collector.py` and `_UNMEASURABLE_EXIT_REASONS` in
  `src/evaluation/cto_report.py` are intentionally separate frozensets with
  identical membership but different filter purposes: the training frozenset
  gates corpus exclusion (skip LLM call entirely), while the evaluation
  frozenset gates stat exclusion (drop from hold-period and confidence
  calibration metrics). Do not consolidate them — the distinction clarifies
  each module's intent and allows them to diverge independently if the two
  use-cases evolve differently.
- **`src/api/cloud_routes/training.py:138`** — dashboard
  `COALESCE(trade_outcome, outcome_type, outcome)` was using the verbose
  `_build_outcome_text()` blob as primary bucket key. The blob is a unique
  multi-line string per trade, producing ~40 distinct buckets with none
  matching `WIN/LOSS/TIMEOUT/PASS`, causing an empty chart. Reordered to
  `COALESCE(outcome_type, outcome, trade_outcome)` so compact labels win.
  Also added `outcome_type` column to both primary and contrastive INSERTs
  (`WIN/LOSS/TIMEOUT` for primary; `NULL` for synthetic contrastive rows).

#### Sibling-search receipt

Swept `data_collector.py` and `cloud_routes/training.py` for related
`SELECT *` wildcard joins, additional `_classify_outcome`-style pnl-only
classification sites, and other COALESCE ordering bugs:

- No other `SELECT st.*, <joined_table>.*` wildcard joins found in the
  training pipeline; the explicit column list fix is isolated to the one
  join at line 311.
- `src/evaluation/cto_report.py`: also classifies outcomes via exit-reason
  lists. Uses `_UNMEASURABLE_EXIT_REASONS` for stat exclusion — parallel
  pattern, intentionally separate (see note above).
- No other dashboard COALESCE ordering bugs found in `cloud_routes/training.py`.

---

### Track (b) — FED calendar scraper fix

`fed_collector.py` date extraction broke when the Fed website stopped
embedding 8-consecutive-digit tokens (`20260128`-style) directly in link text.
Page continued returning HTTP 200 with structural selectors intact — the
failure was silent (zero rows stored, no exception).

#### Fixed

- **`src/data_collection/fed_collector.py:_parse_href_date`** — replaced
  8-digit regex `r"(\d{8})"` with patterns that match the current Fed href
  formats (`/YYYY/MMDD.htm` path components and
  `/monetarypolicy/fomcminutes<8-digit>.htm` URL substrings). Function still
  returns `None` for non-date hrefs.
- **Link filter** — updated CSS/HTML selectors to match observed 2026 page
  structure confirmed by live probe (2026-05-17 PM): `div#article` present,
  `div.col-xs-12` present, `<main>` NOT present, `fomcMinutes` tokens present;
  8-digit bare tokens absent.
- Updated fixture HTML in `tests/test_data_collectors.py` to reflect current
  href format.

#### Sibling-search receipt

Reviewed all regex-based date parsers in `src/data_collection/` for the same
brittle 8-consecutive-digit pattern:

- `macro_collector.py`, `news_collector.py`, `docs_collector.py`: no
  href-date parsing; date construction from API response fields only.
- `fed_collector.py` was the only collector with bare href-date regex
  extraction. No siblings to fix.

---

### Track (c) — FINRA short-volume collector (replaces defunct Finnhub short_interest)

Finnhub `/stock/short-interest` returns HTTP 403 across all 102 SP100
tickers — plan entitlement lost. v0.36.12 added an early-exit so the
overnight cycle no longer threshold-fails; this track provides a real
replacement data source.

**Important metric caveat:** FINRA daily short-volume differs from Finnhub
settlement-date short-interest. FINRA `CNMSshvol` counts executed short sales
per trading day (flow); Finnhub reported total short positions per member firm
bi-monthly (stock). Both signal the same directional pressure but are not
numerically comparable. Any model feature or dashboard panel previously reading
from `short_interest` (0 rows since entitlement loss) and now reading from
`short_volume_daily` is using a same-direction but semantically different
metric. Callers should update column references and display labels accordingly.

#### Added

- **`src/data_collection/short_volume_finra.py`** — new collector hitting
  `https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt`
  (pipe-delimited, no auth, ~500 KB/day). Filters to SP100. Computes
  `short_ratio = short_volume / total_volume`. Stores to `short_volume_daily`.
- **`short_volume_daily` table** in `src/schema/registry.py` — columns:
  `ticker`, `trade_date`, `short_volume`, `short_exempt_volume`,
  `total_volume`, `short_ratio`, `source` (default `'finra'`), `collected_at`.
  Composite PK `(ticker, trade_date)`. `sync_to_postgres=True`,
  `sync_mode="incremental"`, `sync_time_column="trade_date"`.
  The existing `short_interest` table is left in place, marked deprecated in
  its schema description.
- **`src/scheduler/overnight.py`** — FINRA short-volume task wired into the
  Mon–Fri overnight schedule (FINRA publishes T+1).
- **`tests/data_collection/test_short_volume_finra.py`** — full regression-
  lock suite: URL format, pipe-delimited parser, SP100 filtering, `short_ratio`
  computation, schema column coverage. HTTP layer mocked per CLAUDE.md rule.

#### Sibling-search receipt

Reviewed all callers of the old `short_interest` table to ensure none are
silently reading 0 rows without warning:

- `src/data_collection/short_interest_collector.py` — early-exit path added
  in v0.36.12 is intact; updated to log a deprecation hint pointing to
  `short_volume_daily`.
- Dashboard short-interest panel: reads from `short_volume_daily` after this
  change. Label update recommended but not enforced in this track (out of
  scope for hotfix).
- No model-feature extractors found that join directly on `short_interest` —
  feature pipeline reads via the collector's output dict, not raw SQL joins.

---

### Track (d) — Audit hardening: suppress four false-positive alerts

Four audit alerts firing daily, all sourced from data-quality pollution rather
than model degradation. Each fix includes a data-quality filter and a
regression-lock test with fixture rows containing both polluted and clean data.

#### Fixed

1. **"75% good process → bad outcome" quadrant skew**
   (`src/evaluation/cto_report.py:583`) — `is_win = "win" in source` was
   bucketing `contrastive_win` (synthetic training rows, 10 of 75) as real
   wins. Added `WHERE source IN ('blinded_win', 'blinded_loss',
   'blinded_timeout', 'blinded_pass')` to exclude all `contrastive_*` rows
   from quadrant analysis. Also tightened `quality_score_auto IS NOT NULL`
   requirement: previously `score is not None and score >= 3.0` let NULL
   scores fall into the `bad_process_*_outcome` bucket, inflating the bad-
   process count.

2. **"All trades classified as 'unknown' regime"** (`src/evaluation/auditor.py`)
   — audit was coalescing NULL `regime_at_entry` → `'unknown'` and then
   reporting 100% 'unknown' regime. PG state is 45 GREEN / 398 NULL / 0
   'unknown'. Fix: skip NULL rows from the percentage denominator; do not fold
   them into 'unknown'. The alert now only fires if explicitly-written 'unknown'
   values exist, not for the NULL class (which is addressed by Track f).

3. **"Avg hold period 336 days"** (`src/evaluation/cto_report.py:440, 756`;
   `src/evaluation/model_monitor.py:85`) — exclude trades where
   `duration_days = 999` (sentinel written by the old backfill script; see
   Track e) OR `exit_reason IN ('unknown', 'reconciled_stale', 'manual',
   'qty_mismatch_partial_fill')`. The filter reduces the PG average from 137.7
   days to ~1.5 days, consistent with the pullback strategy's intended hold
   window.

4. **"0% confidence calibration + no rubric ≥70"**
   (`src/evaluation/cto_report.py:_compute_confidence_calibration`) — added
   two exclusion filters: `recommendation_id IS NOT NULL` (removes the 48
   LEFT-JOIN orphans repaired in Track a) and unmeasurable exit reasons (the
   same `_UNMEASURABLE_EXIT_REASONS` frozenset used in stat exclusion).

#### Sibling-search receipt

After fixing the four filter sites, swept `src/evaluation/` for other
quadrant, hold-period, or calibration computations that might share the same
NULL/sentinel/contrastive-contamination patterns:

- **`src/evaluation/scorecard.py:99`** — uses a similar pnl-sign outcome
  classification without an unmeasurable-reason guard. Same pattern as the
  pre-fix `_classify_outcome`. **Out of scope for this hotfix**; filed as
  known follow-up. Deferred: `scorecard.py` is not in the live training
  loop; fixing it does not unblock the Training page.
- **`src/evaluation/canary.py:234`** — `duration_days` sentinel check absent.
  Would benefit from the same `duration_days = 999` exclusion. **Out of scope
  for this hotfix**; filed as known follow-up. Deferred: canary fires on
  aggregate, not per-trade, so the distortion is less acute than in the CTO
  report's hold-period line.
- All other `cto_report.py` metric sites reviewed; no additional
  contrastive-contamination paths found beyond the four fixed above.

---

### Track (e) — Data archaeology: sentinel duration_days=999 cleanup

One-shot interactive backfill script for pre-existing sentinel pollution in
`shadow_trades`.

#### Added

- **`scripts/backfill_v0.36.13_archaeology.py`** — interactive script
  (`input()` confirmation before commit). Actions:
  - 11 trades with `exit_reason='unknown'` and `duration_days=999` (all
    share synthetic `actual_entry_time='2026-05-05T12:09:43.107835'` from
    the old bulk backfill): sets `duration_days=NULL` and
    `actual_entry_time=NULL`. `exit_reason` left as `'unknown'` — the
    outcome is genuinely unknown, only the sentinel is removed.
  - 3 trades with `exit_reason='manual'` and `duration_days=999`: same
    treatment.
  - 49 `reconciled_stale` trades: no change (real durations 0–7 days).
  - Attempts `regime_at_entry` backfill for NULL trades from available
    regime history. NOTE: `regime_snapshots` table does not exist in PG;
    the script queries `market_regime` / `regimes` per the schema registry.
    If no historical regime exists for a trade's entry timestamp, leaves NULL.
  - Runs all updates in a single transaction; prints pre/post counts; rolls
    back on operator cancel.
- **`tests/test_backfill_v0_36_13_archaeology.py`** — regression-lock suite
  validating pre/post state logic and rollback behavior.

#### Sibling-search receipt

Searched `scripts/` for other one-shot backfill scripts using the same
`duration_days=999` or `actual_entry_time='2026-05-05T12:09:43.107835'`
sentinel values to ensure no sibling scripts would re-introduce the pollution:

- No other scripts write `duration_days=999` as a sentinel. The original
  source was the v0.36.10-era bulk-reconciliation pass; that script has no
  successor.
- `scripts/post_close_check.py`: reads `duration_days` but does not write
  it. Not affected.

---

### Track (f) — Forensic logging for regime_at_entry NULL on live scans

13 of 18 currently-open trades have `regime_at_entry=NULL`. Root cause traces
to a vocabulary mismatch spanning three subsystems; cross-subsystem fix is
deferred to the next sprint. This track adds forensic logging so the next
overnight cycle leaves a clear trail.

#### Added

- **`src/services/scan_service.py`** — added explicit logging when
  `feat.get("regime")` and `feat.get("market_regime")` are both None at the
  regime-capture site. The log entry records the feat-dict keys present, the
  ticker, and the scan timestamp so the next failure is immediately traceable.

#### Known follow-up (deferred — see `docs/audits/2026-05-17-v0.36.13-training-page/regime_capture_followup.md`)

The root-cause trace identified a secondary bug at `scan_service.py:370`: the
ternary `feat.get("regime") or feat.get("market_regime")` reads keys that are
never set by the enrichment pipeline. The enricher sets `feat["regime_label"]`
and the nested `feat["traffic_light"]` dict — neither `"regime"` nor
`"market_regime"`. This line has been ineffective from day one.

The fix requires a **vocabulary decision**: the feature pipeline has two
incompatible regime vocabularies sharing the `regime_label` key name:

- `src/features/regime.py` — 5-label descriptive vocabulary
  (`calm_uptrend`, `volatile_uptrend`, `calm_downtrend`,
  `volatile_downtrend`, `transitional`)
- `src/features/traffic_light.py` — 3-label sizing vocabulary
  (`GREEN`, `YELLOW`, `RED`)

The `shadow_trades.regime_at_entry` column currently stores 3-label values
(45 `GREEN` rows). The correct fix is to read
`feat.get("traffic_light", {}).get("regime_label", "")` (matching
`executor.py:1116`) rather than the non-existent `"regime"` key — but this
change must be validated against all downstream readers before landing.
Additionally, `enrichment.py:_apply_traffic_light` has a broad exception
handler that leaves `feat["traffic_light"]` unset on failure; plugging that
gap is the deeper fix that would prevent the NULL class on future scans.

The `regime_capture_followup.md` audit doc (created in this sprint by the T6
agent) contains the full subsystem trace, the call graph from
`compute_market_regime()` through `executor.py:1116`, and the recommended
next-sprint scope. Review it before dispatching any follow-up work on this
class.

#### Sibling-search receipt

Searched for all sites reading `feat.get("regime")` or
`feat.get("market_regime")` across `src/`:

- `scan_service.py:370` — the site under investigation; forensic logging
  added.
- `src/services/scan_service.py:370` was the only callsite using the
  non-existent `"regime"` / `"market_regime"` keys. All other regime reads
  in the codebase correctly use `feat.get("traffic_light", {})` or
  `feat.get("regime_label")`.

---

### Service deploy

Restart `nssm restart ArcisWatchLoop` after merge to load the updated
modules. The short-volume collector begins populating `short_volume_daily`
on the next weekday overnight run (T+1 after merge). One-shot archaeology
script (`scripts/backfill_v0.36.13_archaeology.py`) requires manual operator
invocation against the PG instance.


## [v0.36.12] — 2026-05-17 — Residual PG-dialect collector hotfixes

Closes the three issue classes left over after v0.36.11's watch-loop
hardening. Two of them are sibling-search misses (`feedback_review_sibling_search`
discipline from 2026-04-26): when v0.36.11 fixed raw `INSERT OR REPLACE` in
`scripts/stress_test.py`, the same anti-pattern in `scripts/collect_1min_bars.py`
was missed and continued crashing every overnight 1-min-bars pull. The third
is a previously-undiagnosed PG transaction-abort cascade in the FRED macro
collector that silently dropped 22+ series per overnight run.

### Fixed

- **`scripts/collect_1min_bars.py`** — replaced raw `INSERT OR REPLACE INTO minute_bars`
  with `engine_aware_upsert(action="replace")`. Pre-fix the PG-routed overnight
  cycle failed with `syntax error at or near "OR"` 17 times in a row (Sat 2026-05-16
  23:30 → Sun 2026-05-17 00:00); no 1-min bars were stored for 2026-05-15.
- **`src/data_collection/macro_collector.py`** — replaced raw `INSERT INTO macro_snapshots`
  with `engine_aware_upsert(action="ignore")` so PG handles same-day re-runs
  natively via `ON CONFLICT (series_id, collected_date) DO NOTHING`. Also added
  `except DBError` with `conn.rollback()` as a defensive belt-and-suspenders.
  Pre-fix one `IntegrityError` on FEDFUNDS poisoned the shared PG connection
  and 22+ subsequent FRED series silently dropped with
  `current transaction is aborted, commands ignored until end of transaction block`.
  Silent data loss — `[MACRO] Collection complete: {'series_collected': 31, ...}`
  was still logged because the collector reports the *attempted* count, not the
  persisted count.
- **`src/data_collection/short_interest_collector.py`** — early-exit on the first
  HTTP 403 from Finnhub's `/stock/short-interest` endpoint, with a single
  "entitlement gap" warning. Returns `{"skipped_entitlement": True}` rather
  than threshold-failing the overnight cycle. Pre-fix the collector retried
  102 tickers, log-spammed 102 WARN lines, and threshold-failed the entire
  overnight collection on what is really an API-plan / key-entitlement issue.

### Added

- `minute_bars` to `_REPLACE_SEMANTICS` (in_place_update) per the T0.12 audit
  process. Leaf table — no incoming FKs, no triggers — same shape as
  `stress_test_results`. Audit doc updated with §7.1 "Post-audit hotfix
  additions" tracking `operator_view_state` + `stress_test_results` +
  `minute_bars`.
- `tests/test_collectors_pg_dialect_residuals.py` — 5 regression-lock tests
  pinning the three fixes plus the audit-dict entry.

### Sibling-search coverage

Reviewed all `INSERT OR REPLACE` and shared-conn loop sites to confirm no
further misses:

- `INSERT OR REPLACE INTO` raw SQL: only `scripts/collect_1min_bars.py:127`
  remained (now fixed). Other matches in `src/utils/db.py`, `src/evaluation/build_score.py`,
  `src/monitoring/system_metrics.py`, `src/platform/rigor/walkforward_universe.py`
  are all engine-aware dispatchers or explanatory docstrings.
- Shared-connection `for` loops with `INSERT` + `try/except continue` (cascade-risk):
  only `macro_collector.py` exposed. `options_collector`, `trends_collector`,
  `vix_collector`, `docs_collector` all open per-iteration connections so a
  poisoned tx in one iteration can't leak into the next.

### Service deploy

No service restart strictly required — the codepaths affected are nightly
overnight tasks, not the live trading loop. The next overnight cycle picks up
the fix automatically once main lands and the watch loop is on v0.36.11+.


## [v0.36.11] — 2026-05-17 — Watch-loop root-cause hardening (release cut)

Promotes the `[Unreleased]` watch-loop hardening section (merged 2026-05-16 in
PR #1122 as `df92c454` / `b5d7db6d`) to a tagged release. The hardening work
itself was deferred-tag pending operator decision on whether it should be the
release boundary — confirmed 2026-05-17. No new code in this cut; bumps
`src/version.py` + `tests/test_version.py` and dates the section.

Service deploy required: the watch loop process running pre-hardening Friday
code (PID started 2026-05-15 15:59:51) must be restarted via
`nssm restart ArcisWatchLoop` to load the new modules. Before restart the
following recurred at every overnight cycle:

- `function date(text, unknown) does not exist` (attribution resolver)
- `syntax error at or near "OR"` (stress-test persistence)
- `HOLDOUT EMPTY: corpus most recent ... — 5-day gap` (training scheduler)
- Reconciliation reporting auto-resolved stale rows as failures

All of the above are fixed by the modules loaded after restart.

### PATCH hotfix - watch-loop root-cause hardening

#### Fixed

- Replaced SQLite-only attribution cutoff SQL with a Python-computed timestamp
  so the post-close resolver works on the PG-routed path.
- Replaced stress-test `INSERT OR REPLACE` persistence with
  `engine_aware_upsert` and deterministic `stress_test_results.result_id`
  values.
- Blocked fine-tuning before GPU handoff when the 5-day temporal split leaves
  an empty holdout; UTF-8 subprocess env/encoding is now forced for training
  scripts.
- Split reconciliation output into `resolved_stale` and `unresolved_stale` so
  stale rows auto-closed by the reconciler do not keep the nightly summary in
  failure state.
- Added writer-side exit-reason coercion for `close_shadow_trade` and
  deterministic audit prechecks for unknown exits, bracket coverage, stale
  reconciliation, drawdown, and model win rate.
- Suppressed repeated YAML email-password warnings and kept `.env` /
  `EMAIL_PASSWORD` as the only password source.
- Converted expected stress-test yfinance historical gaps into structured
  caveats instead of repeated failure noise.

#### Hardened

- New trained models remain evaluation-only until holdout evaluation, canary
  evaluation, and the promotion gate pass.
- A recent critical deterministic audit suppresses new entry risk through the
  risk governor without writing the operator-only kill switch; exit management
  and reconciliation continue.

#### Docs

- Added `docs/audits/2026-05-16-watchloop-root-cause-hardening.md`.
- Updated `docs/operator-guide.md` and `MASTER.md` with durable operator and
  system behavior changes.


## [v0.36.10] — 2026-05-15 — Codemod safety tool (closes the v0.36.8 failure class)

Closes the lessons-learned requirement from v0.36.9. The v0.36.8 codemod
shipped a SyntaxError because its ad-hoc migration script ran without a
post-migration parse check. The lint test (regex-based) couldn't detect
it. This release adds the reusable infrastructure so any future bulk
migration auto-detects + rolls back the entire transform if any modified
file fails to parse.

### Added

- **`src/utils/codemod.py:apply_codemod`** — codemod runner with
  snapshot/rollback safety:
  ```python
  from src.utils.codemod import apply_codemod, CodemodError

  def transform(path, original):
      return original.replace("old", "new")

  result = apply_codemod([Path("a.py"), Path("b.py")], transform)
  # If any modified .py file fails py_compile, CodemodError raised and
  # ALL files reverted to their pre-codemod snapshots.
  ```

  Behavior:
  1. Snapshot every targeted file before applying the transform.
  2. Apply file-by-file, writing changes to disk.
  3. After all writes, `py_compile` every modified `.py` file.
  4. If ANY file fails to parse: revert ALL files (even ones that
     parsed cleanly) and raise `CodemodError`.

  Toggles: `py_compile_check=False` (skip parse check for non-Python
  codemods), `dry_run=True` (report what WOULD change without writing).

### Tests

- **`tests/test_codemod_safety.py`** — 8 tests across 4 classes:
  - **HappyPath**: simple transform writes changes; multiple files all
    succeed.
  - **Rollback**: syntax error in one file rolls back all; **replay of
    the exact v0.36.8 bug** (the malformed `(, DBError` import) is
    detected and reverted, asserting the regression-lock loop closes.
  - **NoOpAndDryRun**: identity transform skips the file (mtime
    preserved); dry_run reports but doesn't write.
  - **EdgeCases**: non-`.py` files (e.g. `.json`, `.md`) bypass
    py_compile; `py_compile_check=False` lets caller take responsibility.

### Decisions

- **Module location**: `src/utils/codemod.py` (not `scripts/`). Tests
  import from `src.utils.X`; importability matters more than the
  "developer tool" framing. A CLI shim in `scripts/` is a future
  follow-up if direct-from-shell invocation becomes useful.
- **`py_compile_check` defaults to True**: the v0.36.8 incident shows
  that opt-in safety doesn't get adopted. Opt-out (with explicit
  reason) is the right default.
- **Rollback covers ALL snapshots, not just .py files**: a partial
  rollback leaves the working tree in a hybrid state that's hard to
  reason about. Whole-batch atomicity > selective recovery.

### Cleanup performed in-session

3 remaining `needs_manual_review` shadow_trade records transitioned to
terminal status:
- **C** trade `b8c8437e` (26 sh @ $128.19, partial-fill artifact) →
  `cancelled` / `qty_mismatch_partial_fill`
- **KO** trade `e436496f` (35 sh @ $79.63, partial-fill artifact) →
  `cancelled` / `qty_mismatch_partial_fill`
- **UPS** trade `cdb246c7` (39 sh @ $109.42, broker flat) → `closed` /
  `reconciled_stale`

**Total `needs_manual_review` rows remaining in shadow_trades: 0.**


## [v0.36.9] — 2026-05-15 — Hotfix: v0.36.8 SyntaxError in src/scheduler/watch.py

The v0.36.8 codemod script that mechanically migrated 41 `except sqlite3.X:`
sites had a regex bug in its import-extension logic: it correctly handled
single-line `from src.utils.db import a, b, c` imports but malformed the
one multi-line parenthesized import in the codebase. The result at
`src/scheduler/watch.py:49`:

    from src.utils.db import (, DBError
        _scalar,
        configure_sqlite_for_production,
        connect_db,
        connect_db_with_pg_retry,
    )

The leading `(, DBError` produced a SyntaxError on import. Effect: the
watch loop service couldn't start at all post-v0.36.8 — startup
validation passed all 6 phases, but `from src.scheduler.watch import
WatchLoop` raised on module load, leaving the NSSM service in a Paused
state with the syntax error stuck in `arcis_err.log`.

### Fixed

- **`src/scheduler/watch.py:49`** — repair the malformed import:
  ```python
  from src.utils.db import (
      DBError,
      _scalar,
      configure_sqlite_for_production,
      connect_db,
      connect_db_with_pg_retry,
  )
  ```
- **Audited the other 12 migrated files** via `py_compile` — only this
  one file was affected; the script's bug specifically hit multi-line
  parenthesized imports, of which watch.py was the only example.

### Lessons learned for the codemod-as-a-tool path

Per the v0.36.8 closing insight ("A reusable `scripts/codemod.py` would
be a small productivity investment with multi-incident payoff"), this
release adds one explicit requirement to any future codemod runner:
**post-migration `py_compile` sweep across every modified file**, with
the migration aborted (and the diff reverted) if any file fails to
parse. The v0.36.8 codemod ran without this safety check, the lint
test passed (because `tests/test_no_naked_sqlite_exceptions.py` parses
each file as text via regex, not as Python), and the broken import
shipped. The compile-check would have caught it in seconds.


## [v0.36.8] — 2026-05-15 — Hotfix: engine-agnostic DBError exception tuples (41-site sweep)

Closes the systemic exception-class gap surfaced during the v0.36.7
council Round 1 diagnosis. The codebase had **45 sites** in 15 files
catching `sqlite3.Error` / `OperationalError` / `IntegrityError`
without their `psycopg2` counterparts. Each was a place where a
PG-specific error would silently escape the wrapper and crash the
enclosing loop — exactly the bug class that crashed today's daily
council.

### Added

- **`src/utils/db.py`**: three engine-agnostic exception tuples that
  span both `sqlite3` and `psycopg2` hierarchies:
  ```python
  DBError = (sqlite3.Error, psycopg2.Error)
  DBOperationalError = (sqlite3.OperationalError, psycopg2.OperationalError)
  DBIntegrityError = (sqlite3.IntegrityError, psycopg2.IntegrityError)
  ```
  Call sites use `except DBError:` instead of `except sqlite3.Error:`.

### Changed (41 sites across 13 files)

Migrated all engine-naked `except sqlite3.X:` to the canonical tuples:

| File | Sites | Mapping |
|---|---|---|
| `src/council/agent_data.py` | 22 | `sqlite3.Error` → `DBError` |
| `src/email/digest_builder.py` | 2 | `sqlite3.OperationalError` → `DBOperationalError` |
| `src/features/event_risk_score.py` | 2 | `sqlite3.Error` → `DBError` |
| `src/data_collection/{analyst,edgar,fed,short_interest}_collector.py` | 1 each | `sqlite3.IntegrityError` → `DBIntegrityError` |
| `src/api/cloud_routes/kpis.py` | 1 | `sqlite3.OperationalError` → `DBOperationalError` |
| `src/api/routes/live.py` | 1 | `(sqlite3.OperationalError, TypeError, ValueError)` → `DBOperationalError + (TypeError, ValueError)` |
| `src/platform/__init__.py` | 1 | `sqlite3.OperationalError` → `DBOperationalError` |
| `src/platform/promotion.py` | 1 | `sqlite3.OperationalError` → `DBOperationalError` |
| `src/platform/risk/exposure_limits.py` | 1 | `sqlite3.Error` → `DBError` |
| `src/scheduler/watch.py` | 1 | `sqlite3.Error` → `DBError` |
| `src/services/training_service.py` | 1 | `sqlite3.OperationalError` → `DBOperationalError` |
| `src/shadow_trading/reconcile_state.py` | 1 | `sqlite3.OperationalError` → `DBOperationalError` |
| `src/shadow_trading/state.py` | 1 | `sqlite3.OperationalError` → `DBOperationalError` |
| `src/training/ingestion_gate.py` | 1 | `sqlite3.Error` → `DBError` |
| `src/monitoring/manual_intervention_drift.py` | 1 | `sqlite3.Error` → `DBError` |

### Intentionally NOT migrated

- **`src/utils/db.py`** — the module that DEFINES the tuples; imports
  `sqlite3` as a building block.
- **`src/schema/sqlite.py`** — SQLite-engine-specific schema applier;
  never runs against PG, so its 4 `except sqlite3.OperationalError`
  catches are correctly engine-specific.

Both are allowlisted in the new lint test.

### Tests

- **`tests/test_no_naked_sqlite_exceptions.py`** — new lint test with
  two assertions:
  1. No naked `except sqlite3.X:` anywhere in `src/` (outside the
     2-file allowlist). Prevents regression by failing the build on
     any new offender.
  2. `DBError` / `DBOperationalError` / `DBIntegrityError` must include
     both engines' base classes. Prevents accidental narrowing.
- Regression sweep on `tests/council/` (10 tests), `tests/shadow_trading/`,
  `tests/monitoring/test_alert_silence.py`, `tests/test_db_util.py` —
  298 passed, 11 skipped, 3 pre-existing failures (2 `timeout` kwarg
  mock issues + 1 test_query_max_signal_works_on_pg permission error
  against prod PG, all confirmed pre-existing).

### Decisions

- **PATCH bump**: eighth defensive hotfix in the post-PG-cutover
  stabilization lineage. Consistent with v0.36.2–.7 scope.
- **Single-PR full sweep** chosen over phased rollout — the migration
  is mechanical, per-site risk is low, and bundling avoids partial
  states where some wrappers catch PG errors and others don't.


## [v0.36.7] — 2026-05-15 — Hotfix: council Round 1 GroupingError + MO/BK record cleanup

Closes the council daily-session crash surfaced during the post-v0.36.6
health-check. `gather_risk_data` at `src/council/agent_data.py:313`
contained:

    SELECT ticker, MIN(max_adverse_excursion) as worst_mae FROM shadow_trades ...

PG rejected with
`column "shadow_trades.ticker" must appear in the GROUP BY clause or be
used in an aggregate function`. The daily council fired at 08:32 ET
this morning, crashed Round 1, and no council session has run since.
SQLite was permissive (picks an arbitrary `ticker`), so the bug only
fired post-cutover. Same SQLite-ism residual class as v0.36.2 / v0.36.3
/ v0.36.5 / v0.36.6 (seventh hotfix of the day in this lineage).

### Fixed

- **`src/council/agent_data.py:313`** — dropped the `ticker` column
  from the SELECT. Downstream code (`parts.append(f"Worst MAE ...
  {mae['worst_mae']:.1f}%")`) only uses `worst_mae`; the `ticker` was
  dead weight that triggered PG's strict-GROUP-BY check.

### Data cleanup (operator-side, completed in-session)

- **4 MO/BK shadow_trade records transitioned** from
  `needs_manual_review` to `closed`:
  - BK trade_id `4ec035e9` (35 sh @ $134.57) → exit @ $135.95, +$48.30, `manual`
  - BK trade_id `a6c374ee` (34 sh @ $132.12) → exit @ $135.95, +$130.22, `manual`
  - MO trade_id `3df268b0` (51 sh @ $68.40, original orphan-backfill) → exit @ $72.88, +$228.48, `manual`
  - MO trade_id `9bed44ad` (51 sh @ $68.40, duplicate from the v0.36.3
    revert-then-rebackfill dance) → exit @ $72.88, $0.00, `reconciled_stale`
    (excluded from outcome stats)
- Total real P&L recorded retrospectively: **+$406.99**. Broker had
  already been flat for both tickers (operator manually closed earlier
  in the session); these are the bookkeeping records catching up.

### Tests

- **`tests/council/test_agent_data.py::TestAgentDataPgGroupingErrorRegressionLock`** —
  inspects `gather_risk_data` source, asserts no
  `SELECT ticker, MIN(max_adverse_excursion)` pattern. Catches any
  future re-introduction of the buggy form.
- Updated the existing `TestAgentDataMAE` tests to match the new SQL
  shape (drop `ticker` from SELECT).

### Decisions

- **PATCH bump** (not MINOR): seventh defensive hotfix in the SQLite-
  ism-residual class. Consistent with v0.36.2 / v0.36.3 / v0.36.5 /
  v0.36.6 scope.
- **Other potentially-similar patterns flagged for follow-up sweep**:
  `src/features/engine_helpers.py:62` and `src/api/cloud_routes/platform.py:90`
  both have `SELECT non_aggregate, MAX(...)` shapes that warrant
  verification (multi-line SQL — GROUP BY may exist below the SELECT,
  but worth a careful look in a future session).


## [v0.36.6] — 2026-05-15 — Hotfix: alert_silence UNION text/timestamp mismatch

Closes the new bug class surfaced during the post-v0.36.5 health-check.
`src/monitoring/alert_silence.py:_query_max_signal` UNION'd three signal
sources to find the most-recent notification timestamp:

  1. `notifications_sent.sent_at` — `text` (SQLite-shaped column)
  2. `notifications_digest_queue.flushed_at` — `TIMESTAMP WITHOUT TIME ZONE`
  3. `notifications_digest_queue.created_at` — `TIMESTAMP WITHOUT TIME ZONE`

PG refused the UNION with
`UNION types text and timestamp without time zone cannot be matched`.
The check fired ~every 30 min (13:24, 13:56, 14:27 ET) since the PG
cutover, silently disabling the alert-silence safety net. Same root
class as the v0.36.2 SQLite-ism residuals — text-typed columns shipped
from SQLite into the PG schema, with downstream code that compares them
against PG-native types.

### Fixed

- **`src/monitoring/alert_silence.py:_query_max_signal`** — replaced the
  three-source `UNION ALL` with three separate `ORDER BY col DESC LIMIT 1`
  queries, merged in Python via `_parse_ts`. Engine-agnostic by
  construction (no SQL-level type reconciliation needed). Performance
  cost is microseconds; the function runs at 5-min cadence on small
  tables. Verified live against halcyon-pg: returns a valid `ts` and
  `source` without raising.

### Decisions

- **Initial fix attempted `CAST(sent_at AS TIMESTAMP)`** in the original
  UNION query. SQLite's `CAST(text AS TIMESTAMP)` coerces to NUMERIC
  affinity and truncates the string at the first non-digit character —
  `'2026-05-15T14:00:00+00:00'` becomes the int `2026`. The cast was
  engine-divergent in the opposite direction from the original bug.
  Backed out in favor of the per-query Python-merge approach.

### Tests

- **`tests/monitoring/test_alert_silence.py`** — added
  `test_query_max_signal_does_not_union_mixed_types`. Inspects the
  function source and asserts no `UNION ALL` is present. Any future
  refactor that collapses back to a single UNION query (re-introducing
  the engine-divergent cast problem) will be caught by this guard.
- Existing 7 SQLite-based tests still pass; the PG-mode regression-lock
  (`test_query_max_signal_works_on_pg`) remains skip-on-missing-PG-env.


## [v0.36.5] — 2026-05-15 — Hotfix: paper/live adapter side + type normalization

Closes the deferred follow-up from v0.36.3. The `fix(adapter)` hotfix
this afternoon migrated the `status` field at 8 paper/live adapter
callsites from `str(order.status)` to `_strip_enum(order.status)`,
explicitly deferring the sibling `side` and `type` fields under "no
downstream code currently compares those against lowercase sets." That
was true at the time, but leaves the same enum-prefix bug pattern in
place for any future code path that does compare those fields. This
release closes the gap so the canonical adapter contract (every enum
field returned in canonical lowercase) holds uniformly.

### Fixed

- **`src/shadow_trading/alpaca_adapter_paper.py`** (6 line edits):
  - `place_paper_entry` (lines 50, 51) — `str(order.side)` /
    `str(order.type)` → `_strip_enum(order.side)` / `_strip_enum(order.type)`
  - `place_paper_exit` (lines 88, 89) — same migration
  - `place_bracket_order` (lines 156, 157) — same migration
- **`src/shadow_trading/alpaca_adapter_live.py`** (6 line edits):
  - `place_live_entry` (lines 134, 135) — same migration
  - `place_live_bracket` (lines 209, 210) — same migration
  - `place_live_exit` market-sell branch (lines 273, 274) — same migration
- **Skipped intentionally** — `place_live_exit` close_position branch
  (lines 246, 247) already hardcodes `"sell"` / `"market"` (no enum
  involved); `get_live_order_status` doesn't return side/type fields.

### Tests

- **`tests/shadow_trading/test_adapter_status_normalization.py`** —
  extended `_make_mock_order()` to accept `side` / `type` enum
  parameters (real Enum instances, mimicking alpaca-py 0.43+
  stringification). Added `_LocalOrderSide` + `_LocalOrderType` enums
  and `CANONICAL_SIDE_VALUES` / `CANONICAL_TYPE_VALUES` sets.
  Tightened the existing 8 tests: each now asserts the returned dict's
  `side` AND `type` AND `status` are all in their canonical lowercase
  sets. 6 tests went RED before the fix (the 6 functions returning raw
  `str(enum)`); 2 stayed GREEN (close_position branch hardcoded;
  get_live_order_status has no side/type fields). All 8 now GREEN.

### Decisions

- **PATCH bump** (not MINOR): defensive infrastructure for a known
  enum-stringification bug class, consistent with v0.36.3 / v0.36.4
  scope decisions. The canonical adapter contract is now uniform —
  every enum field returns the lowercase value, not the alpaca-py
  prefixed repr.


## [v0.36.4] — 2026-05-15 — Hotfix: bracket-protection backfill tool (no-bracket gap)

Closes the systemic gap surfaced by the 2026-05-15 health-check: 17 of
19 open shadow_trades had no active broker-side stop/target legs. Two
converging failure modes:

1. **Bracket canceled** by the 2026-05-12 reconciler mis-fire — upstream
   PG schema errors (`relation "model_versions" does not exist`) caused
   the reconciler to cancel TP/SL legs of seven tickers as "dangling
   orders for a missing trade record." The records existed; the schema
   query couldn't see them.
2. **No bracket ever attached** to orphan-backfilled positions — when
   the reconciler backfills an orphan (broker has shares, system
   doesn't), it creates the shadow_trade record but never submitted a
   new bracket order to the broker. 15 of the 17 unprotected positions
   came from this path.

### Added

- **`src/shadow_trading/bracket_attach.py`** —
  `attach_brackets_for_unprotected_positions(db_path, desk, dry_run,
  ticker_filter)`. Scans open shadow_trades and submits an OCO
  (sell-limit at `target_1` + sell-stop at `stop_price`) for each
  position the broker shows unprotected. Pre-flight validates qty match,
  stop < current < target_1, no other open orders, and not already
  protected. Per-ticker isolation: a failure on one ticker does not
  halt the batch. Returns
  `{scanned, submitted, skipped, failed}`. CLI:
  `python -m src.shadow_trading.bracket_attach [--dry-run]`.
- **`scripts/reattach_brackets.py`** — thin CLI shim deferring to the
  module above. Same `--dry-run` flag, same behavior.

### Changed

- **`src/shadow_trading/reconcile.py`** — after each
  `[RECONCILE-PAPER] Backfilled orphaned position` event, automatically
  call `attach_brackets_for_unprotected_positions(ticker_filter=[ticker])`.
  Closes the no-bracket gap on future orphan backfills. Wrapped in
  `try/except` so a transient broker failure can't abort the reconcile
  pass. Logs `[RECONCILE-PAPER] Auto-attached OCO for X` on success or
  `Bracket auto-attach for X skipped: <reason>` on pre-flight skip.

### Tests

- **`tests/shadow_trading/test_bracket_attach.py`** — 10 tests covering:
  happy path (submit + DB update), 6 skip reasons (no position, qty
  mismatch, stop ≥ current, target ≤ current, existing open orders,
  already protected), 2 flag tests (dry_run, ticker_filter), and 1
  per-ticker isolation test (one failure does not halt the batch).

### Operational follow-up (already completed 2026-05-15)

Per the same-day health-check incident:

- 17 OCO orders manually submitted via the tool (`scripts/reattach_brackets.py`)
  to retro-fit protection on the 17 unprotected positions found at the
  time of v0.36.4 cut: AMD, AMZN, BAC, C, COST, CVS, CVX, DIS, DUK, ETN,
  FDX, GILD, GOOG, GOOGL, JNJ, KO, UNP.
- All 17 now show parent=NEW + leg=HELD at the broker (limit + stop
  active). Verified via direct broker query.


## [v0.36.3] — 2026-05-15 — Hotfix: paper/live adapter status normalization (exit overshoot trigger)

Closes the 8-callsite SQLite-ism's `__str__`-prefix cousin: the
`fix/paper-exit-qty-asymmetry` sprint deferred eight `str(order.status)`
callsites in `alpaca_adapter_paper.py` (3) and `alpaca_adapter_live.py`
(5) that bypass `_strip_enum()` and return `"OrderStatus.X"` instead of
the canonical lowercase value. That mismatch caused the 2026-05-15 MO/BK
exit-overshoot incident: `place_paper_exit` returned
`status="OrderStatus.PENDING_NEW"`, `_is_pending_status` misclassified
it as a failure, the retry loop submitted a duplicate SELL, the race
between the original-pending-fill and the cancel-before-retry produced
a 2× sell, and the long-only positions ended at −51 (MO) and −34 (BK)
short. Reconciler's safety guard caught the overshoot and halted both
trades for manual review — exactly the working failure mode, but the
trigger is now removed.

### Fixed

- **`src/shadow_trading/alpaca_adapter_paper.py:50, 86, 153`** —
  `str(order.status)` → `_strip_enum(order.status)` in
  `place_paper_entry`, `place_paper_exit`, `place_bracket_order`.
  Lazy `_strip_enum` import added to each function (matches the existing
  `_check_enabled`/`_get_trading_client` pattern; avoids circular import
  at module load).
- **`src/shadow_trading/alpaca_adapter_live.py:134, 208, 242, 269, 305`** —
  same fix in `place_live_entry`, `place_live_bracket`, `place_live_exit`
  (both close_position and market-sell branches), `get_live_order_status`.
  Dormant in paper mode, but the next flip to live would re-trigger
  this without warning — defense-in-depth.

### Tests

- **New: `tests/shadow_trading/test_adapter_status_normalization.py`** —
  8 tests (3 paper, 5 live), one per fixed callsite. Each mocks
  `_get_trading_client` + `submit_order` with a local Enum that mimics
  alpaca-py 0.43+'s regular-Enum stringification behavior, asserts the
  returned dict's `status` field is in the canonical lowercase value set.
  RED across all 8 before the fix; GREEN across all 8 after. The
  `test_place_paper_exit_returns_normalized_status` test is the
  regression-lock for the exact MO/BK overshoot trigger.

### Decisions

- **`side` and `type` raw-`str(enum)` callsites left as-is.** The same
  enum-prefix pattern applies to `side` and `type` fields in all 8
  callsites, but no downstream code currently compares those against
  lowercase sets — only `status` does. Scope kept tight to the active
  bug. Tracked as future work; when migrated, the canonical pattern is
  the same as `_serialize_order` (use `_strip_enum` for every enum field).

### Operational follow-up

- **MO and BK paper positions** were manually unstuck at the broker
  before this fix (operator action; v0.36.3 prevents the trigger
  recurring on future orphan-backfilled positions).


## [v0.36.2] — 2026-05-15 — Hotfix: SQLite-ism residuals (post-cutover stability)

Patch release closing five surviving SQLite-only SQL forms that crashed or
silently failed against the post-cutover Postgres backend. Three were in
production code paths (`earnings_signals`, `exit_reconciliation`,
`cosine_similarity`); two were operator-run scripts (`post_close_check`,
`weekly_review`). The Phase 2.5 AST lint scanner is extended to catch the
bound-parameter `date(?)` / `datetime(?)` / time-modifier `date(?, '-N
days')` forms that let these slip past the cutover audits. Also includes
the 2026-05-14 P0 RCCA preventive actions (PA-1/PA-3/PA-4) that hadn't yet
been cut into a release.

### Fixed

- **SQLite-ism residuals causing live PG crashes (post-cutover):** the
  Sprint 5 §J5/§J6 Phase 2.5 migration left three production SQLite-only
  SQL forms that the AST lint scanner couldn't detect, plus two ops
  scripts the scanner doesn't cover. Each was crashing or silently
  failing on PG:
  - `src/data_enrichment/earnings_signals.py:106` —
    `WHERE earnings_date >= date(?)` → `>= ?`. SQLite's `date(text)` is a
    no-op cast; PG's `date(text)` produces a `date` value the text column
    can't compare with (`operator does not exist: text >= date`). Was
    crashing every ticker in every enrichment cycle since the cutover,
    poisoning the three sibling earnings signals in the same transaction.
  - `src/shadow_trading/exit_reconciliation.py:52` —
    `datetime('now', '-24 hours')` → Python-computed UTC cutoff bound as
    `?`. Nightly reconciliation was silently returning zero rows on PG.
  - `src/platform/features/cosine_similarity.py:151-152` —
    `date(?, '-400 days')` / `date(?, '-300 days')` time-modifier form
    → Python-computed window-start / window-end bound as `?`. Caught by
    the lint extension below (would have crashed YoY cosine similarity
    computations).
  - `scripts/post_close_check.py:147-149` —
    `julianday('now') - julianday(actual_entry_time)` → Python-computed
    days-since-entry.
  - `scripts/weekly_review.py:212, 320, 348-354` — six
    `datetime('now', '-7 days')` sites → single `SEVEN_DAYS_AGO_ISO`
    Python-computed cutoff bound as `?`.

### Tests

- **Lint: extend `SQLITE_DATE_FRAGMENTS` to catch parametrized casts
  (`tests/test_no_sqlite_isms_in_pg_safe_files.py`):** added `"date(?"`
  and `"datetime(?"` to the substring scanner, closing the blind spot
  that let `earnings_signals.py:106` slip past the Phase 2.5 audits. Two
  synthetic self-tests (`test_scanner_catches_synthetic_date_qmark_cast`,
  `test_scanner_catches_synthetic_datetime_qmark_cast`) regression-lock
  the new fragments. The closing paren is intentionally omitted from
  the fragments so the time-modifier form (`date(?, '-N days')`) is
  caught too — this immediately surfaced a third production site at
  `src/platform/features/cosine_similarity.py:151` that the original
  scanner missed.
- **`KNOWN_OFFENDERS` line shifts (cosine_similarity.py 185→195, 201→211)**
  rebased onto the new line numbers after the YoY-window inline migration.

### Operations

- **PA-1 — PG forensic logging baseline (`docker-compose.yml`):** added
  `logging_collector=on` + `log_directory=log` + `log_filename=postgresql-%Y-%m-%d_%H%M%S.log`
  + `log_rotation_size=100MB` to the postgres service command line. Forensic logs
  now persist to file at `/var/lib/postgresql/data/log/` rather than going only
  to stderr → docker logs (a finite circular buffer). Closes the observability
  gap identified in the 2026-05-14 P0 RCCA (without `logging_collector=on`, the
  docker log buffer rotated past the wipe window before forensic check ran,
  leaving the destructive DDL unidentified).
- **PA-1 — halcyon-pg memory cap raised 2G → 8G:** matches operator-side `docker
  update --memory=8g` applied 2026-05-15 (was asymmetric with halcyon-pg-test's
  unlimited cap). Gives PG headroom to bump `shared_buffers` from default 128MB
  to a workload-appropriate value (next operator task; requires PG restart).
- **PA-3 — codified recovery script (`scripts/recovery/restore_pg_from_snapshot.ps1`):**
  replaces ad-hoc interactive psql sessions for PG recovery from snapshot. Includes
  pre-flight checks (file size, optional SHA256), confirmation prompt, atomic
  DROP+CREATE schema, snapshot copy via PowerShell (avoids Git Bash path
  mangling that bit recovery on 2026-05-14), `psql -f` restore, post-restore
  GRANT ALL + ALTER DEFAULT PRIVILEGES (per memory feedback_drop_schema_grant_pattern
  — without these, halcyon_app can SELECT but not UPDATE → watch loop restart
  loop, incident 2026-05-15), table-count + row-count verification, and a
  canary UPDATE test as halcyon_app to confirm permissions actually work.
  Per-recovery audit dir at `C:\arcis\data\recovery-audit\<timestamp>\`.

### Fixed

- **PA-4 — `python-dotenv` path-pinning (`src/config/__init__.py:44`):**
  `load_dotenv()` now binds explicitly to `<repo_root>/.env` (computed from
  `Path(__file__).resolve().parent.parent.parent`) instead of using
  `find_dotenv()`'s default parent-directory walk. Closes the H5 finding
  from the 2026-05-14 P0 RCCA: pytest in agent worktrees at
  `C:/arcis/halcyon-lab/.claude/worktrees/agent-XXX/` was walking UP and
  finding the operator's production `.env`, inheriting `DATABASE_URL=prod-PG`
  and `ARCIS_PG_CUTOVER_ENABLED=1` — defeating worktree env-isolation
  contrary to memory `feedback_worktree_env_drift`. With the path-pin,
  worktrees only load their own `.env` (typically absent since `.env` is
  gitignored), restoring intended hermeticity.

### Docs

- **`docs/audits/2026-05-14-p0-pg-wipe/rcca.md`** — full RCCA-lite report
  for the 2026-05-14 PG halcyon table-wipe incident. Documents the four
  candidate hypotheses tested (3 falsified/weakened, 1 unconfirmed), the
  H5 finding (python-dotenv parent-walk inheritance), the 7 proposed
  preventive actions, lessons learned, and open questions. Honest about
  what's known vs unknown.


## [v0.36.1] — 2026-05-14 — Dashboard rectification: 9 P-cluster fixes + morning hotfixes

Patch release bundling the 2026-05-14 dashboard-rectification audit findings
(spec at `docs/audits/2026-05-14-dashboard-rectification/spec.md`). Covers 9
P-priority bug clusters (P0–P9), 6 morning hotfixes (#142–#147), and 4
investigation tasks (T7/T10/T11, plus T9 no-op with regression-lock). Eight
follow-up trackers (#150–#157) filed for out-of-scope items.

### Fixed

- **P0 — /training page blank (T1 / T1b):** `/api/data-collection-stats` SQL
  rewritten with explicit column aliases (`total_records`, `latest_collection`,
  `coverage_count`) on all 12 collector queries. `_build_table_stats` now reads
  by column name instead of positional index — eliminates `IndexError` on the
  Postgres `RealDictRow` path that caused every collector to show "No data
  collected yet". T1b stacks a `row = dict(row)` defensive cast so
  `sqlite3.Row` (which lacks `.get()`) works uniformly alongside `RealDictRow`.
  +16 parametrized tests + 4 unit tests + 1 sqlite3.Row regression-lock.

- **P1 — HSHS composite score 0.0 during early phase (T4):** `compute_hshs_score()`
  now returns two values: `overall` (weighted arithmetic mean — degrades
  gracefully when any dimension is 0) AND `overall_geometric` (existing strict
  geometric-mean gate). Frontend reads `overall`. Early-phase example
  (P=79/MQ=71/DA=74/FV=0/D=73) now correctly yields 58.85 instead of 0.0.
  `_weighted_arithmetic_mean` helper extracted. +8 tests.

- **P2 — Attribution badge reads total pairs instead of resolved count (T5):**
  Badge logic now reads `paired_n` (resolved-pair count) rather than total
  pairs. Was showing ADEQUATE (200+) while the body said 0 resolved. +3 tests.

- **P3 — LiveLedger starting_capital flash at $100 (hotfix #147):** Starting
  capital fallback changed from 100 → 100,000. Eliminates the transient $100
  equity display on fresh dashboard load.

- **P4 — Frontend formatter regressions (T6):** Two fixes: (1) LiveLedger
  equity renders as `$100,000.00` via `toLocaleString` (was plain integer).
  (2) Dashboard OPEN SHADOW TRADES "Days" column computes live days held from
  `actual_entry_time` when `duration_days` is null (was `0.00` for all open
  trades). +4 tests.

- **P5 — Open-position count misalignment (T8 / T8b):** `/api/status` SQL
  filter changed from `source='live'` → `desk='swing'`, returning the correct
  count (was 0 of 28 paper trades). Frontend `ShadowLedger` uses
  `['shadow-open', 'swing']` queryKey (was an unfiltered cache miss).
  `TradeHistory.jsx` adds `?? 0` nullish fallbacks for win/loss counts (was
  rendering `undefinedW / undefinedL`). T8b updates 4 regression-lock tests in
  `tests/api/test_status.py`. +6 component tests + 3 Python tests in
  `tests/api/test_cloud_routes_status.py`.

- **P6 — /validation page stuck on spinner (T9):** `/validation` renders an
  explicit "No validation runs yet" empty state when the API returns empty data
  (was stuck on `LoadingSpinner` indefinitely). +4 component tests + 1
  regression-lock.

- **P7 — /api/cto-report timeout >12 s (T9):** Endpoint gains a 5-minute TTL
  cache (was recomputing on every request over a 365-day window). +3 cache
  tests. (Note: default window was already 30 days — cache is additive hardening
  against worst-case operator-supplied windows; disclosed in PR.)

- **P8 — /schema page shows stale table count (T3):** `/schema` now displays 76
  tables (canonical registry count) instead of stale 48. `/system/table-counts`
  endpoint returns `{counts, registry_total: 76}`. Tracker #150 filed for cloud
  `/api/system/table-counts` parity. +2 vitest tests.

- **P9 — win_rate shown as 5000% (hotfix #144):** `/api/shadow/closed` and
  `/api/shadow/metrics` normalize `win_rate` from raw percentage to decimal
  (divide by 100) before returning. Dashboard now displays correct 50.0% instead
  of 5000%.

- **Morning hotfixes #142–#147 (pre-committed `b45085c1`):**
  - **#142:** WATCH MODE banner reads engine state (PG vs SQLite). Drops stale
    "Render sync" suffix that was always shown regardless of active engine.
  - **#143:** `deploy_info` captures `git` stderr via `subprocess.PIPE`; silences
    the stderr-to-console bleed on systems where git config is partially missing.
    Operator-side `git config --system safe.directory` applied for NSSM-managed
    service (see memory ref `reference_nssm_git_ownership.md`).
  - **#144:** Same as P9 above (win_rate percent → decimal normalization).
  - **#145:** SPA fallback exception handler catches `404` on non-`/api/*` GET
    routes and returns `index.html` so React Router handles client-side navigation.
  - **#146:** Three missing endpoints mirrored locally: `/api/shadow/desks`,
    `/api/shadow/sharpe-attribution`, `/api/diagnostic-runs` (+ `/{run_id}`,
    `/report`, `/plots`).
  - **#147:** LiveLedger `starting_capital` fallback 100 → 100,000 (same as P3).

### Added

- **T2 — Version bump to v0.36.1:** `src/version.py` bumped `v0.36.0` →
  `v0.36.1`. `src/api/app.py` and `src/api/cloud_app.py` import `VERSION` and
  strip the `'v'` prefix for FastAPI bare-semver responses. +6 regression-lock
  tests.

- **T3 — `/system/table-counts` endpoint:** New endpoint returning
  `{counts: {<table>: <n>}, registry_total: 76}` for programmatic schema-count
  queries. See P8 above.

- **T11 — Capability registry probes (investigation):** Three probes
  (`shadow_trade_cohort`, `reconcile_trades`, `attribution_resolver`) have
  correct code but appear unavailable on cloud due to a Render PG schema gap
  (tracker #155). Two probes (`strategy_registry_state`,
  `training_corpus`) had missing imports fixed (`NameError` on `connect_db`).
  Trackers filed: #154 (`psycopg2.Error` hardening), #155 (Render PG schema
  check), #156 (3-scan consolidation in `_training_corpus_counts`). +10
  parametrized tests.

### Investigated — no code bug found

- **T7 — Packets fields null on cloud:** Investigation confirmed the code is
  correct — `packets.py`, `store.py`, and `cloud_routes/trades.py` all use
  `SELECT *` and all 5 fields are in the registry. The null values are data-side:
  Render PG `recommendations` table has 2 rows with NULL price-target fields;
  SQLite has 875 populated rows. Tracker #151 (OPS) filed for PG backfill from
  SQLite. +3 regression-lock tests pinning the response contract.

- **T10 — Stress test 0.0% win rate:** No computation bug found. The 0.0% WR
  across all 7 historical scenarios is authentic: mean-reversion strategy +
  sustained downtrends (2008/2020/2022 crashes) + stop-first bracket evaluation
  genuinely produces near-zero WR. Trackers #152 (refactor
  `scripts/stress_test.py` to use shared helper) and #153 (design decision on
  strategy or scenario changes) filed. `compute_win_rate()` and
  `compute_win_rate_from_trades()` extracted as testable helpers. +10 regression
  tests.

### Follow-up trackers filed (out of scope for v0.36.1)

- **#150** — Cloud `/api/system/table-counts` parity (mirror T3 endpoint)
- **#151** — OPS: backfill Render PG `recommendations` NULL price-target fields from SQLite
- **#152** — Refactor `scripts/stress_test.py` to use shared win-rate helper
- **#153** — Design decision: keep mean-reversion strategy or adjust for stress-test scenarios
- **#154** — `psycopg2.Error` hardening in capability probes
- **#155** — Render PG schema check for capability probe tables
- **#156** — 3-scan consolidation in `_training_corpus_counts`
- **#157** — (reserved — filed during audit pass)

## [v0.36.0] - 2026-05-14 — Sprint 6 Wave B: Walk-Forward Validation Framework v1

Sprint 6 wires walk-forward validation v1 (binding spec at
`docs/audits/2026-05-11-stage1-completion/walkforward-spec-v1.md`) into the
production gate hierarchy: shadow_trading → production AND-composition with
fail-safe `WALKFORWARD_GATE_ENABLED` sentinel, DA-1 freshness cap, T13
scheduler auto-fire, and Stage-1 corpus-binding admissibility check.

### Added

- Sprint 6 Wave B T14 (SP-WF-014 + DA-1 + DA-5): production-gate walkforward composition in
  `_evaluate_production_gate` at `src/platform/promotion.py`. Sentinel guard mirroring T9:
  when `WALKFORWARD_GATE_ENABLED=false`, v0.35.0 bypass (DSR AND methodology only). When enabled
  (default): 3-gate AND-composition (DSR AND walkforward AND methodology). Strict no-row policy:
  no walkforward row → `passes=False` (no legacy fall-through). DA-1 freshness cap: sha-match +
  30-day window; on staleness `walkforward_stale=True` + `walkforward_stale_reason` set. Evidence
  symmetric with shadow_trading gate. DA-5 verified: `promote()` persists `walkforward_outcome_state`
  in `gate_result_json`. +8 tests. Spec refs: Sprint 6 plan T14, SP-WF-014, DA-1, DA-5.

- Sprint 6 Wave B T13 (SP-WF-013): scheduler auto-fire on backtest completion.
  (A) New module `src/platform/walkforward_autofire.py` — `auto_fire_walkforward()` spawns
  a detached subprocess of `python -m scripts.backtest.run_walkforward --auto-fire` after
  each successful backtest persist. Pre-flight checks: WALKFORWARD_AUTOFIRE_ENABLED env
  sentinel, corpus_id resolution (SP-WF-010 required), non-blocking filelock acquisition.
  Emits 5 platform_events event types: spawn_failed, skipped_locked, skipped_no_corpus,
  skipped_disabled, giveup. Never raises — backtest-persist success is never undone.
  (B) Post-persist hook in `scripts/run_backtest.py` calls `auto_fire_walkforward` after
  `persist_backtest_result()` succeeds, wrapped in try/except so a broken auto-fire never
  breaks the backtest CLI. (C) `_run_walkforward_reconciler()` method on `WatchLoop` —
  hourly during market hours (11–15 ET) finds orphan backtests without walkforward_results
  and fires auto_fire_walkforward; caps retries at 3 per (strategy_id, code_git_sha) per 24h
  across spawn_failed + skipped_no_corpus + timeout events; emits giveup on cap.
  (D) `scripts/backtest/run_walkforward.py` gains `--backtest-result-id`, `--auto-fire`,
  and `--force` flags; manual CLI invocations acquire per-strategy filelock (DA-4).
  (E) New dep: `filelock>=3.0,<4.0`. +9 tests across
  `tests/platform/test_walkforward_autofire.py` (5 tests) and
  `tests/scheduler/test_walkforward_reconciler.py` (4 tests incl. DA-2 no-corpus cap).

- Sprint 6 Wave B T10 (SP-WF-004/SP-WF-010): CLI flag + HTTP read-route extensions.
  (A) CLI: added `--corpus-id <str>` flag to `scripts/backtest/run_walkforward.py` — passes
  through to `WalkForwardConfig.corpus_id` per SP-WF-010; default None preserves backward
  compat. Added `--excess-sharpe-min <float>` flag — passes through to
  `WalkForwardConfig.excess_sharpe_min` per SP-WF-004; default None = raw-Sharpe gate only.
  Both flags are additive (omitting them leaves existing behavior unchanged). (B) HTTP read-route:
  `GET /api/walkforward/runs/{run_id}` already uses `SELECT *` so the T4 columns
  (`gate_version`, `excess_sharpe_min_used`) are returned automatically. (C) +5 tests:
  `tests/scripts/test_run_walkforward_cli.py` (2 new CLI flag tests) and new file
  `tests/api/test_walkforward_route.py` (3 tests for gate_version + excess_sharpe_min_used
  payload inclusion). T8 wired persistence; this task is the read-path + CLI entry-point.

- Sprint 6 Wave B T9 (SP-WF-009): promotion-gate sentinel guard in `_evaluate_shadow_trading_gate`
  in `src/platform/promotion.py`. When `WALKFORWARD_GATE_ENABLED` resolves false, orchestrator
  short-circuits to 2-gate AND-composition (DSR AND methodology only), skipping `_evaluate_walkforward_gate`
  entirely. When enabled (default), full 3-gate composition (DSR AND walkforward AND methodology).
  Evidence dict carries `walkforward_gate_enabled: bool` in all code paths (error, disabled, enabled)
  so audit trail can surface "WF gate DISABLED during this run". +3 tests in
  `tests/platform/test_promotion.py` (wf_disabled_skips_wf, wf_enabled_calls_wf,
  evidence_carries_gate_enabled_flag). This task lands before T14 (production-gate symmetry, Wave 5).

- Sprint 6 Wave B T8 (SP-WF-007/SP-WF-010): runner integration wiring T5/T6 outputs into
  `walkforward_runner.py`. (A) Corpus binding gate: when `config.corpus_id is not None`,
  delegates to the canonical filesystem-based gate at
  `src.evaluation.walkforward._gate_corpus_or_raise(corpus_id, boundaries)` — loads
  `data/corpus/<corpus_id>/manifest.json`, validates `is_admissible()`, and verifies every
  fold's test window falls within the manifest's `walkforward_window`. Raises `RuntimeError`
  on failure (per audit `cutover-impact.md:24` corpora are filesystem-based; no DB table).
  Bypass path preserved when `corpus_id=None`. Captured `manifest_admissibility` and
  `parse_failure_count` surface in `WalkForwardRunResult.evidence`. (B) VIX coverage validator
  wired: `validate_vix_tier_coverage` called once per run over all pooled OOS trades; result
  stored in `evidence['vix_coverage']` (`distinct_tiers`, `passes`, `missing_tiers`).
  `vix_tier_coverage` in `walkforward_results` populated from the structured validator result.
  (C) Persistence of T4 gate-version columns: `gate_version='v2'` written when
  `config.excess_sharpe_min is not None` (raw+excess Sharpe gate active); `'v1'` otherwise
  (raw-Sharpe only, registry default). `excess_sharpe_min_used` populated from
  `config.excess_sharpe_min`. (D) `derived_from_backtest_id: str | None = None` kwarg threads
  through `run_walkforward` → `WalkForwardRunResult` → `persist_run_result` into the T4 column
  of the same name (None default for manual invocations; T13 auto-fire reconciler will populate
  with the source `backtest_results.id`). +6 tests in `tests/platform/rigor/test_walkforward_runner.py`.
  T8(a) `build_walkforward_windows` runner wiring deferred to a follow-up task: the plan
  description called for a `window_count`/anchor-driven invocation path; that requires either
  a new `WalkForwardConfig.window_count` field (T5 module ownership) or a runner-level
  anchor+count kwarg pair (design call on anchor derivation source). Builder remains
  callable directly from T5 callers; no orphan imports left in the runner.

- Sprint 6 Wave B T4 (PR #1092): 3 new columns added to `walkforward_results` table in
  `src/schema/registry.py`: `excess_sharpe_min_used REAL` (per-run rf-adjusted Sharpe threshold;
  null if raw-Sharpe gate only), `gate_version TEXT DEFAULT 'v1'` (framework version string —
  'v1' = raw-Sharpe gate only; 'v2' = raw+excess Sharpe gates active), `derived_from_backtest_id
  TEXT` (backtest_results.id that auto-fire used to spawn the run; null for manual invocations).
  All nullable/defaulted (additive, backward-compat). +3 schema tests.

- Sprint 6 Wave B T2 (PR #1089): `src/evaluation/walkforward.py` refactored to use canonical
  `subtract_trading_days` from `src/scheduler/holidays.py`; local `_subtract_trading_days`
  helper deleted. Behavior-preserving at the call site (anchor is pre-normalized via
  `_next_trading_day`).

- Sprint 6 Wave B T1 (PR #1090): `WALKFORWARD_GATE_ENABLED` env-flag sentinel added to
  `_evaluate_walkforward_gate` in `src/platform/promotion.py`. Default `'true'` (enabled,
  blocking). Recognized values: `'true'`, `'1'`, `'yes'` (case-insensitive) — any other value
  disables the gate (fail-safe semantics; documented in PR #1090 docstring fix-up).

- Sprint 6 Wave B T7 (SP-WF-001 through SP-WF-016): SQLite-side migration verified via
  `validate-schema --fix` against a fresh test DB (`ARCIS_DB_PATH` override, never production).
  Three T4 columns confirmed materialized: `excess_sharpe_min_used REAL`, `gate_version TEXT DEFAULT 'v1'`,
  `derived_from_backtest_id TEXT`. Zero drift confirmed on subsequent `validate-schema` (no-fix run, exit 0).
  All 3 T4 schema tests pass (`test_walkforward_results_has_excess_sharpe_min_used_column`,
  `test_walkforward_results_has_gate_version_column`, `test_walkforward_results_has_derived_from_backtest_id_column`).
  Postgres sync via `python scripts/render_migrate.py` is **operator-owned** — to be run manually after merge.

- Sprint 6 Wave B T5 (SP-WF-001/002/006/010): `corpus_id: str | None = None` field added to
  `WalkForwardConfig` (additive, default None preserves backward compat; T8 will wire the runner
  gate). `build_walkforward_windows(anchor, n_windows, is_trading_days, oos_trading_days,
  embargo_trading_days)` builder added to `walkforward_config.py` — generates non-overlapping
  IS/OOS window tuples using canonical `subtract_trading_days` arithmetic (no calendar-day
  approximation). Enforces `train_end < test_start` invariant. `DEFAULT_WINDOWS` unchanged.
  +4 tests in `tests/platform/rigor/test_walkforward_config.py`.
- Sprint 6 Wave B T6: `VixCoverageResult` dataclass + `validate_vix_tier_coverage` function
  added to `src/platform/rigor/walkforward_power.py`. Wrapper layer over
  `walkforward_metrics.vix_tier_of` that returns structured pass/fail evidence
  (`distinct_tiers`, `passes`, `missing_tiers`) for downstream persistence
  by T8 (runner integration). +4 tests in `tests/platform/rigor/test_walkforward_power.py`.

- Sprint 6 Wave B T3 (SP-WF-004): `excess_sharpe_min: float | None = None` field added to
  `WalkForwardConfig` (additive, default None preserves backward compat). When set, wired into
  `compute_window_metrics` as an additional rf-adjusted excess-Sharpe gate using
  `canonical_sharpe.rf_adjusted_excess_sharpe` as the source of truth. `WindowMetrics` gains
  three new default-None fields: `excess_sharpe`, `passes_excess_sharpe`, `excess_sharpe_fail_reason`.
  +3 tests in `tests/platform/rigor/test_walkforward_metrics.py`.

- Sprint 6 Wave B T11 (PR #1101): regression-lock test suite for the walk-forward end-to-end
  pipeline. New `tests/platform/rigor/test_walkforward_regression_lock.py` (60 LOC, hermetic —
  no DB, no network, no corpus FS) with 4 deterministic tests pinning the three-state outcome
  state machine and the pooled-Sharpe determinism invariant:
  `test_regression_lock_pass_outcome` (Sharpe ≈ 3.0 synthetic trades → PASS),
  `test_regression_lock_fail_outcome` (constant `-0.5` returns in ≥2 windows → FAIL),
  `test_regression_lock_inconclusive_outcome` (≥2 windows with <10 trades → INCONCLUSIVE),
  `test_regression_lock_pooled_sharpe_stable` (0.01-tolerance determinism lock catching
  numerical drift across T3/T5/T6/T8 modules). Reuses `FakeTrade` + `_generate_trades` +
  `_minimal_spec` prior art from `test_walkforward_runner.py`. The agent grandfathered
  T13's pre-existing `_run_walkforward_reconciler` 62-line function in `known_violations.json`
  as part of #731 disclosure.

### Changed

- Sprint 6 Wave A — SP6 catch-all sweep (7 PR-review follow-ups from Sprint 5):
  - **WA1** (`_get_finnhub_key` extraction, #1082/#1083/#1084): extracted the
    12-line `_get_finnhub_key` helper from 6 collectors (institutional_ownership,
    filings_sentiment, press_releases, insider, short_interest, analyst) into
    `src/data_collection/_finnhub_shared.py`. Each collector now imports
    `get_finnhub_key as _get_finnhub_key` to preserve existing test patch targets.
    +1 test in `tests/data_collection/test_finnhub_shared.py` (env-precedence +
    YAML fallback + None-on-neither).
  - **WA2** (`price_target` matrix, #1085): added `"price_target"` to
    `_FEATURE_MATRIX['fundamental-1']` in `src/data_enrichment/finnhub_plan.py`.
    Activates the `analyst_collector.py:147` gate on paid plans (Finnhub
    fundamental-1 tier includes `/stock/price-target`). Removed `"price_target"`
    from `_REVERSE_INVARIANT_ALLOWLIST` in the T26 AST scanner test. +1 test.
  - **WA3** (PE quality thresholds, #1084): `_derive_quality_flag()` in
    `src/data_enrichment/financials.py` now reads PE bounds from
    `data_enrichment.fundamental_quality_thresholds.{pe_min,pe_max}` in
    `config/settings.example.yaml`, with fallback to hardcoded 2.0/200.0 defaults
    for backward-compat. +2 tests in `tests/data_enrichment/test_financials.py`.
  - **WA4** (env-pollution test fix, #1085): added
    `monkeypatch.delenv("FINNHUB_PLAN", raising=False)` to
    `test_feature_matrix_distinguishes_free_and_premium` in `tests/test_enrichment.py`
    so the test passes on machines with `FINNHUB_PLAN` set in `.env`. Moved the
    entry in `docs/audits/known-pre-existing-failures.md` to "Recently cleared".
  - **WA5** (Decision 27 lock test, #1083): new structural test
    `tests/data_collection/test_filings_sentiment_revision_semantics.py` locks the
    current `action='ignore'` behavior (second upsert of same PK with different
    score silently drops the revision). Test PASSES now; inverts if/when
    `action='replace'` is adopted.
  - **WA6** (migration utils extraction, #1067): created
    `scripts/_shared_migration_utils.py` with `topo_sort_tables` (uses
    `graphlib.TopologicalSorter`, Python 3.9+ stdlib), `redact_password`, and
    `confirm` helpers. Both migration scripts (`sqlite_to_pg_migrate.py`,
    `render_to_local_migrate.py`) import from the shared module. SQLite-to-PG
    migration now applies topo sort before migrating (was missing, PR #1067 fix).
    +6 tests in `tests/scripts/test_shared_migration_utils.py`.

## [v0.35.0] - 2026-05-13 — Sprint 5 close: cutover stabilization + notification policy + LLM packet enrichment + dual-GPU disposition

Sprint 5 delivered 15 named tasks across 6 waves (C cutover-stabilization,
C7a packet sections, C7b plan-gated Finnhub enrichment + AST scanner,
D notification policy/digest/silence, E dual-GPU disposition, F dev tooling)
plus 14 trackers (#54/#56/#69/#92/#93/#94/#101/#103/#108/#109/#110/#111/#115)
plus pre-T16 hardening (#1081). Final commits: `2b5e7cab` (T26 / Wave C7b
COMPLETE) → tag `v0.35.0` at this PR's squash-merge.

**Key architectural deliveries:**
- Phase-3-revised cutover from SQLite → local Postgres (localhost:5433/halcyon)
  with `_RowFactoryCursor` + `_scalar` + `engine_aware_upsert` + 82-site
  mechanical-replacement sweep; `ARCIS_PG_CUTOVER_ENABLED` env gate routes
  `connect_db()` to the right engine.
- 7th-generation AST-based structural guardrail (`test_finnhub_plan_runtime_coverage`,
  joining the M4 / wrapper / `_scalar` / fetchone-int / policy-purity /
  fetchall-listcomp / conflict-marker scanners).
- Wave D notification subsystem (policy gate → digest queue → safe_send
  verdict-dispatch → alert silence detector with engine-agnostic SQL).
- Wave C7a/C7b LLM packet enrichment (4 council sections + 4 plan-gated
  Tier-2 sections + DATA CONTEXT header for plan-gated-vs-data-gap disambiguation).
- Dual-GPU workload-separation deferred to first post-Sprint-5 maintenance
  window per Wave E disposition doc (RTX 3060 + RTX 3090 split design preserved).

### Added

- `tests/test_no_conflict_markers_in_repo.py` (#109): structural CI test that scans `src/`, `tests/`, `scripts/`, `docs/`, `config/`, `.github/` for git conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) and fails if any are found outside the allowlist. Closes the marker-class that bit twice in 24h on 2026-05-12 (PR #1065 hotfix, PR #1069 hotfix) when Edit-tool silently failed on multi-line `old_string` matches during rebase conflict resolution. Also resolves a previously unknown stranded marker discovered at `docs/archive/quality/improvement_log.md:8` during this scan.
- `scripts/sqlite_to_pg_migrate.py` (#111): interactive YES-prompt confirmation gate added before wet-write phase. Symmetric to render_to_local_migrate.py's `_confirm()` helper added in #1067. Closes the safety gap surfaced 2026-05-12 when the script ran against a stale `DATABASE_URL` pointing at Render PG (instead of intended local PG) and shipped data in the wrong direction. The `--yes` CLI flag skips the prompt for scripted/CI use. Dry-run path unchanged (no confirmation needed for read-only).
- T13 (Wave D D4): `_html_escape` applied to `notify_regime_alert` (#93) and `notify_streak_alert` (#94) to prevent HTML injection in Telegram alerts. Pattern mirrors Sprint 4 T5 (notify_risk_alert / notify_exposure_alert).
- Pytest isolation conftest fixture sets `ARCIS_NOTIFICATION_SOURCE='pytest:<worktree>'`, monkeypatches `_send_single` to a `_null_router` stub, and clears `ARCIS_TELEGRAM_TOKEN` per-test — prevents tests from accidentally calling the real Telegram API (#101).
- 5 new tests in `tests/notifications/test_html_escape_siblings.py` including an AST guardrail that scans `notify_regime_alert` and `notify_streak_alert` for unescaped f-string interpolations.
- T14 (Wave D D5): `src/monitoring/alert_silence.py` — `check_alert_silence(now_et, threshold_minutes=60)` detects notification silence during market hours by reading UNION of notifications_sent (MAX sent_at), notifications_digest_queue (MAX flushed_at), AND notifications_digest_queue (MAX created_at — proves watch loop alive during digest-only quiet hours). Emits via `safe_send(event_type='alert_silence', severity='high')` + writes platform_events row for forensic trail. Wired as 5-min `tick_alert_silence` handler in WatchLoop.
- `src/scheduler/holidays.py::is_market_open(now_et)` — extracted from `WatchLoop._is_market_open` for re-use across monitoring code. WatchLoop method becomes a thin delegate. +3 unit tests in `tests/scheduler/test_holidays.py`. +5 tests in `tests/monitoring/test_alert_silence.py`.
- T14 fix-up (PR #1076 review, operator 2026-05-13): rewrote `_query_max_signal` SQL from `SELECT MAX(ts), source FROM (...)` (SQLite-only valid — PG rejects with `psycopg2.errors.GroupingError: column "source" must appear in the GROUP BY clause`) to `SELECT ts, source FROM (...) u ORDER BY ts DESC NULLS LAST LIMIT 1` (engine-agnostic; works on both SQLite and PostgreSQL). Original form would have caused silent infinite-retry loop in `tick_alert_silence` post-cutover (#1055/#1056). Added +3 tests in `tests/monitoring/test_alert_silence.py`: empty-tables → `(None, "none")`, most-recent-source selection, and PG-mode regression test `test_query_max_signal_works_on_pg` (skipped unless `DATABASE_URL=postgres://...` + `ARCIS_PG_CUTOVER_ENABLED=1`).
- `src/notifications/telegram.py::notify_alert_silence(last_seen, minutes_silent)` — dedicated Telegram formatter for alert silence events; replaces stub `notify_system_event` mapping in `_EVENT_MAP`.

### Changed

- T19 (Wave C7a.3): `=== RECENT ATTRIBUTION ===` section at index 15 (after T18's HISTORICAL CREDIBILITY). Enricher reads `attribution_trades` joined to `recommendations` over a configurable lookback window (default 30 days, overridable via `config['data_enrichment']['attribution_window_days']`). Computes setup-class W/L rate (closed trades only, filtered by `setup_class`), ticker-specific mean PnL, and similar-ticker (sector-match, excluding self) mean PnL. Closed trades only: filters on `llm_portfolio_pnl_pct IS NOT NULL`. No-recent-trades fallback: `(No attribution trades in window)`. Three private helpers (`_setup_class_win_rate`, `_ticker_mean_pnl`, `_similar_sector_mean_pnl`) keep the main function under the 60-line limit. Tests in `tests/llm/test_packet_recent_attribution.py` (+3).
- T20 (Wave C7a.4): `=== STRATEGY CONTEXT ===` header preamble (prepended BEFORE TECHNICAL DATA in the prompt — structurally different from indexed sections T17-T19). Enricher reads `strategy_registry` keyed by the `shadow_trades.strategy_id` FK (T2/#56). Populates `strategy_status` (current_status) and `strategy_parent_name` (display_name). NULL-strategy_id fallback `Strategy: (unassigned - legacy trade)` for legacy trades pre-dating the T2 FK wiring. T2 hard dependency verified — `shadow_trades.strategy_id` FK present in `src/schema/registry.py` (L320-L323, L336-L337 with `initially_deferred=True`). Tests in `tests/llm/test_packet_strategy_context.py` (+3). Wave C7a deliverables complete (PR #1077 T17+T18 plus this PR's T19+T20); closes part of #102.
- T15 (Wave E): Filed `docs/audits/2026-05-12-dual-gpu-ideation/disposition.md` — dual-GPU workload separation is deferred to first post-Sprint-5 maintenance window. Updated 4 stale-text references in the canonical spec inline: test-floor 3682→5400, Sprint 6→post-Sprint-5, Unsloth→Transformers+PEFT+TRL, NUM_PARALLEL=1→4 (per RTX 3090 swap, memory project_gpu_upgrade). Test-floor target corrected from initial 5350 to 5400 per PR #1073 review (operator flagged v2 vs v3 closeout plan target).
- T25 (Wave C7b.5): `analyst_collector` nightly cap is now plan-conditional. `fundamental-1` tier → 100 tickers/night (well within the 30 API calls/sec global rate-limit); free tier → 20 tickers/night (preserved current behavior). `_get_nightly_cap` uses `get_finnhub_plan(config)` directly rather than `finnhub_plan_supports()` because the cap is a tier-numeric property, not a binary feature gate (operator decision 2026-05-13 post-review of initial implementation). Rate-limit source: https://finnhub.io/docs/api/company-dps-estimates retrieved 2026-05-13 — "On top of all plan's limit, there is a 30 API calls/second limit." Closes part of #102 — Wave C7b.5 deliverable.
- Wave C7b Batch 1 (T21+T22): plan-gated Finnhub collectors for institutional ownership + filings sentiment, surfaced through two new packet sections.
  - T21 (C7b.1): `src/data_collection/institutional_ownership_collector.py` — plan-gated Finnhub `/stock/institutional-ownership` collector. Writes one aggregated row per ticker (total_shares, num_holders, top-5 concentration, qoq_delta) into the new `institutional_holdings` table. Gate at function entry on `finnhub_plan_supports('institutional_ownership', config)`; no API call on free-tier (Decision 30). New `=== INSTITUTIONAL FLOW ===` packet section at index 4.5 (between SECTOR RELATIVE and FUNDAMENTAL SNAPSHOT). Three render states: (a) plan supports + data present → full render with data age; (b) plan supports + no data → `(No data yet - collector pending)`; (c) plan does not support → section ABSENT. Nightly tick wired in `src/scheduler/overnight.py`. +5 tests in `tests/data_collection/test_institutional_ownership_collector.py`.
  - T22 (C7b.2): `src/data_collection/filings_sentiment_collector.py` — plan-gated Finnhub `/stock/filings-sentiment` collector. Writes one row per filing (filing_type, filed_at, sentiment_score, sentiment_label) into the new `filings_sentiment` table. Distinct retrieval cadence from `edgar_filings` (Decision 27 — separate tables, separate collectors). Gate at function entry on `finnhub_plan_supports('filings_sentiment', config)`; no API call on free-tier (Decision 30). New `=== MATERIAL EVENTS ===` packet section at index 7.5 (between RECENT NEWS and MACRO CONTEXT). Section is a composition wrapper around sub-blocks — T22 seeds with the filings_sentiment sub-block. Composition rule: section header omits entirely if no sub-block has plan-support. T23 adds the press_releases sub-block. Nightly tick wired in `src/scheduler/overnight.py`. +5 tests in `tests/data_collection/test_filings_sentiment_collector.py`.
  - T23 (C7b.3): `src/data_collection/press_releases_collector.py` — plan-gated Finnhub `/press-releases` collector. Writes one row per press release into the new `press_releases` table. Distinct catalyst category from RECENT NEWS pipeline (Decision 27). Gate on `finnhub_plan_supports('press_releases', config)`. Extends T22 MATERIAL EVENTS section with the second sub-block. Composition rule honored: section renders with only present sub-block when only one of {filings_sentiment, press_releases} has plan-support. Nightly tick wired in `src/scheduler/overnight.py`. +6 tests in `tests/data_collection/test_press_releases_collector.py`.
  - T24 (C7b.4): `src/data_enrichment/financials.py` (NEW) — runtime read-only enricher reading existing nightly-export sink `data/finnhub_fundamentals/<ticker>.json` (no Finnhub API call at runtime). Plan-gated on `stock_financials`. `enrich_stock_financials` sets `_stock_financials_plan_supports` (mirrors institutional/filings/press_releases sibling enrichers) so DATA CONTEXT can distinguish plan-gated absence from a transient sink-missing data-gap. Enriches FUNDAMENTAL SNAPSHOT in-place with live P/E, debt/equity, gross margin, ROIC, quality flag. Free-tier preserves existing last-known cached fallback. DATA CONTEXT header (spec 4.8.1): prepended at prompt top when at least one Tier-2 section (INSTITUTIONAL FLOW, MATERIAL EVENTS, FUNDAMENTAL SNAPSHOT live-enrichment) omits, distinguishing plan-gated absences from data gaps. `_collect_tier2_omissions` checks the plan flag (not data presence) for all three Tier-2 sections — closes the Decision 32 falsifiability gap operator flagged in PR #1084 review (2026-05-13). Stale-data ageing (spec 4.8.2) surfaces `*_age_days` when above threshold (default 7d, overridable via `data_enrichment.stale_data_threshold_days`). +4 tests in `tests/data_enrichment/test_financials.py` + 5 tests in NEW `tests/llm/test_data_context_header_trigger.py` (3 + 2 plan-vs-data-gap regression locks).
  - Closes #102 — Wave C7b complete pending T26 AST scanner.
- T26 (Wave C7b.6): `tests/test_finnhub_plan_runtime_coverage.py` (NEW) — two-way AST scanner enforcing runtime coverage of `_FEATURE_MATRIX`. Forward invariant: every fundamental-1 feature has at least one `finnhub_plan_supports(<feature>, ...)` call site in src/ (closes the "stuck on shelf" class — feature defined but no runtime caller). Reverse invariant: every `finnhub_plan_supports()` call site references a feature in `_FEATURE_MATRIX['fundamental-1'] ∪ ['free']` (closes the "gate calls unknown feature so always returns False" class). Both invariants tolerate narrow documented allowlists: `_UNWIRED_FORWARD_ALLOWLIST` (company_executive, filings, fund_ownership, stock_ownership — reserved-in-matrix-for-downgrade-ceremony but unwired) and `_REVERSE_INVARIANT_ALLOWLIST` (price_target — analyst_collector.py latent gate-off, deferred per operator decision 2026-05-13). Includes 4 self-tests that exercise the diff/scanner logic against synthetic source-tree fixtures, proving the test catches the failure modes it claims. To make the forward invariant pass, added defensive plan-gates at 6 free-tier call sites (no behavior change on current plans — company_news / insider_transactions / recommendation_trends / short_interest are in both `'free'` and `'fundamental-1'`, so gates are no-ops; guards against future plan-tier additions that might exclude these features): `src/data_enrichment/news.py::fetch_recent_news` + `fetch_historical_news` (company_news), `src/data_enrichment/insiders.py::fetch_insider_activity` (insider_transactions), `src/data_collection/insider_collector.py::collect_insider_transactions` (insider_transactions), `src/data_collection/short_interest_collector.py::collect_short_interest` (short_interest), `src/data_collection/analyst_collector.py::collect_analyst_estimates` (recommendation_trends). Test-has-teeth verified (revert→FAIL listing 4 missing features, re-apply→6/6 PASS). Updated `tests/test_data_collectors.py::test_collect_skips_price_target_when_plan_does_not_support_it` to differentiate the mock by feature (recommendation_trends=True, price_target=False) so it tests the price-target gate in isolation rather than the new aggregate behavior. Closes #102 — Wave C7b deliverables COMPLETE.

### Fixed

- `DigestQueue.pending_count` and `DigestQueue.abandoned_count` now use `_scalar(row)` from `src.utils.db` instead of `.fetchone()[0]` positional indexing — the positional form raises `KeyError(0)` on PG (post-cutover) because `PostgresConnectionWrapper` returns `RealDictCursor` rows. Pre-existing leak from PR #1072 merge caught by `test_no_fetchone_int_index_in_pg_unsafe_files` AST scanner during operator's PR #1076 review (2026-05-13).
- `scripts/sqlite_to_pg_migrate.py`: added `connect_timeout=30` to the wet-write `psycopg2.connect` at line 286 (symmetric with `render_to_local_migrate.py` lines 345-346 which already had it from PR #1070 hardening). Closes the hang-on-Render-outage failure mode operator flagged in PR #1080 review.

- `DigestQueue` now correctly round-trips dataclass payloads through enqueue→DB→flush→dispatch. Three coordinated fixes: (a) `enqueue` calls `dataclasses.asdict()` before `json.dumps` to support dataclass payloads; (b) `flush()` injects `event_type` and `severity` from DB columns into the dispatched dict (the dispatcher's contract — previously flush only selected `id, payload_json, flush_attempts`, so `_real_dispatcher` in watch.py got `event_type=""` and silently failed all digest dispatches); (c) `_do_dispatch` adds `_PAYLOAD_CLASS_MAP = {"trade_opened": TradeOpenedPayload, ...}` and reconstructs the dataclass from dict before invoking `notify_*` (which uses attribute access — previously `notify_trade_opened` would crash with `AttributeError: 'dict' object has no attribute 'ticker'` on the json.loads round-trip). Together these close the production bug where `safe_send(event_type, payload=TradeOpenedPayload(...))` during quiet hours would have crashed at flush time. Regression-locked by `test_full_roundtrip_trade_opened_dataclass_enqueue_to_dispatch`, `test_flush_injects_event_type_into_row_payload`, and `test_flush_injects_severity_into_row_payload`. Latent bug surfaced by operator's PR #1071 review (#115).

- T12 fix-up: patched 13 pre-existing tests in `tests/notifications/test_safe_send.py`, `test_safe_send_hooks.py`, and `test_telegram_payload_wiring.py` to patch `_load_config_for_safe_send` and `_now_et_for_safe_send` so policy gate returns `verdict=send`. Tests were written for the pre-T12 direct-dispatch contract; the new policy gate could route `trade_opened`/medium -> `digest` during quiet hours, triggering `TypeError: Object of type TradeOpenedPayload is not JSON serializable` in `DigestQueue.enqueue`. Underlying JSON-serialization gap tracked as #115 (Sprint 5 closeout). Per PR #1071 review (operator, 2026-05-13).

### SP5 Wave D T12 fix-up — Security (2 medium, 3 low) + QA (3 nits) from PR #1071 review

Addresses all 8 actionable findings from the combined Security (REQUEST_CHANGES) and QA (APPROVE with nits) review of T12 base commit `f2ce5f2`.

#### Security Medium 1 fixed — DB connection leak in digest path

`safe_send`'s digest branch now wraps `_get_digest_db_conn()` in a `with` context manager, ensuring the connection is always released after `DigestQueue.enqueue` — even on exception. Previously the connection leaked on every digest enqueue, creating burst-load DoS potential.

#### Security Medium 2 fixed — Sensitive payload exposure in escalated email

`_do_dispatch_escalated` now applies `_redact_token(repr(payload))[:1024]` before writing to the email body. The bare `f"Payload: {payload}"` format (which dumped raw kwargs including potential bot tokens into mail archives) is replaced with a redacted, truncated representation plus a forensic SQL query for audit trail. The exception log line also applies `_redact_token(str(e))`.

#### Security Low 3+QA Nit 2 fixed — force=True audit log + structural dedup

`safe_send`'s force=True path is now a single guard block (force-first) instead of the previous structurally-duplicated pattern (initial decision built on lines 1571–1582, then unconditionally overwritten on 1584–1591). The force-first block emits `logger.info("[NOTIFICATIONS] force_bypass: ...")` for audit visibility. The `config = None` initializer ensures the `config` name is always bound before the verdict-dispatch chain.

#### Security Low 4 fixed — Narrow exception in escalated-email path

`_do_dispatch_escalated`'s email branch now catches `(urllib3.exceptions.HTTPError, requests.exceptions.RequestException, socket.timeout, OSError)` matching `_do_dispatch`'s pattern. The previous bare `except Exception` suppressed `ImportError`, `NameError`, `AttributeError` — exactly the import-time bugs the module docstring says must propagate.

#### Security Low 5 fixed — `_EVENT_MAP` immutability

`_EVENT_MAP` is now `MappingProxyType(_EVENT_MAP_MUTABLE)`. Runtime code cannot mutate the event map. `MappingProxyType` supports `__getitem__` and `__contains__` so all existing lookup sites continue to work. `_KNOWN_EVENT_TYPES = frozenset(_EVENT_MAP)` is unchanged.

#### QA Nit 1 fixed — tick_digest_queue replaces inline NotificationsConfig with validated config

`tick_digest_queue` now calls `_load_config_for_safe_send()` (same path used by `safe_send`) instead of constructing `NotificationsConfig` inline from raw dict fields. This ensures config validation runs through the same `_load_notifications_config` validator and eliminates the maintenance hazard of keeping two parallel construction sites in sync. Function shrank from 62 to 51 lines (now under the 60-line limit; removed from known_violations.json oversized_functions).

#### QA Nit 3 fixed — Dead RuntimeError patch cleaned up

`test_safe_send_handles_dispatch_exception` now only patches `ConnectionError` (the actual network exception being tested). The dead outer `RuntimeError("boom")` patch that was immediately shadowed by the inner ConnectionError patch is removed.

#### Regression-lock tests added

- `test_safe_send_digest_path_closes_connection_after_enqueue` — verifies `__exit__` is called on the digest DB connection. Fails without `with` wrap.
- `test_escalated_email_body_redacts_bot_token_in_payload` — verifies bot token pattern is absent from escalated email body. Fails without `_redact_token`.
- `test_safe_send_propagates_non_network_exceptions` — verifies `RuntimeError` from dispatch code propagates uncaught (non-network exceptions must not be swallowed).

#### Files changed

- **`src/notifications/telegram.py`**: MappingProxyType wrap, _do_dispatch_escalated body redaction + narrow exception, safe_send force-first guard + digest with-wrap + audit log.
- **`src/scheduler/watch.py`**: tick_digest_queue replaced inline NotificationsConfig build with `_load_config_for_safe_send()`.
- **`tests/notifications/test_safe_send_wiring.py`**: 3 new regression-lock tests, dead RuntimeError patch removed.
- **`tests/notifications/test_safe_send_dual_rep_consolidated.py`**: updated isinstance check from `dict` to `Mapping` to accommodate MappingProxyType.
- **`config/known_violations.json`**: telegram.py line count updated (1625→1651), safe_send function line count updated (91→101), watch.py line count updated (2445→2432), tick_digest_queue removed from oversized_functions (now 51 lines, under limit).

### SP5 Wave D T12 — safe_send verdict-dispatch wiring + #110 security fold-in (D3)

Wires `safe_send` to consult T10's `should_dispatch` policy gate on every call; branches on `PolicyDecision.verdict` (send/digest/mute/escalate); replaces T11's stub dispatcher in `tick_digest_queue` with a real `_do_dispatch`-flavor dispatcher; consolidates the dual-representation tension between `_KNOWN_EVENT_TYPES` and the local `event_map` inside `safe_send` into a single `_EVENT_MAP` module-level dict. Also folds in tracker #110 — nested `bypass_severity` check + `routing_overrides.<event_type>.*` key allowlist.

#### Added

- **`src/notifications/telegram.py` — `_EVENT_MAP`**: module-level dict (single source of truth) mapping event_type strings to notify_* functions. `_KNOWN_EVENT_TYPES` is now derived as `frozenset(_EVENT_MAP)` — the two representations can never diverge.
- **`src/notifications/telegram.py` — `_check_nested_bypass_severity`**: recursive walk of the notifications config section; raises `NotificationsConfigError` with the offending key path if `bypass_severity` appears anywhere (including inside `routing_overrides` sub-dicts). Called once in `_load_notifications_config`.
- **`src/notifications/telegram.py` — `_ALLOWED_ROUTING_OVERRIDE_KEYS`**: frozenset `{'telegram', 'email', 'escalation_after_attempts'}`. Used to validate each routing override entry's dict keys; unknown keys raise `NotificationsConfigError` with the exact key and event_type path.
- **`src/notifications/telegram.py` — `_load_config_for_safe_send`, `_now_et_for_safe_send`, `_get_digest_db_conn`, `_resolve_source_tag`**: testability hooks replaceable by `patch()`. Production paths load config from `settings.yaml`, return `datetime.now(ET)`, open `DB_PATH` connection, and return `"safe_send"` respectively.
- **`src/notifications/telegram.py` — `_do_dispatch`**: dispatch helper for SEND verdict. Looks up the notify_fn via the module object (not the frozen dict reference) so test patches on notify_* take effect. Catches network exceptions, logs warning, calls `_record_send_failure`.
- **`src/notifications/telegram.py` — `_do_dispatch_escalated`**: dispatch helper for ESCALATE verdict. Calls telegram channel via `_do_dispatch`, then attempts email via `src.email.notifier.send_email`. Sequential (not parallel) — failure visibility is more important than throughput for escalated alerts. Returns True if any channel succeeds.
- **`src/notifications/telegram.py` — `safe_send` rewrite**: adds `force: bool = False` keyword arg; pops `severity` from kwargs (default `'normal'`); calls `_load_config_for_safe_send` + `_now_et_for_safe_send` to get routing context; delegates verdict-dispatch to `_do_dispatch`/`DigestQueue.enqueue`/log/`_do_dispatch_escalated`. KeyError on unknown event_type raised BEFORE policy gate.
- **`src/notifications/telegram.py` — module-level `should_dispatch` import**: imported from `policy` at module level so tests can patch `src.notifications.telegram.should_dispatch`.
- **`src/scheduler/watch.py` — `tick_digest_queue` dispatcher replacement**: replaces `_stub_dispatcher` with `_real_dispatcher` that calls `_do_dispatch(event_type, kwargs, severity, ["telegram"])` directly (bypasses safe_send → policy re-gating, since rows were policy-gated at enqueue time). Config now read from `self.config` instead of hard-coded defaults.
- **`tests/notifications/test_safe_send_wiring.py`**: 6 tests — send path, digest path, mute path, force bypass, dispatch exception, escalate path.
- **`tests/notifications/test_load_notifications_config_strict.py`**: 4 tests — nested bypass_severity raises, unknown routing override key raises with path, escalation_after_attempts accepted, string-not-dict raises.
- **`tests/notifications/test_safe_send_dual_rep_consolidated.py`**: 2 tests — `_EVENT_MAP` non-empty at import, `_KNOWN_EVENT_TYPES == frozenset(_EVENT_MAP.keys())`.

#### Changed

- **`src/notifications/telegram.py` — `_load_notifications_config`**: extended with `_check_nested_bypass_severity` call + routing_overrides key allowlist validation (type check + unknown key detection). Existing top-level `bypass_severity` check kept for clear error messaging.
- **`config/settings.example.yaml`**: updated `escalation_after_attempts` comment from "T12 D3 will use this" to a live description.
- **`docs/operator-guide.md`**: added safe_send verdict-dispatch matrix, updated Decision 20 note for recursive bypass_severity lockdown, added routing_overrides key allowlist section.
- **`config/known_violations.json`**: updated `src/notifications/telegram.py` line count and `safe_send` / `_load_notifications_config` function line counts to reflect T12 additions.

#### Design choices (DR-02 explicit uncertainty resolution)

- **escalate dispatch sequential vs parallel**: chose sequential. Escalated alerts are high-urgency; knowing which channel failed (vs which succeeded) is more operationally useful than saving 50ms. If telegram succeeds but email fails, the log clearly shows which channel needs investigation.
- **safe_send `severity` kwarg vs positional**: kept as a kwarg (`severity="high"`) to avoid changing all existing call sites. Call sites that don't pass `severity` default to `'normal'`.
- **_do_dispatch re-resolution via `sys.modules[__name__]`**: necessary because `_EVENT_MAP` stores function references frozen at import time; patching `notify_scan_complete` at the test level doesn't update the frozen reference. Re-resolving by name through the module respects patches. Production overhead is negligible (one dict lookup per dispatch).

### SP5 Wave D T11 — Notification digest queue (D2)

Implements the persistence layer for `PolicyDecision(verdict='digest')` outputs. The watch loop drains the queue every `digest_flush_minutes` minutes (default 60). T11 owns the queue mechanics, schema, and watch.py flush hook; T12 (D3) will wire `safe_send` to enqueue.

#### Added

- **`src/notifications/digest_queue.py`**: `DigestQueue` class with `enqueue`, `flush`, `mark_flush_failed`, `pending_count`, `abandoned_count` methods. `enqueue` validates `event_type` against `_KNOWN_EVENT_TYPES`. `flush` atomically transitions `pending` → `in_progress` → `sent|pending(retry)|abandoned`. `mark_flush_failed` sets `flush_status='abandoned'` with `flush_error` for operator forensic recovery. `FlushResult(successes, failures, abandoned)` returned from flush.
- **`src/schema/registry.py` — `notifications_digest_queue` TableDef**: 10-column table (`id`, `event_type`, `severity`, `payload_json`, `source_tag`, `created_at`, `flushed_at`, `flush_status`, `flush_attempts`, `flush_error`). Indexes on `flush_status` and `created_at`. `sync_to_postgres=True`, `sync_mode='incremental'`.
- **`src/scheduler/watch.py` — `tick_digest_queue`**: periodic flush hook. Cadence controlled by `notifications.digest_flush_minutes` (default 60). Stub dispatcher logs payload (T12 will wire real `safe_send`). Done-flag inside `try` per CLAUDE.md rule. Backoff keyed to `'digest_queue'`. Placed after `tick_drift_detector`, before T14's future tick.
- **`src/notifications/policy.py` — `NotificationsConfig.digest_flush_minutes`**: new field (default 60); consumed by watch.py tick cadence.
- **`src/notifications/telegram.py` — `_load_notifications_config`**: parses `digest_flush_minutes` with bounds `[5, 1440]`; raises `NotificationsConfigError` on out-of-range.
- **`config/settings.example.yaml`**: added `notifications.digest_flush_minutes: 60` with range comment.
- **`docs/operator-guide.md`**: added "Digest queue" subsection under "Notifications routing" with config knob, lifecycle docs, forensic query, and manual recovery SQL.
- **`tests/notifications/test_digest_queue.py`**: 10 tests covering enqueue/flush happy paths + boundary conditions.
- **`tests/notifications/test_digest_queue_atomicity.py`**: 4 tests covering `mark_flush_failed` + flush-then-fail recovery + abandoned-row persistence.

#### T11 Fix-up (Security + QA review responses — applied on top of 69fe912)

- **Security MEDIUM**: `_dispatch_one_row` and `mark_flush_failed` now apply `_redact_token()[:500]` before writing `flush_error`. Prevents Telegram bot token leakage via `/bot<TOKEN>/sendMessage` URLs in HTTP exception strings, which sync to Postgres via `sync_to_postgres=True`. `_redact_token` imported from `src.notifications.telegram` (project convention established 2026-04-24).
- **Security LOW**: `enqueue` now caps `source_tag` at 64 chars (`source_tag[:64]`) before INSERT. Defense-in-depth on tagging metadata.
- **QA nit 1**: `test_flush_then_fail_recovery` assertion tightened from `in ("pending", "abandoned", "sent")` to `== "pending"` with a failing dispatcher. The original accepted 3 of 4 possible states; the new assertion is specific to the crash-recovery-with-retries-remaining path.
- **QA nit 3**: `flush_error` ColumnDef description updated to reflect actual state machine (`abandoned` only, no `failed`) and document the redaction + cap discipline for future authors.
- **Regression-lock**: `test_flush_error_redacts_bot_token_in_exception_string` added to `tests/notifications/test_digest_queue.py`. Fails with "Bot token leaked into flush_error" if `_redact_token` is removed from `_dispatch_one_row`.

### SP5 Recovery — Render Postgres → local Postgres data migration script

Production incident 2026-05-12 ~18:15 ET: NSSM ArcisWatchLoop sent a "startup blocked" Telegram notification and entered a restart loop. Root cause: the prior recovery this session ran `scripts/sqlite_to_pg_migrate.py` with the operator's shell `DATABASE_URL` pointing at the **Render** Postgres URL (pre-cutover carryover), not the post-cutover-canonical local PG at `localhost:5433/halcyon`. 1.46M+ rows were silently copied to Render PG instead of local PG. Local PG stayed empty. The watch loop's `initialize_database()` crashed on `UPDATE shadow_trades` (UndefinedTable) and NSSM auto-restarted into a loop.

Recovery: built a new migration script with a YES-prompt guard, ran it, restarted NSSM cleanly. 2,196,965 rows / 71 tables migrated in 3:43, zero errors. Watch loop now holds lockfile, `[3/6] Schema: OK 71 tables, 0 drift`, 17 startup checks pass.

#### Added

- **`scripts/render_to_local_migrate.py`** (273 LOC): one-shot Render PG → local PG data migration tool. Reads `SOURCE_DATABASE_URL` (Render) and `DATABASE_URL` (local destination); validates both are postgres URLs and distinct; prints redacted URLs + per-side row counts; requires interactive `YES` (exact case) confirmation before any writes (or `--yes` flag for scripted use). Calls `create_all_tables` on destination from the registry, then copies row-by-row in chunks of 1000 via `execute_values` with `INSERT ... ON CONFLICT (pk) DO NOTHING` for PK-based dedup. Advances destination SERIAL/IDENTITY sequences to `MAX(pk)+1` post-bulk so subsequent INSERTs don't collide. Per-table reporting and total summary.

#### Follow-ups filed (post-merge clean-up)

- **#111**: backport the YES-prompt guard to `scripts/sqlite_to_pg_migrate.py` so the misdirection pattern can't recur on the original migration script.
- **#112**: investigate bidirectional row-count drift (some tables have SQLite > Render; those SQLite-only rows are missing from local PG post-recovery). Decide whether to top off from SQLite.
- **#113**: task #88 (Phase-3-revised cutover) was marked complete but writes to Render continued up to 2026-05-08; audit the cutover to identify the leak path that the cutover should have closed.
- **#114**: content-level dedup pass for different-PK same-content duplicates from pre-cutover dual-writes era (e.g., `options_chains` 1.5M rows on Render vs 755K on SQLite may include autoincrement-divergent duplicates).

### SP5 Wave D T10 — Notification routing policy gate (D1)

Implements the pure-function notification routing gate `should_dispatch(event_type, severity, now_et, config) -> PolicyDecision`. Decides whether a notification should be sent immediately, digested for batch delivery, or muted. First task of Wave D; T11 (D2) will implement the digest queue; T12 (D3) will wire safe_send to consult this policy.

#### Added

- **`src/notifications/policy.py`**: `should_dispatch` pure-function gate + `PolicyDecision` dataclass + `NotificationsConfig` dataclass. No I/O, no logging, `now_et` is injected. Decision rules (first match wins): (1) severity high/critical → SEND always [Decision 20 bypass]; (2) event_type in mute_event_types → MUTE; (3) now_et in quiet-hours window → DIGEST or MUTE; (4) severity=low + digest_low=True → DIGEST; (5) default routing → SEND.
- **`src/notifications/errors.py`**: `NotificationsError` base + `NotificationsConfigError` subclass; mirrors T3's `src/council/errors.py` and T4's `src/monitoring/errors.py` hierarchy.
- **`src/notifications/telegram.py` — `_KNOWN_EVENT_TYPES`**: module-level frozenset of all valid event_type strings for config validation.
- **`src/notifications/telegram.py` — `_load_notifications_config(yaml_path)`**: validates the `notifications:` YAML section and returns a `NotificationsConfig`. Raises `NotificationsConfigError` on: `bypass_severity` key present (Decision 20 lockdown), unknown event_type in routing_overrides/cadence, invalid HH:MM time strings, cadence out-of-range [1, 1440], retry.attempts out-of-range [1, 10], backoff_seconds length mismatch.
- **`src/main.py`**: calls `_load_notifications_config` at startup to fail-fast before the watch loop starts.
- **`config/settings.example.yaml`**: added `notifications:` section per spec §4.7.
- **`docs/operator-guide.md`**: added "Notifications routing" section documenting Decision 20, quiet hours, mute list, digest, channel routing, cadence, and retry knobs.
- **`tests/notifications/test_policy.py`**: 23 tests covering 14 truth-table cases + 7 validation rejection cases + 2 happy-path cases.
- **`tests/notifications/test_policy_purity.py`**: 2 AST guardrail tests — fails if policy.py imports I/O modules or makes logging calls.
- **`tests/notifications/test_event_map_load_order.py`**: 1 MIN7 integration test validating event_map is populated at module-import-time before the validator runs.

### SP5 Wave C — SQL-function DEFAULT rendering fix (Wave C schema fix-up)

Fixes a bug in `src/schema/postgres.py` and `src/schema/sqlite.py` where SQL function call defaults such as `CURRENT_TIMESTAMP`, `NOW()`, and `CURRENT_DATE` were emitted quoted (`DEFAULT 'CURRENT_TIMESTAMP'`). Postgres surfaces this as `psycopg2.errors.InvalidDatetimeFormat` at INSERT time; SQLite silently stores the literal string. The bug affected `platform_events.created_at` (the single in-registry usage of a SQL function default).

#### Fixed

- **`src/schema/postgres.py` — `_format_default` helper + 2 call sites**: SQL function call defaults (CURRENT_TIMESTAMP, CURRENT_DATE, CURRENT_TIME, LOCALTIMESTAMP, LOCALTIME, NOW(), NOW) are now emitted unquoted. String literals remain quoted. Non-string defaults (integers) are emitted as-is. Applied at both the CREATE TABLE column-def site (line ~87) and the ALTER TABLE ADD COLUMN site (line ~127).
- **`src/schema/sqlite.py` — `_format_default` helper + 2 call sites**: Same fix applied at the `_render_column` CREATE TABLE site and the `ensure_columns` ALTER TABLE site.

#### Added

- **`tests/schema/test_default_value_rendering.py`**: 6 regression tests covering Postgres and SQLite CREATE TABLE and ALTER TABLE paths for both SQL-function defaults (unquoted) and string literal defaults (quoted).

### SP5 Wave C T4 — Manual-intervention drift detector (#45)

Detects when the operator closes a paper position in the Alpaca dashboard but the local `shadow_trades` row still says active. Emits a Telegram notification (severity=high) and writes a forensic-trail row to `platform_events`. Runs every 30 minutes via a new `tick_drift_detector` method in the watch loop.

#### Added

- **`src/monitoring/manual_intervention_drift.py`**: `detect_drift(broker_positions, db_positions, threshold_minutes, *, state_path, conn)` — returns `list[DriftFinding]`. Detector does NOT call `safe_send` (recursion guard enforced by AST test). Writes `platform_events` rows with `event_type='drift_detected'`, `severity='high'`, `source='drift_detector'`.
- **`src/monitoring/errors.py`**: `MonitoringError` base + `MonitoringDataError` for broker/DB read failures; mirrors T3's `src/council/errors.py` hierarchy.
- **`src/notifications/telegram.py` — `notify_manual_intervention_drift`**: formats drift alert message. Registered in `event_map` at module-import-time so Wave D policy.py validator can discover it.
- **`src/scheduler/watch.py` — `tick_drift_detector`**: 30-minute cadence tick. Calls `detect_drift`, emits via `safe_send` for each finding. Done-flag inside try block per CLAUDE.md rule. Backoff keyed to `"drift_detector"` per-task.
- **`data/drift_detector_state.json`** (runtime): atomic-write state file tracking `first_seen_iso`, `last_alerted_iso`, `expected_state`, `actual_state` per ticker. 24h dedup window. T12 precursor (Decision 21).
- **`docs/operator-guide.md` — "Drift detection" section**: explains threshold, dedup, state file, silence procedure, forensic-trail query.
- **`tests/monitoring/test_manual_intervention_drift.py`**: 6 tests covering divergence detection, 29/31-min threshold boundaries, state persistence + 24h dedup, broker outage guard, `platform_events` row insert.
- **`tests/monitoring/test_drift_detector_no_recursion.py`**: AST guardrail — fails if `detect_drift` or `_handle`/`_emit` functions call `safe_send`.

#### T4 fix-up — Security REQUEST_CHANGES (commit after 727a42a)

- **`src/notifications/telegram.py` — `notify_manual_intervention_drift`**: applied `_html_escape()` to `ticker`, `expected_state`, `actual_state`, and `severity` fields before HTML interpolation. Fixes Medium security finding: without escaping, a malformed broker response containing `<`/`>`/`&` in a state string would cause Telegram's HTML parser to 400 the message, silently dropping the drift alert. Consistent with the module-wide `_html_escape` discipline enforced across ~30 other `notify_*` functions.
- **`src/monitoring/manual_intervention_drift.py` — `_atomic_write_json`**: changed temp filename from `path.with_suffix('.tmp')` (fixed) to `path.with_suffix(f'.tmp.{os.getpid()}')` (pid-suffixed). Defense-in-depth: prevents tmp-file collision if a secondary process writes state concurrently outside the `data/watch.lock` singleton (Low security finding).
- **`tests/notifications/test_telegram_send_path.py` — `test_notify_manual_intervention_drift_html_escapes_user_fields`**: regression-lock test. Passes `<script>` and `&` in payload fields; asserts `&lt;` and `&amp;` appear in the formatted message. Fails loudly if `_html_escape` is removed.

### SP5 Wave C T2 fix-up — revert platform_events to spec §3.1c (QA REQUEST_CHANGES)

QA reviewer flagged two spec deviations and one misleading test docstring introduced in the T2 base commit. All three reverted to spec-literal.

#### Changed

- **`src/schema/registry.py` — `platform_events.created_at`**: type reverted from `TEXT` to `TIMESTAMP` per spec §3.1c (design.md line 204). SQLite stores TIMESTAMP as TEXT internally; Postgres gets the proper TIMESTAMP type via render_migrate.py. The dev's `TEXT` choice was an undisclosed deviation.
- **`src/schema/registry.py` — `platform_events` indexes**: reverted from dev's composite `idx_platform_events_type_created (event_type, created_at)` + `idx_platform_events_severity` to spec-literal `idx_platform_events_created_at ([created_at])` + `idx_platform_events_event_type ([event_type])` per spec §3.1c (design.md lines 206-209). Severity index removed — not in spec.
- **`tests/test_schema.py` — `test_shadow_trades_strategy_id_fk_db_enforcement` docstring**: corrected misleading claim that FK is "verified at COMMIT time via PRAGMA defer_foreign_keys=ON". The test never sets that pragma; IntegrityError fires at INSERT. Docstring now accurately describes INSERT-time immediate enforcement and references #107 (deferred-semantics gap tracked against src/schema/sqlite.py).

#### Added

- **`tests/test_schema.py` — `test_platform_events_created_at_is_timestamp`**: asserts `created_at` type is `TIMESTAMP` per spec §3.1c.
- **`tests/test_schema.py` — `test_platform_events_has_proper_indexes`**: asserts spec-aligned index names (`idx_platform_events_created_at`, `idx_platform_events_event_type`) and absence of non-spec indexes.

### SP5 Wave C T2 — strategy_id FK + platform_events TableDef (closes #56, #96)

Adds `shadow_trades.strategy_id` forward-compat FK column for methodology gate filtering, and declares the `platform_events` table as a forensic-trail write target for Wave C/D monitoring modules.

#### Added

- **`src/schema/registry.py` — `shadow_trades.strategy_id`**: `TEXT nullable=True` column + `ForeignKeyDef('strategy_id', 'strategy_registry', 'strategy_id', initially_deferred=True)`. Legacy trades remain NULL; forward-compat for C7a.4 filter. PostgreSQL migration uses `NOT VALID` (Decision 24 — no AccessExclusiveLock; operator runs `VALIDATE CONSTRAINT` off-hours).
- **`src/schema/registry.py` — `platform_events` TableDef**: new table with `id` (INTEGER autoincrement PK), `event_type` (TEXT not null), `severity` (TEXT not null), `payload_json` (TEXT nullable), `source` (TEXT not null), `created_at` (TIMESTAMP default CURRENT_TIMESTAMP). Indexes: `idx_platform_events_created_at ([created_at])` + `idx_platform_events_event_type ([event_type])`. Write-sites are C4 drift detector + D5 alert_silence; this task declares only.
- **`src/schema/registry.py` — `ForeignKeyDef.initially_deferred`**: new boolean field (default False) on `ForeignKeyDef` dataclass. Consumed by `generate_fk_constraint_sql` to emit `NOT VALID` constraints in render_migrate.
- **`src/schema/postgres.py` — `generate_fk_constraint_sql`**: generates `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ... NOT VALID;` per Decision 24.
- **`scripts/render_migrate.py` — `--dry-run` flag**: prints FK constraint SQL without connecting to Postgres; also shows `NOT VALID` constraints on live runs with operator VALIDATE reminder.

#### Changed

- **`src/api/cloud_routes/kpis_compute.py` — `_fetch_closed_trades`**: adds optional `strategy_id: str | None = None` parameter. When not None, filters rows by `strategy_id`. Default None preserves existing behavior.

#### Tests

- 6 new tests in `tests/test_schema.py`: `test_shadow_trades_strategy_id_column_present`, `test_platform_events_table_present_with_all_columns`, `test_shadow_trades_strategy_id_fk_db_enforcement`, `test_fetch_closed_trades_filters_by_strategy_id`, `test_fetch_closed_trades_strategy_id_none_returns_all`, `test_render_migrate_fk_emits_not_valid`.

#### Migration note

`VALIDATE CONSTRAINT shadow_trades_strategy_id_fkey` is operator-run off-hours (deferred per Decision 24). The `NOT VALID` constraint is active for new inserts immediately post-migration.

### SP5 Wave C #54 — Wire dates+directions to promotion_gate KPI

Fixes the silent MC-permutation abstention in the /api/kpis promotion_gate
response. Previously `get_kpis()` called `_compute_promotion_gate_kpi(n_trades,
returns)` without dates or directions, causing `_run_mc_perm` to abstain with
`reason='mc_permutation_requires_real_directions'` on every request.

#### Changed

- **`src/api/cloud_routes/kpis.py` — `get_kpis()`**: extracts `dates` (from
  `actual_entry_time` via `_parse_iso_date`) and `directions` (from `direction`
  field, mapped `"long"→1`, anything-else→-1) from the instrumented trades list
  and passes them as kwargs to `_compute_promotion_gate_kpi`. No signature
  changes to `kpis_compute.py` or `promotion_gate.py`.

#### Changed (performance fix-up)

- **`src/data_ingestion/risk_free_rate.py` — `_fetch_dtb3_observations()`**:
  FRED HTTP timeout reduced from 15 s to 5 s. With T1's dates+directions
  wire-up the rf-rate path now activates per `/api/kpis` request. A 15 s
  blocking call on a dashboard endpoint is unacceptable; the graceful fallback
  to `RF_PERIOD_CONSTANT` in `src/methods/_rf_vector.py:90-98` makes a shorter
  timeout safe.

#### Added

- **`tests/api/test_kpis.py` — `TestPromotionGateDatesDirectionsWired`**
  (3 tests): verifies dates and directions are forwarded as kwargs with correct
  length and type (int 1/-1), and that `_run_mc_perm` does not abstain when
  directions is non-None.
- **`tests/test_risk_free_rate_timeout.py`** (1 test): asserts
  `_fetch_dtb3_observations` passes `timeout=5` to `requests.get` — regression
  lock against future timeout creep.

### SP5 Wave C — Council typed exception hierarchy + agent_data.py refactor (#68)

Replaces 28 bare `except Exception` blocks in `src/council/agent_data.py` with typed catches, surfacing previously-swallowed SQLite errors.

**NOTE: Canary deploy required** — this may surface previously-swallowed code-level bugs (KeyError/TypeError); infrastructure errors (sqlite3) still gracefully degrade per Performance review T3 fix-up; canary deploy via watch-loop restart with eyes-on for 1h.

#### Added

- **`src/council/errors.py`** — typed hierarchy: `CouncilError(Exception)` base; `CouncilParseError`, `CouncilTimeoutError`, `CouncilAgentDataError`, `CouncilProviderError` subclasses. `CouncilUnavailableError` gains `CouncilError` as second base (back-compat: still `RuntimeError`).
- **`tests/council/test_typed_errors.py`** (15 tests): 5 instantiation tests, 7 hierarchy/IS-A tests, 1 AST-based enforcement test asserting zero bare `except Exception` remain in `agent_data.py`, +2 outer-guard resilience tests (T3 fix-up).
- **`_council_agent_data_failures`** module-level `collections.defaultdict(int)` counter in `agent_data.py` — keyed by function name; incremented on every outer-guard catch; readable by schedule_health metric path for operator's daily digest.

#### Changed

- **`src/council/agent_data.py`** — all 28 bare `except Exception` blocks converted to `except sqlite3.Error` (DB query sites) or `except (CouncilAgentDataError, ImportError, AttributeError, sqlite3.Error)` (compute_hshs site). Outer function guards broadened from `except CouncilAgentDataError` to `except (CouncilAgentDataError, sqlite3.Error)` — restores infrastructure-error degradation path (DB-lock returns fallback string instead of propagating to abort the 5-agent council session). Each outer guard now emits `logger.warning("[COUNCIL] <fn> caught <type>: <msg> — degrading to fallback")` and increments the failure counter. Code bugs (KeyError/TypeError/AttributeError) still propagate. Public function signatures unchanged.

### SP5 Wave A+B strategic fix — wrap `PostgresConnectionWrapper.execute()` cursor (closes #98)

Root-cause fix for the M4/2026-05-10 KeyError:0 bug class that drove the T1ext 82-site defensive-dispatch sweep and the subsequent `_scalar(row)` helper (PR #1059). `PostgresConnectionWrapper.execute()` previously returned a raw psycopg2 cursor whose `fetchone()` produced raw dicts — incompatible with `row[0]` access. `cursor().execute()` already wrapped via `_RowFactoryCursor` (CompatRow output). This PR closes that asymmetry by wrapping the inner cursor identically in `execute()` and `executemany()`.

Effect on existing call sites: the 82 `_scalar(row)` sites consolidated in PR #1059 continue to work unchanged (CompatRow supports `row[0]`, which is what the helper falls back to for non-dict shapes). The helper's `isinstance(row, dict)` branch is now unreachable in practice but remains as forward-compat protection if a future caller routes around the wrapper.

#### Changed

- **`src/utils/db.py` — `PostgresConnectionWrapper.execute()` + `executemany()`**: return value wrapped in `_RowFactoryCursor` (uniform with `cursor()`). Pre-existing `__getattr__` passthrough on `_RowFactoryCursor` preserves access to `.rowcount`, `.description`, etc., so caller surface is unchanged.

#### Added

- **`tests/test_pg_wrapper_execute_returns_compatrow.py`** (5 tests): regression-lock that asserts `wrapper.execute(sql)` and `wrapper.executemany(sql, params)` return `_RowFactoryCursor`, that `fetchone()` returns `CompatRow` (with both `row[0]` and `row['col']` working), that `fetchall()` returns list of CompatRow, and that pass-through attributes like `.rowcount` still work.

#### Follow-ups (post-merge cleanup, scoped separately)

- Mechanically remove the 82 `_scalar(row)` call sites added in PR #1059 — replace with direct `row[0]` access. Helper can then be deprecated. Tracked as next-tier follow-up.

### SP5 Wave A+B post-merge — `_scalar(row)` helper + 82-site dispatch consolidation

Operator review observation on PR #1058 surfaced T1ext idiom drift: 81 sites used a defensive cross-engine scalar-fetch dispatch pattern, but 1 site at `watch.py:1182` drifted to a brittle literal-key idiom (`row['count']`) that only works because psycopg2 auto-aliases `COUNT(*)` → `'count'`. Any SQL change to a different aggregate (MIN, AVG, subquery) would break it silently. This PR consolidates all 82 sites onto a single `_scalar(row)` helper.

#### Added

- **`_scalar(row)` helper at `src/utils/db.py`**: single function handles all four row shapes flowing out of `fetchone()` under the cross-engine wrapper architecture — `None`, `sqlite3.Row`, `CompatRow` (PG via `.cursor().execute()`), and raw `dict` (PG via `.execute()` — see follow-up #98). Replaces inline `row[0] if not isinstance(row, dict) else ...` dispatch at every call site.
- **`tests/test_scalar_helper_discipline.py`** (5 tests): AST-based structural guardrail that forbids future drift back to the inline dispatch idiom. Narrow matcher distinguishes scalar-fetch dispatch (`X[0] if not isinstance(X, dict) else list(X.values())[0]` or `X['key']`) from legitimate defensive `.get()` patterns. Joins `test_no_fetchone_int_index_in_pg_unsafe_files.py` (T1ext) and `test_no_sqlite_isms_in_pg_safe_files.py` (M4) as the third AST-based cross-engine guardrail.

#### Changed

- **82 dispatch sites consolidated onto `_scalar(...)`** across 14 files. Per-file count:
  - `src/scheduler/reports.py` (23 sites)
  - `src/evaluation/build_score.py` (16)
  - `src/evaluation/hshs_live.py` (15)
  - `src/scheduler/watch.py` (7 — includes the brittle Idiom B at line 1182)
  - `src/attribution/logger.py` (5)
  - `src/shadow_trading/executor.py` (4)
  - `src/scheduler/overnight.py` (3)
  - `src/notifications/telegram_commands.py` (2)
  - `src/services/system_service.py` (2)
  - `src/api/cloud_routes/broker_exceptions.py` (1 — Idiom C variant)
  - `src/config/overrides.py` (1)
  - `src/evaluation/system_validator.py` (1)
  - `src/features/traffic_light.py` (1)
  - `src/scheduler/premarket.py` (1)

#### Follow-ups filed (deeper hardening, NOT silently expanded into scope)

- **Task #98**: Wrap `PostgresConnectionWrapper.execute()`'s cursor in `_RowFactoryCursor` (`db.py:402-409`). Root cause of why the 82-site dispatch was needed — `wrapper.execute()` returns a raw psycopg2 cursor while `wrapper.cursor().execute()` returns the wrapped variant. Fixing this would make the dispatch entirely unnecessary at all 82 sites. Tactical fix in this PR (the helper) + strategic fix in #98 is the right sequence — lower-risk path that doesn't conflate concerns.

### SP5 Wave A+B T3 — known_violations.json render_sync.py stale entries

#### Fixed

- **SP5 Wave A+B T3 — render_sync.py known_violations.json cleanup** (`config/known_violations.json`): confirmed `src/sync/render_sync.py` is absent post-Phase-3-revised (PR #1055) and `config/known_violations.json` contains zero `render_sync` references — stale entries were removed as part of that PR's T7 deletion batch. Closes task #26. (T3, verification-only)

### SP5 Wave B T5 — Extend _html_escape to notify_risk_alert + notify_exposure_alert

#### Security

- **SP5 Wave B T5 — HTML-escape external strings in notify_risk_alert** (`src/notifications/telegram.py:notify_risk_alert`): `alert_type` and `detail` are now wrapped with `_html_escape()` before interpolation into the Telegram HTML-mode payload, preventing display corruption or HTTP 400 on malformed HTML from special chars like `<`, `>`, `&`. (task #65)
- **SP5 Wave B T5 — HTML-escape external strings in notify_exposure_alert** (`src/notifications/telegram.py:notify_exposure_alert`): `sector` (appears twice) and each ticker in the `tickers` list are now wrapped with `_html_escape()`. Same class as above. (task #65)

#### Tests

- **SP5 Wave B T5** (`tests/test_notifications_telegram.py`): 4 new tests covering escape coverage for both functions — special-char inputs produce escaped output, clean inputs round-trip unchanged.

#### Follow-ups filed (sibling-search results — NOT silently expanded into this PR)

Per the `feedback_review_sibling_search` discipline, the sibling-search step surfaced two additional notify_* functions with the same unescaped-HTML-interpolation gap class. These were NOT silently fixed inside T5's scope; they are tracked as durable follow-up tasks for Sprint 5 catch-all (SP6):

- **task #93** — Extend `_html_escape()` to `notify_regime_alert` (src/notifications/telegram.py:781-797): `regime_old`, `regime_new`, `risk_governor_status` interpolated raw.
- **task #94** — Extend `_html_escape()` to `notify_streak_alert` (src/notifications/telegram.py:810-822): ticker symbols + `risk_governor_status` interpolated raw.

### SP5 §J Cutover Rectification — post-2026-05-11 hardening (T1–T8 + T2-fix)

9 rectification items addressing the two P0 failure modes from the 2026-05-11T20:37Z cutover attempt (P0 #89: 59 PG tables disappeared with `log_statement=none`; P0 #90: NVDA shadow_trade bypassed the gate). Goal: the next cutover attempt has comprehensive instrumentation + hardened guardrails so failures either can't recur or leave a precise forensic trail. Spec: `docs/audits/2026-05-11-cutover-rectification/spec.md`.

#### Added

- **SP5 §J Cutover Rectification — schema drift audit** (`scripts/audit_schema_drift.py`): per-column NULL constraint detector comparing registry / SQLite / PG. Surfaced and reconciled `setup_signals.setup_type` NOT NULL drift that crashed the 2026-05-11 cutover. (T3, `02ce393`)
- **SP5 §J Cutover Rectification — PG roles setup** (`scripts/setup_pg_roles.py`): idempotent setup of `halcyon_app` (INSERT/SELECT/UPDATE/DELETE + USAGE on sequences, no superuser) and `halcyon_readonly` (SELECT only). Uses `psycopg2.sql.Literal` for safe password literal escaping; supports password rotation via interactive `\password`. (T2, `0c124fa`)
- **SP5 §J Cutover Rectification — startup fail-fast gate consistency** (`src/startup_checks.py:check_cutover_gate_consistency`): CRITICAL at process start if `ARCIS_PG_CUTOVER_ENABLED=1` but `DATABASE_URL` non-postgres. Pairs with T5 runtime WARN. (T7, `b068677`)
- **SP5 §J Cutover Rectification — pg_stat_activity capture** (`scripts/capture_pg_activity.ps1`): operator runbook tool for mid-smoke connection forensics. Loops every 30s during cutover smoke. (T8, `79f84ab`)
- **SP5 §J Cutover Rectification — wrapper-function discipline test** (`tests/test_connect_db_discipline.py::test_wrapper_functions_use_connect_db`): AST-scans `insert_*`/`log_*`/`record_*`/`save_*` functions in `src/`, asserts each uses `connect_db()`. Closes the structural gap that allowed the 2026-05-11 NVDA shadow_trade leak. (T6, `6a8cba5`)

#### Changed

- **SP5 §J Cutover Rectification — PG log_statement=all** (`docker-compose.yml`): halcyon-pg now runs with `-c log_statement=all -c log_line_prefix='%t [%p] %u@%d '` for DDL forensic trail. Foundation for diagnosing the next cutover attempt. (T1, `3c4f76d`)
- **SP5 §J Cutover Rectification — setup_signals.setup_type nullable** (`src/schema/registry.py`): changed from `nullable=False` to default-nullable to match SQLite reality + caller behavior (`setup_classifier.classify_setup` returns None when no rule matches). (T3, `02ce393`)

#### Fixed

- **SP5 §J Cutover Rectification — sequence advance after bulk INSERT** (`scripts/sqlite_to_pg_migrate.py:_advance_sequence_after_bulk`): post-migration `setval(<seq>, COALESCE(MAX(<pk>), 0) + 1, false)` for serial PKs, silently skipped for UUID/composite PKs. Closes the activity_log pkey=3 conflict that crashed the watch loop during the 2026-05-11 cutover. (T4, `dd1116e`)
- **SP5 §J Cutover Rectification — symmetric forensic WARN** (`src/utils/db.py:_warn_gate_on_no_pg_url_once`): one-time WARN at runtime when `ARCIS_PG_CUTOVER_ENABLED=1` but `DATABASE_URL` non-postgres. Sibling to existing SP-ONEDB-009 WARN; closes the silent-fallthrough class. (T5, `efcd232`)

#### Security

- **SP5 §J Cutover Rectification — CREATE ROLE SQL injection fix** (`scripts/setup_pg_roles.py`): password env vars now use `psycopg2.sql.Literal` instead of f-string interpolation into `CREATE ROLE ... PASSWORD '...'`. Closes the SQL injection vector identified by Security Reviewer (HIGH severity). Named `$halcyon$` dollar-quote tag adds defense-in-depth. Also added `ALTER DEFAULT PRIVILEGES ... GRANT USAGE ON SEQUENCES TO halcyon_app` for future SERIAL columns. (T2-fix, `0c124fa`)

#### Documentation

- **SP5 §J Cutover Rectification — operator-guide cutover-runbook updates** (`docs/operator-guide.md`): added Step 0.5 (pgAdmin isolation pre-flight check), Step 7.5 (mid-smoke pg_stat_activity capture), new "PG application roles (post-merge one-time setup)" section, and "Rotating role passwords" subsection. (T2 + T8)
- **SP5 §J Cutover Rectification — schema drift audit report** (`docs/audits/2026-05-11-cutover-rectification/drift-audit-results.md`): documents the NOT NULL drift findings + sibling-search of all 30+ setup_type callers in src/. (T3)
- **SP5 §J Cutover Rectification — spec** (`docs/audits/2026-05-11-cutover-rectification/spec.md`): 9-task rectification spec from the 2026-05-11 cutover failure. (Deliverable 0, `4b913cd`)

### SP5 §J5/§J6 Phase 3-revised — One-database cutover correction

Closes the PR #1054 cutover gap (which routed only ~5 of 336 call sites to PG). With this PR + the operator-led re-cutover runbook (see `docs/operator-guide.md` §"Postgres Cutover (SP5 §J5/§J6 Phase 3-revised — one-DB)"), `ARCIS_PG_CUTOVER_ENABLED=1` routes EVERY `connect_db()` call to Postgres regardless of how `db_path` was passed — closing the one-database invariant. Full design at `docs/audits/2026-05-11-modified-a-migration/spec-revised-one-db.md`.

**Code changes (T1-T6):**
- **`src/utils/db.py`** — `connect_db()` precedence rule inverted: gate ON + DATABASE_URL postgres now wins for ALL call sites, including explicit `db_path`. Adds `_warn_db_path_ignored_once` helper that emits a one-time WARN per distinct `db_path` override (SP-ONEDB-009). `connect_db_with_pg_retry()` mirrors the inversion. `_REPLACE_SEMANTICS` gets `'operator_view_state': 'in_place_update'`.
- **`src/schema/registry.py`** — 8 tables flipped to `sync_to_postgres=True` (daily_ib_health, model_evaluations, preference_pairs, config_overrides, bracket_health, data_freshness, system_metrics, operator_view_state). `sync_state` TableDef removed entirely (deprecated alongside render_sync.py). Total tables now 71 (was 72).
- **Writers converted to `engine_aware_upsert`:**
  - `src/training/ab_evaluation.py` (model_evaluations writer)
  - `src/training/dpo_pipeline.py` (preference_pairs writer)
  - `src/commands/executor.py` (command_results writer)
  - `src/config/overrides.py` (config_overrides writer)
  - `src/shadow_trading/bracket_monitor.py` (bracket_health writer)
  - `src/api/cloud_routes/system_index.py` (operator_view_state writers ×2)

**Deletions (T7):**
- `src/sync/render_sync.py` — deprecated; relied on `sync_state` table (removed)
- `src/sync/reconcile.py` — deprecated; no callers post-cutover
- `src/cli/commands.py:cmd_reset_live_prices_watermark` + `src/cli/main.py` subcommand registration
- `tests/test_render_sync*.py` files
- `config/known_violations.json` entries referencing the deleted files

**Tests added (~25 net new):**
- 12 truth-table tests in `tests/test_db_util.py` (8 rows × extras for warn-once + retry-parity)
- 2 schema regression locks in `tests/test_schema.py` (8-flip assertion + sync_state-absence)
- 6 cross-engine writer tests across `tests/test_writers_*.py` (one per writer)
- 3 deletion-regression-locks in `tests/test_render_sync_removed.py`

**Operator next steps:** see `docs/operator-guide.md` §"Postgres Cutover (SP5 §J5/§J6 Phase 3-revised — one-DB)" for the 8-step re-cutover runbook. Includes the SQLite-shows-zero-recent-writes assertion that would have caught PR #1054 in 30 seconds.

**Out of scope (cleanup backlog):**
- `cloud_routes/` manual `if database_url:` branches are now redundant under one-DB but each has independent quirks — cleanup is post-merge backlog (SP-ONEDB-011).
- The autouse `_REPLACE_SEMANTICS` monkeypatch fixtures in `tests/test_writers_operator_view_state.py` and `tests/api/conftest.py` become no-ops post-merge (T1+T6 together cover the entry); deletion is post-merge backlog.

### Sprint S1-CC Batch B — Walk-Forward Framework Scoping (3 docs-only tasks)

Closes the second half of Sprint S1-CC. Stage 1 corpus admissibility passed (Batch A landed via PR #1051); this batch lands the v1 spec + v1 plan for the walk-forward validation framework that gates Stage 2 OOS dispatch and v2 training. **Docs-only.** No src/, tests/, or config/ changes.

- **`docs/audits/2026-05-11-stage1-completion/walkforward-prior-art.md`** (NEW, 419 lines) — B1 prior-art review. Inventories WIRED vs SHELF across `src/methods/promotion_gate._decide`, `src/platform/promotion._evaluate_walkforward_gate`, `src/evaluation/walkforward.py` (Stage-1 anchored harness), and `src/platform/rigor/walkforward_*` (R1-R8 state-machine + `walkforward_results` persistence). Documents the composition pattern (walk-forward AND-composes with the 4-of-5 methodology voter at the orchestrator level, NOT as a 6th vote) and surfaces 12 open methodological questions (D1-D12) the spec must resolve.
- **`docs/audits/2026-05-11-stage1-completion/walkforward-spec-v1.md`** (NEW, 264 lines) — B2 v1 spec. Per operator-convention section flow (Revision History → Overview → Architecture → Data Model → API & Module Surface → Error Handling → Testing Strategy → Operational Notes → File Inventory → Known Considerations → Design Decisions Table → Do-Not-Do → Falsifiability Triggers). **12 design decisions captured** (SP-WF-001 through SP-WF-012). Key resolutions:
  - **SP-WF-008 (composition)** = Choice B — walk-forward stays AND-composed at `src/platform/promotion.py:_evaluate_backtested_to_shadow`, NOT a 6th vote into `_decide`. Preserves independent falsifiability of methodology voter vs regime-stability gate.
  - **SP-WF-009 (sentinel default)** = Choice A — `WALKFORWARD_GATE_ENABLED=true` by default. The gate is already wired and blocking in production (R1-R8 v1); `false` default would silently regress an enforced gate.
- **`docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md`** (NEW, 325 lines) — B3 v1 plan. 12 tasks across 5 batches (parallel-eligible where independent). Sentinel: matches spec SP-WF-009 (default `true`). Schema additions: D7 Choice A (reuse existing `walkforward_results` table + add `gate_version TEXT DEFAULT 'v1'` column for forward-compat reads; new `excess_sharpe_min_used REAL` column for self-describing rows). Total estimated LOC budget: ~235 net new src/ + ~395 new test lines. T7 is procedure-only (`validate-schema --fix` + `render_migrate.py`).

**Cross-doc alignment verified:** B2 and B3 were drafted by parallel agents (worktree-isolated) and independently converged on the AND-composition pattern + sentinel `true` default. Independent convergence is a positive signal that the resolutions are grounded in the existing codebase, not artifact of any single agent's reasoning.

**Out of scope:** v2 training dispatch (still gated on walk-forward shipping + Stage 2 closure). Strategy specs (#511 Connors RSI(2) etc.) remain separate. No src/ or test changes in this batch — the impl sprint dispatches from the plan after operator review.

### SP5 §J5/§J6 Phase 3 T3.2 — connect_db precedence-flip gated behind ARCIS_PG_CUTOVER_ENABLED

The Phase 3 cutover gate. `src/utils/db.py:connect_db()` and `connect_db_with_pg_retry()` now route to Postgres ONLY when BOTH `DATABASE_URL` starts with `postgres` AND `ARCIS_PG_CUTOVER_ENABLED=1`. Without the gate, behavior on every machine with a stale `DATABASE_URL` env var is unchanged (SQLite path). Production cutover (Phase 3 T3.3) requires the operator to set BOTH env vars on the NSSM service via `nssm set ArcisWatchLoop AppEnvironmentExtra` (APPEND syntax). Rollback is a single env unset: `ARCIS_PG_CUTOVER_ENABLED=` → instant SQLite revert. Gate removed in Phase 4 T4.4 once cutover is stable.

- **`src/utils/db.py`** — `connect_db()` and `connect_db_with_pg_retry()` precedence rule gated. Docstring updated with the M2 mitigation rationale (2026-05-10 cutover attempt failed in 2 min from stale shell DATABASE_URL; gate makes T3.2 merge a no-op on dev boxes).
- **`tests/test_db_util.py`** — 3 new tests: gate-off+PG-url → SQLite, gate-on+PG-url → PG, gate-on+no-PG-url → SQLite. Plus updates to any existing PG-routing tests to set the gate explicitly.
- **`docs/audits/2026-05-11-modified-a-migration/t3.4-smoke-checklist.md`** (NEW, 284 lines) — operator-runnable 30-min smoke checklist for T3.4 post-cutover verification. §0 pre-smoke gates (7 checks including PG schema-mirror + data-migration spot checks); §1 write-path smoke (5 paths: system_metrics, shadow_trades, activity_log, notifications_dedup, scan_metrics — each cross-verified against SQLite max-timestamps to confirm writes are landing in PG); §2 read-path smoke (7 dashboard endpoints incl. the Phase 2.5 ET-tz fixes); §3 C1 LIKE regression coverage (the `executor.py:777` drawdown-alert LIKE site + 2 sibling sites — exercises the wrapper's `_rewrite_question_to_pct` quote-and-percent state machine); §4 log sweep with per-pattern decision matrix (relation/column-missing = CRITICAL, KeyError:0 = HIGH, OperationalError = MEDIUM); §5 explicit PASS/DEGRADED/FAIL criteria with the T3.5 rollback procedure (single env unset). Per CLAUDE.md governance — operator runbook updates ship with the PR that introduces them.

### SP5 §J5/§J6 Phase 2.5 — KNOWN_OFFENDERS date-function cleanup (12 sites, 6 files)

Phase 3 cutover prerequisite. Phase 2 T2.14 (AST-based SQLite-ism discipline scan) shipped with a `KNOWN_OFFENDERS` allowlist containing 12 `datetime('now', ...)` / `date('now', ...)` sites across 6 files — patterns that crash on Postgres because the SQLite negative-offset date literal has no PG equivalent. This phase migrates all 12 sites to Python-side `datetime.now(ET) - timedelta(days=N)` cutoffs bound as `?` parameters (the wrapper rewrites `?` → `%s` for psycopg2 post-cutover). After this phase, `KNOWN_OFFENDERS` is **Phase-3-cutover-ready**: zero remaining date-function offenders block the cutover (only the PRAGMA-guarded `system_validator.py:167` and the 34 dynamic-`?` wrapper-handled sites remain).

- **`src/evaluation/build_score.py`** (4 sites — lines was 151, 163, 408, 432) — `_score_data_asset_value` and `_build_data_detail` 30-day + 90-day cutoffs now `datetime.now(ET) - timedelta(days=N)` matching the production write convention at `src/training/data_collector.py:460`. Side benefit: closes a pre-existing 4-hour UTC/ET skew bug at the cutoff boundary (the old SQLite `datetime('now', ...)` returned UTC against ET-stored timestamps).
- **`src/evaluation/hshs_live.py`** (3 sites — lines was 218, 260, 266) — `_score_data_asset` 7-day freshness + `_score_flywheel_velocity` 7-day/14-day cohort comparison. Cohort comparison reworked to share a single `now_et` anchor across the two queries so the boundary is byte-stable.
- **`src/council/agent_data.py`** (2 sites — lines was 272, 451) — `gather_risk_data` 7-day llm failure-rate fallback + `gather_macro_data` 365-day high-yield average. 365-day site uses `.date().isoformat()` because `collected_date` is stored as YYYY-MM-DD date string (not full ISO timestamp); string-comparison-safe.
- **`src/council/context.py`** (1 site — line was 30) — `build_shared_context` 1-day recent-recommendations rollup. Same `datetime.now(ET) - timedelta(days=1)` pattern.
- **`src/api/routes/system.py`** (1 site — line was 694) — `monitoring_history` hours-parameterized cutoff. **Preserved pre-existing UTC behavior** (matches the SQLite `datetime('now', ? || ' hours')` UTC return); `system_metrics.timestamp` is written in ET so a 4-5h skew exists at the boundary. Statistically irrelevant for typical 24-hour windows but filed as a follow-up.
- **`src/api/routes/ib_status.py`** (1 site — line was 76) — `ib_status` 30-day uptime % cutoff. Uses tz-aware `datetime.datetime.now(ET)` matching the write-side convention at `src/trading/ib_shadow.py:78` (post-review fix per PR #1052 review).
- **`tests/test_build_score_date_now.py`** (NEW, 214 lines) — 4 tests + 2 cross-engine SQLite/PG parity tests
- **`tests/test_hshs_live_date_now.py`** (NEW, 240 lines) — 4 tests
- **`tests/test_agent_data_date_now.py`** (NEW, 383 lines) — 6 tests (risk + macro paths)
- **`tests/test_council_context_date_now.py`** (NEW, 269 lines) — 5 tests
- **`tests/test_api_routes_system_date_now.py`** (NEW, 211 lines) — 4 tests
- **`tests/test_ib_status_uptime_window.py`** (NEW, 192 lines) — 4 tests
- **`tests/test_no_sqlite_isms_in_pg_safe_files.py`** — removed all 12 date-function entries from `KNOWN_OFFENDERS`; added a summary comment block explaining the migration. All 15 AST-scan tests pass against the post-merge integration.

### Sprint S1-CC Batch A — Stage 1 corpus closeout

### Added

- Stage 1 corpus generation complete (67,528 entries, §B2 admissibility PASS, manifest pinned at SHA256 `43c2e3ed...0d93` per `data/corpus/stage1-001/MANIFEST.md`). Cold-read verdict PASS → proceed to walk-forward framework scoping (S1-CC Batch B).

### SP5 §J5/§J6 Phase 0 — Modified-A migration (T0.7)

- **`src/schema/registry.py`** — added `sync_conflict_col="event_type, dedup_key"` to the `notifications_dedup` TableDef. The PK `id` is autoincrement; uniqueness is enforced via the composite index on `(event_type, dedup_key)` at registry.py:2543 — that composite is the natural ON CONFLICT target. Prerequisite for the SP5 §J5 `engine_aware_upsert` migration at `src/notifications/platform_events.py:96` (tracked as T1.7 in Phase 1).
- **`tests/test_schema.py`** — added `test_notifications_dedup_sync_conflict_col_matches_composite_unique` asserting `TABLES['notifications_dedup'].sync_conflict_col == "event_type, dedup_key"`.

### Wave 5.1 — Training-readiness verification script (post-3090 trainer preflight)

- **`scripts/verify_training_readiness.py`** (NEW) — non-destructive, fail-fast diagnostic that proves the post-3090-upgrade trainer (`training_data/train.py`) is ready to run end-to-end. Five sequential checks with `[VERIFY-N]` prefixes and a final `READINESS: PASS|FAIL (X/5)` summary + non-zero exit on fail: (1) CUDA + 3090 detection with ≥20 GB free VRAM gate; (2) trainer dependency import sweep (transformers, peft, trl, bitsandbytes, datasets); (3) Stage 1/2/3 jsonl path + first-5-line JSON validity; (4) trainer dry-run capped at `max_steps=1` with tmpdir cleanup; (5) GGUF export artifact verification (≥1 MB). 329 lines, 9 functions ≤49 lines each.
- **`tests/test_verify_training_readiness.py`** (NEW) — 4 new tests; mock torch.cuda + tmp_path file fixtures. Real-code-path coverage (no tautological mocks).

### Wave 4.1 — `sqlite_to_pg_migrate.py` one-shot data migration script

- **`scripts/sqlite_to_pg_migrate.py`** (NEW) — copies all 63 sync-eligible registry tables from local SQLite to local Docker Postgres. Idempotent via `INSERT … ON CONFLICT DO NOTHING`; CLI flags `--tables`, `--dry-run`, `--vacuum-after`. Streaming SQLite read via `cursor.fetchmany(_CHUNK_SIZE)` keeps peak per-table RAM at ~100 KB regardless of table size. Bulk inserts via `psycopg2.extras.execute_values` (~5–10× faster than `executemany`). Single PG connection reused across the per-table loop with per-table commit/rollback boundaries. Per-table transactions; skips NULL-pk rows (matches sync_thread #243 fix). Dry-run on operator's actual data: 63 tables, 1,323,393 rows total — committed log at `docs/audits/2026-05-10-cloudflare-tunnel-cutover/migration-dry-run.log`.
- **`tests/test_sqlite_to_pg_migrate.py`** (NEW) — 6 tests with mocked psycopg2 (no live PG required): null-pk filtering, chunk boundaries, dry-run no-op, abort on missing/wrong DATABASE_URL, sync-skip filter.

### Wave 4.2 — `SYNC_THREAD_ENABLED` feature flag for `start_render_sync`

- **`src/sync/render_sync.py`** — added an env-var gate at the top of `start_render_sync()`: when `SYNC_THREAD_ENABLED=false` (case-insensitive), log INFO and return None early (matches existing `watch.py:1351-1355` None-handling contract). Default `'true'` preserves existing behavior. Surgical 4-line change placed before any config reads. Risk R5 mitigation per cutover spec §7 — without this flag, watch loop post-Render-decommission would log connection errors continuously when `RenderSyncThread` tries to push to a dead Render PG endpoint.
- **`tests/test_render_sync.py`** — 2 new tests added (existing 70 preserved): `test_start_render_sync_returns_none_when_sync_thread_enabled_false`, `test_start_render_sync_starts_when_sync_thread_enabled_true_or_unset`.

### Wave 3 — Cutover verification + Render decommission docs

- **`docs/audits/2026-05-10-cloudflare-tunnel-cutover/wave-3-smoke-test-checklist.md`** (NEW) — operator-actionable per-page table for browser smoke-testing all 6 pages on `halcyonlab.app` after tunnel cutover.
- **`docs/audits/2026-05-10-cloudflare-tunnel-cutover/wave-3-render-decommission-runbook.md`** (NEW) — pre-deletion checklist, Render-dashboard delete steps, DNS cleanup audit, post-deletion verification curl (with required Chrome User-Agent per `reference_cloudflare_bot_fight` memory), 7-day rollback window, and 2026-05-17 PG retention disposal reminder.
- **`docs/audits/2026-05-10-cloudflare-tunnel-cutover/wave-3-receipt.md`** (NEW) — template for operator-completed evidence (PM-prepped; operator fills + commits).

### Wave 2.1 — Engine-aware `connect_db` shim (dual-engine SQLite/Postgres)

- **`src/utils/db.py`** — `connect_db` refactored from a pure SQLite helper into an engine-aware shim. When called with no `db_path` argument and `DATABASE_URL` starts with `postgres`, returns a `PostgresConnectionWrapper` backed by psycopg2 (`RealDictCursor` for name-based result access). When `DATABASE_URL` is unset / empty (or any explicit `db_path` is passed), returns the existing `sqlite3.Connection` with `busy_timeout=30000` and `row_factory=sqlite3.Row` — default behavior is byte-for-byte identical to pre-change. New `PostgresConnectionWrapper` class exposes `cursor()`, `execute()`, `executemany()`, `commit()`, `rollback()`, `close()`, and `row_factory`. This is the foundational wedge for the Wave 4 watch-loop write-side flip — once `DATABASE_URL` is set in the NSSM service env, all 336 `connect_db` call sites route to PG transparently.
- **`tests/test_db_util.py`** — 4 new tests added; existing 3 tests preserved unchanged. New tests use monkeypatch + mocked psycopg2.connect (no real PG connection required): `test_connect_db_uses_sqlite_when_database_url_unset`, `test_connect_db_uses_postgres_when_database_url_postgres_scheme`, `test_connect_db_explicit_db_path_forces_sqlite`, `test_pg_wrapper_exposes_required_methods`.

### Cutover — Cloudflare Tunnel + Modified-A migration (Wave 1, 2026-05-10)

Infrastructure stand-up for the unified-DB switch. Today's exit state is **transitional Hybrid** (Postgres provisioned with mirrored schema but no live data; SQLite still primary). The data migration + watch-loop write-side flip + SQLite retirement are explicit tail items per `docs/audits/2026-05-10-cloudflare-tunnel-cutover/spec.md` §6.

- **`docker-compose.yml`** (NEW) — Postgres 16-alpine, container `halcyon-pg`, bound to `127.0.0.1:5433`. Port 5433 (not the default 5432) because the operator's machine has a Windows-installed PostgreSQL 18 service on 5432; 5433 sidesteps the conflict and preserves the local PG tool for ad-hoc analytic queries. Volume mounts to `C:/arcis/data/pg-data` (outside the git repo per CLAUDE.md "runtime data lives outside the repo" rule). Healthcheck via `pg_isready`; 2 GB memory cap.
- **`src/api/app.py`** — auth-gated for the post-cutover tunnel exposure. `verify_auth` lifted from `cloud_app.py:153-176` (same hash-or-plaintext bearer-token model the frontend already speaks). Every native router (system, scan, shadow, training, …) now requires bearer auth via `include_router(dependencies=[Depends(verify_auth)])`. 3 new cloud_routes wired in (`notifications`, `platform`, `walkforward`) — these were previously cloud_app-only; bringing them local is required for the tunnel cutover. Existing cloud_routes (kpis, broker_exceptions, preflight) + new ones use the `dependency_overrides` pattern from `cloud_app.py:316-340`. New unauthenticated `/healthz` endpoint for curl smoke tests + external monitoring. WebSocket `/ws/live` still UNAUTH'd as a follow-up (`#1100`). FastAPI title version bumped 0.17.1 → 0.34.0 to match latest release tag.
- **`training_data/train.py`** — switched from Unsloth single-stage trainer to multi-stage curriculum (STRUCTURE → EVIDENCE → DECISION) using HF Transformers + PEFT LoRA + TRL SFTTrainer + bitsandbytes nf4 4-bit quantization. Driven by the 2026-05-10 GPU upgrade (RTX 3060 12 GB → RTX 3090 24 GB) which removes the 12 GB VRAM ceiling that originally rejected Unsloth's standard path. GGUF export retains Unsloth as primary path with llama.cpp CPU conversion as fallback. `.gitignore` updated: `training_data/` → `training_data/*` so allowlist sibling rules can re-include `train.py` and `README.md` (parent-dir exclusion blocks child re-inclusion per gitignore spec).
- **Render PG snapshot** — `pg_dump` ran to `C:/arcis/data/render-pg-snapshot-2026-05-10.sql` (478 MB, 65 CREATE TABLE + 65 COPY blocks). Rollback artifact for the migration.
- **Local SQLite snapshot** — `cp` to `C:/arcis/data/ai_research_desk-2026-05-10-precutover.sqlite3` (507 MB). Rollback artifact for the data-migration phase.
- **Schema mirrored** to Docker PG via `scripts/render_migrate.py` — 63 tables, 862 columns, 70 indexes, 0 columns added (clean migration).
- **Frontend rebuild** — fresh `npm run build` produces `frontend/dist/` with new `VITE_API_SECRET` baked into the bundle. Local FastAPI's `StaticFiles` mount at `app.py:80` serves it at the same origin as `/api/*`, so no CORS in production.
- **NSSM `ArcisDashboard` service** — operator-installed wrapper for `python -m src.main dashboard --port 8000` (the FastAPI uvicorn host). Sibling to the existing `ArcisWatchLoop` service. Stdout/stderr logs at `C:/arcis/logs/dashboard-{stdout,stderr}.log`.
- **Cloudflare Zero Trust public hostname** — operator-configured rule routing `halcyonlab.app → http://localhost:8000` through tunnel `f6f41208-e674-43cf-bb9d-6ca5c4972eb3`.

Audits committed for history: SP3 visual-verify gate evidence (17 PNG before/after pairs from PR #1006), SP5 (terminal sprint) scope inventory (operator-confirmed Hybrid canon disposition).

Wave 2-5 are dispatched via `arcis:code` (coding-team skill) per operator policy on Sprint-1+ feature work.

## [v0.34.0] - 2026-05-08 — Sprint 4 Wave 1+2+3: cockpit followups + notifications observability + post-deploy hotfixes + sprint closeout

### Sprint 4 closeout summary

Sprint 4 delivered 22 of 23 planned tasks (T22 deferred to Sprint 5 as `#SP5-notifications-routing-policy`, tracked as task #69). Test floor: **4,798 tests passing** (baseline was 3,682 pre-Sprint-4; +1,116 net across all waves). Deferred to Sprint 5: `#SP5-notifications-routing-policy` (T22, task #69), `#SP5-notifications-CC6-prefixing`, `#SP5-notifications-dataclass-payloads-tail`, `#SP5-council-errors-consolidation` (task #68). Visual-verify gate: 11 priority pages + 2 new components all PASS post-deploy. WON'T FIX: `#SP4-settings-backend-float32-storage` (frontend clamp applied in T11; backend float32 storage retained).

### Sprint 4 Wave 2 deploy + 6 post-deploy hotfixes

This release cuts after Sprint 4 Wave 1+2+3 deploys to halcyonlab.app and 6 hotfixes shipped during the post-deploy visual-verify gate.

**Hotfixes shipped during the post-deploy gate (most recent first):**

### Hotfix — MR feature dict adds `current_price` key (true root cause of #52)

- **`src/features/mean_reversion.py:compute_mr_features`** now includes `current_price` (alongside the existing `last_close`) in its returned feature dict. Pre-fix, the dict had only `last_close` — but `build_packet_from_features` (`src/packets/template.py:170`) reads `features.get("current_price", 0.0)` as the canonical key. MR features were ALWAYS missing it, so packet builder ALWAYS got `0.0` and refused via #621. Pullback scan worked because `compute_all_features` (engine.py:173) already returns `current_price`. This is the TRUE root cause of the recurring BAC/CVX/DE/AMZN/AVGO MR-scan rejections — yfinance data was clean; the bug was a feature-dict key naming mismatch between the two scan paths. PR #1037 (yfinance trailing-zero sanitizer) and #1036 (None-guard at enhance_packet_with_llm) remain as defense-in-depth but didn't address the actual production symptom. New regression test `tests/test_mr_features_current_price_key.py` (5 tests) covers: MR features include current_price, current_price aliases last_close, end-to-end MR features → build_packet returns non-None packet, pullback features schema already includes current_price (sibling-lock).

### Hotfix — Operator-only kill switch (auto-halt removed)

- **`src/risk/governor.py`** introduces `_HALT_ALLOWED_SOURCES = frozenset({"cli", "dashboard", "api", "test"})` and a new `HaltSourceForbiddenError(ValueError)` exception. `_global_halt(True, source=...)` now raises if the source is not in the allowlist. Resume calls (`halt=False`) remain unrestricted (anyone can clear). This is the architectural lockdown — even if a future bug introduces a new auto-halt code path, the governor refuses it at the boundary.
- **`src/evaluation/auditor.py`** removes the `_global_halt(True, source="auditor", ...)` call in the production-mode CRITICAL branch. Auditor now escalates via `logger.critical` + email alert + appends `{"action": "operator_action_required", "severity": "critical", ...}` instead of `{"action": "halt_trading", ...}`. Email subject is now "[TRADE DESK] CRITICAL AUDIT FLAG — Operator Action Required" with body listing the 3 manual halt paths (CLI/dashboard/API). Bootcamp downgrade for non-`_NEVER_DOWNGRADE` categories still applies — alert text changes, severity tag may downgrade, but no auto-halt under any path.
- **Tests:** `tests/test_kill_switch_source_allowlist.py` (NEW, 17 tests) covers allowed sources, forbidden sources raise `HaltSourceForbiddenError`, resume-is-unrestricted, error message quality. `tests/test_auditor.py` 3 tests flipped from "must halt" to "must alert + no halt": `test_critical_flag_alerts_operator_no_auto_halt`, `test_risk_governor_breach_never_downgraded_in_bootcamp` (severity stays critical, no halt), `test_emergency_halt_bypass_alerts_operator_no_auto_halt`, `test_post_bootcamp_config_prevents_critical_downgrade` (severity preserved, no halt). `tests/test_kill_switch.py` and `tests/test_risk_governor.py` updated to pass `source="cli"` / `source="test"` instead of relying on default `source="unknown"` (now forbidden).
- **Operator policy 2026-05-08:** kill switch is operator-action-only. Triggered by 2 days of an auditor auto-halt over a debatable concentration call (35% / 6 sectors / BK 4.6%) that blocked all trading. Operator chose to remove the auditor's halt power entirely; alerts still flow.

### Hotfix — OHLCV trailing zero/NaN close sanitizer (root cause of #52)

- **`src/data_ingestion/market_data.py:_extract_batch_frames`** now calls a new `_trim_invalid_trailing_close` helper that drops trailing rows where `Close <= 0` or `Close == NaN` from the per-ticker DataFrame before returning it. yfinance batch downloads occasionally append a row with `Close == 0.0` or NaN for tickers whose data fetch partially failed (Open/High/Low/Volume populated, just Close=0/NaN). `df.dropna(how="all")` doesn't catch those rows, so they propagated to `engine.py:_compute_price_features` as `current_price = float(close.iloc[-1]) = 0`, triggering `template.py:177`'s #621 packet refusal — which until the #52 hot-fix crashed `enhance_packet_with_llm` with NoneType AttributeError. Affected tickers in production logs: AMZN+BAC×4 (2026-05-08), AVGO×5 (2026-05-07). Sanitizer logs a per-ticker WARNING with trimmed-row count when triggered. New test file `tests/data_ingestion/test_market_data_close_sanitize.py` (10 tests) covers: trailing zero, trailing NaN, multiple trailing invalid, valid data unchanged, interior zero preserved (only TRAILING is sanitized), all-invalid → empty, missing-Close-column defensive, warning emitted when trimmed, no-warning when clean.

### Hotfix — packet_writer None-guard (closes #52)

- **`src/llm/packet_writer.py:enhance_packet_with_llm`** now short-circuits when called with `packet=None`. `build_packet_from_features` (`src/packets/template.py:177`) legitimately returns None for tickers with `current_price <= 0` (#621 defensive — silent feature-fetch failure for ~14 tickers/day). Two callers — `src/services/mr_scan_service.py` (Mean Reversion scan) and `src/services/scan_service.py` (Pullback scan) — were missing the matching `if packet is None: continue` guard, crashing with `'NoneType' object has no attribute 'llm_conviction_parse_failed'` at packet_writer.py:729 every cycle. Today's `arcis.log` shows 4 fires today, ~30min cadence (332 historical occurrences since 2026-04-30). Watch loop's `_safe_run` caught each with 60s backoff so the loop survived, but **every MR scan attempt was lost**. Belt-and-suspenders fix: (1) `enhance_packet_with_llm` now returns None + logs WARNING when input packet is None, (2) `mr_scan_service.py` + `scan_service.py` add the missing caller-side `if packet is None: continue`. Sibling-search confirmed `universe_scanner.py:175`, `corpus_generator.py:274`, `backtester.py:204` already had the guard. New regression test `tests/llm/test_packet_writer_none_guard.py` (4 tests) locks the entry-guard behavior.

### Sprint 4 Wave 2 hotfix — MetricCard sign-aware prefix formatting (T18 sibling-fix)

- **`frontend/src/components/MetricCard.jsx`** rewrites `{prefix}{value}{suffix}` rendering through a new `_formatValue(prefix, value, suffix)` helper that moves a leading numeric sign before the prefix. Negative dollar amounts now render `-$6.55` (sign before prefix) instead of `$-6.55` (sign after). Visual-verify of the post-Wave-2 deploy on `halcyonlab.app` caught `AVG LOSS $-6.55` in the ShadowLedger Closed-tab summary card — a sibling site that T18's per-row fix didn't cover. Centralizing the fix at the component level closes 9 call sites in one edit (4 in ShadowLedger, 2 in ModelPerformance, 2 in LiveLedger, 1 in Dashboard). Regex guard `/^[-+]\d/` ensures non-numeric leading-dash values like `--` (no-data placeholder) pass through unchanged. New `frontend/src/components/MetricCard.test.jsx` (8 tests) locks: unsigned-value pass-through, negative-sign move, positive-sign move, `--` placeholder pass-through, zero, no-prefix bypass, suffix preservation, comma-separated negative.

### Sprint 4 Wave 1 hotfix — urllib3 + DATABASE_URL test fixture

- **urllib3 added to requirements-cloud.txt** (6th recurrence of cloud-deploy import drift bug class). Sprint 4 T3 added `import urllib3.exceptions` to `src/notifications/telegram.py` for the `safe_send` network-error catch list. T7 fast-lane AST walker correctly flagged this as reachable from `cloud_app` via `cloud_routes/platform.py → notifications/telegram.py` but missing from `requirements-cloud.txt`. urllib3 ships transitively via requests today; declaring explicitly per defensive policy. Walker package count: 53 → 54.
- **DATABASE_URL fixture in `_clean_env()`**: `tests/test_cloud_requirements_imports.py::TestSlowLaneVenvImport` strips env vars for hermeticity but `cloud_app` validates `DATABASE_URL`/`ARCIS_DB_PATH` at import time (`src/config/__init__.py:65`). Subprocess env now sets `DATABASE_URL=postgresql://fake:fake@localhost:5432/fake` so the slow-lane import-graph check works without exposing the underlying RuntimeError before pytest can observe `ModuleNotFoundError` failures (the actual test target). Both flagged by Sprint 4 PR #1020 review.

### Sprint 4 — Cockpit Followups + Notification Subsystem (sprint/cockpit-followups-2026-05-07/base)

<!-- T2  --> Fixed two stacked silent-swallow bugs in CUSUM alarm path: (a) renamed `detect_performance_change` → `check_performance_drift` at `src/scheduler/overnight.py:127-128` (ImportError was caught by outer try/except, never reached the inner Telegram code), (b) renamed `send_telegram_message` → `send_telegram` at `src/scheduler/overnight.py:134/149/304/311` (NameError caught by inner try/except). New regression test `tests/notifications/test_overnight_alarm_paths.py` (6 tests) locks both fixes. Without (a), T2's send_telegram fix would have shipped incomplete because the ImportError fires first.
<!-- T3  --> Added `safe_send(event_type, **kwargs)` central dispatcher to `src/notifications/telegram.py`. Catches ONLY network errors (urllib3.HTTPError, requests.RequestException, socket.timeout, OSError); ImportError/NameError/AttributeError propagate so code-level bugs surface at startup (not silently at runtime). Bot-token redaction applied at BOTH the warning log AND the `_record_send_failure` persistence path (defense-in-depth for T15's notifications_sent table). Re-exported from `src/notifications/__init__.py`. T15 will wire the `_record_send_failure` stub to the `notifications_sent` table; T4 will migrate the 25+ caller sites from try/except Exception to safe_send.
<!-- T4a --> Migrated try/except Exception caller pattern to safe_send wrapper at src/scheduler/{watch,reports,watch_handlers,overnight}.py. ImportError on notify_X functions now propagates to startup; only network errors are caught. Part of Group A.3 16-file migration (T4a scheduler track).
<!-- T4b --> Migrated 13 notification call sites across `src/services/scan_service.py` and `src/shadow_trading/executor.py` from the `try { import notify_X + is_telegram_enabled() check } except Exception` pattern to one-line `safe_send(event_type, **kwargs)`. scan_service.py: 1 site (`trade_opened` on shadow trade open). executor.py: 12 sites — `trade_closed`, `risk_alert` × 2 (live capital guard + daily loss limit), `trade_opened` (live trade), `milestone` × 7 (open/close/streak milestones in helper functions), `streak_alert`, `exposure_alert`. Redundant inline `send_telegram` imports at 8 executor.py sites eliminated (module-level import already present). `safe_send` also hoisted to module-level import in scan_service.py. Post-fix: 0 `try:.*from src.notifications` matches in all 4 scope files.
<!-- T4c --> Migrated 4 training+risk notify call sites to `safe_send`: `training/canary.py` (_send_alert → `model_event`), `training/ingestion_gate.py` (alert_training_halt → `system_event`), `training/trainer.py` (holdout-empty → `trainer_holdout_empty`), `risk/governor.py` (governor-disabled → `system_event`). Eliminates silent swallow of ImportError/NameError at each call site.
<!-- T4d --> Migrated remaining `try/except Exception` notification patterns to `safe_send`: `research_synthesizer.py` (1 site — `send_telegram` direct call → `safe_send("research_digest", ...)`), `cli/commands.py` (1 site — `_notify_startup_telegram` → `safe_send("startup_complete", ...)`), `cloud_routes/platform.py` (3 sites — outer `try/except Exception` wrappers removed from `notify_backtest_complete`, `notify_strategy_promoted`, `notify_strategy_demoted` calls; platform_events functions retain their own internal error handling). `auditor.py` confirmed 0 notification patterns via GREP (no-op).
<!-- T5  --> Fixed I10 — relocated lazy `from src.notifications import safe_send` imports from function bodies to module-level in `src/cli/commands.py`. ImportError now surfaces at process startup, not at first command-execution hit. New regression test `tests/cli/test_commands_imports.py` (NEW, +2 tests) AST-walks the module to lock no-lazy-imports invariant.
<!-- T6  --> Fixed I12: `check_action_reminders` at src/notifications/telegram_commands.py now uses per-check try/except (5 independent reminder checks). Previously a function-wide bare `except Exception` aborted all 5 if any raised — including operator-action-required reminders (API key rotation, phase-gate milestone, retrain-overdue alert). Fixed CC2: consolidated duplicate `_get_telegram_config` (telegram.py:104 + telegram_commands.py:32) into shared `src/notifications/_config.py` (NEW). Both modules import from the new module. Regression test `tests/notifications/test_check_action_reminders_isolation.py` (NEW) locks both fixes.
<!-- T7  --> Added cloud-req fast-lane AST guardrail (`tests/test_cloud_requirements_imports.py` + `scripts/check_cloud_deploy_imports.py`) preventing the recurring cloud-deploy import drift bug class (jsonschema -> numpy -> requests -> scipy — Sprint 3 #1007 was 4th recurrence). PR-time check; sub-second runtime; walks src/api/cloud_app.py import graph transitively through all of src/, validating each top-level package is stdlib or present in requirements-cloud.txt. Catches all 4 historical IMPORT-statement recurrences (jsonschema, numpy, requests, scipy) including deep-transitive ones (jsonschema lives at src/platform/capability_registry/schemas.py, two hops outside src/api/). Note: tzdata (5th recurrence, surfaced by T8 slow-lane) loads via `zoneinfo.ZoneInfo()` runtime string lookup — out of AST walker design scope; T8 slow-lane is the detection vector for that class. T8 slow-lane provides defense-in-depth via venv subprocess.
<!-- T8  --> Added cloud-req slow-lane venv subprocess test (`tests/test_cloud_requirements_imports.py` extension) + tzdata to requirements-cloud.txt (5th recurrence of cloud-deploy import drift bug class — `zoneinfo.ZoneInfo('America/New_York')` fails on Windows clean venv without OS tzdata; masked on Linux Render). T8 revision adds: subprocess child-kill on timeout (`_run_or_kill` helper), PyPI-offline skip guard (`has_pypi_network` fixture), configurable timeouts via env vars (`CLOUD_REQ_PIP_TIMEOUT`, `CLOUD_REQ_IMPORT_TIMEOUT`), and pytest slow-marker registration (`pytest.ini`). Marked `@pytest.mark.slow`; creates temp venv, installs ONLY requirements-cloud.txt, asserts `from src.api.cloud_app import app` succeeds. Synthetic regression-lock asserts missing scipy raises ModuleNotFoundError. Defense-in-depth complement to T7 fast-lane AST walker; informational/CI-only — does NOT block PR merge.
<!-- T9  --> Extended _desk_clause() helper at `src/api/cloud_routes/trades.py:42-60` from 2-tuple to 3-tuple (`(frag, params, cohort_id)`). For `desk='live'`: emits SQL fragment `source = %s` with param `'live'` AND `cohort_id='trades.live_only'`; other desks: `cohort_id='trades.all_closed'`. 5-endpoint blast radius — all 5 callers in `trades.py` (shadow_open, shadow_closed, sharpe_attribution, shadow_metrics, shadow_account) updated to consume new 3-tuple. shadow_metrics emits cohort from helper instead of hardcoded 'trades.all_closed'. Updated 5 helper unit-test unpacks at `tests/test_shadow_desk_filter.py` to match new tuple shape. New `tests/api/test_sharpe_attribution.py` (NEW file) + extended `tests/api/test_shadow_metrics.py` cover per-desk cohort behavior across 11 tests.
<!-- T10 --> Fixed cockpit-#2: `/api/status` `open_positions` SQL now includes `AND source = 'live'` predicate, aligning the query with its `_meta` cohort label `'trades.live_only'`. Pre-fix, the count included all open trades regardless of source (live + swing), making the label a lie. Sibling-search confirmed only one `WHERE status='open'` site in `core.py`. Added 2 regression-lock tests: `test_status_open_positions_cohort_aligned` (5-row fixture: 2 live + 3 swing → open_positions=2) and `test_open_positions_sql_filters_source_live` (SQL call_args assertion verifying `source` and `live` appear in the issued SQL).
<!-- T11a --> Added `compute_total_pnl_dollars(instrumented)` to `kpis_compute.py` (sum of `pnl_dollars` rounded to 2dp). Wired into `/api/kpis` response as top-level `total_pnl_dollars` field and `_meta.total_pnl_dollars` with `cohort='kpi.canonical'`, `n=n_trades`, `label=COHORT_LABELS['kpi.canonical']`. Zero-safe: returns `0.0` when no instrumented trades. +3 tests in `tests/api/test_kpis.py` (value+sum, meta cohort+n, empty-DB zero).
<!-- T11b --> Hardened email subsystem (Group B): (C5) `cc_addresses or []` guards against YAML omission returning None — eliminates TypeError on `[recipient] + cc_addresses`; (C4) removed YAML `password` fallback from `send_email` — `EMAIL_PASSWORD` env var now required, warning emitted at call-time if YAML key is non-empty (security: passwords must not live in YAML config); (C17) when `smtplib.sendmail` returns a non-empty failures dict, invoke `safe_send("system_event", ...)` as telegram fallback with subject + body truncated to 400 chars; (N1) re-exported `digest_builder` module from `src/email/__init__.py` so callers can `from src.email import digest_builder`. New `tests/email/test_notifier.py` (+8 tests) covers all four fixes plus envelope, TLS, and ConnectionRefused paths.
<!-- T12 --> Replaced PromotionGateCard (5th card) in `frontend/src/components/dashboard/KPIStrip.jsx` with new `TotalPnlDollarsCard` reading `safeKpis.total_pnl_dollars` + `_meta.total_pnl_dollars` envelope. Promotion-gate vote count surfaced via tooltip badge under `TrafficLightCard` (new `promotionKpi` prop) so the methodology-gate signal is preserved without consuming a primary card. Closes cockpit-#8b / #SP3-T12-pnl-card. New tests in `frontend/src/components/dashboard/KPIStrip.test.jsx` lock: dollar formatting `$X,XXX.XX`, meta badge `n=...` visible, `Promotion Gate` text absent, `4/5` vote count rendered in TrafficLight slot.
<!-- T13a --> Added `_html_escape(text)` helper (I6) escaping `&`, `<`, `>` for HTML parse_mode messages. Added chunked send to `send_telegram` (C15): messages >4000 chars are split at `_TELEGRAM_CHUNK_SIZE=4000` boundaries and sent as multiple messages with `[chunk N/M]` markers. Extraction of `_send_single` helper keeps the function body under the 60-line cap. New tests: `tests/notifications/test_html_escape.py` (6 tests) and `tests/notifications/test_telegram_chunked_send.py` (4 tests).
<!-- T13b --> C16: `notify_research_digest` now truncates `digest_summary` at 800 chars and appends `\n[truncated; see email digest]`. C7: `notify_overnight_complete` mirrors `notify_overnight_training_complete` dict-with-success pattern — dict values with `success=False` render ❌ with error text instead of silently showing ✅. I11: `notify_action_required` raises `ValueError` on unknown urgency (was silent default to "🔔"). I16: hardcoded `&amp;` in `notify_premarket_brief` ("S&amp;P") and `notify_weekly_digest` ("P&amp;L") replaced with `_html_escape()` calls — output identical but now uses canonical helper.
<!-- T13c --> I15: new `src/data_ingestion/finnhub.py` with `normalize_earnings_time(raw)` — maps "Pre-market"/"PRE"/"before market" → "BMO", "After hours"/"AMC"/"after market" → "AMC", None/"" → "TBD". Wired into `notify_position_earnings_warning` replacing inline ad-hoc string check that missed "Pre-market". Note: I11 urgency ValueError guard delivered in T13b per spec order.
<!-- T13-SECREV --> [SECURITY REVISION] applied `_html_escape` to 11 external-data interpolations across `src/notifications/telegram.py`: `last_error` (notify_collection_failure), `top_paper` (notify_research_papers), `digest_summary` (notify_research_digest), `model_name`/`event`/`detail` (notify_model_event), `exit_reason`/`ticker` (notify_trade_closed), `event`/`detail` (notify_system_event), `action`/`detail` (notify_action_required), `milestone`/`detail` (notify_milestone), `key`/`val`/`err` (notify_overnight_complete), `task`/`error` (notify_overnight_training_complete). Made `_html_escape` None-safe and str-coercing (prevents AttributeError when Optional[str] fields are None). Added plaintext fallback in `send_telegram` chunked path: if any HTML chunk returns 400 (Telegram tag-tearing error), all chunks are retried with `parse_mode=None` ensuring delivery. New static-analysis test `tests/test_safe_send_event_type_literal_guardrail.py` AST-walks all `safe_send()` call sites in `src/` and asserts the `event_type` argument is always a string literal — fails on any future PR that wires a dynamic value to event_type. Net +5 new tests (3 None/int-guard + 1 plaintext-fallback chunk + 2 AST-literal guardrail).
<!-- T14 --> Registered `notifications_sent` (id INTEGER PK + event_type, channel ['telegram'|'email'], recipient, sent_at, status ['ok'|'failed'|'dropped'|'heartbeat'], retry_count, error_msg + index on (event_type, sent_at DESC)) and `notifications_dedup` (id INTEGER PK + UNIQUE(event_type, dedup_key) + sent_at) tables in `src/schema/registry.py` per CLAUDE.md schema-rules-mandatory. Schema-only — T15 (Batch 4) wires the write hooks; retention policy deferred to Sprint 5 follow-up `#SP5-notifications-retention`. EXPECTED_TABLE_COUNT bumped 68→72 in `tests/test_schema.py`; +5 schema-shape tests covering column types, nullability, indexes, and UNIQUE constraint.
<!-- T15a --> Migrated `_DEDUP_CACHE` (in-memory dict) in `src/notifications/platform_events.py` to DB-backed dedup via `notifications_dedup` table. New `_already_notified_recently_db(event_type, dedup_key, conn=None, db_path=None)` reads/writes the table; expired rows (>24h) are updated in-place so the slot is reused. NSSM-restart-safe: dedup state survives watch-loop restarts because the DB persists across process boundaries. Added `write_heartbeat(conn=None)` writes a `status='heartbeat'` sentinel to `notifications_sent` for pipeline liveness checks. +5 tests in `tests/notifications/test_dedup_persistence.py`.
<!-- T15b --> Wired `_write_notification_sent(event_type, channel, status, error_msg, recipient, conn)` into `src/notifications/telegram.py` `safe_send` (success → `status='ok'`; network failure → `status='failed'` via `_record_send_failure`) and `src/email/notifier.py` `send_email` (SMTP success → `channel='email', status='ok'`; all failure paths → `channel='email', status='failed'`). New `src/api/cloud_routes/notifications.py` exposes `GET /api/notifications/health` returning last-24h `{success_rate, fail_count, dedup_hits, oldest_unack_alert}` from `notifications_sent` + `notifications_dedup`. Route registered in `src/api/cloud_app.py`. +4 tests in `tests/notifications/test_safe_send_hooks.py` + 4 tests in `tests/api/test_notifications_health.py`.
<!-- T15c --> New `frontend/src/components/dashboard/NotificationsHealthPanel.jsx` — bottom-of-page widget that reads `/api/notifications/health` via arrow-form `queryFn` (per Sprint 3/4 T16 ESLint rule). Displays success_rate badge (green ≥95%, amber ≥80%, red otherwise), fail_count, dedup_hits, and oldest_unack_alert. Added `getNotificationsHealth()` to `frontend/src/api.js`. Appended §"Notification dedup migration" to `docs/operator-guide.md` with NSSM restart warning about expected one-shot duplicate alerts + optional post-deploy dedup seed script.
<!-- T15-REV --> QA REJECT revision: (MF1) wired `_already_notified_recently_db` into both `notify_backtest_complete` and `notify_shadow_gate_ready` in `platform_events.py` — both now use DB-backed restart-safe dedup; `_already_notified_recently` (in-memory) retained with zero production callers for now (see module docstring). (MF2) Added `force_send: bool = False` kwarg to `notify_validation_summary` in `telegram.py` — `force_send=True` bypasses the silent-on-pass branch (spec C12). (MF3) Chose **Option A** for `/api/notifications/health` cloud architecture per operator review: flipped `sync_to_postgres=True` on both `notifications_sent` and `notifications_dedup` in `src/schema/registry.py` so render_sync.py mirrors them to Postgres, refactored the endpoint to dual-mode (SQLite local / Postgres on Render via `psycopg2`, mirroring `kpis_compute._fetch_closed_trades` pattern), and re-included the router in `src/api/cloud_app.py` with `verify_auth` dependency override (matching the kpis/broker_exceptions/preflight registration pattern). The cockpit `NotificationsHealthPanel` widget is now functional in both local dev and Render production. (SF4/auth) Resolved by re-including with `verify_auth` override. (SF5) End-to-end test for `safe_send` failure path now writes to a real tmp_path SQLite DB (no mock on `_write_notification_sent`). (SF6/heartbeat) Deferred: wiring `write_heartbeat` into `src/scheduler/watch.py` is out of T15 scope; tracked as follow-up.
<!-- T16 --> Extended `frontend/eslint-rules/no-bare-queryfn-with-args.js` to flag any `queryFn` value that is not an `ArrowFunctionExpression` or `FunctionExpression` (catches Identifier + CallExpression in addition to the Sprint 3 MemberExpression-only scope). Wrapped bare Identifier call sites: `StrategyResearch.jsx:41` and `PlatformStatusWidget.jsx:13` (`getPlatformStrategies` → `() => getPlatformStrategies()`). Also wrapped `BrokerExceptionsPanel.jsx:110` and `PreflightStatusCard.jsx:77` which were newly caught by the extended rule (zero-arg local helpers, safe in practice but now consistent). Created `frontend/eslint-rules/no-bare-queryfn-with-args.test.js` with 4 RuleTester cases: Identifier fires, ArrowFunctionExpression passes, FunctionExpression passes, CallExpression fires. `npm run lint:queryfn` exits 0; `tests/test_eslint_queryfn_guardrail.py` 2/2 pass.
<!-- T17a --> Migrated Calmar ratio at `src/evaluation/cto_report.py:738` and `src/simulation/engine.py:439` to canonical `calmar_ratio()` from `src.evaluation.statistics`. Both sites now import and call `calmar_ratio(annualized_return, max_dd)` instead of inline division. Removed both from `_ALLOWLIST` in `tests/test_calmar_canonical_only.py`. Behavioral equivalence: canonical returns `0.0` for zero drawdown; both call sites guard `max_dd > 0` or `max_dd != 0` before invoking so zero-drawdown behavior is unchanged. +6 new tests in `test_calmar_canonical_only.py` (T17a/T17b canonical-match assertions + allowlist-empty enforcement + compute_calmar zero-dd → 0.0).
<!-- T17b --> Migrated remaining 2 Calmar canonical-debt sites: `src/evaluation/backtester.py:343` (`round(ann_return / abs(max_dd_pct), 2)` → `round(calmar_ratio(ann_return, abs(max_dd_pct)), 2)`) and `src/platform/metrics.py:75` (`compute_calmar` body delegated to `calmar_ratio(total_return, max_drawdown)`). Behavioral change: `compute_calmar(x, 0.0)` now returns `0.0` (canonical) instead of `float('inf')`. INF-sentinel sibling-search across src/ found 0 callers that depend on the inf sentinel. Emptied both `_ALLOWLIST` and `_CALMAR_FUNC_ALLOWLIST` in `tests/test_calmar_canonical_only.py`. Updated `_scan_calmar_func_defs` guardrail to exempt thin-wrapper calmar-named functions whose body calls `calmar_ratio(` — allowing `compute_calmar` to retain its API-compatible name while the formula debt is resolved. All 4 canonical-debt Calmar sites now migrated; both allowlists are empty.
<!-- T18a --> Fixed negative-P&L sign formatting in `LiveLedger.jsx` `PnlValue` component (line 40): `Math.abs(value).toFixed(2)` without sign prefix stripped the minus sign from all losing trades, showing e.g. `$150.50` instead of `-$150.50`. Fixed with `{value > 0 ? '+' : value < 0 ? '-' : ''}` prefix. New test file `frontend/src/pages/__tests__/PnlSignFormatting.test.jsx` (T18a tests: negative → `-$150.50`, positive → `+$200.00`, zero → `$0.00`).
<!-- T18b --> Fixed negative-P&L sign formatting in `ShadowLedger.jsx` at 3 sites: `PnlValue` component (line 64, same pattern as T18a), open-cols inline render (line 568, dead code — open tab uses `OpenPositionCard` cards), and closed-cols inline render (line 592). All 3 sites now use `{val > 0 ? '+' : val < 0 ? '-' : ''}` ternary before `$`. `PnlSignFormatting.test.jsx` extended with 4 T18b assertions targeting the closed tab (where SummaryRow PnlValue + closedCols render). **Out-of-scope finding:** `OpenPositionCard.jsx:122` has the same bug for live open-trade P&L display; PM-tracked for T18d.
<!-- T18c --> Fixed negative-P&L sign formatting in `TradeHistory.jsx` `formatDollars` helper (lines 31-36): `sign = val >= 0 ? '+' : ''` produced no sign prefix for negative values. Fixed to `val > 0 ? '+' : val < 0 ? '-' : ''`. `PnlSignFormatting.test.jsx` extended with 2 T18c assertions (negative → `-$150.50`, positive → `+$200.00`). ActivityFeed regression-lock test confirms `ActivityFeed.jsx:57` remains correct (already uses raw signed value).
<!-- T18d --> fix(cockpit-#4): OpenPositionCard.jsx:122 — correct sign-dollar order for open-tab P&L (negative rendered $-150.50; now renders -$150.50); sibling-site fix for T18 5-site sweep
<!-- T18e --> Fixed cockpit-#4 sign-formatting bug at `frontend/src/components/ActivityFeed.jsx:57` (7th sibling site). The original `($${d.pnl_dollars >= 0 ? '+' : ''}${d.pnl_dollars.toFixed(2)})` placed the sign INSIDE the dollar sign, rendering `($-150.50)` for negative P&L. Replaced with native sign-preserving pattern `(${sign}$${Math.abs(value).toFixed(2)})`, matching the canonical form in LiveLedger/ShadowLedger/OpenPositionCard. Zero sign produces `($0.00)` (no prefix). The original T18 spec wrongly listed ActivityFeed as non-buggy; T18d agent caught it during sibling-search review.
<!-- T19 --> Extended reconciliation test coverage (Sprint 4 T19a/b/c): (a) `postgres_session` fixture added to `tests/conftest.py` (function-scoped, isolates per test per reviewer #12); `test_dashboard_reconciliation.py` parametrized against SQLite + Postgres backends — Postgres variant skipped when `TEST_DATABASE_URL` absent so test count stays stable across CI and local environments (`DATABASE_URL` is intentionally NOT honored — operator's `.env` points at production Render Postgres and CLAUDE.md forbids tests touching prod) (#SP4-render-pg-reconcile); (b) `test_kpis_meta_envelope_reconciliation` in `tests/api/test_status.py` regression-locks `_meta.rf_adjusted_excess_sharpe`, `_meta.win_rate`, and `_meta.total_pnl_dollars` all carrying `cohort='kpi.canonical'` and non-negative integer `n` fields, with full hermetic patch set (`_fetch_closed_trades` + `_fetch_spy_returns_for_trades` + `filter_fully_instrumented`) (#SP4-kpis-meta-reconciliation-test); (c) `test_status_open_positions_cohort_aligned_via_core_router` regression-locks `core.py:147-150` SQL includes `source='live'` and `_meta.open_positions.cohort='trades.live_only'` via `create_router` path (complementary to existing `cloud_app`-patched T10 tests) (#SP4-status-open-positions-cohort).
<!-- T20 --> *placeholder mid-W2 visual-verify checkpoint*
<!-- T21a --> Extended `tests/notifications/test_telegram_commands.py` with `TestCommandHandlerHappyPaths` (17 tests) and `TestCommandHandlerErrorPaths` (17 tests) covering all 17 `handle_command` routes (C13). New `tests/notifications/test_telegram_send_path.py` (+1 test) foundation send-path test: `send_telegram` → POST API mock → `True` return (CC5). Net +35 tests.
<!-- T21b --> Added 5 typed exception classes (`CostCapExceededError`, `AgentTimeoutError`, `LLMUnavailableError`, `NoQuorumError`, `InvalidQuestionError`) to `src/notifications/telegram_commands.py`. Extracted `run_council_command` wrapper for patchability. Replaced generic `except Exception` in `_cmd_council` with 5 typed except branches returning categorized diagnostic strings per C14 spec. Added `@dataclass` payload classes (`TradeOpenedPayload`, `TradeClosedPayload`, `EodReportPayload`, `WeeklyDigestPayload`) to `src/notifications/telegram.py` (CC3): missing required field → `TypeError` at construction. +13 tests.
<!-- T21c --> `docs/operator-guide.md`: added §12 "Notification Troubleshooting" covering bot-silent decision tree (health endpoint, NSSM restart, stale watch.lock), bot-token rotation procedure, email-digest failure diagnosis (SMTP config + `notifications_sent` table query), and subsystem health verification via `/api/notifications/health` (I13). `docs/telegram-commands.md`: added "CLI: send-test-email" section documenting the command, when to use it, and troubleshooting table (I14). TOC entry for §12 added to operator guide.
<!-- T21-REV --> Wired CC3 dataclass payloads into all 4 notify_* functions: `notify_trade_opened`, `notify_trade_closed`, `notify_eod_report`, `notify_weekly_digest` now accept typed payload objects only (Option A — breaking change). Updated `safe_send` to route payload events via `kwargs["payload"]`. Updated all 6 call sites: `scheduler/reports.py` (eod_report + weekly_digest), `scheduler/universe_scanner.py` (trade_opened), `shadow_trading/reconcile.py` ×2 (trade_closed), `shadow_trading/executor.py` (trade_closed via safe_send). Updated 7 test files to use payload API. New `tests/notifications/test_telegram_payload_wiring.py` (+21 tests) covering wiring + safe_send full chain.
<!-- T23 --> Sprint 4 closeout (T23): visual-verify gate (13 post-merge screenshots, all PASS), operator-guide enhancements (§1 GPU prerequisite, §5 corpus-not-progressing decision tree, §7 watchdog-timeout signs, §8 SD#NN glossary entry), WON'T-FIX paragraph for `#SP4-settings-backend-float32-storage`, test floor confirmed ≥4798 (T22 skipped → `#SP5-notifications-routing-policy` opened as #69), CHANGELOG T22 placeholder removed, `src/data_enrichment/news.py` 490-line violation disclosed in `config/known_violations.json`.

## [v0.33.0] - 2026-05-07 — Sprint 3 Cockpit Coherence

### Group E — Correctness bugs (5 fixes)

- **T1 (#987): E5 Calmar 1000x overshoot.** Replaced ad-hoc formula in analytics.py:568 with call to canonical src/evaluation/statistics.py calmar_ratio() helper. Added tests/api/test_calmar_unit_audit.py regression-lock + tests/test_calmar_canonical_only.py CI guardrail. 3 additional hand-rolled Calmar sites (cto_report.py, engine.py, backtester.py) allowlisted, tracked as #SP4-calmar-debt.
- **T2 (#988): E6 Attribution paired-overlap gate.** Replaced marginal-count gate with paired-overlap count. Updated Attribution.jsx label to paired_n/200 with subtitle. Fixed regression: old gate overstated statistical power when marginal counts exceeded paired overlap.
- **T3 (#990): E7 Monitoring 500/503 fix.** analytics.py:935-957 now returns {snapshots: [], note: 'system_metrics is local-only...'} on UndefinedTable/runtime errors. Updated Monitoring.jsx data-shape consumption. Backend + frontend handle local-only system_metrics gracefully on Render.
- **T4 (#988): E2 stop_loss sign + E4 profit_factor None sentinel.** E2: sign inversion is in display layer (tracked as #SP4-stop-loss-fallback). E4: engine.py:458 now emits Python None instead of 999.0 when profit_factor is inf. T4-followup made compute_verdict() + print_heatmap() None-safe via 'or 0' pattern.
- **T11 (#985): Settings float-precision clamp + Health IB-status feature flag.** Settings risk inputs no longer show float artifacts (0.0049999... to 0.005). Health IB-status card rendered conditionally behind feature flag.

### Group A — Cohort taxonomy (2 backend + 1 frontend)

- **T8 (#991): A1.A Backend _meta envelope helper + KPI/CTO/Status emission.** New src/api/cohort_meta.py with meta_entry(cohort_id, label, n) helper and 8-cohort closed taxonomy. Wired _meta onto /api/kpis, /api/cto-report, /api/status. All changes additive.
- **T9 (#993): A1.B _meta on remaining 7 endpoints.** Wired meta_entry() into /api/shadow/metrics (all desks → trades.all_closed; #SP4-shadow-metrics-live-cohort for true live filter), /api/attribution/stats, /api/strategy-detail, /api/model-performance, /api/build-score, /api/health/hshs, /api/stress-test/results, /api/simulation/results. T9-followup corrected trades.live_only cohort mapping at f42a095.
- **T12 (#997): A4 Dashboard/TradeHistory/Strategy meta consumption.** KPIStrip.jsx: rf-adjusted excess Sharpe + win rate cards wired to _meta cohort badges. TradeHistory.jsx: inline cohort badge below Excess Sharpe panel. Strategy.jsx: inline cohort badge from /api/strategy-detail._meta. T12-followup added missing tests + spec-drift resolution. total_pnl_dollars has no primary value card (#SP3-T12-pnl-card).
- **T5 (#986): A3 KPICard meta prop + cohort badge.** KPICard in KPIStrip.jsx accepts meta prop and renders cohort badge (n=N · last-segment). Foundation for T12 sub-card wiring.

### Group B — Header source-of-truth

- **T10 (#992): B1+B2 Layout.jsx /api/kpis with 3-state fallback.** Header TL indicator now reads stage_traffic_light from /api/kpis. Three fallback states: pending to TL: ..., loaded-but-null to TL: COMPUTING, errored to TL: ERR. Closes TL: NOT SET regression.
- **T16 (#999): B3 CI dashboard reconciliation test (cohort-aware, SQLite-only).** New tests/test_dashboard_reconciliation.py — 8 tests regression-locking _meta envelope across 5 endpoints. Cohort-aware: test_closed_count_reconciles checks cohort match BEFORE n equality. Postgres validation deferred to #SP4-render-pg-reconcile.

### Group C — Loading state

- **T6 (#983): C1 Shared LoadingState component (with retryDisabledFor cooldown).** New frontend/src/components/LoadingState.jsx. 3-state: loading to data/empty/error. retryDisabledFor={ms} cooldown. API: isLoading, isError, error, retry, retryDisabledFor, isEmpty, loadingMessage, emptyMessage, compact, children.
- **T13 (#996): C2 Migrated 4 widgets to LoadingState.** BrokerExceptionsPanel, DBSchema, Health, Monitoring — all use LoadingState instead of ad-hoc patterns. Closes E7 presentation bug: Monitoring 500/503 now renders explicit error card + retry button instead of infinite spinner.

### Group F — Operator-action ambiguity

- **T7 (#984): F1 Shared ActionButton (cliOnly + secure-context fallback).** New frontend/src/components/ActionButton.jsx. cliOnly=true renders disabled button + [CLI only] badge + tooltip with CLI command copy. Clipboard uses navigator.clipboard with window.isSecureContext check; falls back to pre with select-on-click hint. T7-followup added interactive prop to Tooltip with hover-bridge.
- **T14 (#998): F2 Migrated 4 pages to ActionButton.** LiveLedger (reconcile button to cliOnly), DiagnosticKickoffButtons (3 buttons), Simulation (2 run buttons), Council (Run Council Now + Ask Council). profit_factor null renders 'N/A (no losses)' in Simulation.
- **T15 (#995): F2.B Settings IB toggle migration to visually-disabled with whyDisabled tooltip.** live_trading.ib.shadow_mode and live_trading.ib.paper_routing toggles are visually disabled (cursor-not-allowed opacity-40). whyDisabled: 'Effect requires local IB Gateway connection' rendered inline, always visible. Click is a true no-op. Non-IB toggles unchanged (BC).

### TanStack v5 sweep + ESLint guardrail

- **T17 (#994): E1.A1 Bare-queryFn sweep (Layout, RevenueProjection, IBShadow, Notes).** 4 bare refs wrapped in arrow form.
- **T18 (#1003): E1.A2 Bare-queryFn sweep (Dashboard, ModelPerformance, StressTest, Training).** 11 bare refs wrapped.
- **T19 (#1002): E1.A3 Bare-queryFn sweep (Docs, Validation, TradeHistory).** 3 bare refs wrapped. Closes TradeHistory.jsx:238 getSharpeAttribution(desk) desk=[object Object] regression.
- **T20 (#1001): E1.B Bare-queryFn sweep (Attribution, Settings, Health, Monitoring).** 8 bare refs wrapped.
- **T21 (#1000): E1.B2 Bare-queryFn sweep (LiveLedger, Council, Simulation, ShadowLedger).** 6 bare refs wrapped. Closes ShadowLedger.jsx:476/478/481 primary desk=[object Object] regression sources.
- **T22 (#1004): E1.C ESLint custom rule + pytest fixture preventing future bare-queryFn regressions.** frontend/eslint-rules/no-bare-queryfn-with-args.js reports error on bare MemberExpression queryFn. Registered as local/no-bare-queryfn-with-args: error. lint:queryfn npm script. tests/test_eslint_queryfn_guardrail.py with 2 tests.

### Test floor

- Pre-Sprint-3: 4602 baseline (post-Sprint-2).
- Post-Sprint-3: **4702 passing** (actual run 2026-05-07 T23 closeout). Spec target was 4646 (44 new tests estimated); actual +100 net from pre-sprint baseline, likely due to parametrized tests expanding beyond estimates. 43 pre-existing failures unchanged (tracked in CI, not regressions).

### Sprint 3 CI guardrails added

- tests/test_calmar_canonical_only.py: any def *calmar* outside src/evaluation/statistics.py fails CI.
- tests/test_eslint_queryfn_guardrail.py: bare-queryFn refs in useQuery fail via ESLint rule.
- tests/test_dashboard_reconciliation.py: cohort-aware reconciliation across 5 endpoints.

### Sprint 4 follow-up issues (open items)

- #SP4-shadow-metrics-live-cohort: wire source='live' SQL filter for /api/shadow/metrics when desk='live'.
- #SP4-status-open-positions-cohort: align /api/status._meta.open_positions cohort label with SQL filter.
- #SP4-calmar-debt: migrate 3 hand-rolled Calmar sites (cto_report.py, simulation/engine.py, backtester.py) to canonical helper.
- #SP4-stop-loss-fallback: locate and fix downstream stop_loss display sign-inversion (T4 E2 downgrade).
- #SP4-render-pg-reconcile: extend T16 reconciliation test to Postgres (currently SQLite-only).
- #SP4-kpis-meta-reconciliation-test: regression-lock /api/kpis _meta envelope (T16 substituted stress-test/results due to fixture-isolation).
- #SP4-tanstack-strategyresearch-platformstatus: bare-ref queryFn at StrategyResearch.jsx:41 + PlatformStatusWidget.jsx:13 (pre-existing, surfaced by T22 ESLint investigation).
- #SP3-T12-pnl-card: no dollar P&L primary card in 5-card KPIStrip — design decision to add one or accept the gap.


## [v0.32.0] - 2026-04-29 — Sprint 1.C Phase 1 + Phase 2: attribution discipline + LLM-prompt PIT audit

### Release summary

Sprint 1.C kicked off with operator option C ("wire LLM-scoring into backtester first, then build deterministic-ranker shadow"). Phase 1 closed three measurement-quality bugs in attribution data surfaced by the §4 attribution_readout in PR #845. Phase 2 audited all 11 sections of the LLM prompt assembly path against PIT semantics — the binding finding that gates Phase 4 corpus generation. Pre-reg §3.1 Stage 1 start date may need revision from 2014 to ~2022 due to insider/news Finnhub coverage limits surfaced by the audit.

### Added

- **Attribution canonical action validator** (`src/attribution/logger.py`) — `_CANONICAL_LLM_ACTIONS` frozenset + `ValueError` on non-canonical input. Caller-side bugs surface immediately at write time. (#846 / PR #849)
- **`scripts/diagnostics/attribution_readout.py` band correctness** — bands rescaled from 0-49/50-69/70-84/85+ (modeled on ranker_score 0-100) to 1-3/4-6/7-8/9-10 matching the canonical 1-10 conviction scale. Surfaced 7-8 band as the cleanest signal currently available (avg pnl 1.56% on n=32, not contaminated by conviction=5 parse-failures). (#847 / PR #851)
- **Coverage-drop postmortem** — `audits/attribution-coverage-drop-postmortem-2026-04-29.md`. The audit's "117 H1 vs 3 H2" headline reframed: not a coverage break but a model-version transition (`halcyon-v1.0.0` → `arcis:v1.0.0`) on Apr 13 compounded with parse-failure pollution. (#848 / PR #852)
- **LLM-prompt PIT-cleanliness audit** — `docs/research/llm-prompt-pit-audit.md`. 11 prompt sections traced against PIT semantics. Sections 1-2 clean; 4/5/7/10/11 PIT-broken (HIGH severity); 6 wireable; 3 needs operator policy; 8/9 unclear. Six operator decisions surfaced. (#94 / PR #853)
- **8 PIT follow-up trackers filed** (#854-#861) for the must-fix sections + sub-investigations + sector-PIT-policy doc.
- **#850 follow-up tracker filed** for conviction=5 parse-failure pollution (gates Phase 4 corpus generation).

### Fixed

- **`src/services/scan_service.py:305`** wrote non-canonical `"buy"`/`"skip"` labels for 227 rows (80 + 147) silently excluded from §4 t-test. Canonicalized to mirror `universe_scanner.py:248-253` semantics: `taken` if rec_id+conviction, `conviction_none` if rec_id+no-conviction, `rejected` otherwise. (#846 / PR #849)

### Decisions

- **Sprint 1.C option C locked in** — wire LLM-scoring into backtester first, then build deterministic-ranker shadow. Pre-computed corpus strategy chosen over live-LLM-call.
- **Phase 1d added** — #850 parse-failure flag (option B: schema add, non-destructive) added as Phase 1d after #847 surfaced the parse-failure pollution. In flight at v0.32.0 cut.
- **Pre-reg §3.1 revision likely** — Stage 1 start date may need to advance from 2014 to ~2022 per audit findings (Finnhub coverage limits on Sections 5+6). Phase 3 addendum will lock the final decision.

## [v0.31.0] - 2026-04-28 — Sprint 1.B Wave A/B/C: walk-forward harness + methodology wiring

### Release summary

Sprint 1.B closed the gap between the methodology toolkit shelf (built across PR-690 / Track 1.5) and production wiring. Walk-forward harness, cost-model calibration, FRED-backed risk-free rate, promotion-gate post-train flow, subgroup-analysis harness all wired. Pre-registration document drafted (Stage 1 walk-forward validation discipline). Pre-push hook (#59) closed the stale-base hazard class after 5 incidents in 5 days.

### Added

- **Walk-forward harness** (`src/evaluation/walkforward.py`) — anchored expanding × 8 folds × 21-day embargo. Underpowered-fold flag (<15 trades) excludes from primary aggregate per pre-reg §3.5. (#78 / PR #831)
- **Cost-model calibration wiring** — backtester reads `data/calibration/cost_model.json`; per-trade `median_round_trip_cost_bps` deducted at entry. Falls back to zero cost with warning if absent. (#79 / PR #834)
- **FRED-backed risk-free rate** — `src/data_ingestion/risk_free_rate.py` wired into backtester via per-trade `get_rf_rate()` lookup. Replaces placeholder `rf=0.0001`. (#80 / PR #835)
- **Promotion-gate post-train flow** — `src/methods/promotion_gate.py` wired into training/post-train; ≥4-of-5 voting gate now runs on every promotion candidate. (#49 Sprint 1.B Wave B / PR #836)
- **Subgroup-analysis harness** (`src/evaluation/subgroup_analysis.py`) — pre-reg §6 exploratory subgroups (regime/year/sector/LLM-conviction) with per-partition metrics (trade_count, mean_return, win_rate, Sharpe via canonical raw_sharpe, max_drawdown_pct). 24 tests. (#81 / PR #845)
- **Pre-registration document** (`docs/research/pre-registration-stage1.md`) — binding methodology contract per §5.3 (forbids post-hoc fixes once Stage 1 begins). (#63 / PR #822)
- **Pre-push git hook** (`scripts/hooks/pre-push`) — refuses pushes from branches behind origin/main. Closes stale-base hazard class (5 incidents: #769, #816, #829, #840, #841). Bypass: `git push --no-verify`. (#59 / PR #842)
- **Backtester import smoke test** + **kill_switch test isolation** + **scan_metrics UNIQUE constraint** (#52, #62, #64 — bundled patches).

### Fixed

- **`src/evaluation/backtester.py` silent except** narrowed to `(ConnectionError, TimeoutError)` (#67 / PR #830).
- **`backtester.slice_to_date` import** restored (closes 0-trades mystery, #64 / PR #823).
- **Validator hardcoded snapshot-size cap** replaced with data-driven `max_observed × 1.05` (#65 / PR #837).
- **`diagnostic_runs` stale-job watchdog** at watch-loop startup (#56 / Tier 1.D / PR #840).
- **`docs/methodology-toolkit.md`** conflict markers shipped to main by #835 squash-merge — hotfix (PR #839).

### Decisions

- **Pre-registration § committed**: §1 deterministic-ranker shadow as secondary diagnostic; §3.5 underpowered-fold filter <15 trades; §6 four exploratory subgroups; §8.1 exploratory not pass/fail.
- **Per-trade allocation_pct=0.05** anchors the backtester equity curve; subgroup harness mirrors this for max-drawdown computation.

## [v0.30.0] - 2026-04-28 — Reconcile track + dashboard sprint (Tier 1.A-1.F)

### Release summary

Two parallel tracks closed: (1) Render Postgres delete-replication reconcile track (#68-#74) addressing 623,360 ghost rows accumulated across 25 tables from prior SQLite-archive cycles, and (2) dashboard sprint resolving operator's 2026-04-27 audit Tier 1.A-1.F findings (old-data display, empty registries, API failures + CORS, stuck training audit, "Clear stale" 404, "outcome data pending migration"). One-time manual reconcile (Pass 1 + 2 + 3) executed with operator approval.

### Added

- **Delete-replication reconcile module** (`src/sync/reconcile.py`) — `is_eligible()`, `topo_sort_reconcile_tables()`, `assert_no_ghost_rows()`, `reconcile_all()`. Snapshot-Postgres-first (race-window discipline). (#68-#74 series)
- **`TableDef.sync_reconcile: bool`** registry-driven allowlist (33 tables flagged). Pass 1+2+3 reconciled tables + "Clean (no diff)" eligibles. (#73 / PR #829)
- **Periodic reconcile in `RenderSyncThread`** — `_maybe_run_reconcile()` helper with `reconcile_every_n_cycles=30` default; integrated into `run_sync_cycle` end-of-cycle. (#72 / PR #832)
- **`src/schema/sync_config._topo_sort_tables()`** — Kahn's BFS with cycle detection via `len(result) != len(names)`; dual-source FK lookup (TableDef.foreign_keys or fallback to TABLES registry). (#76 / PR #826)
- **Dashboard cloud routes wired** — kpis, broker_exceptions, preflight orphan route imports added to `src/api/cloud_app.py`. CORS env-var documented. (Tier 1.C / PR #833)
- **Dashboard `/api/commands/expire-stale`** + **COALESCE outcome query** — closes Tier 1.E ("Clear stale" 404) + Tier 1.F (training outcome data pending migration). (PR #827)
- **Dashboard registry imports** in `cloud_app.py` to populate runtime registries on startup. (Tier 1.D / PR #816)

### Fixed

- **One-time manual reconcile** — 623,360 ghost rows deleted across 25 tables in three passes, with per-table verification protocol (BEFORE snapshot → execute → AFTER snapshot → verify Postgres delta == expected, SQLite unchanged, no remaining ghosts). pg_dump backups taken before each pass.
- **FK violation on `council_sessions`** during reconcile resolved by reordering deletes (children first).
- **Group B (~938K rows in `mode=latest_only` tables)** identified and **deferred to #75** for reconcile.py extension.
- **`fix(p0)` connect_db imports** missing across multiple sites (#767, #783 / PR #793).

### Deferred / follow-ups

- **#75** — extend reconcile.py to handle `mode=latest_only` + composite-key delete-replication (Group B cleanup).
- **#85** — split `RenderSyncThread.run()` (60-line cap follow-up).
- **#86** — integration test for periodic reconcile gating.
- **#87** — Cloud Postgres equivalents for broker_exceptions / preflight / kpis (currently SQLite-only via `connect_db()` — won't work on Render cloud).

## [v0.29.0] - 2026-04-27 — Sprint 1.A.x: point-in-time SP100 universe discipline

### Release summary

The single biggest training-data quality lift since v0.27.1. Migrated backtest, simulation, and training-backfill sites from "current S&P 100 membership" to point-in-time-correct historical universe lookups. Wikipedia-sourced JSON membership table with curated corp-action history (Tier A: PCLN→BKNG, KRFT→KHC, UTX+RTN→RTX, EMC removal, YHOO removal). Tier B (CELG, S, FB→META) added immediately after Tier A. T10 survivorship migration enforced by lint test.

### Added

- **`data/reference/sp100_history.json`** — Wikipedia-scraped historical SP100 membership snapshots back to ~2015. Loaded by `src/universe/pit.py::load_sp100_membership_table()`. (Sprint 1.A.0 / PR #802)
- **`src/universe/pit.py`** — canonical PIT lookup module: `get_sp100_at(as_of, membership_table=None)`, `get_data_range()`, `get_all_historical_tickers()`. `UniverseDataMissing` raised for out-of-range or missing JSON. (Sprint 1.A.0 / PR #802)
- **`scripts/build_sp100_history.py`** — regenerates the JSON via Wikipedia scraper + curated changes. (Sprint 1.A.0 / PR #802)
- **T10 survivorship migration** — backtest/sim/training-backfill sites now use `get_sp100_at(<as_of>)`; text-masking sites use `get_all_historical_tickers()`. Live-runtime callers (scheduler/services/cli/api/llm/platform/commands/training-bootstrap) intentionally retain `get_sp100_universe()`. (Sprint 1.A.1 / PR #813)
- **Tier A corp-action handling** — PCLN→BKNG, KRFT→KHC, UTX+RTN→RTX, EMC removal, YHOO removal in `_CURATED_CHANGES`. (#803 / PR #818)
- **Tier B corp-action handling** — CELG, S, FB→META. (#803 follow-up / PR #821)
- **`tests/test_pit_universe_discipline.py`** — allowlist + lint test enforcing T10 migration.
- **Smoke backtest tool** (`scripts/smoke_backtest.py`) — operator-runnable PIT validation.
- **Test baseline** lifted from 3671 → 3682 (T10 regression-locks +11). CI floor bumped in `CLAUDE.md`.

### Fixed

- **Render Postgres compat** — `ARCIS_DB_PATH` made optional when `DATABASE_URL` is set (#768 / PR #782).
- **Schema-verify infinite loop** at watch-loop startup (#766 hotfix).
- **`src/api/cloud_app.py`** missing registry-populating imports (#807 / PR #816).

## [v0.28.0] - 2026-04-26 — Sprint 0 wave-system + 0.B-0.D consolidation

### Release summary

Post-Track-1.5 + post-PR-690 sweep. 14 wave-style PRs (Sprint 0 Wave 1a-5c) closed dashboard cockpit, status-constants, exit vocabulary lifecycle, watch-loop discipline, schema floor, local-auth surface, FRED rf wiring v2, walkforward KPIs SE, Sharpe consolidation, promotion-gate methodology, live-order verification, PIT features. Followed by Sprint 0.B-0.D triage closing ~30 silent-failure / code-hygiene / connect-db / size / method-violation findings from Round-7/7b technical audit. PM-autonomous parallel agent dispatch with worktree isolation discipline (formalized in this release after #690 N3 stash-pop incidents).

### Added

- **14 Sprint 0 Wave-X parallel-dispatch PRs** (#700-#724): frontend cockpit, status constants, shadow-trade lifecycle bugs, DB-stub paths, schema floor, watch-loop discipline, exit-vocabulary lifecycle, local-auth surface, docs+MIME+API-secret, FRED-rf-v2, Sharpe consolidation eval, promotion-gate methodology, live-order verification, PIT features. Each carried strict-rigor receipts; 5/5 stash-pop class incidents documented + recovered via `git fsck --lost-found`.
- **Worktree-per-agent dispatch pattern formalized** — `CLAUDE.md` "Parallel Agent Dispatch — Worktree Discipline" section + recovery patterns + `.env`/untracked-files limitations doc. Closes #699. (PR #734)
- **Sprint 0.B-0.D batches**: silent-failure cleanup (B2.1), code-hygiene (B2.2), connect-db wiring (B2.3 + C.1), size refactors (B2.4 + C.2 alpaca-split), method-violation fixes (B2.5), test-triage (B2.6 + C.3 + D.2), schema-infra (C.6 sync_state in-flight), code-bugs (C.5), process+versioning audit trail (C.4), connect_db hotfixes (#793).
- **`src/version.py`** — single source of truth for app version; `get_app_version()` cleanup. (#660 closure / Sprint 0.C C.4)

### Fixed

- **Render-sync `mode=full` tables** — never strip `id` column (closes #797 / PR #800).
- **PR #690 in-PR review-finding sweep continuation** — additional N3 / O-tier findings landed via the wave system.
- **Coding-skill discipline** — Planner maxTurns 6→12 + stale-base check before PR-create (#53 follow-up / PR #817). Lessons-learned baked into anti-fallacy playbook (#749).

### Decisions

- **`feedback_strict_rigor_no_handwave.md`** — operator stated "rather take a full day than hand wave" (2026-04-26). Encoded as PM memory.
- **`feedback_autopilot_origin_check.md`** — every wakeup: `git fetch origin` + `gh pr list` BEFORE dispatching, to avoid racing operator on parallel work.
- **`feedback_worktree_env_drift.md`** — agent worktrees don't carry `.env`; tests with env-var-driven deps may pass in worktree but break post-merge.

## [v0.27.1] - 2026-04-26 — PR #690 review-finding sweep + Sprint 0 Wave 1a kickoff

### Release summary

PR #690 (Track 1.5 instrumentation) merged with 27 review findings landed as in-PR fixes (5 Blockers + 8 Important + 14 Observations). Sprint 0 Wave 1a kicked off post-merge to clear the dashboard cockpit issues that survived the PR-690 sweep — F-AUTH (Rules of Hooks compliance) + F-CHANGELOG (this entry; WhatsNewPanel was still advertising v0.25.0 as latest).

### Fixed

- **F-CHANGELOG (Sprint 0 Wave 1a / PR #690 review B3):** `frontend/src/components/system/WhatsNewPanel.jsx` was still listing v0.25.0 (2026-04-18) as the most recent entry, missing the entire Track 1.5 + Round 10 + PR #690 review-sweep work. RECENT_ENTRIES refreshed to mirror the canonical CHANGELOG (this file). Regression test added: `frontend/src/components/system/WhatsNewPanel.test.jsx` asserts the top entry is current and that the rendered date reflects the latest release. `src/version.py` bumped from v0.27.0 → v0.27.1.

- **PR #690 in-PR review-finding sweep** (full list in PR #690 commit history, summarized):
  - **B1–B5 Blockers:** exit_reconciliation direction-aware semantics + named tolerance constant (O2/O3); analytics monitor route raises 500 instead of silent empty array (O8); replaced `setdefault(key, dict.get(key))` no-op with explicit assignment (O10); publicized `compute_timeout_status` + `shadow_trades.quarantined NOT NULL` migration + integration negative-path tests (O4/O7/O9); 3 services routed `[BROKER_EXCEPTION]` → `log_and_persist` (O1-redo).
  - **I1–I8 Important:** wired FRED DTB3 rf adapter into kpis + stage1 baseline (I1); promotion-gate exception logging + distinct caption (I2); Lo (2002) autocorrelation-corrected Sharpe SE (I3); split `n_spy` and `n_total` in KPI response (I4); regenerated sprint_F engine fixtures + dropped `--ignore` (I5); labeled TradeHistory rolling Sharpe as diagnostic + used Alpaca equity for projections drawdown baseline (O11/I6); Round-8.F backtick template-literal stripping anti-regression test (I7); KPI threshold pinning (I8) with decision-matrix thresholds aligned to audit-spec §3.1 (B3-A).
  - **O1–O14 Observations:** packet_writer Key Risk regex semantics + truncation marker budget (O13); _find_latest_transcript sorts by mtime not lexicographic (O6); replaced projections.py non-canonical Sharpe with `canonical_sharpe.raw_sharpe` (B5); MR_VIX_LOOKUP_FAILED warning instead of bare pass on VIX swallow (O5); route-parity value-validation tests for kpis + projections (O14); 7 test failures from post-rewrite sweep resolved.

### Decisions

- **Decision 6 — KPI traffic-light thresholds anchored to audit-spec §3.1.** Pinning tests added in `tests/api/test_kpis.py` so Stage-1/Stage-2 boundaries cannot drift silently. Rationale + thresholds documented in PR #690 B3-A commit.

## [v0.27.0] - 2026-04-25 — Track 1.5 instrumentation gap closure (post-audit, PM-autonomous dispatch)

### Release summary

Post-audit instrumentation-gap-closure track dispatched autonomously by the PM after the 2026-04-27 Trading-Readiness Audit (v0.26.0 / v0.27.0) completed. 14 rounds + 4 plugin/infra fixes across ~16 commits. All Critical + Important findings from both audit passes cleared. ~250 new tests added.

Full design decisions, hard truths, and deferred items: [`docs/audits/2026-04-27-trading-readiness/track-1.5-DECISIONS.md`](docs/audits/2026-04-27-trading-readiness/track-1.5-DECISIONS.md)

### Added

- **Track 1.5 instrumentation deliverables (B1–B9):**
  - B1: `signal_exit_price` + `exit_slippage_bps` persisted at close (`executor.py` update path)
  - B2.A: `broker_exceptions` schema table + 4 silent-swallow upgraded to writes
  - B2.B: Structured logging for 15 broker partial-swallow sites in `executor.py`
  - B2.C: Bounded retry + qty-mismatch detection (CVS regression closure)
  - B3: `exit_reason` canonical taxonomy + nightly reconciliation script
  - B4 + B8: `key_risk_assessment` + LLM-set `expected_holding_period_days` persisted at open
  - B5 + B8: Schema + executor open-path stamping for `instrumentation_version` INTEGER sentinel + `timeout_days`; `INSTRUMENTATION_VERSION_CURRENT = 3` constant; `filter_to_version` helper (`src/analytics/instrumentation.py`)
  - B6: End-to-end integration test for full instrumentation pipeline
  - B9: `llm_timeout_days` surfaced in dashboard trade ledgers

- **5-KPI hero strip** (`frontend/src/components/dashboard/KPIStrip.jsx` + `src/api/cloud_routes/kpis.py`): rf-adjusted excess Sharpe, SPY-relative Sharpe + p-value + CI, win rate, Stage-1/2 traffic light, promotion-gate vote count. Replaces Dashboard hero MetricCards.

- **`broker_exceptions` panel** (`frontend/src/components/dashboard/BrokerExceptionsPanel.jsx` + `/api/broker-exceptions` endpoint): live-trade observability for all broker partial-swallows and exception writes. Critical gap from Round 7b G1 finding.

- **Preflight gate UI echo** (Round 8 / S4): `scripts/preflight_monday.py` output now written back to Dashboard via a preflight result card. Prior state: output written to disk only, never read back.

- **Vitest infra** (`frontend/src/` test harness) + `arcis-pulse` keyframe animation (B9 cleanup).

- **`docs/instrumentation_versions.md`** (NEW): v0/v1/v2/v3 version-to-feature matrix per B5 design. Rationale for the INTEGER sentinel, analytics filter rules, cross-references to B5 design doc + executor stamping point + `filter_to_version` helper.

- **3 new sprints queued** (post-Track-1.5): (1) v0.26.3 `sections_json` widening, (2) System Index visibility audit, (3) Council impact analysis. Cohort 3 strategy redesign (T2.14b/T2.14c/T2.16b) also queued as Sprint 4.

### Changed

- **Dashboard hero replaced with canonical KPIStrip** (R1 resolved): three incompatible Sharpe formulas across four surfaces collapsed to a single canonical strip. Dashboard hero and CTOReport previously used uncanonical `mean/stdev`; only TradeHistory attribution panel used T1.03. Now the strip is the single source of truth.

- **Win-rate silent fallback removed** (R2 fixed): `Dashboard.jsx:469` previously fell back to Alpaca account API value when `shadow_service` returned null — different denominator, no quarantine filter, misleading number. Fallback removed; null → `"—"` displayed.

- **P&L source labels added** (R3 fixed): Shadow Equity and cumulative P&L chart now carry explicit source annotations so operator can see when values come from different count bases.

### Fixed

- **5 Critical findings from Round 7 technical audit** (Round 8.A):
  - C1 Monitoring history shape mismatch — backend `{snapshots: [...]}` vs frontend array expectation
  - C2/C3/C4 Local-route parity — `/ib-shadow/*`, `/strategy-detail/{type}`, `/system/index` mirrored to local FastAPI
  - C5 `RevenueProjection` live route added

- **3 deferred audit items closed in Round 8.F** (cosmetic + Important-tier findings): SPY data source label, double-prefix bug, and remaining Important catch-all items from Round 7 + 7b.

### Decisions

- **Fix-everything-technically-before-trading principle** adopted as SD#46 (2026-04-25). Supersedes Mon $100 deploy from SD#41 REVISED until Cohort 3 redesign produces a strategy with positive expected alpha. Full reasoning in `track-1.5-DECISIONS.md` Decision 1. Memory artifact: `feedback_fix_before_trade.md`.

- **5-KPI strip layout approved** with documented color rules per §3.1 Decision Matrix thresholds.

- **Mon $100 live deploy DEFERRED** until post-Cohort-3 strategy redesign. Mon AM preflight still runs as system-health check, not deploy gate. Next deploy decision happens after Cohort 3 redesign (T2.14b/T2.14c/T2.16b) produces a strategy with reason to believe in its alpha signal.

Full reasoning for all decisions: [`docs/audits/2026-04-27-trading-readiness/track-1.5-DECISIONS.md`](docs/audits/2026-04-27-trading-readiness/track-1.5-DECISIONS.md)

## [v0.26.0] - 2026-04-23 — v0.26.0 chain complete + triage bundle + overshoot root cause

### Release summary

Tag cut pre-Friday bootcamp archive (SD#42) to anchor code state for the DB cutover. Scope since v0.25.0 is too large for a patch release — this is a minor bump.

**Trading safety (critical):**
- Exit-overshoot cancel-race fix (#608/#609/#610, PR #636): `_handle_pre_exit_cancel` routes to `_close_from_broker_fill` when cancel races a fill instead of submitting another SELL. Addresses C 4/21 + AMD 4/22 root cause that survived #595.
- CVS retry loop + phantom exits (PR #595): D2 reconcile 3rd branch + D3 executor qty sync + _strip_enum enum.value normalization.
- Council fail-closed (#612, PR #636): ClaudeAuthError + CouncilUnavailableError replace silent fake 5-0 consensus from failed stubs.

**Training data:**
- Silent-failure detection (#615, PR #636): CollectionResult dataclass + Telegram alert when is_silent_failure=True. Closes 11-day blind-spot pattern 4/13-4/23.
- Missing recommendation fallback (PR #606): LEFT JOIN + COALESCE + _build_feature_input_from_trade fallback builder + skip-instead-of-degenerate-example guard.

**v0.26.0 chain (closes #530):**
- Sprint F (PR #585): spec-driven ranker + features/enrichment port with 20 byte-identity fixtures
- Sprint G/H (commit 413fd39): spec-driven packet builder + scan plumbing

**Triage bundle (PR #636 — 29 issues closed across 4 tiers):**
- Tier 3 dep-health 13-pack: #527, #544-546, #572, #587-590, #599-601, #605, #608-610, #612, #615, #616, #630
- Tier 1 observability: #613, #614, #618, #623
- Tier 2 safety one-liners: #438, #440
- Tier 4 scoped feature work: #576, #598, #622, #624

**Dashboard (PR #637, #638):**
- src/version.py single source of truth (#631-15)
- Trade open/close websocket refresh events
- 10 other UX polish items from #631


### Fixed (Sprint fix/paper-exit-qty-asymmetry — CVS retry loop + phantom exits)

Closes #591 (D2 reconcile 3rd branch) and #592 (D3 paper exit qty sync).

Three interlocking bugs surfaced by the 2026-04-21 investigation
(`docs/audit/root_cause_investigation_2026-04-21.md`) collapsed into a
single root cause: `_strip_enum` at `src/shadow_trading/alpaca_adapter.py:38`
returned UPPERCASE names instead of lowercase values from alpaca-py's
regular-Enum `OrderStatus`. Downstream executor checks at
`executor.py:1375` and `:1383` compare against lowercase sets and
silently missed every filled bracket leg. Fallback stop/target/timeout
path then dispatched `_submit_exit_order(planned_shares)` against a
position already closed server-side → phantom sell-to-open → overshoot.

CVS on 2026-04-21 added a second failure mode: a partial fill left
4 residual shares against `planned_shares=130`. Reconcile's stuck-trade
resolution only had two branches (qty<=0 or qty>0); missing branch for
`0 < qty < planned` reverted to `open` every cycle → 17+ failed sell
attempts before operator manual quarantine.

- **D2 fix (`src/shadow_trading/reconcile.py:655-700`):** added the
  `0 < alpaca_qty < planned_shares` branch. Marks
  `status='needs_manual_review'`, `exit_reason='qty_mismatch_partial_fill'`.
  Distinct reason separates qty-mismatch residuals from directional
  overshoots for cleanup tooling.
- **D3 fix (`src/shadow_trading/executor.py`):** new helper
  `_sync_exit_qty(ticker, requested_shares, broker_positions)` reuses
  the `get_all_positions` result already fetched at `:1174` (now a
  `dict[str, float]` keyed by ticker) to clip or skip exits against
  actual broker qty. Threads `broker_positions` through `_retry_exit`.
  Phantom exits (`broker_qty <= 0`) are marked `exit_pending` with
  `position_already_closed` for reconcile to finalize — no sell ever
  submitted against a closed position.
- **Upstream fix (`src/shadow_trading/alpaca_adapter.py:38-70`):**
  `_strip_enum` now returns `val.value` for `enum.Enum` instances.
  Callsite audit documented in commit 6 message — no other callers
  needed changes beyond the existing `.lower()` patterns they already
  applied (`bracket_monitor.py:75`, `_is_filled_status`, `_is_pending_status`).
- **9 new tests + 3 test updates** covering partial-fill mismatch,
  phantom-exit prevention, race with reconcile, `_strip_enum`
  normalization, and bracket leg-fill detection case-insensitivity.
  Three existing tests (`test_retry_exit_called_for_exit_failed`,
  `test_bad_timestamp_forces_timeout`, `test_exception_marks_exit_failed_not_open`)
  updated to mock broker positions so they exercise their intended paths
  rather than hitting D3's new skip branch.
- **`scripts/cleanup_overshoot_zombies_2026_04_21.py`** for operator to
  run post-deploy to close the 13 accumulated zombies (dry-run default;
  `--apply` required; idempotent; read-only Alpaca calls).

Sprint artifacts:
- Pass 1 evaluation: `docs/sprints/fix_paper_exit_qty_asymmetry_evaluation.md`
- Pass 2 research: `docs/sprints/fix_paper_exit_qty_asymmetry_research.md`

Pre-existing failures on main, NOT introduced or fixed by this sprint:
2 Sprint F byte-identity tests; `ranker.py` > 400 lines (not in
`config/known_violations.json`).

### Added (Cleanup Sprint 3 — 4 strategic-sprint spec drafts)

Four draftable-tonight specs surfaced by the 2026-04-20 audit's
"Strategic" items 1–4, landed in `docs/sprints/future/`. Zero code
changes; future-CC can Ralph-Loop each spec into its own sprint.

- **`docs/sprints/future/eval_harness_spec.md`** — wire the existing
  canary / A/B / quality-drift / leakage-detector infrastructure into
  a nightly harness that gates model promotions (300-prompt canary,
  6-dim rubric judge, composite gate, `eval_results` table). 2–3
  sprints to deliver; dependencies none.
- **`docs/sprints/future/second_strategy_evaluation_spec.md`** —
  pivoted from the prompt's 4-candidate selection to "implement the
  already-selected Strategy 2 (mean reversion) and Strategy 3
  (evolved PEAD)" because existing decision docs
  (`Strategy_2_Selection__Mean_Reversion_Wins.md`, ADR-002) already
  made the selection. Track A: Strategy 2 implementation audit.
  Track B: Strategy 3 ground-up build (4-way PEAD composite).
- **`docs/sprints/future/training_curriculum_gate_spec.md`** —
  10-criteria pre-training gate blocking training runs with
  unbalanced outcome mix (40/25/5/15) or ratio drift from the 62/38
  curated/generated target. Chains with the eval harness spec
  (post-training gate) without circular dependency. 1–2 sprints.
- **`docs/sprints/future/containerization_spec.md`** — move training
  subsystem to WSL2 (alone first, Docker later) to eliminate cp1252
  issues that cost three subsystems tonight. Watch loop stays
  Windows-native per NSSM integration. 1–2 sprints.

Pass-1 evaluation + Pass-2 research docs in
`docs/sprints/cleanup_sprint_3_evaluation.md` and
`cleanup_sprint_3_research.md` record the scope pivots for Spec 1
(infra exists, not greenfield) and Spec 2 (decisions already made).

---

### Added (Cleanup Sprint 2 — Track A DB reconciliation script)

`scripts/reconcile_2026_04_20.py` — one-shot DB reconciliation for the
19 broken-state shadow_trades rows + 1 stale model_versions row
surfaced by the 2026-04-20 live-state analysis. Author-only in this
PR; the operator runs it after Alpaca fills confirm zero-short state.

- 12 trades (9 CLOSE_AT_OPEN incl GS + 3 NEEDS_OPERATOR_JUDGMENT) →
  `status='closed'`, `exit_reason='manual_reconcile'`.
- 7 trades (4 stale exit_failed + 3 open-row phantoms) →
  `status='exit_abandoned'`, `exit_reason='phantom_row_cleanup'`.
- TGT #12 broker-tag corrected `ib → alpaca` (position was on Alpaca).
- `model_versions.arcis:v1.0.0` → `status='active'` after three-way
  reconciliation (Ollama + config agree it is operational).

Safeguards: kill-switch pre-flight (exit 2), Alpaca pre-flight for
zero shorts (exit 3), single atomic transaction, post-update count
verification with rollback (exit 4), idempotent re-runs skip resolved
rows. Structured audit log appended to
`docs/audit/reconcile_2026_04_20_execution.log`. 5 regression tests
(`tests/scripts/test_reconcile_2026_04_20.py`).

### Changed (Cleanup Sprint 2 — `bootcamp.max_packets_per_scan` 20 → 8)

`config/settings.local.yaml:103` (gitignored — operator-local value).
Post-reconciliation BP (~$100-200K) comfortably fits 8 × ~$15.5K = $124K.
20-cap produced 11 BP-rejections 2026-04-20 because 20 × $15.5K =
$310K exceeded the $6,982 BP. Matches `settings.example.yaml:455`
default. **Operator must manually verify their local
`config/settings.local.yaml` contains `max_packets_per_scan: 8`** —
gitignored file cannot be committed.

### Fixed (Cleanup Sprint 2 — 7 medium-risk code fixes: L, K, C2-partial, H4, H5, H7, L5)

Seven independent code fixes from the 2026-04-20 post-market audit.
Kill-switch engaged throughout; no order submissions, no live-state
mutations. See `docs/sprints/cleanup_sprint_2_evaluation.md` (Pass-1)
and `cleanup_sprint_2_research.md` (Pass-2) for per-item rationale.

- **L — `_scan_cycle_committed` reset on every scan entry.**
  The module-level BP-committed counter persisted across scan cycles
  because `reset_scan_cycle_committed()` was called only from
  `src/services/scan_service.py:37`. The production watch path
  (`src/scheduler/universe_scanner.py`) and the MR path
  (`src/services/mr_scan_service.py`) skipped the reset, producing
  `committed $37,942` persistence across 11 scans today. Fix: add
  `reset_scan_cycle_committed()` at the top of both scan entries.
  4 regression tests including a static guard that fails CI if any
  scan-entry module loses the reset call.
- **K — pre-LLM BP check in scan entry paths.**
  New helpers `_check_paper_buying_power_allocation(allocation)` and
  `_record_bp_rejection_pre_llm(packet)` in executor.py. Wired at
  `universe_scanner.py:202`, `scan_service.py:169`, and
  `mr_scan_service.py:117` — before `enhance_packet_with_llm`. Saves
  ~17s of Ollama compute per un-fundable ticker (11 AVGO retries
  today = ~3 min wasted). Fail-closed on account-fetch errors. Does
  not increment `_scan_cycle_committed` (authoritative gate stays at
  `executor.py:598`). 7 regression tests.
- **C2-partial — cancel dangling orders before orphan backfill.**
  `reconcile.py:498` orphan-backfill loop now calls
  `cancel_orders_for_ticker` before `insert_shadow_trade`, matching
  the existing stale-close path at `:546` (fix #356). Prevents
  stale bracket legs from firing a duplicate sell after backfill
  (the exit-overshoot pattern behind today's 12 shorts). 2
  regression tests.
- **H4 — governor-disabled critical alert.**
  `risk/governor.py` — when `enabled=False`, `check_trade` now fires
  one `logger.critical` + one Telegram alert per process lifetime
  (module-level sentinel prevents per-check spam). Alert message
  names the config key to edit (`risk_governor.enabled`). Prevents a
  silent governance bypass from a config flip. 5 regression tests.
- **H5 — traffic-light credit classifier `int+str` TypeError.**
  `macro_snapshots.value` is stored as SQLite TEXT (SQLite type
  affinity allows str INSERTs into REAL columns). `sum(values)` of
  str raised `TypeError` (26 warnings today, silently disabling the
  credit-spread regime input). Fix: parse each value via `float()`
  with try/except skip; require 20 parseable values post-filter.
  5 regression tests.
- **H7 — bare `sqlite3.connect()` → `connect_db()` in reconcile.py.**
  7 call sites swapped. Promotes `busy_timeout` from the 5-second
  default to the canonical 30 seconds and adds `row_factory=Row`.
  Matches CLAUDE.md rule for all SQLite connections. connect_db does
  **not** apply `PRAGMA foreign_keys` or WAL (Pass-2 research
  correction) — FK enforcement remains a separate follow-up. 4
  regression tests including an integration test that a second
  writer waits rather than failing immediately.
- **L5 — EOD report format-string `Unknown format code 'f'` crash.**
  `reports.py:399-407` now casts `pnl_dollars` and `pnl_pct` to
  `float()` before passing into `notify_eod_report`'s `{:+.2f}`
  f-strings. Fixes the 4 EOD failures observed on 04-14/04-15/04-16/04-17.
  3 regression tests. Upstream writer storing TEXT remains a separate
  data-layer bug.

### Deferred to dedicated sprints

- **H8** — `activity_log.id` needs `PRIMARY KEY AUTOINCREMENT` —
  schema migration tracked in issue #580.
- **AAPL 24-day stop=0/target=0** — backfill-default root cause
  investigation tracked in issue #581.
- **Model registry archaeology** — `arcis:v1.0.0` rollback audit
  tracked in issue #582.

---

### Fixed (Cleanup Sprint 1 — critical-path code fixes: C3, H6, H3.b)

Three independent zero-live-state fixes surfaced by the 2026-04-20 log
audit (see `docs/sprints/cleanup_sprint_1_evaluation.md` and
`cleanup_sprint_1_research.md`). Kill-switch stayed engaged throughout;
no trading-path, governor, or model-registry changes.

- **C3 — reconcile dispatch `db_path=None` TypeError.**
  `src/scheduler/watch.py:694` calls `reconcile_all_paper_trades()` with
  no `db_path` kwarg; the `None` default propagated through
  `get_strategies_by_status` to `sqlite3.connect(None)` and raised
  TypeError. Intra-day reconciliation failed 13× today and has been
  silently failing every 30-min scan cycle. Added None-guards at both
  call sites (`src/shadow_trading/reconcile_dispatch.py`,
  `src/platform/promotion.py:489`) that resolve `None` to the config
  `DB_PATH`. 5 regression tests in
  `tests/shadow_trading/test_reconcile_dispatch_db_path.py`.
- **H6 — cp1252 Unicode crash in overnight reconciliation log.**
  Windows StreamHandler could not encode `❌` (U+274C) when emitted via
  `logger.info("[WATCH] %s", msg)` on line 67 (source on line 65);
  10 logger crashes today. Replaced `❌`/`✅`/`—` in logger/print/msg
  paths with `[FAIL]`/`[OK]`/`--`. Preserved emojis in Telegram-only
  paths (Telegram renders UTF-8 natively). Preserved em dashes in
  docstrings and comments (never reach an emittable stream). 5
  regression tests in `tests/scheduler/test_overnight_encoding.py`
  including a cp1252 round-trip and a static scan that fails if any
  logger/print/msg line contains cp1252-incompatible bytes.
- **H3.b — `trl` version pin.** Pinned `trl>=0.12,<0.25` in
  `requirements-training.txt`. Unbounded upper resolved to trl 1.1.0
  which ships `chat_templates/gptoss.jinja` read via `Path.read_text()`
  without an explicit encoding; on Windows that raised
  UnicodeDecodeError, killing `SFTTrainer` import and silently breaking
  overnight fine-tune for approximately one week. Pin is compatible
  with co-pinned `transformers>=4.46` and `accelerate>=1.0`.

Operator follow-up (not in sprint scope):
- Add `PYTHONUTF8=1` to the watch-loop NSSM service environment.
- `pip install -r requirements-training.txt` on the training host to
  downgrade `trl` to the 0.12–0.24 window.
- Investigate what caused remote `main` to be fast-forwarded to this
  sprint's tip without a PR (see `audit/2026-04-21` branch for the
  automated audit commit preserved from the incident).

---

### Added (2024 OHLCV backfill for Sprint F byte-identity fuzz)

Closes #570. Unblocks Sprint F (#564) byte-identity fuzz. Populates
`data/simulation_cache/` with 2023-01-01..2024-12-31 daily OHLCV for
the S&P 100 universe + SPY + ^VIX = **104 tickers, 501 trading days
each**. All 11 Sprint F fuzz/primary dates (2024-01-16 through
2024-11-19, primary 2024-03-26) have exact-match data.

**Date range is 24 months, not calendar-year 2024**, because
`compute_features` requires SMA200 (200 trading days) and RS-6m
(126 trading days) of lookback before the earliest fuzz date. A
calendar-year-2024 fetch would have broken feature computation on
the first 7 of 11 fuzz dates — confusing `SMA200 NaN` failures
attributable to data setup rather than the port. The extra 6 months
of 2023 data costs ~2 MB and ~1 minute of runtime.

**SPY is included** (not just "S&P 100 universe + ^VIX"): `rank_universe`
uses SPY for `_classify_relative_strength` (the 1m/3m/6m RS calculations
that feed `relative_strength_state`). SPY is a functional prerequisite
for the scan pipeline, not universe expansion. `^VIX` is required by
`compute_market_regime` for the `vix_proxy` volatility classification.

**New script:** `scripts/backfill_2024_ohlcv.py` (throwaway; kept
committed for re-runnability). Reuses `src/simulation/cache.py::fetch_cached_ohlcv`
— no new fetch abstractions (prompt anti-goal). Per-call parquet save
(crash-safe), cache-hit skip on re-run (idempotent).

**Results:**
- 104 of 104 tickers succeeded (0 failures)
- Runtime 83.1 seconds (under the 3-minute Pass 1 estimate)
- 4 Pass-1-flagged tickers (PYPL, F, GM, KHC) all fetched cleanly —
  none are delisted; S&P 100 membership-staleness remains an open
  observation but no new issue filed per operator direction (only
  file if >1 actually fails, which they didn't)
- 8 pre-existing scenario-partial parquets (different cache keys)
  preserved untouched as designed
- BRK.B → `BRK_B_...` filename translation verified via
  `to_yfinance_ticker()`; hyphen/dot handling clean

**Re-run:** `python scripts/backfill_2024_ohlcv.py` is idempotent —
skips cached files, re-fetches only missing ones. If any parquet is
known-bad, delete it before re-running.

---

### Fixed (Sprint C.1 — schema refinement: scoring shape gaps)

Closes #569, #567, #568 — slot 6-a in the #530 Sprint chain (chain count
revised 8→9; F/G/H shift to slots 7/8/9). Sprint F Pass 1 (see
`docs/sprints/sprint_F_evaluation.md` on `feat/port-ranker-to-spec`,
parked at `53dee07`) surfaced 9 schema shape gaps blocking byte-identity
port of the ranker; Sprint C.1 closes them before Sprint F resumes.

**9 items:**

1. **Categorical bands** — `ranking.bands` accepts `category: <str>` as
   an alternative to `range: [lo, hi]`. Mutual exclusion. Covers
   `trend_state` / `relative_strength_state` in `_score_ticker`.
2. **Compound AND conditions** — band entries may use `conditions:
   [{metric, operator, threshold}, ...]` instead of a top-level metric.
   Covers `iv_rank > 75 AND pc_vol > 1.2`. Operator enum
   `{>, >=, <, <=, ==, !=}`.
3. **Weighted blend groups** — bands accept optional `weight: float
   [0,1]` + `blend_group: <str>` for weighted sums across tagged bands.
   Covers the 0.6/0.4 market-vs-sector RS blend. Weights within a group
   should sum to 1.0 (warn if not).
4. **`ranking.adjustments` block** — new block with same grammar as
   `ranking.bands` plus `clamp: [lo, hi]`. Covers `_regime_adjustment`
   (ranker.py:72-102).
5. **`ranking.derived_metrics` block** — declarative feature derivations.
   Ops: `subtract`, `weighted_sum`. DAG cycle check. Covers
   `_compute_sector_rs` (ranker.py:105-147).
6. **#567 — `packet_worthy` → `min_score` hard-rename.** Schema validator
   previously asserted bool; runtime stored int threshold. Field is now
   `min_score: int` in `[0, 100]`. No legacy alias.
7. **#568 — `KNOWN_POST_SCAN_HELPERS` contents + strict flip.** Set
   aligned to runtime dispatch names `{traffic_light, event_risk}`;
   `post_scan.chain` flipped to `strict=True`.
8. **`KNOWN_SCORING_METRICS` registry.** 10-metric seed for
   `_validate_bands` / `_validate_band_condition`. Effective set at
   validation = seed ∪ derived-metric names from Item 5.
9. **Event-risk casing docstring (Item 9).** Schema comment codifies the
   lowercase_with_underscores convention. No runtime edits — Option 9A
   per operator resolution 2026-04-20.

**Registry additions:**

- `KNOWN_REGIME_LABELS` — 5-label set from `compute_market_regime()`
  (regime.py:161-170). Intentionally separate from `KNOWN_REGIME_KEYS`
  (7-label, threshold dispatch). Documented with comment explaining
  the split.
- `KNOWN_SCORING_METRICS` — 10-metric seed from `_score_ticker` +
  `_regime_adjustment`. Additions require a refinement sprint
  (C.1-style) — silent edits risk schema/runtime scoring drift.
- `ALLOWED_BAND_OPERATORS`, `ALLOWED_DERIVED_OPS` — operator enums.

**Structure:**

- Ranking validators extracted to `src/platform/_strategy_spec_ranking.py`
  (341 LOC) to keep `strategy_spec.py` focused and under guardrail. Main
  module re-exports the constants for public API stability.
- `strategy_spec.py`: 393 → 388 lines (under 650 guardrail).
- `tests/platform/specs/test_schema_c1_refinements.py`: 28 tests covering
  all 9 items + backward compat + registry seeds.

**Known Sprint F divergence (operator resolution 2026-04-20):** the
sector_rs None-fallback in `_score_ticker:182-187` (market gets weight
1.0 when sector data absent) is NOT expressible in pure weighted-blend
schema. Sprint F will observe byte-identity fuzz failure → STOP → file
issue for a follow-on sprint (C.2-style) if the fallback matters.

**Follow-up candidates for Sprint F or C.2:** symmetric categorical-value
validation for non-regime metrics (`trend_state`, `relative_strength_state`,
`market_breadth_label`) — each ~10 LOC. Deferred because immediate scope
is `regime_label` per operator. Sprint F may surface additional gaps
that get bundled.

**Sprint F unblocks:** once #569 merges AND #570 (2024 OHLCV data gap)
resolves, `feat/port-ranker-to-spec` (parked at `53dee07`) resumes as
Sprint F at slot 7 of 9.

---

### Added (Sprint E — hooks, enrichment, post-scan, event-risk, bootcamp schema)

Closes #551 — fifth of 8 prerequisite sprints in the #530 Sprint chain
(Sprints A #494, B #493, C #549, D #550 merged earlier). **Sprint E
completes the v0.26.0 schema surface**; the next two sprints (F, G) port
the runtime (`compute_all_features`, `rank_universe`, bracket engine) to
consume the declared spec instead of hardcoded logic.

`src/platform/strategy_spec.py::validate_spec` now validates five
additive optional top-level blocks:

```yaml
hooks:                           # attribution logger refs (strict)
  attribution:
    - log_before_llm
    - log_after_llm

enrichment:                      # ordered enricher chain (warn)
  chain:
    - technicals
    - insider
    - macro
    - news
    - sector

post_scan:                       # ordered post-ranking helpers (warn)
  chain:
    - classifier
    - filter_duplicates

event_risk:                      # category-based quarantine gate (warn)
  quarantine_categories:
    - earnings_imminent
    - fomc

bootcamp:                        # strategy-level bootcamp overrides (strict)
  qualification_threshold: 55
  watchlist_threshold: 30
  max_positions: 20
  traffic_light_floor: 0.5
```

Per-block policy — strict-vs-warn chosen by registry maturity
(documented in `docs/sprints/schema_final_blocks_evaluation.md §2`):

| Block | Policy | Registry source | Reason |
|-------|--------|-----------------|--------|
| `hooks.attribution` | **strict** | `src/attribution/logger.py` (2 stable functions) | Typo silently disables attribution — 2-year-old code, capability-registry-registered. |
| `enrichment.chain` | warn | no formal registry yet | Sprint prompt names aspirational; Sprint F wires the registry. |
| `post_scan.chain` | warn | no registry exists | Same; runtime binding deferred. |
| `event_risk.quarantine_categories` | warn | fragmented (`MACRO_EVENT_TYPES` + `KNOWN_EVENTS` labels) | 20-seed-entry union of current category sources; sprint-prompt earnings names aren't in code yet. |
| `bootcamp` | **strict** | `config/settings.example.yaml:435-457` | 4 keys load-bearing at 7 runtime sites; typo silently reverts to hardcoded default. |

Validation rules (strict blocks):

- **`hooks.attribution`** — list of string refs; each must be in
  `KNOWN_ATTRIBUTION_HOOKS = {log_before_llm, log_after_llm}`.
- **`bootcamp`** — dict; allowed keys are
  `{qualification_threshold, watchlist_threshold, max_positions,
  traffic_light_floor}`. Per-key type check: thresholds are int in
  `[0, 100]`, `max_positions` is a positive int (bool excluded),
  `traffic_light_floor` is a number in `[0.0, 1.0]`.

Validation rules (warn blocks): unknown refs emit
`logger.warning("[PLATFORM] %s[%d]: unknown ref %r (known: ...)")` but
do not block the spec load. Matches the Sprint C/D precedent
(ranking.bands overlap, regime-key unknowns).

Added constants and helpers in `strategy_spec.py`:

- `KNOWN_ATTRIBUTION_HOOKS`, `KNOWN_ENRICHERS`,
  `KNOWN_POST_SCAN_HELPERS`, `KNOWN_EVENT_RISK_CATEGORIES` (20 entries),
  `KNOWN_BOOTCAMP_KEYS` (all module-level frozensets).
- `_LIST_BLOCKS` dispatch tuple — single loop handles the 4
  list-of-refs blocks (hooks, enrichment, post_scan, event_risk).
- `_validate_known_ref_list(items, known, path, errors, *, strict)` —
  shared helper factoring the common shape out of four dispatch sites.
- `_validate_bootcamp_overrides(block, errors)` + `_BOOTCAMP_RULES`
  table-driven per-key type checks.

Guardrails:

- **Schema-only.** `StrategySpec` dataclass unchanged; new blocks land
  in `.raw`. Downstream consumers pick them up from `.raw` without
  modification. Reproducibility hash at `backtest_engine.py:187`
  captures the new blocks (intentional; same precedent as Sprint C/D).
- **Zero top-level key collision.** `{hooks, enrichment, post_scan,
  event_risk, bootcamp}` appear in neither `lazy_prices_v1.yaml` nor
  `post_audit_ruleset_v1.yaml`; existing `attribution` top-level key
  is in a separate namespace from `hooks.attribution`.
- **File-size budget preserved.** `strategy_spec.py` grew from 298 to
  393 lines — under the 400-line cap set by the sprint prompt.

Tests — `tests/platform/specs/test_schema_final_blocks.py` (25 tests):

- 2 tests per block × 5 blocks = 10 (prompt minimum).
- +5 combined / backward-compat (all-5-simultaneously, lazy_prices_v1,
  post_audit_ruleset_v1, none-declared, non-dict outer ignored).
- +5 edge cases (empty list, not-a-list, non-string entry, bootcamp
  not-a-dict, all-outer-dicts-empty).
- +5 bootcamp-specific (threshold range, bool-is-int trap, floor
  range, floor valid, watchlist valid).

Platform test count: 447 → 470 (23 new + 2 new skipped = 25 additive).

Documentation:

- `docs/sprints/schema_final_blocks_evaluation.md` — Pass 1 per-block
  registry-source discovery, strict-vs-warn decision matrix, test plan.
- `docs/sprints/schema_final_blocks_research.md` — Pass 2 verification
  of the 7 Pass-1 assumptions (attribution module location, bootcamp
  consumers, top-level key collisions, spec.raw consumers, event-risk
  seed byte-match, file-size budget, test count floor).

Next: Sprint F (ranker port — `compute_all_features` + `rank_universe`
consume spec instead of hardcoded logic).

### Added (Sprint D — multi-target brackets + regime-adaptive sizing schema)

Closes #550 — fourth of 8 prerequisite sprints in the #530 Sprint chain
(Sprints A #494, B #493, C #549 merged earlier).

`src/platform/strategy_spec.py::validate_spec` now validates two additive
schema blocks — a list-form `exit.targets[]` alternative to the legacy
singular `exit.target`, and a `position_sizing.method: regime_adaptive`
option alongside the existing `fixed_pct_equity`.

Accepted shapes:

```yaml
exit:
  kind: mechanical
  timeout_days: 21
  stop:
    atr_multiple: 2.0                # required when using targets[]
  targets:                           # list-form; alternative to exit.target
    - name: target_1
      atr_multiple: 1.5
    - name: target_2
      atr_multiple: 3.0

position_sizing:
  method: regime_adaptive
  regimes:
    BULL_LOW_VOL:     {packet_worthy: true,  position_pct: 0.05}
    CRISIS:           {packet_worthy: false, position_pct: 0.0}
```

Validation rules:

- **Brackets XOR.** When `exit.kind == "mechanical"`, exactly one of
  `exit.target` (legacy singular) or `exit.targets` (new plural) is
  required. Both is rejected; neither is rejected. `exit.kind ==
  "python_plugin"` passes through without either (plugin owns brackets).
- **`exit.targets[]` interior.** Non-empty list; each entry has a
  non-empty string `name` (unique across the list) plus a numeric
  `atr_multiple > 0`. Bool values rejected (isinstance-True-is-int trap).
- **`exit.stop.atr_multiple`.** Required when `exit.targets` is used;
  legacy `exit.target` path leaves `exit.stop` uninspected (rich
  `{method, atr_period, multiplier, floor_pct, cap_pct}` shape passes
  through unchanged).
- **`position_sizing.method`.** Restricted to `fixed_pct_equity` or
  `regime_adaptive`. `fixed_pct_equity` interior (`pct`,
  `max_concurrent`) passes through unvalidated.
- **`regime_adaptive.regimes`.** Non-empty dict. Each entry requires
  `packet_worthy: bool` + `position_pct: float` in [0.0, 1.0]. Unknown
  regime keys warn via `logger.warning` but do not reject — the known
  set is the incumbent 7-label `classify_regime`/`REGIME_THRESHOLDS`
  codomain (`BULL_LOW_VOL`, `BULL_HIGH_VOL`, `TRANSITION`, `CORRECTION`,
  `BEAR_EARLY`, `BEAR_ESTABLISHED`, `CRISIS`).

**Schema-only sprint — no runtime consumption.** Sprints F (ranker
port) and G (exit/bracket port) consume these blocks. `strategy_spec.py`
grew from 195 → 298 lines (under the 300-line C+D combined budget). New
tests: `tests/platform/specs/test_schema_brackets_sizing.py` (29 tests)
cover every rejection path, unknown-regime-key warn semantics, duplicate
target names, bool/negative/zero `atr_multiple`, and backward compat on
both shipping specs (`lazy_prices_v1` + `post_audit_ruleset_v1`).

**Backward compat.** Zero production YAML changes — both
`src/platform/specs/*.yaml` use the legacy `exit.target` +
`fixed_pct_equity` shapes (2/2 each, grep-verified in Pass 2). Three
test-helper fixtures that used bare `exit: {kind: mechanical}` without
targets were updated to `exit: {kind: python_plugin}` (tests don't
exercise brackets); commented inline.

**Housekeeping.** `config/known_violations.json` grandfathers
`src/platform/signal_eval.py` (450 lines) — grew past the 400-line cap
in Sprint B (#556) but wasn't added to the oversized list at merge;
surfaced by `tests/test_repo_structure.py::test_no_file_over_400_lines`
after pulling main into the sprint branch.

### Added (Sprint C — scoring-DSL schema block)

Closes #549 — third of 8 prerequisite sprints in the #530 Sprint chain
(Sprints A #494 and B #493 merged earlier).

`src/platform/strategy_spec.py::validate_spec` now validates an optional
`ranking.bands` block — a declarative scoring DSL that the Sprint F ranker
port will consume in place of the hardcoded bands in
`src/ranking/ranker.py::_score_ticker`.

Accepted shape:

```yaml
ranking:
  bands:
    - metric: pullback_depth_pct   # non-empty str
      range: [-8, -3]              # 2-element numeric list, lower < upper
      score: 25                    # int or float
```

Validation rules:

- `ranking` is an optional top-level key; specs without it load unchanged
  (`lazy_prices_v1` and `post_audit_ruleset_v1` regression-tested).
- `ranking.bands` is optional inside `ranking`; other sub-keys (e.g.
  hypothetical `ranking.weights`) pass through unchecked.
- Each band must provide a non-empty string `metric`, a 2-element numeric
  `range` with `range[0] < range[1]`, and a numeric `score`. Bool values
  are explicitly rejected (Python's `isinstance(True, int)` trap).
- Multiple bands per metric are allowed. Overlapping ranges on the same
  metric emit a `[PLATFORM] ranking.bands overlap: ...` warning via
  `logger.warning` — the spec still validates successfully. `validate_spec`'s
  `(ok, errors)` return signature is preserved; no callers break.

**Schema-only sprint — no runtime consumption.** Sprint F ports the ranker
to consume this block. `strategy_spec.py` grew from 131 → 195 lines (under
the 250-line sprint cap). New tests:
`tests/platform/specs/test_schema_scoring_dsl.py` (23 tests) cover every
rejection path, overlap-warn semantics, backward compat on both shipping
specs, and the `ranking.weights` pass-through case.

### Validated (v0.25.6 — lazy_prices_v1 walk-forward rerun on real EDGAR)

Closes #547. First walk-forward rerun after three upstream capabilities landed
(v0.25.4 VIX enrichment #535, v0.25.4 INCONCLUSIVE_DURATION sub-state #538,
v0.25.5 sections_json parser backfill #537). Spec, seed, and universe
unchanged from the v0.25.3 baseline (`docs/validation/lazy-prices-v1-walkforward-real-2026-04-19.md`).

**Run identity**

- `run_id`: `7a8a96b6-3d3d-4cc3-9e6f-34573547cc72`
- `spec_hash`: `ea78fed32a6ff7b3169e1657988392075677885280a22e800dfadd07c62b9e15` (identical to v0.25.3)
- `code_git_sha`: `638ef96912fa6338d88fd380b6d2328377a06d83`
- `random_seed`: `42`
- Exit code: 3 (INCONCLUSIVE)

**Outcome delta (v0.25.3 → v0.25.6)**

| metric | v0.25.3 | v0.25.6 |
|---|---|---|
| outcome_state | INCONCLUSIVE | INCONCLUSIVE |
| Windows (PASS/FAIL/INC_DATA/INC_POWER/INC_DURATION) | 0/0/5/0/— | 0/0/4/0/**1** |
| vix_tier_coverage | 0 | **3** |
| OOS trades with vix_at_entry non-NULL | 0/20 | 21/21 |
| Total OOS trades | 20 | 21 |
| Pooled Sharpe | 3.5280 | 3.8976 |
| Pooled MDE | 10.5448 | 10.2932 |

**Confirmations closed**

- **#535 (VIX enrichment):** `vix_at_entry` populated on 100% of OOS trades
  across 3 tiers (low/medium/high). `lookup_vix_at_entry` wired end-to-end
  via `_build_trade()`. Closes v0.25.3 §Follow-ups #1.
- **#538 (window-duration sub-state):** Window 4 (273 days < 365 threshold)
  correctly flips to `INCONCLUSIVE_DURATION` regardless of trade count.
  Persisted `n_windows_inconclusive_duration = 1`. Closes v0.25.3 §Follow-ups #3.

**Parser backfill impact observation**

v0.25.5's lift from 28% → 71% useful `sections_json` coverage produced **+1
new OOS trade** (PG 2024-08-06 in Window 4). Windows 0-3 trade counts
identical to v0.25.3. Pre-registered rule R3 predicted 2-6× lift; observed
delta is well below that. Candidate reasons (not in scope): #552 fetcher issue
still produces `'{}'` on 1,424 rows; prior-year reference filings pre-2019
are not in the corpus; 8-K filings (69% of the v0.25.5 backlog) don't trigger
`lazy_prices` signals. Captured, not interpreted — the framework reports the
number it got.

**Framework-bug triggers**

Inert. All triggers are PASS-conditional; outcome was INCONCLUSIVE. No
framework-bug issue filed.

**Minor follow-up flagged (not filed)**

`scripts/backtest/run_walkforward.py::main()` JSON summary omits
`n_windows_inconclusive_duration` — the persisted DB row carries it but the
CLI stdout doesn't. One-line fix in the `summary` dict. Not bundled into this
PR per the sprint's anti-goal (no spec/runner modification during validation).

**Docs**

- Pass 1 evaluation: `docs/sprints/v0.25.6_evaluation.md` (commit `638ef96`)
- Pass 2 raw capture: `docs/sprints/lazy_prices_v1_rerun_raw.md` (commit `2ca4b36`)
- Pass 3 validation: `docs/validation/lazy-prices-v1-walkforward-real-rerun-2026-04-20.md` (this PR)
### Fixed (Sprint B — python_plugin find_candidates_for_date wiring)

Closes #493, #548 — second of 8 prerequisite sprints in the #530 Sprint
chain (Sprint A, #494 scheduled-kind, merged earlier in this chain).

`src/platform/signal_eval.py::find_candidates_for_date` previously raised
`NotImplementedError` for `entry.kind: python_plugin`, blocking any strategy
declaring itself via the `StrategyPlugin` ABC from running through the live
scan pipeline. The new `_find_candidates_python_plugin` branch:

- resolves universe via `_resolve_universe`; applies `spec.universe.sector_filter`
  (identical plumbing to Sprint A's scheduled path);
- applies `entry.event_exclusion.categories` on the as_of date — short-circuits
  BEFORE dispatching to the plugin, so the plugin isn't needlessly invoked on
  excluded days;
- looks up the plugin via `plugin_registry.get_plugin(entry.plugin_ref or spec.strategy_id)`.
  `entry.plugin_ref` is a new **optional** dict key (NO schema change — not
  validated in `strategy_spec.py`); when absent, the plugin key defaults to
  the spec's own `strategy_id`;
- passes `{"db_path": live_db, "strategy_id": spec.strategy_id}` as the plugin
  `context` arg per the existing `StrategyPlugin.find_candidates` signature;
- translates returned `Candidate` dataclass objects into the shadow_harness
  dict shape, augmenting metadata with `strategy_spec_hash`, `trigger`
  (`"python_plugin"`), `signal_direction`, `plugin_ref`. Plugin-supplied
  metadata keys are preserved;
- dedupes against open `shadow_trades` on desk `research_<strategy_id>`.

Error handling (no new exception classes per sprint guardrail):

- Missing plugin → `KeyError` with `plugin_ref` + hint to check `@register_plugin`.
- Plugin's `find_candidates` raises → `RuntimeError` wrapping original via
  `raise ... from exc`; plugin name in the message.
- Plugin returns non-list → `TypeError` with the actual type.
- Plugin returns non-`Candidate` items → `TypeError` per-item with the actual
  type. All three are caught by `shadow_harness._find_candidates`' broad
  `except Exception`; tick degrades to 0 candidates.

New tests in `tests/platform/test_signal_eval_python_plugin.py` (13 tests)
cover: dispatch on spec.strategy_id, `entry.plugin_ref` override, missing
plugin / raising plugin / bad return type / wrong item type, dedup, sector
filter narrowing the universe received by the plugin, event_exclusion
short-circuit (plugin NOT called), empty universe short-circuit (plugin NOT
called), plugin context delivery, walk-forward path still raises
`NotImplementedError` (backtest_engine untouched), scheduled + event_driven
branches still dispatch correctly.

`backtest_engine._run_backtest` still raises `NotImplementedError` for
`python_plugin` kind — historical replay for plugin strategies is explicitly
out of this sprint's scope (tracked in the #530 chain). Walk-forward runner,
which routes scheduled/event_driven/python_plugin through `run_backtest`,
is untouched.

`src/platform/signal_eval.py` grew from 399 → 450 lines; at the sprint's
450-line cap.

### Executed (v0.25.5 — sections_json parser backfill for EDGAR)

Closes #537. Runs the existing section parser over the 3,743 `edgar_filings`
rows that had `full_text` populated by the 2026-04-19 fulltext backfill but
`sections_json` still NULL. Pure execution sprint — no parser logic changes,
no schema changes.

**Coverage delta**

- Useful (`sections_json` non-empty): 1,518 / 5,393 = 28.1% → 3,837 / 5,393 = **71.1%**
- Attempted (`sections_json IS NOT NULL`): 28.1% → **97.6%**

Remaining 132 NULL rows are all `full_text IS NULL` (ineligible).

**Execution**

3,743 rows processed in 6.1 s total wall-clock (plan budgeted 2 h). Batch
commits every 100 rows, zero exceptions, zero baseline drift against a
5-row spot-check of pre-parsed rows.

- 2,319 rows produced non-empty `sections_json`
- 1,424 rows produced `'{}'` (mark-attempted semantic — see #552)
- 0 exceptions

**Code changes**

- `_parse_sections` → public `parse_sections` in
  `src/data_collection/edgar_collector.py`. Callsites updated in
  `scripts/backfill_edgar_historical.py` and `tests/test_data_collectors.py`.
  No behavioral change.
- New `scripts/backfill_sections_json.py` (205 lines, all functions ≤ 48 lines,
  well under the 60-line guardrail). Flags: `--dry-run`, `--limit`,
  `--batch-size`, `--db-path`. Built-in `capture_baseline`/`verify_baseline`
  defense-in-depth against WHERE-clause drift.
- Storage semantic: empty parser dict stored as `'{}'` literal JSON, NOT NULL.
  One-way divergence from `edgar_collector.py:351` (inline collector path).
  Chosen for idempotency on re-run and diagnostic value for #552.

**Follow-up filed (#552)**

1,424 of the 3,743 rows (~38%) produced empty `sections_json`. Diagnosed
via spot-inspection: `_lookup_primary_document` is resolving some filings
to iXBRL / SGML submission-header documents instead of the narrative HTML.
Parser correctly returns `{}` on these — no narrative sections exist to
extract. Filed as **#552** for a later sprint; out of scope for v0.25.5.

**Docs**

- Pass 1 evaluation: `docs/sprints/v0.25.5_evaluation.md` (commit `c495530`)
- Pass 2 research: `docs/sprints/v0.25.5_research.md` (commit `6a8f290`)
- Pass 3 validation: `docs/sprints/v0.25.5_validation.md` (this PR)
### Fixed (Sprint A — scheduled-kind find_candidates_for_date wiring)

Closes #494 — first of 8 prerequisite sprints in the #530 Sprint A chain
unblocking v0.26.0 incumbent YAML extraction (#523).

`src/platform/signal_eval.py::find_candidates_for_date` previously warned
and returned `[]` for `entry.kind: scheduled`, blocking any scheduled
strategy spec from running through the live scan pipeline. The new
`_find_candidates_scheduled` branch:

- resolves the universe via `_resolve_universe` (honors string aliases like
  `"sp100"`, unlike `backtest_engine._run_scheduled` which short-circuits on
  non-list inputs);
- applies `spec.universe.sector_filter` (v0.26.2-scoped) via `SECTOR_MAP`;
- fires when `_matches_scheduled_trigger(as_of, entry)` is True
  (shared with the backtest path — no behavior fork);
- applies `entry.event_exclusion.categories` (v0.26.2-scoped) on the as_of
  date via `is_excluded_event_date`;
- dedupes against open `shadow_trades` on desk `research_<strategy_id>`;
- emits one candidate dict per qualifying ticker with
  `metadata.trigger == "scheduled"`.

`entry.signal` is intentionally ignored for the scheduled MVP path —
scheduled specs express timing via `day_of_week` today. A cron/interval DSL
is tracked for a later sprint in the #530 chain.

New tests in `tests/platform/test_signal_eval_scheduled.py` (10 tests)
cover: trigger-match emission on a fixed historical Monday (2023-11-06),
empty-filter path returning full universe, sector_filter + event_exclusion
composition, day_of_week mismatch, dedup against open positions, unknown
operator regression guard (no exception), unknown-kind ValueError, and
walk-forward-path-untouched confirmation. Two stale assertions in
`tests/platform/test_find_candidates.py` (which pinned the previous
warn-and-return-`[]` contract) were updated to the new behavior.

`src/platform/signal_eval.py` grew from 370 → 399 lines; under the sprint's
400-line file-size budget. `backtest_engine._run_scheduled` (walk-forward
path) is untouched — Pass 2 research
`docs/sprints/scheduled_kind_wiring_research.md` §3 confirms the two paths
are independent siblings sharing only the stateless `_matches_scheduled_trigger`
helper.

### Added (v0.25.4 Part A — VIX enrichment in walk-forward trades)

Closes #535 (and the umbrella #542). Plugs the gap diagnosed in
`docs/validation/lazy-prices-v1-walkforward-real-2026-04-19.md` where 20/20
OOS trades carried `vix_at_entry = NULL` because `BacktestTrade` had no such
field. The runner's `getattr(t, "vix_at_entry", None)` always returned None
and downstream tier bucketing degenerated to `vix_tier_coverage = 0`.

- New module `src/platform/vix_lookup.py` (~70 lines) with single function
  `lookup_vix_at_entry(entry_iso) -> float | None` that delegates to
  `fetch_cached_ohlcv("^VIX", ...)` and returns the most-recent Close on or
  before `entry_iso`. Returns None on cache miss, empty frame, or no eligible
  bar (graceful degradation, never raises).
- Add `vix_at_entry: float | None = None` field to `BacktestTrade` dataclass.
  Defaulted so existing constructors stay backwards-compatible.
- Wire `lookup_vix_at_entry` into `_build_trade()` — single call site reached
  by both `_run_scheduled` and `_run_event_driven` paths.

The runner picks up the new field automatically; `_assign_vix_tier` correctly
buckets into `low` (<15), `medium` (15–25), `high` (>25). Pass 1 source
decision: yfinance `^VIX` over FRED VIXCLS / `vix_term_structure` table /
non-existent `daily_bars` — the only source with full 2019-2024 daily
coverage (verified 12/12 month-starts in Pass 2) plus already wired through
the existing OHLCV cache path.

11 new tests in `tests/platform/rigor/test_vix_enrichment.py` cover helper
behavior + `BacktestTrade` shape + `_build_trade` integration via mocked
OHLCV/VIX path + end-to-end persistence through `walkforward_runner`.

### Added (v0.25.4 Part B — Window-duration surfacing)

Closes #538 (and the umbrella #542). Adds an `INCONCLUSIVE_WINDOW_DURATION`
sub-state so operators can distinguish "strategy didn't signal"
(`INCONCLUSIVE_DATA`) from "the OOS window was too short to deliver
meaningful coverage" (the new sub-state).

- New constant `WINDOW_INCONCLUSIVE_DURATION` in `walkforward_outcome.py`.
- New `n_windows_inconclusive_duration` field on `OutcomeResult` and matching
  `INTEGER DEFAULT 0` column on `walkforward_results`.
- New per-run config knob `min_window_duration_days: int = 365` on
  `WalkForwardConfig` + module-level `MIN_WINDOW_DURATION_DAYS = 365`. Round-
  trips through `as_json_dict()`. Override-able for power-testing or backport.
- `count_power_states` extended with `windows` + `min_window_duration_days`
  kwargs (both default-no-op so legacy callers stay unchanged). Per-window
  precedence: DURATION > DATA > POWER > PASS > FAIL.
- Run-level reducer: `INCONCLUSIVE_WINDOW_DURATION` ≥ inconclusive_window_threshold
  → outcome `INCONCLUSIVE / duration_inconclusive`, prepended ahead of the
  existing `coverage_inconclusive` and `power_inconclusive` checks.
- `cloud_routes/walkforward.py` SELECT extended to surface the new counter
  to API consumers. Dashboard chip surfacing is a follow-up; backwards-compat
  preserved (existing UI ignores the new column).

Pass 1 chose Option 1 (sub-state) over Option 2 (new `walkforward_windows`
table) because: (a) the `walkforward_windows` table doesn't exist — Option 2
would require creating it, vs Option 1's +1 INTEGER column; (b) sub-state
surfaces the distinction in every consumer (validation docs, promotion gate,
JSON outputs) for free; (c) Option 2 would require every consumer to apply
the threshold itself — drift waiting to happen.

Threshold = 365 days. v0.25.3 default windows are four 15-month (~456-day)
windows + one 9-month (273-day) tail window — the threshold cleanly flags
the tail without affecting the standard four. 1 calendar year is the minimum
needed to span ~1 cycle of seasonal effects.

15 new tests in `tests/platform/rigor/test_window_duration.py` cover reducer
+ classifier + config + persistence + a v0.25.3 retrofit asserting the new
sub-state fires on Window 4 while leaving the run-level outcome's
`coverage_inconclusive` reason intact (1 short window < threshold of 2).

### Added (v0.26.2-scoped — Schema extension: sector_filter + event_exclusion)

Closes #539. Two additive optional fields on the strategy spec, both read-only
filters applied at candidate-selection time (pre-ranking). Minimal and
declarative per the v0.26.2-preflight (PR #536) Path B scope.

- **`universe.sector_filter: list[str]`** — if present, filters the candidate
  ticker set to those whose `SECTOR_MAP[ticker]` (GICS name) matches any
  listed value. Applied in `src/platform/signal_eval.py:_query_event_rows`
  between universe resolution and the SQL `IN(...)` clause.
- **`entry.event_exclusion.categories: list[str]`** — if present, skips any
  entry whose resolved entry date (`filing_date + next trading day`) matches
  a v0.25.1 `KNOWN_EVENTS` row whose category is in the listed set.
  Applied in `src/platform/backtest_engine.py:_run_event_driven`.

Both fields are optional and validated in
`src/platform/strategy_spec.py:validate_spec`. Type rules: non-empty
`list[str]`; nested `entry.event_exclusion` must be a dict if present.

Preserves the v0.25.3 framework baseline and does not modify
`lazy_prices_v1.yaml`. Regression test
`test_lazy_prices_still_loads_without_new_fields` confirms.

### Added (v0.26.2-scoped — post_audit_ruleset_v1.yaml)

First non-null `derived_from` strategy on main. `source_type =
forensic_audit_ruleset`, source date range 2026-04-01 → 2026-04-18,
`source_trade_ids` key intentionally omitted per Pass 2 finding (the R8
firewall at `walkforward_firewall.py:129-135` accepts key-absence but
rejects `null`).

- `universe.sector_filter: [Consumer Staples, Utilities, Health Care]`
  (28 tickers, 28% of current S&P 100 by GICS membership)
- `entry.event_exclusion.categories: [Trade Policy]` (excludes entries on
  any of the 9 2019-2024 Trade Policy dates from v0.25.1 backfill)
- Otherwise mirrors `lazy_prices_v1.yaml` — same cosine-similarity signals
  on 10-K/10-Q sections, same ATR-based brackets, same fixed-pct sizing

### Validated (v0.26.2-scoped — Walk-forward run on real EDGAR data)

First walk-forward run of a non-null-`derived_from` spec.

- **Outcome:** `INCONCLUSIVE / coverage_inconclusive` — matches Pass 1
  hypothesis; trade count collapses to 3 (all Consumer Staples, windows
  0/2/3 one each; windows 1/4 empty).
- **Run:** `run_id=f266e097-0e19-4360-ac4a-ca1c388dda02`,
  `spec_hash=463853b5...`, `code_git_sha=6b887927...`, `seed=42`.
- **Pooled Sharpe:** +1.019 (vs v0.25.3 baseline +3.528)
- **Pooled MDE:** 47.197 (vs 10.545 baseline; ~4.5× scales as 1/√N)
- **Heavy-tail flag:** 0 (N=1 windows degenerate to MDE=inf before the
  bootstrap heuristic activates — correct behavior)
- **R8(a) persisted:** `derived_from_source_type=forensic_audit_ruleset`,
  `derived_from_source_run_id=april-2026-forensic-audit`
- **R8(b):** overlap-assertion trivially cleared (2026-04 vs 2019-2024)
- **Filter bypass trigger (new):** did NOT fire — 3 trades ≤ 20 baseline

**Schema + filters both VALIDATED.** No framework-bug investigation filed.

Per-trade ledger:
- Window 0: PM (Consumer Staples) 2020-02-10, 13d, -5.79% (stop)
- Window 2: COST (Consumer Staples) 2021-10-07, 20d, +12.84% (timeout)
- Window 3: MO (Consumer Staples) 2023-02-28, 17d, -5.00% (stop)

Validation doc:
`docs/validation/post-audit-v1-scoped-walkforward-2026-04-20.md`.
Cycle summary: `docs/validation/v0.26-cycle-summary.md`. Ralph Loop:
`docs/sprints/post_audit_v1_scoped_{evaluation,research}.md`.

**Morning-only filter (the third forensic-audit refinement)** remains
deferred to #540. Pending intraday OHLCV data layer.

**Secondary finding (non-blocking):** `vix_at_entry` / `vix_tier` NULL
on 3/3 OOS trades. Same upstream data-enrichment gap documented in the
v0.25.3 validation doc. Primary `min_trades_per_window=10` gate already
binding.
### Blocked (v0.26.0 — Incumbent YAML extraction)

Closes #523 as **BLOCKED**. See #530 for prerequisite dependency chain.

- **Pass 1 + Pass 2 findings:** 7 of 8 pre-registered blockers hold. Incumbent cannot cleanly extract to YAML without schema extensions + close of #494 + scan pipeline refactor.
- **Deliverable:** `docs/sprints/incumbent_v1_yaml_evaluation.md` (309 lines) + `docs/sprints/incumbent_v1_yaml_research.md` (261 lines).
- **Docs-only ship** per prompt's explicit STOP path.

### Added (v0.26.2-preflight — post-audit ruleset feasibility diagnostic)

Closes #533. Pass 1 only — docs-only sprint, no implementation, no spec,
no schema changes.

- **Outcome: Path B (partial block, scoped sprint).** v0.26.2 does NOT
  inherit the full #530 dependency chain. Walk-forward is insulated
  from the `signal_eval.py:180` `NotImplementedError` (#494 / #530
  Sprint A) because it runs through `backtest_engine._run_scheduled`,
  not the live-flow candidate resolver.
- **Per-filter verdict:** Defensive (hard-filter, disjoint from #530),
  Tariff (schema-only, uses v0.25.1 `is_known_event` substrate),
  Morning-only (deferred to #540 behind intraday OHLCV data layer).
- **R8(a) finding:** `source_trade_ids: null` fails
  `validate_derived_from` at `walkforward_firewall.py:129-135` —
  recommend omitting the key entirely.
- **Deliverable:** `docs/sprints/post_audit_v1_preflight.md` (343 lines).

### Validated (v0.25.3 — Walk-forward framework end-to-end on real EDGAR data)

Closes #532. First real-data run of the walk-forward v1 framework (shipped
in v0.25.0 / PR #520) against `src/platform/specs/lazy_prices_v1.yaml`
using the operator's local EDGAR corpus.

- **Outcome:** `INCONCLUSIVE / coverage_inconclusive` — matches the Pass 1
  pre-registered hypothesis (NOT PASS expected; forensic audit established
  lazy-prices underpowered at 2019-2024 trade density).
- **Run:** `run_id=88fd926e-1789-46f0-aee4-501addbb7256`,
  `spec_hash=ea78fed3...`, `code_git_sha=0f5e7178...`, `random_seed=42`.
- **Windows:** 5/5 `INCONCLUSIVE_DATA`. 20 OOS trades across 2019-2024
  (4/7/4/4/1 per window). Zero purged, zero embargoed.
- **Heavy-tail override:** fired on 4/5 windows, correctly driving MDE
  values to capture small-N pathology (Window 0: 4-trade, Sharpe −142,
  MDE 8.37e15). Not a bug — truthful reflection of small-N instability.
- **R8(a):** `derived_from: null` correctly propagated through to
  `walkforward_results.derived_from_source_type = NULL`.
- **Framework-bug trigger:** did NOT fire (would have required
  `outcome_state = PASS`).
- **Synthetic vs real comparison:** outcome state, reason, window-state
  distribution, heavy-tail count, and pooled MDE all match the synthetic
  INCONCLUSIVE baseline (`docs/validation/lazy-prices-v1-walkforward-2026-04-19.md`).
- **Validation doc:**
  `docs/validation/lazy-prices-v1-walkforward-real-2026-04-19.md`
- **Ralph Loop docs:**
  `docs/sprints/lazy_prices_v1_real_evaluation.md` (Pass 1),
  `docs/sprints/lazy_prices_v1_real_raw.md` (Pass 2).

**Secondary finding (non-blocking for this sprint):**
`vix_at_entry` and `vix_tier` are NULL for 20/20 OOS trades, driving
`vix_tier_coverage = 0`. Data-enrichment gap upstream of the framework;
filed as follow-up in the validation doc. Does not affect this run's
INCONCLUSIVE verdict (primary `min_trades_per_window = 10` gate already
binding).

### Changed (v0.25.2 — Roadmap completeness audit)

Closes #526. Additions-only sprint — no new code, `frontend/src/pages/Roadmap.jsx`
data extensions only.

- **New Phase 1 subphase "Parked / deferred"** — 15 items captured that memory
  and open GitHub issues reference but that were missing from the roadmap UI:
  1 surprise-shipped (HSHS dashboard, flipped to `done` with reference to
  `Health.jsx:247-289`) + 14 pending items across issue-referenced tech debt
  (#367 WatchLoop, #432 position-cap consolidation, #451 residual shorts,
  #478 SQLite repository pattern, #479 executor.py mega-functions, #480
  shadow_trading test suite, #491/#492 Tier 7 correlation work, #493/#494
  v0.24.1 wiring gaps, #497 forensic refactor) and memory-only deferred items
  (AI Council 5→7 expansion, Alpaca MCP integration, IB log-only broker).
- **Phase 2 Month 3** — 1 item appended: UPS purchase (CyberPower
  CP1500PFCLCD) — complements the existing Dedicated Arcis machine row that
  only mentions UPS in its specs blurb.
- **Phase 3 new subphase "Second strategy candidate (v0.27.x)"** — 1 item:
  second-strategy candidate spec gated on v0.26 cycle outcome.
- **Phase 5 Fund formation** — 3 items appended: CPCV upgrade, live
  walk-forward (rolling OOS extension), and v1.0.0 release gate
  (fund-formation readiness) with explicit prerequisite list.
- **Skipped** — "Research Analyst setup" per guardrail #3 (don't invent items
  when memory is vague). Roadmap.jsx:161 already explicitly supersedes the
  concept: "Supersedes the stale 'Research Analyst desk (relaxed thresholds)'
  concept — platform evaluates genuinely uncorrelated strategies, not relaxed
  variants of swing."
- **Ralph Loop docs** — `docs/sprints/roadmap_completeness_evaluation.md`
  (Pass 1) + `docs/sprints/roadmap_completeness_research.md` (Pass 2).

Total Roadmap.jsx delta: +20 items across 4 insertion sites (1 new Phase 1
subphase with 15 items, 1 Phase 2 append, 1 new Phase 3 subphase with 1 item,
3 Phase 5 appends). Zero existing items modified. No MASTER.md changes.

### Added (v0.25.1 — known_events 2019-2024 backfill + is_known_event helper)

Load-bearing prerequisite for v0.26.2's post-audit ruleset tariff-exclusion
rule. Before this sprint, `src/diagnostics/known_events.py` only carried
March-April 2026 forward-planning dates, meaning any tariff-exclusion rule
applied to walk-forward v1 OOS windows (2019-01-01 → 2024-09-30 per
`walkforward_config.py` R1) would match zero historical dates and be
effectively a no-op.

- **9 new events** added to `KNOWN_EVENTS` covering the 2019-09-30 →
  2024-09-30 window, each verified against a primary source
  (treasury.gov/OFAC, USTR, White House EO, BIS, DOD, Maersk). See
  `docs/sprints/known_events_and_drift_repair_research.md` §1.1 for
  per-event market-move verdict and source URL.
- **5 new category labels** — `SANCTIONS_INITIAL`, `SANCTIONS_ESCALATION`,
  `EXPORT_CONTROLS`, `INDUSTRIAL_POLICY`, `TRADE_DISRUPTION` — all roll
  up to existing `"Trade Policy"` category for consumer uniformity
  (`src/diagnostics/analyses.py:_match_events` unchanged).
- **`EVENT_METADATA: dict[str, EventMeta]`** — new parallel dict keyed on
  the same dates as `KNOWN_EVENTS`. Carries per-event description,
  affected-sector list (empty = broad-market), primary-source URL, and
  market-impact note. Invariant enforced by test:
  `set(KNOWN_EVENTS) == set(EVENT_METADATA)`.
- **`is_known_event(date_str, category=None)`** helper — returns True
  iff the date is keyed in `KNOWN_EVENTS` and (if category given) the
  category matches. Pure function, no side effects.
- **Backward compatibility** — `KNOWN_EVENTS` and `EVENT_CATEGORIES`
  dict shapes unchanged; existing consumer at `analyses.py:210-213`
  reads the same API.
- **Coverage floor** — regression test requires ≥ 8 events in the
  2019-09-30 → 2024-09-30 window; hard fails if count drops.
- **File size** — `known_events.py` at 327 lines, within the 400-line
  guardrail; no split required.
- **13 new tests** in `tests/diagnostics/test_known_events.py` covering
  schema invariants, category closure, coverage floor, metadata parity,
  primary-source format, helper lookup, and new-label category routing.

### Fixed (v0.25.1 — MASTER.md Section 2 + CLAUDE.md drift repair)

Today's 11-PR session shipped without mid-sprint `MASTER.md` updates;
`scripts/verify_docs.py` was failing with 5/5 warnings. Repaired:

- `Tests` row: 2,141 → 2,507 (+366 tests across platform-foundation/rigor/
  safety/shadow sprints + dashboard v1 + walk-forward v1 + training-data
  audit + hygiene bundle + known_events backfill). Test files: 181 → 227.
- `Python files` row: 214 → 303 (+89 modules across the same sprint
  cluster).
- `Dashboard pages` row: 25 → 28 (Walkforward Results added v0.25.0).
- `Research docs` row: 107 → 92 (-15; doc pruning since last update).
- `Schema tables` row: 61 → 67 registry, 58 synced to Postgres (9
  local-only enumerated in the annotation).
- `Closed trades` row: 85 → 88 (live count per latest shadow-status).
- `GitHub issues` row: 0 → 40 (actual open issue count via `gh issue list`).
- `Training data` row reformatted to concise
  `1,782 examples total; 76 quarantined (75 format_drift + 1 v1_citation);
  1,706 clean corpus` per updated-prompt copy.
- Component rows in §2 updated to match: `Dashboard (Arcis)`
  (26 → 28 pages), `Schema registry` (63 → 67 tables), `Render sync`
  (44/51 → 58/67 tables).
- **Four new Deployed Components rows** added: WalkforwardResults
  dashboard page (v0.25.0), Walk-forward v1 promotion gate (v0.25.0,
  soft migration live), Capability registry + `/api/system/index`
  (v0.25.0), Training audit pipeline + quarantine (v0.26.0 — 1,706
  clean / 76 quarantined).
- `CLAUDE.md` line 14 table count: 64 → 67. Authoritative-count
  one-liner preserved.
- `scripts/verify_docs.py` now exits 0 with 5/5 passes.

**Deferred follow-up:** `frontend/public/architecture.html` (880 lines,
zero `walkforward` references after PR #520) is stale but outside the
`verify_docs.py` check set. Issue to file for a subsequent sprint.

### Changed (v0.25.1 — RELEASES.md session addendum + Roadmap.jsx retroactive updates)

- `RELEASES.md` v1.0.0 criteria table: Phase 1 gate trade count
  `18 trades (36%)` → `88 trades (target reached — validate
  WR/Sharpe/PF/DD next)`. Count only; WR/Sharpe/PF/DD gate metrics
  not yet computed (next validation sprint).
- `RELEASES.md` — added "v0.25.0 Session addendum (2026-04-19)"
  entry documenting PRs #506, #509, #512-#519, #521 with the
  patch-level rationale for each. Not tagged as its own release
  because it's the same opening-bell session as v0.25.0 (walk-forward
  v1 already tagged) and v0.26.0 (training-data audit still
  [Unreleased]).
- `frontend/src/pages/Roadmap.jsx`:
  - `lastUpdated`: 2026-04-17 → 2026-04-19.
  - **Weeks 8-12 subphase:** 4 items flipped `pending` → `done`
    (Earnings 7-day exclusion SD#33, 3-regime classifier v2 SD#35,
    Monthly retraining cadence SD#34, TCA logging SD#38). Each item's
    `d` field updated with shipping evidence.
  - **Strategy Research Platform subphase:** 13 items flipped
    `pending` → `done` (backtest harness, strategy spec YAML + plugin,
    DSR gate, CSCV/PBO + walk-forward, survivorship bias / point-in-time
    universe, Task 0 EDGAR fetch, per-desk Alpaca clients, shadow-trading
    harness, promotion pipeline, correlation monitoring, hard exposure
    limits, defensive dashboard desk filter, Strategy Research dashboard
    page). Lazy Prices strategy flipped `pending` → `in-progress`
    (spec + synthetic smoke done; real-data walk-forward pending).
  - **New subphase `'v0.25.0 — Rigor + hygiene bundle (April 19, 2026)'`**
    with 11 `done` entries (capability registry v1, training-data audit,
    walk-forward framework, command-queue TTL, DB busy_timeout, SQLite
    TEXT coercion, composite PK fix, command-execution hygiene,
    dependency hygiene, GitHub Actions disabled, SD#42 strategy
    evaluation).
- Frontend build verified after edits (`npm run build` ✓ 526ms,
  2,765 modules transformed).

### Chore (v0.25.1 — grandfathered violations from 2026-04-19 merges)

`config/known_violations.json` — added 1 file + 4 functions that
slipped past `test_repo_structure.py` because GitHub Actions was
disabled mid-session. All pre-existing, not caused by this sprint:

- `src/platform/promotion.py` (525 lines) — PR #520 walk-forward
  gate evaluator.
- `src/platform/promotion.py:_evaluate_shadow_trading_gate` (69 lines)
  — same PR.
- `src/platform/rigor/walkforward_runner.py:persist_run_result` (93)
  — PR #520.
- `src/platform/rigor/walkforward_runner.py:run_walkforward` (103) —
  PR #520.
- `src/sync/render_sync.py:run_sync_cycle` (68 lines) — PR #516
  (expire_stale_commands + heartbeat additions).

Follow-up issue to file: "split platform/promotion.py + rigor/
walkforward_runner.py + sync/render_sync.py:run_sync_cycle for a
dedicated cleanup sprint".

### Fixed (v0.25.1 — test_render_sync mock for expire_stale_commands)

`tests/test_render_sync.py::test_healthy_connection_reused_without_reconnect`
patched `pull_commands` but not the new `expire_stale_commands` orphan-
sweep (added in PR #516 same day). The sweep opens its own psycopg2
connection, breaking the test's `connect.call_count == 1` assertion.
Added `patch("src.sync.render_sync.expire_stale_commands", return_value=0)`
to the mock stack. Test-only change; runtime behavior unaffected.

### Changed (2026-04-19 — GitHub Actions disabled)

- Deleted `.github/workflows/ci.yml` and `.github/workflows/daily-repo-audit.yml` to conserve Actions spend until walk-forward validation proves live edge (per April 2026 pivot).
- Added `scripts/run_ci_locally.ps1` — runs the same checks (repo structure guardrails, full pytest with `-x --timeout=60`, test count floor, frontend build, doc drift). Flags: `-SkipFrontend`, `-SkipSlow`.
- Re-enable path: restore workflows from git history after walk-forward v1 real-data run shows excess-Sharpe ≥ 0.5 at t ≥ 2.0 over 150 OOS trades (SD#25).

### Added (v0.25.0 — Walk-Forward Validation Framework v1)

Load-bearing multi-year infrastructure. Every future strategy must pass
walk-forward v1 before promotion to `shadow_trading` or real capital.
Closes three regime traps identified in the April 18 forensic audit:
regime-averaged false positives, underpowered Sharpe reporting, and
bootcamp-derivation circularity.

- **Three-state outcome framework** (PASS / FAIL / INCONCLUSIVE) — never
  collapsed to boolean anywhere in the stack. Schema enforces
  `outcome_state` NOT NULL; `check_promotion_gate` evidence carries
  `walkforward_outcome_state` + `walkforward_reason` fields end-to-end.
- **R1 — Five non-overlapping OOS windows** 2019-01-01 → 2024-09-30,
  each with a 2-calendar-year IS flank
  (`src/platform/rigor/walkforward_config.py`).
- **R2 — Purge + embargo** (`walkforward_purging.py`) runs at every
  IS/OOS boundary to prevent leakage.
- **R3 — Point-in-time S&P 100 universe** — no survivorship bias.
  `data/reference/sp100_historical.csv` sourced from S&P DJI press
  releases + Wikipedia index-change tables. Resolver in
  `walkforward_universe.py`.
- **R4 — Transaction costs** (0.5 bp per side, 1.0 bp round-trip)
  applied uniformly in `walkforward_costs.py`.
- **R5 — Determinism** via `WalkForwardConfig.random_seed`; spec hash
  + git SHA recorded per run.
- **R6 — MDE gate** using annualized-scale Lo (2002) formula with
  Newey-West N_effective correction; heavy-tail bootstrap SE override
  at `bootstrap_SE > 1.5 × parametric_SE` (10k resamples).
- **R7 — Full reproducibility columns** on every `walkforward_results`
  row: spec_hash, code_git_sha, random_seed, config_json.
- **R8 — Strategy identity firewall** (`walkforward_firewall.py`):
  (a) `derived_from` required field on every spec, (b) overlap
  assertion before any window runs, (c) no inherited credit,
  (d) bootcamp forced False, (e) PR body declaration (honor-system).
  Non-blocking runtime heuristic emits WARNING when spec first-commit
  is within 30 days of a matching forensic audit AND derived_from=null.
- **Schema** — `walkforward_results`, `walkforward_trades`, and
  `sp100_historical_constituents` added to `src/schema/registry.py`.
  Table count 64 → 67.
- **CLI wrapper** `scripts/backtest/run_walkforward.py` — exit codes
  0/1/2/3 map PASS/FAIL/args-error/INCONCLUSIVE so CI can distinguish
  underpowered from failed.
- **Lazy Prices v1** spec updated with `derived_from: null`
  (literature-derived from Cohen-Malloy-Nguyen 2020 JF).
- **Dashboard** `/walkforward-results` React page with three-state
  color coding (PASS green, FAIL red, INCONCLUSIVE amber) +
  INCONCLUSIVE_POWER / INSUFFICIENT_DATA sub-badges +
  per-window/per-trade drill-down.
- **Backend route** `src/api/cloud_routes/walkforward.py` — runs list,
  run detail, window aggregation, trade drill-down.
- **Promotion gate** `check_promotion_gate` — walk-forward v1 takes
  precedence when a row exists; three-state result preserved in
  evidence dict. Soft migration: legacy DSR + PBO + OOS_efficiency path
  still runs when no walkforward_results row exists.
- **Synthetic smoke test** — `scripts/backtest/lazy_prices_smoke_test.py`
  exercises all three outcome paths. Cloud fallback: report marked
  SYNTHETIC FALLBACK when real EDGAR data not accessible. Operator
  re-runs locally after PR review.
- **131 new tests** across 9 new test modules in
  `tests/platform/rigor/`, `tests/scripts/`, `tests/api/`, and
  `tests/platform/test_promotion_walkforward.py`.

### Added (v0.26.0 — Training Data v1-Citation Audit)

- `src/training/audit/` package — three-pass audit for the 1,782-row
  `training_examples` corpus:
  - Pass A (`pass_a_citation.py`) — quarantines rows whose narrative
    cites the v1-buggy outcome and contradicts the v2-corrected
    outcome. Ground truth lives in `attribution_trades`
    (`ranker_only_outcome_v1 != ranker_only_outcome`). Lexicon-based
    win/loss direction classifier with word-boundary regex
    (`successful` fires; `unsuccessful` does not).
  - Pass B (`pass_b_format.py`) — XML tag integrity on `output_text`
    (`<why_now>`, `<analysis>` at 95% prevalence) + plain-text label
    schema on `input_text` (`Ticker:`, `Current Price:`, `Trend State:`
    — all 100% prevalence per commit-12 calibration).
  - Pass C (`pass_c_leakage.py`) — TF-IDF + LogReg probe with
    StratifiedKFold CV + balanced-accuracy scoring on the labeled
    subset (`blinded_win/loss`, `outcome_win/loss`). Masks ticker +
    company names. Report-only; never auto-quarantines in v1.
- `@register_action(name="training_data_audit", ...)` — capability
  registered at import time per Sprint 1B. Appears in
  `/api/system/index` and as a third kickoff button on `/diagnostics`.
- `POST /api/diagnostic-runs/training-audit` + 409 CONFLICT dedup
  (same pattern as regime + forensic).
- `run-training-audit` command dispatched through
  `src/commands/diagnostic_handlers.py` →
  `dashboard_runner.run_diagnostic` →
  `scripts/audits/training_data_v1_audit.py`.
- Frontend: third `<div>` in `DiagnosticKickoffButtons.jsx`
  (grid-cols-3); `DiagnosticRunTable.parseDecision()` recognizes
  `{quarantined_total, total_audited}` summary_json shape.
- Schema: `training_examples.quarantined INTEGER DEFAULT 0` +
  `training_examples.quarantine_reason TEXT` columns (additive via
  registry). `diagnostic_runs.diagnostic_type` description widened
  to `'regime' | 'forensic' | 'training_audit'`.
- Fixed quarantine-reason taxonomy (`src/training/audit/taxonomy.py`):
  `v1_attribution_contradicts_narrative` |
  `format_drift_missing_section` | `format_drift_deprecated_marker` |
  `format_drift_malformed` | `leakage_ngram_suspect`. Free-form
  strings are not accepted (R3).

### Audit results (2026-04-19 production run)

- Total audited: 1,782; quarantined 76 (4.3%); clean corpus 1,706.
- Pass A: 1 quarantine (CSCO, `blinded_win`, narrative cited v1="loss"
  contradicting v2="win"); 7 preserved outcome-neutral.
- Pass B: 75 missing `<why_now>` or `<analysis>` XML tags.
- Pass C: balanced accuracy 0.500, majority baseline 0.721 — NOT
  LEAKING. Probe confirms the narrative does not encode the outcome
  beyond class-imbalance baseline.
- Full report: `docs/audits/training-audit-2026-04-19.md`.

### Tests added (v0.26.0)

- `tests/training/test_pass_a.py` (14 tests)
- `tests/training/test_pass_b.py` (12 tests)
- `tests/training/test_pass_c.py` (7 tests)
- `tests/training/test_audit_integration.py` (12 tests)
- `tests/audits/test_training_audit_cli.py` (6 tests)
- `tests/test_diagnostic_handlers.py` (+3 tests)
- `tests/api/test_diagnostic_routes.py` (+5 tests)
- `tests/test_schema.py` (+2 tests)

### Added (v0.25.0 — Capability Registry, Sprint 1B)

- `src/platform/capability_registry/` — four in-process registries
  (ACTIONS, STATES, SYSTEMS, DECISIONS) populated at import time via
  decorators, mirroring `src/platform/plugin_registry.py:19`. Pydantic
  v2 validation rejects partial metadata at decorator time; deprecated
  entries must specify `deprecated_replacement`. ActionEntry
  input/output schemas validated as Draft-7 JSON Schema (MCP-compatible).
- `GET /api/system/index` + `POST /api/system/index/{name}/mark-reviewed`
  (`src/api/cloud_routes/system_index.py`). State queries and system
  health checks run in a shared ThreadPoolExecutor with a 2s per-call
  timeout. One bad query cannot cascade-break the endpoint (R5).
- `operator_view_state` table (`src/schema/registry.py`) tracks per-
  operator last-viewed baseline + delta for each entry, plus local
  Mark Reviewed override. `sync_to_postgres=False` — local state only
  until v1.1's source-file automation.
- 18 retroactive capability registrations across the platform:
  - Actions: `regime_diagnostic`, `forensic_trade_audit`,
    `strategy_backtest`, `edgar_historical_backfill`
  - States: `shadow_trade_cohort`, `strategy_registry_state`,
    `training_corpus`, `bootcamp_mode`, `alpaca_account`, `ollama_model`
  - Systems: `watch_loop`, `reconcile_trades`, `attribution_resolver`,
    `nightly_audit_agent`
  - Decisions: `bootcamp_still_active`, `pullback_strategy_contaminated`,
    `lazy_prices_deprecated_on_sp100`,
    `no_new_strategy_specs_until_walkforward_ships`
- Dashboard panels: `QuickStatsPanel`, `SystemIndexPanel`,
  `WhatsNewPanel`, `CapabilityDetailModal` (with Mark Reviewed flow).
  Wired into `frontend/src/pages/Dashboard.jsx`; 60s refetch interval.
  No new npm deps.
- CI enforcement: `tests/test_capability_registry_metadata.py` (10
  tests) + `tests/test_capability_registry_integration.py` (5 tests).
  Stale entries (>180d) emit warnings, not failures.
- `jsonschema>=4.0` promoted from transitive to first-class dependency.
- `docs/capability_registry.md` spec + how-to.
- Ralph Loop artifacts: Pass 1 evaluation + Pass 2 research findings
  committed as `docs/sprints/capability_registry_v1_evaluation.md` and
  `docs/sprints/capability_registry_v1_research_findings.md`.

### Tests (Sprint 1B totals)

- 15 schema tests (`tests/platform/test_capability_registry_schemas.py`)
- 14 registry mechanics tests (`tests/platform/test_capability_registry.py`)
- 10 CI metadata tests (`tests/test_capability_registry_metadata.py`)
- 12 API endpoint tests (`tests/api/test_system_index.py`)
- 5 integration tests (`tests/test_capability_registry_integration.py`)
- 56 new tests total, all green.

### Added (v0.25.0 — Diagnostic Dashboard)

- New `/diagnostics` dashboard page with kickoff buttons for regime and forensic diagnostic runs, inline markdown report rendering (react-markdown + remark-gfm), and inline base64 plot display. Polls 5s while active, 30s otherwise.
- `diagnostic_runs` + `diagnostic_run_plots` tables (schema registry `src/schema/registry.py`) — sibling layout with base64-encoded PNGs so plots reach the Render dashboard through existing table-only sync.
- Six new REST endpoints under `/api/diagnostic-runs/*` (cloud): POST regime/forensic (202 with queued run_id), GET list (filterable by type+status), GET single, GET report markdown, GET plots.
- Two new executor handlers in `src/commands/executor.py`: `run-regime-diagnostic`, `run-forensic-audit`. Both delegate to the new `src/diagnostics/dashboard_runner.py` orchestration helper (subprocess, report parse, plot encode, SQLite transaction).
- `src/diagnostics/summary_extractor.py` — regex parser for `## Executive Summary` sections of both report formats, with raw-text fallback when fields can't be extracted.
- Deps: `react-markdown@^9`, `remark-gfm@^4` (operator-approved).
- 26 new tests: 6 summary-extractor, 3 dashboard_runner, 6 handler, 9 API route, 2 end-to-end smoke.

### Refactor (post-Sprint-3 tech debt — closes #471)

- Extract 4 Sprint-2-grandfathered size-guardrail violations into named helpers with zero behavior change:
  - `src/platform/backtest_engine.py` (432 → 396 lines): split `_inject_cosine_scores` into new `src/platform/backtest_attribution.py` module. Pattern mirrors Sprint 1's `signal_eval.py` extraction.
  - `src/platform/promotion.py::check_promotion_gate` (97 → 25 lines): dispatcher delegates to `_evaluate_shadow_trading_gate` / `_evaluate_production_gate` per-target helpers.
  - `src/platform/rigor/walkforward.py::run_walkforward` (83 → 58 lines): extract `_run_one_fold(strategy_spec, fold_spec)` + `_compute_efficiency` helper.
  - `src/platform/features/cosine_similarity.py::_parse_section_from_fulltext` (68 → 32 lines): extract `_is_substantive_match(body)` predicate + `_SECTION_PATTERNS` module-level dict.
- `config/known_violations.json` — 4 entries removed. No new grandfatherings added.

### Added (post-Sprint-3 feature completion — closes #475)

- `backtest_results` schema — 2 new NULL-defaulting columns: `pbo` (Probability of Backtest Overfitting from CSCV) and `oos_efficiency` (walk-forward OOS_SR / IS_SR). Populated by Sprint 4's param-sweep driver (PBO) and by new `--with-walkforward` CLI flag (OOS efficiency).
- `scripts/run_backtest.py --with-walkforward` — invokes `run_walkforward` against the strategy spec + date range and persists `oos_efficiency` to the `backtest_results` row.
- `src/platform/promotion.py::_evaluate_shadow_trading_gate` now enforces the full three-gate check per spec line 1127-1135:
  - DSR ≥ 0.95 (was already live via Task 5-carryover)
  - **PBO ≤ 0.50** (new — fails with clear message if NULL)
  - **OOS_efficiency ≥ 0.30** (new — fails with clear message if NULL)
  Evidence dict now carries all three values; historical gate decisions are fully reproducible from `strategy_promotion_events.gate_result_json`.

### Tests

- 5 new tests in `tests/platform/test_promotion.py` covering each new failure mode (PBO NULL, OOS NULL, PBO over threshold, OOS under threshold) plus the all-pass case.
- `--with-cscv` CLI flag deferred to Sprint 4's param-sweep driver where it semantically belongs (a single-config backtest can't produce meaningful PBO).

### Fixed

- deps: add missing `beautifulsoup4` to `requirements.txt` — `fed_collector` and clean-deploy importability depended on a transitive install; now declared as a first-class dependency. (#455)
- deps: add missing `numpy` and `scipy` to `requirements.txt` — analytics modules (evaluation, features/regime, simulation/monte_carlo) import both but neither was declared; clean deploys crashed on first analytics import. (#460)
- deps: add missing `pyarrow` to `requirements.txt` — `src/simulation/cache.py` uses `pd.read_parquet` / `to_parquet`; pandas requires pyarrow for parquet IO. Simulation cache crashed on clean deploy. (#462)

## v0.24.0 (Strategy Research Platform — Final)

Final release of the Strategy Research Platform (v0.24.0 arc). Merges Sprint 4 continuation: visibility layer + functional signal integration.

### Added
- **`_find_candidates` integration** (highest-value task): `src/platform/signal_eval.py::find_candidates_for_date` — event-driven single-date candidate generation reusing backtest_engine._run_event_driven. ShadowHarness._find_candidates now calls it. Platform is functional — any promoted strategy with event-driven entry can generate real research-desk trades. Dedup against open shadow_trades for the strategy's desk.
- **`/api/platform/*` endpoints** (Task 12b): 5 GET (strategies, detail, backtest-results, backtest-trades, promotion-events) + 3 POST (backtests async kickoff, promotions with 40-char justification + two-step 24h delay for production, demotions with 20-char reason).
- **`/research-platform` dashboard page** (Task 12a): 4 sections — strategy registry table with status badges, expandable detail with YAML spec + backtest history grid + promotion events log, equity curve modal using BacktestEquityChart (Recharts LineChart). Empty state renders cleanly.
- **`PlatformStatusWidget` on home dashboard** (Task 12d): compact status card with strategy counts per state, "ready for approval" nudge, last backtest timestamp. Returns null when no strategies exist.
- **Telegram platform events** (Task 12e): `notify_backtest_complete`, `notify_shadow_gate_ready` (dedup per strategy within 24h), `notify_strategy_promoted`, `notify_strategy_demoted`. All prefixed `[RESEARCH]`. Send failures logged, never raised.
- **Python plugin strategy interface** (Task 2): `src/platform/strategy_plugin.py` (StrategyPlugin ABC + Candidate dataclass) + `src/platform/plugin_registry.py` (register/get/list). Interface-only; plugin execution wiring is v0.24.1.
- **`docs/platform/activation-guide.md`** (Task 13): operator walkthrough from YAML spec to production promotion.

### Deferred to v0.24.1
- **Tier 7 correlation monitoring**: `correlation.py` (Spearman/Pearson/exceedance), `factor_decomp.py` (Carhart 4 + QMJ), `change_detection.py` (PELT), `alerting.py` (tiered). Only relevant once ≥2 concurrent strategies run concurrently. Filed as separate issues.
- **Python plugin execution wiring**: interface defined in v0.24.0 but backtest_engine + shadow_harness python_plugin path is v0.24.1 scope.
- **Historical EDGAR backfill 2019-2023** (issue #469): blocks first Lazy Prices promotion.
- **Scheduled-kind `find_candidates_for_date`**: event-driven path lives; scheduled returns [] with warning.

### Tests
- 22 new tests across Sprint 4 continuation.
- Full suite post-v0.24.0: ~2,141 passed + ~5 skipped + 1 pre-existing failure (`test_open_trades_excluded`).

### Non-negotiable gates — all green
- `_find_candidates` returns non-empty list when signal criteria met (test_find_candidates_returns_nonempty_on_signal_match)
- ShadowHarness.run_one_tick places bracket order via research client on real candidate (test_harness_run_one_tick_places_order_when_candidate_passes_limits)
- POST /api/platform/promotions rejects justification_note < 40 chars (test_promotion_rejects_short_justification)
- POST /api/platform/demotions rejects reason < 20 chars (test_demotion_rejects_short_reason)
- /research-platform renders empty state + populated state cleanly
- npm run build succeeds with no new warnings

## v0.24.0-alpha4 (Sprint 4 Tier 5 — Live Deployment Foundation)

### Added
- **Task 7a** — `src/shadow_trading/alpaca_clients.py`: per-desk `TradingClient` factory via `get_client(desk)`. Cached with double-checked locking. `verify_accounts_distinct()` raises if swing and research resolve to the same Alpaca account_number — catches silent cross-contamination at startup. Config via `desks.{desk}.alpaca_key_env` in `config/settings.example.yaml` (operator populates `settings.local.yaml` with real credentials).
- **Task 7b** — 17 public API functions in `src/shadow_trading/alpaca_adapter.py` accept `desk: str = "swing"` kwarg. `_get_trading_client(desk=...)` and `_get_data_client(desk=...)` dispatch to `alpaca_clients.get_client(desk)` when `desk != "swing"`. `place_live_entry` raises `ValueError` if `desk != "swing"` (live trading is swing-only compliance guardrail).
- **Task 7c (CRITICAL)** — `reconcile_paper_trades(desk=...)` and `reconcile_live_trades(desk=...)` filter `shadow_trades` by desk and route Alpaca queries through the per-desk client. Fixes the silent-404 risk when reconcile polls research positions on the swing Alpaca account. `reconcile_live_trades` raises `ValueError` on research desks.
- **Task 7d** — New `src/shadow_trading/reconcile_dispatch.py` with `reconcile_all_paper_trades()` — single source of truth for the "swing + every active research desk" loop. Used by `overnight.py`, `position_monitor.py`, `watch.py`. Per-desk failure isolation. `cli/commands.py:408` passes `desk="swing"` explicitly.
- **Task 7e** — `src/platform/shadow_harness.py` with `ShadowHarness` class. Per-strategy instance. `__init__` invokes `verify_accounts_distinct`. `run_one_tick(as_of)` does reconcile → candidates → pre-trade-limits → bracket placement → `shadow_trades` write with `desk='research_<strategy_id>'`. `halt()` closes only this strategy's positions. `get_open_positions()` filters by desk. `_find_candidates` is an MVP placeholder (v0.24.1 follow-up).
- **Task 7f** — `ShadowHarness._is_within_hard_limits` delegates to Sprint 3's `check_pre_trade_limits`. NAV from research Alpaca (fallback $100K). Positions desk-filtered. Blocked candidates skip `place_bracket_order`.
- **Task 9** — `WatchLoop._run_platform_shadow_tick` dispatches every strategy in `shadow_trading` state on its own `shadow_cadence_seconds` (default 600s). Interval-gating pattern (not inline). Failure isolation — one strategy's crash does not kill swing. `_last_platform_tick` dict in `__init__`; cleared on `_reset_daily_state`. Outer loop calls `_safe_run("platform shadow tick", ...)` once per cycle.
- **Task CC** — `src/platform/cost_calibration.py` with `calibrate_from_swing_history()`. Computes median `entry_slippage_bps` / `exit_slippage_bps` from closed swing trades. Falls back to hardcoded 3 bps when sample < 10. Non-negotiable gate: calibrated value within 30% of the hardcoded default.

### Tests
- 35 new tests across 7 test files. Non-negotiable gates all pass:
  - `test_harness_reconcile_uses_research_client`
  - `test_harness_bracket_monitor_uses_research_client`
  - `test_verify_accounts_distinct_raises_on_same_account`
  - `test_harness_halt_closes_only_this_strategy_positions`
- Full suite post-Sprint-4-Tier-5: ~2,095 passed + ~4 skipped. Pre-existing failures unchanged.

### Platform stays inert at merge
- Zero strategies in `shadow_trading` state at merge time. No live behavior change until the operator promotes a strategy.
- `SELECT COUNT(*) FROM shadow_trades WHERE desk != 'swing'` returns 0 before and after merge.
- `_find_candidates` stub logs `[HARNESS <id>] _find_candidates: returning []` — platform is correctly inert.

### Deferred to `v0.24.0-alpha5` / `v0.24.1`
- Tier 6 (dashboard `/research-platform` page, action buttons, PlatformStatusWidget, Telegram events) — visibility layer; not load-bearing
- Tier 7 (correlation measurement, Carhart+QMJ factor decomp, PELT change detection, tiered alerting) — only relevant once ≥2 research strategies run concurrently
- Tier 8 (Python plugin strategy interface, final docs sweep + activation-guide.md) — CUT-CANDIDATE per spec
- `_find_candidates` full integration (expose `signal_eval.find_candidates_for_date`) — required before any real shadow trades can be placed

### Operator prerequisites before activating any research strategy
1. Create a SECOND Alpaca paper account with distinct credentials
2. Export `ALPACA_RESEARCH_API_KEY` / `ALPACA_RESEARCH_API_SECRET` in the NSSM service env (via `nssm set ArcisWatchLoop AppEnvironmentExtra ALPACA_RESEARCH_API_KEY=... ALPACA_RESEARCH_API_SECRET=...`)
3. Flip `desks.research.enabled: true` in `config/settings.local.yaml`
4. Restart watch loop → `verify_accounts_distinct()` runs at first ShadowHarness init and fails-fast if mis-configured
5. Wait for `_find_candidates` full integration in v0.24.1 before promoting any strategy to `shadow_trading`

## v0.24.0-alpha3 (Sprint 3 of 4 — Defensive Dashboard + Hard Exposure Limits)

### Added
- **Task 12c — Defensive desk filtering.** `/api/shadow/*` endpoints (`open`, `closed`, `sharpe-attribution`, `metrics`, `account`) accept optional `?desk=` query param: absent/`swing` → swing-only (backward compat), `all` → aggregate, `research_*` → SQL LIKE wildcard, exact match otherwise. `Dashboard.jsx` gets a desk-filter dropdown populated at render time from the new `GET /api/shadow/desks` endpoint (returns distinct desks currently in `shadow_trades`).
- **Task 11b.1 — Correlation schema.** Two new tables registered: `correlation_matrices` (long-form daily Spearman/Pearson/neg_exceedance snapshots) and `factor_loadings` (rolling Carhart 4 + QMJ regression outputs). Both `sync_to_postgres=True`, `sync_mode='incremental'`. No writes this sprint — Sprint 4 correlation monitor populates.
- **Task 11b.4 — Hard exposure limits.** New `src/platform/risk/exposure_limits.py` with `check_pre_trade_limits(ticker, shares, price, positions, nav, db_path) -> (allowed, reason)`. HARD_LIMITS: 6% single-name / 25% sector / 1.5× gross / 8% book drawdown circuit breaker. Book drawdown computed live from `shadow_trades` cumulative pnl_pct — no persistent breach flag needed; "no auto-reset" enforced by the math itself. SOFT_LIMITS stubbed for Sprint 4 (correlation + factor + vol ratio). `get_soft_limit_breaches()` returns empty until Sprint 4 wires correlation data.

### Tests
- 37 new tests across `tests/platform/risk/test_exposure_limits.py` (13), `tests/test_correlation_schema.py` (9), `tests/test_shadow_desk_filter.py` (15). Non-negotiable gates all pass: single-name / sector / drawdown blocks, 4 desk-param semantics on `/api/shadow/sharpe-attribution`, correlation tables sync-to-postgres incremental.

### Notes
- `check_pre_trade_limits` is NOT yet wired into `src/shadow_trading/executor.py` — that's Sprint 4 (per spec line 230). This sprint ships the pure function + tests; integration path follows.
- Sector-concentration test uses NVDA instead of GOOGL because Alphabet was reclassified from Technology to Communication Services in GICS September 2018.
- Two post-sprint follow-ups tracked as GitHub issues: #475 (wire PBO + OOS_efficiency into `check_promotion_gate` evidence) and the existing #471 (v0.24.2 refactor sprint for 4 grandfathered violations).

## v0.24.0-alpha2 (Sprint 2 of 4 — CSCV + Walk-Forward + Promotion Pipeline)

### Added
- `src/platform/rigor/cscv.py` — Combinatorially Symmetric Cross-Validation / Probability of Backtest Overfitting (S=16 default; Bailey-Borwein-López de Prado-Zhu 2014).
- `src/platform/rigor/walkforward.py` — rolling walk-forward (Pardo 2008; default 3y train / 1y test; OOS_efficiency = OOS_SR / IS_SR; flags overfit if < 0.30).
- `src/platform/rigor/trials.py` — global trials registry with N_eff counter + empirical V[SR] estimator (fallback to 0.02/250 when <20 trials).
- `src/platform/promotion.py` — 5-state lifecycle (proposed → backtested → shadow_trading → production, plus deprecated) with DSR + PBO + OOS_efficiency gates, promote/demote/pause, ≥40-char justification enforcement on manual promotions, ≥20-char reason enforcement on demotion.
- Three new SQLite tables: `strategy_registry`, `strategy_promotion_events`, `trials_registry`.
- Three new `shadow_trades` columns: `desk` (default 'swing'), `research_thesis`, `strategy_spec_hash` + `idx_shadow_trades_desk` index. Migration backfills all 85 existing rows to `desk='swing'` via DEFAULT.

### Fixed (v0.24.0-alpha2.1 hotfix — commits 6055952 + bbf0a71 + 86a46fc)
- `src/platform/signal_eval.py` — `_query_event_rows` rejected the spec's `universe.tickers: "sp100"` string alias; `_resolve_universe` now dispatches string aliases via `_UNIVERSE_ALIASES`. Fixes Lazy Prices returning 0 trades on the production DB (H2).
- `src/platform/features/cosine_similarity.py` — `cosine_similarity_yoy` now falls back to parsing sections from `full_text` when `sections_json` is NULL (the EDGAR backfill populated `full_text` but never derived sections). Fixes cosine=None for every event (H1).
- `src/platform/signal_eval.py` — `_evaluate_event_signal` was hardcoded to AND logic; now honors `combinator` parameter so `combinator: any` fires on OR logic as spec declares. Fixes SBUX-style suppression when one-of-two filters passes (H4).
- `src/config/__init__.py` — DB_PATH was relative (`"ai_research_desk.sqlite3"`); now anchored to `Path(__file__).resolve().parent.parent.parent / "ai_research_desk.sqlite3"` with optional `ARCIS_DB_PATH` env override. Prevents CWD-dependent DB resolution that masked the H1/H2/H4 bugs during Sprint 1 review.
- `src/platform/promotion.py::check_promotion_gate` — now reads real N_eff + V from `trials_registry` rather than the stored (null-fallback-computed) `deflated_sharpe` column. Adds `RuntimeError` guard if V is None so null fallback can't silently fire in production.

### Tests
- 55+ new tests across `tests/platform/rigor/` + `tests/platform/` + `tests/test_schema_desk_columns.py` + `tests/test_config_db_path.py`. Non-negotiable gates pass: PBO rejects overfit (PBO>0.8), PBO accepts stable (<0.2), walk-forward OOS efficiency computed + flags overfit, shadow_trades 85-row backfill, justification-note enforcement, trials_sr_variance plumbing (no null fallback), trials_registry counts every backtest.

### Known issues
- EDGAR data is 2024-only (collector wired late 2025). Lazy Prices e2e test pins on `n_trades >= 1` rather than `>= 50`. Historical 2019-2023 backfill tracked in GitHub issue #469 (v0.24.x; blocks first Lazy Prices promotion to shadow_trading but non-blocking for Sprints 3/4).
- DSR paper-example test split into two V-values (V=0.5/250 for DSR=0.9004, V=0.046/250 for SR*₀_ann=0.5429) because the paper's two claimed outputs are mutually inconsistent under any single V (documented in `src/platform/rigor/dsr.py` docstring; source PDF password-protected — v0.25 followup).

## [Unreleased] → v0.24.0-alpha1 (Sprint 1 of 4 — Platform Foundation + DSR Gate)

### Added

- `src/platform/` package: strategy spec loader (Task 1), OHLCV data adapter (Task 3), basic metrics + survivorship haircut (Task 5a), Deflated Sharpe Ratio (Task 5b), strategy-agnostic backtest engine + signal_eval (Task 4), backtest CLI + SQLite persistence (Task 6), Lazy Prices feature providers (Task 11).
- First YAML strategy spec: `lazy_prices_v1` (Cohen-Malloy-Nguyen 2020) at `src/platform/specs/lazy_prices_v1.yaml`.
- Two new SQLite tables via schema registry: `backtest_results`, `backtest_trades` (registry now at 56 tables total).
- `scripts/run_backtest.py` CLI runner — invocable as `python scripts/run_backtest.py --strategy lazy_prices_v1 --start YYYY-MM-DD --end YYYY-MM-DD --output-format pretty`.
- `scripts/backfill_edgar_fulltext.py` backfill script (operator runs ~20-37 min SEC fetch; do not automate).

### Fixed

- `src/data_collection/edgar_collector.py::_fetch_filing_text` — corrected URL base to `www.sec.gov/Archives/...` (was `data.sec.gov/Archives/...` which 404s), replaced directory-scraping regex with submissions-API `primaryDocument` lookup. Root cause of 0/3362 EDGAR coverage (Task 0).

### Tests

- 44 new tests across 7 new test files (`test_dsr.py`, `test_backtest_engine.py`, `test_backtest_persistence.py`, `test_data_loader.py`, `test_lazy_prices.py`, `test_metrics.py`, `test_strategy_spec.py`). DSR paper-example reproduction gate PASSES. Two hand-computed backtest validation tests PASS (scheduled + event-driven modes).

### Notes

- `docs/research/deep-research/backtest-rigor-retrofit-plan.pdf` is password-protected; the DSR paper example was split into two independent assertions (one using V=0.5/250 for DSR=0.9004; one using V=0.046/250 for SR*_0_ann=0.5429) because the paper's stated outputs are mutually inconsistent under any single V. See `src/platform/rigor/dsr.py` module docstring and Plan Issue B.
- `src/data_collection/edgar_collector.py` now 413 lines (exceeded 400-line guardrail; Task 0 repair added ~27 lines). `_fetch_filing_text` is 68 lines (exceeded 60-line cap). Both are NEW violations introduced by Sprint 1 Task 0 — grandfathering or a follow-up split is needed before merging to main.

## [v0.23.4] - 2026-04-16 — Telegram Refresh: richer trade pings + periodic stats pulses

Long overdue operator-experience pass on the notification layer. The
`notify_trade_opened` / `notify_trade_closed` pings now carry sector,
regime, VIX, conviction, R:R, MFE/MAE, excess vs SPY, and slippage —
everything an operator needs to evaluate a fill without opening the
dashboard. Three new stats pulses (7:45, 12:00, 16:05 ET) give
trade-count + win rate + PnL + excess-Sharpe across today / 7d / 30d /
all-time, so performance is visible throughout the day. Coverage gaps
from today's new work (1-min bar collection, attribution resolver,
stress test) are filled with dedicated notifications.

### Added

- **`notify_trading_stats_update(stats, label)`** — formatted 4-window
  summary sent 3× per weekday (pre-market, midday, post-close). Silent
  on empty DB.
- **`src/journal/stats.py`** — `compute_window_stats` / `compute_all_window_stats`
  helpers that aggregate closed `shadow_trades` (excluding open +
  quarantined) across `today` / `7d` / `30d` / `all_time`. Excess-Sharpe
  shown only once ≥10 closed trades in a window.
- **`notify_1min_bar_collection`** — nightly confirmation from the
  Phase B overnight handler (bars, tickers, empty %, storage MB).
- **`notify_attribution_resolve_complete`** — resolved count + pending
  remaining, posted after the 4:30 PM ET resolver job.
- **`notify_stress_test_complete`** — scenario pass/fail summary, posted
  after the model-version-triggered 7 PM re-run.
- **`maybe_stats_pulse`** — new DAYTIME handler registered via
  `_register_default_handlers` alongside the 14 overnight handlers. Three
  done-flags (`_stats_{premarket,midday,postclose}_done`) reset daily.

### Changed

- **`notify_trade_opened`** — extended with optional `sector`,
  `regime_at_entry`, `vix_at_entry`, `concurrent_positions`,
  `llm_conviction` kwargs. Existing callers unchanged (all kwargs
  default to None; rendering is graceful when fields missing).
  `scan_service.py` caller now passes the enriched fields it already
  has from the feature row + current open-position count.
- **`notify_trade_closed`** — extended with optional `sector`, regime
  transition, `mfe_pct`, `mae_pct`, `excess_return`,
  `spy_return_over_hold`, `drawdown_from_mfe`, `entry_slippage_bps`,
  `exit_slippage_bps`. `executor.py` caller passes the full
  `shadow_trades` row so all fields render. Extracted
  `_format_closed_extras` helper to keep `notify_trade_closed`
  under the 60-line cap.
- **`src/scheduler/watch_handlers.py`** — added `DAYTIME_HANDLERS` list
  + `ALL_HANDLERS = OVERNIGHT_HANDLERS + DAYTIME_HANDLERS`.
  `_register_default_handlers` now registers all 15.
- **`src/scheduler/overnight.py`** — `run_1min_bar_collection` fires
  the new notification; new `run_attribution_resolution_and_notify`
  wrapper calls the resolver + posts the summary. `run_stress_test`
  now posts the pass/fail summary at the end.
- **`src/scheduler/watch.py`** — attribution-resolve branch delegates
  to `run_attribution_resolution_and_notify`; new stats-pulse done-flags
  initialized in `__init__` and reset in `_reset_daily_state`.

### Added (tests)

- **`tests/test_journal_stats.py`** — 9 tests covering empty DB,
  open-trade exclusion, quarantined exclusion, window boundaries
  (today / 7d / 30d / all_time), win rate math, excess-Sharpe minimum
  threshold, NULL excess_return handling, + 2 smoke tests for the
  notification formatter.
- **`tests/test_watch_handlers.py`** +6 `maybe_stats_pulse` tests: skip
  on weekend, fire at 7:45 / 12:00 / 16:05, idempotent per window,
  no-op between windows.

### Verified

- 85 tests pass across the relevant suites (registry, handlers, bootstrap,
  resilience, import, journal stats, repo structure).
- Frontend builds clean.
- `notify_trade_closed` now 37 lines — helper extraction brings it well
  under the 60-line cap.

## [v0.23.3] - 2026-04-16 — Hotfix: resolve_pending_outcomes future-window filter

Fourth bug from the Task 1 operational sweep — the `reresolve_attribution.py`
hotfix correctly skipped future-window rows during the *reset* step, but
the downstream `resolve_pending_outcomes()` function itself had no date
filter, so it still picked up every `pending` row including those whose
7-day outcome window is in the future. Each one caused a noisy
`YFPricesMissingError` in the logs and wasted ~0.5s on a dead yfinance call.

Observed on 2026-04-16 running `scripts/reresolve_attribution.py`: 180
fresh `pending` rows from today generated ~180 sequential yfinance error
logs. No data corruption — rows stay `pending` — but the watch loop's
nightly 4:30 PM ET resolution job would have reproduced the same error
storm indefinitely until all rows aged past their 8-day window.

### Fixed

- **`src/attribution/logger.py::resolve_pending_outcomes`** — added
  `AND DATE(scan_timestamp, '+8 days') <= DATE('now')` to the SELECT so
  rows whose outcome window is still in the future are skipped. Matches
  the same filter already present in `scripts/reresolve_attribution.py`.

### Added

- **`tests/attribution/test_resolver.py::test_resolve_pending_outcomes_skips_future_window_rows`**
  — regression test seeding 3 rows (old-resolvable / fresh-future /
  boundary-edge at exactly 8 days ago) and asserting the SELECT filter
  passes only the 2 elapsed-window rows to `_resolve_one_row`. Uses
  `patch()` on `_resolve_one_row` so no yfinance calls are made — the
  test isolates the SELECT filter contract.

### Authority

Error storm observed live during the `scripts/reresolve_attribution.py`
run on 2026-04-16; root-caused as a 4th operational bug that slipped
past the Task 1 audit.

## [v0.23.2] - 2026-04-16 — Asyncio Refactor Phase B (overnight extraction) + Phase C (tests)

First wave of `_run_sync_body` decomposition: the 14 overnight-schedule
tasks now live in a new module and run via the handler dispatch path.
Zero behavior change — done-flag semantics preserved, handler firing
times match the pre-refactor `elif` chain. `_run_sync_body` shrank from
740 → 631 lines; watch.py dropped from 2,041 → 1,941 lines (below the
pre-refactor baseline of 2,039).

### Added

- **`src/scheduler/watch_handlers.py`** (229 lines) — 14 module-level
  `maybe_<name>(watch, now)` handlers extracted from the
  `elif self.overnight and not self._is_market_open(now):` branch of
  `_run_sync_body`. Each checks its time window + done-flag and calls
  `watch._safe_run(...)`. `OVERNIGHT_HANDLERS` list exports them in
  registration order.
- **`HandlerRegistryMixin._dispatch_sync`** — sync-context dispatch so
  the `_run_sync_body` worker thread can fire handlers without crossing
  event-loop boundaries. Coroutine handlers get wrapped in `asyncio.run`;
  sync handlers run inline. Same exception contract as `_dispatch`.
- **`WatchLoop._register_default_handlers`** — single entry point called
  once at startup (between `_check_row_counts()` and the IB cold-storage
  banner) that `functools.partial(handler, self)`-binds each handler in
  `OVERNIGHT_HANDLERS` and registers on `on_tick`.
- **`tests/test_watch_handlers.py`** (25 tests) — per-handler unit tests
  (time window, done-flag respect, weekday gating, chained calls) plus
  integration tests: `_register_default_handlers` binds all 14 in the
  correct order, `_dispatch_sync` fires each handler at the right tick,
  and double-dispatch at the same tick is idempotent.
- **`tests/test_watch_handler_registry.py`** gains 4 `_dispatch_sync`
  tests (sync-handler inline execution, async-handler asyncio.run wrap,
  exception swallowing, registration-order preservation).

### Changed

- **`src/scheduler/watch.py::_run_sync_body`** now calls
  `self._dispatch_sync("on_tick", now)` once per tick, right after the
  midnight daily-state reset. The entire `elif self.overnight and not
  self._is_market_open(now):` branch (lines 1502-1627, 116 lines) is
  removed — its work is now done by the 14 registered handlers. The
  "overnight mode" heartbeat log line is omitted (the watchdog file
  heartbeat already covers the liveness signal).
- **`config/known_violations.json`** — `_run_sync_body` grandfather
  entry updated from 740 → 631 lines to reflect the size reduction.

### Verified

- All 13 existing `test_watch_*` tests pass unchanged.
- 16 handler-registry tests pass (12 Phase A + 4 new `_dispatch_sync`).
- 25 watch_handlers tests pass.
- 15 `test_repo_structure` tests pass.
- Frontend builds clean in 603ms.
- `WatchLoop(...).run()` signature preserved — NSSM / `src/cli/commands.py`
  callers unchanged.

### Not in this branch (queued for follow-up Phase B-continuation)

~20 remaining inline blocks in `_run_sync_body` — market-hours scans
(Tier 1-4), EOD recap cluster, digest schedule (4 windows),
Ollama/council/fundamentals, Saturday/Sunday reports, IB health
check, Telegram polling, earnings warning, action reminders. The
pattern is proven; extracting them is mechanical.

### Authority

`docs/sprints/sprint-asyncio-handler-refactor.md` Phase B (14 of 30+
extractions) + Phase C (mock-clock integration test for the extracted
subset).

## [v0.23.1] - 2026-04-16 — Asyncio Handler Refactor Phase A

Structural refactor of `src/scheduler/watch.py` — introduces an asyncio
event loop + handler registry without changing any observable behavior.
Foundation for Phase 6 intraday streaming (TradingStream, StockDataStream).

### Added

- **`src/scheduler/handler_registry.py`** (new, 69 lines) — `HandlerRegistryMixin`
  providing `run()` / `run_async()` / `on(event)` / `_dispatch(event, ...)`.
  Sync handlers are wrapped in `asyncio.to_thread` so they never block
  the event loop; coroutine handlers are awaited directly. Handler
  exceptions are logged and swallowed to match the `_safe_run` contract.
- **`tests/test_watch_handler_registry.py`** (new, 12 tests) — unit
  coverage for the registry: empty-start, decorator/direct-call
  registration, registration-order preservation, sync + async handler
  dispatch, exception isolation, unknown-event no-op, args/kwargs
  passthrough, `run()`→`run_async()`→`_run_sync_body()` delegation.
- **`docs/research/async-watch-loop-handler-pattern.md`** — handler
  pattern documentation as a public API for future developers, with
  canonical event names (`on_tick`, `on_fill`, `on_minute_bar`, etc.)
  and the Phase B / C / Phase 6 roadmap.

### Changed

- **`src/scheduler/watch.py::WatchLoop`** now inherits
  `HandlerRegistryMixin`. The pre-refactor `run()` method is renamed to
  `_run_sync_body()` and unchanged — Phase B will carve its 740 lines
  of time-window `if/elif` blocks into `_maybe_*` handlers registered
  on `on_tick`. Net +2 lines on `watch.py` (2,039 → 2,041) — the
  mixin keeps infrastructure out of the already-bloated host file.
- **`config/known_violations.json`** — grandfather entry updated from
  `run` (454 lines) to `_run_sync_body` (740 lines) to reflect the
  rename. Pre-existing debt carried forward, not worsened.

### Verified

- All 13 existing `test_watch_*` tests pass unchanged (zero behavior
  change).
- 12 new registry tests pass.
- 15 `test_repo_structure.py` tests pass (docstring, importability,
  60-line cap, 400-line cap, no-legacy-alpaca-SDK).
- NSSM / `src/cli/commands.py` callers unchanged — `WatchLoop(...).run()`
  signature preserved.

### Not in this sprint (explicit out-of-scope per spec)

- Phase B — extracting the 30+ time-window blocks from `_run_sync_body`
  into `_maybe_*` handlers registered on `on_tick`. Queued as
  `refactor/asyncio-phase-b-handler-extraction`.
- Phase C — mock-clock integration test that advances a WatchLoop
  through 24h and asserts every existing task fires at the right ET
  time. Queued as `refactor/asyncio-phase-c-mock-clock-integration`.
- Converting existing `_run_*` methods to `async def`. They stay sync,
  wrapped via `asyncio.to_thread` at dispatch time.
- Any streaming subscription (`TradingStream`, `StockDataStream`) —
  that is Phase 6.

### Authority

`docs/sprints/sprint-asyncio-handler-refactor.md`, drafted on
`docs/asyncio-refactor-spec` branch. This sprint executes Task 1 of
the spec's 5-task plan; Tasks 2-5 (extraction, dispatch switch, mock-clock
tests, docs) are follow-up branches.

## [v0.23.0] - 2026-04-16 — 1-Minute Bar Collection (Phase 6 Foundation)

Lays the data foundation for Phase 6 intraday-desk feasibility work per
`docs/research/deep-research/intraday-desk-feasibility-prompt.md`.
yfinance only exposes ~7 trading days of 1-minute history, so we begin
storing bars now to study historical microstructure when the time comes.

### Added

- **`minute_bars` table** (schema registry) — composite PK `(ticker, timestamp)`;
  OHLCV (REAL) + volume/trade_count (INTEGER); synced to Postgres
  incrementally via `sync_time_column="timestamp"`. ~2.3 MB/day / ~600 MB/yr.
- **`scripts/collect_1min_bars.py`** — yfinance-backed nightly collector
  for S&P 100. Rate-limited at 0.3s/ticker (≈31s wall time). CLI flags:
  `--date YYYY-MM-DD`, `--days N` (backfill up to 7d), `--dry-run`.
  Idempotent via `INSERT OR REPLACE` on the composite PK. Flattens
  yfinance MultiIndex columns (same fix pattern as SD#41 D2) and coerces
  NaN prices/volumes to NULL.
- **Overnight schedule wire-up** (`src/scheduler/watch.py`) — new
  `_1min_bar_collection_done` flag, reset daily, fires at hour 23 minute
  ≥30 ET (after enrichment precache, before the midnight flag reset).
  7-days/week like the other network-only collectors; empty weekend
  responses handled gracefully.
- **`tests/test_collect_1min_bars.py`** — 8 tests covering schema
  registration, MultiIndex flatten, NaN coercion, empty-response path,
  idempotent upsert, dry-run semantics, rate-limiting, and the
  previous-trading-day walker.

### Changed

- **`src/sync/render_sync.py`** — added `open`, `high`, `low`, `close`
  to `_REAL_COLUMNS` and `volume`, `trade_count` to `_INTEGER_COLUMNS`
  so `minute_bars` rows coerce cleanly on the Postgres side.

### Authority

Phase 1 decision #3 of `docs/research/deep-research/intraday-desk-feasibility-report.md` — begin storing 1-min bars now.

## [v0.22.1] - 2026-04-16 — alpaca-py Canonicalization (audit + guardrail)

Verification sprint — the `alpaca-py` migration was already complete; this
sprint documents the audit, tightens the version pin, and adds a CI
guardrail to prevent accidental reintroduction of the deprecated
`alpaca_trade_api` SDK. No runtime behavior changes.

### Changed

- **`requirements.txt`** — floor raised `alpaca-py>=0.30` → `alpaca-py>=0.43`
  to match the locally-installed/tested version and narrow the window
  for CI/dev drift.

### Added

- **`tests/test_repo_structure.py::test_no_legacy_alpaca_trade_api_imports`**
  — AST-walking guardrail over `src/` and `tests/` that fails if any
  `import alpaca_trade_api` or `from alpaca_trade_api ...` appears.
- **`docs/research/alpaca-py-current-best-practices-audit.md`** — per-call-site
  audit of `alpaca_adapter.py` (10 imports) and `executor.py` (3 imports)
  against the modern SDK idioms. Verdict: zero bugs; two improvements
  flagged as follow-up tickets (typed `APIError` handling, `client_order_id`
  for idempotency).
- **`docs/research/alpaca-py-intraday-streaming-gap.md`** — Phase 6 pre-work
  mapping `TradingStream` / `StockDataStream` integration points into the
  post-asyncio-refactor watch loop. No code; reference doc for the
  Phase 6 sprint.

### Verified

- Zero `alpaca_trade_api` references across `src/`, `tests/`, and all
  `requirements*.txt`.
- Zero streaming usage (`TradingStream` / `StockDataStream`) in `src/`
  — Phase 6 surface is intentionally empty.
- Installed `alpaca.__version__ == 0.43.2`.

### Authority

`docs/sprints/sprint-alpaca-py-migration.md`, drafted on the
`docs/alpaca-py-migration-spec` branch.

## [v0.22.0] - 2026-04-16 — Attribution Resolver MultiIndex Fix + Doc Sweep (SD#41 REVISED / D2 follow-up)

Ships the D2 follow-up fix (yfinance MultiIndex bug that corrupted 1,600
attribution resolutions) plus a comprehensive documentation sweep to
reflect the 4 merges from 2026-04-16 (v0.18.0 IB cold storage, v0.19.0
SPY excess instrumentation, v0.20.0 regime/sector diagnostic, v0.21.0
earnings filter hard block).

### Fixed — Part 1: Attribution resolver

- **`src/attribution/logger.py::resolve_pending_outcomes`** — flatten
  yfinance MultiIndex columns before building the OHLCV dict list.
  Before: `bar.get("Low", ...)` missed the tuple-keyed column, returned
  default `0`, and tripped the stop-first branch on day 1 of every
  resolution. After: `data.columns = data.columns.get_level_values(0)`
  normalizes to string keys so `bar.get("Low")` resolves correctly.
  `simulate_mechanical_outcome` itself is unchanged (kept pure-logic).

### Added — Part 1

- **3 new columns on `attribution_trades`:**
  - `resolution_version` (TEXT, indexed) — version tag for resolution
    logic. `'v1_multiindex_bug'` marks the buggy pre-fix rows;
    `'v2_fixed'` marks post-fix re-resolutions.
  - `ranker_only_outcome_v1` (TEXT) — archive of pre-fix outcome.
  - `ranker_only_pnl_pct_v1` (TEXT) — archive of pre-fix pnl_pct.
- **`scripts/reresolve_attribution.py`** — idempotent re-resolution
  script. Snapshots v1 values, resets bug-tagged rows to 'pending',
  calls the fixed resolver, tags newly-resolved rows as 'v2_fixed'.
  `--dry-run` flag snapshots only (no writes beyond the archive).
- **`tests/attribution/test_resolver.py`** — 6 regression tests covering
  the simulator (flat columns, timeout, loss) and the resolver
  data-shape contract (MultiIndex flatten, empty yfinance response,
  flat-columns compat).

### Re-resolution

1,600 `v1_multiindex_bug` rows were re-resolved under `v2_fixed`. V1
values preserved in archive columns for forensic comparison. The stop-
distance fingerprint that was universal in v1 is now absent in v2 (aside
from a small legitimate-stop minority). Outcome distribution shows real
`win` / `loss` / `timeout` spread, consistent with bull-market yfinance
paths over 7-day windows.

### Changed — Part 2: Doc Sweep

- **`MASTER.md` Section 1**: release line now v0.22.0; tech-stack trading
  line notes IB dormant per SD#41.
- **`MASTER.md` Section 2**: closed-trade count 18 → 85; test count 1,801
  → 1,852; dashboard pages 24 → 25; research docs 91 → 107; sprint docs
  43 → 57; PEAD entry removed (SD#3 eliminated); new "Attribution
  resolver FIXED" line.
- **`MASTER.md` Section 2 (new subsections)**: Forensic Analysis Status
  (D1/D2/D3 progress, Stage 1/2 OOS gates) and Permanent Methodology
  Guardrails (SD#41 REVISED).
- **`MASTER.md` Section 2 Diagnostic D2 Status**: CLOSED — citation
  freeze LIFTED for `resolution_version='v2_fixed'` rows.
- **`MASTER.md` Section 5**: heading "40 confirmed" → "41 confirmed";
  SD#3 marked ELIMINATED (PEAD dead); SD#17 marked COMPROMISED and then
  FIXED v0.22.0; SD#36 phase gate redefined; new SD#41 REVISED entry
  supersedes prior SD#41 trade-lifecycle synthesis.
- **`MASTER.md` Section 6**: Phase 1→2 gate redefined — excess-Sharpe
  ≥ 0.5 at t ≥ 2.0 over 150 OOS trades (raw Sharpe gate deprecated).
- **`MASTER.md` Section 8**: Revenue milestones shifted 6-12 months per
  SD#41 REVISED. Intraday desk feasibility research flagged.
- **`MASTER.md` Section 11**: Active Queue rewritten as SD#41 REVISED
  diagnostic-first plan. Prior queue moved to "Completed Sprints
  (historical)" subsection. New Research Queue subsection added.
- **`frontend/src/pages/Roadmap.jsx`** — Phase 1 gate metrics use
  excess-Sharpe + t-stat; IB activation row updated to reference cold
  storage + new gate.
- **`README.md`** — version badge v0.22.0; phase badge "diagnostic";
  test-count badge 1,852; Current Status reflects 85 closed + D1/D2/D3
  status + new Phase 1→2 gate.
- **`RELEASES.md`** — v0.22.0 entry with before/after + re-resolution
  stats.

### Authority

- Sprint spec: `docs/sprints/sprint-attribution-resolver-fix.md` (Part 1)
  + inlined doc sweep (Part 2 per user request)
- D2 audit: `docs/research/attribution-resolver-audit.md`
- Plan: `docs/research/SD-41-REVISED-diagnostic-first-plan.md`

## [v0.20.0] - 2026-04-16 — Regime & Sector Classifier Diagnostic (SD#41 REVISED / Sprint D3)

Closes the regime-NULL and sector-coverage gaps flagged in the forensic
report. No production code change — the enrichment bypass that caused
the 67% NULL `market_regime` was already fixed on 2026-04-14; this
sprint verifies coverage, adds regression tests so it can't silently
regress, backfills `realized_sector` to 100%, and clears up the label
vocabulary confusion between the regime classifier and the traffic
light.

### Diagnosed

- **`recommendations.market_regime` NULL anomaly** — classified as
  hypothesis (c) schema-recent scanner bypass. Per-day NULL rate cuts
  over cleanly at 2026-04-09 (100% -> 0%), matching the
  `attach_post_scan_features` deployment. 1,076 pre-2026-04-09 rows
  left as `NULL` accurately; they legitimately predate the fix.
- **Label-vocabulary confusion** — the codebase carries three distinct
  label systems: 5-state `compute_market_regime` (stored in
  `recommendations.market_regime`), 7-state `classify_regime`
  (canonical going forward), 3-state `traffic_light` (stored in
  `shadow_trades.regime_at_entry` despite the misleading column name).
  All three mapped in `docs/research/regime-classifier-audit.md`.
- **`recommendations.sector_context` 100% NULL** — documented as
  deprecated. Use `shadow_trades.realized_sector` or ticker-lookup via
  `data/reference/sp100-gics-lookup.csv` instead.

### Added

- **`tests/features/test_enrichment_coverage.py`** — 4 regression tests
  that grep the three scanner files for the `attach_post_scan_features`
  literal, plus a behavior test asserting `classify_regime` returns a
  label from the canonical 7-state set for representative inputs.
- **`docs/research/regime-classifier-audit.md`** — 243-line audit
  with label-source map, per-day cut-over evidence, sector backfill
  status, canonical vocabulary policy, and regression-protection summary.

### Changed

- **`data/shadow_trades.realized_sector` coverage now 100%** (226/226
  rows, zero NULL). D1 had backfilled the 85 closed rows; this sprint
  extended the backfill to the remaining 143 open/failed/pending rows
  (all S&P 100 tickers; GICS lookup had no gaps).

### Unchanged production code

No `src/` changes. The `attach_post_scan_features` call is present in
all three scanner paths in current main (`scheduler/universe_scanner.py`,
`services/scan_service.py`, `services/mr_scan_service.py`) and the bug
described in `src/features/enrichment.py:8-14` was remediated
2026-04-14.

### Deferred (out of scope)

- Regime classifier v2 / 7-state DB migration (SD#35, separate sprint).
- Renaming `shadow_trades.regime_at_entry` to `traffic_light_at_entry`
  (schema rename; requires data migration plan).
- Retroactively filling the 1,076 pre-2026-04-09 NULL rows (they
  accurately signal "enrichment not yet deployed").

### Authority

- Sprint spec: `docs/sprints/sprint-D3-regime-sector-diagnostic.md`
- Audit doc: `docs/research/regime-classifier-audit.md`
- Plan: `docs/research/SD-41-REVISED-diagnostic-first-plan.md`

## [v0.21.0] - 2026-04-16 — Earnings Filter Hard Block (SD#33 / Sprint H1)

Narrow scoring fix so trades are hard-blocked when earnings are scheduled
within ~7 trading days, regardless of the market-wide event risk score.
The earnings pipeline (scraper, lookup, scoring hook, risk governor, executor
tagging, dashboard field) was already fully built; the gap was a scoring-scale
mismatch. One-line threshold-override in `compute_event_risk_score` closes it.

### Fixed

- **`src/features/event_risk_score.py::compute_event_risk_score`** — earnings
  within 10 calendar days (~7 trading days, bounded by two weekends) now set
  `earnings_proximity = block_threshold` and floor `total_score` at
  `block_threshold`, guaranteeing `sizing_multiplier = 0.0` and triggering
  the existing `risk/governor.py:430` "Event risk hard block" reject path.
- `components["earnings_forces_block"]` (bool) is always present for
  downstream consumers, not just when earnings exist.

### The bug

Earnings <=2 days out added only +4 on a scale where hard-block threshold is
8. On calm market days (total_score < 4 before earnings), an earnings-imminent
ticker never crossed the threshold, and gap risk was unpriced. Per forensic
analysis, a non-trivial share of closed trades likely caught earnings
surprises mid-hold. Gap risk cannot be managed by stops, vol targeting, or
exits — only by not being in the position when earnings prints.

### Added

- **`tests/features/test_event_risk_earnings.py`** — 9 regression tests
  (core scenarios + parametric boundary at days_until=0/10/11 +
  earnings_forces_block key consistency when no earnings).
- **`tests/features/__init__.py`** — new test subdir.

### Changed

- **`tests/test_event_risk_score.py::test_compute_event_risk_score_adds_earnings_and_blocks`**
  updated to the new contract: `earnings_proximity = block_threshold` rather
  than the previous sliding +4/+2 schedule.

### Unchanged infrastructure (confirmed working — no rebuild)

- Nightly earnings scraper (`scripts/fetch_earnings_calendar.py`)
- Earnings lookup with yfinance fallback (`src/features/earnings.py`)
- Risk governor hard-block path (`src/risk/governor.py:430`)
- Executor earnings_adjacent flag (`src/shadow_trading/executor.py:570, 1934`)
- Schema `shadow_trades.earnings_adjacent` (INTEGER, default 0)

### Authority

- Sprint spec: `docs/sprints/sprint-H1-earnings-filter.md`
- Strategy Decision #33: MASTER.md Section 5, entry 33 (earnings 7-day
  exclusion zone; entry-exclusion layer now IMPLEMENTED, force-exit and
  post-earnings cooldown layers deferred)

## [v0.19.0] - 2026-04-16 — SPY-Matched Excess Instrumentation (SD#41 REVISED / Sprint D1)

Foundational alpha-vs-beta measurement. Every Sharpe metric can now
answer "real alpha, or just SPY drift?" Adds three columns to
`shadow_trades`, a SPY-benchmark utility, an idempotent backfill, a
dedicated API endpoint, and a Trade History lead panel. Redefines the
IB live-trading gate from raw Sharpe (trivially passed by bull-market
beta) to excess-return Sharpe.

### Added

- **3 columns on `shadow_trades`** (via `src/schema/registry.py`):
  - `spy_return_over_hold` (REAL) — SPY total return over the exact
    entry-to-exit date range, close-to-close, auto-adjusted
  - `excess_return` (REAL) — `pnl_pct - (spy_return * 100)`; positive
    means beat SPY over the same period
  - `realized_sector` (TEXT) — GICS sector from
    `data/reference/sp100-gics-lookup.csv`
- **`src/analytics/spy_benchmark.py`** — SPY return fetch via
  yfinance with fail-open semantics (`spy_return_over_range`,
  `excess_return`, `get_sector`)
- **`data/reference/sp100-gics-lookup.csv`** — 102 tickers mapped to
  11 GICS sectors; zero "Unknown" entries
- **`scripts/backfill_spy_excess.py`** — idempotent backfill for
  existing closed trades; `--dry-run` and `--force` flags
- **`/api/shadow/sharpe-attribution`** — primary metric endpoint
  with raw + excess Sharpe, 95% CIs, t-statistic, hit rate, and a
  verdict interpretation key (alpha_significant / alpha_suggestive /
  negative_alpha_* / alpha_not_demonstrated)
- **Trade History "Primary Metric" panel** — excess-Sharpe leads
  above the Today/Yesterday/7d/30d recency cards; raw Sharpe visible
  but demoted to footnote
- **`tests/analytics/test_spy_benchmark.py`** — 7 regression tests
  (pure-logic + mocked yfinance + sector lookup)

### Changed

- **IB live trading gate redefined:** excess-return Sharpe >= 0.5 at
  t >= 2.0 over 150 OOS trades. (Was raw Sharpe >= 1.0, trivially
  passed by SPY beta during a bull run.)
- **`src/journal/store.py::close_shadow_trade`** now centrally writes
  the three SPY fields on every exit (covers 5 executor call sites +
  3 reconcile call sites in one place). Fail-open: SPY yfinance
  exceptions never block trade close.
- **`src/sync/render_sync.py::_REAL_COLUMNS`** adds the two new REAL
  columns so the Postgres sync coerces them to float, not TEXT.

### Backfill

Live DB: 85/85 closed trades backfilled with SPY-matched excess
data, zero "Unknown" sectors. Second run of the backfill script
confirms idempotency (`updated=0, skipped_existing=85`).

### Rationale

Forensic analysis of 78 closed trades showed per-trade Sharpe 3.38
was mostly SPY beta during a bull run. Excess vs SPY = +0.039%,
t = 0.098 over 75 matched periods. Without this instrumentation we
cannot distinguish alpha from beta — every optimization decision
becomes directional noise chasing.

### Authority

- `docs/research/SD-41-REVISED-diagnostic-first-plan.md`
- Sprint spec: `docs/sprints/sprint-D1-spy-excess-instrumentation.md`
- Methodology: `docs/research/sharpe-attribution-methodology.md` (new)

## [v0.18.0] - 2026-04-16 — IB Cold Storage (SD#41)

Disable Interactive Brokers integration through Phase 1 while preserving
every line of IB code for fast reactivation. The entire change is gated by
a single `trading.ib_enabled` flag. Default Alpaca-only operation; flipping
the flag to `true` and restarting the watch loop restores prior behavior.

### Added

- **Top-level `trading.ib_enabled` flag** (default `false`) in
  `config/settings.example.yaml` and `config/settings.local.yaml`. Cross-cutting
  feature flag, distinct from `live_trading.broker` (which selects between
  brokers but no longer overrides the gate).
- **3 regression tests** (`tests/test_ib_cold_storage.py`) covering the
  fallback path, the explicit-opt-in escape hatch, and the default-config
  invariant.
- **Settings page Broker Status panel** — shows "Alpaca · Active" and
  "IB · Dormant (SD#41)" with a one-line note about reactivation.

### Changed

- **`broker_factory.get_live_broker`** falls back to Alpaca with a `[BROKER]`
  warning when `broker=ib` but `trading.ib_enabled=false`. IB
  instantiation code path is preserved verbatim, just gated.
- **`executor._select_paper_broker`** skips IB paper-routing entirely when
  cold-stored, so high-score paper trades stay on Alpaca.
- **`executor.open_shadow_trade` / `place_paper_exit`** skip IB shadow-log
  writes (entry + exit call sites) when cold-stored.
- **`reconcile.reconcile_paper_trades`** defers the IB position fetch when
  cold-stored. Tracked IB-broker positions (TGT, etc.) get a single
  `[RECONCILE]` info log per cycle indicating brackets resolve naturally.
- **`scheduler.watch.WatchLoop.run`** logs `[WATCH] IB integration dormant
  per SD#41. Alpaca-only mode.` once at startup, and short-circuits the
  IB Gateway health-check loop.
- **6 existing IB tests** now opt-in to the IB code path via
  `trading.ib_enabled=true` in their config dicts.

### Preserved (not deleted)

- `src/trading/ib_broker.py`, `src/trading/ib_shadow.py`
- `src/api/cloud_routes/ib_shadow.py`, `src/api/routes/ib_status.py`
- `ib_shadow_log` database table (queryable, just stops growing)
- `ib_async` dependency in `requirements.txt`
- All `live_trading.ib.*` config keys (host, port, paper_routing, shadow_mode)
- IBShadow.jsx component file (no route changes)

### Authority

- `docs/research/SD-41-defer-ib-integration.md`
- Sprint spec: `docs/sprints/sprint-ib-cold-storage.md`

## [v0.17.2] - 2026-04-15 — Hotfix: Grafana Cloud Loki MVP (SD#40) + NSSM service installer

Centralized log aggregation and 24/7 Windows service management, plus a
fix for the startup hang when Render Postgres is unreachable.

### Added

- **Grafana Cloud Loki integration** (SD#40). Raw HTTP handler
  `src/observability/loki_handler.py` ships logs to Grafana Cloud with zero
  new dependencies — uses `requests` only. QueueHandler+QueueListener
  non-blocking dispatch so the trading thread never waits on HTTP.
- **DedupFilter** attached to the Loki handler. Suppresses duplicate log
  messages within a 60s window to keep noisy repeats (e.g. `[SCHEMA]
  Created/verified 53 tables`) from consuming Grafana Cloud quota. File
  and console logging are unaffected.
- **Structured `ctx` → Loki labels.** `event` and `ticker` from the existing
  `extra={"ctx": {...}}` dict are promoted to Loki stream labels; all other
  ctx data rides along in the log-line text via `StructuredFormatter`.
- **New `ctx` tags** on two previously unstructured log lines:
  `shadow_trading.executor` trade-open (`event=trade_open`) and
  `shadow_trading.reconcile` stale-close (`event=stale_close`).
- **Cloud-side shipping.** `src/api/cloud_app.py` wires the Loki handler at
  startup using env vars (`GRAFANA_LOKI_TOKEN`, `GRAFANA_LOKI_URL`,
  `GRAFANA_LOKI_USER`) so the Render-deployed FastAPI also ships logs.
- **NSSM Windows service installer** at `scripts/install_service.ps1` —
  install / uninstall / restart / status commands. Configures AppDirectory,
  log rotation, AppExit Restart, and a 10s `AppRestartDelay` so the PID
  lockfile atexit hook can release before the next watch-loop launch.
- **Config scaffolding.** `config/settings.example.yaml` gains an
  `observability.grafana` section; `.env.example` gains a
  `GRAFANA_LOKI_TOKEN` placeholder.
- **5 new tests** in `tests/test_loki_handler.py` — disabled config,
  missing observability section, missing env-var token, DedupFilter
  suppression, DedupFilter window expiry. No network calls.

### Fixed

- **Startup hang on unreachable Render Postgres.** `psycopg2.connect()` had
  no `connect_timeout`, so libpq retried SYN indefinitely when the Render
  DB was paused. `create_all_tables` / `ensure_columns` gain an optional
  `connect_timeout` kwarg (default `None` preserves manual-migration
  behavior); the three startup-path call sites now pass
  `connect_timeout=5` so an unreachable DB becomes a warning instead of a
  hang.
- **Stale test baselines.** `tests/test_coerce_to_schema.py` targeted
  `planned_shares` (which flipped INTEGER→REAL in v0.17.1 for fractional
  shares) — retargeted onto the still-INTEGER `duration_days`.
  `tests/test_executor_event_risk_resolve.py` filtered caplog at ERROR
  but the function logs at WARNING — lifted to WARNING across three tests.

## [v0.17.1] - 2026-04-13 — Hotfix: test baseline + fractional shares

Post-v0.17.0 hotfix clearing 12 of 19 pre-existing test failures on main and
a latent fractional-shares source bug. Net: test baseline moves from 1738/1757
passing to 1750/1757 passing (7 structural/environment failures remain, tracked
as separate issues for targeted cleanup sprints).

### Schema

- **fix:** `training_examples` gains `updated_at` (TEXT) column. `GuardedScorer`
  issued `UPDATE training_examples SET quality_score_auto = ?, updated_at = ?`
  but the column was never defined in `src/schema/registry.py` — every
  between-scan rescore raised `sqlite3.OperationalError`. Column added,
  migration applied via `validate-schema --fix`. Fixes `test_scorer.py` × 3.
- **fix:** `shadow_trades.planned_shares` and `.actual_shares` changed from
  INTEGER to REAL. Alpaca fractional share counts (e.g. 0.30) were silently
  truncated to 0, then the positive-shares guard in `journal.store` rejected
  the backfill.

### Source

- **fix:** `BrokerPosition.quantity`, `BrokerOrder.quantity`, and
  `BrokerOrder.filled_qty` changed from `int` to `float` in
  `trading.broker_interface`. `alpaca_broker.py` stops wrapping share counts in
  `int(float(...))` — fractional quantities now survive the reconcile path
  end-to-end. Fixes `test_reconcile.py` × 2 (`backfills_orphaned`,
  `ignores_paper_trades`).

### Tests

- **fix:** `test_env_secrets.py::test_env_var_referenced_in_source` (× 6
  parametrized) rewrote from `subprocess.run(["grep", ...])` to pure Python
  `pathlib.rglob + read_text`. Windows subprocess can't pass the embedded
  double-quote in the search pattern, giving false negatives that bash
  execution didn't show.
- **fix:** `test_watch_resilience.py::test_heartbeat_command_callable` —
  import path updated from `src.notifications.telegram` to
  `src.notifications.telegram_commands` after the notifications split.
- **fix:** `test_ingestion.py` × 2 — replaced live `yfinance.download()` calls
  with `patch` + deterministic OHLCV stubs. Complies with CLAUDE.md's
  no-network-in-tests rule.
- **fix:** `test_news.py::test_historical_news_date_bounds` — patches
  `_load_cached` to None and strips `FINNHUB_API_KEY` from the env so the test
  actually exercises the "no API key" branch rather than returning stale cache
  data from a previous run.
- **fix:** `test_render_sync.py::test_healthy_connection_reused_without_reconnect`
  — patches `create_all_tables` and `ensure_columns` so schema-helper internal
  `psycopg2.connect` calls don't inflate the expected count from 1 → 3.

### API

- **chore:** Bump `app.version` in `src.api.app` and `src.api.cloud_app` from
  `1.0.0` to `0.17.1` to match release tagging.

### Deferred (tracked as issues)

- `test_vram_manager::test_handoff_to_training_unload_fails` — needs
  `_wait_for_vram_clear` mock to exercise the no-nvidia-smi unload-failure
  branch correctly.
- `test_repo_structure.py` × 2 — 2 files over 400-line limit
  (`src/api/cloud_routes/trades.py` 427, `src/email/digest_builder.py` 405)
  and 15 functions over 60-line limit — refactor per the lint contract.

## [v0.17.0] - 2026-04-12 — IB Integration Complete + Dashboard Overhaul + Training Backfill

Consolidates seven IB integration sprints (IB-1 through IB-7), four dashboard
sprints (DB-1, DB-2a, DB-2b, DB-3), one final cleanup sprint (DB-FINAL),
a capital-velocity instrumentation drop, and a 703-row regime-diverse training
backfill into a single tagged release. Sub-sections below keep the sprint-level
notes that previously lived under `[Unreleased]` so the ship history stays
traceable.

### DB-FINAL — Dashboard cleanup

- **fix:** `shadow_trades` gains `time_to_mfe_days` (INTEGER) and `mfe_timestamp`
  (TEXT) columns. Executor's `check_and_manage_open_trades` now updates both on
  every MFE high; flat and adverse cycles preserve the peak. 3 new tests cover
  the rise/flat/close paths (Strategy Decision #32 instrumentation).
- **fix:** Attribution logger warnings are visible (`logger.warning` instead of
  `logger.debug` in `scheduler/universe_scanner.py`) and a defensive
  `_parse_price` check skips attribution entirely when entry/stop/target parse
  to 0/None rather than writing corrupt zero-priced ranker-only pairs.
  `attribution_trades` already carries `sync_to_postgres=True`; integration test
  added.
- **feat:** Mobile sidebar collapse in `Layout.jsx` (hamburger + overlay backdrop,
  status bar hidden below md breakpoint), `min-h-[44px]` touch targets on nav
  links, `p-3 md:p-6 lg:p-8` main-content padding.
- **fix:** `Architecture.jsx` and `DBSchema.jsx` set `nodesDraggable={false}` +
  `nodesConnectable={false}`, `<MiniMap>` removed (bottom-right glitch).
  Architecture subtitle no longer advertises drag.
- **chore:** ~15 `data-testid` attributes on Health (hshs-radar, hshs-composite,
  build-score-card, ib-status-card, model-history), Validation
  (validation-category-{name}), Monitoring (resource-chart, ollama-status,
  disk-status, log-table) for the upcoming System Health consolidation.
- **refactor:** `space-y-4 md:space-y-6` roots across 14 dashboard pages.

### DB-3 — Responsive + polish

- **feat:** Architecture diagram shows IB Gateway infrastructure node + a
  `broker_router` → (`live_alpaca` | `live_ib`) execution split reflecting the
  score-gated dual-broker routing.
- **feat:** Simulation page gains a regime dropdown that highlights one equity
  curve and dims the rest (opacity 0.15).
- **feat:** `scripts/stress_test.py` adds 4 historical scenarios — 2018 Q4
  selloff, 2011 debt ceiling, 2015 China deval, 2024 yen unwind.
- **feat:** IB section on Settings page (shadow_mode, paper_routing, routing
  threshold, Gateway port, client_id).
- **feat:** New `/velocity` dashboard page renders hold-period distribution,
  time-to-MFE scatter (falls back to duration until the new column fills),
  MFE capture efficiency. Gated behind a 50-trade banner until statistically
  useful.

### DB-2b — Feature additions

- **feat:** `IB Shadow` → `Broker Comparison`; nav item moved from System to
  Trading. CTO report exposes a by-broker breakdown (win rate, avg/total P&L).
- **feat:** Logs page "Export errors" downloads ERROR+CRITICAL+WARNING entries
  (last 24h) as markdown; "Clear stale" resolves pending/claimed commands
  older than 1 hour.
- **feat:** `get_training_status` returns `outcome_counts` + `source_counts`
  so the Outcome Distribution card renders real data.
- **feat:** 9 additional IB research + ops docs indexed on the Docs page.
- **feat:** `run_data_collection` emits a per-collector success/failure line
  after the 12-step block.

### DB-2a — Bug fixes

- **fix:** Packets page strips everything before the first recognized XML tag
  so the analysis pane shows LLM output only.
- **fix:** `/live/trades` + `/api/live/trades` enrich open rows with
  `current_price` + unrealized `pnl_dollars` / `pnl_pct` (graceful fallback when
  `setup_signals` is missing).
- **feat:** `OpenPositionCard` — rich per-position monitor card (stop/entry/target
  progress gauge, MFE/MAE, bracket status, conviction, days held/timeout).
  Shadow Ledger open tab uses a card grid.
- **feat:** Ledger source toggle (All / Paper / Live) + broker filter (Alpaca /
  IB) + broker column on closed-trades table.
- **feat:** Strategy page Drawdown chart is now a ComposedChart with green/red
  per-trade bars overlaid on the drawdown area.
- **fix:** Stress Test groups runs by scenario; only the latest per scenario
  renders, rest collapse into a "Previous Runs" archive.
- **fix:** Monitoring page crash — `Array.isArray(history) ? history : []`.

### DB-1 — Data integrity + quarantine sync

- **fix:** `scripts/sync_quarantine_to_postgres.py` one-time migration pushes
  locally-quarantined `shadow_trades.quarantined=1` rows to Render Postgres.
  The incremental sync uses `updated_at > last_synced_at` as its cursor — prior
  quarantine UPDATEs didn't touch the column, so ~17 issues were served
  compromised rows even though `COALESCE(quarantined, 0) = 0` was correctly
  applied in every cloud route.
- **fix:** `scripts/quarantine_april10.py` bumps `updated_at` on every UPDATE so
  future runs sync automatically.
- **fix:** `scripts/backfill_model_version.py` backfills
  `recommendations.model_version = 'halcyon-v1.0.0'` for NULL rows, unblocking
  Model Performance attribution.
- **fix:** `get_active_model_name()` falls back to Ollama `/api/ps` then
  `llm.model` when `model_versions` has no active row; new
  `src.llm.client.get_loaded_model_name` helper.
- **fix:** Header version resolves from `ARCIS_VERSION` env →  `VERSION` file →
  `git describe --tags --abbrev=0` → hardcoded fallback (`lru_cache`'d).
- **fix:** DB Schema page renders live table count + cluster-config domain
  count instead of hardcoded "40 tables across 6 domains".
- **fix:** Settings page — `shadow_trading.timeout_days` + `strategies.pullback.timeout_days`
  resolve to actual keys; Min Conviction Score renders "Disabled" at 0/null;
  System Health shows "CLOUD (local status unavailable)" on cloud mode.
- **fix:** HSHS Flywheel Velocity anchors on completed train-deploy cycles
  (`version_count - 1`); scores zero with one deployed model. Data growth and
  recent-volume signals scale by a spin factor.
- **fix:** `council/value_tracker.py` track-record join adds
  `COALESCE(st.quarantined, 0) = 0`.
- **feat:** `council.auto_apply_parameters` config flag (default **false**).
  Advisory-only mode logs recommendations but does NOT rewrite live config.
  Session meta carries `advisory_only` for the dashboard.

### Training backfill

- **data:** 703 regime-diverse training examples imported — broadens v2 dataset
  from 1,019 to 1,722 examples spanning every market regime in the backfill
  sample. Conviction recalibrated (range 1-8, down from 5-9). Leakage check
  passed (59.8%). Halcyon-v2.0.0 retrain pipeline in progress.

## [Unreleased] — Dashboard Data Integrity (Sprint DB-1)

### Data fixes
- **fix:** `scripts/sync_quarantine_to_postgres.py` — one-time migration that pushes
  locally-quarantined `shadow_trades.quarantined=1` flags to Render Postgres. The
  normal sync is incremental on `updated_at`; quarantine UPDATEs run by
  `scripts/quarantine_april10.py` never touched that column, so 17+ issues across
  the dashboard were reading compromised rows despite every cloud route filtering
  on `COALESCE(quarantined, 0) = 0`. The filter was correct; the data wasn't.
- **fix:** `scripts/quarantine_april10.py` now also bumps `updated_at` on every
  UPDATE so future runs sync automatically without a dedicated migration.
- **fix:** `scripts/backfill_model_version.py` — one-time backfill of
  `recommendations.model_version = 'halcyon-v1.0.0'` for NULL rows, unblocking
  Model Performance dashboard attribution.

### Detection + display
- **fix:** `get_active_model_name()` now falls back to Ollama (`/api/ps`) then the
  config `llm.model` value when `model_versions` is empty. Cloud deployments with
  an unpopulated table no longer report a misleading "base".
- **feat:** `src.llm.client.get_loaded_model_name()` — non-recursive helper used by
  the versioning fallback.
- **fix:** Header bar version string is now resolved from `ARCIS_VERSION` env var
  → `VERSION` file → `git describe --tags --abbrev=0` → hardcoded fallback, with
  `lru_cache` so each request is cheap.
- **fix:** DB Schema page reads the live table count from `/system/table-counts`
  and the domain count from the cluster config instead of hardcoding
  "40 tables across 6 domains".
- **fix:** Settings page — `shadow_trading.timeout_days` and
  `strategies.pullback.timeout_days` now resolve to actual config keys; Min
  Conviction Score renders a "Disabled" pill when the value is 0 or null.
- **fix:** System Health indicators display "CLOUD" (title: "local status
  unavailable") instead of "Off" when running against the cloud API, which
  cannot reach local services like Ollama.

### Metrics
- **fix:** HSHS Flywheel Velocity anchors on completed train-deploy cycles
  (`version_count - 1`); scores zero with only one deployed model. Data growth
  and recent volume are scaled by a spin factor that's zero until the first
  cycle, so mere data accumulation no longer inflates the score.
- **fix:** Council agent track-record query in `value_tracker.py` now applies
  `COALESCE(st.quarantined, 0) = 0` to the `shadow_trades` join.

### Safety
- **feat:** `council.auto_apply_parameters` config flag (default **false**).
  While false, the council logs recommended parameter changes for counterfactual
  attribution but does NOT rewrite live config. Enforces the FINSABER Phase 1
  authority boundary. Session result JSON now carries
  `session_meta.advisory_only` so the dashboard can label sessions as advisory.

### Tests
- **test:** `test_versioning.py` — new `monkeypatch`-based test for the Ollama
  fallback path of `get_active_model_name`.

## [Unreleased] — IB Integration Validation (Sprint IB-7)

### Integration Tests (16 tests)
- **test:** End-to-end IB + Alpaca trade lifecycle with broker field tracking
- **test:** Cross-broker position counting — governor, reconciler, executor all agree
- **test:** Config progression matrix — shadow → routing → live transitions
- **test:** Failure/recovery simulation — fallback, resume, mixed broker state
- **test:** Multi-broker API responses — schema columns, status mapping

### Operational Tooling
- **feat:** `scripts/validate_ib_integration.py` — data completeness checker across
  shadow_trades, ib_shadow_log, daily_ib_health, schema columns
- **docs:** `docs/operations/ib-smoke-test.md` — 6-phase manual validation checklist
  (shadow mode → dual routing → bracket monitoring → failure recovery → dashboard → scripts)

## [Unreleased] — IB Paper Trading Activation (Sprint IB-6)

### Validation & Monitoring
- **feat:** `scripts/validate_ib_gateway.py` — validates paper account setup, qualifies 10
  S&P 100 contracts, checks buying power, tests market data. REFUSES port 4001 (live).
- **feat:** `daily_ib_health` schema table — tracks uptime_pct, trade_count, error_count,
  reconnect_count. 30-day gate: >95% market-hours uptime.
- **feat:** IB Gateway status card on Health page — connection status, shadow mode, trade
  count, uptime, last connection timestamp
- **feat:** IB section in EOD digest — connection uptime %, IB vs Alpaca routing breakdown,
  errors/fallbacks (conditional on shadow_mode or paper_routing enabled)

### Operations
- **docs:** `docs/operations/ib-gateway-setup.md` — IBC config, Windows hardening, TDR fix,
  Java heap, Sunday 2FA procedure, troubleshooting

### Tests
- 5 tests: validation script live port refusal, daily_ib_health schema + SQLite creation,
  digest section conditional logic

## [Unreleased] — IB Production Hardening (Sprint IB-5)

### Connection Resilience
- **fix:** `_ensure_connected()` with exponential backoff (3 retries: 1s, 2s, 4s)
- **feat:** `_verify_bracket_integrity()` checks all positions have active stops after reconnect
- **feat:** Connect/disconnect pattern — fresh connection each poll cycle, rebuild state from server

### Order Safety
- **fix:** `outsideRth=True` on ALL orders — protective orders execute outside regular hours
- **fix:** `ocaType=3` on bracket children — block/overfill protection prevents dual fills
- **feat:** `permId` stored for cross-session tracking (survives Gateway restarts)
- **feat:** Partial fill detection with warning log

### Status Normalization
- **feat:** `IB_STATUS_MAP` normalizes IB statuses (PreSubmitted→pending, Inactive→rejected, etc.)
- **feat:** `_handle_ib_error()` classifies common IB error codes (110, 135, 200, 201, 202)

### Schema
- **schema:** Added `ib_perm_id` column to `shadow_trades` for cross-session order tracking
- **schema:** Added `perm_id` field to `BrokerOrder` dataclass

### Tests
- **test:** 16 tests for reconnection, bracket verification, status mapping, partial fills,
  outsideRth/ocaType, error codes, permId

## [Unreleased] — IB Dual-Execution Routing (Sprint IB-4)

### Score-Based Paper Broker Routing

- **feat:** `_select_paper_broker()` routes paper trades to IB when score >= threshold
  (default 80) and `live_trading.ib.paper_routing: true`. Falls back to Alpaca with
  warning if IB Gateway is down.
- **feat:** `open_shadow_trade()` uses the router — IB paper bracket orders placed via
  broker abstraction, Alpaca path unchanged for below-threshold trades.
- **feat:** `reconcile_paper_trades()` checks correct broker per trade — IB trades
  validate against IB positions, Alpaca trades against Alpaca positions.
- **config:** `live_trading.ib.paper_routing` (bool) + `paper_routing_threshold` (int)
- **test:** 12 tests — routing logic, fallback, cross-broker counting, Alpaca regression

## [Unreleased] — IB Shadow Dashboard + API Routes

### IB Shadow Dashboard

- **schema:** Enabled Postgres sync for `ib_shadow_log` (incremental, keyed on `shadow_id`)
- **feat:** 3 cloud API routes (`/api/ib-shadow/summary`, `/api/ib-shadow/log`, `/api/ib-shadow/health`)
- **feat:** IB Shadow dashboard page with KPI cards (shadow count, gateway uptime, contract valid, BP acceptance), trade log table, and error log
- **feat:** Navigation entry in System section (GitCompare icon)
- **feat:** Empty state with setup instructions when no shadow data exists

## [Unreleased] — IB Structural Fixes (Sprint IB-2)

### Critical Runtime Bug Fixes

- **fix:** `get_live_broker()` called without config arg — TypeError on live path
- **fix:** `get_positions()` → `get_all_positions()` + `p["symbol"]` → `p.ticker`
- **fix:** IB bracket child order IDs now stored (enables bracket health monitoring)
- **fix:** Bracket exit monitoring routes through broker factory for live trades
- **fix:** `_retry_exit` cancel uses broker factory for live/IB trades
- **fix:** Risk governor uses IB account equity when `broker=ib`
- **fix:** Live reconciler cancels IB orders before closing stale trades
- **fix:** IB `get_position` fetches current price via market data snapshot
- **fix:** Startup check validates `ib_async` availability when IB configured

### Schema

- Added `ib_child_order_ids` column to `shadow_trades`
- Added `broker_order_id` alias column (prep for `alpaca_order_id` migration)

## [Unreleased] — IB Test Coverage + Shadow Mode (#368)

### IB Broker Unit Tests (24 tests)

- **test:** Full unit test coverage for all 10 `BrokerAdapter` methods on `IBBroker`
  via mock factories (no ib_async dependency required). Covers happy paths (10),
  error handling (8), and edge cases (6) — connection lifecycle, bracket orders,
  market orders, exits, cancellations, positions, price snapshots.
- **test:** Mock factory helpers in `tests/conftest_ib.py` for all 6 ib_async
  object types (AccountValue, Trade, Position, Order, Stock, Ticker).

### IB Shadow Mode

- **feat:** `IBShadowLogger` class (`src/trading/ib_shadow.py`) — validates IB
  Gateway connectivity, contract validity, and buying power for each Alpaca
  trade WITHOUT submitting orders. Stores comparison data in `ib_shadow_log`.
- **schema:** Added `ib_shadow_log` table (17 columns, sync_to_postgres=False).
- **feat:** Executor hooks in `open_shadow_trade()` and `open_live_trade()` —
  non-blocking, wrapped in try/except, only fires when `ib.shadow_mode: true`.
- **test:** 6 shadow logger tests + 2 executor integration tests.

## [v0.16.12] - 2026-04-11

### Trading safety + security batch (#361, #363, #369, #370, #380)

**Trading safety (#369, #370):**
- **fix:** Replaced 6 `except Exception: pass` blocks in `executor.py` with
  `logger.warning()` — critical trading notifications (buying-power crisis,
  unprotected positions, exit circuit breaker) were silently swallowed
- **fix:** Added argument validation to `test_retry_exit_called_for_exit_failed`
  (`assert_called_once_with` instead of `assert_called_once`)
- **fix:** Added explicit assertion to `test_missing_table_does_not_raise`

**Security (#361, #363, #380):**
- **fix:** Added column allowlist in `attribution/logger.py` — dynamic SQL
  SET clause now validates columns against `_ALLOWED_ATTRIBUTION_COLUMNS`
- **fix:** Replaced `.format()` SQL in `value_tracker.py` with parameterized
  `?` placeholders for the `IN` clause
- **fix:** Replaced raw `str(exc)` in 5 command executor error responses with
  generic error categories — full details logged server-side only

## [v0.16.11] - 2026-04-11

### Fix: Test regressions — buying power mock + training gate assertion (#239, #371, #372)

- **fix:** Added `get_account_info` mock to `TestPaperSourceTagging` and
  `TestDualExecution` — tests failed because `_check_paper_buying_power()`
  returns $1 with placeholder API keys (#371, #239)
- **fix:** Updated `test_markdown_bold_heading_rejected` to use a standalone
  bold heading line (`**Market context:**\n`) instead of inline bold-then-text.
  The regex was intentionally narrowed in #334 to allow inline emphasis; the
  test wasn't updated (#372)
- **fix:** Fixed `test_daily_loss_guard_halts_trading` — the daily loss guard
  queries the DB directly, not `get_open_shadow_trades`. Test now inserts a
  losing live trade into tmp_db so the guard finds it.
- **fix:** Fixed `test_generate_create_sql_basic` — SQLite generator inlines
  `PRIMARY KEY` on single INTEGER columns (ROWID alias). Test was asserting
  the separate `PRIMARY KEY (id)` constraint form.

## [v0.16.10] - 2026-04-11

### P2 batch: research feeds, CBOE scraper, buying power race condition (#389-392)

- **fix:** Research feeds (#389): Removed dead Anthropic `/feed.xml` (404) and
  OpenAI `/blog/rss/` (403) URLs. Replaced Anthropic with `/research/rss.xml`.
  Added `Accept` header to SSRN request. Increased arXiv timeout to 60s.
- **fix:** CBOE scraper (#390): Demoted regex-failure log from `warning` to
  `debug` — the SPY proxy and FRED fallbacks already produce reliable data.
  The regex breaks every time CBOE changes their HTML.
- **note:** NULL ids (#391): Investigated and confirmed already resolved —
  SQLite `INTEGER PRIMARY KEY` auto-assigns ROWIDs. Current state: 459K rows,
  0 NULL ids. The auto-repair messages in logs were from a one-time migration.
- **fix:** Buying power race condition (#392): Added per-scan-cycle committed
  capital tracker in executor. Previously N trades each passed the buying power
  check individually but together exhausted capital. Now
  `_scan_cycle_committed` subtracts capital from earlier orders in the same
  batch before checking. Reset at scan start via `reset_scan_cycle_committed()`.

## [v0.16.9] - 2026-04-11

### Root cause gap closures for #383, #386, #388

- **fix:** Added `_coerce_to_schema` to `update_recommendation()` — was unprotected
- **fix:** Refactored direct SQL UPDATE in `executor.py:650` to use
  `update_shadow_trade()` — was bypassing the coercion write boundary
- **fix:** Council dynamic weights: aggregate net PnL per day before joining
  to votes, preventing many-to-many inflation where 1 vote × 5 trades = 5
  data points. Added `session_type` filter to the query.
- **fix:** Applied circuit breaker to `generate_structured()` — was unprotected
  against Ollama outages, burning 180s timeouts independently of `generate()`

## [v0.16.8] - 2026-04-11

### Hotfix: Ollama timeout resilience — circuit breaker + auto-restart (#388)

- **fix:** Added consecutive failure tracking (circuit breaker) to `generate()` —
  after 3 failures, skips immediately instead of burning 180s timeouts per call.
  Previously 15 consecutive timeouts wasted 45 minutes on Apr 10 evening.
- **fix:** Auto-restart mechanism: when circuit breaker trips, attempts to restart
  Ollama via `ollama serve` before giving up
- **fix:** 2-second cooldown between inference calls to prevent Ollama overload
  during batch processing (10-20 tickers per scan cycle)

## [v0.16.7] - 2026-04-11

### Hotfix: Training pipeline — em-dash SyntaxError + GGUF fallback + Modelfile path (#387)

- **fix:** Replaced Unicode em-dash with ASCII `--` in `training_data/train.py:78`
  — Windows cp1252 subprocess could not parse the UTF-8 character, blocking
  the entire training script from loading
- **fix:** Added CPU-based GGUF conversion fallback via llama.cpp when Unsloth
  GPU export fails due to insufficient VRAM (RTX 3060 12GB)
- **fix:** Modelfile path now uses `.as_posix()` for forward slashes — was
  writing Windows backslashes into the `FROM` directive

## [v0.16.6] - 2026-04-11

### Hotfix: Council dynamic weights query — fix broken join (#386)

- **fix:** Replaced broken `JOIN shadow_trades st ON cs.session_id = st.session_id`
  (column never existed) with date-based join `ON date(cs.created_at) = date(st.created_at)`.
  Council sessions are market-level, not per-trade — votes are matched to trades
  opened on the same day.
- **fix:** Added `float()` cast on `pnl_dollars` comparison (defense-in-depth for #383)

## [v0.16.5] - 2026-04-11

### Hotfix: Auto-fix Postgres schema drift during startup (#385)

- **fix:** Startup sequence now runs `create_all_tables()` + `ensure_columns()`
  against Render Postgres automatically, matching the SQLite auto-fix pattern.
  Previously only warned about drift (filed 8 times as #184, #285, #307, #331,
  #332, #338). Missing tables and columns are now created on every startup.

## [v0.16.4] - 2026-04-11

### Hotfix: LLM output quality — repeat penalty + output validation (#384)

- **fix:** Added `repeat_penalty: 1.15` to Ollama API calls in `src/llm/client.py`
  to suppress degenerate repetition loops (52 debug log files showed `===` or
  data fields repeated 10-82 times)
- **fix:** Added `_validate_llm_output()` pre-parser in `src/llm/packet_writer.py`
  that rejects responses containing prompt leakage (37% of debug logs), template
  stubs (10%), and repetition loops (14%) before they reach the XML parser
- **test:** 10 tests for `_validate_llm_output` covering all rejection categories

## [v0.16.3] - 2026-04-11

### Hotfix: Write-boundary type coercion for shadow_trades (#383)

- **fix:** Added `_coerce_to_schema()` to `src/journal/store.py` — coerces dict
  values to match schema registry column types (REAL→float, INTEGER→int) before
  INSERT/UPDATE. Applied to `insert_shadow_trade()`, `update_shadow_trade()`,
  and `log_recommendation()`. This is the systemic root cause behind 10+ prior
  issues where `pnl_dollars`, `entry_price`, `price_at_recommendation` etc.
  were stored as strings, causing TypeErrors in 8+ downstream subsystems.
- **test:** 13 tests for `_coerce_to_schema` covering string→float, None
  preservation, unknown tables/columns, invalid values, and multi-column
  coercion.

## [Unreleased] — Manual Backfill Pipeline

### Historical Backfill: Manual Generation Workflow

**New modules:**
- `src/training/regime_sampler.py` — regime-targeted date selection, stratified sampling, FRED macro formatting, and dataset balancing helpers (moved from backfill.py)
- `scripts/export_backfill_prompts.py` — exports regime-targeted prompt files with real FRED macro context for manual generation via Claude/ChatGPT
- `scripts/import_backfill_results.py` — validates XML, pairs with sealed outcomes, inserts into training_examples (idempotent)
- `scripts/backfill_progress.py` — visual per-regime progress tracker

**Enhancements:**
- `src/training/historical_data.py` — FRED historical series fetch (`fetch_fred_history`) + point-in-time lookup (`get_fred_value_as_of`)
- `src/training/historical_scanner.py` — FRED macro enrichment in scan pipeline, PASS example generation (score 45-69), `generate_backfill_example()` handles outcome=None
- `src/llm/prompts.py` — `PASS_ANALYSIS_PROMPT` for below-threshold setups (conviction 1-4, NEUTRAL direction)

**Refactors:**
- `src/training/backfill.py` — 445→343 lines; `_balance_dataset`, `_deduplicate_candidates`, `_cap_and_diversify` moved to `regime_sampler.py`

**Tests:** 16 new tests (6 FRED history + 10 regime sampler); all 40 pass

## [v0.16.2] - 2026-04-11

### Hotfix: MR scan broken import (#382)

- **fix:** Corrected import path `src.journal.recommendation_logger` →
  `src.journal.store` — the `recommendation_logger` module never existed;
  `log_recommendation()` lives in `store.py`. Mean-reversion scanning has been
  fully disabled since April 9.

## [v0.16.1] - 2026-04-10

### Hotfix: pandas 3.0 import deadlock on Windows

- **fix:** Pin `pandas>=2.2,<3.0` in requirements.txt — pandas 3.0.1 C extensions
  deadlock on import under Python 3.13 + Windows (DLL loading hang in
  `pandas._libs.pandas_parser`)
- **fix:** Recreate venv with pandas 2.2.3 to restore `startup` / watch loop

## [v0.16.0] - 2026-04-10

### Trade Reconciliation Hardening & Data Quarantine

**Security (#348, #349):**
- **fix:** Local API binds to 127.0.0.1 (was 0.0.0.0)
- **fix:** Cloud API raises RuntimeError when API_SECRET is empty

**Order Submission (#352, #353, #359, #360):**
- **feat:** Post-submission order verification via `verify_order_accepted()`
- **fix:** Typed exception handling — ConnectionError/TimeoutError, APIError, Exception
- **feat:** Entry retry with ghost position check on network errors
- **feat:** exit_order_id stored immediately after exit submission

**Reconciler (#354, #356, #357, #358):**
- **fix:** Backfilled orphans get 5% stop/target defaults (was zero)
- **feat:** `cancel_orders_for_ticker()` called before closing stale positions
- **fix:** Alpaca position check before entry prevents duplicate ghost positions
- **feat:** Telegram alert after 3+ consecutive buying power failures
- **feat:** `submission_uncertain` trades resolved by reconciler

**Status Model (#355):**
- **feat:** TERMINAL_STATUSES / ACTIVE_STATUSES constants in models.py
- **fix:** Buying power rejections use status='rejected' (was 'failed')

**Data Quarantine:**
- **feat:** `quarantined` column added to shadow_trades
- 77 compromised records flagged (42 rejected, 34 stale, 1 orphan WMT)
- 18 verified trades preserved ($603.96 P&L, 83.3% win rate)
- All shadow_trades queries filtered on quarantine column
- **fix:** TEXT-to-REAL type casting in shadow_service (TypeError)

**Infrastructure (#328, #350, #351):**
- **fix:** latest_collection date format truncated to date-only
- **fix:** Watch loop done-flags moved inside try blocks
- **test:** Executor entry path coverage added

## [v0.15.3] - 2026-04-08

### Production Sweep — 14 issues closed in 3 phases

**Phase 1 — CRITICAL (v0.15.1):**
- **fix:** Stop-price > 0 guard before bracket order placements (#326)
- **fix:** Fractional share tolerance — alpaca adapter returns float qty (#325)
- **fix:** Conviction extraction stages 7-8 + parse rate logging (#329)
- **fix:** safe_numeric for quality_score_auto, int() cast on config thresholds (#330)
- **fix:** Overnight training script import path verified (#335)

**Phase 2 — HIGH (v0.15.2):**
- **fix:** Postgres create_all_tables + ensure_columns at sync startup (#331)
- **fix:** macro_snapshots sync_conflict_col for duplicate key prevention (#332)
- **fix:** DDL guardrail verified clean (#327)
- **fix:** Data collection stats COALESCE for column compatibility (#328)

**Phase 3 — MEDIUM (v0.15.3):**
- **fix:** NULL PK inline PRIMARY KEY root cause verified (#302)
- **fix:** Research source caching + 30s timeout + retry with backoff (#303)
- **fix:** VRAM handoff 3-retry logic with Telegram alert (#304, #333)
- **fix:** Ingestion gate narrowed for inline bold emphasis (#334)

## [Unreleased — pending v0.15.0]

### Gap Assessment (merged 2026-04-07)
- **feat:** Embedding-based semantic leakage detection — Ollama + LogisticRegression classifier (#295)
- **feat:** Dynamic Bayesian agent weighting for AI Council — Beta posterior, feature flag, 12-week window (#296)
- **feat:** Two-tier relative strength — 60% vs SPY + 40% vs sector ETF, 11 sector ETFs mapped (#297)
- **test:** 7 ranker tests (two-tier RS, pullback bounds, volume weight, backward compat, score cap)
- **test:** 6 council aggregation tests (dynamic weights, floor enforcement, normalization, fallback)
- **test:** 6 embedding leakage tests (mock Ollama, graceful fallback, threshold, class balance)

### Pending merge
- feat/simulation-engine: 13-scenario engine, Monte Carlo, TL validation, dashboard page
- feat/model-performance: per-model metrics, regression alerts, dashboard page
- feat/ui-bloomberg: Bloomberg Terminal aesthetic on all 18 pages

## [v0.14.2] - 2026-04-06

### Hotfix merge sprint — 6 critical production bugs + codex fixes + dependencies

**Critical fixes (PR #313):**
- **fix:** Shadow trade exit cascade — `exit_failed` status + circuit breaker + `cancel-all-pending` CLI (#310)
- **fix:** Type-safety gaps — `safe_numeric` utility for traffic_light, VIX alerts, EOD report (#311)
- **fix:** LLM conviction parsing — Stage 6 catch-all regex + debug file logging (#309, #312)
- **fix:** Risk governor TypeError — `safe_numeric` coercion at `check_trade` entry (#308)
- **fix:** Postgres schema drift — startup drift check + broker column (#307)

**Codex fixes (PR #305):**
- **fix:** Ingestion gate markdown detection narrowed to line-leading headings (#299)
- **fix:** Type-safety in notifications/digests (#300)
- **fix:** Fundamentals refresh import drift (#301)

**Other:**
- **feat:** Structured logging with `|ctx:{}` for AI agent review (#314)
- **fix:** load_dotenv() in config loader — .env works from any entry point (#317)
- **build:** 9 Dependabot PRs (CI actions, npm bumps, yfinance range)
- **chore:** 33+ stale branches deleted

## [v0.14.1] - 2026-04-05

### Log Audit Hotfix (14 production issues)

Full audit of 15K-line arcis.log identified and fixed 14 issues across 8 modules.

**Critical:**
- #279: Bracket monitor strips Alpaca enum prefix from leg statuses + adds `accepted` to ACTIVE_LEG_STATUSES (was reporting 0/N protected)
- #280: Earnings signals column names corrected to schema registry (actual/estimate/metric)

**High:**
- #281: Overnight training script imports fixed (was referencing wrong module paths)
- #282: Position monitor casts timeout_days from SQLite TEXT to int
- #283: Regime refresh passes ohlcv_data argument to sentiment_scanner
- #284: HSHS performance sub-score casts SQLite TEXT to float before abs()
- #285: Training data_collector casts to float before %.2f format string

**Medium:**
- #286: Postgres sync null ID guard + duplicate primary key handling
- Stress test VIX symbol handling fixed
- EOD recap format string type safety

**Audit report:** `docs/audits/log-audit-2026-04-04.md`

---

## [v0.14.0] - 2026-04-05

### Interactive Brokers Integration — Broker Abstraction Layer

5 new files, 19 new tests. Multi-broker architecture deployed.

**New modules:**
- `src/trading/broker_interface.py` — Abstract BrokerAdapter (10 methods) + normalized dataclasses
- `src/trading/broker_factory.py` — Singleton factory, config-driven routing (`"ib" | "alpaca"`)
- `src/trading/ib_broker.py` — IB adapter via ib_async, lazy connection, GTC bracket orders
- `src/trading/alpaca_broker.py` — Thin wrapper over existing alpaca_adapter.py
- `tests/test_broker_interface.py` — 19 tests (interface compliance, factory routing, dataclasses)

**Architecture changes:**
- Live trading routes through broker factory: `get_live_broker(config)` instead of direct Alpaca
- Schema: `broker` column added to `shadow_trades` (default "alpaca")
- Config: `settings.example.yaml` updated with IB settings (host, port, client_id)
- Paper trading unchanged (Alpaca direct, no abstraction needed)

---

## [v0.13.0] - 2026-04-04

### Gap Analysis Rectification — 23 Issues Resolved in 3 Tiers

19 files changed, +414 -157. 0 open issues.

**Tier 1 — CRITICAL (6 issues, money at risk + training data):**
- #272: Live trading now enforces RiskGovernor + LLM validator (was bypassed entirely)
- #274: Bracket fallback places standalone stop-loss (was naked market entry)
- #275: Daily loss guard uses today's realized P&L (was all-time unrealized)
- #277: Feature sanitization BEFORE LLM generation (self-blinding leak fixed)
- #273: Empty-output templates excluded from training dataset
- #278: Partial fills tracked correctly (was recording as full close)

**Tier 2 — HIGH (7 issues, reliability):**
- #271: MR exit passes all required args to close_shadow_trade
- #276: Duplicate position check + insert in same transaction (race fixed)
- #267: Traffic light defaults to 0.5 (conservative) when missing
- #257: _safe_run only sets done-flag on success (failed tasks retry)
- #259: pull_commands only claims successfully inserted commands
- #269: _notify_exit_trade call sites pass all required params
- #264: open_shadow_trade returns None consistently on failure

**Tier 3 — MEDIUM (9 issues, polish):**
- #256: Options metrics query column names fixed
- #260: options_chains retention rule added (30 days)
- #261: Options flow in training documented as future enhancement
- #262: earnings_signals logs errors instead of swallowing
- #263: Duplicate bracket order log removed
- #265: Stub endpoints return not_implemented status
- #266: shadow_account queries unified
- #268: Dead canary_score import removed
- #270: NYSE 2026 holiday calendar added

---

## [v0.12.0] - 2026-04-04

### Codebase Documentation + Issue Resolution + Gap Analysis

116 files changed, +3,757 lines. 0 pre-existing issues remaining.

**Issue resolution (11 closed: #222, #239, #247-#255):**
- #248: Bracket monitor false alarms — Alpaca enum prefix stripped
- #249: System validator reads env vars, not YAML
- #250: Dark mode chart visibility — CSS variables defined
- #251: Packet commentary — raw template headers stripped
- #253: Open positions unrealized P&L computed
- #254: Max consecutive losses wired from cto_report
- #247: Metric cards centered
- #252: Stress test Run button via command queue
- #255: React Flow diagram polish
- #239: Daily audit baseline updated
- #222: Telegram pairing documented

**Codebase documentation:**
- WHY-focused inline comments on all 200+ Python files
- 30 closed issues cross-referenced in code at fix locations
- Strategy decisions (#1-#24) cited at implementation points

**Gap analysis (15 new issues filed: #256-#270):**
- Options pipeline dead (#256), _safe_run done-flags (#257), busy_timeout bypass (#258)
- pull_commands claim bug (#259), options_chains unbounded growth (#260)
- Unused options flow (#261), earnings_signals swallowing (#262), duplicate log (#263)
- open_shadow_trade return type (#264), stub endpoints (#265), wrong columns (#266)
- Traffic light default (#267), broken import (#268), missing params (#269), no holidays (#270)

---

## [Unreleased] - 2026-04-03

### Bug Fixes (PRs #200, #201, #204)

- Cast `pnl_dollars` to float before comparison in shadow trade close logic (#195, PR #200)
- Fix exit order cancel race condition — cancel completes before status update (#196, PR #201)
- Harden VRAM handoff escalation — retry with exponential backoff (#198, PR #201)
- Add Postgres sync reconnection on transient connection drops (#199, PR #201)
- Fix 8 RCCA bugs from 4/3 log audit: SQLite TEXT→numeric casts (4 bugs), VIX `.item()`, regime missing arg, Telegram undefined var, Postgres duplicate keys (PR #204)

### Sprint Gap Closures (PR #204)

- Wire `resolve_pending_outcomes()` into 4:30 PM post-close job (S3)
- Add `tests/test_attribution.py` — 12 tests covering all 5 attribution functions (S3)
- Add `strategy_type` dropdown filter on Shadow Ledger + API response (S4)
- Extract universe scanner from `watch.py` into stateless `universe_scanner.py` (S5)
- VIX-regime ATR-based brackets in stress test (2.0x/2.5x/3.0x by regime) (S7)
- Schedule stress test Sunday 9 PM + re-run on model version change (S7)

### Halcyon-Audit Plugin (PR #204)

- 8 domain agents + 1 synthesis agent for automated codebase auditing
- `/audit` skill with scheduling, quality gate, baseline management
- Idempotent GitHub issue filing with severity/domain labels

### Local API Parity (PR #202)

- 22 missing routes added to local FastAPI server to match cloud endpoints

### Sprints A through 7: Dashboard, Attribution, MR, Multi-Cadence, Training, Stress Testing

**Sprint A — Dashboard Polish + Documentation Consolidation:**
- Redesigned audit banner as compact expandable chip (green/yellow/red/stale states)
- Fixed build score empty state (shows "not yet computed" instead of 0.0)
- Added `cto-report` command handler; fixed action endpoint mappings
- Fixed activity feed "task: ?" entries for overnight_task and default cases
- Created MASTER.md (822 lines, 13 sections) consolidating 5 governance docs
- Archived 11 docs to docs/archive/governance/ and docs/archive/reference/
- Enriched watch loop: startup banner with portfolio stats, 60-min heartbeat, scan summary line

**Sprint 3 — Alpha Attribution Experiment:**
- Added `attribution_trades` table (49 tables total in registry)
- Two-phase attribution logging in watch.py (before/after LLM)
- Mechanical outcome simulator for post-close evaluation
- Historical backtest script (`scripts/alpha_attribution_backtest.py`)
- Dashboard Attribution page with win rate comparison and statistical power

**Sprint 4 — Mean Reversion Paper Trading:**
- Mean reversion feature engine (RSI(2), 200 EMA, Bollinger, volume spike)
- Shared `compute_rsi()` utility in `src/features/indicators.py`
- Strategy config with `paper_only` enforcement
- Strategy-aware exit dispatcher (RSI(2) > 70 exit, ATR stop, MR timeout)

**Sprint 5 — Multi-Cadence Scanning:**
- Extracted 4 modules: position_monitor (15 min), universe_scanner (30 min), sentiment_scanner (60 min), fundamentals_refresh (daily)
- 4-tier timing orchestrator wired into watch.py main loop
- Staleness detection with per-ticker per-source tracking (`data_freshness` table)

**Sprint 6 — Outcome-Conditioned Training Pipeline:**
- Outcome classifier (WIN/LOSS/TIMEOUT from exit_reason + P&L)
- 4 outcome-conditioned + 2 contrastive prompt templates (all self-blinding)
- Data collector now generates 3-5 examples per closed trade (up from 1)
- 8 outcome metadata columns added to shadow_trades

**Sprint 7 — Historical Stress Testing:**
- Stress test script for 2008, 2020, 2022 crisis periods
- Survivorship bias mitigation (filter + note limitation)
- Extended backtester metrics (calmar, monthly returns, drawdown duration)
- Dashboard StressTest page with equity curves
- Results stored in `stress_test_results` table

## [Previous] - 2026-03-31

### Sprint 8: Comprehensive Cleanup — All Remaining Issues

**Training Pipeline Safety (Task 1):**
- Sanitize feature snapshots: remove outcome-correlated fields before storage (#110)
- Exclude canary example IDs from exported training data (#111)
- Leakage detector returns INSUFFICIENT_DATA when <30 examples per class (#113)
- Temporal split applied BEFORE quality filter to prevent future leakage (#114)
- Dynamic gradient accumulation prevents crash on small datasets (#115)
- Partial close detection: label as PARTIAL and exclude from training (#116)

**Council Fixes (Task 2):**
- Exponential backoff retry on Anthropic rate limit errors (#117)
- Filter unparseable votes from consensus tally (#118)
- Dynamic majority threshold (len//2+1) instead of hardcoded 3 (#119)
- Cost cap check before Round 2 with configurable max_session_cost (#120)
- Type-validate confidence values — non-numeric defaults to 0.5 (#121)
- Auto-create value tracker tables on first access (#122)

**LLM Pipeline Hardening (Task 3):**
- Configurable LLM timeout via llm.inference_timeout_seconds (#153)
- Context window overflow protection with enrichment truncation (#154)
- Prompt injection sanitization for news/filing enrichment data (#156)
- Universe lookup failure rejects trade (fail closed) (#162)
- Grammar client VRAM leak fix on model version change (#163)
- Daily packets list capped at 200 and cleared after EOD digest (#164)
- VRAM threshold increased from 500MB to 1500MB (#166)
- Empty string LLM responses treated as failure (#167)
- Conviction None defaults to 5 with warning (#168)
- Out-of-range conviction logged as hallucination before clamping (#169)

**Data Pipeline Robustness (Task 4):**
- Nightly retention policy: prunes old rows from 7 tables (#123)
- Options collector validates underlying_price (reject NaN/None/0) (#125)
- EDGAR accession numbers normalized to dashed format (#126)
- EDGAR NLP UPDATE checks columns exist via PRAGMA (#127)
- CBOE collector returns None on regex failure (#128)
- Short interest collector uses cursor.rowcount (#129)
- Sync timezone handling verified (#131)
- Enricher rate limiting: Finnhub 1s, SEC 0.1s intervals (#133)

**Trading Logic Fixes (Task 5):**
- Atomic duplicate position check with BEGIN IMMEDIATE (#99)
- Alpaca API failure counter with Telegram alert at >50% failure rate (#102)
- Partial fill detection on bracket legs (#104)
- Backfilled positions flagged with zero stop/target (#107)
- Stale record closure attempts yfinance P&L, falls back to reconciled_stale (#108)
- Daily loss limit uses realized (closed) trades only (#109)
- Traffic light persistence debounce (5-minute cooldown) (#144)
- Sector exposure uses current market price (#145)

**Frontend Bug Fixes (Task 6):**
- Verified all fetchApi() calls match backend routes, added getBuildScore (#81, #134)
- Per-page ErrorBoundary wrapping all routes (#135)
- ShadowLedger reads starting capital from API (#138)
- CTOReport uses optional chaining on all data fields (#139)
- Council page invalidates queries after askStrategic mutation (#140)
- Training page derives outcome types dynamically (#142)

**Frontend Security & UX (Task 7):**
- AuthGate hashes password with SHA-256, 24h expiry (#137)
- Docs page sanitizes HTML to prevent XSS (#136)
- .env.example clarifies VITE_API_SECRET is dashboard-only (#148)
- formatTimestamp utility with Intl.DateTimeFormat (#141)
- Text labels alongside color-coded status indicators (#143)

**Sprint 6 Visibility (Task 8):**
- All 6 Sprint 6 tasks were already implemented; refactored Training.jsx (450→315 lines)

**Config, Performance & Tech Debt (Task 9):**
- Central DB_PATH constant in src/config (#83)
- Added missing env vars to .env.example (#84)
- Added 10+ minimal import tests for untested modules (#85)
- Updated AGENTS.md route count (55→124) (#86)
- Added indexes on shadow_trades.status and recommendations.created_at (#92, #97)
- Replaced all var(--slate-*) with var(--arcis-*) (#93)
- Moved config_overrides.py to src/config/overrides.py (#95)
- Added comprehensive comments to settings.example.yaml (#98)
- Research collector logs fallback to keyword scoring (#146)
- NYSE holiday awareness for 2026 (#149)
- Sleep/crash recovery detection with gap alerting (#152)
- reload_config() clears cache on demand (#165)

**Tests:** +78 new tests (1225 total, up from 1147) across 16 new test files
**Files:** 173 Python modules, 101 test files

**Issues closed:** #81, #83, #84, #85, #86, #92, #93, #95, #97, #98, #99, #102, #104, #107, #108, #109, #110, #111, #113, #114, #115, #116, #117, #118, #119, #120, #121, #122, #123, #125, #126, #127, #128, #129, #131, #133, #134, #135, #136, #137, #138, #139, #140, #141, #142, #143, #144, #145, #146, #148, #149, #152, #153, #154, #156, #162, #163, #164, #165, #166, #167, #168, #169

---

### Sprint 7: Reliability & Critical Bug Fixes

**P0 fixes (trading risk / system crash):**
- Watch loop crash protection: top-level exception handler with Telegram CRITICAL alert, graceful SIGTERM handling, exponential backoff (10s/30s/60s cap) replacing fixed 5-min cooldown, hourly instability alerts (#159, #155, #157)
- Bracket orders changed from DAY to GTC time-in-force — positions now protected overnight/weekends (#101)
- Exit-failed recovery: failed exits marked `exit_failed` and retried next scan cycle with Telegram alert (#100)
- Timestamp parse failure now defaults to days_open=999 (force timeout) instead of 0 (disable timeout) (#105)
- Stop-loss vs take-profit bracket leg identification in exit_reason field (#103)
- Traffic Light API: replaced UNKNOWN stub with live DB query (#89)
- Render sync crash detection: Telegram alert on error, mutex to prevent overlapping cycles (#161, #130)
- load_dotenv added to watch.py for standalone execution (#90)

**P1 fixes (will cause problems soon):**
- Heartbeat: writes timestamp to data/watchdog.txt every 60s, /heartbeat Telegram command (#150)
- Scan overlap prevention: _scan_in_progress flag prevents concurrent scans (#151)
- SQLite busy_timeout: new `src/utils/db.py` helper with PRAGMA busy_timeout=5000; migrated executor, bracket_monitor, reconcile (#160)
- Missing API key alerts: one-time Telegram alert per missing key (FINNHUB, FRED) (#124)

**Cosmetic:**
- Renamed "HALCYON LAB" to "ARCIS" in watch banner and startup notification (#94)
- Updated build_score.py docstring from "Halcyon Lab" to "Arcis" (#96)
- Replaced hardcoded Render URL with RENDER_API_URL env var (#91)

**Tests:** +18 new tests (1168 total) across 3 new test files: test_watch_resilience.py, test_bracket_safety.py, test_db_util.py

**Issues closed:** #89, #90, #91, #94, #96, #100, #101, #103, #105, #124, #130, #150, #151, #155, #157, #159, #160, #161

### Automated Daily Reconciliation (#170)

#### Paper Trade Reconciliation
- Added: `reconcile_paper_trades()` in `src/shadow_trading/reconcile.py` — compares Alpaca paper positions with local `shadow_trades` (source='paper')
- Added: Orphaned position backfill with `order_type='reconciled'`, stale trade detection (alert-only, no auto-close), qty discrepancy reporting
- Added: `_run_postclose_reconciliation()` in watch loop — runs daily at 4:30 PM ET postclose, sends Telegram summary
- Added: 4 tests in `tests/test_reconcile.py` (all-matched, orphaned backfill, stale no-auto-close, qty discrepancy)

---

### Sprint 6: Data Pipeline Visibility

#### API Wiring (Task 1)
- Added: `getDataCollectionStats`, `getTrainingHistory`, `getScanMetrics` methods to frontend api.js

#### Data Collectors Grid (Task 2)
- Added: 12-card collector grid on Training page with freshness indicators (green/yellow/red)
- Added: row counts, relative dates ("2h ago", "yesterday"), and ticker coverage per collector
- Added: responsive grid (3 cols desktop, 2 tablet, 1 mobile)

#### Training Pipeline Status (Task 3)
- Added: pipeline status section on Training page with active model card and status badge
- Added: format compliance display (XML vs plain_text counts)
- Added: leakage test indicator with OK/Marginal/Leaking thresholds
- Added: quadrant distribution 2x2 grid (good/bad process x good/bad outcome)

#### Model History (Task 4)
- Added: model history timeline on Health page with version, status badge, example count, holdout score
- Added: graceful single-model state ("First model — no comparisons yet")

#### Scan Metrics Trend (Task 5)
- Added: scan metrics section on Dashboard with today's summary (scans, packets, LLM success rate)
- Added: 7-day trend sparkline using Recharts LineChart
- Added: LLM success rate color coding (green >90%, yellow 70-90%, red <70%)

#### Card Contrast Fix (Task 6)
- Added: `.arcis-card` CSS class in index.css (elevated bg, border, shadow, hover state)
- Changed: all card elements across Dashboard, Health, Training, Settings, CTOReport to use `.arcis-card`
- Changed: MetricCard component migrated from inline styles to `.arcis-card`
- Changed: Dashboard cards migrated from `--slate-*` to `--arcis-*` design tokens
- Added: light mode shadow variant for `.arcis-card`

#### .env Secret Migration (Task 7)
- Added: `os.environ.get()` with YAML fallback to 10 modules (telegram, claude_client, 3 Finnhub collectors, macro collector, email notifier, insiders enrichment, news enrichment)
- Added: `TELEGRAM_CHAT_ID` to `.env.example`
- Added: `tests/test_env_secrets.py` with 11 tests covering env precedence, YAML fallback, missing keys, and placeholder detection
- Pattern: `.env` (via `load_dotenv`) takes precedence; YAML config is backward-compatible fallback

#### Documentation (Task 8)
- Updated: CHANGELOG.md with Sprint 6 entry
- Updated: AGENTS.md counts
- Verified: test baseline maintained, frontend builds successfully

---

### Sprint 5: Dashboard Polish & UX

#### Shadow Ledger (Task 1)
- Added: summary row (total positions, unrealized P&L, avg days held)
- Added: P&L values with colorblind-accessible arrows (▲/▼) + `financial-data` class
- Added: alternating row shading via `var(--arcis-bg-elevated)`
- Added: mobile-responsive columns (hide IS bps, strategy on <768px)
- Added: default sort by P&L% descending (best performers at top)
- Fixed: all `var(--slate-*)` references migrated to `var(--arcis-*)` design tokens

#### Validation Page (Task 2)
- Added: `validate-system` command to executor (command queue integration)
- Added: error state display when watch loop offline
- Enhanced: fallback from direct API to command queue for validation runs

#### Training Page (Task 3)
- Added: hero section with large total examples count, weekly count, avg quality
- Added: outcome distribution horizontal stacked bar (WIN/LOSS/TIMEOUT/PASS)
- Added: v2 spec targets vs actual comparison grid
- Added: source breakdown bar chart (historical_backfill, blinded_win, etc.)
- Added: ticker coverage progress bar and regime coverage display
- Added: recent examples table (last 10 with ticker, source, outcome, quality, date)
- Added: graceful handling when outcome_type data pending migration

#### CTO Report (Task 4)
- Added: Phase 1 gate progress bar (X/50 trades)
- Added: minimum-data notices ("Requires N+ closed trades" instead of N/A)
- Added: early win rate callout (100% on <10 trades note)
- Changed: fund metrics only shown when 20+ trades available
- Changed: confidence calibration section shows data requirements when <10 trades

#### Docs Page (Task 5)
- Added: sticky mobile back button ("← Back to documents") always visible on mobile
- Added: two-column desktop layout (300px sidebar + content viewer)
- Added: single-column mobile navigation (list → detail → back)
- Added: document viewer max-width 720px for comfortable reading
- Added: file icon indicators and sidebar card styling

#### Notes Page (Task 6)
- Added: tag filter pills at top for quick category filtering
- Added: pinned-first + reverse chronological default sort
- Added: relative date formatting (e.g., "2h ago", "Mar 15")
- Added: empty state with icon ("No notes yet — add your first note above")
- Changed: textarea placeholder to "Add a note..." for cleaner UX

#### Logs Page (Task 7)
- Added: expandable log rows (click to show details_json as formatted JSON)
- Added: "Run Command" dropdown with common commands (scan, council, collect-data, validate)
- Added: command auto-refresh at 10s (faster than logs at 30s)
- Added: empty state messages for both logs and commands
- Added: CRITICAL level background highlighting (red tint)
- Fixed: all `var(--slate-*)` references migrated to `var(--arcis-*)` design tokens

#### Settings Page (Task 8)
- Added: section icons (Settings2, Shield, Brain, Clock) from lucide-react
- Added: setting descriptions below each label
- Added: "Saved ✓" animation feedback on setting changes
- Added: reset confirmation dialog (two-step: click → confirm)
- Added: system health items in card-style background tiles
- Fixed: all `var(--slate-*)` references migrated to `var(--arcis-*)` design tokens

#### Backend
- Added: `validate-system` command handler in executor.py
- Test count: 1,110 (unchanged)

### Sprint 4E: Post-Review Cleanup & Production Hardening

#### Database Schema
- Added: `strategy_type` column to shadow_trades (DEFAULT 'pullback')
- Added: `outcome_type` and `regime` columns to training_examples
- Added: `level` column to activity_log (DEFAULT 'INFO')
- Added: `build_score_history` CREATE TABLE to create_missing_tables.py
- Added: scripts/migrate_production_db.py (safe, idempotent migration)
- Backfilled: outcome_type on 969/972 training examples from trade outcomes

#### Watch Loop Fixes
- Fixed: Traffic Light now computed during watch loop scans (was only in scan_service)
- Fixed: VIX read from vix_term_structure DB table instead of relying on vix_proxy feature
- Fixed: scan_metrics now recorded for every scan cycle (success, empty, or failed)
- Fixed: Council failure sends Telegram notification (was silent on error)

#### Robustness
- Fixed: weekly_review.py checks column existence via PRAGMA before querying
- Added: schema health section to weekly review (expected vs actual columns)
- Updated: README.md rewritten for Arcis (75 lines, private-repo focused)

#### Tests
- Added: tests/test_db_migration.py (4 tests: idempotent, adds columns, preserves data, creates tables)
- Added: test_vix_30_6_produces_red_vix_component in test_traffic_light.py
- Test count: 1,105 -> 1,110

### Sprint 4C: Dashboard as Control Plane

#### Command Queue System
- Added: pull-based command queue pattern (pending_commands, command_results, config_overrides, log_entries tables)
- Added: bidirectional sync — cloud pulls commands to local, local pushes results to cloud
- Added: command executor with 10 command types (scan, council, collect-data, halt-trading, etc.)
- Added: 5-minute command expiry, 10/min rate limiting, 10KB result truncation
- Added: DBLogHandler that writes WARNING+ to log_entries table (last 500 entries)

#### Config Override System
- Added: dashboard-editable settings with whitelisted keys only
- Added: config overrides merge with YAML defaults (overrides win for whitelisted keys)
- Added: blocked prefixes for API keys, DB paths, and secrets (never editable remotely)
- Added: "Reset to YAML" to clear all dashboard overrides

#### Cloud API Overhaul
- Changed: all stub action endpoints now submit commands via queue instead of returning "must be done locally"
- Added: POST /api/commands/submit, GET /api/commands/{id}/status, GET /api/commands/recent
- Added: GET /api/logs/recent with level and source filtering
- Added: DELETE /api/settings/overrides to clear all overrides
- Changed: POST /api/settings now submits config_change commands via queue

#### Frontend
- Added: editable Settings page with toggle/number inputs and source badges (yaml default vs dashboard override)
- Added: Logs page with filterable log table and recent commands history
- Added: command pending indicator on Dashboard (blue pulsing badge)
- Added: 14th dashboard page (Logs) to navigation

#### Documentation
- Added: ADR 012 — Pull-based command queue architecture decision
- Updated: AGENTS.md counts (169 Python files, 77 test files, 40 DB tables, 55 API routes)
- Added: 15 tests in test_command_queue.py (submission, expiry, whitelist, rate limiting, round-trip)

## [Unreleased] - 2026-03-27/29

### Weekend Mega Sprint (4 sprints: Stabilize + Hotfix + Build + Document)

#### Critical Safety Fixes
- Fixed: safety checks fail closed on errors, not open (#42)
- Fixed: journal closes after broker confirmation, not before (#41)
- Fixed: LLM validator accepts the real `TradePacket` schema (#40)
- Fixed: paper trades are logged as `failed` on submission failure instead of phantom opens (#46)
- Fixed: `/shadow/close` now requires broker exit semantics for Alpaca-backed trades (#45)
- Fixed: council data gatherers query the correct live column names (#44)
- Fixed: Telegram trade notifications use the real packet fields and source labels (#48)
- Fixed: kill-switch tests and training-ingestion tests now run deterministically against the hardened runtime behavior

#### New Features
- Added: event calendar 0-10 continuous risk scoring with sizing multipliers and Telegram alerts
- Added: bracket order health monitor with intraday, pre-market, and post-close verification
- Added: optional GBNF grammar enforcement path for XML commentary generation
- Added: data quality ingestion gates with duplicate detection and batch halt alerts
- Added: Notes page plus cloud CRUD API for pinned, tagged operator notes
- Added: Council.jsx v2 with new agent identities, consensus labels, strategic prompt input, and parameter adjustment history
- Added: HSHS radar chart and live phase-weight display on the Health page

#### Infrastructure
- Added: `scripts/verify_counts.py` for AGENTS.md count verification
- Added: `scripts/schema_report.py` for canonical SQLite schema reporting
- Added: `scripts/generate_dependency_graph.py` and generated `docs/dependency-graph.md`
- Added: `scripts/render_architecture_doc.py` to regenerate the architecture inventory from live code
- Added: strategy-specific pullback timeout support (15 -> 7 days)
- Added: Render sync coverage for the new notes data path
- Added: `bracket_health` and `user_notes` tables to the working schema
- Fixed: SQLite connection handling in earnings enrichment (#52)
- Fixed: kill-switch path handling so safety remains configurable without leaking ambient state into tests (#47)
- Removed: stale council v1 compatibility wrappers from active code paths

#### Documentation
- Added: 11 architecture decision records under `docs/decisions/`
- Rewrote: `docs/architecture.md` from the live module, route, and schema inventories
- Rewrote: `docs/roadmap.md` to consolidate the confirmed March 28-29, 2026 decisions
- Added: `docs/observation-log-template.md` for the Monday-through-Sunday operating rhythm
- Updated: Framework v2.1 research integration notes for risk budgeting, EDGAR fundamentals, operating cadence, and fund-path deferrals
- Documented: council prompt caching was evaluated and intentionally not enabled because the current agent prompts do not share a reusable long prefix

---

## 2026-03-28 — Reliability Sprint + Research-Informed Features

### Critical Safety Fixes
- Risk governor REJECTS trades on exception (was: approve anyway)
- Drawdown returns 15% conservative estimate on error (was: 0%)
- `train-pipeline` CLI runs full 5-step pipeline (was: empty stub)
- LLM validator REJECTS trades on exception (was: continue)
- Bracket order checks child/leg statuses (was: parent only)

### Wiring & Integration
- `data_integrity.py` → scan pipeline (feature validation pre-ranking)
- `canary.py` → trainer (post-retrain evaluation gate)
- `metrics.py` → CTO report (shared calculations)
- All 12 Telegram notifications wired into watch.py
- 44+ bare `except: pass` → logged at WARNING+
- `overnight.py` consolidated (deleted), `broker.py` deleted

### New Features
- **Traffic Light regime:** VIX(20/30) + 200-DMA(3%) + credit spread(0.5σ/1.5σ) → sizing multiplier. 5-day persistence filter.
- **PEAD enrichment:** 5 earnings signals in pullback prompt (conditional on proximity ≤30 days)
- **Implementation Shortfall:** Signal price capture, IS computation on fill, rolling 20-trade alert
- **HSHS live:** 5-dimension health score from database, wired into CTO report + council + API
- **System validator:** 50+ checks, Validation dashboard page
- Independent live trade monitoring (source_filter parameter)

### Research & Architecture
- 6 new research documents (35 total), all strategy decisions confirmed
- Master blueprint v2, Halcyon Framework v2 updated
- Council redesign architecture finalized (vote-first, value tracking)
- 24 deep research prompts generated

---

## 2026-03-27 — Test Gap Closure (Priority 1 — Critical Money Path)

### New Test Files (6)
- **test_statistics.py** (56 tests) — All 11 statistical functions: Sharpe, PSR, bootstrap CI, profit factor, max drawdown, Sortino, Calmar, win rate test, expectancy test, MinTRL
- **test_gate_evaluator.py** (32 tests) — Gate decision logic (PROCEED/EXTEND/REVISION/ROOT CAUSE), metric thresholds, statistical outputs, format_gate_report, boundary conditions
- **test_change_detector.py** (12 tests) — CUSUM symmetric filter, threshold sensitivity, drift detection, performance drift with real SQLite
- **test_llm_validator.py** (18 tests) — All 6 validation checks: ticker universe, entry price deviation, stop below entry, stop distance bounds, position size cap, conviction range
- **test_filing_nlp.py** (17 tests) — Loughran-McDonald sentiment scoring, cautionary phrase detection, filing delta computation, tech-fundamental divergence
- **test_broker.py** (11 tests) — Broker abstraction, AlpacaAdapter methods, factory function, abstract interface

### Full Test Gap Closure (Priority 2-3)
- **test_backtester.py** (7 tests) — Walk-forward backtest with mocked market data, compare_models winner selection
- **test_services.py** (39 tests) — All 7 service modules: scan, shadow, system, training, review, recap, watchlist
- **test_docs_collector.py** (12 tests) — File scanning, title extraction, category assignment, table population
- **test_data_integrity.py** (21 tests) — Feature validation, trade entry validation, universe validation
- **test_activity_logger.py** (8 tests) — Activity log insertion, metadata, missing table handling
- **test_packet_builders.py** (16 tests) — Template packet builder, watchlist builder, EOD recap builder
- **test_llm_writers.py** (10 tests) — Postmortem writer, watchlist narrative generator
- **test_local_api_routes.py** (24 tests) — Packets, training, scan, review route endpoints
- **test_websocket.py** (7 tests) — ConnectionManager connect/disconnect/broadcast

### Coverage Impact
- Tests: 1,035 (up from 657 baseline, +378 new tests)
- All critical money-path, service layer, utility, and API route modules now tested
- Test files: 69 (up from 52)

---

## 2026-03-27 — Dashboard Hardening + Email Digests

### Error Visibility (Part A)
- Every `except Exception` block in cloud_app.py now has `logger.error()` with endpoint name and exc_info
- Every error response now includes an `"error"` key with the exception message
- New `/api/diagnostics` endpoint tests all 23 dashboard tables and reports pass/fail per table

### Test Coverage (Part B)
- Added 29 new cloud API tests covering all previously untested endpoints
- Coverage: activity feed, live trades/summary, council session detail, health score dimensions, settings, market overview, data asset growth, journal, signal zoo, macro dashboard, research papers/digest, training quality, scan metrics, projections, diagnostics, reconcile, CTO report shape
- Total cloud API tests: 67 (up from 38)

### Email Digests (Part C)
- New `src/email/digest_builder.py` — 4 fund-manager-style digests: pre-market (7:30), midday (12:00), EOD (4:15), evening (8:00)
- New `email_mode: digest` — sends exactly 4 emails per day at configured times
- Digest schedule wired into watch.py main tick loop with daily flag resets
- Per-trade and per-scan emails suppressed in digest mode
- Risk alerts still send immediately regardless of mode
- 15 new tests for all 4 digest builders (empty DB, populated, format)

### Telegram (Part D)
- Trade open/close and risk alerts remain immediate
- Per-scan email spam suppressed in digest mode (Telegram notifications unchanged)

---

## 2026-03-27 — Live Trade Reconciliation

### New Features
- **`reconcile-live` CLI Command** — Detects orphaned Alpaca positions (on broker but not in DB) and stale DB records (in DB but not on broker); backfills or marks closed with `--dry-run` option
- **Live Ledger Reconcile Button** — Disabled button with tooltip showing CLI command for local execution

### Fixes
- **Fractional Shares** — `get_live_positions()`, `get_all_positions()`, `get_position()` in alpaca_adapter now use `float(qty)` instead of `int(qty)` to support fractional share positions

### Backend
- New `POST /api/live/reconcile` endpoint (returns cloud_mode error — local CLI only)
- New `src/shadow_trading/reconcile.py` module with `reconcile_live_trades()` function

### Tests
- 5 new tests: dry-run safety, orphan backfill, stale marking, no-discrepancy, paper-trade isolation

---

## 2026-03-27 — Dashboard Polish Sprint

### New Features
- **Research Docs on Cloud** — 35+ markdown docs served via `research_docs` Postgres table with category sidebar and search
- **Council Session Detail View** — Expandable session rows with full agent vote cards, vote distribution chart, dissent highlighting
- **Activity Feed Cloud Polling** — Polling fallback for cloud mode (60s) with event-type icons
- **Live Trade Ledger** — New page for $100 Alpaca live account with equity curve, open/closed tables, header metrics
- **Shadow Ledger Enhancements** — Metrics strip (equity, PF, DD), expandable trade detail rows, 4 viz tabs (equity curve, distribution, sector heatmap, calendar)
- **Hardware Roadmap** — Phase 2 and Phase 4 build specs with costs and unlock descriptions
- **Monthly Cost Timeline** — Visual bar chart of per-phase monthly costs

### Fixes
- **Audit Banner** — Parses raw JSON/code fences from audit summary, shows clean text
- **Shadow Equity** — Uses `shadow/account` endpoint (starting_capital + closed_pnl) instead of potentially wrong `alpaca_equity`
- **KPI Thresholds** — Sharpe/Win Rate show with >= 2 trades (was >= 5)
- **Confidence Calibration** — Shows "< X/50 trades" instead of "--"
- **Rubric Score** — Shows "Not scored yet" with tooltip instead of "n/a"
- **Health Score Dimensions** — All 5 dimensions (Performance, Model Quality, Data Asset, Flywheel, Defensibility) now computed from real data with metric breakdowns
- **Review Tab Removed** — Replaced with Live Ledger in sidebar navigation

### Backend
- 8 new cloud API endpoints: `/api/council/session/{id}`, `/api/activity/feed`, `/api/live/trades`, `/api/live/summary`, `/api/settings` (GET/POST), updated `/api/docs`, `/api/health/score`
- `research_docs` table added to sync pipeline
- Research synthesis wired to Sunday 6 PM schedule
- Daily metric snapshots at 4 PM EOD (not just Saturday)
- Nightly Telegram notification for new research papers

### Components
- New `Tooltip.jsx` — Hover tooltip with 300ms delay
- New `LiveLedger.jsx` — Full live trading ledger page
- Updated `ActivityFeed.jsx` — Cloud polling fallback + event icons
- Updated `Council.jsx` — Expandable session rows
- Updated `ShadowLedger.jsx` — Enhanced with viz tabs + trade expansion

### Roadmap
- Updated to 6 phases (added Phase 6 — Multi-Desk Expansion)
- Phase costs updated: $64 → $125 → $155 → $220 → $500+
- Hardware roadmap section added
