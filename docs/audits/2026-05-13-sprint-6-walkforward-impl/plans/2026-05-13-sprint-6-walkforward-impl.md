# Sprint 6 Walkforward Implementation Plan

## Companion spec

[Sprint 6 design spec](../specs/2026-05-13-sprint-6-walkforward-impl-design.md)

## Provenance

This plan inherits v1 plan T1-T12 verbatim (binding starting point) and adds T13/T14/T15 per Sprint 6 design decisions. Post-Feasibility (v1.1) patches applied inline to T4 / T13 / T15. See spec §"Feasibility Resolutions" for per-finding traceability.

## Task graph (JSON form)

```json
{
  "tasks": [
    {
      "id": 1,
      "name": "T1 \u2014 Feature-flag sentinel wiring + config-key registration",
      "description": "Per walkforward-plan-v1.md T1 (binding). Implements spec \u00a7Operational Notes sentinel decision. Adds WALKFORWARD_GATE_ENABLED as a named config key that _evaluate_walkforward_gate in src/platform/promotion.py reads before executing the gate. When flag resolves false, gate short-circuits and returns (None, evidence) with walkforward_status='disabled' \u2014 identical to no-row-found fallback. Reads via os.environ.get('WALKFORWARD_GATE_ENABLED', 'true').lower() == 'true'. Follows the METHODOLOGY_GATE_ENABLED sentinel pattern at promotion.py line 286.",
      "files_in_scope": [
        "src/platform/promotion.py",
        "tests/platform/test_promotion.py"
      ],
      "files_read_only": [
        "src/platform/rigor/walkforward_config.py",
        "src/platform/rigor/walkforward_runner.py",
        "src/schema/registry.py",
        "docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md"
      ],
      "depends_on": [],
      "test_strategy": "Add 3 tests to tests/platform/test_promotion.py: test_walkforward_gate_disabled_bypasses_check (patches env false, asserts (None, evidence)), test_walkforward_gate_enabled_by_default (no env patch), test_walkforward_gate_enabled_true_explicit (env=true). All use unittest.mock.patch over sqlite3 \u2014 no live DB.",
      "scope_fence": "Do NOT change other gate functions in promotion.py. Do NOT add new YAML config keys. Do NOT modify walkforward_runner.py or walkforward_config.py. Do NOT exceed +20 lines in promotion.py and +30 lines in test_promotion.py.",
      "estimated_complexity": "low"
    },
    {
      "id": 2,
      "name": "T2 \u2014 Trading-day arithmetic migration (evaluation/walkforward.py)",
      "description": "Per walkforward-plan-v1.md T2 (binding). Replaces local _subtract_trading_days helper (lines 66-74) in src/evaluation/walkforward.py with src.scheduler.holidays.subtract_trading_days. Pure behavior-preserving refactor \u2014 both use pandas_market_calendars NYSE calendar. Updates _compute_embargo_end and compute_fold_boundaries call sites; deletes the dead local function.",
      "files_in_scope": [
        "src/evaluation/walkforward.py",
        "tests/evaluation/test_walkforward.py"
      ],
      "files_read_only": [
        "src/scheduler/holidays.py",
        "config/known_violations.json",
        "docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md"
      ],
      "depends_on": [],
      "test_strategy": "Add 2 tests to tests/evaluation/test_walkforward.py: test_fold_boundaries_use_canonical_trading_days (regression-lock against subtract_trading_days output), test_no_local_subtract_trading_days (AST/grep structural assertion).",
      "scope_fence": "Do NOT change _run_fold, compute_aggregate, run_walkforward logic. Do NOT modify src/platform/rigor/walkforward*.py. Net change \u226430 lines.",
      "estimated_complexity": "low"
    },
    {
      "id": 3,
      "name": "T3 \u2014 Excess-Sharpe alignment for per-window gate",
      "description": "Per walkforward-plan-v1.md T3 (binding). Implements SP-WF-004. Adds excess_sharpe_min: float | None = None field to WalkForwardConfig (additive, default None preserves backward compat). Wires the field into compute_window_metrics in walkforward_metrics.py as an additional check branch. Default None = use existing raw Sharpe threshold only.",
      "files_in_scope": [
        "src/platform/rigor/walkforward_config.py",
        "src/platform/rigor/walkforward_metrics.py",
        "tests/platform/rigor/test_walkforward_metrics.py"
      ],
      "files_read_only": [
        "src/analytics/canonical_sharpe.py",
        "src/data_ingestion/risk_free_rate.py",
        "docs/methodology-toolkit.md",
        "docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md"
      ],
      "depends_on": [],
      "test_strategy": "Add 3 tests to test_walkforward_metrics.py: test_window_metrics_excess_sharpe_gate_pass (excess returns above threshold), test_window_metrics_excess_sharpe_gate_fail (below threshold, reason='excess_sharpe_below_min'), test_window_metrics_excess_sharpe_none_uses_raw (excess_sharpe_min=None unchanged behavior).",
      "scope_fence": "Do NOT change walkforward_runner.py, walkforward_outcome.py, walkforward_power.py. Do NOT change the 9 existing threshold constants. No schema changes.",
      "estimated_complexity": "low"
    },
    {
      "id": 4,
      "name": "T4 \u2014 Schema registry: new columns for v2 outcome fields",
      "description": "Per walkforward-plan-v1.md T4 (binding). Adds two optional columns to walkforward_results table in src/schema/registry.py: excess_sharpe_min_used REAL (records per-run threshold), gate_version TEXT DEFAULT 'v1' (records framework version). Both nullable with defaults to preserve existing inserts. ONLY modifies registry \u2014 T7 applies DDL via validate-schema --fix. Feasibility-fix (v1.1): also add `derived_from_backtest_id TEXT NULL` column to walkforward_results \u2014 needed by T13 reconciler SQL + SP-WF-016 falsifiability query 1. Column-additive, in scope per operator constraint (no NEW tables; columns are fine).",
      "files_in_scope": [
        "src/schema/registry.py",
        "tests/test_schema.py"
      ],
      "files_read_only": [
        "src/platform/rigor/walkforward_runner.py",
        "docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md"
      ],
      "depends_on": [],
      "test_strategy": "Add 2 structural tests to tests/test_schema.py: test_walkforward_results_has_excess_sharpe_min_used_column, test_walkforward_results_has_gate_version_column. Both import TABLES from registry and assert ColumnDef presence.",
      "scope_fence": "Do NOT write CREATE TABLE or ALTER TABLE outside registry \u2014 CLAUDE.md mandatory. Do NOT modify walkforward_runner.py (T8 owns). Do NOT run validate-schema --fix (T7 owns). +15 lines registry, +20 lines test_schema.",
      "estimated_complexity": "low"
    },
    {
      "id": 5,
      "name": "T5 \u2014 Window-shift math + corpus gate",
      "description": "Per walkforward-plan-v1.md T5 (binding). Implements SP-WF-001 / SP-WF-006 generator path. Adds WalkForwardWindowBuilder utility function to walkforward_config.py that generates DEFAULT_WINDOWS-compatible sequences using subtract_trading_days. DEFAULT_WINDOWS tuple stays as canonical default for backward compat. Also adds corpus_id: str | None = None field to WalkForwardConfig \u2014 when set, runner (T8) will call _gate_corpus_or_raise.",
      "files_in_scope": [
        "src/platform/rigor/walkforward_config.py",
        "tests/platform/rigor/test_walkforward_config.py"
      ],
      "files_read_only": [
        "src/scheduler/holidays.py",
        "src/evaluation/walkforward.py",
        "docs/audits/2026-05-11-stage1-completion/walkforward-prior-art.md",
        "docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md"
      ],
      "depends_on": [],
      "test_strategy": "Add 4 tests to test_walkforward_config.py: test_window_builder_generates_no_overlap (train_end < test_start invariant), test_window_builder_uses_canonical_trading_days (embargo match), test_config_accepts_corpus_id, test_config_corpus_id_none_is_default.",
      "scope_fence": "Do NOT modify DEFAULT_WINDOWS tuple. Do NOT modify walkforward_runner.py (T8 wires the corpus_id path). No schema changes. File stays under 400-line ceiling.",
      "estimated_complexity": "medium"
    },
    {
      "id": 6,
      "name": "T6 \u2014 VIX regime coverage validator",
      "description": "Per walkforward-plan-v1.md T6 (binding). Adds validate_vix_tier_coverage(trades, min_tiers) function to src/platform/rigor/walkforward_power.py returning a VixCoverageResult(distinct_tiers, passes, missing_tiers). Existing distinct_tier_count in walkforward_metrics.py is the structural predecessor \u2014 this task adds the pass/fail wrapper + missing_tiers diagnostic for structured failure evidence in walkforward_results.vix_tier_coverage.",
      "files_in_scope": [
        "src/platform/rigor/walkforward_power.py",
        "tests/platform/rigor/test_walkforward_power.py"
      ],
      "files_read_only": [
        "src/platform/rigor/walkforward_metrics.py",
        "src/platform/rigor/walkforward_config.py",
        "docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md"
      ],
      "depends_on": [],
      "test_strategy": "Add 4 tests to test_walkforward_power.py: test_vix_coverage_all_tiers (3 tiers \u2192 passes=True), test_vix_coverage_missing_high (no >25 \u2192 passes depends on min_tiers), test_vix_coverage_single_tier_fails, test_vix_coverage_empty_trades_fails.",
      "scope_fence": "Do NOT modify walkforward_metrics.py, walkforward_outcome.py, walkforward_universe.py. The distinct_tier_count function is NOT replaced \u2014 this task adds a wrapper layer only. No schema changes.",
      "estimated_complexity": "low"
    },
    {
      "id": 7,
      "name": "T7 \u2014 Schema migration + validate-schema --fix verification",
      "description": "Per walkforward-plan-v1.md T7 (binding). Runs python -m src.main validate-schema --fix after T4 lands, materializing the two new columns into SQLite. Runs python scripts/render_migrate.py if DATABASE_URL configured (guarded by env-var check). Verifies schema round-trips with post-fix validate-schema returning zero drift. Infrastructure-only \u2014 no Python source changes.",
      "files_in_scope": [],
      "files_read_only": [
        "src/schema/registry.py",
        "src/platform/rigor/walkforward_runner.py",
        "docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md"
      ],
      "depends_on": [
        4
      ],
      "test_strategy": "Structural verification: python -m src.main validate-schema zero drift after --fix. python -m pytest tests/test_schema.py -v passes including T4's new structural tests. No new pytest tests.",
      "scope_fence": "Do NOT add columns to registry (T4 owns). Do NOT modify walkforward_runner.py (T8 owns). Zero Python source-line changes.",
      "estimated_complexity": "low"
    },
    {
      "id": 8,
      "name": "T8 \u2014 Runner integration: wire T5/T6 outputs into walkforward_runner",
      "description": "Per walkforward-plan-v1.md T8 (binding). Updates src/platform/rigor/walkforward_runner.py to: (a) call WalkForwardWindowBuilder from T5 when config.windows is not explicit and window_count override is present; (b) call _gate_corpus_or_raise when config.corpus_id is set; (c) call validate_vix_tier_coverage from T6 and include VixCoverageResult in evidence; (d) populate excess_sharpe_min_used and gate_version='v2' when persisting (v2 for runs using T3 excess-Sharpe path). Update config/known_violations.json LOC waiver if needed.",
      "files_in_scope": [
        "src/platform/rigor/walkforward_runner.py",
        "tests/platform/rigor/test_walkforward_runner.py",
        "config/known_violations.json"
      ],
      "files_read_only": [
        "src/platform/rigor/walkforward_config.py",
        "src/platform/rigor/walkforward_power.py",
        "src/evaluation/walkforward.py",
        "src/schema/registry.py",
        "docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md"
      ],
      "depends_on": [
        3,
        5,
        6,
        7
      ],
      "test_strategy": "Add 4 tests to test_walkforward_runner.py: test_runner_calls_corpus_gate_when_corpus_id_set, test_runner_skips_corpus_gate_when_corpus_id_none, test_runner_persists_gate_version_v2_when_excess_sharpe_set, test_runner_persists_gate_version_v1_when_excess_sharpe_none.",
      "scope_fence": "Do NOT change walkforward_firewall.py, walkforward_purging.py, walkforward_costs.py, walkforward_universe.py, walkforward_outcome.py. Do NOT change promotion.py. No schema DDL. \u226455 net new lines.",
      "estimated_complexity": "medium"
    },
    {
      "id": 9,
      "name": "T9 \u2014 Promotion-gate sentinel guard",
      "description": "Per walkforward-plan-v1.md T9 (binding). Audits evaluate_promotion_gate in src/platform/promotion.py to confirm WALKFORWARD_GATE_ENABLED from T1 is correctly consulted. Adds a guard in evaluate_promotion_gate that short-circuits to the legacy gate path when the sentinel is false \u2014 preserves three-gate composition (methodology AND walkforward AND DSR) when enabled, falls through to legacy two-gate (methodology AND DSR) when disabled. Adds walkforward_gate_enabled key to returned evidence dict.",
      "files_in_scope": [
        "src/platform/promotion.py",
        "tests/platform/test_promotion.py"
      ],
      "files_read_only": [
        "src/platform/rigor/walkforward_config.py",
        "src/platform/rigor/walkforward_runner.py",
        "docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md"
      ],
      "depends_on": [
        1
      ],
      "test_strategy": "Add 3 tests to test_promotion.py: test_evaluate_promotion_gate_wf_disabled_skips_wf (patches sentinel false, asserts walkforward gate not queried), test_evaluate_promotion_gate_wf_enabled_calls_wf (sentinel true, mocked WF PASS row), test_evaluate_promotion_gate_evidence_carries_gate_enabled_flag.",
      "scope_fence": "Do NOT modify _evaluate_walkforward_gate (T1 owns). Do NOT modify methodology gate, DSR gate, or shadow_trading\u2192production gate (T14 owns). +15 lines max.",
      "estimated_complexity": "low"
    },
    {
      "id": 10,
      "name": "T10 \u2014 CLI + HTTP read-route updates",
      "description": "Per walkforward-plan-v1.md T10 (binding). Adds --corpus-id and --excess-sharpe-min argparse flags to scripts/backtest/run_walkforward.py (both optional, pass through to WalkForwardConfig). Extends src/api/cloud_routes/walkforward.py read-route response to include gate_version and excess_sharpe_min_used from walkforward_results row. No new routes, no method changes.",
      "files_in_scope": [
        "scripts/backtest/run_walkforward.py",
        "src/api/cloud_routes/walkforward.py",
        "tests/scripts/test_run_walkforward_cli.py",
        "tests/api/test_walkforward_route.py"
      ],
      "files_read_only": [
        "src/platform/rigor/walkforward_config.py",
        "src/platform/rigor/walkforward_runner.py",
        "src/schema/registry.py",
        "docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md"
      ],
      "depends_on": [
        5,
        7,
        8
      ],
      "test_strategy": "New tests/scripts/test_run_walkforward_cli.py (\u226440 lines): test_cli_corpus_id_flag_accepted, test_cli_excess_sharpe_min_flag_accepted. test_walkforward_route_includes_gate_version (mocked DB row).",
      "scope_fence": "Do NOT add new HTTP routes. Do NOT change runner, config, or promotion gate. No schema changes. CLI flags added in T13 (--backtest-result-id, --auto-fire) are T13's scope, NOT T10's.",
      "estimated_complexity": "low"
    },
    {
      "id": 11,
      "name": "T11 \u2014 Regression-lock test suite",
      "description": "Per walkforward-plan-v1.md T11 (binding). New tests/platform/rigor/test_walkforward_regression_lock.py exercising the full R1-R8 v1 framework end-to-end with hermetic synthetic fixtures (no DB, no network). Three fixtures: PASS path (Sharpe \u2248 0.4, 15 trades per window, deterministic seed=42), FAIL path (<0.3 Sharpe in \u22652 windows), INCONCLUSIVE path (\u22652 windows <10 trades). Locks three-state outcome state machine against regression.",
      "files_in_scope": [
        "tests/platform/rigor/test_walkforward_regression_lock.py"
      ],
      "files_read_only": [
        "src/platform/rigor/walkforward_config.py",
        "src/platform/rigor/walkforward_outcome.py",
        "src/platform/rigor/walkforward_metrics.py",
        "src/platform/rigor/walkforward_power.py",
        "docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md"
      ],
      "depends_on": [
        3,
        5,
        6,
        8
      ],
      "test_strategy": "Four new tests in the new file: test_regression_lock_pass_outcome, test_regression_lock_fail_outcome, test_regression_lock_inconclusive_outcome, test_regression_lock_pooled_sharpe_stable (within 0.01 of expected \u2014 determinism lock). All deterministic via random.seed(42).",
      "scope_fence": "Do NOT modify src/ files. Do NOT add DB or network access. New test file \u226480 lines.",
      "estimated_complexity": "medium"
    },
    {
      "id": 12,
      "name": "T12 \u2014 Per-task CHANGELOG entries (FOLD INTO T15)",
      "description": "Per walkforward-plan-v1.md T12 \u2014 Sprint 6 splits this into per-task CHANGELOG entries (each PR adds an [Unreleased] entry per CLAUDE.md mandate) PLUS T15 aggregation. This task is now a marker that every T1-T11+T13+T14 PR must include a one-line CHANGELOG [Unreleased] entry. T15 (closeout) handles the operator-guide append and final aggregation. No separate PR for T12.",
      "files_in_scope": [
        "CHANGELOG.md"
      ],
      "files_read_only": [
        "docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md"
      ],
      "depends_on": [],
      "test_strategy": "Per CLAUDE.md mandate \u2014 every Sprint 6 PR must touch CHANGELOG.md [Unreleased] with at least one line. PM verifies during PR review. No new pytest tests for T12 itself.",
      "scope_fence": "T12 is a discipline marker, not a standalone PR. Operator-guide section append moves to T15 (closeout PR), where it joins the version bump + aggregate. No duplicate operator-guide writes per-task.",
      "estimated_complexity": "low"
    },
    {
      "id": 13,
      "name": "T13 \u2014 Scheduler auto-fire on backtest completion",
      "description": "NEW Sprint 6 task. Implements SP-WF-013. Adds (a) new file src/platform/walkforward_autofire.py (~120 LOC) with auto_fire_walkforward(strategy_id, backtest_result_id, db_path) helper that spawns a detached subprocess invocation of python -m scripts.backtest.run_walkforward with --backtest-result-id and --auto-fire flags; uses filelock at data/walkforward-{strategy_id}.lock for per-strategy concurrency; emits platform_events rows for spawn-failed / skipped-locked / giveup outcomes; never raises. (b) Hook in scripts/run_backtest.py:main() after persist_backtest_result() (line 94) to invoke the helper. (c) New method _run_walkforward_reconciler() in src/scheduler/watch.py (~80 LOC) invoked hourly during market hours via existing _safe_run/done-flag pattern (mirror _run_postclose_reconciliation at line 2176); scans backtest_results for orphan rows (no matching walkforward_results), calls auto_fire_walkforward for each; caps at 3 attempts per (strategy_id, code_git_sha) per 24h. (d) Add --backtest-result-id and --auto-fire flags to scripts/backtest/run_walkforward.py (additional to T10's flags). Behind WALKFORWARD_AUTOFIRE_ENABLED env (default true). Feasibility-fix (v1.1): (a) Add `filelock>=3.0,<4.0` to `requirements.txt` + CLAUDE.md `New Dependencies` section. (b) Implement `_resolve_corpus_id_for_strategy(strategy_id, db_path) -> str | None` helper in `src/platform/walkforward_autofire.py` \u2014 reads `strategy_registry.corpus_id` (or fallback `corpus_metadata` latest-per-strategy); on null, emit `event_type=walkforward_auto_fire_skipped_no_corpus` and return without spawning (corpus is REQUIRED per SP-WF-010). (c) Module docstring for `walkforward_autofire.py` MUST include `Config keys: WALKFORWARD_AUTOFIRE_ENABLED (env, default true).` line, mirroring `promotion.py:12` discipline. Env-read pattern matches `promotion.py:286`. (d) Reconciler registers via `src/scheduler/watch_handlers.py::ALL_HANDLERS` (5-tick schedule 1100/1200/1300/1400/1500 ET) \u2014 mirror hourly sentiment-refresh pattern at `watch.py:1673`, NOT once-daily `_run_postclose_reconciliation`. (e) Retry-cap SQL must use json_extract: `SELECT COUNT(*) FROM platform_events WHERE event_type LIKE 'walkforward_auto_fire_spawn_failed' AND json_extract(payload_json, '$.strategy_id') = ? AND json_extract(payload_json, '$.code_git_sha') = ? AND created_at > datetime('now', '-24 hours')`. Add `test_reconciler_caps_at_three_attempts` to test_strategy.",
      "files_in_scope": [
        "src/platform/walkforward_autofire.py",
        "scripts/run_backtest.py",
        "src/scheduler/watch.py",
        "scripts/backtest/run_walkforward.py"
      ],
      "files_read_only": [
        "src/platform/backtest_persist.py",
        "src/platform/promotion.py",
        "src/schema/registry.py",
        "docs/audits/2026-05-11-stage1-completion/walkforward-spec-v1.md"
      ],
      "depends_on": [
        8,
        9,
        10
      ],
      "test_strategy": "5 tests in new tests/platform/test_walkforward_autofire.py: test_auto_fire_spawns_child_process (mock Popen), test_auto_fire_emits_platform_event_on_spawn_failure, test_auto_fire_skips_when_locked, test_auto_fire_does_not_raise_on_any_failure, test_auto_fire_releases_lock_after_spawn. 3 tests in new tests/scheduler/test_walkforward_reconciler.py: test_reconciler_finds_orphan_backtest, test_reconciler_skips_paired_backtest, test_reconciler_caps_at_three_attempts. All hermetic \u2014 mock subprocess.Popen and sqlite3.",
      "scope_fence": "Do NOT modify _evaluate_walkforward_gate or _evaluate_shadow_trading_gate (T1/T9 own). Do NOT introduce a new event-bus abstraction \u2014 platform_events is the only audit trail. Do NOT modify walkforward_runner.py (T8 owns). Do NOT fire walkforward synchronously inside scripts/run_backtest.py \u2014 must spawn detached child. Backtest-persist failure must NEVER come from auto-fire \u2014 helper always returns cleanly.",
      "estimated_complexity": "high"
    },
    {
      "id": 14,
      "name": "T14 \u2014 Production-gate walkforward composition",
      "description": "NEW Sprint 6 task. Implements SP-WF-014. Extends _evaluate_production_gate at src/platform/promotion.py:506-525 to call _evaluate_walkforward_gate symmetrically with _evaluate_shadow_trading_gate. Closes the placeholder lines 519-520 (`evidence['pbo'] = None; evidence['oos_efficiency'] = None`). Composition: passes_dsr AND walkforward_pass AND methodology_pass. Honors WALKFORWARD_GATE_ENABLED sentinel from T9 (same sentinel, both gates). Stricter no-row policy: if walkforward gate returns (None, evidence), production gate returns False (NOT legacy fall-through). Evidence dict gains walkforward_outcome_state, walkforward_status, walkforward_reason, walkforward_run_id, walkforward_pooled_sharpe, walkforward_pooled_mde, walkforward_heavy_tail_flag \u2014 symmetric with shadow_trading. Line 519 (pbo=None) stays per spec scope-fence.",
      "files_in_scope": [
        "src/platform/promotion.py",
        "tests/platform/test_promotion.py"
      ],
      "files_read_only": [
        "src/platform/rigor/walkforward_runner.py",
        "src/schema/registry.py",
        "docs/audits/2026-05-11-stage1-completion/walkforward-spec-v1.md"
      ],
      "depends_on": [
        1,
        9
      ],
      "test_strategy": "5 tests added to tests/platform/test_promotion.py: test_production_gate_passes_with_walkforward_pass (mock WF PASS + DSR PASS + MG PASS), test_production_gate_fails_with_walkforward_fail, test_production_gate_fails_with_walkforward_inconclusive, test_production_gate_fails_when_no_walkforward_row (stricter than shadow_trading \u2014 no legacy fall-through), test_production_gate_skips_walkforward_when_sentinel_disabled (env false bypasses, v0.35.0 composition preserved as bypass).",
      "scope_fence": "Do NOT remove line 519 (evidence['pbo'] = None) \u2014 PBO production wiring is explicitly out of scope. Do NOT introduce new sentinel \u2014 use WALKFORWARD_GATE_ENABLED only. Do NOT modify _evaluate_walkforward_gate or _evaluate_shadow_trading_gate. Do NOT change promote() call site. Do NOT modify scheduler. \u226430 net new lines in promotion.py, \u226460 in test_promotion.py.",
      "estimated_complexity": "medium"
    },
    {
      "id": 15,
      "name": "T15 \u2014 Sprint 6 closeout PR (v0.36.0)",
      "description": "NEW Sprint 6 task. Implements SP-WF-015. Aggregates the [Unreleased] CHANGELOG entries from T1-T14 PRs into a new [v0.36.0] - 2026-MM-DD section with full provenance (references to walkforward-spec-v1.md and Sprint S1-CC Batch B2/B3 docs). Bumps src/version.py from v0.35.0 to v0.36.0. Appends a 'Walk-Forward Validation Gate' subsection to docs/operator-guide.md including the three SQL queries from SP-WF-016 (orphan-backtest, production-walkforward-evidence, auto-fire-failure-rate). Refreshes roadmap docs (docs/roadmap-*.md if present) \u2014 mirror the T16/v0.35.0 close PR commit 8d06e8ca pattern. Runs scripts/verify_docs.py to confirm zero drift. Operator-led tag command (git tag v0.36.0 + push) is OUT of scope \u2014 flagged in PR description. Feasibility-fix (v1.1): test-count acceptance criterion is `\u2265 5345 (5300 floor + ~45 net adds across T1-T14)`, tightened from initial 5320 target \u2014 sharper drift detection.",
      "files_in_scope": [
        "CHANGELOG.md",
        "src/version.py",
        "docs/operator-guide.md"
      ],
      "files_read_only": [
        "docs/audits/2026-05-11-stage1-completion/walkforward-spec-v1.md",
        "docs/audits/2026-05-11-stage1-completion/walkforward-plan-v1.md",
        "docs/audits/2026-05-11-stage1-completion/sprint-spec.md"
      ],
      "depends_on": [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14
      ],
      "test_strategy": "Structural: scripts/verify_docs.py zero drift items. python -c 'from src.version import VERSION; assert VERSION == \"v0.36.0\"'. python -m pytest tests/ -q test count \u2265 5320 (5300 floor + 20 added). python -m pytest tests/test_repo_structure.py -v zero new violations. No new pytest tests.",
      "scope_fence": "Do NOT push the git tag (operator-led). Do NOT modify src/ Python files other than version.py. Do NOT modify tests. Do NOT delete the v0.35.0 CHANGELOG section \u2014 aggregate ABOVE it. Do NOT change MASTER.md (separate operator decision). CHANGELOG.md aggregate must reference the v1 spec/plan paths verbatim for provenance traceability.",
      "estimated_complexity": "medium"
    }
  ],
  "execution_order": [
    [
      1,
      2,
      3
    ],
    [
      4,
      5,
      6
    ],
    [
      7
    ],
    [
      8
    ],
    [
      9,
      10
    ],
    [
      11,
      13,
      14
    ],
    [
      15
    ]
  ],
  "notes": "Sprint 6 is PM-orchestrated via /arcis:code with worktree-isolated parallel dispatch (CLAUDE.md mandatory). Tasks T1-T12 are verbatim from walkforward-plan-v1.md (binding); T13/T14/T15 are Sprint 6 additions. Wave structure: Wave 1 = T1+T2+T3 (parallel, independent foundation). Wave 2 = T4+T5+T6 (parallel, independent extensions). Wave 3 = T7 alone (schema migration, blocks T8). Wave 4 = T8 (runner integration, blocks downstream). Wave 5 = T9+T10 (parallel, sentinel guard + CLI/HTTP). Wave 6 = T11+T13+T14 parallel (regression suite + auto-fire + production gate \u2014 none of these share files). Wave 7 = T15 alone (closeout, depends on all). T12 is a discipline marker \u2014 every PR adds a CHANGELOG [Unreleased] line; T15 aggregates. Each agent worktree must run python -m pytest tests/test_repo_structure.py -v as part of strict-rigor receipt (CLAUDE.md disclosure rule). Test floor 5300 \u2192 must end \u2265 5320 (5300 + 20 added). Target close commit: v0.36.0 ahead of next sprint planning. Provenance: every PR references walkforward-spec-v1.md and walkforward-plan-v1.md by path. T13 + T14 PR descriptions specifically cite SP-WF-013/014 from this Sprint 6 spec. T15 aggregates all four new SP-WF-013\u2026016 decisions into the v0.36.0 CHANGELOG entry. NO new tables, NO new event-bus, NO new sentinels beyond WALKFORWARD_AUTOFIRE_ENABLED (which is T13's auto-fire override, distinct from T9's WALKFORWARD_GATE_ENABLED)."
}
```
