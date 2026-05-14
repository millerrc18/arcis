# 2026-05-14 Dashboard Rectification — v0.36.1 Patch

**Goal:** Fix every operator-visible defect surfaced by the Chrome DevTools sweep of all 27 dashboard pages at https://halcyonlab.app on 2026-05-14 morning. Bundle with already-shipped morning hotfixes into a single v0.36.1 patch PR.

**Trigger:** Operator opened the dashboard pre-market and flagged five concrete issues (Shadow Ledger, Strategy WR 16.4%, Packets missing info, Dashboard no scan metrics / health notifications, Training data collectors empty). Operator directive: "review every page before building out a rectification plan." Sweep walked all 27 routes, cataloged 9 problem clusters.

**Target version:** v0.36.1 (patch).
**Target tag:** `v0.36.1`.
**Base branch:** `sprint/sp6-wave-a/base` (current operator branch).

---

## Section 0 — Already done (morning hotfixes — needs commit + cherry-pick into PR)

These four files are modified on disk on `sprint/sp6-wave-a/base` and have been verified live post-restart. They address trackers #142–#147 but were never committed. They MUST land in the v0.36.1 PR.

| Tracker | File | Change |
|---|---|---|
| #142 | `src/scheduler/watch.py:649-680` | WATCH MODE banner reads PG cutover env → emits `DB: PostgreSQL (Docker)` when active, drops stale "Render sync: active" suffix |
| #143 | `src/utils/deploy_info.py:_run_git` | Capture stderr instead of DEVNULL; log actual git error at debug level on `CalledProcessError`. Also applied operational fix `git config --system --add safe.directory C:/arcis/halcyon-lab` (already live on operator's machine, NOT a code change) |
| #144 | `src/api/routes/shadow.py` | `_normalize_win_rate_to_decimal()` helper at API boundary divides percent→decimal so frontend's `*100` works correctly. Used by `/shadow/closed` and `/shadow/metrics` |
| #145 | `src/api/app.py` | SPA fallback exception handler returns `index.html` for any non-`/api/*` GET that 404s |
| #146 | `src/api/routes/shadow.py` + new `src/api/routes/diagnostic.py` | Three missing endpoints mirrored locally: `/api/shadow/desks`, `/api/shadow/sharpe-attribution`, `/api/diagnostic-runs` (+`/{run_id}`, `/{run_id}/report`, `/{run_id}/plots`) |
| #147 | `frontend/src/pages/LiveLedger.jsx:184` | `starting_capital || 100000` (was `|| 100`) — fixes transient `$100.00` flash before API resolves |

**Action for PM:** Commit these as the first commit on the integration branch (`feat(dashboard): morning hotfixes #142–#147`). Do NOT reimplement.

---

## Section 1 — P0 — `/api/data-collection-stats` returns "list index out of range" for every collector (kills Training page)

**Surface (operator-facing):** `/training` page → "Data Collectors" section → all 12 collectors show "No data collected yet".

**Root cause:** `src/api/routes/system.py:_DATA_COLLECTION_QUERIES` (lines 56–93) contains SQL like:
```sql
SELECT COUNT(*), MAX(collected_at), COUNT(DISTINCT ticker) FROM options_chains
```
Un-aliased. `_build_table_stats(row)` at line 96–112 does positional indexing (`row[0]`, `row[1]`, `row[2]`). Post-PG-cutover the wrapper's CompatRow can't reliably map duplicate `count` column names that PG produces, so `row` is sometimes empty and `row[0]` raises `IndexError("list index out of range")`. The exception is caught at line 331 and serialized into the response — operator sees the error string in `/api/data-collection-stats` payload.

**Fix recipe:**
1. Add column aliases to every entry in `_DATA_COLLECTION_QUERIES` in `src/api/routes/system.py`:
   ```python
   "SELECT COUNT(*) AS total_records, "
   "       MAX(collected_at) AS latest_collection, "
   "       COUNT(DISTINCT ticker) AS coverage_count "
   "FROM options_chains"
   ```
2. Rewrite `_build_table_stats` to read by NAME (use `row['total_records']` not `row[0]`), matching cloud_routes/training.py pattern.
3. Sibling-check: do the same audit on `src/api/cloud_routes/training.py` `_DATA_COLLECTION_QUERIES` (mirrors local, must stay in sync per docstring at line 31).
4. Some tables use `collected_date` not `collected_at` (#328 note in source) — preserve the `COALESCE(collected_at, collected_date)` pattern where present.

**Files in scope:**
- `src/api/routes/system.py` (PRIMARY)
- `src/api/cloud_routes/training.py` (sibling)

**Verification:**
- `curl http://localhost:8000/api/data-collection-stats -H "Authorization: Bearer <token>"` returns each collector with `total_records` numeric (zero is OK), no `"error"` key.
- Open `/training` in browser → "Data Collectors" section shows actual counts (or zero), no "No data collected yet" everywhere.
- Run `python -m pytest tests/test_schema.py::test_stats_queries_reference_valid_columns -v` (existing test validating SQL refs valid columns).

---

## Section 2 — P1 — Open-position count breakage across pages

**Surface:** Multiple pages disagree about open-position count.
- Top status bar (every page): `-- POSITIONS` (should be 28)
- Dashboard "Open Trades" KPI card: 28 ✓
- Shadow Ledger top: `Open (0)` ❌ (should be 28; trades table also stuck `LOADING...`)
- Trade History: `0 closed trades` ❌ (Shadow Ledger says 16 closed; Model Perf `base` row says 16)
- Status bar: `LLM OFFLINE` flickers between visits despite Ollama actually being online

**Investigation steps:**
1. For each broken surface, open Chrome DevTools → Network → identify which endpoint feeds it. Capture the endpoint URL, params, and actual response.
2. Compare with the WORKING surfaces (Dashboard KPI card hits `/api/shadow/open?desk=swing` → returns `open_count: 28`).
3. Likely hypothesis: top status bar reads `/api/status` which may return stale or unauthenticated data. Shadow Ledger may filter by `desk` or `quarantined` more aggressively.

**Specific surface fixes (after investigation confirms cause):**
- **Top status bar** (`frontend/src/components/Layout.jsx` or similar header component): identify the data source. If it's `/api/status`, ensure that endpoint returns the same count as `/api/shadow/open`.
- **Shadow Ledger `Open (0)` + stuck `LOADING...`**: `frontend/src/pages/ShadowLedger.jsx` — check the query key it uses (`['shadow-open', deskFilter]`). Verify desk filter is selecting "Swing" by default (matches Dashboard).
- **Trade History `0 closed`**: `frontend/src/pages/TradeHistory.jsx` — likely uses a different endpoint or `days` window. Operator-facing label "0 closed trades · Last 6 months" suggests `?days=180` or similar — but if the 16 closed trades all happened >6 months ago they wouldn't show. Check the actual date span first.
- **`undefinedW / undefinedL` literal in DOM**: same TradeHistory page — `wins`/`losses` props are undefined when 0 trades returned. Add fallback to `0` in the template string.

**Files in scope:**
- `frontend/src/pages/ShadowLedger.jsx`
- `frontend/src/pages/TradeHistory.jsx`
- `frontend/src/components/Layout.jsx` (status bar)
- Possibly `src/api/cloud_routes/core.py` (`/api/status` shape)

**Verification:**
- Open `/` Dashboard → status bar shows `28 POSITIONS`
- Open `/shadow` → top shows `Open (28)`, table renders 28 trade rows
- Open `/trade-history` → shows `16 closed trades` matching ShadowLedger
- Top bar `LLM ONLINE` stays consistent across page transitions (poll cadence sane)

---

## Section 3 — P2 — Stale version stamp + stale schema snapshot

**Surface 1:** `/docs` page (OpenAPI Swagger UI) header reads `Arcis 0.34.0`. Actual version is `0.36.0`.

**Root cause:** `src/api/app.py:122` has `app = FastAPI(title="Arcis", version="0.34.0", lifespan=lifespan)`. Hardcoded.

**Fix recipe:**
1. Read the version from `src/version.py` instead of hardcoding:
   ```python
   from src.version import __version__
   app = FastAPI(title="Arcis", version=__version__, lifespan=lifespan)
   ```
2. Same fix in `src/api/cloud_app.py:124` (`version="0.17.2"` — also stale).
3. Bump `src/version.py` to `0.36.1` as part of this PR (the rectification IS the patch release).

**Surface 2:** `/schema` page renders "DB SCHEMA — 48 tables across 6 domains" but the watch loop verified 76 tables at startup.

**Root cause:** Either the page reads from a stale snapshot, OR the schema-render code only counts a subset (e.g., tables grouped into 6 domains, omitting unaffiliated ones).

**Fix recipe:**
1. Open `frontend/src/pages/DBSchema.jsx` — check how table count is computed.
2. Open `/api/schema` (or equivalent) endpoint — see if it returns 48 or 76.
3. Likely fix: query `src.schema.registry.TABLES` directly to get the canonical count, or render a comment showing both "48 visualized / 76 total".

**Files in scope:**
- `src/api/app.py:122` (version)
- `src/api/cloud_app.py:124` (version)
- `src/version.py` (bump to 0.36.1)
- `frontend/src/pages/DBSchema.jsx` (table count)
- Possibly schema-related endpoint

**Verification:**
- `/docs` page shows `Arcis 0.36.1`
- `/schema` page shows `76 tables` (or "48 visualized of 76 total" if the diagram intentionally omits some)
- `git tag v0.36.1` ready to push after merge

---

## Section 4 — P3 — HSHS composite math broken

**Surface:** `/health` page shows `HSHS COMPOSITE = 0.0` while displaying sub-scores Performance 79 / Model Quality 71 / Data Asset 74 / Flywheel Velocity 0 / Defensibility 73 with phase weights 10/25/35/20/10%.

**Math check:** Weighted sum = 79×0.10 + 71×0.25 + 74×0.35 + 0×0.20 + 73×0.10 = 7.9 + 17.75 + 25.9 + 0 + 7.3 = **58.85**, NOT 0.0.

**Root cause hypothesis:** Either the composite is reading a different field that's zero (e.g., the legacy `health_composite` column that hasn't been populated post-cutover), OR a multiplication bug where `0 × weight` short-circuits the whole calc, OR the composite is being computed from a separate `phase_weights` dict that's missing keys.

**Investigation:**
1. Find HSHS composite computation site. Likely `src/methods/hshs/*` or `src/api/cloud_routes/kpis_compute.py`.
2. Trace: where does HSHS COMPOSITE get its 0.0?
3. Fix the math, add a regression test.

**Verification:**
- `/health` page COMPOSITE shows ~59 (consistent with sub-scores × weights)
- Unit test: `tests/methods/test_hshs.py` (or new file) — given known sub-scores + weights, composite == expected weighted sum

---

## Section 5 — P4 — `/attribution` badge says ADEQUATE despite 0 resolved pairs

**Surface:** `/attribution` page shows `ADEQUATE (200+)` badge in header, but body reports `0 paired trades resolved (both arms). Need 200+ for statistical significance`. Self-contradictory.

**Root cause:** Badge logic reads `total_pairs` (1059) instead of `resolved_pairs` (0).

**Fix recipe:** In `frontend/src/pages/Attribution.jsx`, the badge condition should read `pairs.resolved_count >= 200`, not `pairs.total_count >= 200` (or whatever the field names actually are). 1-line fix once located.

**Files in scope:**
- `frontend/src/pages/Attribution.jsx`

**Verification:**
- Open `/attribution` → badge reads `INSUFFICIENT (0/200)` or similar accurate state
- When `resolved_pairs` crosses 200, badge transitions to `ADEQUATE`

---

## Section 6 — P5 — Capability registry timeouts / unavailable

**Surface:** Dashboard "Quick Stats" + "System Index" panels show:
- `shadow_trade_cohort` → timeout (also appears in Quick Stats as "unavailable")
- `strategy_registry_state` → unavailable
- `training_corpus` → unavailable
- `reconcile_trades` → timeout
- `attribution_resolver` → timeout

**Root cause hypothesis:** The capability registry health probes run with a short timeout. Post-PG-cutover, the queries are hitting PG which has higher round-trip cost than local SQLite, exceeding the timeout. Or the registered probe functions are using SQLite-only SQL that errors on PG.

**Investigation:**
1. Find the capability registry probe definitions: `src/platform/capability_registry/*.py`, `src/diagnostics/*.py`, `src/attribution/logger.py`, `src/services/bootcamp_state.py`, `src/services/training_service.py`, `src/llm/ollama_state.py`, `src/data_ingestion/backfill_registration.py`.
2. For each `unavailable`/`timeout` probe: identify the timeout threshold and the SQL it runs.
3. If SQL is SQLite-only (`datetime('now', ...)`, `json_extract`, etc.) → port to PG-compatible per the established pattern.
4. If the timeout is too tight → raise it OR add a cache layer.

**Files in scope:** TBD by the investigator. Start with the registries listed in `cloud_app.py:63-70` imports.

**Verification:**
- Dashboard Quick Stats → all 4 registries show `ok` with real values (not `unavailable`)
- System Index → no `timeout` badges

---

## Section 7 — P6 — Stuck pages (`/validation` + `/cto-report`)

**Surface 1: `/validation`** — stuck on `LOADING...` indefinitely. The Dashboard's overall validation card showed 37 Pass / 20 Warn / 0 Fail, so data exists somewhere — the dedicated page just can't render it.

**Surface 2: `/cto-report`** — stuck on `LOADING...` >12s. The endpoint `/api/cto-report?days=365` is slow.

**Investigation:**
- `/validation`: open Network panel → find what endpoint it hits. If 401, auth issue. If 5xx, backend error. If 200 with timeout, frontend interpret error.
- `/cto-report`: profile the `/api/cto-report?days=365` query. Likely a slow aggregate over the full year that needs caching or a smaller default window.

**Fix recipes:**
- `/validation`: depends on the failure mode. If endpoint is broken → fix. If frontend is misinterpreting empty `items: []` → render an empty state.
- `/cto-report`: cache the 365-day report (TTL ~5 min) or change the default window to 30 days with explicit "Load 365" button.

**Files in scope:**
- `frontend/src/pages/Validation.jsx`
- `frontend/src/pages/CTOReport.jsx`
- `src/api/cloud_routes/core.py` or `src/api/cloud_routes/preflight.py` (validation endpoint)
- `src/api/cloud_routes/core.py` (CTO report endpoint)

**Verification:**
- `/validation` renders 37 Pass / 20 Warn within 5s
- `/cto-report` renders within 5s (cached or smaller default)

---

## Section 8 — P7 — Stress Test methodology shows 0.0% WR across all 7 scenarios

**Surface:** `/stress-test` page shows 7 historical scenarios (Yen Unwind, China Deval, Debt Ceiling, Q4 Selloff, Bear Market, COVID Crash, Financial Crisis) — **all with 0.0% Win Rate**.

**Uniformity is suspicious.** Even adverse scenarios should have *some* winners. Three hypotheses:
1. The mechanical bracket simulator always exits at stop, never target (e.g., target-fill logic broken)
2. Survivorship filter strips all winners
3. Win-rate computation reads wrong column (e.g., `pnl_dollars > 0` count divided by `total` but uses `wins=0` always)

**Investigation:**
1. Pick one scenario, run the simulator manually, inspect intermediate trade results.
2. Verify the win-counting logic in the stress-test pipeline.
3. Add a regression test with a hand-rolled "should win 50%" scenario.

**Files in scope:** TBD. Start with `frontend/src/pages/StressTest.jsx` to find the API endpoint, then trace backend.

**Verification:**
- At least one scenario shows non-zero WR
- Regression test: hand-crafted scenario expected to win 50% actually shows 50%

---

## Section 9 — P8 — Field formatters

**Surface 1:** `/live` page shows `LIVE EQUITY $100000.00` (no thousands separator).

**Fix:** `frontend/src/pages/LiveLedger.jsx` — wrap `equity.toFixed(2)` with `toLocaleString()` like Shadow Ledger does. Single-line edit.

**Surface 2:** Dashboard `OPEN SHADOW TRADES` table shows `0.00` in the DAYS column for trades opened 2026-05-08 (today is 2026-05-14, so should be ~6 days).

**Root cause hypothesis:** Entry-time math fails on date parsing. Looking at the table: newer trades (05-08) show `0.00`, mid-week trades (05-06) show `2.00`, older trades (05-05) show `3.00`. So **all trades opened in the most recent batch show 0** while a subset shows real days. Likely: `duration_days` is None for open trades (only computed at close), and the frontend falls through to a default of 0 instead of computing live `(now - entry_time).days`.

**Fix:** In the dashboard table renderer (`frontend/src/pages/Dashboard.jsx` OR a shared component), compute days-held client-side from `actual_entry_time` if `duration_days` is null.

**Files in scope:**
- `frontend/src/pages/LiveLedger.jsx` (equity format)
- `frontend/src/pages/Dashboard.jsx` (DAYS column live compute)

**Verification:**
- `/live` shows `$100,000.00` (with comma)
- `/` Dashboard "OPEN SHADOW TRADES" table shows real days held for all trades (6.00 for 05-08, 8.00 for 05-06 if today is 05-14, etc.)

---

## Section 10 — P9 — Packet rendering shows empty ENTRY/STOP/TARGETS/CONF

**Surface:** `/packets` page renders both visible packets (AAPL 2026-05-13 SCORE 80, AAPL 2026-05-08 SCORE 20) with:
```
ENTRY:
STOP:
TARGETS: /
CONF: 0/10
```
All fields empty. (Operator-flagged: "Packets is missing a bunch of info".)

**Root cause hypothesis:** Either the `recommendations` table rows have null `entry_price`/`stop_price`/`target_1`/`target_2`/`llm_conviction` (data not populated by packet writer), OR the frontend reads wrong column names. Given that the dashboard's OPEN SHADOW TRADES table DOES show entry/stop/target prices for the same tickers, the data exists somewhere — likely the issue is frontend reading the wrong source.

**Investigation:**
1. Open `/packets` page in Chrome DevTools → Network → inspect the `/api/packets?days=7` response shape. What does each packet row contain?
2. Open `frontend/src/pages/Packets.jsx` → check which fields it tries to render.
3. If response has the fields but they're null → backend issue: `packet_writer` not populating, OR endpoint joining wrong table.
4. If response has fields under different names → fix the frontend.

**Files in scope:**
- `frontend/src/pages/Packets.jsx`
- `src/api/routes/packets.py` (local endpoint)
- Possibly `src/api/cloud_routes/trades.py` (cloud endpoint)

**Verification:**
- `/packets` page → both AAPL packets show entry/stop/target prices populated
- LLM conviction shows actual value (not 0/10)

---

## Cross-cutting non-goals

These were observed but are out of scope for this rectification:
- Stage 1 corpus generation gaps
- Walk-forward gate behavior
- Training pipeline / model retraining
- Strategy regime classifier failure (UNKNOWN classification for 29/55 trades — separate ticker, requires data investigation not a UI fix)
- Render decommissioning leftovers

## Acceptance criteria for v0.36.1

1. All 9 P-clusters resolved per the section-level verification criteria above
2. Morning hotfixes #142–#147 included in the PR
3. `src/version.py` bumped to `0.36.1`
4. CHANGELOG.md updated with v0.36.1 entry
5. `python -m pytest tests/ -q` passes with no new failures vs the 5300-test floor
6. Manual verification: re-walk the 27 pages, confirm no `🔴` items remain
7. Operator approves the PR
8. `nssm restart ArcisDashboard` + `nssm restart ArcisWatchLoop` to load new code
9. Operator tags `v0.36.1` post-merge

## Test floor

Current floor: 5300 (Sprint 5 close baseline per CLAUDE.md). This patch is expected to ADD tests (HSHS regression, data-collection-stats column-aliasing, stress-test methodology, possibly more). Bump floor after merge if collected count grows past the previous baseline.

## Worktree discipline

All multi-file changes via `arcis:code` PM dispatch with `isolation: "worktree"`. Per memory `feedback_strict_rigor_no_handwave`: worktree isolation, sibling-search, no skip/weaken/bypass, PM-side verification, wave checkpoints.

Operator quote (carry-forward): "rather take a full day than hand wave."
