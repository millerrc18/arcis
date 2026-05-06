# Methodology Gate Wiring — Implementation Plan v5

**Source spec**: `docs/audits/2026-05-05-methodology-gate-wiring/spec.md` (v5)

## Execution order (parallel batches)

**Batch 1**: T1, T3
**Batch 2**: T2
**Batch 3**: T4, T5, T6
**Batch 4**: T7, T8
**Batch 5**: T9

## Notes

Task 1 (registry doc-string update) and Task 3 (trainer + kpi_compute input-quality fix) are independent — run in parallel as wave 1. Task 2 is the primary integration point (Critical 2 fix) and gates everything downstream. Wave 3 (Tasks 4, 5, 6) can run in parallel: watch.py firing, CLI, KPI compute. Wave 4 (Tasks 7, 8): dashboard route depends on KPI; integration tests depend on the full stack. Task 9 (docs) closes the sprint. Worktree isolation MANDATORY for waves 1, 3, and 4. Each agent must run `python -m pytest tests/test_repo_structure.py -v` and disclose violations in its strict-rigor receipt. Test count baseline (3682) bumps after T8 completes.

**v5 changes vs v4** (final architect revision before Sprint 2 resumes):
- T2 description expanded with (a) explicit AND-compose insertion at all SEVEN return sites of `_evaluate_shadow_trading_gate` (DA major fix 1: line 298 was missing in v4), (b) `walkforward_status` placement inside `_evaluate_walkforward_gate` alongside (NOT replacing) `walkforward_outcome_state` (DA major fix 4), (c) production-gate asymmetry note — DSR-only AND-compose at production target (DA major fix 5).
- T2 new tests added: `test_methodology_gate_and_composed_at_walkforward_pass_path`, `test_walkforward_status_populated_for_all_four_states`, `test_walkforward_outcome_state_still_populated_for_backwards_compat`, `test_production_gate_methodology_compose_with_dsr_only`, `test_methodology_gate_evidence_schema_matches_decide_function`.
- T3 description expanded with (a) NULL `actual_entry_time` handling in SQL (DA major fix 3), (b) length-invariant tests, (c) Choice A regression-lock that documents the long-only degeneracy of MC permutation, (d) sibling-search regression tests at `cli/commands.py:964 cmd_run_promotion_gate` (DA major fix 6).
- T3 complexity raised medium → high (Minor 3: cross-file refactor + test dependencies + verification step).
- T3 new tests added: `test_resolve_returns_for_gate_returns_length_matched_tuple`, `test_resolve_returns_for_gate_handles_null_entry_times`, `test_resolve_returns_for_gate_returns_empty_when_all_undated`, `test_trainer_promotion_gate_currently_cannot_promote_long_only`, `test_cmd_run_promotion_gate_post_fix_behavior`, `test_cmd_run_promotion_gate_passes_dates_directions`.
- T5 description gains an explicit ordering ratchet (Minor 1) — T5 cannot meaningfully gate-block until T2 has merged. Test `test_cli_confirm_promotion_re_fire_includes_methodology_gate` makes the dependency observable.
- All other tasks unchanged. Execution order, batch structure, and total task count (9) preserved.

## Tasks

### T1 — Update triggered_by ColumnDef description for new sentinels

**Complexity**: low

**Files in scope**: `src/schema/registry.py`, `tests/test_schema.py`

**Files read-only**: `src/platform/promotion.py`

**Description**: Modify the ColumnDef description string at src/schema/registry.py:2113-2114 to document the two new sentinel values 'gate_proposal' and 'operator_confirm'. Description-string-only change. NO schema migration. NO new tables. NO new columns.

**Test strategy**: Add a regression test asserting the ColumnDef description string contains all four sentinel values ('manual', 'auto_gate', 'gate_proposal', 'operator_confirm'). Run `python -m src.main validate-schema` and confirm no drift detected.

**Scope fence**: Do NOT add new tables. Do NOT add new columns. Do NOT modify any other ColumnDef. Do NOT change `gate_result_json` ColumnDef. Do NOT touch promotion.py or watch.py.

---

### T2 — Wire methodology gate into platform.promotion (AND-compose; vote schema; walkforward_status)

**Complexity**: high

**Depends on**: T1

**Files in scope**: `src/platform/promotion.py`, `tests/test_promotion_methodology_gate.py`

**Files read-only**: `src/methods/promotion_gate.py`, `src/methods/promotion_gate_helpers.py`, `src/analytics/instrumentation_filter.py`, `src/schema/registry.py`

**Description**: Primary integration task. In src/platform/promotion.py:

(a) Add `_evaluate_strategy_methodology_gate(strategy_id, db_path) -> tuple[bool, dict]` helper that loads shadow_trades, applies `analytics.instrumentation_filter.is_fully_instrumented` AND filters `actual_entry_time IS NOT NULL` AND `pnl_pct IS NOT NULL`, builds MethodInputs (returns + dates + directions; length invariant `len(returns) == len(dates) == len(directions)`), calls `methods.promotion_gate.promotion_gate(...)`, and returns `(passes_bool, evidence_dict)`. Evidence shape MUST match spec §3.2 EXACTLY — vote keys are `{cpcv, block_bootstrap, mc_perm, psr_dsr, white_rc}` (NO `pbo`; `mc_perm` not `mc_permutation`); `votes[name]` is `bool | None`; per-vote `details[name]` carries `{value, threshold, [details]}`; counts at `details.{n_pass, n_fail, n_abstentions}` (NOT top-level `tally`).

(b) **AND-compose at all SEVEN return sites of `_evaluate_shadow_trading_gate` (DA major fix 1):** lines 260, 269, 295, **298** (the wf-pass-PBO-pass success branch — most critical, was missing in v4 list), 303, 309, 315. Apply uniform pattern at each:
```python
mg_passes, mg_evidence = _evaluate_strategy_methodology_gate(strategy_id, db_path)
evidence['methodology_gate'] = mg_evidence
return (<existing-return-expr> and mg_passes), evidence
```

(c) **AND-compose at the ONE return site of `_evaluate_production_gate` (line 328):** `return passes_dsr, evidence`. Apply same pattern. NOTE (DA major fix 5): production gate only checks DSR — methodology AND-composes with DSR only here. Lines 326-327 explicitly set `pbo=None` and `oos_efficiency=None` as Sprint-4 placeholders; do NOT add walkforward/PBO logic here in this sprint.

(d) **`walkforward_status` placement inside `_evaluate_walkforward_gate` (DA major fix 4):**
- At line 223-225 (no-row branch), add `evidence["walkforward_status"] = "no_data_yet"` alongside the existing `walkforward_outcome_state = None` (preserve old key for backwards-compat).
- At line 226 onward (row-exists branches), add `evidence["walkforward_status"] = state.lower() if state else "no_data_yet"` alongside the existing `walkforward_outcome_state = wf["outcome_state"]`.
- Possible values: `'no_data_yet' | 'pass' | 'fail' | 'inconclusive'`.
- DO NOT remove or rename `walkforward_outcome_state` — backwards-compat for existing consumers.

(e) Add top-level `run_daily_gate_for_all_active_strategies(db_path, notify=None)` that iterates `get_strategies_by_status(['shadow_trading','backtested'])`, persists `triggered_by='gate_proposal'` rows, invokes notify on PASS.

(f) Honor `METHODOLOGY_GATE_ENABLED` flag — short-circuit to True with no persistence when false.

(g) `threshold_used` key in evidence per spec §3.2 ('4_of_5' default; '4_of_4_no_white_rc' fallback).

**Test strategy** (mandatory + DA-major-fix locks):
- `test_helper_aggregates_shadow_trades_correctly`
- `test_partial_instrumentation_excluded_from_gate_input`
- `test_empty_candidate_pool_uses_4_of_4_fallback_with_threshold_key`
- `test_feature_flag_disabled_short_circuits_persistence`
- `test_and_composition_with_walkforward_blocks_methodology_only_pass`
- **`test_methodology_gate_and_composed_at_walkforward_pass_path`** (DA major fix 1) — wf-PASS+PBO-PASS+DSR-PASS strategy with methodology gate False; assert `check_promotion_gate(target='shadow_trading')` returns False (line 298 AND-compose fired).
- **`test_methodology_gate_evidence_schema_matches_decide_function`** (DA major fix 2) — assert evidence keys match spec §3.2 EXACTLY: vote names `{cpcv, block_bootstrap, mc_perm, psr_dsr, white_rc}`; no `pbo` in votes; no top-level `tally`; per-vote details under `details[name]`.
- **`test_walkforward_status_populated_for_all_four_states`** (DA major fix 4) — assert all four values (`no_data_yet, pass, fail, inconclusive`) appear under their respective conditions.
- **`test_walkforward_outcome_state_still_populated_for_backwards_compat`** (DA major fix 4) — assert old key still set on every code path.
- **`test_production_gate_methodology_compose_with_dsr_only`** (DA major fix 5) — passing DSR + failing methodology against `target='production'`; assert overall False; assert `evidence['pbo'] is None` and `evidence['oos_efficiency'] is None`.
- `test_gate_proposal_row_has_from_status_eq_to_status`
- `test_run_daily_iterates_active_strategies_only`
- `test_walkforward_status_no_data_yet_when_table_empty`

**Scope fence**: Do NOT modify methods/promotion_gate.py. Do NOT modify methods/promotion_gate_helpers.py. Do NOT modify analytics/instrumentation_filter.py. Do NOT touch trainer.py, watch.py, or CLI. Do NOT add new tables. Do NOT change any existing ColumnDef. Do NOT modify the `promote()` function itself. Do NOT remove or rename `walkforward_outcome_state` (backwards-compat).

---

### T3 — Fix trainer abstention bug + kpi_compute mirror bug + Choice A regression-lock

**Complexity**: high (was medium in v4 — Minor 3: cross-file refactor + test dependencies + verification step)

**Files in scope**: `src/training/trainer.py`, `src/api/cloud_routes/kpis_compute.py`, `tests/test_trainer_dates_directions_fix.py`, `tests/test_cmd_run_promotion_gate_post_fix.py`

**Files read-only**: `src/methods/promotion_gate.py`, `src/methods/promotion_gate_helpers.py`, `src/methods/mc_permutation.py`, `src/api/cloud_routes/kpis.py`, `src/cli/commands.py`

**Description**:

**Pre-existing input-quality bug fix per Phase 4 deep_report finding 5, RE-VERIFIED 2026-05-05.**

> **Note (Operator Choice A, 2026-05-05): this fix does NOT, by itself, enable promote decisions in the trainer.py / kpis_compute.py call paths.** It only ensures the gate receives well-formed inputs (FRED-driven rf adjustment via `dates`; consistent `directions` encoding; non-NULL entry timestamps). Promote-capable evaluation runs through the **watch.py daily orchestrator (T4)** which can pass a real `candidate_pool` via `active_research_strategies`. See spec §1.3.1 "Sprint 2 limitations" for the long-only directions degeneracy in MC permutation that caps the trainer/kpi ceiling at 3-of-5 votes.

**The bug** at `src/training/trainer.py:1039`:
```python
result = promotion_gate(returns, n_trials=n_trials)
```
omits the `dates` and `directions` parameters. Per `promotion_gate_helpers.py:121-131` (MC permutation: abstains when `directions is None`) and `:178-188` (White RC: abstains when `n_trials<=1` and no `candidate_pool`), missing these args cause both methods to abstain unconditionally (`passed=None`).

**Mirror bug** at `src/api/cloud_routes/kpis_compute.py:376` (same omission pattern):
```python
gate_result = promotion_gate(returns, n_trials=1)
```

**Plus**: `_resolve_returns_for_gate` at `trainer.py:955` pre-subtracts `rf_placeholder = 0.0001` (lines 975-976). Once `dates` is passed to `promotion_gate(...)`, `_adjust_returns_via_fred` (helpers.py:225) subtracts FRED rf again → double-count.

**Sibling search — third callsite at `src/cli/commands.py:964` (`cmd_run_promotion_gate`):** calls `trainer.run_promotion_gate_for_version`, which calls `_resolve_returns_for_gate` and then `promotion_gate(...)` at trainer.py:1039. Transitively fixed by trainer.py fix; T3 adds explicit regression tests there to prevent silent drift (DA major fix 6).

**Fix shape**:

1. Refactor `_resolve_returns_for_gate` (trainer.py:955) to return tuple `(returns, dates, directions)`:
   - `returns`: `list[float]` of `pnl_pct/100` (raw, NO rf pre-subtraction)
   - `dates`: `list[date]` of `actual_entry_time` per trade — parsed via `date.fromisoformat(actual_entry_time[:10])`
   - `directions`: `list[int]` of `+1` (long-only system; `recommendations.direction` defaults to `'long'` per `registry.py:202`)
2. Update SELECT at trainer.py lines 967-972 to:
   - Fetch `actual_entry_time` AND `pnl_pct`.
   - **Enforce `actual_entry_time IS NOT NULL` filter alongside the existing `pnl_pct IS NOT NULL` filter** (DA major fix 3). Shadow trades may have NULL `actual_entry_time` (open positions, partial fills, backfilled orphans per CLAUDE.md).
3. **DROP** `rf_placeholder = 0.0001` pre-subtraction at trainer.py:975-976.
4. If filtered list is empty, return `([], [], [])`. The upstream `run_promotion_gate_for_version` already handles empty returns (lines 1019-1036).
5. Update the call at trainer.py:1039 to:
   ```python
   result = promotion_gate(returns, n_trials=n_trials, dates=dates, directions=directions)
   ```
6. Update `_compute_promotion_gate_kpi` (kpis_compute.py:364) to accept the trade list (or dates+directions). Update line 376 to pass new kwargs. Update caller at `kpis.py:91` to pass `instrumented` trade list (which already has `actual_entry_time` — see line 79). The kpi_compute call uses `n_trials=1` — White RC will continue to abstain there (no candidate_pool wired), which is a pre-existing limitation tracked separately. The MC-perm fix is the primary input-quality win at this site.
7. Length invariant `len(returns) == len(dates) == len(directions)` MUST hold at the call boundary.

**Test strategy**:
- `test_resolve_returns_for_gate_returns_tuple_shape` — locks new return shape `(returns, dates, directions)`.
- `test_resolve_returns_for_gate_returns_length_matched_tuple` (DA major fix 3) — asserts invariant `len(returns) == len(dates) == len(directions)` for every non-empty result.
- `test_resolve_returns_for_gate_handles_null_entry_times` (DA major fix 3) — seeds row with NULL `actual_entry_time`; asserts the row is filtered by SQL; asserts no `TypeError: 'NoneType' object is not subscriptable` from `None[:10]`.
- `test_resolve_returns_for_gate_returns_empty_when_all_undated` — seeds rows with NULL `actual_entry_time`; asserts `_resolve_returns_for_gate` returns `([], [], [])`; asserts `run_promotion_gate_for_version` skips gate gracefully.
- `test_promotion_gate_called_with_dates_and_directions` — patches `promotion_gate`; asserts call signature includes `dates` + `directions` kwargs (trainer.py path).
- `test_rf_placeholder_subtraction_removed` — locks the pre-subtraction at 975-976 is gone (raw `pnl_pct/100` is what's returned).
- `test_kpi_compute_promotion_gate_passes_dates_and_directions` — locks the kpis_compute.py:376 fix.
- `test_directions_default_long_for_long_only_system` — asserts directions list is all +1.
- **`test_trainer_promotion_gate_currently_cannot_promote_long_only`** (Choice A regression-lock) — feeds healthy returns through `run_promotion_gate_for_version`; asserts `result['decision'] in {'reject', 'defer'}`; asserts MC-perm vote in evidence is `passed=False, value≈1.0`. Locks the documented degeneracy from spec §1.3.1 to prevent a future contributor from "fixing" it without understanding the structural constraint.
- **`test_cmd_run_promotion_gate_post_fix_behavior`** (DA major fix 6) — runs CLI `cmd_run_promotion_gate` end-to-end on synthetic returns; asserts deterministic FAIL outcome from Choice A.
- **`test_cmd_run_promotion_gate_passes_dates_directions`** (DA major fix 6) — patches `promotion_gate`; asserts kwargs flow through from `cmd_run_promotion_gate` → `run_promotion_gate_for_version` → trainer.py:1039.

**Required verification step** (Minor 3): Before claiming completion, run `python -m pytest tests/training/ tests/api/test_kpis.py tests/methods/ -v` and confirm pass count is unchanged or all failures are documented in the strict-rigor receipt. Disclose any modifications needed to existing tests.

**Scope fence**:
- Do NOT add gate-firing logic to trainer.py (T4 owns watch.py firing).
- Do NOT call `run_daily_gate_for_all_active_strategies` from trainer.
- Do NOT touch methodology-gate semantics in any way — input-quality fix only.
- Do NOT modify `methods/promotion_gate.py`.
- Do NOT modify `methods/promotion_gate_helpers.py`.
- Do NOT modify `methods/mc_permutation.py` (the long-only degeneracy is intentional documentation per Choice A — fixing it is a future-sprint structural concern).
- Do NOT modify `analytics/instrumentation_filter.py`.
- Do NOT add `candidate_pool` wiring (separate concern; White RC will continue to abstain at the kpi_compute call site until that follow-up).
- Do NOT touch `src/api/cloud_routes/kpis.py` beyond the minimum kwarg-passing required at line 91.
- Do NOT modify `src/cli/commands.py` (fix is transitive via trainer.py; T3 only adds regression tests at this callsite).
- Do NOT change `directions` semantics from `[+1]*N` for long-only (the encoding is semantically honest per `registry.py:202`).

---

### T4 — Wire daily 16:35 ET gate firing into watch.py

**Complexity**: medium

**Depends on**: T2

**Files in scope**: `src/scheduler/watch.py`, `tests/test_watch_strategy_gate.py`

**Files read-only**: `src/platform/promotion.py`

**Description**: In src/scheduler/watch.py: (a) Add `self._strategy_gate_done = False` to `__init__` at line 258 (immediately after `self._postclose_reconcile_done = False`). (b) Add `self._strategy_gate_done = False` to `_reset_daily_state` at line 365. (c) Insert a new daily-loop block IMMEDIATELY AFTER the post-close-reconcile block ending at line 1623, with the slot guard `if (hour == 16 and now.minute >= 35 and not self._strategy_gate_done)`. The block late-imports `from src.platform.promotion import run_daily_gate_for_all_active_strategies` inside the method body to avoid circular imports, then wraps the call in `self._safe_run(...)` per existing convention (set the done-flag only on success). (d) Add `self._notify_gate_proposal(strategy_id, evidence)` helper for digest emission (stub OK — log + Telegram-friendly format).

**Test strategy**: test_watch_loop_fires_at_16_35_ET, test_watch_loop_idempotent_within_day, test_watch_loop_resets_flag_at_day_roll, test_late_import_avoids_circular.

**Scope fence**: Do NOT modify any other watch-loop slot. Do NOT change post-close-reconcile semantics. Do NOT eagerly import platform.promotion at module top. Do NOT add operator-CLI logic.

---

### T5 — Add CLI confirm-promotion command (thin wrapper around promote())

**Complexity**: medium

**Depends on**: T2

**Files in scope**: `src/cli/promotion_cmd.py`, `src/main.py`, `tests/test_cli_confirm_promotion.py`

**Files read-only**: `src/platform/promotion.py`

**Description**: Add a new CLI command `confirm-promotion --strategy <id> --justification "..." [--target-status live] [--yes]`. The command MUST be a thin front-end that delegates to `platform.promotion.promote(triggered_by='operator_confirm', ...)`. NO synthetic-outcome path. Steps in order: (1) validate `len(args.justification.strip()) >= 40` client-side; (2) load latest `triggered_by='gate_proposal'` row; reject if missing or older than 24h; (3) display proposal evidence and prompt y/N (unless --yes); (4) call `promote(strategy_id, target_status, triggered_by='operator_confirm', justification_note=args.justification)`; (5) handle promote()'s server-side re-fire rejection (exit non-zero with reason); (6) print event_id on success.

**Ordering ratchet (Minor 1)**: T5 cannot merge until T2 has merged (already implicit via dependency graph; documented here for clarity). The methodology gate AND-composition only fires once T2 is in main; T5's call to `promote()` → `check_promotion_gate()` will not gate-block on methodology grounds before then.

**Test strategy**: test_operator_confirm_calls_promote_not_synthetic_outcome, test_reject_outcome_not_overridable_via_cli, test_operator_confirm_row_has_real_transition, test_stale_proposal_rejected_by_cli, test_promote_re_fires_gate_server_side, test_short_justification_rejected_client_side, **test_cli_confirm_promotion_re_fire_includes_methodology_gate** (Minor 1: mocks `promote()`, asserts methodology gate is in the re-fire call graph). Mock platform.promotion.promote to assert exact call signature.

**Scope fence**: Do NOT bypass `promote()`. Do NOT call `_apply_gate_outcome` with a synthetic outcome. Do NOT write `strategy_promotion_events` rows directly from the CLI. Do NOT modify `promote()` itself. Do NOT add an override-reject CLI path (Decision 4: reject is not overridable).

---

### T6 — Add KPI compute for daily gate proposals

**Complexity**: low

**Depends on**: T2

**Files in scope**: `src/analytics/kpis_compute.py`, `tests/test_kpis_compute_gate.py`

**Files read-only**: `src/platform/promotion.py`, `src/schema/registry.py`

**Description**: Extend the existing KPI compute pipeline (`src/analytics/kpis_compute.py` or equivalent — Documentarian to confirm exact filename) to surface counts of gate proposals by decision (promote/reject/defer) over the last 1d/7d/30d windows. Read from `strategy_promotion_events` filtered by `triggered_by='gate_proposal'`. Pure read-side aggregation.

**Test strategy**: Seed 5 gate_proposal rows across decisions and time windows; assert KPI compute returns correct counts. Test that `triggered_by='operator_confirm'` rows are EXCLUDED from gate-proposal counts.

**Scope fence**: Do NOT add new KPI categories beyond gate-decision counts. Do NOT modify dashboard frontend. Do NOT write to the database. Do NOT touch `src/api/cloud_routes/kpis_compute.py` (different module — the latter is the cloud read-API aggregator already updated by T3).

---

### T7 — Surface gate-proposal KPI in dashboard read API

**Complexity**: low

**Depends on**: T6

**Files in scope**: `src/api/dashboard_routes.py`, `tests/test_dashboard_gate_kpi_route.py`

**Files read-only**: `src/analytics/kpis_compute.py`

**Description**: Wire the new gate-proposal KPI into the existing dashboard read API (FastAPI route — exact path per Documentarian). Pure read-side endpoint addition. JSON response schema. NO frontend changes.

**Test strategy**: Integration test: hit the new route, assert 200, assert response shape matches schema, assert counts come from kpis_compute.

**Scope fence**: Do NOT modify the React frontend. Do NOT change auth/permission logic. Do NOT add write endpoints.

---

### T8 — Cross-cutting integration tests (locks all critical+major safety properties)

**Complexity**: medium

**Depends on**: T2, T4, T5

**Files in scope**: `tests/test_methodology_gate_integration.py`

**Files read-only**: `src/platform/promotion.py`, `src/scheduler/watch.py`, `src/cli/promotion_cmd.py`, `src/methods/promotion_gate.py`

**Description**: Author the named integration tests from spec §6 that span multiple modules and lock the critical+major safety properties. Each test name corresponds 1:1 to a critical+major fix.

The 9 mandatory integration tests:
- `test_operator_confirm_calls_promote_not_synthetic_outcome`
- `test_reject_outcome_not_overridable_via_cli`
- `test_and_composition_with_walkforward_blocks_methodology_only_pass`
- `test_methodology_gate_and_composed_at_walkforward_pass_path` (DA major fix 1)
- `test_partial_instrumentation_excluded_from_gate_input`
- `test_empty_candidate_pool_uses_4_of_4_fallback_with_threshold_key`
- `test_feature_flag_disabled_short_circuits_persistence`
- `test_gate_proposal_row_has_from_status_eq_to_status`
- `test_operator_confirm_row_has_real_transition`

Plus the cross-cutting locks added in v5:
- `test_methodology_gate_evidence_schema_matches_decide_function` (DA major fix 2 — vote schema)
- `test_production_gate_methodology_compose_with_dsr_only` (DA major fix 5 — production asymmetry)
- `test_walkforward_status_populated_for_all_four_states` (DA major fix 4)
- `test_walkforward_outcome_state_still_populated_for_backwards_compat` (DA major fix 4)
- `test_cli_confirm_promotion_re_fire_includes_methodology_gate` (Minor 1 — ordering ratchet)
- `test_trainer_promotion_gate_currently_cannot_promote_long_only` (Choice A regression-lock)

**Test strategy**: Each test exercises the full integration path (DB → gate → persistence → CLI re-fire). Use sqlite :memory: with schema-registry init; freeze time for stable test_partial_instrumentation_excluded test. Run `python -m pytest tests/test_methodology_gate_integration.py -v` and confirm all named tests appear in collection output verbatim.

**Scope fence**: Do NOT modify production code in this task — tests only.

---

### T9 — Operator runbook update + CHANGELOG

**Complexity**: low

**Depends on**: T5, T8

**Files in scope**: `docs/operator-guide.md`, `CHANGELOG.md`

**Files read-only**: `src/platform/promotion.py`, `src/cli/promotion_cmd.py`

**Description**: Add a 'Daily methodology-gate workflow' section to docs/operator-guide.md covering:
(a) what the daily 16:35 ET sweep does
(b) how to read the digest
(c) how to interpret evidence JSON (decision, threshold_used, votes per spec §3.2 schema, instrumentation_excluded_count, walkforward_status, n_pass/n_fail/n_abstentions in details)
(d) running `confirm-promotion` end-to-end
(e) troubleshooting defer outcomes
(f) bootstrap-window `walkforward_status='no_data_yet'` and `scripts/smoke_gate_9_fold1.bat`
(g) feature-flag and STRICT_GATE env-var matrix from spec §9.1
(h) **Sprint 2 limitations from spec §1.3.1** — trainer/kpi call paths cannot reach `decision='promote'` due to long-only directions degeneracy in MC permutation; operator should NOT misread `decision='reject'` from those paths as a methodology problem; instead look at the watch.py daily orchestrator's evidence (which has candidate_pool wired).
(i) **Production-gate asymmetry from spec §1.2** — production target only AND-composes methodology with DSR (PBO/walkforward are Sprint-4 placeholders); shadow_trading target AND-composes methodology with walkforward+DSR+PBO. Different transitions enforce different preconditions.

Update CHANGELOG.md under [Unreleased].

**Test strategy**: No automated tests. Manual review checklist: (1) all CLI flags documented, (2) all env-var names match implementation, (3) 2x2 grid from spec §9.1 reproduced, (4) bootstrap-window `walkforward_status='no_data_yet'` documented, (5) Sprint 2 limitations from §1.3.1 documented, (6) production-gate asymmetry from §1.2 documented, (7) CHANGELOG entry references all PRs in this sprint.

**Scope fence**: Do NOT modify production code. Do NOT add docstrings to source files. Do NOT update test count baseline in CLAUDE.md unless explicitly told to.

---
