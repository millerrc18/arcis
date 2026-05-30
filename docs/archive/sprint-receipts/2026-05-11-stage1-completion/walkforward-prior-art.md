# Walk-Forward Framework — Prior-Art Review (Sprint S1-CC Batch B1)

**Date:** 2026-05-11
**Status:** Synthesis input to Batch B2 (spec drafting) + Batch B3 (plan drafting)
**Scope:** Inventory what already exists in the codebase + methodology corpus
            before any new spec is drafted. **No greenfield reinvention** — B2's
            spec must compose with the existing `walkforward_results` table,
            promotion-gate wiring, and the methodology-toolkit voter.
**Authority:** Sprint spec at `docs/audits/2026-05-11-stage1-completion/sprint-spec.md`

---

## Revision history

| Date       | Change |
|------------|--------|
| 2026-05-11 | Initial synthesis (B1). |

---

## 1. Walk-forward components — WIRED vs SHELF

The codebase has **two parallel walk-forward implementations** that grew at
different times for different purposes. Any new framework MUST acknowledge both
and decide how to compose with them — neither is deletable in B3's scope.

### 1.A `src/evaluation/walkforward.py` — Anchored expanding, Stage-1 pre-reg §3

- **Status:** WIRED (CLI entrypoint + invoked by Stage-1 backtest_model harness).
- **Methodology:** Anchored expanding window — `train_anchor` fixed to `_COVERAGE_START`
  (`2015-03-19`); `train_end` slides forward per fold. Default 8 folds × ~4 months
  from `2023-09-01` anchor, 21-trading-day embargo.
- **Public surface:**
  - `compute_fold_boundaries(anchor, fold_count, embargo_days)` → list of fold dicts
  - `run_walkforward(model, anchor, fold_count, embargo_days, output_json,
    corpus_id, with_shadow)` → flat-shape `dict` OR `{primary,shadow,delta}` dict
  - `compute_aggregate(folds)` → primary Sharpe + t-stat over powered folds only
  - `_run_fold` / `_gate_corpus_or_raise` / `_compute_shadow_delta` / `_build_flat_result`
    / `_assemble_with_shadow_result` (private helpers)
  - `main()` + `_build_parser()` (CLI)
- **Notable params (defaults):**
  - `_UNDERPOWERED_THRESHOLD = 15` (per fold)
  - `_DEFAULT_FOLD_COUNT = 8`
  - `_DEFAULT_EMBARGO_DAYS = 21` trading days
  - `_DEFAULT_ANCHOR = "2023-09-01"`
  - `_COVERAGE_START = "2015-03-19"`
- **Corpus gate (pre-reg §A3):** `_gate_corpus_or_raise(corpus_id, boundaries)` loads
  the corpus manifest and asserts (a) admissibility + (b) every fold's test window is
  inside the corpus window, BEFORE any folds run.
- **Deterministic-ranker shadow (#82, pre-reg §A1.6, listed in
  `config/known_violations.json` line 142 — 431-line waiver):** when
  `with_shadow=True`, runs the primary AND a deterministic-ranker shadow over the
  SAME fold boundaries with the SAME corpus, returns `{primary, shadow, delta}`
  where `delta` contains `delta_excess_sharpe`, `delta_total_pnl_pct`, and trade
  count deltas. The shadow is a *secondary diagnostic* — does the LLM filter add
  signal over a deterministic ranker? — not a vote into the gate.

### 1.B `src/platform/rigor/walkforward.py` (legacy) + `src/platform/rigor/walkforward_*` (R1-R8 v1)

- **Status:** Both WIRED, but to *different* promotion-gate paths.
  - The legacy `src/platform/rigor/walkforward.py` is the Pardo-2008 rolling
    wrapper. `_run_one_fold` + `_compute_efficiency` + `run_walkforward()`
    return `oos_efficiency = mean_OOS_SR / mean_IS_SR` with `OVERFIT_THRESHOLD = 0.30`.
    Caller path: `src/platform/promotion.py` legacy gate reads `oos_efficiency`
    from a stored backtest row when no `walkforward_results` row exists for the
    strategy.
  - The R1-R8 v1 framework (`walkforward_config.py`, `walkforward_runner.py`,
    `walkforward_metrics.py`, `walkforward_power.py`, `walkforward_purging.py`,
    `walkforward_costs.py`, `walkforward_firewall.py`, `walkforward_outcome.py`,
    `walkforward_universe.py`) ships a **three-state outcome state machine** —
    `PASS` / `FAIL` / `INCONCLUSIVE` — that persists to the `walkforward_results`
    table. Caller: `_evaluate_walkforward_gate(strategy_id, db_path, evidence)`
    in `src/platform/promotion.py`. Runner CLI: `scripts/backtest/run_walkforward.py`;
    HTTP read route: `src/api/cloud_routes/walkforward.py`.
- **R1-R8 v1 public surface** (per `docs/sprints/SPRINT_walkforward_validation_v1.md`):
  - `WalkForwardConfig` dataclass — strategy_id, windows (default 5 non-overlapping
    OOS spans 2019-01 → 2024-09), universe_tag, embargo_days (default `5` trading
    days), per_side_cost_bps (default `0.5`), random_seed (default `42`), alpha
    (`0.05`), power (`0.80`), heavy_tail_se_ratio (`1.5`), bootstrap_resamples
    (`10_000`), sharpe_min (`0.3`), mde_max (`0.3`), pooled_sharpe_min (`0.5`),
    max_drawdown_cap_pct (`0.20`), min_trades_per_window (`10`), min_vix_tiers (`2`),
    min_window_duration_days (`365`), bootcamp_override (forced `False`).
  - `WalkForwardWindow` (frozen dataclass) — train_start/end + test_start/end with
    validation `train_end < test_start` (no IS/OOS leakage).
  - `reduce_outcome(window_states, max_drawdowns, pooled_sharpe, distinct_vix_tiers,
    pooled_sharpe_min, max_drawdown_cap_pct, min_vix_tiers,
    windows_passing_criterion_2, inconclusive_window_threshold)` → `OutcomeResult`.
  - `run_walkforward(strategy_spec_raw, config, window_trades, ...)` → in-memory
    `WalkForwardRunResult`.
  - `persist_run_result(result, strategy_spec_raw, oos_trades_per_window, db_path)` —
    writes `walkforward_results` + `walkforward_trades` rows. Idempotent
    (primary key replace).
- **R1 default windows (canonical v0.25.0):** 5 windows, each 2-year IS / 15-month OOS,
  spanning 2017-01-01 IS-start → 2024-09-30 OOS-end (last window is 9 months
  because of data cutoff).
- **Methodology promotion gate sub-thresholds (constants in `walkforward_config.py`):**
  - `SHARPE_MIN_PER_WINDOW = 0.3`
  - `MDE_MAX_PER_WINDOW = 0.3` at 80% power
  - `POOLED_SHARPE_MIN = 0.5`
  - `MAX_DRAWDOWN_CAP_PCT = 0.20`
  - `MIN_TRADES_PER_WINDOW = 10`
  - `MIN_VIX_TIERS_REPRESENTED = 2` (low <15, medium 15-25, high >25)
  - `MIN_WINDOW_DURATION_DAYS = 365` (#538 v0.25.4 — distinguishes "window too short"
    from "strategy didn't signal")
  - `WINDOWS_PASSING_CRITERION_2 = 4` (≥4-of-5 windows must satisfy Criterion 2)
  - `INCONCLUSIVE_WINDOW_THRESHOLD = 2` (≥2 windows in `INCONCLUSIVE_*` → run
    INCONCLUSIVE overall)
- **R8 firewall** (`walkforward_firewall.py`): every strategy spec must declare
  `derived_from` (or explicit `null`); `assert_no_overlap` raises `R8ViolationError`
  if the source-trade date range overlaps any OOS window; bootcamp_override forced
  False; runtime heuristic WARNs if `derived_from == null` AND spec first-commit is
  within 30 days of a forensic audit on the same strategy family.

### 1.C `src/methods/cpcv.py` — Anchored CPCV (shelf, methodology-toolkit only)

- **Status:** SHELF — called by the 4-of-5 voter as one of its 5 votes
  (`promotion_gate._decide → _run_cpcv`); not directly invoked outside the voter.
- `cpcv_anchored(returns, k, embargo, rf_period)` — anchored variant where each
  fold's training window is pinned to start at index 0 (window grows monotonically).
  Returns `{fold_sharpes, fold_indices}`.
- `cpcv_with_fred_rf` / `cpcv_anchored_with_fred_rf` — Sprint-0 Wave-3b RF-WIRING
  siblings; take per-period dates and pull FRED DTB3 per-period rf before
  excess-Sharpe computation.
- **Use within the voter:** per-fold OOS Sharpes are averaged; vote passes if the
  mean is positive at α=0.05 (see `_run_cpcv` in `promotion_gate_helpers.py`).
  This is NOT the same construct as `src/evaluation/walkforward.py` — different
  fold geometry, different stopping rules, different output shape.

---

## 2. How walk-forward composes with the methodology-toolkit gate

**Answer:** Walk-forward is a **separate gate** that **AND-composes** with the
4-of-5 voter — it does NOT feed votes into `promotion_gate._decide`. The actual
call sequence in `src/platform/promotion.py:evaluate_promotion_gate` for
`target='shadow_trading'`:

```
1. evaluate_strategy_methodology_gate(strategy_id, db_path)
     ↳ runs the 5-of-5 voter (CPCV / block_bootstrap / mc_perm / psr_dsr / white_rc)
       on the strategy's per-trade excess-return series, returns
       (passes_methodology_gate, mg_evidence).
   If methodology gate FAILS:
     return (False, evidence)  ← gate already False; never collapse.

2. _evaluate_walkforward_gate(strategy_id, db_path, evidence)
     ↳ reads the LATEST walkforward_results row for this strategy_id
       (ORDER BY created_at DESC LIMIT 1).
     ↳ Three-state response:
         outcome_state='PASS'         → wf_pass=True;  keep checking DSR.
         outcome_state='FAIL'         → wf_pass=False; evidence['error']=
                                        'walkforward_failed';  return (False, …).
         outcome_state='INCONCLUSIVE' → wf_pass=False; evidence['error']=
                                        'walkforward_inconclusive'; return (False, …).
         no row found                  → wf_pass=None; fall back to legacy
                                        oos_efficiency gate.

3. DSR + PBO + (legacy oos_efficiency if step 2 returned None).
```

The five vote keys consumed by `_decide` are
`cpcv` / `block_bootstrap` / `mc_perm` / `psr_dsr` / `white_rc` — note `cpcv`
is NOT a walk-forward window vote; it is the CPCV-anchored fold-Sharpe vote.
Walk-forward is wired one level up, in the gate orchestrator that runs BOTH
the 5-of-5 voter AND the walk-forward gate AND the DSR gate, AND-composed.

This composition is verified shape from PR #971 v5 — the D5/D6 patterns referenced
in the sprint spec. The methodology gate's structured failure preserves the FAIL
reason from `mg_evidence`; the walk-forward gate's structured failure preserves
`walkforward_outcome_state` + `walkforward_reason` + `walkforward_run_id` for
dashboard read-through.

**Implication for the new framework (B2):** the new framework must EITHER

- **(A)** plug into the existing `walkforward_results` table (write a new
  `outcome_state` per run), reusing `_evaluate_walkforward_gate` verbatim and
  the persistence path in `walkforward_runner.persist_run_result`, OR
- **(B)** define a NEW outcome shape and modify `_evaluate_walkforward_gate` to
  read either old or new shape (versioned).

Default to (A) unless B2 finds a structural reason the existing shape is
insufficient. The existing shape already supports per-window state, pooled
Sharpe, pooled MDE, heavy-tail flag, regime coverage — these cover most of the
methodology requirements.

---

## 3. Existing parameters / config keys / sentinels the new framework MUST honor

### 3.1 Trading-day arithmetic (CANONICAL)

- `subtract_trading_days(anchor: date, n: int) -> date` from
  `src/scheduler/holidays.py` — NYSE-calendar-aware via `pandas_market_calendars`.
  CLAUDE.md explicitly forbids `timedelta(days=365)` or other calendar-day
  approximations for fetch anchors and lookback windows. **The new framework
  MUST use this helper for all "N trading days before X" computations.**
- Note: `src/evaluation/walkforward.py` has its own `_subtract_trading_days`
  (lines 66-74) that walks day-by-day; this predates the canonical helper and
  is on the cleanup-rollup list. New code should call the canonical helper.

### 3.2 Persistence (tables, no greenfield DDL)

- `walkforward_results` table — already defined in `src/schema/registry.py`,
  carries `run_id`, `strategy_id`, `spec_hash`, `code_git_sha`, `random_seed`,
  `config_json`, `outcome_state`, `reason`, `pooled_sharpe`, `pooled_mde`,
  `heavy_tail_flag`, `heavy_tail_window_count`, `n_windows*`, `derived_from_*`,
  `effective_universe_size`, `max_drawdown_pct`, `vix_tier_coverage`, `created_at`.
- `walkforward_trades` table — per-trade detail with `window_index`,
  `is_in_is_window`, `vix_tier`, `purged`, `embargoed`, `sharpe_observed`,
  `bootstrap_se`, `mde_value`.
- **Schema discipline (CLAUDE.md MANDATORY):** any new column MUST go through
  `src/schema/registry.py`; no `CREATE TABLE` or `ALTER TABLE` outside the
  registry. If the new framework needs new columns, B3 task list must include a
  registry-edit task BEFORE the runner-edit task.

### 3.3 Default thresholds (constants in `walkforward_config.py`)

The 9 constants enumerated in §1.B above (sharpe_min, mde_max, pooled_sharpe_min,
max_drawdown_cap_pct, min_trades_per_window, min_vix_tiers, min_window_duration_days,
windows_passing_criterion_2, inconclusive_window_threshold). New framework must
either (a) keep these defaults verbatim and document the rationale, or (b)
explicitly override them with a B2 design-decision-table entry justifying the
override.

### 3.4 Sentinels (env vars / feature flags)

- **`WALKFORWARD_GATE_ENABLED` does NOT exist in src/ today.** Confirmed via grep
  — the only references are in spec docs at
  `docs/audits/2026-05-11-stage1-completion/sprint-spec.md` and the design-raw JSON
  for modified-A migration. **B3 is responsible for choosing the default
  (true/false) and documenting the rationale.** A safe default given the framework
  is already wired and operating (FAIL/INCONCLUSIVE outcomes are already
  blocking promotion) is `true` — but B3 should consider whether a sprint-spec-style
  "off-by-default until first PASS observed" pattern is safer for the cutover.
- `bootcamp_override` — forced `False` at config layer; runner asserts. (R8(d)
  defense-in-depth.)
- `random_seed` — default `42`; propagated into `WalkForwardConfig` and recorded
  per-run in `walkforward_results.random_seed`. (R5 — determinism.)

### 3.5 Corpus admissibility (Stage 1 → Stage 2 bridge)

- `_gate_corpus_or_raise(corpus_id, boundaries)` in `src/evaluation/walkforward.py`
  is the existing pattern — load corpus manifest, assert `is_admissible()`, assert
  every fold's test range is inside `[walkforward_window_start, walkforward_window_end]`.
- Stage 1 corpus `stage1-001` is admissible (§B2 PASS, 67,528 entries). New
  framework MUST honor this gate when corpus-grounded scoring is used.

### 3.6 Anchored vs rolling — current state

- `src/evaluation/walkforward.py` → **anchored expanding** (train_anchor fixed
  at coverage_start). This is the Stage-1 pre-reg §3 canonical methodology.
- `src/platform/rigor/walkforward.py` → **rolling** (train_start slides every
  `test_years`). This is the Pardo-2008 legacy wrapper. Default
  `train_years=3, test_years=1`.
- `src/platform/rigor/walkforward_config.py:DEFAULT_WINDOWS` → **fixed
  non-overlapping** (explicit window list, 5 windows). Neither pure-anchored nor
  pure-rolling — it's the operator-pinned R1 set from v0.25.0.
- **B2 must explicitly choose** which geometry the new framework uses — see §4 D5.

### 3.7 Retrain cadence context (for OOS interpretation)

- `docs/research/optimal-retraining-cadence-lora.md` (#1): **monthly retrain from
  the original Qwen3 8B base** when ~30-50 new examples have accumulated.
  Weekly retrains on 5-10 new examples are below the noise floor; quarterly is
  reliably measurable. Hybrid trigger: canary-perplexity >8% for 2 consecutive
  weeks OR ≥20 new examples OR 6-week time-ceiling OR regime override (VIX spike
  >30% weekly).
- **Implication for walk-forward:** OOS windows must be long enough to cover at
  least one model-version (i.e. one retrain cycle's worth of behavior). The
  existing `MIN_WINDOW_DURATION_DAYS = 365` floor matches this comfortably; the
  shorter "8 folds × ~4 months" in `src/evaluation/walkforward.py` is below the
  floor and is appropriate for Stage-1 corpus-grounded validation only (it tests
  the LLM packet's signal, not the post-retrain model behavior).

---

## 4. Open methodological questions for the operator (B2 §Design Decisions input)

The questions below are the seed list for B2's §Design Decisions Table. Each is
phrased as "Choice A vs Choice B" per sprint-spec hard requirement.

- **D1 — Window geometry.** Anchored expanding (`src/evaluation/walkforward.py`)
  vs rolling (`src/platform/rigor/walkforward.py`) vs fixed non-overlapping
  (`walkforward_config.DEFAULT_WINDOWS`)? Each is currently in production for a
  different code path; the new framework must pick one as the canonical.
- **D2 — Window length / IS-OOS split.** R1 canonical is 2-year IS / 15-month OOS
  (last 9 months). Stage-1 `evaluation/walkforward.py` is anchor-to-now / fold-by-4-months.
  Should the new framework keep R1 windows (2:1.25 ratio) or move to a different
  ratio (e.g., 80/20, 75/25)? Per-strategy or fixed?
- **D3 — Refit cadence.** Per OOS window (refit once per window) vs sub-window
  (e.g., monthly within the OOS span, mirroring the LoRA retrain cadence)?
  Important when the strategy is the LLM, not a fixed rule.
- **D4 — Statistical gates per window.** Keep `Sharpe ≥ 0.3 AND MDE ≤ 0.3`
  (R1 default) vs separate excess-Sharpe threshold (the methodology-toolkit
  uses excess-Sharpe, not raw Sharpe — Stage 2 spec already requires
  excess-Sharpe ≥ 0.5 over 150 OOS trades per MASTER.md SD#43). Should the
  per-window gate also be excess-Sharpe-based for consistency?
- **D5 — Acceptance criteria across windows.** ≥4-of-5 (R1 default), majority,
  or unanimous? Sprint spec asks the question explicitly. The 4-of-5 threshold
  mirrors the methodology-gate voter intentionally (physics-multi-source robustness
  argument). Unanimous is too brittle; majority is too permissive.
- **D6 — Anchored vs rolling for the canonical.** D1 picks the geometry; D6 is
  the alternative — if D1 picks "fixed non-overlapping," D6 asks whether to ALSO
  support anchored as a `WalkForwardConfig` mode for non-S&P-100 strategies or
  ones with shorter coverage history.
- **D7 — Composition with the existing promotion gate.** Reuse
  `_evaluate_walkforward_gate` verbatim (Choice A) vs version the gate to read
  EITHER `walkforward_results.outcome_state` OR a new `walkforward_v2_results`
  table (Choice B). Per §2, Choice A is the recommended default unless B2 finds
  a structural reason for B.
- **D8 — Vote contribution to `_decide`.** Does walk-forward add a 6th vote to
  the 4-of-5 voter (Choice A — changes `_MIN_VOTES_TO_PROMOTE`), or does it
  stay as a separate AND-composed gate (Choice B — current state)? §2 already
  answers "currently B"; D8 is whether to change that.
- **D9 — Feature-flag default.** `WALKFORWARD_GATE_ENABLED=true` (Choice A —
  on by default, blocking) vs `=false` (Choice B — soft-launch, logged but
  non-blocking until first verified PASS). Sprint-spec asks this explicitly in
  B3 ("Sentinel decision").
- **D10 — Corpus binding.** Does the new framework REQUIRE a `corpus_id` (Choice
  A — Stage-1 grounded, no live LLM calls during walk-forward) or allow
  `corpus_id=None` (Choice B — falls back to live LLM scoring per fold)? Live
  LLM is non-deterministic; R5 (determinism) effectively forces Choice A for
  promotion-grade runs.
- **D11 — Shadow-portfolio bundling.** Does every walk-forward run produce a
  primary + deterministic-ranker shadow (Choice A — mirrors §A1.6 #82
  current behavior) or is shadow opt-in via `--with-shadow` (Choice B —
  current `src/evaluation/walkforward.py` default)? Shadow doubles compute
  cost.
- **D12 — Embargo geometry.** Trading days (5 in `walkforward_config.py`; 21
  in `src/evaluation/walkforward.py`) vs calendar days vs bilateral (purge IS
  side + embargo OOS side, R2 default)? R2 default is the current pattern;
  D12 asks whether the new framework keeps it.

---

## 5. Falsifiability triggers (for B2's §Falsifiability Triggers section)

These are observations that, if seen, should force a re-open of the spec:

- A strategy passes all 5 methodology votes BUT fails walk-forward, AND the
  walk-forward FAIL reason is "criterion_5_regime_coverage" — strong signal that
  the methodology gate is missing a regime check (currently it has none — the
  voter operates on a globally pooled trade list).
- A strategy passes walk-forward `PASS` but Stage 2 OOS performance differs by
  >2× from the pooled Sharpe — signal that the cost model is wrong (paper vs live
  multiplier asymmetry per methodology-toolkit doc §"paper vs live target/stop
  multipliers") or that the universe drifted.
- More than one strategy passes walk-forward in the same calendar month — needs
  re-evaluation of search-burden penalty (n_trials in DSR may be stale).
- `walkforward_results.outcome_state` collapses to `INCONCLUSIVE` for >3
  consecutive runs of the SAME strategy_id — indicates either coverage gap or
  power gap; needs spec re-open to relax `min_trades_per_window` OR extend
  windows.

---

## 6. DO-NOT-DO (B2 must echo)

- Walk-forward does NOT replace MC permutation. MC perm answers "are my labels
  random?"; walk-forward answers "is my edge regime-stable?" Both must run.
- Walk-forward does NOT bypass Stage 2 OOS criteria (excess Sharpe ≥ 0.5 over
  150 OOS live trades). Walk-forward is the bridge BETWEEN Stage 1 admissibility
  and Stage 2 dispatch; it is not a substitute for either.
- Walk-forward does NOT vote into `_decide`. Per §2, it AND-composes with the
  voter at the orchestrator level.
- Walk-forward does NOT use `timedelta(days=365)` or any other calendar-day
  approximation. All trading-day arithmetic goes through
  `src/scheduler/holidays.subtract_trading_days`.
- Walk-forward does NOT mutate the corpus during runs. Corpus is admissibility-gated
  upstream; runs are read-only against `data/corpus/<corpus_id>/entries.jsonl`.
- Walk-forward does NOT write DDL outside `src/schema/registry.py`. If new columns
  are needed, B3 must include a registry-edit task ahead of the runner-edit task.

---

## 7. File inventory (for B2 §File Inventory section)

| File                                                  | Status | Role in new framework |
|-------------------------------------------------------|--------|-----------------------|
| `src/evaluation/walkforward.py`                       | WIRED  | Stage-1 anchored harness; B2 decides keep / rename / remove |
| `src/platform/rigor/walkforward.py`                   | WIRED  | Legacy Pardo wrapper; B2 decides keep / deprecate |
| `src/platform/rigor/walkforward_config.py`            | WIRED  | R1-R8 v1 config; B2 reuses or supersedes |
| `src/platform/rigor/walkforward_runner.py`            | WIRED  | R1-R8 v1 orchestrator + persistence |
| `src/platform/rigor/walkforward_outcome.py`           | WIRED  | Three-state reducer; B2 reuses or supersedes |
| `src/platform/rigor/walkforward_metrics.py`           | WIRED  | Per-window Sharpe / SE / MDE inputs |
| `src/platform/rigor/walkforward_power.py`             | WIRED  | MDE + power-gate evaluator |
| `src/platform/rigor/walkforward_purging.py`           | WIRED  | R2 purge + embargo |
| `src/platform/rigor/walkforward_costs.py`             | WIRED  | R4 per-side cost application |
| `src/platform/rigor/walkforward_firewall.py`          | WIRED  | R8 firewall (derived_from + overlap assertion) |
| `src/platform/rigor/walkforward_universe.py`          | WIRED  | R3 point-in-time universe |
| `src/platform/promotion.py:_evaluate_walkforward_gate`| WIRED  | Reads `walkforward_results`; AND-composes |
| `scripts/backtest/run_walkforward.py`                 | WIRED  | CLI wrapper for runner |
| `src/api/cloud_routes/walkforward.py`                 | WIRED  | Dashboard read route |
| `src/methods/cpcv.py`                                 | SHELF→VOTER | Anchored CPCV; consumed by `_run_cpcv` vote |
| `src/methods/promotion_gate.py`                       | WIRED  | 4-of-5 voter (separate from WF gate) |
| `src/scheduler/holidays.py:subtract_trading_days`     | WIRED  | Canonical trading-day arithmetic |

Total walk-forward LOC under `src/platform/rigor/walkforward_*`: ~1,963.
Total Stage-1 anchored harness in `src/evaluation/walkforward.py`: 431 (waived in
`config/known_violations.json` line 142).

---

## 8. Cross-references

- Sprint spec: `docs/audits/2026-05-11-stage1-completion/sprint-spec.md`
- Methodology toolkit decision tree: `docs/methodology-toolkit.md`
- R1-R8 v1 spec: `docs/sprints/SPRINT_walkforward_validation_v1.md`
- v0.25.0 evaluation: `docs/sprints/walkforward_v1_evaluation.md`
- v0.25.0 research findings: `docs/sprints/walkforward_v1_research_findings.md`
- Stage-1 pre-registration §3 (anchored expanding):
  `docs/research/pre-registration-stage1.md` + addenda
- Retrain cadence research: `docs/research/optimal-retraining-cadence-lora.md`,
  `docs/research/Preventing_Model_Degradation_in_Iterative_QLoRA_Retraining__Data_Accumulation__Golden_Ratio_Mixing__and_Champion-Challenger_Evaluation.md`
- Promotion-gate composition (PR #971 v5 D5/D6 patterns):
  `src/platform/promotion.py:evaluate_promotion_gate` (target=`shadow_trading`).
- `known_violations.json` waivers tied to walk-forward:
  - line 142: `src/evaluation/walkforward.py` 431 lines (#82 shadow-ranker)
  - lines 735-742: `walkforward_runner.persist_run_result` 95 lines + `run_walkforward` 105 lines
