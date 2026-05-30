# Walk-Forward Validation Framework — Plan v1

## Revision History

| Version | Date | Author | Notes |
|---------|------|--------|-------|
| v1.0 | 2026-05-11 | Sprint S1-CC Batch B3 | Initial draft. Implements walkforward-spec-v1. |

## Companion spec

`docs/audits/2026-05-11-stage1-completion/walkforward-spec-v1.md` (drafted in parallel by Batch B2)

---

## Sentinel decision

**`WALKFORWARD_GATE_ENABLED` default = `true`**

Rationale: The walk-forward gate (`_evaluate_walkforward_gate` in `src/platform/promotion.py`) is already wired and executing on every `backtested → shadow_trading` promotion attempt. The `walkforward_results` table already receives PASS / FAIL / INCONCLUSIVE rows from the R1-R8 v1 runner; FAIL and INCONCLUSIVE outcomes already block promotion today. Setting the default to `true` is therefore the least-surprise choice — it names explicitly what is already true operationally. A `false` default would silently bypass a blocking gate that has been running in production since Sprint walkforward-v1, creating a regression for any strategy currently relying on a `PASS` row in `walkforward_results`. The flag's primary use-case is operator escape-hatch for forensic debugging (e.g., inspect a gate failure without re-triggering the full pipeline), not soft-launch behavior. Operator override via `WALKFORWARD_GATE_ENABLED=false` in `.env` or `walkforward_gate_enabled: false` in `config/settings.local.yaml` (lower-wins, env overrides settings).

---

## Execution order

Tasks within a batch are parallel-safe (zero file overlap, zero intra-batch dependency). Batches run sequentially.

```
Batch 1 (parallel: T1, T2, T3)
  T1 — Feature-flag sentinel wiring + config-key registration
  T2 — Trading-day arithmetic migration (evaluation/walkforward.py)
  T3 — Excess-Sharpe alignment for per-window gate

Batch 2 (parallel: T4, T5, T6)
  T4 — Schema registry: new columns for v2 outcome fields
  T5 — Window-shift math + corpus gate (spec §Architecture composition pattern)
  T6 — VIX regime coverage validator (spec §Data Model regime_coverage field)

Batch 3 (sequential: T7 depends on T4; T8 depends on T5+T6)
  T7 — Schema migration + validate-schema --fix verification
  T8 — Runner integration: wire T5/T6 outputs into walkforward_runner

Batch 4 (parallel: T9, T10)
  T9 — Promotion-gate sentinel guard (spec §API surface WALKFORWARD_GATE_ENABLED)
  T10 — CLI + HTTP read-route updates (scripts/backtest/run_walkforward.py + cloud_routes)

Batch 5 (sequential: T11 depends on all prior; T12 depends on T11)
  T11 — Regression-lock test suite (spec §Testing Strategy)
  T12 — Operator-guide update + CHANGELOG entry
```

---

## Notes

- All worktree-isolated parallel dispatches per CLAUDE.md "Parallel Agent Dispatch — Worktree Discipline"
- Test floor must increase by ≥15 tests across T1/T2/T3/T5/T6/T8/T9/T11 per CI workflow
- Schema additions go through `src/schema/registry.py` per CLAUDE.md "Database Schema Rules" — T4 MUST commit before T8 dispatches
- Sentinel flag honored via config-key precedence: env (`WALKFORWARD_GATE_ENABLED`) > `settings.local.yaml` key `walkforward_gate_enabled` > registry default `true`
- `subtract_trading_days` from `src/scheduler/holidays.py` is the ONLY permitted trading-day arithmetic helper — no `timedelta(days=N)` approximations
- `bootcamp_override` is forced `False` at the `WalkForwardConfig` layer; no task changes this behavior
- T4 (schema) and T7 (migration) are serialized to prevent a race between column additions and the migration runner
- B2 spec sections are referenced by topic throughout; if B2's literal section numbers differ from what is named here, the topic reference is authoritative

---

## Tasks

---

### T1 — Feature-flag sentinel wiring + config-key registration

**Description.** Implements the spec §Operational Notes sentinel decision. Adds `WALKFORWARD_GATE_ENABLED` as a named config key that `_evaluate_walkforward_gate` in `src/platform/promotion.py` reads before executing the gate. When the flag resolves `false`, the gate short-circuits and returns `(None, evidence)` with `walkforward_status='disabled'` — identical to the "no row found" fallback path — so the caller transparently falls through to the legacy OOS-efficiency gate without behavioral surprise. Reads the flag from `os.environ.get('WALKFORWARD_GATE_ENABLED', 'true').lower() == 'true'`; no new YAML key is required in this task (the env path is sufficient for the operator escape-hatch use-case). The existing `METHODOLOGY_GATE_ENABLED` sentinel in `promotion.py` is the exact structural pattern to follow.

**Test Strategy.** New tests in `tests/platform/test_promotion.py` (already in scope for that file):
- `test_walkforward_gate_disabled_bypasses_check` — patches `WALKFORWARD_GATE_ENABLED=false`, calls `_evaluate_walkforward_gate`, asserts `(None, evidence)` returned and `walkforward_status == 'disabled'`.
- `test_walkforward_gate_enabled_by_default` — no env patch, asserts gate executes normally (mocked DB returns a PASS row).
- `test_walkforward_gate_enabled_true_explicit` — env `WALKFORWARD_GATE_ENABLED=true`, asserts gate executes.
Must not break any of the 3682-floor tests.

**Scope Fence.**
- IN: `src/platform/promotion.py` (modify `_evaluate_walkforward_gate` only — ≤20 added lines)
- IN: `tests/platform/test_promotion.py` (add 3 test functions — ≤30 added lines)
- READ-ONLY: `src/platform/rigor/walkforward_config.py`, `src/platform/rigor/walkforward_runner.py`, `src/schema/registry.py`
- OUT: No schema changes. No new YAML config keys. No changes to `walkforward_runner.py` or `walkforward_config.py`. No changes to other gate functions in `promotion.py`.
- Estimated LOC: `promotion.py` +20 lines; `test_promotion.py` +30 lines

---

### T2 — Trading-day arithmetic migration (evaluation/walkforward.py)

**Description.** Implements the spec §Architecture composition pattern requirement that all trading-day arithmetic use `src/scheduler/holidays.subtract_trading_days`. The existing `src/evaluation/walkforward.py` has its own `_subtract_trading_days` (lines 66-74) that walks day-by-day and predates the canonical helper. This task replaces the local helper with a call to `subtract_trading_days` from `src/scheduler/holidays`, updates the `_compute_embargo_end` and `compute_fold_boundaries` call sites that depended on the local helper, and deletes the dead local function. This is a pure behavior-preserving refactor: the canonical helper uses `pandas_market_calendars` NYSE calendar, which is the same calendar the local function walks through. Tests verify output equality on known date ranges.

**Test Strategy.** New tests in `tests/evaluation/test_walkforward.py` (existing file):
- `test_fold_boundaries_use_canonical_trading_days` — calls `compute_fold_boundaries` with a known anchor/fold_count, asserts each fold's embargo boundary matches what `subtract_trading_days` returns directly for the same inputs (regression-lock).
- `test_no_local_subtract_trading_days` — AST/grep assertion that `_subtract_trading_days` does not appear anywhere in `src/evaluation/walkforward.py` (structural guard).
Must not break existing `tests/evaluation/test_walkforward.py` tests.

**Scope Fence.**
- IN: `src/evaluation/walkforward.py` (delete `_subtract_trading_days`, update callers — ≤30 net line change; known_violations.json waiver for 431-line size is pre-existing, no new waiver needed)
- IN: `tests/evaluation/test_walkforward.py` (add 2 tests — ≤25 added lines)
- READ-ONLY: `src/scheduler/holidays.py` (consume `subtract_trading_days`), `config/known_violations.json` (verify waiver still valid after edit)
- OUT: No changes to `_run_fold`, `compute_aggregate`, `run_walkforward` logic. No changes to `src/platform/rigor/walkforward*.py`. No corpus-gate changes.
- Estimated LOC: `evaluation/walkforward.py` net -10 lines (delete helper, update 2 call sites); `test_walkforward.py` +25 lines

---

### T3 — Excess-Sharpe alignment for per-window gate

**Description.** Implements the spec §Architecture composition pattern decision on D4 (per-window statistical gate). The R1-R8 v1 framework currently gates on raw Sharpe (≥0.3) per `SHARPE_MIN_PER_WINDOW`. The methodology toolkit uses excess-Sharpe (returns minus per-period FRED rf) throughout; the Stage 2 spec (MASTER.md SD#43) requires excess Sharpe ≥ 0.5 over 150 OOS trades. This task adds an `excess_sharpe_min` field to `WalkForwardConfig` (defaulting to `None` to preserve backward compatibility), wires it into `compute_window_metrics` in `walkforward_metrics.py` as an additional check when the field is set, and documents the default as "None = use raw Sharpe threshold only." This is additive — no existing behavior changes unless the caller sets `excess_sharpe_min`. The spec §Design Decisions Table entry D4 is the authority; if B2 resolves D4 differently, this task absorbs the resolution.

**Test Strategy.** New tests in `tests/platform/rigor/test_walkforward_metrics.py` (existing file):
- `test_window_metrics_excess_sharpe_gate_pass` — fixture with excess returns above `excess_sharpe_min`, asserts window passes.
- `test_window_metrics_excess_sharpe_gate_fail` — fixture with excess returns below threshold, asserts window fails with `reason='excess_sharpe_below_min'`.
- `test_window_metrics_excess_sharpe_none_uses_raw` — `excess_sharpe_min=None`, asserts original raw-Sharpe gate logic unchanged.
Must not break existing `tests/platform/rigor/test_walkforward_metrics.py` or `test_walkforward_config.py`.

**Scope Fence.**
- IN: `src/platform/rigor/walkforward_config.py` (add `excess_sharpe_min: float | None = None` field — ≤10 lines)
- IN: `src/platform/rigor/walkforward_metrics.py` (add excess-Sharpe check branch — ≤20 lines)
- IN: `tests/platform/rigor/test_walkforward_metrics.py` (add 3 tests — ≤35 added lines)
- READ-ONLY: `src/analytics/canonical_sharpe.py` (reference for excess-Sharpe formula), `src/data_ingestion/risk_free_rate.py` (rf source), `docs/methodology-toolkit.md`
- OUT: No changes to `walkforward_runner.py`, `walkforward_outcome.py`, `walkforward_power.py`. No changes to the 9 existing threshold constants (no default overrides). No schema changes.
- Estimated LOC: `walkforward_config.py` +10 lines; `walkforward_metrics.py` +20 lines; `test_walkforward_metrics.py` +35 lines

---

### T4 — Schema registry: new columns for v2 outcome fields

**Description.** Implements the spec §Data Model `walkforward_results` schema additions. Adds two new optional columns to the `walkforward_results` table definition in `src/schema/registry.py`: `excess_sharpe_min_used REAL` (records the per-run `excess_sharpe_min` threshold so each result row is self-describing) and `gate_version TEXT DEFAULT 'v1'` (records the framework version that produced the row, enabling future forward-compatible reads by `_evaluate_walkforward_gate`). Both columns are nullable with defaults to preserve existing row inserts. This task ONLY modifies the registry; T7 runs `validate-schema --fix` to apply the DDL. Per CLAUDE.md schema discipline: no `ALTER TABLE` outside the registry.

**Test Strategy.** New tests in `tests/test_schema.py` (existing file, schema structural tests):
- `test_walkforward_results_has_excess_sharpe_min_used_column` — imports `TABLES` from registry, asserts `walkforward_results` table def has column `excess_sharpe_min_used`.
- `test_walkforward_results_has_gate_version_column` — same pattern for `gate_version`.
Must not break any existing `tests/test_schema.py` tests (currently passing at 3682 floor).

**Scope Fence.**
- IN: `src/schema/registry.py` (add 2 `ColumnDef` entries to `walkforward_results` — ≤15 added lines)
- IN: `tests/test_schema.py` (add 2 structural tests — ≤20 added lines)
- READ-ONLY: `src/platform/rigor/walkforward_runner.py` (verify column names don't conflict with persist_run_result INSERT)
- OUT: No `ALTER TABLE` or `CREATE TABLE` statements anywhere. No changes to `walkforward_runner.py` (T8 handles that). No changes to other tables. `validate-schema --fix` is run by T7, not T4.
- Estimated LOC: `registry.py` +15 lines; `test_schema.py` +20 lines

---

### T5 — Window-shift math + corpus gate (spec §Architecture composition pattern)

**Description.** Implements the spec §Architecture composition pattern for the canonical window geometry decision (spec D1 / D6). Adds a `WalkForwardWindowBuilder` utility function in `src/platform/rigor/walkforward_config.py` that generates `DEFAULT_WINDOWS`-compatible window sequences from a start date and window count, using `subtract_trading_days` from `src/scheduler/holidays` for embargo boundary computation. This replaces the hard-coded `DEFAULT_WINDOWS` tuple as the generator path (the hard-coded tuple remains as the canonical default for backward compatibility). Also adds `corpus_id` as an optional field on `WalkForwardConfig`; when set, the runner (T8) will call `_gate_corpus_or_raise` from `src/evaluation/walkforward.py` before executing folds — implementing the spec §Architecture corpus-admissibility composition. The builder function is ≤40 lines; corpus_id field addition is ≤10 lines.

**Test Strategy.** New tests in `tests/platform/rigor/test_walkforward_config.py` (existing file):
- `test_window_builder_generates_no_overlap` — calls builder with anchor + count, asserts every generated `WalkForwardWindow` satisfies `train_end < test_start` invariant.
- `test_window_builder_uses_canonical_trading_days` — asserts embargo boundaries match `subtract_trading_days` output for known inputs.
- `test_config_accepts_corpus_id` — `WalkForwardConfig(strategy_id='x', corpus_id='stage1-001')` does not raise.
- `test_config_corpus_id_none_is_default` — `WalkForwardConfig(strategy_id='x').corpus_id is None`.
Must not break existing `test_walkforward_config.py` tests.

**Scope Fence.**
- IN: `src/platform/rigor/walkforward_config.py` (add `WalkForwardWindowBuilder` function + `corpus_id` field — ≤55 lines total additions; file stays under 400-line ceiling with these additions)
- IN: `tests/platform/rigor/test_walkforward_config.py` (add 4 tests — ≤40 added lines)
- READ-ONLY: `src/scheduler/holidays.py`, `src/evaluation/walkforward.py` (corpus gate pattern), `docs/audits/2026-05-11-stage1-completion/walkforward-prior-art.md`
- OUT: No changes to `DEFAULT_WINDOWS` tuple (backward compatibility). No changes to `walkforward_runner.py` (T8 wires the corpus_id path). No schema changes.
- Estimated LOC: `walkforward_config.py` +55 lines; `test_walkforward_config.py` +40 lines

---

### T6 — VIX regime coverage validator (spec §Data Model regime_coverage field)

**Description.** Implements the spec §Data Model VIX tier coverage validation refinement. The existing `walkforward_universe.py` provides point-in-time universe lookup. The existing `MIN_VIX_TIERS_REPRESENTED = 2` constant in `walkforward_config.py` requires at least 2 distinct VIX tiers (low <15, medium 15-25, high >25) across a run's OOS windows. This task adds a `validate_vix_tier_coverage(trades, min_tiers)` function to `src/platform/rigor/walkforward_power.py` that accepts a list of per-trade VIX observations and the `min_tiers` threshold, returns a `VixCoverageResult(distinct_tiers, passes, missing_tiers)` datatype. The existing `distinct_tier_count` in `walkforward_metrics.py` is the structural predecessor; this task adds the pass/fail wrapper and the `missing_tiers` diagnostic field for structured failure evidence in `walkforward_results.vix_tier_coverage`. Function is ≤30 lines.

**Test Strategy.** New tests in `tests/platform/rigor/test_walkforward_power.py` (existing file):
- `test_vix_coverage_all_tiers` — VIX observations spanning <15, 15-25, >25 → `passes=True`, `distinct_tiers=3`.
- `test_vix_coverage_missing_high` — no observations >25 → `passes` depends on `min_tiers` (passes=True if min_tiers=2, fails if min_tiers=3).
- `test_vix_coverage_single_tier_fails` — all observations in one tier → `passes=False` (min_tiers=2 default).
- `test_vix_coverage_empty_trades_fails` — empty list → `passes=False`, `distinct_tiers=0`.
Must not break existing `tests/platform/rigor/test_walkforward_power.py` tests.

**Scope Fence.**
- IN: `src/platform/rigor/walkforward_power.py` (add `VixCoverageResult` + `validate_vix_tier_coverage` — ≤35 lines)
- IN: `tests/platform/rigor/test_walkforward_power.py` (add 4 tests — ≤40 added lines)
- READ-ONLY: `src/platform/rigor/walkforward_metrics.py` (reference `distinct_tier_count`), `src/platform/rigor/walkforward_config.py` (MIN_VIX_TIERS_REPRESENTED constant)
- OUT: No changes to `walkforward_metrics.py`, `walkforward_outcome.py`, `walkforward_universe.py`. No schema changes. The `distinct_tier_count` function in `walkforward_metrics.py` is NOT replaced — this task adds a wrapper layer only.
- Estimated LOC: `walkforward_power.py` +35 lines; `test_walkforward_power.py` +40 lines

---

### T7 — Schema migration + validate-schema --fix verification

**Description.** Implements the spec §Operational Notes schema-migration step. Runs `python -m src.main validate-schema --fix` after T4's registry additions to materialize the two new columns (`excess_sharpe_min_used`, `gate_version`) into the SQLite schema. Commits the migration output as a documented artifact. Also runs `python scripts/render_migrate.py` if a Postgres DATABASE_URL is configured (guarded by env-var check — skip gracefully if absent, log that Postgres sync is deferred). Verifies the schema round-trips correctly via a post-fix `validate-schema` (no-flag) call that returns zero drift items. This task has no Python source changes — it is infrastructure-only.

**Test Strategy.** Structural verification only:
- `python -m src.main validate-schema` produces zero drift items after `--fix` — paste output in PR description.
- `python -m pytest tests/test_schema.py -v` passes (includes T4's new structural tests, which are committed on T4's branch and merged to integration before T7 dispatches).
- No new test functions are written by T7 itself.

**Scope Fence.**
- IN: `src/schema/registry.py` — read to verify (no changes; T4 owns modifications)
- IN: PR description (migration output artifact — not a committed file)
- READ-ONLY: `src/platform/rigor/walkforward_runner.py` (verify INSERT path accommodates new columns)
- OUT: No Python source changes. No new test files. T7 does NOT add columns to the registry (T4 owns that). T7 does NOT modify `walkforward_runner.py` (T8 owns that).
- Estimated LOC: 0 source lines changed

---

### T8 — Runner integration: wire T5/T6 outputs into walkforward_runner

**Description.** Implements the spec §Architecture composition pattern for the full runner integration. Updates `src/platform/rigor/walkforward_runner.py` to: (a) call `WalkForwardWindowBuilder` from T5 when `config.windows` is not explicitly set and a `window_count` config override is present (preserving `DEFAULT_WINDOWS` as the hard-coded fallback); (b) call `_gate_corpus_or_raise` from `src/evaluation/walkforward.py` when `config.corpus_id` is set (T5 added this field); (c) call `validate_vix_tier_coverage` from T6 and include `VixCoverageResult` in the run evidence; (d) populate `excess_sharpe_min_used` and `gate_version='v2'` (new gate_version string for runs that use T3's excess-Sharpe path) when persisting to `walkforward_results`. The runner already has a known LOC waiver (`persist_run_result` 95 lines + `run_walkforward` 105 lines per `config/known_violations.json` lines 735-742) — each sub-change in this task must stay within the existing waiver bounds or the agent must update the waiver in the same commit.

**Test Strategy.** New tests in `tests/platform/rigor/test_walkforward_runner.py` (existing file):
- `test_runner_calls_corpus_gate_when_corpus_id_set` — mock `_gate_corpus_or_raise`, assert it is called when `config.corpus_id='stage1-001'`.
- `test_runner_skips_corpus_gate_when_corpus_id_none` — `config.corpus_id=None`, assert `_gate_corpus_or_raise` NOT called.
- `test_runner_persists_gate_version_v2_when_excess_sharpe_set` — `config.excess_sharpe_min=0.3`, run with mocked backtest engine, assert `walkforward_results` row has `gate_version='v2'`.
- `test_runner_persists_gate_version_v1_when_excess_sharpe_none` — `config.excess_sharpe_min=None`, assert `gate_version='v1'`.
Must not break existing `tests/platform/rigor/test_walkforward_runner.py` tests.

**Scope Fence.**
- IN: `src/platform/rigor/walkforward_runner.py` (4 wiring points — ≤55 net new lines; stay within existing waivers or update `config/known_violations.json` in same commit)
- IN: `tests/platform/rigor/test_walkforward_runner.py` (add 4 tests — ≤50 added lines)
- IN: `config/known_violations.json` (update runner waiver line counts if needed — ≤5 changed lines)
- READ-ONLY: `src/platform/rigor/walkforward_config.py`, `src/platform/rigor/walkforward_power.py`, `src/evaluation/walkforward.py`, `src/schema/registry.py`
- OUT: No changes to `walkforward_firewall.py`, `walkforward_purging.py`, `walkforward_costs.py`, `walkforward_universe.py`, `walkforward_outcome.py`. No schema DDL. No changes to `promotion.py`.
- Estimated LOC: `walkforward_runner.py` +55 lines; `test_walkforward_runner.py` +50 lines; `known_violations.json` ≤5 lines

---

### T9 — Promotion-gate sentinel guard (spec §API surface WALKFORWARD_GATE_ENABLED)

**Description.** Implements the spec §API surface decision-path audit for `evaluate_promotion_gate` in `src/platform/promotion.py`. Audits the `evaluate_promotion_gate` function (the top-level `backtested → shadow_trading` orchestrator) to confirm the `WALKFORWARD_GATE_ENABLED` flag from T1 is correctly consulted before the AND-composition step. Adds a guard in `evaluate_promotion_gate` that short-circuits to the legacy gate path when the sentinel is `false` — preserving the three-gate composition (`methodology gate AND walk-forward gate AND DSR gate`) when enabled, and falling through to the legacy two-gate path (`methodology gate AND DSR gate`) when disabled. Also adds `walkforward_gate_enabled` to the returned `evidence` dict so dashboard read-through knows the gate status. This task is additive in `evaluate_promotion_gate` only (≤15 lines); it does NOT touch `_evaluate_walkforward_gate` (T1 owns that function).

**Test Strategy.** New tests in `tests/platform/test_promotion.py`:
- `test_evaluate_promotion_gate_wf_disabled_skips_wf` — patches sentinel false, mocked methodology gate pass, asserts walkforward gate not queried.
- `test_evaluate_promotion_gate_wf_enabled_calls_wf` — patches sentinel true, mocked WF PASS row, asserts walkforward gate IS queried.
- `test_evaluate_promotion_gate_evidence_carries_gate_enabled_flag` — asserts `evidence['walkforward_gate_enabled']` present in both cases.
Must not break existing `tests/platform/test_promotion.py` or `tests/test_promotion_methodology_gate.py`.

**Scope Fence.**
- IN: `src/platform/promotion.py` (modify `evaluate_promotion_gate` only — ≤15 added lines; no changes to `_evaluate_walkforward_gate`)
- IN: `tests/platform/test_promotion.py` (add 3 tests — ≤35 added lines)
- READ-ONLY: `src/platform/rigor/walkforward_config.py`, `src/platform/rigor/walkforward_runner.py`
- OUT: No changes to the methodology gate, DSR gate, or shadow-trading→production gate. No changes to `walkforward_runner.py`. No schema changes.
- Estimated LOC: `promotion.py` +15 lines; `test_promotion.py` +35 lines

---

### T10 — CLI + HTTP read-route updates

**Description.** Implements the spec §API surface CLI and HTTP surface updates. Two sub-targets: (a) `scripts/backtest/run_walkforward.py` — adds `--corpus-id` flag that passes through to `WalkForwardConfig.corpus_id`, adds `--excess-sharpe-min` flag that passes through to `WalkForwardConfig.excess_sharpe_min` (both optional, default None). (b) `src/api/cloud_routes/walkforward.py` — extends the read-route response to include `gate_version` and `excess_sharpe_min_used` from the `walkforward_results` row (both already present in the DB after T4/T7; this is a read-through-only change). No new routes. No change to the HTTP route path or method. The CLI script is currently ≤200 lines; additions will stay under that.

**Test Strategy.** New tests:
- `tests/scripts/test_run_walkforward_cli.py` (new file, ≤40 lines):
  - `test_cli_corpus_id_flag_accepted` — parse `['--strategy-id', 'x', '--corpus-id', 'stage1-001']`, assert `corpus_id='stage1-001'` in parsed config.
  - `test_cli_excess_sharpe_min_flag_accepted` — parse with `--excess-sharpe-min 0.3`, assert `excess_sharpe_min=0.3`.
- `tests/api/test_walkforward_route.py` (existing if present, or new ≤30 lines):
  - `test_walkforward_route_includes_gate_version` — mocked DB row with `gate_version='v1'`, asserts response contains `gate_version`.
Must not break existing CLI tests.

**Scope Fence.**
- IN: `scripts/backtest/run_walkforward.py` (add 2 argparse flags + config pass-through — ≤25 added lines)
- IN: `src/api/cloud_routes/walkforward.py` (add 2 fields to response dict — ≤10 added lines)
- IN: `tests/scripts/test_run_walkforward_cli.py` (new file — ≤40 lines)
- IN: `tests/api/test_walkforward_route.py` (new or existing — ≤30 lines)
- READ-ONLY: `src/platform/rigor/walkforward_config.py`, `src/platform/rigor/walkforward_runner.py`, `src/schema/registry.py`
- OUT: No new HTTP routes. No changes to the runner, config, or promotion gate. No schema changes.
- Estimated LOC: `run_walkforward.py` +25 lines; `cloud_routes/walkforward.py` +10 lines; test files +70 lines

---

### T11 — Regression-lock test suite (spec §Testing Strategy)

**Description.** Implements the spec §Testing Strategy cross-cutting regression lock. Adds a `tests/platform/rigor/test_walkforward_regression_lock.py` file that exercises the full R1-R8 v1 framework end-to-end with a hermetic synthetic fixture (no DB, no network, no Alpaca). The fixture: (a) builds a `WalkForwardConfig` with `DEFAULT_WINDOWS` and `strategy_id='regression_lock_001'`; (b) provides a deterministic synthetic trade list per window (seed=42, 15 trades per window, Sharpe ≈ 0.4, one VIX tier per window); (c) calls `reduce_outcome` directly; (d) asserts `outcome_state == 'PASS'` and `pooled_sharpe >= 0.3`. A second fixture exercises the FAIL path (Sharpe < 0.3 in ≥2 windows). A third fixture exercises INCONCLUSIVE (≥2 windows with <10 trades). These three fixtures lock the three-state outcome state machine against regression. All fixtures use `random.seed(42)` deterministically; no external dependencies.

**Test Strategy.** New file `tests/platform/rigor/test_walkforward_regression_lock.py` (≤80 lines):
- `test_regression_lock_pass_outcome` — synthetic PASS fixture, assert `outcome_state == 'PASS'`.
- `test_regression_lock_fail_outcome` — synthetic FAIL fixture, assert `outcome_state == 'FAIL'`.
- `test_regression_lock_inconclusive_outcome` — synthetic INCONCLUSIVE fixture.
- `test_regression_lock_pooled_sharpe_stable` — PASS fixture pooled_sharpe within 0.01 of expected value (determinism lock).
Must not break any existing `tests/platform/rigor/` tests.

**Scope Fence.**
- IN: `tests/platform/rigor/test_walkforward_regression_lock.py` (new file — ≤80 lines)
- READ-ONLY: `src/platform/rigor/walkforward_config.py`, `src/platform/rigor/walkforward_outcome.py`, `src/platform/rigor/walkforward_metrics.py`, `src/platform/rigor/walkforward_power.py`
- OUT: No src/ changes. No changes to existing test files. No DB or network access.
- Estimated LOC: 0 src/ lines; new test file ≤80 lines

---

### T12 — Operator-guide update + CHANGELOG entry

**Description.** Implements the spec §Operational Notes documentation requirements. Updates `docs/operator-guide.md` with a new subsection "Walk-Forward Validation Gate" covering: (a) how to check gate status for a strategy (`SELECT outcome_state, reason FROM walkforward_results WHERE strategy_id=? ORDER BY created_at DESC LIMIT 1`); (b) the `WALKFORWARD_GATE_ENABLED=false` override procedure and when to use it; (c) how to trigger a new walk-forward run via CLI (`scripts/backtest/run_walkforward.py --strategy-id X --corpus-id stage1-001`); (d) how to interpret PASS / FAIL / INCONCLUSIVE and when to file a spec re-open (per §5 falsifiability triggers in the prior-art doc). Adds CHANGELOG entry under `[Unreleased]` for the walk-forward framework v2 additions. Runs `scripts/verify_docs.py` to confirm no drift. This task is docs-only; no src/ or test changes.

**Test Strategy.** `scripts/verify_docs.py` passes with zero new drift items. No new pytest tests; this is documentation only. Pre-existing `tests/test_repo_structure.py` must still pass (docs-only changes do not trigger file-size violations).

**Scope Fence.**
- IN: `docs/operator-guide.md` (add subsection — ≤60 added lines)
- IN: `CHANGELOG.md` (add [Unreleased] entry — ≤10 added lines)
- READ-ONLY: `docs/audits/2026-05-11-stage1-completion/walkforward-prior-art.md`, `docs/audits/2026-05-11-stage1-completion/walkforward-spec-v1.md` (B2 output)
- OUT: No src/ changes. No test changes. No MASTER.md changes (MASTER.md is updated at sprint closeout, not per-task). No changes to any `walkforward_*.py` files.
- Estimated LOC: 0 src/ lines; `operator-guide.md` +60 lines; `CHANGELOG.md` +10 lines

---

## Acceptance criteria (sprint-level)

- [ ] All 12 tasks merged via worktree-isolated PRs
- [ ] CI test count increases from 3682 baseline by ≥15 (estimated: ~17 new test functions across T1/T2/T3/T5/T6/T8/T9/T10/T11)
- [ ] Walk-forward gate integration smoke-tests pass (`test_walkforward_gate_enabled_by_default`, `test_evaluate_promotion_gate_wf_enabled_calls_wf`)
- [ ] Operator-guide updated with `WALKFORWARD_GATE_ENABLED` override procedure (T12)
- [ ] `scripts/verify_docs.py` zero drift items after T12
- [ ] CHANGELOG entry under `[Unreleased]` for walk-forward framework v2 additions
- [ ] `python -m src.main validate-schema` returns zero drift items after T7
- [ ] `python -m pytest tests/test_repo_structure.py -v` zero new violations (docs + additive src changes only)
- [ ] MASTER.md update deferred to sprint closeout PR (not per-task)

---

## Out of scope (sprint-level)

- v2 training dispatch (still gated on walk-forward shipping + Stage 2 closure)
- New strategy specs (#511 Connors RSI(2) etc. stays separate)
- Modifications to existing CPCV / PSR / white_rc / block_bootstrap impls
- Bootcamp settings (still active per MASTER.md SD#43)
- Stage 2 OOS gate changes (excess Sharpe ≥ 0.5 over 150 OOS trades per SD#43 is a Stage 2 concern, not this sprint)
- `src/evaluation/walkforward.py` architectural replacement or renaming — it remains as the Stage-1 anchored harness
- Removal or deprecation of `src/platform/rigor/walkforward.py` (legacy Pardo wrapper) — deferred
- New `walkforward_v2_results` table (spec D7 Choice B) — plan adopts Choice A (reuse existing table + `gate_version` column to distinguish runs)
- Walk-forward vote contribution to `_decide` in `promotion_gate.py` (spec D8 Choice A) — plan preserves Choice B (AND-composed separate gate, current state)
- MASTER.md Section 2 volatile-state update — deferred to sprint closeout PR after all tasks merge
