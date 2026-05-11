# Walk-Forward Validation Framework — Spec v1

## Revision History

| Version | Date | Author | Notes |
|---------|------|--------|-------|
| v1.0 | 2026-05-11 | Sprint S1-CC Batch B2 | Initial draft. Closes B1 prior-art → spec gap. |

---

## Overview

The Walk-Forward Validation Framework is the mandatory gate between Stage 1 corpus admissibility and Stage 2 OOS dispatch. Its function is to verify that a strategy's measured edge is regime-stable — not merely an artifact of a favorable trailing sample — before any live OOS trades are authorized. Walk-forward is not a substitute for MC permutation, block bootstrap, or PSR/DSR; it is the fourth AND-composed gate that sits alongside the 4-of-5 methodology voter in `src/platform/promotion.py:evaluate_promotion_gate`.

The framework is being specified now (2026-05-11) because the Stage 1 corpus has reached §B2 admissibility (67,528 entries, PASS). Per MASTER.md SD#43, Stage 2 requires excess Sharpe ≥ 0.5 at p < 0.05 over 150 OOS trades plus the full ≥4-of-5 methodology gate. The walk-forward gate is the bridge: a strategy that cannot pass walk-forward on its Stage-1 backtest record has no business accumulating Stage-2 OOS capital. v2 training is also gated on walk-forward shipping — a model version retrained without a walk-forward PASS on its predecessor is not promotable.

This spec governs the **canonical walk-forward framework** going forward. Two legacy implementations exist (`src/evaluation/walkforward.py` anchored-expanding for Stage-1 corpus-grounded runs; `src/platform/rigor/walkforward.py` Pardo-2008 rolling wrapper; `src/platform/rigor/walkforward_config.py` R1-R8 v1 fixed non-overlapping). The new framework extends the R1-R8 v1 fixed non-overlapping geometry (Decision SP-WF-001), adds the excess-Sharpe per-window gate to replace raw Sharpe (SP-WF-004), and formalizes the sentinel and corpus-binding rules. The legacy implementations are frozen in place — neither is deleted in this sprint or the impl sprint. The canonical path is R1-R8 v1.

The §B2 admissibility precedent: the corpus `stage1-001` is admissible under `_gate_corpus_or_raise` (every fold's test window falls inside `[walkforward_window_start, walkforward_window_end]`, manifest `is_admissible=true`). The new framework must honor this gate when corpus-grounded scoring is used. Any run that is not corpus-grounded (i.e., `corpus_id=None`) is non-deterministic per R5 and is not promotion-grade (Decision SP-WF-010).

---

## Architecture

The new framework does NOT add a 6th vote to `_decide` in `src/methods/promotion_gate.py`. Walk-forward remains an AND-composed separate gate, wired one level up in `src/platform/promotion.py:_evaluate_backtested_to_shadow`. This is the current production shape (PR #971 D5/D6) and is preserved verbatim (Decision SP-WF-008). The rationale: the 4-of-5 voter operates on a globally-pooled per-trade excess-return series and answers "is this Sharpe real?"; walk-forward answers "is this Sharpe regime-stable over non-overlapping temporal windows?" These are orthogonal questions. Collapsing them into a single voter changes the semantics of `_MIN_VOTES_TO_PROMOTE` and introduces the risk that a methodology FAIL can be masked by a walk-forward PASS (or vice versa). AND-composition at the orchestrator level preserves independent falsifiability.

The call sequence for `target='shadow_trading'` is unchanged:

```
1. _evaluate_strategy_methodology_gate(strategy_id, db_path)
       → runs the 4-of-5 voter (cpcv / block_bootstrap / mc_perm / psr_dsr / white_rc)
       → returns (passes_methodology_gate, mg_evidence)
   FAIL → return (False, evidence)   [never continue to walk-forward on methodology FAIL]

2. _evaluate_walkforward_gate(strategy_id, db_path, evidence)
       → reads latest walkforward_results row (ORDER BY created_at DESC LIMIT 1)
       → PASS        → wf_pass=True;  continue to DSR gate
       → FAIL        → wf_pass=False; return (False, evidence)
       → INCONCLUSIVE→ wf_pass=False; return (False, evidence)
       → no row      → wf_pass=None;  fall back to legacy oos_efficiency gate

3. DSR + PBO + (legacy oos_efficiency if step 2 returned None)
```

The R1-R8 v1 framework (`walkforward_runner.run_walkforward` → `persist_run_result` → `walkforward_results` table) feeds step 2. The new framework extends R1-R8 v1 in-place; `_evaluate_walkforward_gate` reads from the existing `walkforward_results` table unchanged (Decision SP-WF-007). No new table or new gate function is introduced.

The canonical window geometry is **fixed non-overlapping** (R1 default: 5 windows, 2-year IS / 15-month OOS, 2017-01-01 IS-start → 2024-09-30 OOS-end). `WalkForwardConfig.windows` is the authoritative list. The anchored-expanding geometry of `src/evaluation/walkforward.py` is retained for Stage-1 corpus-grounded diagnostic runs only — it is not the promotion gate input (Decision SP-WF-001 and SP-WF-002).

All trading-day boundary arithmetic uses `src/scheduler/holidays.subtract_trading_days`. No `timedelta(days=N)` approximations anywhere in the new framework.

---

## Data Model

The existing `walkforward_results` table (defined in `src/schema/registry.py`) is the persistence target. No new table is introduced. The existing columns already cover the new framework's output requirements:

| Column | Type | Role |
|--------|------|------|
| `run_id` | TEXT PK | UUID per run |
| `strategy_id` | TEXT | FK to strategy_registry |
| `spec_hash` | TEXT | SHA256 of WalkForwardConfig JSON |
| `code_git_sha` | TEXT | Git SHA at run time (determinism audit) |
| `random_seed` | INTEGER | Default 42 (R5 — determinism) |
| `config_json` | TEXT | Full WalkForwardConfig serialized |
| `outcome_state` | TEXT | 'PASS' / 'FAIL' / 'INCONCLUSIVE' |
| `reason` | TEXT | Structured reason string |
| `pooled_sharpe` | REAL | Net-of-cost pooled excess-Sharpe across all windows |
| `pooled_mde` | REAL | Pooled MDE at 80% power |
| `heavy_tail_flag` | INTEGER | 1 if heavy-tail SE adjustment applied |
| `heavy_tail_window_count` | INTEGER | Number of windows flagged heavy-tail |
| `n_windows_pass` | INTEGER | Windows in PASS state |
| `n_windows_fail` | INTEGER | Windows in FAIL state |
| `n_windows_inconclusive_data` | INTEGER | Windows INCONCLUSIVE due to low trades |
| `n_windows_inconclusive_power` | INTEGER | Windows INCONCLUSIVE due to low power |
| `effective_universe_size` | INTEGER | Point-in-time S&P 100 size at run date |
| `max_drawdown_pct` | REAL | Max drawdown across all OOS windows |
| `vix_tier_coverage` | TEXT | JSON array of VIX tiers represented |
| `derived_from_strategy_id` | TEXT | R8 firewall: source strategy (or null) |
| `derived_from_backtest_id` | TEXT | R8 firewall: source backtest run |
| `created_at` | TEXT | ISO timestamp UTC |

The `walkforward_trades` table (per-trade detail) is similarly unchanged. No schema-registry edits are required in the impl sprint UNLESS the excess-Sharpe gate (SP-WF-004) requires a new per-window `excess_sharpe_observed` column. That column check is the first task in the impl sprint's B3 task list — consult registry before adding.

Schema discipline: any new column introduced during implementation MUST go through `src/schema/registry.py` as a `ColumnDef` BEFORE the runner-edit task runs. DDL nowhere else (CLAUDE.md mandatory).

---

## API & Module Surface

The canonical module location is `src/platform/rigor/` (the R1-R8 v1 state-machine cluster). The `src/evaluation/walkforward.py` anchored harness stays in place for corpus-grounded Stage-1 diagnostic runs. No new top-level module is introduced (Decision SP-WF-006).

**Functions unchanged (frozen, read-only):**
- `WalkForwardConfig` dataclass — all 15 fields unchanged
- `WalkForwardWindow` frozen dataclass — `train_start/end`, `test_start/end`, leakage assertion
- `run_walkforward(strategy_spec_raw, config, window_trades, ...)` → `WalkForwardRunResult`
- `persist_run_result(result, strategy_spec_raw, oos_trades_per_window, db_path)` — idempotent (primary-key replace)
- `reduce_outcome(window_states, ...)` → `OutcomeResult` (three-state reducer)
- `_evaluate_walkforward_gate(strategy_id, db_path, evidence)` in `src/platform/promotion.py`

**Functions modified in impl sprint (each ≤60 lines net change):**
- `walkforward_metrics.py`: replace raw `SHARPE_MIN_PER_WINDOW = 0.3` gate with excess-Sharpe threshold `EXCESS_SHARPE_MIN_PER_WINDOW` (Decision SP-WF-004). Old constant kept as a deprecated alias for one sprint.
- `walkforward_config.py`: add `excess_sharpe_min_per_window` field to `WalkForwardConfig` with default matching `EXCESS_SHARPE_MIN_PER_WINDOW`. Backward-compatible (field has a default).
- `walkforward_runner.py`: thread `corpus_id` through `run_walkforward`; raise `CorpusNotBoundError` when `corpus_id=None` and `bootcamp_override=False` (Decision SP-WF-010). The `bootcamp_override` guard is R8(d) and stays.

**New functions (impl sprint):**
- `walkforward_config.py::_validate_sentinel()` (≤15 lines) — reads `WALKFORWARD_GATE_ENABLED` env var; raises `WalkForwardSentinelError` if explicitly set to a non-boolean string. Called at import time.
- `src/platform/promotion.py::_check_walkforward_sentinel()` (≤10 lines) — reads sentinel; if `false`, bypasses `_evaluate_walkforward_gate` and logs a WARNING with the strategy_id. Called before step 2 in the AND-composed sequence above.

All new public functions must have unit tests with ≥1 happy path + ≥1 failure path. No unexercised code paths (per existing test discipline).

---

## Error Handling

**Insufficient OOS trades per window (`n_trades < MIN_TRADES_PER_WINDOW = 10`):**
Window state → `INCONCLUSIVE_DATA`. If ≥2 windows are `INCONCLUSIVE_*`, overall outcome is `INCONCLUSIVE`. The reason string encodes `criterion_insufficient_trades_per_window`. Gate returns `(False, evidence)` with `walkforward_status='inconclusive'`.

**Refit failure (corpus_id not bound):**
`CorpusNotBoundError` raised in `run_walkforward` before any windows execute. Caller catches and writes `outcome_state='FAIL'` with `reason='corpus_not_bound'`. Gate returns `(False, evidence)`.

**Window-aggregation conflict (pooled_sharpe NaN):**
Can occur when all windows are INCONCLUSIVE. `reduce_outcome` maps this to overall `INCONCLUSIVE` with `reason='all_windows_inconclusive'`. Gate returns `(False, evidence)`.

**R8 firewall violation (`R8ViolationError`):**
`assert_no_overlap` in `walkforward_firewall.py` raises before any windows execute. Caller catches; `outcome_state='FAIL'`, `reason='r8_firewall_overlap'`. Gate returns `(False, evidence)`.

**Sentinel flag off (`WALKFORWARD_GATE_ENABLED=false`):**
`_check_walkforward_sentinel()` in `promotion.py` bypasses `_evaluate_walkforward_gate` entirely. Evidence gains `walkforward_status='sentinel_disabled'`. Gate returns `(True, evidence)` — the walk-forward check is skipped, not failed. This is a soft-launch path only; production should run with the sentinel on.

**Table missing on legacy DB (`sqlite3.OperationalError`):**
Existing handler in `_evaluate_walkforward_gate` returns `(None, evidence)` — falls back to legacy `oos_efficiency` gate. No change.

---

## Testing Strategy

**Unit tests (each ≤60 lines, new file `tests/platform/rigor/test_walkforward_excess_sharpe.py`):**
- `test_excess_sharpe_gate_pass` — window with excess_sharpe > `EXCESS_SHARPE_MIN_PER_WINDOW` → window state `PASS`
- `test_excess_sharpe_gate_fail` — window with excess_sharpe < threshold → window state `FAIL`
- `test_corpus_not_bound_raises` — `corpus_id=None`, `bootcamp_override=False` → `CorpusNotBoundError`
- `test_sentinel_disabled_bypasses_gate` — `WALKFORWARD_GATE_ENABLED=false` → `walkforward_status='sentinel_disabled'`, gate passes

**Unit tests for window-shifting math (existing `tests/platform/rigor/test_walkforward_config.py`, extend):**
- `test_window_boundaries_no_is_oos_overlap` — all 5 default windows: `train_end < test_start` for each
- `test_embargo_uses_trading_day_helper` — `WalkForwardWindow` boundary with `embargo_days=5` calls `subtract_trading_days`, not `timedelta`

**Integration tests (new file `tests/platform/rigor/test_walkforward_integration.py`, ≤120 lines):**
- `test_walkforward_gate_pass_through_promotion` — mock `walkforward_results` row with `outcome_state='PASS'`; full `evaluate_promotion_gate` returns gate pass
- `test_walkforward_gate_fail_blocks_promotion` — mock `outcome_state='FAIL'`; full gate returns False
- `test_walkforward_gate_inconclusive_blocks_promotion` — mock `outcome_state='INCONCLUSIVE'`; full gate returns False with `walkforward_status='inconclusive'`
- `test_methodology_gate_fail_short_circuits_walkforward` — methodology gate fails → walk-forward never queried (assert mock not called)

**Regression locks (extend `tests/platform/test_promotion.py`):**
- `test_walkforward_gate_enabled_sentinel_default_true` — env var absent → sentinel reads as `true`
- `test_walkforward_and_composition_order` — methodology gate always runs before walk-forward (order is enforced by the call sequence, not a flag)

All mocks must use `unittest.mock.patch` over `sqlite3` reads — no network calls, no live DB.

---

## Operational Notes

**Sentinel decision: `WALKFORWARD_GATE_ENABLED` default = `true` (Decision SP-WF-009).**
The R1-R8 v1 framework is already wired and operating in production. `outcome_state` values of FAIL and INCONCLUSIVE are already blocking promotion. Defaulting the sentinel to `false` would silently regress the gate that is already enforced. The sentinel exists for emergency soft-launch bypass (e.g., first post-retrain window where walkforward_results row is absent and the legacy `oos_efficiency` fallback is insufficient). The sentinel is an escape hatch, not the default state.

Env var: `WALKFORWARD_GATE_ENABLED` in `.env` / OS environment. Values `true` (default, absent = true) and `false`. Any other value raises `WalkForwardSentinelError` at import time.

**Operator override path:** set `WALKFORWARD_GATE_ENABLED=false` in `.env` before restarting the watch loop. NSSM restarts pick up the new env. Restore to `true` (or delete the var) after the bypass window. Override should be time-bounded; the operator runbook must document the expected restoration step.

**Refit cadence:** Per OOS window (Decision SP-WF-003) — one model refit per window boundary, not sub-window. The LoRA monthly retrain cadence (SD#34 / `docs/research/optimal-retraining-cadence-lora.md`) sets the floor at 30-50 new examples; that is the v2 training trigger, not the walk-forward refit trigger. Walk-forward runs are scored against a **frozen corpus snapshot** per window — the model weights used for each fold are recorded in `code_git_sha` and `spec_hash`. Sub-window refits are out of scope (they introduce a new form of IS/OOS leakage; Decision SP-WF-003 rationale).

**Run trigger:** walk-forward is not run on every promotion attempt. It is run on-demand via `scripts/backtest/run_walkforward.py` or manually via `python -m src.main run-walkforward <strategy_id>`. The CLI writes to `walkforward_results`; the promotion gate reads the latest row. Promotion attempts without a `walkforward_results` row fall back to the legacy `oos_efficiency` gate.

---

## File Inventory

| File | Status | Role |
|------|--------|------|
| `src/platform/rigor/walkforward_config.py` | EXTEND | Add `excess_sharpe_min_per_window` field + `_validate_sentinel()` |
| `src/platform/rigor/walkforward_metrics.py` | EXTEND | Replace raw Sharpe gate with excess-Sharpe gate |
| `src/platform/rigor/walkforward_runner.py` | EXTEND | Thread `corpus_id`; raise `CorpusNotBoundError` when unbound |
| `src/platform/rigor/walkforward_outcome.py` | READ-ONLY | Three-state reducer unchanged |
| `src/platform/rigor/walkforward_power.py` | READ-ONLY | MDE/power evaluator unchanged |
| `src/platform/rigor/walkforward_purging.py` | READ-ONLY | R2 purge + embargo unchanged |
| `src/platform/rigor/walkforward_costs.py` | READ-ONLY | R4 cost application unchanged |
| `src/platform/rigor/walkforward_firewall.py` | READ-ONLY | R8 firewall unchanged |
| `src/platform/rigor/walkforward_universe.py` | READ-ONLY | R3 point-in-time universe unchanged |
| `src/platform/rigor/walkforward.py` (legacy) | READ-ONLY | Pardo wrapper frozen; not deleted |
| `src/platform/promotion.py` | EXTEND | Add `_check_walkforward_sentinel()`; wire into AND-composed sequence |
| `src/evaluation/walkforward.py` | READ-ONLY | Stage-1 anchored harness frozen; not deleted |
| `scripts/backtest/run_walkforward.py` | READ-ONLY | CLI entry unchanged unless runner sig changes |
| `src/api/cloud_routes/walkforward.py` | READ-ONLY | Dashboard read route unchanged |
| `src/schema/registry.py` | EXTEND (conditional) | Only if excess-Sharpe column added to `walkforward_results` |
| `src/scheduler/holidays.py` | READ-ONLY | `subtract_trading_days` canonical helper |
| `src/methods/promotion_gate.py` | READ-ONLY | `_decide` voter unchanged |
| `tests/platform/rigor/test_walkforward_excess_sharpe.py` | NEW | 4 unit tests for new excess-Sharpe gate |
| `tests/platform/rigor/test_walkforward_integration.py` | NEW | 4 integration tests |
| `tests/platform/test_promotion.py` | EXTEND | 2 regression locks |

---

## Known Considerations

These are open methodological questions deferred to the impl sprint. They are NOT design decisions (those are in the table below) — they require resolution before impl tasks are written but do not block this spec.

1. **`walkforward_trades.excess_sharpe_observed` column existence.** The registry defines `sharpe_observed` per-trade in `walkforward_trades`. The impl sprint must confirm whether adding `excess_sharpe_observed` (rf-adjusted) is needed or whether the existing column is already rf-adjusted. Check `walkforward_metrics.py` computation path before opening a registry edit task.

2. **`cpcv` vs walk-forward for corpus-grounded runs.** `src/methods/cpcv.py:cpcv_anchored` and `src/evaluation/walkforward.py` both run fold-based validation on the same corpus. Their outputs are NOT combined — CPCV is a voter input; walk-forward is a gate. If both run on the same strategy-corpus pair, the impl sprint should document that they answer different questions (leakage vs regime-stability) and are not redundant.

3. **Legacy `oos_efficiency` fallback removal schedule.** When no `walkforward_results` row exists, the gate currently falls back to legacy `oos_efficiency >= 0.30`. This fallback is appropriate for strategies predating R1-R8 v1. The impl sprint should set a milestone for when the fallback is deprecated (e.g., after 3 months of R1-R8 v1 production runs, all active strategies should have a `walkforward_results` row).

4. **Shadow-portfolio bundling default.** Decision SP-WF-011 selects opt-in. The impl sprint must confirm that `--with-shadow` is plumbed through `scripts/backtest/run_walkforward.py` to `walkforward_runner.run_walkforward` without touching the runner's internal shadow logic (which mirrors `src/evaluation/walkforward.py` §A1.6 behavior).

5. **VIX-tier coverage computation.** `MIN_VIX_TIERS_REPRESENTED = 2` in `walkforward_config.py` requires a VIX-tier tagger per trade. If the corpus-grounded runner does not already tag VIX tier at ingest time, the impl sprint must add a lookup against the VIX data series. This is a data dependency that must be pre-verified before the runner-edit task starts.

---

## Design Decisions Table

| ID | Decision | Choice A | Choice B | Selected | Rationale | Falsifiability trigger |
|----|----------|----------|----------|----------|-----------|------------------------|
| SP-WF-001 | Window geometry | Fixed non-overlapping (R1 default: 5 windows, 2-year IS / 15-month OOS) | Anchored expanding (`src/evaluation/walkforward.py` Stage-1 harness) | **A** | R1 fixed windows are already in production, cover 2017–2024, and have defined regime diversity. Anchored expanding grows the IS set on every fold and cannot cleanly separate regime coverage. | If pooled OOS Sharpe variance across the 5 windows exceeds 0.5 SD, the regime-stability claim is falsified — revisit to adaptive windows. |
| SP-WF-002 | IS/OOS split ratio | R1 canonical 2-year IS / 15-month OOS (last window 9 months) | 80/20 split per-strategy | **A** | Consistent with the existing R1 default; changing the split mid-strategy cohort introduces non-comparability in `walkforward_results` history. | If ≥2 of 5 windows are INCONCLUSIVE_POWER (MDE cannot be measured in 15-month OOS span), the window length is too short — switch to 18-month OOS. |
| SP-WF-003 | Refit cadence | Per OOS window (one refit per window boundary) | Sub-window monthly (mirrors LoRA monthly retrain cadence) | **A** | Sub-window refits introduce a new IS/OOS leakage vector: the model can observe the beginning of the OOS window before the window ends. Per-window refit is clean. | If `code_git_sha` changes mid-window in any production run, the run is invalidated — log a `WalkForwardRefitViolation` and void the result. |
| SP-WF-004 | Per-window statistical gate | Excess-Sharpe ≥ 0.3 (rf-adjusted, consistent with methodology-toolkit voter) | Raw Sharpe ≥ 0.3 (current R1 constant `SHARPE_MIN_PER_WINDOW`) | **A** | MASTER.md SD#43 and the methodology-toolkit voter both operate on excess returns. Using raw Sharpe makes walk-forward inconsistent with the voter it AND-composes with. | If FRED DTB3 rf data is unavailable for a window date range, fall back to `rf=0.0001` per existing placeholder (log WARNING); if this occurs >1 window in a single run, void the run and require rf data before re-running. |
| SP-WF-005 | Cross-window acceptance criterion | ≥4-of-5 windows must pass Criterion 2 (`WINDOWS_PASSING_CRITERION_2 = 4`) | Unanimous (all 5 pass) | **A** | Mirrors the ≥4-of-5 logic of the methodology voter. Unanimous is too brittle given the 9-month last window (inherently lower power). The existing constant is already 4; this decision preserves it explicitly. | If the strategy passes walk-forward on exactly 4 windows AND the passing window set always excludes the same regime (e.g., always excludes the high-VIX window), the spec's regime-diversity claim is falsified — add regime-specific pass requirement. |
| SP-WF-006 | Module location for new code | Extend `src/platform/rigor/walkforward_*.py` in-place | Create new `src/methods/walkforward.py` shelf module | **A** | R1-R8 v1 is already wired, tested, and covers ~1,963 LOC. Creating a parallel module would require wiring in `promotion.py` while the R1 path still exists, causing a dual-path maintenance burden. | If the R1-R8 files collectively exceed 2,500 LOC post-impl, the split into a shelf module should be reconsidered to meet the repo LOC discipline. |
| SP-WF-007 | Gate persistence target | Reuse existing `walkforward_results` table (Choice A — `_evaluate_walkforward_gate` verbatim) | New `walkforward_v2_results` table with versioned schema | **A** | The existing table already carries all required fields (per §Data Model above). A versioned second table would require `_evaluate_walkforward_gate` to query both tables, adding a join path that does not exist today. | If the excess-Sharpe gate (SP-WF-004) requires a new column not present in the existing schema, the column must be added via registry before impl — not a new table. |
| SP-WF-008 | Vote contribution to `_decide` | Walk-forward adds a 6th vote to `promotion_gate._decide` (changes `_MIN_VOTES_TO_PROMOTE` semantics) | Walk-forward stays AND-composed at the orchestrator level (current state) | **B** | Collapsing walk-forward into the voter changes the semantics of `_MIN_VOTES_TO_PROMOTE` and risks a methodology FAIL being masked by a walk-forward PASS. AND-composition at the orchestrator preserves independent falsifiability. This is the PR #971 D5/D6 verified shape. | If the methodology voter produces "promote" on a strategy that walk-forward rejects, AND the operator elects to override walk-forward to promote — this pattern repeated ≥2× suggests the voter and walk-forward are measuring the same thing, and consolidation should be evaluated. |
| SP-WF-009 | Sentinel default | `WALKFORWARD_GATE_ENABLED=true` (on by default, blocking) | `WALKFORWARD_GATE_ENABLED=false` (soft-launch, logged non-blocking until first verified PASS) | **A** | R1-R8 v1 is already wired and already blocking on FAIL/INCONCLUSIVE. Defaulting to `false` would silently regress a gate that is currently enforced in production. The sentinel exists for emergency bypass, not default state. | If the first 3 strategies all return INCONCLUSIVE (not FAIL), the sentinel logic may need a `soft_launch` mode that counts INCONCLUSIVEs as non-blocking. Reassess at first 3 runs. |
| SP-WF-010 | Corpus binding requirement | `corpus_id` required for all promotion-grade runs (`corpus_id=None` raises) | `corpus_id=None` permitted, falls back to live LLM scoring per fold | **A** | Live LLM scoring is non-deterministic (model weights may change between folds), violating R5 (determinism). `corpus_id` binding ensures the fold scores are reproducible and auditable. `bootcamp_override=True` already forces `False` at config layer; this extends that discipline to corpus binding. | If a strategy's corpus window does not cover all 5 walk-forward windows (admissibility mismatch), the run must fail at `_gate_corpus_or_raise`, not silently use partial folds. |
| SP-WF-011 | Shadow-portfolio bundling | Every walk-forward run produces primary + deterministic-ranker shadow (always-on, mirrors §A1.6 #82) | Shadow opt-in via `--with-shadow` CLI flag (current `src/evaluation/walkforward.py` default) | **B** | Shadow doubles compute cost. Given walk-forward runs are infrequent (per-promotion-candidate) and operator-triggered, the cost is manageable — but it should be elective until the shadow diagnostic value is demonstrated over ≥3 walk-forward cycles. | If shadow `delta_excess_sharpe` is consistently near zero (< 0.05) across 3+ runs, the shadow is not adding diagnostic value and can be deprecated. |
| SP-WF-012 | Embargo geometry | Trading days via `subtract_trading_days` (canonical helper, 5 days per `walkforward_config.py`) | Calendar days or bilateral (purge IS side + embargo OOS side, R2 default) | **A** (trading days, bilateral purge already implemented) | R2 bilateral purge is the current R1-R8 v1 default — both the IS trailing `embargo_days` and the OOS leading `embargo_days` are already applied in `walkforward_purging.py`. The new framework keeps this unchanged. The key enforcement: `subtract_trading_days` must be used for the boundary computation, not `timedelta`. | If a backtest shows IS/OOS leakage despite the bilateral embargo (same trade appearing in both sides), the 5-day default is insufficient — raise to 21 days (matching `src/evaluation/walkforward.py` default) and re-run. |

---

## Do-Not-Do (this spec)

- Does **NOT** replace MC permutation. MC perm answers "are my labels random?"; walk-forward answers "is my edge regime-stable?" Both must pass. A strategy that passes walk-forward but fails MC perm is rejected.
- Does **NOT** bypass the Stage 2 excess-Sharpe ≥ 0.5 criterion over 150 OOS live trades (MASTER.md SD#43). Walk-forward is the gate BETWEEN Stage 1 admissibility and Stage 2 dispatch — a strategy that passes walk-forward is authorized to accumulate Stage 2 OOS trades; it is not declared Stage-2 complete.
- Does **NOT** vote into `promotion_gate._decide`. Walk-forward is AND-composed at the orchestrator level, not a 6th vote (Decision SP-WF-008).
- Does **NOT** use `timedelta(days=N)` or calendar-day approximations. All trading-day arithmetic goes through `src/scheduler/holidays.subtract_trading_days`.
- Does **NOT** mutate the corpus during runs. Corpus is admissibility-gated upstream; runs are read-only against `data/corpus/<corpus_id>/entries.jsonl`.
- Does **NOT** write DDL outside `src/schema/registry.py`. Any new column requires a registry-edit task in the impl sprint BEFORE the runner-edit task.
- Does **NOT** modify `src/evaluation/walkforward.py` (Stage-1 anchored harness), `src/platform/rigor/walkforward.py` (Pardo legacy), or `src/methods/promotion_gate.py` (4-of-5 voter). These are frozen READ-ONLY for this spec.
- Does **NOT** cover `design_decisions.json` — that companion file is impl-sprint scope.
- Does **NOT** cover the walk-forward plan (`walkforward-plan-v1.md`) — that is B3's deliverable.

---

## Falsifiability Triggers

The following observations, if seen in production, would void this spec and require a redraft:

1. **Regime-gate missing from methodology voter.** A strategy passes all 5 methodology votes (CPCV / block_bootstrap / mc_perm / psr_dsr / white_rc) BUT fails walk-forward with `reason='criterion_5_regime_coverage'` (VIX tier coverage below `MIN_VIX_TIERS_REPRESENTED = 2`). This is a structural gap: the methodology voter operates on a globally-pooled trade list with no regime segmentation. If this pattern occurs ≥2×, the voter is missing a regime check and the AND-composition spec needs revision to wire VIX-tier coverage into the voter (not just the walk-forward gate).

2. **Stage 2 OOS divergence from pooled Sharpe.** A strategy receives walk-forward `PASS` but its Stage 2 OOS excess Sharpe after 50 live trades is more than 2× below `walkforward_results.pooled_sharpe`. This signals either (a) the paper-vs-live ATR multiplier asymmetry (documented in `docs/methodology-toolkit.md` §"paper vs live target/stop multipliers") is larger than anticipated, or (b) the universe drifted and the cost model is stale. Either requires a spec re-open to tighten the cost model or add a live-vs-paper correction term.

3. **Multi-strategy promotions in the same calendar month.** More than one strategy receives walk-forward PASS in the same calendar month. Per the DSR search-burden penalty, this implies `n_trials` in `psr_dsr` is stale (it was set for the number of strategies searched to date). If this occurs, the DSR gate is underpenalized and the spec's independence-of-gates claim is weakened — recalculate `n_trials` and re-run DSR.

4. **Consecutive INCONCLUSIVE runs.** `walkforward_results.outcome_state` returns `INCONCLUSIVE` for ≥3 consecutive runs of the same `strategy_id`. This indicates either a coverage gap (the strategy does not generate enough trades per OOS window) or a power gap (`min_trades_per_window = 10` may be too high relative to the strategy's signal frequency). Spec re-open required to either relax `min_trades_per_window` or extend OOS window length (SP-WF-002 Choice B).

5. **Sentinel abuse.** `WALKFORWARD_GATE_ENABLED=false` is left active across ≥2 promotion cycles (strategy promoted without a walk-forward row). If this is observed, the sentinel default must be reconsidered — either enforce a hard time-limit on bypass duration or require an explicit bypass justification string (mirroring the `GATE_JUSTIFICATION_MIN_CHARS = 40` pattern in `promotion.py`).
