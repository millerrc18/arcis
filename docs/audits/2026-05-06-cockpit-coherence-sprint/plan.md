# Sprint 3 — Cockpit Coherence — Implementation Plan

**Generated**: 2026-05-06
**Spec**: `spec.md` (canonical)
**Source artifact**: `docs/audits/2026-05-06-dashboard-coherence/recommendations.md`
**Consumable by**: `arcis:code` PM orchestrator

## Execution order

Tasks within a batch are parallel-safe (zero file overlap, zero intra-batch dependency). Batches run sequentially.

```
Batch 0: [1, 4, 5, 6, 7, 11]
Batch 1: [2]
Batch 2: [3, 8]
Batch 3: [9, 10]
Batch 4: [12, 13, 14, 15, 16, 17]
Batch 5: [18, 19, 20, 21]
Batch 6: [22]
Batch 7: [23]
```

## Plan notes

REVISION v2 — split E1 sweep across 5 sub-tasks (17, 18, 19, 20, 21) + ESLint rule (22) to honor `max 4 files_in_scope` + pre-commit scope-check + pre-push stale-base hooks. Tasks 17-19 are parallel-safe (files NOT owned by other tasks). Tasks 20-21 sequenced after their owning tasks (2/3/4/11/13/14/15). Task 22 sequenced after all wraps complete so ESLint rule passes. Worktree isolation MANDATORY for all parallel batches per CLAUDE.md. Reviewer dispatch: Tasks 1-4, 8-10 → QA + Performance. Tasks 5-7, 11-15 → QA only. Tasks 16-23 → QA only. Visual-verify rule: Tasks 5, 10, 12, 13, 14, 15 (Dashboard/KPIStrip/Layout/page-level edits). Sibling-search rule: Tasks 1, 2, 3, 4, 11, 17-21 (every bug-fix or wrap site). NOTE on Task 8 split: tests/test_cto_report.py (existing root path) and tests/api/test_kpis.py (existing) are listed read-only in Task 8 to avoid file-collision; if assertions need to land directly, fold into Task 9 — Task 9 owns test_cto_report.py edits explicitly. Task 9 model-performance fix is at training.py:549 (CORRECTED). Test floor strict equality 4646 in Task 23 — operator must approve any deviation. V3 mechanical corrections (no new design decisions): (1) T10 moved out of T8's batch — now Batch 3 alongside T9 (both depend on T8); (2) T2 depends_on=[1] and T3 depends_on=[2] to serialize the three analytics.py edits and avoid pre-push stale-base hazard on parallel writes — mirrors E1-split discipline (D8). T4 stays parallel since it touches engine.py + executor.py only, no analytics.py. Per-bug task granularity preserved. Execution_order rebuilt: [[1,4,5,6,7,11],[2],[3,8],[9,10],[12,13,14,15,16,17],[18,19,20,21],[22],[23]] — 8 batches (was 9). (3) Task 17 path corrected to components/RevenueProjection.jsx. (4) Task 3 test file renamed to tests/api/test_monitoring_history_fallback.py to avoid collision with existing tests/api/test_monitoring_history_shape.py. (5) Spec §2.1 + §9.1: Layout.test.jsx + Settings.test.jsx + Health.test.jsx all marked NEW (filesystem-verified absent).

## Tasks

### Task 1 — E5 — Calmar 1000x overshoot fix + canonical helper refactor + Calmar SoT guardrail

- **Batch**: ?
- **Depends on**: none (root)
- **Complexity**: ?
- **Files in scope**:
  - `src/api/cloud_routes/analytics.py`
  - `tests/api/test_calmar_unit_audit.py`
  - `tests/test_calmar_canonical_only.py`
- **Files read-only**:
  - `src/evaluation/statistics.py`
  - `src/evaluation/cto_report.py`
  - `src/simulation/engine.py`
  - `src/evaluation/backtester.py`

**Description:**

Replace `src/api/cloud_routes/analytics.py:568` buggy formula `ann_ret / (max_dd / 100000 * 100)` with call to canonical `src/evaluation/statistics.py:131` `calmar_ratio()` helper. Add `tests/api/test_calmar_unit_audit.py` regression-lock asserting fund_metrics['calmar_ratio'] equals canonical helper output to 3 decimals. NEW v2: also create `tests/test_calmar_canonical_only.py` CI guardrail that greps `src/` for ad-hoc Calmar formulas (regex: `calmar.*max_dd|max_dd.*calmar` and `/ max_dd`); allowlist 3 currently-correct hand-rolled sites with comments + tracked as `#SP4-calmar-debt`. Sibling-search inside analytics.py for `/ 100000 * 100` style algebraic foot-guns.

**Scope fence:**

Do NOT modify cto_report.py:738, engine.py:439, backtester.py:343, hshs_live.py:116 (verified correct per deep report; allowlisted with comments in test_calmar_canonical_only.py). Do NOT add `_meta` envelope here (Task 8). Do NOT touch attribution endpoint (Task 2). CHANGELOG.md updated by Task 18 only.

**Test strategy:**

1) Regression-lock: pnls=[+2,-1,+3], pnl_dollars=[200,-100,300] → fund_metrics['calmar_ratio'] within 0.001 of canonical. 2) Algebraic-equiv: grep `100000 * 100` in source — must be absent. 3) Calmar SoT guardrail: any new Calmar formula outside canonical helper or allowlist fails the test.

---

### Task 2 — E6 — Attribution paired-overlap gate (CORRECTED) + frontend label

- **Batch**: ?
- **Depends on**: [1]
- **Complexity**: ?
- **Files in scope**:
  - `src/api/cloud_routes/analytics.py`
  - `frontend/src/pages/Attribution.jsx`
  - `tests/api/test_attribution_stats.py`

**Description:**

v2-corrected: backend gates on paired-overlap (NOT min(rr,lr)). Add new query at `src/api/cloud_routes/analytics.py` after L745: `paired_resolved = runtime.query_one("SELECT COUNT(*) as c FROM attribution_trades WHERE ranker_only_outcome != 'pending' AND llm_portfolio_outcome IS NOT NULL")`. Update L762 gate to use `paired_n = paired_resolved['c']` instead of `rr`. Add top-level `paired_n` field to response. Update `frontend/src/pages/Attribution.jsx` label from `(${total}/200)` to `(${paired_n}/200)`. Subtitle: 'X paired trades resolved (both arms)'. Sibling-search analytics.py for similar gate patterns; document in PR body.

**Scope fence:**

Do NOT change response shape for total_pairs, by_action, by_pair_type, ranker_only, llm_portfolio (BC). Do NOT add `_meta` envelope yet — Task 9 owns. Do NOT touch other analytics.py endpoints. Do NOT change Attribution.jsx beyond label + subtitle (E1 wrap of L10 is in Task 17b). v3: depends_on=[1] to serialize analytics.py edits T1→T2→T3.

**Test strategy:**

1) Disambiguating fixture: rr=300 marginal, lr=300 marginal, paired-overlap=10 → paired_n=10, statistical_power='insufficient'. 2) Both arms 300 paired → paired_n=300, 'adequate'. 3) _meta envelope (cohort='attribution.pairs') passthrough check. 4) Frontend snapshot: paired_n=10 → label '(10/200)'.

---

### Task 3 — E7 — Monitoring 500/503 fix (200 + empty + note pattern)

- **Batch**: ?
- **Depends on**: [2]
- **Complexity**: ?
- **Files in scope**:
  - `src/api/cloud_routes/analytics.py`
  - `frontend/src/pages/Monitoring.jsx`
  - `tests/api/test_monitoring_history_fallback.py`
- **Files read-only**:
  - `src/schema/registry.py`
  - `docs/audits/2026-05-05-unified-db-architecture/spec.md`

**Description:**

Per deep report Focus 4 Option B: change `analytics.py:935-957` to return `{snapshots: [], note: 'system_metrics is local-only; view at http://localhost:8000/api/monitoring/history'}` on UndefinedTable / runtime errors instead of raising 500 (Render proxy may surface as 503). Mirrors existing `/api/monitoring/snapshot` (analytics.py:959-969). Update `frontend/src/pages/Monitoring.jsx:46` to read `history?.snapshots ?? (Array.isArray(history) ? history : [])`. NOTE: do NOT install LoadingState here — Task 13 owns that migration; Task 3 only changes the data-shape consumption path.

**Scope fence:**

Do NOT add system_metrics to render_sync.py. Do NOT touch /api/monitoring/snapshot. Do NOT install LoadingState (Task 13). Do NOT add isError check to Monitoring.jsx — Task 13 owns that. CHANGELOG.md by Task 23. v3: depends_on=[2] to serialize analytics.py edits T1→T2→T3 (avoids pre-push stale-base hazard).

**Test strategy:**

1) Patch runtime.query to raise psycopg2.errors.UndefinedTable → response is 200 with snapshots=[] and note populated. 2) Happy path with synthetic system_metrics rows → snapshots is non-empty. 3) Frontend reads new shape correctly: history.snapshots=[] renders empty state.

---

### Task 4 — E2 + E4 — stop_loss sign + profit_factor 999 sentinel (with pre-investigation)

- **Batch**: ?
- **Depends on**: none (root)
- **Complexity**: ?
- **Files in scope**:
  - `src/simulation/engine.py`
  - `src/shadow_trading/executor.py`
  - `tests/test_profit_factor_sentinel.py`
  - `tests/test_stop_loss_sign.py`
- **Files read-only**:
  - `src/shadow_trading/exit_reason.py`
  - `src/shadow_trading/reconcile.py`
  - `frontend/src/pages/Simulation.jsx`
  - `frontend/src/pages/StressTest.jsx`

**Description:**

E2: pre-investigation done (executor.py:1872, reconcile.py:131). Read `src/shadow_trading/executor.py:1872` (stop_loss exit construction) + `src/shadow_trading/reconcile.py:131` (matcher). Identify which computes pnl_dollars/pnl_pct from entry/exit; fix sign. If neither flips sign (downstream display-only), downgrade to 'investigation only' and add Sprint 4 follow-up to operator TaskList. E4: change `src/simulation/engine.py:458` to emit Python `None` instead of `999.0` when profit_factor is `inf`. NOTE: frontend null-handling for Simulation.jsx + StressTest.jsx is included in Task 14 (already in F2 scope) — Task 4 ships only backend + tests. Sibling-search executor.py for similar sign foot-guns; document.

**Scope fence:**

Do NOT modify Simulation.jsx / StressTest.jsx in this task — Task 14 owns frontend null-handling. Do NOT touch reconcile.py (read-only here; if sign-flip is in reconcile.py, expand scope in Sprint 4 follow-up). Do NOT add _meta to /api/simulation/results (Task 9). Do NOT change pnl semantics for non-stop_loss exits.

**Test strategy:**

E2: 1) Synthetic exit, exit_reason='stop_loss', entry=100, exit=95 → pnl_pct < 0 AND pnl_dollars < 0. 2) Sibling: target_hit yields pnl > 0. E4: 1) Winners-only → profit_factor None. 2) Mixed → finite float. 3) Empty → 0 (legacy contract preserved). Tests live at root tests/ (not tests/simulation/ which doesn't exist).

---

### Task 5 — A3 — KPICard meta prop + cohort badge

- **Batch**: ?
- **Depends on**: none (root)
- **Complexity**: ?
- **Files in scope**:
  - `frontend/src/components/dashboard/KPIStrip.jsx`
  - `frontend/src/components/dashboard/KPIStrip.test.jsx`
- **Files read-only**:
  - `frontend/src/pages/Dashboard.jsx`

**Description:**

Add `meta` prop to `KPICard` in `frontend/src/components/dashboard/KPIStrip.jsx`. Anchor near the existing `caption=` and `subLine=` props (search for `caption=\`N=` and `subLine` to locate the function definition). When meta is provided, render small italic muted-text badge with `n=N · <last-segment-of-cohort-id>` and tooltip showing full label. Extend `KPIStrip.test.jsx` with meta-prop test + undefined-meta-no-badge test. Visual-verify rule: render in browser before push.

**Scope fence:**

Do NOT wire Dashboard.jsx or any consumer to pass meta yet — Task 12. Do NOT modify other KPIStrip subcomponents. Do NOT touch the existing `caption` or `subLine` rendering logic beyond placement of the new meta block.

**Test strategy:**

1) Given meta={cohort:'kpi.canonical', label:'Fully instrumented (v3)', n:5} → badge renders with `n=5 · canonical`. 2) Tooltip shows full label on hover. 3) When meta is undefined, no badge renders (BC). 4) Visual-verify screenshot in PR.

---

### Task 6 — C1 — Shared LoadingState (with retryDisabledFor cooldown)

- **Batch**: ?
- **Depends on**: none (root)
- **Complexity**: ?
- **Files in scope**:
  - `frontend/src/components/LoadingState.jsx`
  - `frontend/src/components/LoadingState.test.jsx`
- **Files read-only**:
  - `frontend/src/components/LoadingSpinner.jsx`
  - `frontend/src/components/EmptyState.jsx`

**Description:**

Create `frontend/src/components/LoadingState.jsx` wrapping existing `LoadingSpinner` and `EmptyState`. API includes `retryDisabledFor={ms}` cooldown (NEW v2). Render: spinner / error-card-with-cooldown-retry / empty-card / children. Add `LoadingState.test.jsx` with all 5 cases including retry-cooldown via `vi.useFakeTimers()`.

**Scope fence:**

Do NOT replace LoadingSpinner or EmptyState — wrap them. Do NOT migrate any consumer widget yet — Task 13. Do NOT add data-fetch logic.

**Test strategy:**

1) isLoading=true → spinner + loadingMessage. 2) isError=true with error.message='X' → error card with 'X' + retry button; click → calls retry(); button disabled for retryDisabledFor ms. 3) isEmpty=true → empty card. 4) data path → children. 5) compact=true → inline (no card).

---

### Task 7 — F1 — Shared ActionButton (cliOnly + secure-context fallback)

- **Batch**: ?
- **Depends on**: none (root)
- **Complexity**: ?
- **Files in scope**:
  - `frontend/src/components/ActionButton.jsx`
  - `frontend/src/components/ActionButton.test.jsx`
- **Files read-only**:
  - `frontend/src/pages/LiveLedger.jsx`
  - `frontend/src/components/Tooltip.jsx`

**Description:**

Create `frontend/src/components/ActionButton.jsx`. cliOnly=true renders disabled button + [CLI only] badge + Tooltip with whyDisabled + monospace cliCommand + Copy button. NEW v2: copy handler checks `navigator.clipboard && window.isSecureContext`; on failure or non-secure-context, falls back to selectable `<pre>` with 'Press Ctrl+C' hint. Catches promise rejections. cliOnly=false renders normal active button. pending=true shows inline spinner. Reference: `LiveLedger.jsx:271-276`.

**Scope fence:**

Do NOT migrate any existing button to ActionButton yet — Task 14. Do NOT modify Tooltip. Do NOT add cloud-vs-local detection — consumer's responsibility.

**Test strategy:**

1) cliOnly=true: button has `disabled` + opacity-50 + [CLI only] badge. 2) cliOnly=true: hover shows tooltip with cliCommand monospace + Copy. 3) Copy in secure context → `navigator.clipboard.writeText` called with cliCommand; success hint. 4) Copy in non-secure context (mocked `window.isSecureContext = false`) → fallback `<pre>` selected + 'Press Ctrl+C' hint, no exception. 5) cliOnly=false + onClick: click fires onClick. 6) pending=true: button disabled + spinner.

---

### Task 8 — A1 — Backend _meta helper + KPI/CTO/Status emission

- **Batch**: ?
- **Depends on**: [1, 2]
- **Complexity**: ?
- **Files in scope**:
  - `src/api/cohort_meta.py`
  - `src/api/cloud_routes/kpis.py`
  - `src/api/cloud_routes/core.py`
  - `tests/api/test_status.py`
- **Files read-only**:
  - `src/api/cloud_routes/analytics.py`
  - `src/analytics/instrumentation_filter.py`
  - `tests/api/test_kpis.py`
  - `tests/test_cto_report.py`

**Description:**

Create `src/api/cohort_meta.py` exporting `COHORT_LABELS` dict and `meta_entry(cohort_id, n, label=None)` (raises KeyError for unknown cohort). Document the shadow_metrics cohort-resolution rule in module docstring. Wire into `/api/kpis` (kpis.py:69-93), `/api/cto-report` (analytics.py per-section: trade_summary, performance, fund_metrics), `/api/status` (core.py:142-194). Per-section _meta for cto-report. Extend `tests/api/test_kpis.py`, `tests/test_cto_report.py` (root path, NOT tests/api/), CREATE `tests/api/test_status.py` (NEW file).

**Scope fence:**

Do NOT touch other analytics.py endpoints — Task 9. Do NOT modify training.py — Task 9 owns model-performance. Do NOT touch trades.py — Task 9 owns shadow/metrics. Do NOT modify the numeric values of existing keys (additive _meta only). Tests for cto_report and kpis are 'read-only' to avoid file-collision; if assertions need to land, fold into Task 9 via files_in_scope expansion.

**Test strategy:**

1) /api/kpis _meta.rf_adjusted_excess_sharpe.cohort='kpi.canonical'. 2) /api/cto-report _meta.trade_summary.win_rate.cohort='trades.all_closed' (per-section). 3) /api/status _meta.open_positions.cohort='trades.live_only'. 4) All cohort_id values present in COHORT_LABELS. 5) meta_entry('unknown', 0) raises KeyError. NOTE: extending test_kpis.py and tests/test_cto_report.py is reading-only here as marker — actual extension by Task 18 closeout sweep IF needed; primary _meta assertions land in test_status.py + new fixtures in this task.

---

### Task 9 — A1.B — Backend _meta on remaining 7 endpoints (training.py corrected)

- **Batch**: ?
- **Depends on**: [2, 3, 8]
- **Complexity**: ?
- **Files in scope**:
  - `src/api/cloud_routes/analytics.py`
  - `src/api/cloud_routes/trades.py`
  - `src/api/cloud_routes/training.py`
  - `tests/test_cto_report.py`
- **Files read-only**:
  - `src/api/cohort_meta.py`
  - `tests/api/test_attribution_stats.py`
  - `tests/api/test_kpis.py`

**Description:**

Wire `_meta` into the remaining endpoints: /api/shadow/metrics (`src/api/cloud_routes/trades.py` — emits trades.all_closed by default, trades.live_only when desk filter applied per §2.3 rule), /api/attribution/stats (analytics.py:718, depends Task 2's paired_n), /api/strategy-detail (analytics.py:769), **/api/model-performance (`src/api/cloud_routes/training.py:549` — CORRECTED v2; was incorrectly placed in analytics.py)**, /api/build-score (analytics.py), /api/health/hshs (analytics.py:244 — per-section: overall=none, performance=trades.all_closed), /api/stress-test/results (analytics.py:885), /api/simulation/results (analytics.py). Extend `tests/test_cto_report.py` (existing root path) + `tests/api/test_kpis.py` if cross-referenced.

**Scope fence:**

Do NOT alter existing numeric keys. Do NOT add new endpoints. Do NOT touch /api/kpis, /api/cto-report, /api/status (Task 8 owns). Do NOT touch /api/monitoring/* (Task 3).

**Test strategy:**

1) Each endpoint emits valid `_meta` envelope. 2) /api/health/hshs has per-section _meta. 3) /api/strategy-detail/pullback emits cohort='trades.strategy'. 4) /api/attribution/stats emits cohort='attribution.pairs'. 5) /api/build-score emits cohort='none' (still emits envelope). 6) /api/model-performance (in training.py) emits cohort='trades.model'. 7) /api/shadow/metrics emits trades.all_closed by default; trades.live_only with desk=live filter (§2.3 rule).

---

### Task 10 — B1 + B2 — Header migration with 3 explicit fallback states

- **Batch**: ?
- **Depends on**: [8]
- **Complexity**: ?
- **Files in scope**:
  - `frontend/src/components/Layout.jsx`
  - `frontend/src/api.js`
  - `frontend/src/components/Layout.test.jsx`
- **Files read-only**:
  - `src/api/cloud_routes/kpis.py`
  - `src/api/cloud_routes/kpis_compute.py`
  - `frontend/src/components/dashboard/KPIStrip.jsx`

**Description:**

Per deep report Focus 5 Option (b): migrate `frontend/src/components/Layout.jsx:103` to fetch `/api/kpis` (queryKey ['kpis'], shared with KPIStrip). Read `kpis.stage_traffic_light.decision_matrix_state`. NEW v2: implement 3 explicit fallback states — (a) `kpisQuery.isError` → 'TL: ERR' with `last_attempt` tooltip; (b) `kpis === undefined || isPending` → 'TL: …'; (c) `kpis.stage_traffic_light?.decision_matrix_state == null` → 'TL: COMPUTING' with `last_computed_at` tooltip if present. Verify `api.js` has `getKpis`; add if absent. Add tooltip to `25 POSITIONS`. Visual-verify rule.

**Scope fence:**

Do NOT modify /api/status response shape. Do NOT add traffic_light to /api/status (rejected per D6). Do NOT touch other StatusBar fields (LLM, MKT, version). NOTE: Task 17a will wrap the existing useQuery({queryFn: api.getStatus}) in Layout.jsx:103 with arrow — do NOT pre-wrap here; Task 17a owns it.

**Test strategy:**

1) Mock /api/kpis returning decision_matrix_state='GREEN' → 'TL: GREEN' green-styled. 2) Mock kpisQuery.isPending=true → 'TL: …'. 3) Mock kpis loaded but stage_traffic_light=null → 'TL: COMPUTING' with last_computed_at tooltip if present. 4) Mock kpisQuery.isError=true → 'TL: ERR' with last-attempt tooltip. 5) queryKey ['kpis'] shared with KPIStrip → only one fetch per 30s window. 6) Visual-verify screenshot in PR.

---

### Task 11 — E3 + E8 — Float-precision clamp + IB-status feature flag (corrected import)

- **Batch**: ?
- **Depends on**: none (root)
- **Complexity**: ?
- **Files in scope**:
  - `frontend/src/pages/Settings.jsx`
  - `frontend/src/pages/Health.jsx`
  - `frontend/src/pages/Settings.test.jsx`
  - `frontend/src/pages/Health.test.jsx`
- **Files read-only**:
  - `frontend/src/components/Layout.jsx`
  - `frontend/src/config.js`

**Description:**

E3: `frontend/src/pages/Settings.jsx:43` SettingInput — defense-in-depth precision clamp. (a) Mount: useState clamps to step precision via toFixed. (b) onBlur emit: only clamp when `Math.abs(localValue - displayValue) < step/2` (preserves user's finer-than-step typing). E8: `frontend/src/pages/Health.jsx:68` — feature-flag `getIBStatus` useQuery with `enabled: !IS_CLOUD`. CORRECTED v2: import `IS_CLOUD` from `'../config'` (NOT `@/utils/env`). Render 'Not available in cloud mode' when IS_CLOUD && !ibStatus. Health.jsx and Settings.jsx are also touched by Tasks 13/15/17b — see scope_fence below.

**Scope fence:**

CO-OWNERSHIP NOTE: Health.jsx is also touched by Task 13 (LoadingState migration) and Task 17b (E1 wraps); Settings.jsx is also touched by Task 15 (IB toggle cliOnly) and Task 17b (E1 wraps). Sequenced via depends_on so file-collision avoided. This task: ONLY E3 SettingInput precision clamp + E8 IS_CLOUD gate on getIBStatus useQuery + import of IS_CLOUD from '../config'. Do NOT migrate other Health widgets to LoadingState (Task 13). Do NOT migrate IB toggles (Task 15). Do NOT touch the Roadmap.jsx 'slider' (operator confirmation pending). Do NOT add backend stub for /api/ib/status. Do NOT pre-wrap useQuery sites in arrow form (Task 17b).

**Test strategy:**

E3: 1) Initial 0.005000000001 with step=0.001 → renders 0.005. 2) onBlur: 0.005000000001 typed → emits 0.005 (drift clamped). 3) onBlur: user types 0.006 (different from 0.005 by step) → emits 0.006 (preserved, no spurious clamp). E8: 1) IS_CLOUD=true → enabled=false, fetch mock not called. 2) IS_CLOUD=false → enabled=true, fetch fires.

---

### Task 12 — A4 — Dashboard / TradeHistory / Strategy meta consumption

- **Batch**: ?
- **Depends on**: [5, 8, 9]
- **Complexity**: ?
- **Files in scope**:
  - `frontend/src/pages/Dashboard.jsx`
  - `frontend/src/pages/TradeHistory.jsx`
  - `frontend/src/pages/Strategy.jsx`
  - `frontend/src/pages/TradeHistory.test.jsx`
- **Files read-only**:
  - `frontend/src/components/dashboard/KPIStrip.jsx`

**Description:**

Wire `meta={kpis._meta?.<field>}` props through Dashboard.jsx (KPI strip cards), TradeHistory.jsx (Sharpe attribution numbers), Strategy.jsx (per-strategy stats from /api/strategy-detail). Add cohort badge below relevant numeric values via the KPICard meta prop (Task 5) + ad-hoc badges where KPICard isn't used. Visual-verify rule.

**Scope fence:**

Do NOT modify KPICard component (Task 5). Do NOT migrate other pages (only Dashboard, TradeHistory, Strategy). Do NOT modify endpoint responses (Tasks 8, 9). Do NOT pre-wrap useQuery sites in Dashboard.jsx (Task 17a owns those wraps).

**Test strategy:**

1) Dashboard.jsx KPICard receives meta from kpis._meta.win_rate; badge renders. 2) TradeHistory.jsx Sharpe section shows badge from response._meta.sharpe_ratio. 3) Strategy.jsx renders strategy cohort badge from /api/strategy-detail._meta. 4) Visual-verify screenshot.

---

### Task 13 — C2 — Migrate 4 widgets to LoadingState

- **Batch**: ?
- **Depends on**: [3, 6, 11]
- **Complexity**: ?
- **Files in scope**:
  - `frontend/src/components/dashboard/BrokerExceptionsPanel.jsx`
  - `frontend/src/pages/DBSchema.jsx`
  - `frontend/src/pages/Health.jsx`
  - `frontend/src/pages/Monitoring.jsx`
- **Files read-only**:
  - `frontend/src/components/LoadingState.jsx`

**Description:**

Replace ad-hoc loading patterns: BrokerExceptionsPanel.jsx (compact variant for inline rows), DBSchema.jsx (page-level), Health.jsx (replace 'Collecting...' text), Monitoring.jsx (replace LoadingSpinner; CRUCIAL: pass isError to LoadingState — closes the presentation bug from Task 3). All 4 must pass `isError` from useQuery. Visual-verify all 4 widget states. Health.jsx is co-owned with Task 11/17b; sequence via depends_on.

**Scope fence:**

CO-OWNERSHIP: Health.jsx also touched by Task 11 (E8 IB feature flag) and Task 17b (E1 wraps). Sequenced via depends_on=[3,6,11]; ensure rebase + scope-check before commit. Monitoring.jsx also touched by Task 17b. Do NOT migrate widgets outside the 4 named (Roadmap, Notes, Council are Sprint 4). Do NOT modify LoadingState (Task 6). Do NOT change useQuery beyond consuming isError. Do NOT pre-wrap useQuery sites in arrow form (Task 17b).

**Test strategy:**

1) BrokerExceptionsPanel: isLoading=true → spinner; isError → error card + retry; isEmpty → '✓ no exceptions'. 2) DBSchema: page-level loading + error states. 3) Health: 'Collecting HSHS' replaced with LoadingState empty. 4) Monitoring: 503/500 from /api/monitoring/history → error card (not infinite spinner) — closes E7 presentation bug. 5) Visual-verify all 4 states.

---

### Task 14 — F2 — Migrate 4 pages to ActionButton (Settings IB deferred to Task 15)

- **Batch**: ?
- **Depends on**: [4, 7]
- **Complexity**: ?
- **Files in scope**:
  - `frontend/src/pages/LiveLedger.jsx`
  - `frontend/src/components/DiagnosticKickoffButtons.jsx`
  - `frontend/src/pages/Simulation.jsx`
  - `frontend/src/pages/Council.jsx`
- **Files read-only**:
  - `frontend/src/components/ActionButton.jsx`
  - `frontend/src/pages/StressTest.jsx`
  - `frontend/src/pages/Settings.jsx`

**Description:**

Apply ActionButton per §7.2 decision matrix. Live Ledger reconcile → cliOnly. Diagnostics 3 buttons (DiagnosticKickoffButtons.jsx) → cloud-actionable. Simulation Run button → cloud-actionable + dedupe (one shared instance for empty-state + header). Council Run + Ask → cloud-actionable. ALSO null-handle profit_factor in Simulation.jsx + StressTest.jsx (consume Task 4's null sentinel: render 'N/A (no losses)'). EXPLICITLY DEFER Settings IB toggles to Task 15 — do NOT touch Settings.jsx in this task. Visual-verify rule.

**Scope fence:**

Do NOT touch Settings.jsx — Task 15 owns IB toggles; non-IB toggles unchanged. Do NOT modify mutations / network calls — only button rendering. Do NOT deduplicate beyond named Simulation duplicate. Do NOT pre-wrap useQuery sites in arrow form (Task 17b owns those for these files).

**Test strategy:**

1) LiveLedger: ActionButton cliOnly + cliCommand 'python -m src.main reconcile-live' rendered. 2) Diagnostics 3 buttons: ActionButton non-cliOnly with their existing mutations, no regression. 3) Simulation: only ONE ActionButton instance (dedupe verified via DOM count). 4) Council 2 buttons: ActionButton non-cliOnly. 5) Simulation.jsx + StressTest.jsx render `null` profit_factor as 'N/A (no losses)'. NOTE: StressTest.jsx is read-only here — if it requires editing for null handling, expand scope to add it; flag in PR if scope adjustment needed.

---

### Task 15 — F2.B — Settings IB toggle migration to ActionButton cliOnly

- **Batch**: ?
- **Depends on**: [7, 11]
- **Complexity**: ?
- **Files in scope**:
  - `frontend/src/pages/Settings.jsx`
  - `frontend/src/pages/Settings.test.jsx`
- **Files read-only**:
  - `frontend/src/components/ActionButton.jsx`

**Description:**

Migrate `live_trading.ib.shadow_mode` and `live_trading.ib.paper_routing` toggles in `Settings.jsx` to ActionButton cliOnly variant (or visually-disabled toggle with whyDisabled='Effect requires local IB Gateway connection'). Per §7.2 decision matrix. Add unit test asserting the IB toggles are visually disabled with reason text.

**Scope fence:**

Do NOT touch non-IB Settings rows. Do NOT change underlying api.updateSettings mutation. Do NOT modify SettingsToggle / SettingInput components beyond IB-specific visual-disable. Do NOT pre-wrap useQuery sites in arrow form (Task 17b).

**Test strategy:**

1) IB shadow_mode row: cliOnly (or visually-disabled toggle) with whyDisabled visible. 2) IB paper_routing row: same. 3) Other Settings toggles unchanged. 4) Mutation onUpdate not fired for IB rows even on click.

---

### Task 16 — B3 — CI dashboard reconciliation test (SQLite-only, cohort-aware)

- **Batch**: ?
- **Depends on**: [8, 9]
- **Complexity**: ?
- **Files in scope**:
  - `tests/test_dashboard_reconciliation.py`
- **Files read-only**:
  - `src/api/cohort_meta.py`
  - `src/api/cloud_routes/kpis.py`
  - `src/api/cloud_routes/core.py`
  - `src/api/cloud_routes/analytics.py`

**Description:**

Create `tests/test_dashboard_reconciliation.py`. NEW v2: explicitly scope as SQLite-only (Postgres runbook deferred to Sprint 4 follow-up `#SP4-render-pg-reconcile`). Cohort-aware assertions: assert each endpoint emits `_meta`; assert `cohort` match BEFORE asserting `n` equality (skip cohort-mismatch case as 'by design'); separate test for /api/status.open_positions vs /api/live/summary.open_positions.

**Scope fence:**

Do NOT add new endpoints to test against. Do NOT modify backend response shape (read-only test). Do NOT use real network — fixtures only. Postgres validation explicitly OUT OF SCOPE (Sprint 4 follow-up).

**Test strategy:**

1) test_all_endpoints_emit_meta: iterate 5 endpoints, assert _meta present. 2) test_closed_count_reconciles: assert cto._meta.trade_summary.win_rate.cohort == shadow._meta.win_rate.cohort FIRST; if drift (e.g., desk filter applied), pytest.skip; otherwise assert n == n. 3) test_open_position_reconcile: /api/status.open_positions == /api/live/summary.open_positions. 4) test_invalid_cohort_id_rejected: meta_entry('bogus', 0) raises KeyError.

---

### Task 17 — E1.A — TanStack v5 wraps (parallel-safe files, 9 files)

- **Batch**: ?
- **Depends on**: [10]
- **Complexity**: ?
- **Files in scope**:
  - `frontend/src/components/Layout.jsx`
  - `frontend/src/components/RevenueProjection.jsx`
  - `frontend/src/pages/IBShadow.jsx`
  - `frontend/src/pages/Notes.jsx`
- **Files read-only**:
  - `frontend/src/api.js`

**Description:**

NEW v2 split: wrap useQuery({queryFn: api.X}) sites in 4 files NOT touched by other Sprint 3 tasks. Files: `Layout.jsx` (L103 — coordinated with Task 10), `components/RevenueProjection.jsx` (path corrected v3: file lives in components/, not pages/), `IBShadow.jsx`, `Notes.jsx`. Each file's useQuery({queryFn: api.foo}) sites wrapped in `() => api.foo()` arrows. NOTE: Task 10 modifies Layout.jsx — Task 17a sequences after Task 10 to avoid collision. Sibling-search each file for queryFn patterns; document in PR.

**Scope fence:**

Do NOT touch files outside the 4 named — Task 17a-extension owns the rest. Do NOT modify api.js method signatures. Do NOT change useQuery options beyond queryFn shape. Do NOT touch Dashboard.jsx (Task 17a-extension below). Stay strictly within 4 files.

**Test strategy:**

1) After wrap: each useQuery's queryFn is an arrow, not a bare api method ref. 2) Smoke: navigate cloud Dashboard — no '?desk=%5Bobject+Object%5D' URLs in network log. 3) ESLint custom rule (Task 17c) is registered — passes after wrap.

---

### Task 18 — E1.A2 — TanStack v5 wraps (parallel-safe, 4 more files)

- **Batch**: ?
- **Depends on**: [12]
- **Complexity**: ?
- **Files in scope**:
  - `frontend/src/pages/Dashboard.jsx`
  - `frontend/src/pages/ModelPerformance.jsx`
  - `frontend/src/pages/StressTest.jsx`
  - `frontend/src/pages/Training.jsx`
- **Files read-only**:
  - `frontend/src/api.js`

**Description:**

Continuation of Task 17 split. Files: `Docs.jsx`, `ModelPerformance.jsx`, `Training.jsx`, `Validation.jsx`, plus `StressTest.jsx`, `Dashboard.jsx` (pages/). Wraps stylistic-only sites for consistency. Reduces to 4 files_in_scope: Dashboard.jsx, ModelPerformance.jsx, StressTest.jsx, Training.jsx. Three remaining files (Docs.jsx, Notes.jsx, Validation.jsx) tracked separately in Task 19. Sibling-search each file.

**Scope fence:**

Dashboard.jsx is owned by Task 12 — sequenced via depends_on=[12]. Do NOT modify any other content of these files beyond wrapping useQuery({queryFn: api.X}) → useQuery({queryFn: () => api.X()}). Do NOT touch api.js signatures. Files outside the 4 named are owned by Task 19 / Task 20.

**Test strategy:**

Same as Task 17. Each useQuery's queryFn wrapped; ESLint rule passes.

---

### Task 19 — E1.A3 — TanStack v5 wraps (parallel-safe, final 3 files)

- **Batch**: ?
- **Depends on**: [12]
- **Complexity**: ?
- **Files in scope**:
  - `frontend/src/pages/Docs.jsx`
  - `frontend/src/pages/Validation.jsx`
  - `frontend/src/pages/TradeHistory.jsx`
- **Files read-only**:
  - `frontend/src/api.js`

**Description:**

Continuation of Task 17 split. Files: `Docs.jsx`, `Validation.jsx`, plus `TradeHistory.jsx` (the L237 buggy site getSharpeAttribution wrap is THE primary bug fix here; also wrap any other useQuery sites). Note: TradeHistory.jsx is co-owned with Task 12 — sequenced via depends_on. Sibling-search each file.

**Scope fence:**

TradeHistory.jsx co-owned with Task 12. Sequenced via depends_on. Do NOT modify any non-queryFn-wrap content. Do NOT touch api.js signatures.

**Test strategy:**

1) TradeHistory.jsx:237 wrapped: queryFn: () => api.getSharpeAttribution(filter). 2) Smoke: TradeHistory page with filter — no '?filter=%5Bobject+Object%5D' URLs.

---

### Task 20 — E1.B — TanStack v5 wraps (sequenced, file-conflict subset)

- **Batch**: ?
- **Depends on**: [2, 3, 11, 13, 15]
- **Complexity**: ?
- **Files in scope**:
  - `frontend/src/pages/Attribution.jsx`
  - `frontend/src/pages/Settings.jsx`
  - `frontend/src/pages/Health.jsx`
  - `frontend/src/pages/Monitoring.jsx`
- **Files read-only**:
  - `frontend/src/api.js`

**Description:**

NEW v2: wrap useQuery({queryFn: api.X}) sites in 6 files OWNED by prior tasks. Files: `Attribution.jsx` (Task 2 owns), `Settings.jsx` (Tasks 11+15 own), `Health.jsx` (Tasks 11+13 own), `Monitoring.jsx` (Tasks 3+13 own). Other conflict-prone files (LiveLedger.jsx, Council.jsx, Simulation.jsx, ShadowLedger.jsx, DiagnosticKickoffButtons.jsx) in Task 21 (split for files_in_scope ≤4). Sequenced AFTER all owning tasks complete; rebase before commit.

**Scope fence:**

Sequenced AFTER owning tasks. Rebase against latest origin/main before push (pre-push stale-base hook will refuse otherwise). Do NOT modify any other content of these files beyond queryFn wraps. Sibling-search each file: grep `queryFn: api\.` to confirm exhaustive wrap.

**Test strategy:**

Same as Task 17/18/19. After wrap: ESLint custom rule passes; no bare-queryFn sites remain in these 4 files.

---

### Task 21 — E1.B2 — TanStack v5 wraps (final sequenced files)

- **Batch**: ?
- **Depends on**: [4, 14]
- **Complexity**: ?
- **Files in scope**:
  - `frontend/src/pages/LiveLedger.jsx`
  - `frontend/src/pages/Council.jsx`
  - `frontend/src/pages/Simulation.jsx`
  - `frontend/src/pages/ShadowLedger.jsx`
- **Files read-only**:
  - `frontend/src/api.js`
  - `frontend/src/components/DiagnosticKickoffButtons.jsx`

**Description:**

Final E1 split task. Files: `LiveLedger.jsx`, `Council.jsx`, `Simulation.jsx`, `ShadowLedger.jsx` (the L476/L478/L481 buggy sites). Plus `DiagnosticKickoffButtons.jsx` is OUT OF SCOPE here — it has no useQuery sites that match the bare-queryFn pattern (verify; if found, expand). Sequenced AFTER Tasks 4 + 14. Sibling-search each file.

**Scope fence:**

Sequenced AFTER owning tasks. Rebase against latest origin/main before push. Do NOT modify any other content. Do NOT touch DiagnosticKickoffButtons.jsx unless an unwrapped site is found (sibling-search it; if found, expand scope and document).

**Test strategy:**

1) ShadowLedger.jsx:476 wrapped: queryFn: () => api.getOpenTrades(desk). 2) ShadowLedger.jsx:478, :481 wrapped. 3) LiveLedger.jsx:164,167 wrapped. 4) Council.jsx:287 wrapped. 5) Simulation.jsx:50 wrapped. 6) Smoke: ShadowLedger with desk filter — no '?desk=%5Bobject+Object%5D' URLs.

---

### Task 22 — E1.C — ESLint custom rule + npm script + pytest fixture

- **Batch**: ?
- **Depends on**: [17, 18, 19, 20, 21]
- **Complexity**: ?
- **Files in scope**:
  - `frontend/eslint-rules/no-bare-queryfn-with-args.js`
  - `frontend/eslint.config.js`
  - `frontend/package.json`
  - `tests/test_eslint_queryfn_guardrail.py`

**Description:**

Create `frontend/eslint-rules/no-bare-queryfn-with-args.js` — ESLint rule that visits ObjectExpression nodes inside useQuery() calls; flags Property nodes where key.name === 'queryFn' and value.type === 'Identifier' (i.e., a bare api method reference, not an arrow). Register in `frontend/eslint.config.js` under `rules`. Add `lint:queryfn` npm script in `frontend/package.json`. Create `tests/test_eslint_queryfn_guardrail.py` — pytest fixture that shells out to `npm --prefix frontend run lint:queryfn`, asserts exit 0. Sequenced AFTER all 17/18/19/20/21 wraps complete (lint must pass).

**Scope fence:**

Do NOT modify api.js signatures. Do NOT touch any wrapped sites (Tasks 17-21 own). The custom rule only flags Identifier-shaped queryFn values; arrow functions are accepted regardless of body.

**Test strategy:**

1) ESLint rule fires on synthetic test code with `useQuery({queryFn: api.foo})` (bare). 2) ESLint rule does NOT fire on `useQuery({queryFn: () => api.foo()})`. 3) `npm --prefix frontend run lint:queryfn` exits 0 against current frontend (after all wraps). 4) Pytest fixture passes.

---

### Task 23 — Sprint closeout — CHANGELOG + operator runbook + visual-verify gallery + strict test count

- **Batch**: ?
- **Depends on**: [16, 22]
- **Complexity**: ?
- **Files in scope**:
  - `CHANGELOG.md`
  - `docs/operator-guide.md`
  - `config/known_violations.json`
- **Files read-only**:
  - `tests/test_repo_structure.py`

**Description:**

Update `CHANGELOG.md` Unreleased with all Sprint 3 deliverables (E1-E8, A1-A4, B1-B3, C1-C2, F1-F2). Update `docs/operator-guide.md` if any operator-runnable command was added (likely none). Compile visual-verify screenshot gallery for PR descriptions. Run final pytest sweep — assert STRICT EQUALITY: `pass_count == 4602 + 44 = 4646`. Run test_repo_structure.py; document any new violations in known_violations.json. Add Sprint 4 follow-ups to operator TaskList: `#SP4-render-pg-reconcile`, `#SP4-calmar-debt`, `#SP4-stop-loss-fallback` (if Task 4 downgraded to investigation-only).

**Scope fence:**

Do NOT touch src/version.py (no version bump in Sprint 3). Do NOT modify governance docs (MASTER.md, CLAUDE.md). Do NOT bypass test_repo_structure.py via fix-not-acknowledge. Do NOT silently update test count target — operator must approve any deviation from 4646.

**Test strategy:**

1) Run `python -m pytest tests/ -q --timeout=60`; assert pass count == 4646 (strict). If different, root-cause and adjust spec OR adjust test count BEFORE merge. 2) Run `python -m pytest tests/test_repo_structure.py -v`; document any new violations. 3) Visual-verify gallery linked from PR. 4) CHANGELOG.md has entries for all Group E/A/B/C/F deliverables.

---

## Sprint workflow

- Worktree-isolated dispatch per task (CLAUDE.md mandate). PM writes `.claude/agent-scope.json` per dispatch with `files_in_scope` exactly mirroring this plan's entries — pre-commit scope-check hook enforces.
- Pre-push stale-base hook will refuse a push if origin/main has advanced past the agent's branch base. Sequenced tasks (e.g., T1→T2→T3 on analytics.py; T20 depending on [2, 3, 11, 13, 15]) must rebase before push.
- Each PR updates `CHANGELOG.md` under `[Unreleased]`. Sprint closeout (Task 23) consolidates the entries.
- Visual-verify rule applies to any frontend Dashboard / KPIStrip / Layout edit (per CLAUDE.md `feedback_visual_verify_ui` memory).
- `test_repo_structure.py` disclosure: any new file/function size violation must be added to `config/known_violations.json` with rationale.

## Reviewer dispatch (per CLAUDE.md table)

| Task touches… | QA | Security | Performance |
|---------------|----|----------|-------------|
| API routes (T1, T2, T3, T8, T9, T10) | ✓ | — | ✓ |
| Frontend components (T5, T6, T7) | ✓ | — | — |
| Page retrofit / migration (T12-T15) | ✓ | — | — |
| Sweep / code-mod (T17-T22) | ✓ | — | — |
| CI test (T16) | ✓ | — | — |
| Closeout (T23, docs) | — | — | — |
