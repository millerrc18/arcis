# Methodology Gate Wiring — Implementation Plan

**Source spec**: `docs/audits/2026-05-05-methodology-gate-wiring/spec.md` (v3)

## Execution order (parallel batches)

**Batch 1**: T1, T3

**Batch 2**: T2

**Batch 3**: T4, T5, T6

**Batch 4**: T7, T8

**Batch 5**: T9


## Notes

Task 1 (registry doc-string update) and Task 3 (trainer abstention bug fix, isolated) are independent — run in parallel as wave 1. Task 2 is the primary integration point (Critical 2 fix) and gates everything downstream. Wave 3 (Tasks 4, 5, 6) can run in parallel: watch.py firing, CLI, KPI compute — they all consume task 2's surface but don't conflict. Wave 4 (Tasks 7, 8): dashboard route depends on KPI; integration tests depend on the full stack. Task 9 (docs) closes the sprint. Worktree isolation MANDATORY for waves 1, 3, and 4 (parallel agents per CLAUDE.md). Each agent must run `python -m pytest tests/test_repo_structure.py -v` and disclose violations in its strict-rigor receipt. Test count baseline (3682) bumps after T8 completes — recompute and update CLAUDE.md as part of T9.

## Tasks

### T1 — Update triggered_by ColumnDef description for new sentinels

**Complexity**: low

**Files in scope**: `src/schema/registry.py`, `tests/test_schema.py`

**Files read-only**: `src/platform/promotion.py`

**Description**: Modify the ColumnDef description string at src/schema/registry.py:2113-2114 to document the two new sentinel values 'gate_proposal' and 'operator_confirm'. Description-string-only change. NO schema migration. NO new tables. NO new columns. The existing `strategy_promotion_events` table absorbs all new persistence via these sentinel values + JSON keys inside `gate_result_json`.

**Test strategy**: Add a regression test asserting the ColumnDef description string contains all four sentinel values ('manual', 'auto_gate', 'gate_proposal', 'operator_confirm'). Run `python -m src.main validate-schema` and confirm no drift detected.

**Scope fence**: Do NOT add new tables. Do NOT add new columns. Do NOT modify any other ColumnDef. Do NOT change `gate_result_json` ColumnDef. Do NOT touch promotion.py or watch.py — those are downstream tasks.

---

### T2 — Wire methodology gate into platform.promotion (AND-compose)

**Complexity**: high

**Depends on**: T1

**Files in scope**: `src/platform/promotion.py`, `tests/test_promotion_methodology_gate.py`

**Files read-only**: `src/methods/promotion_gate.py`, `src/analytics/instrumentation_filter.py`, `src/schema/registry.py`

**Description**: Primary integration task. In src/platform/promotion.py: (a) add `_evaluate_strategy_methodology_gate(strategy_id, db_path) -> tuple[bool, dict]` helper that loads shadow_trades, applies `analytics.instrumentation_filter.is_fully_instrumented`, builds MethodInputs, calls `methods.promotion_gate.promotion_gate(...)`, and returns (passes_bool, evidence_dict). (b) AND-compose into `_evaluate_shadow_trading_gate` (line 246) and `_evaluate_production_gate` (line 318) at existing return points: `mg_passes, mg_evidence = _evaluate_strategy_methodology_gate(...); evidence['methodology_gate'] = mg_evidence; return (passes and mg_passes), evidence`. (c) Add top-level `run_daily_gate_for_all_active_strategies(db_path, notify=None) -> list[dict]` that iterates `get_strategies_by_status(['shadow_trading','backtested'])`, persists a `triggered_by='gate_proposal'` row per strategy with from_status==to_status, and invokes notify on PASS. (d) Honor `METHODOLOGY_GATE_ENABLED` feature flag — short-circuit to True with no persistence when false. (e) `threshold_used` key included in evidence (passes through from `promotion_gate()`).

**Test strategy**: Tests (named per spec §6): test_helper_aggregates_shadow_trades_correctly, test_partial_instrumentation_excluded_from_gate_input, test_empty_candidate_pool_uses_4_of_4_fallback_with_threshold_key, test_feature_flag_disabled_short_circuits_persistence, test_and_composition_with_walkforward_blocks_methodology_only_pass, test_gate_proposal_row_has_from_status_eq_to_status, test_run_daily_iterates_active_strategies_only.

**Scope fence**: Do NOT modify methods/promotion_gate.py (the 4-of-5 voter is unchanged). Do NOT modify analytics/instrumentation_filter.py. Do NOT touch trainer.py, watch.py, or any CLI module — those are downstream tasks. Do NOT add new tables. Do NOT change any existing ColumnDef. Do NOT modify the `promote()` function itself — only add helpers and call sites that compose with it.

---

### T3 — Fix trainer model-version abstention bug (bug-fix-only)

**Complexity**: low

**Files in scope**: `src/training/trainer.py`, `tests/test_trainer_abstention_bug.py`

**Files read-only**: `src/platform/promotion.py`, `src/methods/promotion_gate.py`

**Description**: Pre-existing bug in trainer.py: the model-version-gating abstention check returns True when the model-version field is None, causing false-positive abstentions consumed by the methodology gate's MinTRL/instrumentation pipeline. Fix the None-handling so a missing model-version explicitly returns False (or raises, depending on existing convention). This task is INPUT-quality only — trainer.py is NOT a gate-firing site under any condition in this design. Scope-fenced strictly to that single fix.

**Test strategy**: Regression test: construct a trainer cycle with model_version=None; assert abstention check returns False (or raises, matching existing convention); assert the regression test fails on pre-fix code and passes after.

**Scope fence**: Do NOT add gate-firing logic to trainer.py. Do NOT call `run_daily_gate_for_all_active_strategies` from trainer. Do NOT add gate-related imports beyond what's needed for the bug fix. Do NOT touch methodology-gate semantics in any way — this is a trainer-internal abstention bug.

---

### T4 — Wire daily 16:35 ET gate firing into watch.py

**Complexity**: medium

**Depends on**: T2

**Files in scope**: `src/scheduler/watch.py`, `tests/test_watch_strategy_gate.py`

**Files read-only**: `src/platform/promotion.py`

**Description**: In src/scheduler/watch.py: (a) Add `self._strategy_gate_done = False` to `__init__` at line 258 (immediately after `self._postclose_reconcile_done = False`). (b) Add `self._strategy_gate_done = False` to `_reset_daily_state` at line 365 (alongside the existing reset of `_postclose_reconcile_done`). (c) Insert a new daily-loop block IMMEDIATELY AFTER the post-close-reconcile block ending at line 1623, with the slot guard `if (hour == 16 and now.minute >= 35 and not self._strategy_gate_done)`. The block late-imports `from src.platform.promotion import run_daily_gate_for_all_active_strategies` inside the method body to avoid circular imports, then wraps the call in `self._safe_run(...)` per existing convention (set the done-flag only on success). (d) Add `self._notify_gate_proposal(strategy_id, evidence)` helper for digest emission (stub OK — the notification UI is out of scope; just log + Telegram-friendly format).

**Test strategy**: Tests: test_watch_loop_fires_at_16_35_ET, test_watch_loop_idempotent_within_day, test_watch_loop_resets_flag_at_day_roll, test_late_import_avoids_circular. Use existing watch-loop test fixtures with frozen-time helpers.

**Scope fence**: Do NOT modify any other watch-loop slot. Do NOT change post-close-reconcile semantics. Do NOT eagerly import platform.promotion at module top — must be late-imported inside the method body. Do NOT add operator-CLI logic — that is Task 5.

---

### T5 — Add CLI confirm-promotion command (thin wrapper around promote())

**Complexity**: medium

**Depends on**: T2

**Files in scope**: `src/cli/promotion_cmd.py`, `src/main.py`, `tests/test_cli_confirm_promotion.py`

**Files read-only**: `src/platform/promotion.py`

**Description**: Add a new CLI command `confirm-promotion --strategy <id> --justification "..." [--target-status live] [--yes]`. The command MUST be a thin front-end that delegates to `platform.promotion.promote(triggered_by='operator_confirm', ...)`. NO synthetic-outcome path. Steps in order: (1) validate `len(args.justification.strip()) >= 40` client-side; (2) load latest `triggered_by='gate_proposal'` row for the strategy; reject if missing or older than 24h; (3) display proposal evidence to operator and prompt y/N (unless --yes); (4) call `promote(strategy_id, target_status, triggered_by='operator_confirm', justification_note=args.justification)`; (5) handle the case where promote()'s server-side re-fire of `check_promotion_gate` rejects (exit non-zero with reason); (6) print event_id on success.

**Test strategy**: Tests (named per spec §6): test_operator_confirm_calls_promote_not_synthetic_outcome, test_reject_outcome_not_overridable_via_cli, test_operator_confirm_row_has_real_transition, test_stale_proposal_rejected_by_cli, test_promote_re_fires_gate_server_side, test_short_justification_rejected_client_side. Mock platform.promotion.promote to assert exact call signature.

**Scope fence**: Do NOT bypass `promote()`. Do NOT call `_apply_gate_outcome` with a synthetic outcome. Do NOT write `strategy_promotion_events` rows directly from the CLI — only `promote()` writes audit rows. Do NOT modify `promote()` itself. Do NOT add an override-reject CLI path (Decision 4: reject is not overridable).

---

### T6 — Add KPI compute for daily gate proposals

**Complexity**: low

**Depends on**: T2

**Files in scope**: `src/analytics/kpis_compute.py`, `tests/test_kpis_compute_gate.py`

**Files read-only**: `src/platform/promotion.py`, `src/schema/registry.py`

**Description**: Extend the existing KPI compute pipeline (`src/analytics/kpis_compute.py` or equivalent — Documentarian to confirm exact filename) to surface counts of gate proposals by decision (promote/reject/defer) over the last 1d/7d/30d windows. Read from `strategy_promotion_events` filtered by `triggered_by='gate_proposal'`. Pure read-side aggregation — NO writes to the table.

**Test strategy**: Test: seed 5 gate_proposal rows across decisions and time windows; assert KPI compute returns correct counts. Test that `triggered_by='operator_confirm'` rows are EXCLUDED from gate-proposal counts.

**Scope fence**: Do NOT add new KPI categories beyond gate-decision counts. Do NOT modify the dashboard frontend (out of scope per spec §1.4). Do NOT write to the database.

---

### T7 — Surface gate-proposal KPI in dashboard read API

**Complexity**: low

**Depends on**: T6

**Files in scope**: `src/api/dashboard_routes.py`, `tests/test_dashboard_gate_kpi_route.py`

**Files read-only**: `src/analytics/kpis_compute.py`

**Description**: Wire the new gate-proposal KPI into the existing dashboard read API (FastAPI route handler — exact path per Documentarian). Pure read-side endpoint addition. Add JSON response schema. NO frontend changes.

**Test strategy**: Integration test: hit the new route, assert 200, assert response shape matches schema, assert counts come from kpis_compute.

**Scope fence**: Do NOT modify the React frontend. Do NOT change auth/permission logic. Do NOT add write endpoints — gate proposals are written only by the daily watch.py firing.

---

### T8 — Cross-cutting integration tests (locks all 8 critical+major safety properties)

**Complexity**: medium

**Depends on**: T2, T4, T5

**Files in scope**: `tests/test_methodology_gate_integration.py`

**Files read-only**: `src/platform/promotion.py`, `src/scheduler/watch.py`, `src/cli/promotion_cmd.py`, `src/methods/promotion_gate.py`

**Description**: Author the named integration tests from spec §6 that span multiple modules and lock the critical safety properties. Each test name corresponds 1:1 to a critical+major fix in v3 review. The 8 mandatory tests: test_operator_confirm_calls_promote_not_synthetic_outcome, test_reject_outcome_not_overridable_via_cli, test_and_composition_with_walkforward_blocks_methodology_only_pass, test_partial_instrumentation_excluded_from_gate_input, test_empty_candidate_pool_uses_4_of_4_fallback_with_threshold_key, test_feature_flag_disabled_short_circuits_persistence, test_gate_proposal_row_has_from_status_eq_to_status, test_operator_confirm_row_has_real_transition. Some of these may already be covered by Tasks 2/4/5 unit tests; this task ensures end-to-end coverage and that the test names appear verbatim somewhere in the test suite (so future audits can grep for them).

**Test strategy**: Each test exercises the full integration path (DB → gate → persistence → CLI re-fire). Use sqlite :memory: with schema-registry init; freeze time for stable test_partial_instrumentation_excluded test. Run `python -m pytest tests/test_methodology_gate_integration.py -v` and confirm all 8 named tests appear in collection output verbatim.

**Scope fence**: Do NOT modify production code in this task — tests only. If an integration test reveals a bug, file a follow-up task; do not patch the bug inside this task without re-routing through the appropriate scope.

---

### T9 — Operator runbook update + CHANGELOG

**Complexity**: low

**Depends on**: T5, T8

**Files in scope**: `docs/operator-guide.md`, `CHANGELOG.md`

**Files read-only**: `src/platform/promotion.py`, `src/cli/promotion_cmd.py`

**Description**: Add a 'Daily methodology-gate workflow' section to docs/operator-guide.md covering: (a) what the daily 16:35 ET sweep does, (b) how to read the digest notification, (c) how to interpret evidence JSON (decision, threshold_used, votes, instrumentation_excluded_count), (d) running `confirm-promotion` end-to-end, (e) troubleshooting defer outcomes, (f) feature-flag and STRICT_GATE env-var matrix from spec §9. Update CHANGELOG.md under [Unreleased] per CLAUDE.md rule.

**Test strategy**: No automated tests — documentation. Manual review checklist: (1) all CLI flags documented match implementation, (2) all env-var names match implementation, (3) 2x2 grid from spec §9.1 reproduced accurately, (4) CHANGELOG entry references all PRs in this sprint.

**Scope fence**: Do NOT modify production code. Do NOT add docstrings to source files (those are part of their owning tasks). Do NOT update test count baseline in CLAUDE.md unless explicitly told to — that's a separate sprint-completion step.

---

