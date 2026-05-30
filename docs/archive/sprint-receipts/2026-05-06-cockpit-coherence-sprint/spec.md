# Sprint 3 — Cockpit Coherence (Wave 1+2) Design Spec — REVISION 2 (FINAL)

**Audit reference:** `docs/audits/2026-05-06-dashboard-coherence/`
**Sprint identifier:** Sprint 3 — Cockpit Coherence
**Spec date:** 2026-05-06
**Status:** Draft v3 FINAL (post-feasibility-v2 mechanical corrections)
**Test floor on entry:** 4602 (post-Sprint-2)
**Test floor on exit:** 4602 + 44 new test cases = **exactly 4646** (strict equality at sprint closeout)

---

## 0. Revision Notes

### v2 → v3 changelog (mechanical corrections only — no new design decisions)

**Major fixes:**
- **Task 10 batch placement** — v2 placed Task 10 (B1+B2 header migration) in the same parallel batch as its prerequisite Task 8. Corrected: T10 now lands in the batch AFTER T8 completes (alongside T9, which has the same dependency).
- **Tasks 1/2/3 analytics.py parallel-edit hazard** — v2 had T1 (Calmar), T2 (Attribution), T3 (Monitoring) all editing `src/api/cloud_routes/analytics.py` in parallel Batch 0. This passes pre-commit scope-check but trips the pre-push stale-base hook on the second/third pusher (same disease that drove the E1 split, D8). Corrected: T2 now `depends_on=[1]`, T3 now `depends_on=[2]`. T2 and T3 sequence in their own batches. Per-bug task granularity preserved (matches reviewer dispatch table in §11.3). Trade-off accepted: serial analytics.py touches (3 commits, not 1). T4 stays parallel — it touches engine.py + executor.py only, no analytics.py.

**Minor fixes:**
- **Task 17 path correction** — `frontend/src/pages/RevenueProjection.jsx` corrected to `frontend/src/components/RevenueProjection.jsx` (filesystem-verified).
- **Frontend test files marked NEW** — `Layout.test.jsx`, `Settings.test.jsx`, `Health.test.jsx` do not exist on disk; spec §2.1 + §9.1 corrected from `Yes (extend)` / `EXTEND` to `NEW`.
- **`tests/api/test_monitoring_history_fallback.py` naming collision avoided** — existing `tests/api/test_monitoring_history_shape.py` covers shape contracts. New file renamed to `tests/api/test_monitoring_history_fallback.py` to reflect the 200-with-empty-fallback contract scope.

No new design decisions; v2 Decision Log entries (D1-D20) carry forward unchanged. The E6 paired-overlap statistics (D4), 3-state header fallback (D7), and secure-context clipboard fallback (D15) remain as in v2. v3 adds a single Decision (D21) recording these mechanical corrections.

---

## 0.1 Revision Notes (v1 → v2)

Reviewer findings addressed:

**Critical (file/path corrections):**
- `/api/model-performance` correctly located in `src/api/cloud_routes/training.py:549` (NOT analytics.py).
- `tests/test_cto_report.py` is the existing path (NOT `tests/api/test_cto_report.py`).
- `tests/api/test_status.py` is NEW (created in Task 8).
- `IS_CLOUD` imports from `'../config'` (not `'@/utils/env'`); 12+ existing call sites confirmed (App.jsx:9, Layout.jsx:5, contexts/WebSocketContext.jsx:2, etc.).
- `frontend/src/pages/Dashboard.jsx` (NOT `frontend/src/components/dashboard/Dashboard.jsx`).
- `tests/simulation/` and `tests/frontend/` directories created in Task 1/Task 4 setup.
- §3.8 reworded: `raises 500 (Render proxy may surface as 503)`.
- KPIStrip line refs re-anchored to search terms (`caption=` calls at `'canonical T1.03'`, `'quarantine-filtered'`, `'S='`).

**Critical (scope/dependency):**
- Task 17 split into **17a (10 non-conflict files)** and **17b (6 conflict files, depends_on Tasks 2/11/13/14)** to honor `max 4 files_in_scope` constraint and avoid pre-commit scope-check + pre-push stale-base hook failures.
- Each split task's `files_in_scope` ≤4. The remaining ShadowLedger/TradeHistory wraps stay in 17a; conflict-prone wraps in 17b.
- Tasks 11+13 carry explicit Health.jsx co-ownership note in scope_fence.

**Major (statistical correctness):**
- E6/D5 corrected: McNemar's gate now uses **paired-overlap count** (BOTH arms resolved), not `min(rr, lr)`. Verified `rr` and `lr` in analytics.py:735/741 are MARGINAL counts (independent any-resolution).

**Major (header fallback):**
- Three explicit fallback states: pending → `'TL: …'`, loaded-but-null → `'TL: COMPUTING'`, errored → `'TL: ERR'`. Tooltip surfaces `last_computed_at` when present.

**Major (B3 cohort handling):**
- shadow_metrics cohort resolution defined explicitly; test asserts cohort match BEFORE asserting n equality. B3 explicitly scoped as SQLite-only; Postgres validation deferred to Sprint 4 runbook task.

**Major (AST guardrail):**
- Replaced Python AST walker with **ESLint custom rule** at `frontend/eslint-rules/no-bare-queryfn-with-args.js`, wired into `frontend/eslint.config.js`. Pytest fixture shells out to `npm --prefix frontend run lint:queryfn`.

**Major (clipboard secure context):**
- ActionButton's copy handler checks `navigator.clipboard && window.isSecureContext` first; falls back to `<pre>` with select-on-click + `Press Ctrl+C` hint. Promise rejections caught.

**Major (test floor math):**
- Replaced 'lines added' with explicit test-case counts. Sum: **44 new test cases** (recounted in §9.1). Sprint closeout asserts strict equality: `pass_count == 4646`.

**Minor (folded in):**
- F2 Task 14 description explicitly defers Settings IB toggles to Task 15.
- E3 onBlur clamp: only clamps when typed value differs from displayed by less than `step/2`.
- LoadingState API: `retryDisabledFor={ms}` cooldown added.
- Task 4 (E2 stop_loss): pre-investigation done — `src/shadow_trading/executor.py:1872` constructs the stop_loss exit; `reconcile.py:131` matches the exit_reason. Files added to scope.
- 5 Calmar SoT: new CI test `tests/test_calmar_canonical_only.py` (Task 1 scope).
- Per-cohort callsite justification in §2.3.

---

## 1. Overview

Sprint 3 implements Wave 1+2 of the cockpit-coherence audit: eradicate correctness bugs surfaced by the operator's audit pass on `halcyonlab.app`, install three coherence primitives (additive `_meta` envelope, shared `<LoadingState>`, shared `<ActionButton cliOnly>`), and reconcile the header source-of-truth — all without breaking the existing `/api/*` response contracts.

**Five groups in scope (see CODEBASE_REPORT for catalogs):**

| Group | Theme | Tasks | Deep-report focus |
|-------|-------|-------|-------------------|
| **E** | Correctness bugs | 8 sub-bugs | Focus 1, 2, 3, 4, 9 |
| **A** | Cohort taxonomy | additive `_meta` envelope + KPICard prop + 3-page retrofit | Focus 6, 10 |
| **B** | Header source-of-truth | reconcile TL: NOT SET / 25 POSITIONS, CI reconciliation test | Focus 5 |
| **C** | Loading state | shared `<LoadingState>`, 4-widget migration | Focus 7 |
| **F** | Operator-action ambiguity | shared `<ActionButton cliOnly>`, 5-page migration | Focus 8 |

**Out of scope (UNCHANGED, deferred):** Groups D, G, H, I; Render Postgres replication gap; 88% reconciled-stale exits; Council narrative redesign.

**Operator design choices (LOCKED, restated):**
1. Cohort envelope: ADDITIVE `_meta` sibling field. Existing keys stay numeric; new sibling object `_meta: { <field_name>: { cohort, label, n } }` per endpoint **section**. Backwards-compatible.
2. CLI-only UX: disabled-but-visible button + dimmed styling + `[CLI only]` badge + tooltip with copy-CLI affordance + 'Why disabled' reason string. Reference: `frontend/src/pages/LiveLedger.jsx:271-276`.

---

## 2. Architecture

### 2.1 Files touched (verified)

| File | Existing? | Change kind | Group |
|------|-----------|-------------|-------|
| `src/api/cloud_routes/analytics.py` | Yes | Edit (calmar L568, attribution L718-767, monitoring L935-957) | E5/E6/E7 + A1 |
| `src/api/cloud_routes/training.py` | Yes | Edit (model-performance L549) | A1 |
| `src/api/cloud_routes/core.py` | Yes | Edit (status _meta) | A1 |
| `src/api/cloud_routes/kpis.py` | Yes | Edit (kpis _meta) | A1 |
| `src/api/cloud_routes/trades.py` | Yes | Edit (shadow/metrics _meta) | A1 |
| `src/api/cohort_meta.py` | NEW | Helper module | A1 |
| `src/simulation/engine.py` | Yes | Edit (profit_factor 999 → null at L458) | E4 |
| `src/shadow_trading/executor.py` | Yes | Read-only (L1872 stop_loss site) | E2 |
| `src/shadow_trading/exit_reason.py` | Yes | Edit if needed (sign-convention) | E2 |
| `src/shadow_trading/reconcile.py` | Yes | Read-only (L131 stop_loss matcher) | E2 |
| `src/evaluation/statistics.py` | Yes | Read-only (canonical Calmar at L131) | E5 |
| `tests/test_cto_report.py` | Yes (existing) | Edit (per-section _meta assertions) | A1 |
| `tests/api/test_kpis.py` | Yes | Edit (_meta assertions) | A1 |
| `tests/api/test_status.py` | NEW | Create (status _meta + structural tests) | A1 |
| `tests/api/test_attribution_stats.py` | NEW | Paired-n math + _meta envelope | E6 |
| `tests/api/test_monitoring_history_fallback.py` | NEW | Fallback + _meta envelope | E7 |
| `tests/api/test_calmar_unit_audit.py` | NEW | Regression-lock formula | E5 |
| `tests/test_calmar_canonical_only.py` | NEW | Guardrail: no other Calmar formulas in src/ | E5 (D4 follow-up) |
| `tests/test_dashboard_reconciliation.py` | NEW | CI cross-endpoint reconciliation (SQLite scope) | B3 |
| `tests/test_eslint_queryfn_guardrail.py` | NEW | Pytest fixture shelling to npm lint:queryfn | E1 |
| `tests/test_profit_factor_sentinel.py` | NEW (root tests/) | E4 sentinel emit-null | E4 |
| `tests/test_stop_loss_sign.py` | NEW (root tests/) | E2 sign convention | E2 |
| `frontend/src/api.js` | Yes | Edit (add getKpis if absent) | B1 |
| `frontend/src/components/Layout.jsx` | Yes | Edit (header TL fallback states) | B1/B2 |
| `frontend/src/components/Layout.test.jsx` | NEW | 3 fallback states | B1 |
| `frontend/src/components/dashboard/KPIStrip.jsx` | Yes | Edit (KPICard meta prop; anchor near `caption=` calls and `subLine`) | A3 |
| `frontend/src/components/dashboard/KPIStrip.test.jsx` | Yes | Extend (meta-prop test) | A3 |
| `frontend/src/components/LoadingState.jsx` | NEW | Shared 3-state primitive + retryDisabledFor | C1 |
| `frontend/src/components/LoadingState.test.jsx` | NEW | Test | C1 |
| `frontend/src/components/ActionButton.jsx` | NEW | Shared cliOnly variant + secure-context fallback | F1 |
| `frontend/src/components/ActionButton.test.jsx` | NEW | Test (+ non-secure-context path) | F1 |
| `frontend/eslint-rules/no-bare-queryfn-with-args.js` | NEW | Custom ESLint rule | E1 |
| `frontend/eslint.config.js` | Yes | Edit (register rule + lint:queryfn script) | E1 |
| `frontend/package.json` | Yes | Edit (add `lint:queryfn` npm script) | E1 |
| `frontend/src/pages/Dashboard.jsx` | Yes | Edit (KPICard meta wiring) | A4 |
| `frontend/src/pages/TradeHistory.jsx` | Yes | Edit (E1 wrap L237 + meta) | E1+A4 |
| `frontend/src/pages/Strategy.jsx` | Yes | Edit (meta wiring) | A4 |
| `frontend/src/pages/Attribution.jsx` | Yes | Edit (label fix + E1 wrap L10) | E6+E1 |
| `frontend/src/pages/ShadowLedger.jsx` | Yes | Edit (E1 wraps L476/L478/L481) | E1 |
| `frontend/src/pages/Settings.jsx` | Yes | Edit (SettingInput precision clamp + E1 wraps + IB toggles cliOnly) | E3+E1+F2 |
| `frontend/src/pages/Settings.test.jsx` | NEW | E3 clamp + E8 IS_CLOUD gate + IB cliOnly tests | E3+E8+F2.B |
| `frontend/src/pages/Health.test.jsx` | NEW | E8 IS_CLOUD gate tests | E8 |
| `frontend/src/components/dashboard/BrokerExceptionsPanel.jsx` | Yes | Edit (LoadingState migration) | C2 |
| `frontend/src/pages/DBSchema.jsx` | Yes | Edit (LoadingState migration) | C2 |
| `frontend/src/pages/Health.jsx` | Yes | Edit (LoadingState + IS_CLOUD IB-status flag + E1 wraps) | C2 + E8 + E1 |
| `frontend/src/pages/Monitoring.jsx` | Yes | Edit (LoadingState + isError + E1 wraps) | C2 + E7 |
| `frontend/src/pages/LiveLedger.jsx` | Yes | Edit (ActionButton + E1 wraps) | F2+E1 |
| `frontend/src/components/DiagnosticKickoffButtons.jsx` | Yes | Edit (ActionButton) | F2 |
| `frontend/src/pages/Simulation.jsx` | Yes | Edit (ActionButton dedupe + E1 wrap L50) | F2+E1 |
| `frontend/src/pages/Council.jsx` | Yes | Edit (ActionButton + E1 wrap L287) | F2+E1 |
| `frontend/src/pages/Diagnostics.jsx` | Yes | Edit (DiagnosticKickoffButtons consumer; no separate button changes) | F2 |
| Plus E1-stylistic-only sites | Yes | Edit (wrap in arrow) | E1 (Task 17a/17b) |
| `CHANGELOG.md` | Yes | Edit (Unreleased) | All |
| `config/known_violations.json` | Yes | Maybe edit (test_repo_structure.py) | All |

### 2.2 Component diagram (unchanged from v1)

```
 ┌──────────────────────────────────────────────────────────────┐
 │                     React Frontend (cloud)                   │
 │  Layout.jsx ──[useQuery 'kpis']───────────┐                  │
 │   (header TL — 3 fallback states)         │                  │
 │  KPIStrip.jsx ──[useQuery 'kpis']─────────┤  shared cache    │
 │                                            ▼                  │
 │                                    /api/kpis (TanStack)      │
 │  KPICard ◄─── meta={...} ◄─── Dashboard.jsx (A4)             │
 │  ActionButton ◄── cliOnly + secure-context-aware copy (F1)   │
 │  LoadingState ◄── {isLoading,isError,isEmpty,error,retry}    │
 │                   + retryDisabledFor cooldown (C1)            │
 └──────────────────────────────────────────────────────────────┘
            │ HTTP (Bearer)
            ▼
 ┌──────────────────────────────────────────────────────────────┐
 │                   FastAPI cloud_routes/*                     │
 │  /api/kpis     ──┬─ + _meta {...}                            │
 │  /api/cto-report ┤  + _meta per-section                      │
 │  /api/attribution┤  fix L762 → paired_overlap (E6)           │
 │  /api/monitoring/history → 200+empty+note (E7) at L935-957   │
 │  /api/model-performance ── + _meta (training.py L549) ←FIX   │
 │  /api/shadow/metrics  ── + _meta (cohort:trades.all_closed)  │
 │  /api/stress-test/results ── + _meta                          │
 │  /api/simulation/results ── + _meta (PF=null sentinel L458)  │
 │  /api/strategy-detail/* ── + _meta                            │
 │  /api/build-score ── + _meta (cohort:none)                   │
 │  /api/health/hshs ── + _meta per-section                     │
 └──────────────────────────────────────────────────────────────┘
```

### 2.3 Cohort taxonomy (8 cohorts; per-cohort callsite justification)

| cohort_id | Definition | Callsites |
|-----------|------------|-----------|
| `kpi.canonical` | `filter_fully_instrumented(rows) AND quarantined=0` | `/api/kpis` only |
| `trades.all_closed` | `status='closed' AND COALESCE(quarantined,0)=0 AND outcome_stats_filter_sql()` | `/api/cto-report` trade_summary, `/api/shadow/metrics` (default cohort) |
| `trades.strategy` | `trades.all_closed AND strategy_type=<strategy>` | `/api/strategy-detail/{strategy_type}` |
| `trades.model` | `trades.all_closed AND model_version IS NOT NULL AND model_version != 'unknown'` | `/api/model-performance` |
| `trades.live_only` | `trades.all_closed AND source='live'` | `/api/status._meta.open_positions`, `/api/shadow/metrics` (when desk filter='live'), `/api/live/summary` |
| `stress.scenario` | `stress_test_results.scenario=<scenario_id>` | `/api/stress-test/results`, `/api/simulation/results` |
| `attribution.pairs` | `attribution_trades` table (separate from shadow_trades) | `/api/attribution/stats` only |
| `none` | metric not cohort-bound | `/api/build-score`, `/api/health/hshs` overall section |

**shadow_metrics cohort resolution rule (NEW for v2):** `/api/shadow/metrics` emits `cohort='trades.live_only'` IFF its query filtered by `source='live'` (via desk parameter); otherwise emits `cohort='trades.all_closed'`. The endpoint MUST emit a single cohort per request based on the actual SQL filter applied. Rule documented in `cohort_meta.py` docstring.

### 2.4 Schema (TypeScript-style)
```ts
MetaEntry = { cohort: string, label: string, n: number }
MetaEnvelope = { [field_name: string]: MetaEntry }

// Per-section (cto-report):
{ trade_summary: {...}, performance: {...}, fund_metrics: {...},
  _meta: { trade_summary: { win_rate: {cohort,label,n}, ... }, ... } }

// Per-endpoint flat (kpis):
{ rf_adjusted_excess_sharpe: {...}, win_rate: {...},
  _meta: { rf_adjusted_excess_sharpe: { cohort:"kpi.canonical", ... }, ... } }
```

---

## 3. Group E — Correctness Bugs

### 3.1 E1 — TanStack v5 bare-queryFn anti-pattern (28 sites split)

**Root cause:** `useQuery({ queryFn: api.foo })` passes `QueryFunctionContext` as positional arg. With optional URL-encoded params, result is `?desk=%5Bobject+Object%5D`.

**Three buggy sites (correctness):** ShadowLedger.jsx:476 `getOpenTrades`, :478 `getAccount`, TradeHistory.jsx:237 `getSharpeAttribution`.

**25 stylistic-only sites:** wrap for consistency. Sites enumerated in deep-report Focus 1.

**Split owing to scope-fence + file-collision constraints (max 4 files_in_scope per task; pre-commit scope-check + pre-push stale-base hooks):**

- **Task 17a (parallel-safe):** wraps in files NOT touched by Tasks 2/11/12/13/14: `Layout.jsx`, `RevenueProjection.jsx`, `Docs.jsx`, `IBShadow.jsx`, `ModelPerformance.jsx`, `Notes.jsx`, `Training.jsx`, `Validation.jsx`, `StressTest.jsx`. Plus `Dashboard.jsx` (pages/) — already touched by Task 12, so 17a depends on 12.
- **Task 17b (sequenced):** wraps in files OWNED by prior tasks: `Attribution.jsx` (Task 2), `Settings.jsx` (Task 11+15), `Health.jsx` (Tasks 11+13), `Monitoring.jsx` (Task 13 + Task 3), `LiveLedger.jsx` (Task 14), `Council.jsx` (Task 14), `Simulation.jsx` (Task 14+4), `DiagnosticKickoffButtons.jsx` (Task 14). 17b depends_on [2, 3, 11, 13, 14] (and 17a/17c may be in parallel).
- **Task 17c (ESLint guardrail, parallel-safe):** creates `frontend/eslint-rules/no-bare-queryfn-with-args.js`, registers in `frontend/eslint.config.js`, adds `lint:queryfn` npm script in `frontend/package.json`, and adds pytest fixture `tests/test_eslint_queryfn_guardrail.py` that shells out to `npm --prefix frontend run lint:queryfn`. Since the lint will fail on any unwrapped sites, 17c is sequenced AFTER 17a+17b.

**Sibling-search rule:** developer greps each touched file for `queryFn: api\.[A-Za-z]+` patterns and confirms all wraps applied.

### 3.2 E2 — desk=[object Object] (subsumed by E1)

Same root cause; the 3 buggy-site wraps must pass the actual `desk` argument from component state (ShadowLedger.jsx has `sourceFilter` at line ~470).

### 3.3 E3 — stop_loss sign flip

**Pre-investigation (NEW for v2):** Confirmed sites for stop_loss + pnl coupling:
- `src/shadow_trading/executor.py:1847` — bracket-target-fill construction (take_profit/stop_loss split).
- `src/shadow_trading/executor.py:1872` — direct stop_loss exit construction.
- `src/shadow_trading/reconcile.py:131` — reconciliation of `stop_hit/stop_loss` exits.

Fix lives in whichever of these computes pnl_dollars/pnl_pct from entry/exit prices. Task 4 reads all three and edits the one(s) where the sign flip occurs. If none flip the sign (i.e., the bug is downstream display-only), Task 4 downgrades to 'investigation only' with Sprint 4 follow-up tracked in TaskList.

**Test:** `tests/test_stop_loss_sign.py` — given exit with `exit_reason='stop_loss'`, entry=100, exit=95: `pnl_pct < 0` AND `pnl_dollars < 0`. Sibling assertion: `target_hit` exits yield `pnl > 0` (no inversion).

### 3.4 E4 — Float-precision input clamp

**Site:** `frontend/src/pages/Settings.jsx:43` SettingInput.

**Defense-in-depth fix (refined for v2):**
1. **Mount-clamp (always):** `useState(typeof displayValue === 'number' && meta.step ? Number(displayValue.toFixed(Math.ceil(-Math.log10(meta.step)))) : displayValue)`.
2. **onBlur emit-clamp (only when drift detected):** `if (Math.abs(localValue - displayValue) < meta.step / 2) { emit(displayValue) } else { emit(parseFloat(localValue.toFixed(precision))) }`. Prevents silent loss of finer-than-step precision when the operator types a sub-step refinement.
3. **Test:** `displayValue=0.005000000001`, `step=0.001` → renders `0.005`, onBlur emits `0.005`.
4. **Test (NEW):** `displayValue=0.005`, user types `0.006` → onBlur emits `0.006` (no spurious clamp to `0.005`).

**Roadmap slider:** Audit could not substantiate; spec confines E3 to Settings.jsx. **Operator confirmation flagged in PR body.**

### 3.5 E5 — Calmar 1000× overshoot

**Confirmed bug:** `src/api/cloud_routes/analytics.py:568`:
```python
fund_metrics["calmar_ratio"] = round(ann_ret / (max_dd / 100000 * 100), 3) if max_dd else None
```
Algebra: `ann_ret * 1000 / max_dd`. Produces Calmar 8299 instead of ~8.3.

**Fix:**
```python
from src.evaluation.statistics import calmar_ratio as _canonical_calmar
fund_metrics["calmar_ratio"] = _canonical_calmar(ann_ret, max_dd)
```
Canonical helper at `src/evaluation/statistics.py:131` is the SoT.

**Other Calmar sites (correct per deep report):** `cto_report.py:738`, `engine.py:439`, `backtester.py:343` are all correct; `hshs_live.py:116` is not a Calmar.

**NEW v2 — Calmar canonical-only CI guardrail:** `tests/test_calmar_canonical_only.py` greps `src/` for `calmar_ratio` AND assignments containing `/ max_dd` (regex). Fails if any site outside `src/evaluation/statistics.py` defines its own Calmar formula. Forces Sprint 4+ migrations through guardrail. Three sites currently hand-rolled (cto_report.py:738, engine.py:439, backtester.py:343) are explicitly allowlisted in the test with rationale comments + tracked as follow-up `#SP4-calmar-debt` in operator TaskList.

**Regression test:** `tests/api/test_calmar_unit_audit.py` — given `pnls=[+2, -1, +3]`, `pnl_dollars=[200, -100, 300]`, asserts cto-report response Calmar matches `_canonical_calmar(...)` to 3 decimals.

### 3.6 E4 (renamed from E6 in original — Profit Factor 999 sentinel)

**Site:** `src/simulation/engine.py:458`. Emit `null` (Python `None`) instead of 999.0 sentinel when profit_factor is `inf`.

**Frontend:** `Simulation.jsx`, `StressTest.jsx` render `null` as `'N/A (no losses)'`.

**Test:** `tests/test_profit_factor_sentinel.py` — winners-only → `None`; mixed → finite; empty list → `0` (preserve legacy contract).

### 3.7 E6 — Attribution coordination bug (CORRECTED v2)

**v1 was statistically wrong.** `rr` (analytics.py:735) and `lr` (L741) are MARGINAL counts (independent any-resolution per arm). McNemar's test requires PAIRED-OVERLAP count.

**Fix (v2-corrected):** Add a third query:
```python
paired_resolved = runtime.query_one(
    "SELECT COUNT(*) as c FROM attribution_trades "
    "WHERE ranker_only_outcome != 'pending' "
    "  AND llm_portfolio_outcome IS NOT NULL"
)
paired_n = paired_resolved["c"] if paired_resolved else 0
stat_power = ("insufficient" if paired_n < 50 
              else "low" if paired_n < 200 
              else "adequate")
```

Return-shape addition: `paired_n` top-level field.

**Frontend (Attribution.jsx):** label uses `paired_n`:
```js
const powerLabel = power === 'adequate' ? 'Adequate (200+)' 
                 : power === 'low' ? 'Low (50-200)' 
                 : `Insufficient (${pairedN}/200)`
```
Subtitle: 'X paired trades resolved (both arms)'.

**Test (NEW):** disambiguating fixture — `rr=300 marginal, lr=300 marginal, paired-overlap=10` → `paired_n=10, statistical_power='insufficient'`. Confirms gate uses overlap, not marginal min. Plus `rr=300, lr=300, overlap=300` → `adequate`.

### 3.8 E7 — `/api/monitoring/history` 500 (Render proxy may surface as 503)

**Per deep report Focus 4:** `system_metrics.sync_to_postgres=False`. Cloud handler queries a Postgres table that doesn't exist → raises 500 (Render proxy may surface as 503).

**Fix (Option B from deep report):** `analytics.py:935-957`:
```python
@router.get("/api/monitoring/history", dependencies=[Depends(verify_auth)])
def monitoring_history(hours: int = 24):
    try:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(hours=hours)).isoformat()
        rows = runtime.query(
            "SELECT * FROM system_metrics WHERE timestamp > %s ORDER BY timestamp DESC LIMIT 500",
            (cutoff,),
        )
        return {"snapshots": [dict(r) for r in rows], "note": None}
    except HTTPException:
        raise
    except Exception as exc:
        runtime.logger.warning("[API] monitoring/history fallback (cloud-mode): %s", exc)
        return {"snapshots": [], "note": "system_metrics is local-only; view at http://localhost:8000/api/monitoring/history"}
```

**Frontend:** `Monitoring.jsx` reads `history?.snapshots ?? (Array.isArray(history) ? history : [])` for forward-compat. Adds `isError` check via `<LoadingState>` migration in Task 13.

### 3.9 E8 — `/api/ib/status` 404 poll feature flag

**Site:** `frontend/src/pages/Health.jsx:68`.

**Fix (CORRECTED import path for v2):**
```js
import { IS_CLOUD } from '../config'  // existing pattern, see Layout.jsx:5
// ...
const { data: ibStatus } = useQuery({
  queryKey: ['ib-status'],
  queryFn: () => api.getIBStatus(),
  refetchInterval: 30000,
  enabled: !IS_CLOUD,
})
```
UI renders 'Not available in cloud mode' when `IS_CLOUD && !ibStatus`.

**Test:** `Health.test.jsx` extend — `IS_CLOUD=true` → `enabled: false` → no fetch fires.

---

## 4. Group A — Cohort Taxonomy (`_meta` envelope)

### 4.1 A1 — Backend `_meta` emission (10 endpoints, CORRECTED v2)

| Endpoint | File | Cohort | Section structure |
|----------|------|--------|-------------------|
| `/api/kpis` | `src/api/cloud_routes/kpis.py:69` | `kpi.canonical` | flat |
| `/api/cto-report` | `src/api/cloud_routes/analytics.py` (~480-580) | `trades.all_closed` (×3 sections) | per-section |
| `/api/shadow/metrics` | `src/api/cloud_routes/trades.py` | `trades.all_closed` or `trades.live_only` (per §2.3 rule) | flat |
| `/api/attribution/stats` | `src/api/cloud_routes/analytics.py:718` | `attribution.pairs` | flat |
| `/api/strategy-detail/{strategy_type}` | `src/api/cloud_routes/analytics.py:769` | `trades.strategy` | flat |
| **`/api/model-performance`** | **`src/api/cloud_routes/training.py:549`** ← FIX | `trades.model` | flat |
| `/api/build-score` | `src/api/cloud_routes/analytics.py` | `none` | flat (still emit envelope) |
| `/api/health/hshs` | `src/api/cloud_routes/analytics.py:244` | `none` overall + `trades.all_closed` perf | per-section |
| `/api/stress-test/results` | `src/api/cloud_routes/analytics.py:885` | `stress.scenario` | flat |
| `/api/simulation/results` | `src/api/cloud_routes/analytics.py` | `stress.scenario` | flat |

**Helper module:** `src/api/cohort_meta.py` exporting `COHORT_LABELS` dict + `meta_entry(cohort_id, n, label=None) -> dict`. `meta_entry('unknown', 0)` raises `KeyError` (validates taxonomy).

### 4.2 A2 — Status `_meta`

**Site:** `src/api/cloud_routes/core.py:142-194`. Adds `_meta.open_positions` (`trades.live_only`), `_meta.closed_trades` (`trades.all_closed`), `_meta.training_examples` (`none`).

### 4.3 A3 — KPICard `meta` prop

**Site:** `frontend/src/components/dashboard/KPIStrip.jsx`. Anchors near existing `caption=` prop (search for `caption=\`N=` and `caption={\`S=`); add new `meta` prop alongside `caption`/`subLine`.

```jsx
function KPICard({ title, value, status, subLine, caption, meta, children }) {
  return (
    <div className="kpi-card">
      <div className="kpi-label">{title}</div>
      <div className="kpi-value">{value}</div>
      {meta && (
        <div className="kpi-cohort-badge" title={meta.label}>
          n={meta.n} · {meta.cohort.split('.').pop()}
        </div>
      )}
      {caption && <div className="kpi-caption">{caption}</div>}
      {subLine && <div className="kpi-sublabel">{subLine}</div>}
      {children}
    </div>
  )
}
```

**Visual-verify rule applies.**

### 4.4 A4 — Page retrofit (Dashboard / TradeHistory / Strategy)

Wires `meta={kpis._meta?.<field>}` through 3 pages.

---

## 5. Group B — Header Source-of-Truth

### 5.1 B1 — Migrate Layout.jsx header to `/api/kpis` (3-state fallback, CORRECTED v2)

**Site:** `frontend/src/components/Layout.jsx:103`.

**Three explicit fallback states:**
```jsx
function StatusBar({ status, kpis, kpisQuery }) {
  let tlState
  let tlClassName
  let tlTooltip = ''
  
  if (kpisQuery.isError) {
    tlState = 'ERR'
    tlClassName = 'tl-err'
    tlTooltip = `Last attempt: ${kpisQuery.dataUpdatedAt ? new Date(kpisQuery.dataUpdatedAt).toISOString() : 'never'}`
  } else if (kpis === undefined || kpisQuery.isPending) {
    tlState = '…'  // loading ellipsis
    tlClassName = 'tl-pending'
  } else if (kpis?.stage_traffic_light?.decision_matrix_state == null) {
    tlState = 'COMPUTING'
    tlClassName = 'tl-computing'
    tlTooltip = kpis?.stage_traffic_light?.last_computed_at 
      ? `Last computed: ${kpis.stage_traffic_light.last_computed_at}` 
      : 'Compute pending'
  } else {
    tlState = kpis.stage_traffic_light.decision_matrix_state
    tlClassName = `tl-${tlState.toLowerCase()}`
    tlTooltip = kpis?.stage_traffic_light?.last_computed_at 
      ? `Last computed: ${kpis.stage_traffic_light.last_computed_at}` 
      : ''
  }
  return <span className={tlClassName} title={tlTooltip}>TL: {tlState}</span>
}
```

**Test:** `Layout.test.jsx` covers 3 states + 1 success state = 4 cases.

### 5.2 B2 — Reconcile `25 POSITIONS` count (unchanged)

Keep `open_positions` in header for live-position count; add tooltip clarifying the cohort.

### 5.3 B3 — CI reconciliation test (CORRECTED v2)

**File:** `tests/test_dashboard_reconciliation.py`. **Explicit scope: SQLite only.** Postgres validation deferred to Sprint 4 runbook task (added to operator TaskList #SP4-render-pg-reconcile).

**Cohort-aware reconciliation:**
```python
def test_trade_counts_reconcile_across_endpoints(api_client):
    cto_resp = api_client.get("/api/cto-report").json()
    shadow_resp = api_client.get("/api/shadow/metrics").json()
    
    cto_meta = cto_resp["_meta"]["trade_summary"]["win_rate"]
    shadow_meta = shadow_resp["_meta"]["win_rate"]
    
    # Cohort match BEFORE n equality
    if cto_meta["cohort"] != shadow_meta["cohort"]:
        # By design: shadow_metrics defaults to trades.all_closed; if a desk filter
        # produces trades.live_only, ns will differ. Skip cohort-mismatch case.
        pytest.skip(f"cohort drift by design: cto={cto_meta['cohort']} shadow={shadow_meta['cohort']}")
    assert cto_meta["n"] == shadow_meta["n"], \
        f"closed-trade count drift: cto={cto_meta['n']} shadow={shadow_meta['n']}"
```

Two-step assertion: cohort match first, then n equality. Plus a separate `test_open_position_count_reconciles` for `/api/status.open_positions` vs `/api/live/summary.open_positions`.

---

## 6. Group C — Loading State

### 6.1 C1 — Shared `<LoadingState>` (with `retryDisabledFor` cooldown, NEW v2)

**File:** `frontend/src/components/LoadingState.jsx` (NEW).

**API:**
```jsx
<LoadingState
  isLoading={isLoading}
  isError={isError}
  isEmpty={data?.length === 0}
  error={error}
  retry={() => refetch()}
  retryDisabledFor={2000}  // ms cooldown between retries
  emptyMessage="No broker exceptions in last 24h. ✓"
  loadingMessage="Loading broker exceptions..."
  compact={false}
>
  {/* render data here */}
</LoadingState>
```

Retry button enters disabled state for `retryDisabledFor` ms after click. Prevents user-driven retry storms.

**Test:** 5 cases (loading, error+retry, empty, data, compact). Covers retry-cooldown via `vi.useFakeTimers()`.

### 6.2 C2 — Migrate 4 widgets (unchanged from v1)

All 4 widgets pass `isError` from useQuery into LoadingState (closes Monitoring presentation bug from E7).

---

## 7. Group F — Operator-Action Ambiguity

### 7.1 F1 — Shared `<ActionButton cliOnly>` (with secure-context fallback, NEW v2)

**File:** `frontend/src/components/ActionButton.jsx` (NEW).

**Copy handler (revised for non-secure-context fallback):**
```jsx
async function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return { success: true, mode: 'clipboard' }
    } catch (err) {
      // fall through to non-secure-context fallback
    }
  }
  return { success: false, mode: 'manual', hint: 'Press Ctrl+C to copy' }
}
```

Render:
```jsx
{cliOnly && (
  <Tooltip content={
    <div>
      <div>{whyDisabled}</div>
      <hr/>
      <pre 
        onClick={(e) => { window.getSelection().selectAllChildren(e.currentTarget) }}
        className="select-all cursor-pointer"
      >{cliCommand}</pre>
      <button onClick={async () => {
        const r = await copyToClipboard(cliCommand)
        setCopyHint(r.success ? 'Copied!' : r.hint)
      }}>Copy</button>
      {copyHint && <span>{copyHint}</span>}
    </div>
  }>
    <button disabled className="cli-only-btn">{label} <span>[CLI only]</span></button>
  </Tooltip>
)}
```

**Test (added v2 case):** mock `window.isSecureContext = false` → click Copy → renders 'Press Ctrl+C to copy' hint, no exception thrown.

### 7.2 F2 — Migrate 5 pages (unchanged decision matrix)

| Page | Button | Decision |
|------|--------|----------|
| Live Ledger | Reconcile | cliOnly |
| Diagnostics | Run Regime/Forensic/Training Audit (×3) | cloud-actionable |
| Simulation | Run Simulation | cloud-actionable + dedupe |
| Council | Run Council Now / Ask Council (×2) | cloud-actionable |
| Settings | IB shadow_mode + IB paper_routing toggles | cliOnly (Task 15 owns; Task 14 explicitly defers) |
| Settings | Other toggles + reset | cloud-actionable (UNCHANGED — out of cliOnly scope) |

Task 14 description must explicitly state: 'Do NOT touch Settings IB toggles — those are owned by Task 15. Migrate ONLY LiveLedger, Diagnostics 3 buttons, Simulation Run, Council 2 buttons.'

---

## 8. Error Handling (CORRECTED v2)

| Scenario | Behavior | Site |
|----------|----------|------|
| Backend `runtime.query` raises (UndefinedTable) | E7: 200 + empty + note | `analytics.py:935-957` |
| Backend `meta_entry` lookup fails | Wrap in try/except; emit `cohort='unknown'` if helper raises | `cohort_meta.py` |
| Frontend useQuery isError | LoadingState renders error card + retry (disabled for `retryDisabledFor` ms after click) | `LoadingState.jsx` |
| Cloud build receives `getIBStatus` request | Skipped via `enabled: !IS_CLOUD` | `Health.jsx:68` |
| Float-precision drift display | Mount-clamp + onBlur emit-clamp (only when drift > step/2) | `Settings.jsx:43` |
| ActionButton onClick throws | Caught by parent mutation error boundary; resets `pending=false` | `ActionButton.jsx` |
| `navigator.clipboard.writeText` rejects (non-secure-context) | Falls back to selectable `<pre>` + 'Press Ctrl+C' hint | `ActionButton.jsx` |
| `/api/kpis` errors | Header renders 'TL: ERR' with `last_attempt` tooltip | `Layout.jsx` |
| `/api/kpis` returns `stage_traffic_light=null` (compute pending) | Header renders 'TL: COMPUTING' | `Layout.jsx` |
| `/api/kpis` is loading | Header renders 'TL: …' (ellipsis) | `Layout.jsx` |

**Backwards-compat:** All `_meta` additions are sibling fields. No existing key changes type or location.

---

## 9. Testing Strategy

### 9.1 Test cases added (precise count, CORRECTED v2)

| Test file | Status | Test cases | Owner task |
|-----------|--------|-----------|------------|
| `tests/api/test_calmar_unit_audit.py` | NEW | 2 (regression-lock, algebraic-equiv) | E5 (Task 1) |
| `tests/test_calmar_canonical_only.py` | NEW | 1 (no other Calmar formulas in src/) | D4 follow-up (Task 1) |
| `tests/api/test_attribution_stats.py` | NEW | 4 (overlap=10 vs marginals=300, paired=300 adequate, _meta envelope, by_action passthrough) | E6 (Task 2) |
| `tests/api/test_monitoring_history_fallback.py` | NEW | 3 (happy path, UndefinedTable fallback, _meta envelope) | E7 (Task 3) |
| `tests/test_profit_factor_sentinel.py` | NEW (root tests/) | 3 (winners-only=null, mixed=finite, empty=0) | E4 (Task 4) |
| `tests/test_stop_loss_sign.py` | NEW (root tests/) | 2 (stop_loss neg pnl, sibling target_hit pos pnl) | E2 (Task 4) |
| `frontend/src/components/dashboard/KPIStrip.test.jsx` | EXTEND | 2 (meta renders, undefined no badge) | A3 (Task 5) |
| `frontend/src/components/LoadingState.test.jsx` | NEW | 5 (loading, error+retry, empty, data, retryDisabledFor cooldown) | C1 (Task 6) |
| `frontend/src/components/ActionButton.test.jsx` | NEW | 6 (cliOnly disabled, cliOnly tooltip, copy-secure success, copy-non-secure fallback, non-cliOnly active, pending spinner) | F1 (Task 7) |
| `tests/api/test_kpis.py` | EXTEND | 1 (_meta envelope) | A1 (Task 8) |
| `tests/test_cto_report.py` (existing root) | EXTEND | 1 (per-section _meta) | A1 (Task 8) |
| `tests/api/test_status.py` | NEW | 2 (status structure smoke + _meta envelope) | A1 (Task 8) |
| `frontend/src/components/Layout.test.jsx` | NEW | 3 (kpis pending → '…', kpis loaded null → 'COMPUTING', kpis errored → 'ERR') | B1 (Task 10) |
| `frontend/src/pages/Settings.test.jsx` | NEW | 2 (precision clamp mount, precision clamp emit) | E3 (Task 11) |
| `frontend/src/pages/Health.test.jsx` | NEW | 2 (IS_CLOUD enabled=false, !IS_CLOUD enabled=true) | E8 (Task 11) |
| `tests/test_dashboard_reconciliation.py` | NEW (SQLite-only) | 4 (all-emit-meta, closed-cohort-match-then-n, open-position-reconcile, invalid-cohort-rejected) | B3 (Task 16) |
| `tests/test_eslint_queryfn_guardrail.py` | NEW | 1 (npm lint:queryfn passes on current frontend) | E1 (Task 17c) |

**Total new test cases: 2 + 1 + 4 + 3 + 3 + 2 + 2 + 5 + 6 + 1 + 1 + 2 + 3 + 2 + 2 + 4 + 1 = 44**

**Sprint closeout assertion (Task 18):** `assert pass_count == 4602 + 44`. Strict equality, not `>=`. If actual count differs, root-cause before merging.

### 9.2 External-API mock policy

All new tests honor 'no network calls.' FRED, Alpaca, Finnhub, yfinance, Ollama all mocked.

### 9.3 Pre-existing test failures

Reference `docs/audits/known-pre-existing-failures.md`. Sprint 3 must not introduce new failures.

### 9.4 Visual-verify rule

**Mandatory** for any frontend Dashboard / KPIStrip / Layout edit (CLAUDE.md mandate). Tasks 5, 10, 12, 13, 14, 15 must browser-verify before push.

### 9.5 test_repo_structure.py disclosure

Every PR runs `python -m pytest tests/test_repo_structure.py -v` and includes output in strict-rigor receipt. New shared components (`LoadingState.jsx`, `ActionButton.jsx`) must stay under 200 lines.

### 9.6 Sibling-search rule (per CLAUDE.md / 2026-04-26 incident)

Applies to: E2 stop_loss (executor.py + reconcile.py), E5 Calmar (handled at sprint level via canonical helper), E6 attribution (analytics.py gate patterns), E1 (handled at catalog level — 28 sites enumerated), E7 monitoring (analytics.py runtime.query fallback patterns). Developer documents grep results in PR body.

---

## 10. Decision Log (REVISED v2)

| # | Decision | Rationale | Alternatives | Tradeoffs |
|---|----------|-----------|--------------|-----------|
| D1 | Additive `_meta` sibling envelope (per-section for cto-report) | Operator locked; preserves BC; cto-report mixes 3 cohorts | Replace numerics with `{value, _meta}` (rejected: breaks consumers); flat per-endpoint (rejected: misrepresents cto-report) | Slightly nested cto-report shape |
| D2 | E5 Calmar refactor to canonical `src/evaluation/statistics.py:131` | Prevents recurrence; consolidates SoT | Single-line patch (rejected: dup math); refactor all 5 sites (rejected: 4 are correct, scope creep) | Larger diff in Task 1; pays back |
| D3 | E5 — add CI guardrail `tests/test_calmar_canonical_only.py` (NEW v2) | Prevents future Calmar drift; addresses reviewer minor finding on D4 | Trust developers; flagged as a debt comment | Extra test; allowlist file in test holds 3 currently-correct hand-rolled sites |
| D4 | E6 — gate on **paired-overlap** count (NOT min(rr, lr)) (CORRECTED v2) | McNemar's requires paired observations; rr/lr are MARGINAL counts (verified analytics.py:735/741) | min(rr,lr) (rejected v2: statistically wrong); rr only (rejected v1) | Adds third query in handler; trivially fast |
| D5 | E7 — return 200 + empty + note (Option B) | Mirrors /snapshot pattern; no architectural conflict | Add system_metrics to render_sync (rejected: conflicts with unified-DB spec); table-existence check (rejected: more code) | Shape change BC due to existing coalesce |
| D6 | Header reads `/api/kpis` for traffic_light (Option b) | Already computes canonical TL; queryKey dedupes | Add to /api/status (rejected: doubles cost); compute on FE (rejected: complex logic) | New /api/kpis dependency in header |
| D7 | Header has 3 explicit fallback states (NEW v2) | Reviewer found v1 only handled `kpis === undefined`; missed null state + error state | Single 'NOT SET' fallback (rejected: ambiguous to operator) | More complex StatusBar; tested across 4 cases |
| D8 | E1 — wrap all 28 sites; split into 17a/17b/17c (NEW v2 split) | Files-in-scope ≤4; pre-commit scope-check + pre-push stale-base hooks; file collisions with prior tasks | Single Task 17 with 16 files (rejected: violates `max 4`); wrap only 3 buggy sites (rejected: leaves 25 latent) | Three sequenced tasks; 17b depends on [2,3,11,13,14] |
| D9 | E1 — ESLint custom rule (NOT Python AST) (CORRECTED v2) | Python has no JSX parser; ESLint already in frontend | Babel/regex/subprocess (rejected: fragile or slow) | New file in `frontend/eslint-rules/`; npm script |
| D10 | E4 — emit `null` for inf profit_factor | Sentinel 999 inflates dashboards | Keep 999 (rejected: ambiguous); 'Infinity' (rejected: invalid JSON) | Frontend null-handling change |
| D11 | E8 — `IS_CLOUD` from `'../config'` (CORRECTED v2) | Existing pattern; 12+ call sites | `@/utils/env` (rejected v1: file doesn't exist); backend stub (rejected: pointless) | None |
| D12 | E3 — defense-in-depth clamp + drift-aware emit (REFINED v2) | Catches mount drift + roundtrip drift; preserves user's finer typed values | Mount-only (rejected: roundtrip leak); emit-only (rejected: re-render jitter); aggressive emit-clamp always (rejected: silently drops sub-step input) | Slightly more code |
| D13 | F2 decision matrix (per-button cliOnly assignment) | Brief was ambiguous; deep report Focus 8 confirms cloud-actionable for most | All cliOnly (rejected: regresses functionality); all cloud-actionable (rejected: misrepresents Live Ledger + IB) | Spec must document; reviewer validates |
| D14 | Add `attribution.pairs` as 8th cohort | attribution_trades is separate table | Subsume under trades.* (rejected: wrong table); use 'none' (rejected: it IS a cohort) | 8 cohorts vs brief's 7 |
| D15 | F1 — clipboard secure-context fallback (NEW v2) | LAN/Tailscale-by-IP operators on HTTP fail navigator.clipboard | Mock and ignore (rejected: real-user fails); throw (rejected: poor UX) | Slightly more ActionButton code; 1 extra test case |
| D16 | LoadingState — `retryDisabledFor` cooldown (NEW v2) | Prevents retry-storms on transient errors | No cooldown (rejected: user can hammer button) | Extra prop; 1 extra test case |
| D17 | shadow_metrics cohort emit rule (NEW v2) | Reviewer found v1 ambiguous: trades.all_closed OR trades.live_only | Always emit one cohort regardless of filter (rejected: lies about scope) | 1 extra rule in cohort_meta.py docstring; B3 test handles cohort drift via skip |
| D18 | B3 — SQLite-only scope; Postgres deferred (NEW v2) | Reviewer flagged false-positive risk on Render Postgres replication gaps | Run B3 against Render Postgres in CI (rejected: pytest+Render env); parameterize (rejected: complexity) | Sprint 4 follow-up `#SP4-render-pg-reconcile` added to operator TaskList |
| D19 | Test floor exit: strict `4646` equality (CORRECTED v2) | Reviewer found v1 used 'lines' not 'cases'; numeric drift | `>= 4602` (rejected: regression invisible) | Closeout fails if any test added/removed unexpectedly; root-cause before merge |
| D20 | Task 4 — pre-investigate stop_loss site (NEW v2) | Reviewer asked for grep before dispatch; done — `executor.py:1872` + `reconcile.py:131` confirmed | Investigate at dispatch time (rejected: PM-side rigor mandate) | Three files in scope vs two |

---

## 11. Sprint workflow (per CLAUDE.md)

### 11.1 Branch + worktree discipline

All parallel coding-team agent dispatches MUST use `isolation: 'worktree'`. PM writes `.claude/agent-scope.json` before each dispatch. Pre-commit scope-check + pre-push stale-base hooks must remain active.

### 11.2 PR conventions

Every PR: CHANGELOG.md Unreleased entry; test_repo_structure.py output; visual-verify screenshots for frontend tasks; strict-rigor receipt with sibling-search disclosure.

### 11.3 Reviewer dispatch (per CLAUDE.md table)

| Tasks | QA | Security | Performance |
|-------|-----|----------|-------------|
| 1, 2, 3, 4 (backend bug fixes) | Yes | No | Yes |
| 8, 9, 10 (API _meta + header migration) | Yes | No | Yes |
| 5, 6, 7 (FE shared components) | Yes | No | No |
| 11 (frontend bug fixes E3+E8) | Yes | No | No |
| 12, 13, 14, 15 (page retrofits) | Yes | No | No |
| 16, 17a, 17b, 17c (CI tests + E1 sweep + ESLint guardrail) | Yes | No | No |
| 18 (closeout) | Yes | No | No |

No task touches auth or user input handling beyond the existing verify_auth surface; Security review not triggered.

---

## 12. Acceptance criteria (REVISED v2)

- [ ] All 8 Group E bugs fixed; each has at least one regression test.
- [ ] All 10 endpoints in §4.1 emit `_meta` envelope with valid cohort from §2.3 taxonomy. (`/api/model-performance` correctly located in `training.py:549`.)
- [ ] KPICard renders cohort badge when `meta` prop provided. Browser-verified screenshot in PR.
- [ ] Header reads `/api/kpis.stage_traffic_light.decision_matrix_state` with 3 explicit fallbacks (pending/computing/error); shows GREEN/AMBER/RED/HALT when KPI data is fully available.
- [ ] CI reconciliation test passes (SQLite scope) for all 5 trade-count endpoints with cohort-match-first assertion.
- [ ] 4 named widgets render via `<LoadingState>` with `retryDisabledFor` cooldown.
- [ ] 5 named pages migrated to `<ActionButton>` per §7.2 decision matrix; secure-context fallback verified.
- [ ] All 28 useQuery sites wrapped per §3.1 (Tasks 17a + 17b); ESLint custom rule blocks future bare-queryFn drift (Task 17c).
- [ ] Test floor strict equality: `pass_count == 4646`.
- [ ] Zero new test_repo_structure.py violations.
- [ ] CHANGELOG.md updated.
- [ ] Operator confirmation obtained on E3 'Roadmap slider' audit reference.
- [ ] Sprint 4 follow-ups added to operator TaskList: `#SP4-render-pg-reconcile`, `#SP4-calmar-debt`, E2 fallback if not located.


---

## Design Decisions (canonical table)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Use additive `_meta` sibling envelope (per-section for cto-report, per-endpoint elsewhere) | Operator locked. Preserves BC; cto-report mixes 3 cohorts. shadow_metrics emits per-§2.3 rule (defaults to trades.all_closed; trades.live_only when desk filter applied). |
| D2 | E5 Calmar refactor to canonical helper + NEW v2 CI guardrail (test_calmar_canonical_only.py) | Reviewer minor finding D4: prevent future Calmar drift via guardrail not just refactor. Allowlist 3 currently-correct hand-rolled sites; track as `#SP4-calmar-debt`. |
| D3 | E6 — gate on PAIRED-OVERLAP count (NOT min(rr, lr)) (CORRECTED v2) | v1 was statistically wrong: rr/lr at analytics.py:735/741 are MARGINAL counts (independent any-resolution). McNemar's requires paired observations (count of trades where BOTH arms resolved). New SQL: `WHERE ranker_only_outcome != 'pending' AND llm_portfolio_outcome IS NOT NULL`. |
| D4 | E7 Monitoring 200 + empty + note (Option B) (UNCHANGED) and reword '503' → '500 (Render proxy may surface as 503)' | Mirrors /snapshot pattern; no architectural conflict. Reviewer corrected wording: handler raises 500, not 503; Render proxy converts. |
| D5 | Header reads /api/kpis with 3 explicit fallback states (NEW v2) | Reviewer found v1 only handled `kpis === undefined`. Three states needed: pending → '…'; loaded-but-null state → 'COMPUTING'; errored → 'ERR'. Tooltip surfaces last_computed_at when present. |
| D6 | E1 — split Task 17 into Tasks 17/18/19/20/21/22 (CORRECTED v2 for scope-fence + collision avoidance) | Reviewer found Task 17 violated `max 4 files_in_scope` (16+ files needed) AND collided with Tasks 2/11/13/14 (file ownership not in depends_on). Split: Tasks 17/18/19 are parallel-safe (10 non-conflict files); Tasks 20/21 sequenced after owning tasks (6 conflict files); Task 2... |
| D7 | E1 — ESLint custom rule (NOT Python AST) (CORRECTED v2) | Reviewer found Python has no native JSX parser; spec was unspecified. ESLint already in frontend; custom rule at `frontend/eslint-rules/no-bare-queryfn-with-args.js`, registered in `frontend/eslint.config.js`, exposed via `npm run lint:queryfn` script. Pytest fixture at `tests... |
| D8 | E4 emit null for inf profit_factor (UNCHANGED) | 999.0 sentinel inflates dashboards; null is unambiguous and JSON-native. |
| D9 | E8 IS_CLOUD imported from '../config' (CORRECTED v2) | Reviewer found `@/utils/env` doesn't exist (no Vite alias for `@`; no utils/env.js file). Actual: 12+ existing call sites use `from '../config'` or `'./config'`. Layout.jsx:5 is the canonical reference. |
| D10 | E3 — defense-in-depth clamp + drift-aware emit (REFINED v2) | Reviewer found v1 emit-clamp silently dropped finer-than-step typed values. v2 onBlur emit only clamps when `Math.abs(localValue - displayValue) < step/2` — preserves user's intentional sub-step typing while still suppressing drift. |
| D11 | F1 ActionButton — secure-context fallback for clipboard (NEW v2) | Reviewer found navigator.clipboard.writeText() requires HTTPS or localhost. Operators on HTTP origins (LAN access, Tailscale by IP) hit TypeError. v2 checks `navigator.clipboard && window.isSecureContext` first; falls back to selectable `<pre>` + 'Press Ctrl+C' hint. Promise r... |
| D12 | C1 LoadingState — retryDisabledFor cooldown prop (NEW v2) | Reviewer minor finding: prevent retry-storms on transient errors. ms cooldown after click; button re-enabled after timer. |
| D13 | F2 decision matrix — Task 14 explicitly defers Settings IB to Task 15 (CLARIFIED v2) | Reviewer found Task 14 description ambiguous on Settings IB ownership. v2: Task 14 description states 'Do NOT touch Settings.jsx — Task 15 owns IB toggles'. Task 15 owns Settings.jsx + IB-toggle-only edit. |
| D14 | Add `attribution.pairs` as 8th cohort_id (UNCHANGED) + per-cohort callsite justification (NEW v2) | attribution_trades is separate table. Reviewer minor finding: drop cohorts with zero callsites. Each cohort_id in §2.3 now has explicit callsite list; none have zero callsites. |
| D15 | shadow_metrics cohort emit rule (NEW v2) | Reviewer found v1 ambiguous about when shadow_metrics emits trades.all_closed vs trades.live_only. v2 rule: emits trades.live_only IFF the SQL filtered by source='live' (via desk parameter); otherwise emits trades.all_closed. Documented in cohort_meta.py module docstring. |
| D16 | B3 — SQLite-only scope; Postgres validation deferred to Sprint 4 runbook (NEW v2) | Reviewer found local pytest+SQLite passes don't reflect Render Postgres replication gaps (system_metrics.sync_to_postgres=False, possibly attribution_trades). v2 explicitly scopes B3 as SQLite-only; adds Sprint 4 follow-up `#SP4-render-pg-reconcile` for manual Postgres validat... |
| D17 | Test count strict equality 4646 (CORRECTED v2) | Reviewer found v1 mixed 'lines added' (~35) with case counts; numeric drift. v2 explicit: 44 test cases, exit floor 4646, Task 23 closeout asserts strict equality. If pytest count differs, root-cause before merge. |
| D18 | Task 4 (E2 stop_loss) — pre-investigated before dispatch (NEW v2) | Reviewer asked for grep before dispatch. v2 pre-investigation: stop_loss exit construction at `src/shadow_trading/executor.py:1872`; matcher at `reconcile.py:131`. Files added to Task 4 scope. If neither flips sign, Task 4 downgrades to 'investigation only' with Sprint 4 follo... |
| D19 | /api/model-performance located in training.py:549, NOT analytics.py (CORRECTED v2) | Reviewer found path error in v1. Confirmed via grep: `analytics.py` has no model-performance route; `training.py:549` defines it. |
| D20 | Test path corrections (CORRECTED v2) | Reviewer found `tests/api/test_cto_report.py` doesn't exist (actual: `tests/test_cto_report.py`); `tests/api/test_status.py` doesn't exist (NEW). v2 corrected throughout spec + plan. |
| D21 | v3 mechanical corrections — serialize T1/T2/T3 analytics.py edits (T2 dep=[1], T3 dep=[2]); move T10 to batch after T8; fix Task 17 RevenueProjection.jsx path; rename test_monitoring_history.py → test_monitoring_history_fallback.py; mark Layout/Settings/Health test files NEW in spec | Feasibility v2 returned 2 majors + 3 minors, all mechanical (paths, sequencing, file-collision). No design rationale changes. Serializing analytics.py edits applies the same discipline used in the E1 split (D8): pre-commit scope-check passes for parallel agents declaring the s... |

## Known Considerations

- **Devil's Advocate v2 was not re-run after v2/v3 architect revisions** — the v2 re-run hit an AUP false-positive and was not retried. The v1 Devil's Advocate critical+major findings were addressed in v2 (Task 17 split into 17/18/19/20/21/22 with explicit depends_on edges; McNemar's PAIRED-OVERLAP gate; header 3-state fallback; ESLint custom rule replacing Python AST guardrail; navigator.clipboard secure-context fallback; test count strict equality at 4646; B3 SQLite-only scope with Sprint 4 follow-up). v3 only added mechanical corrections (T1/T2/T3 serialization on analytics.py, T10 batch move, file path fixes) — no design-level reasoning that Devil's Advocate would have flagged.

- **Three Calmar compute paths remain hand-rolled** (cto_report.py, simulation/engine.py, backtester.py). v3's `test_calmar_canonical_only` CI test (Task 1) will fail-grep on any non-canonical Calmar formula, forcing Sprint 4+ to migrate. Tracked as follow-up `#SP4-calmar-debt`.

- **B3 reconciliation test is SQLite-only**. Render Postgres has documented replication gaps (`system_metrics.sync_to_postgres=False`; `attribution_trades` replication state un-audited). The CI test gives a false-positive coherence signal for the production deployment. Tracked as `#SP4-render-pg-reconcile`.

- **Settings IB toggle migration** is split between Task 14 (4 pages, no Settings.jsx) and Task 15 (Settings.jsx only). The split is intentional — Task 11 also touches Settings.jsx for the float-precision clamp, so Task 15 sequences after both Task 11 and Task 7 to avoid file collisions. Reviewers should not flag Task 14's missing Settings.jsx as a scope gap.
