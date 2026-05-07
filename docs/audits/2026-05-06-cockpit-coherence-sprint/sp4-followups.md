# Sprint 4 Follow-Up Issues — Sprint 3 Cockpit Coherence Closeout

**Generated**: 2026-05-07 (T23 closeout)
**Sprint**: cockpit-coherence-2026-05-06
**Instructions**: Paste each item below as a GitHub issue via `gh issue create --title "..." --body "..." --label "..."`.

---

## Issue 1: `#SP4-shadow-metrics-live-cohort`

**Title**: `fix(api): wire source='live' SQL filter for /api/shadow/metrics when desk='live'`

**Body**:
```
## Context

Sprint 3 T9 followup (#SP4-shadow-metrics-live-cohort). In `src/api/cloud_routes/analytics.py`, the `_desk_clause()` helper filters by the `desk` column, not the `source` column. As a result, `desk='live'` currently maps to `cohort_id='trades.all_closed'` (same as all other desk values) instead of `trades.live_only`.

## What to fix

1. Identify the SQL column that carries `source='live'` for live trades in `shadow_trades`.
2. Wire a proper `source = 'live'` predicate in `_desk_clause()` (or equivalent) when `desk='live'`.
3. Update `cohort_id` to `'trades.live_only'` for the live desk path.
4. Update the test: replace `test_shadow_metrics_all_desks_emit_all_closed` with a per-desk cohort assertion.

## Files

- `src/api/cloud_routes/analytics.py` (shadow_metrics endpoint)
- `tests/` (update desk cohort tests)

## Labels

enhancement, sprint-4, cockpit-coherence-followup
```

---

## Issue 2: `#SP4-status-open-positions-cohort`

**Title**: `fix(api): align /api/status._meta.open_positions cohort label with SQL filter`

**Body**:
```
## Context

Sprint 3 T8/T9 followup (#SP4-status-open-positions-cohort). In `src/api/cloud_routes/core.py`, the `open_positions` SQL at line ~148 may use a different filter than the cohort label emitted at line ~189. The cohort label says `trades.open` but the SQL may filter differently.

## What to fix

1. Read `core.py` lines 140-200 to verify SQL filter vs cohort label.
2. Align the cohort_id emitted by `meta_entry()` with the actual SQL predicate.
3. Add a regression test asserting `status._meta.open_positions.cohort` matches the SQL filter semantics.

## Files

- `src/api/cloud_routes/core.py`
- `tests/api/test_status.py`

## Labels

bug, sprint-4, cockpit-coherence-followup
```

---

## Issue 3: `#SP4-calmar-debt`

**Title**: `refactor(analytics): migrate 3 hand-rolled Calmar sites to canonical calmar_ratio() helper`

**Body**:
```
## Context

Sprint 3 T1 followup (#SP4-calmar-debt). The T1 Calmar fix replaced the hand-rolled formula in `analytics.py`. Three additional hand-rolled Calmar sites were allowlisted with comments in `tests/test_calmar_canonical_only.py` but not yet migrated:

1. `src/evaluation/cto_report.py` (search for `calmar`)
2. `src/simulation/engine.py` (search for `calmar`)
3. `src/evaluation/backtester.py` (search for `calmar`)

## What to fix

For each site:
1. Replace the hand-rolled formula with `from src.evaluation.statistics import calmar_ratio`.
2. Call `calmar_ratio(returns_series, max_drawdown)` with appropriate args.
3. Remove the allowlist entry from `tests/test_calmar_canonical_only.py`.
4. Add a regression test (or extend existing) confirming the site uses the canonical helper.

## Files

- `src/evaluation/cto_report.py`
- `src/simulation/engine.py`
- `src/evaluation/backtester.py`
- `tests/test_calmar_canonical_only.py`

## Labels

technical-debt, sprint-4, cockpit-coherence-followup
```

---

## Issue 4: `#SP4-stop-loss-fallback`

**Title**: `fix(frontend): locate and fix downstream stop_loss display sign-inversion`

**Body**:
```
## Context

Sprint 3 T4 downgrade followup (#SP4-stop-loss-fallback). T4 investigated the E2 stop_loss sign bug and determined the sign inversion is in the **display layer** rather than the backend data. The backend (`executor.py:1872`, `reconcile.py:131`) emits correct signed values; the inversion happens when the dashboard renders stop_loss exits.

## What to fix

1. Identify the frontend component(s) that render stop_loss P&L (likely `LiveLedger.jsx`, `TradeHistory.jsx`, or a shared trade-row component).
2. Find where the sign flip occurs in the display path.
3. Fix the sign inversion so stop_loss exits show negative P&L correctly.
4. Add a frontend test asserting stop_loss renders as negative.

## Files

- `frontend/src/pages/LiveLedger.jsx` (candidate)
- `frontend/src/pages/TradeHistory.jsx` (candidate)
- Frontend shared components (search for `stop_loss` render path)

## Labels

bug, sprint-4, cockpit-coherence-followup
```

---

## Issue 5: `#SP4-render-pg-reconcile`

**Title**: `test(ci): extend T16 dashboard reconciliation test to Postgres`

**Body**:
```
## Context

Sprint 3 T16 followup (#SP4-render-pg-reconcile). The `tests/test_dashboard_reconciliation.py` created in T16 is SQLite-only per spec §5 B3. The Postgres path (Render cloud deployment) has a different execution path and could diverge.

## What to fix

1. Add a `pytest.mark.postgres` variant of `test_dashboard_reconciliation.py` that connects to a test Postgres instance.
2. Parametrize the existing tests to run against both SQLite and Postgres fixtures.
3. Add to CI matrix when `DATABASE_URL` env is available (skip otherwise).

## Files

- `tests/test_dashboard_reconciliation.py`
- `tests/conftest.py` (postgres fixture)
- CI workflow (add `DATABASE_URL` secret)

## Labels

testing, sprint-4, cockpit-coherence-followup
```

---

## Issue 6: `#SP4-kpis-meta-reconciliation-test`

**Title**: `test(ci): regression-lock /api/kpis _meta envelope (T16 substituted stress-test/results)`

**Body**:
```
## Context

Sprint 3 T16 followup (#SP4-kpis-meta-reconciliation-test). The T16 reconciliation test covers 5 endpoints but substituted `/api/stress-test/results` for `/api/kpis` due to fixture isolation complexity. The `/api/kpis` `_meta` envelope (wired by T8/T9) lacks a dedicated reconciliation regression test.

## What to fix

1. Add `test_kpis_meta_envelope_reconciliation` to `tests/test_dashboard_reconciliation.py`.
2. Assert `_meta.rf_adjusted_excess_sharpe.cohort == 'kpi.canonical'`, `_meta.win_rate.cohort == 'kpi.canonical'`, and that `n` fields are non-negative integers.
3. Use same mock-runtime pattern as existing T16 tests.

## Files

- `tests/test_dashboard_reconciliation.py`

## Labels

testing, sprint-4, cockpit-coherence-followup
```

---

## Issue 7: `#SP4-tanstack-strategyresearch-platformstatus`

**Title**: `fix(frontend): wrap bare queryFn refs in StrategyResearch.jsx:41 and PlatformStatusWidget.jsx:13`

**Body**:
```
## Context

Sprint 3 T22 ESLint investigation followup (#SP4-tanstack-strategyresearch-platformstatus). The ESLint `lint:queryfn` rule passes on the post-T17-T21 frontend. However, during T22 investigation, two pre-existing bare-queryFn sites were noted:

- `frontend/src/pages/StrategyResearch.jsx:41` — bare `queryFn: api.getStrategyResearch` (or similar)
- `frontend/src/components/PlatformStatusWidget.jsx:13` — bare `queryFn: api.getPlatformStatus` (or similar)

These were pre-existing before Sprint 3 and are NOT in the files that T17-T21 touched. Verify these sites exist and wrap them.

## What to fix

1. Read both files, confirm bare-queryFn sites at the referenced lines.
2. Wrap each in `() => api.method()` arrow form.
3. Add tests asserting `typeof queryFn === 'function'` for each site.
4. Run `npm --prefix frontend run lint:queryfn` to confirm no new failures.

## Files

- `frontend/src/pages/StrategyResearch.jsx`
- `frontend/src/components/PlatformStatusWidget.jsx`
- Corresponding test files

## Labels

bug, sprint-4, cockpit-coherence-followup
```

---

## Issue 8: `#SP3-T12-pnl-card`

**Title**: `feat(frontend): add dollar P&L primary KPI card to 5-card KPIStrip`

**Body**:
```
## Context

Sprint 3 T12 followup (#SP3-T12-pnl-card). The 5-card KPIStrip on the Dashboard shows: rf-adjusted excess Sharpe, SPY-relative, win rate, Stage traffic light, and promotion-gate vote count. There is no dollar P&L card.

During T12, the `total_pnl_dollars` field from `/api/kpis` `_meta` envelope has no primary value card to attach a badge to — the field exists in the backend but has no frontend display surface.

## What to fix

1. Add a 6th KPI card (or replace one of the lower-priority cards) showing dollar P&L as its headline value.
2. Wire `safeKpis._meta?.total_pnl_dollars` badge to the new card.
3. Update `KPIStrip.test.jsx` with a test for the new card.
4. Design decision needed: add 6th card OR replace promotion-gate vote card (discuss with operator).

## Files

- `frontend/src/components/dashboard/KPIStrip.jsx`
- `frontend/src/components/dashboard/KPIStrip.test.jsx`
- `src/api/cloud_routes/kpis.py` (verify total_pnl_dollars is emitted)

## Labels

enhancement, sprint-4, ux
```

---

## Issue 9: `#47` — Telegram + email triage findings (cross-domain)

**Title**: `chore(notifications): triage and remediate findings from Telegram + email sweep audit (#46)`

**Body**:
```
## Context

Operator-tracked task #47 (folded into Sprint 4 per operator decision 2026-05-07). Audit task #46 ("Exhaustive sweep — Telegram notifications + email updates") completed; this issue tracks the remediation work.

The audit surfaced findings spanning notification template hygiene, mute/digest rules, auth/access policy, and channel routing. Sprint 3 closed cockpit-coherence findings on the dashboard surface; Sprint 4 will additionally close the notification-channel surface so the operator's incoming signal stream matches the dashboard's quality bar.

## What to fix

1. Read the #46 audit output (location: `docs/audits/2026-04-XX-telegram-email-sweep/` or wherever the sweep filed findings).
2. Triage each finding by severity (CRITICAL / IMPORTANT / NOISY / NIT) — same vocabulary as the cockpit audit.
3. Group fixes into Sprint 4 batches alongside the 8 cockpit-coherence followups.
4. Sprint 4 will need its own `arcis:design` cycle (audit→spec→plan) to consolidate the 9 items into one execution plan before dispatch (Sprint 3's spec was 56KB; Sprint 4 will be similar magnitude).

## Files

TBD per Sprint 4 spec — likely:
- `src/notifications/` (channel routing, templates)
- `src/services/email_*.py` (email send paths)
- `src/services/telegram_*.py` (telegram bot, command handlers)
- `config/settings.*.yaml` (mute/digest rules)
- `docs/operator-guide.md` (notification troubleshooting)

## Labels

chore, sprint-4, notifications, cross-domain

## Cross-link

- Audit task: #46 (completed)
- Operator-tracker task: #47 (pending until Sprint 4 closes)
- Sibling Sprint 4 issues: #SP4-shadow-metrics-live-cohort, #SP4-status-open-positions-cohort, #SP4-calmar-debt, #SP4-stop-loss-fallback, #SP4-render-pg-reconcile, #SP4-kpis-meta-reconciliation-test, #SP4-tanstack-strategyresearch-platformstatus, #SP3-T12-pnl-card
```

---

## Issue 10: `#SP4-cloud-req-import-guardrail`

**Title**: `test(ci): add cloud-deploy import guardrail to catch missing requirements-cloud.txt entries`

**Body**:
```
## Context

Sprint 3 integration deploy (#1006) failed because T1's Calmar canonical helper refactor (`src/api/cloud_routes/analytics.py` → `src/evaluation/statistics.py` → `from scipy import stats`) introduced a transitive scipy import that wasn't in `requirements-cloud.txt`. Hot-fixed by #1007.

This is the **fourth recurrence** of the same bug class:
- jsonschema (some past sprint)
- numpy (PR #690)
- requests (some later sprint)
- scipy (Sprint 3, #1007)

Each time, the cloud-routes import chain pulls in a package that's in `requirements.txt` but not `requirements-cloud.txt`, the deploy crashes on startup, and we react with a one-line addition. The pattern indicates a structural blind spot: there's no pre-merge check that verifies `src.api.cloud_app` is importable under the cloud-only requirement set.

## What to fix

Add a pytest test (or a CI-only script) that:
1. Creates a temporary venv with ONLY `requirements-cloud.txt` installed.
2. Runs `python -c "from src.api.cloud_app import app"`.
3. Asserts no `ModuleNotFoundError`.

Alternative (lighter weight): a static-analysis test that enumerates all imports reachable from `src/api/cloud_app.py` (via AST walk) and verifies each top-level package name is either stdlib or in `requirements-cloud.txt`.

## Files

- `tests/test_cloud_requirements_imports.py` (NEW)
- (Optional) `scripts/check_cloud_deploy_imports.py` for CI invocation

## Labels

test, ci, sprint-4, cloud-deploy, regression-prevention
```

---

## Issue 11: `#SP4-settings-backend-float32-storage`

**Title**: `fix(backend): clean up float32 storage of risk.planned_risk_pct_min/max settings`

**Body**:
```
## Context

Sprint 3 visual-verify investigation (2026-05-07) on the live halcyonlab.app dashboard surfaced that the Settings page's Risk % Min and Risk % Max inputs render correctly in the actual DOM (HTML `value="0.005"`, JS `.valueAsNumber=0.005`), BUT Chrome's accessibility tree reports `aria-valuenow="0.004999999888241291"`.

Investigation showed:
- T11's frontend mount-time clamp (`clampToStep` in `Settings.jsx:57`) IS working as designed.
- The `aria-valuenow` value reported by Chrome is a float32-cast representation that the browser computes from the input's numeric value during accessibility-tree construction.
- The float32 noise originates upstream: the backend stores `risk.planned_risk_pct_min/max` as float32 (likely via Python `numpy.float32` cast somewhere in the config-overrides write path, OR SQLite REAL with implicit precision loss).
- The same pattern shows in `aria-valuemin="0.0010000000474974513"` (float32 cast of 0.001) — the `min` HTML attribute the frontend passes is "0.001" but Chrome reports the float32-cast.

This is NOT a Sprint 3 frontend regression. The frontend clamp is correct. But the underlying storage cleanup would prevent the noise from surfacing in any tool that reads via the float32-cast path (e.g., the audit tool that captured the original concern, screen readers that surface aria-valuenow, third-party automation).

## What to fix

1. Trace the write path for `config_overrides` updates of `risk.planned_risk_pct_*` keys. Identify where the value transits through float32 (vs being preserved as Python float / SQLite REAL).
2. Either:
   a. Cast to float64 before write (preserves IEEE-754 nearest double of 0.005, which is closer to "exactly 0.005" than the float32 cast).
   b. Add a backend clamp using the same `decimalsFromStep` / `toFixed` semantics the frontend uses, then store as REAL.
3. Verify via Chrome's accessibility tree that `aria-valuenow="0.005"` (no float32 noise) post-fix.

## Files

- `src/api/cloud_routes/settings.py` (or wherever config_overrides are written)
- `src/schema/registry.py` (verify column type is REAL not REAL with explicit FLOAT precision)
- Possibly `src/services/config_overrides.py`

## Labels

bug, sprint-4, settings, backend, accessibility

## Cross-link

- Originally surfaced as audit 23-C1 in `docs/audits/2026-05-06-dashboard-coherence/summary.md`
- Sprint 3 T11 closed the frontend display path; this issue closes the underlying storage path
- Investigation docs: `docs/audits/2026-05-06-cockpit-coherence-sprint/visual-verify/results.md`
```

---

*End of SP4 followup issue list. 11 issues total. Run `gh issue create` for each above.*
