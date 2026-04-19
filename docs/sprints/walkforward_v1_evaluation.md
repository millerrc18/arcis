# Walk-Forward Validation v1 — Pass 1 Evaluation

**Sprint:** `feat/walkforward-validation-v1` / cloud branch
`claude/walkforward-validation-v1-IpQw2`
**Target tag:** v0.25.0
**Spec:** `docs/sprints/SPRINT_walkforward_validation_v1.md`
**Pass:** 1 of 3 (pre-code evaluation).

## Purpose

This Pass 1 evaluation exists to force all design decisions above the
waterline before writing any code. Per Ralph Loop discipline, Pass 2 is
research findings before implementation; Pass 3 is self-review after
implementation. Pass 1's job is to expose risks, satisfaction maps, and
decisions the operator may want to revisit — so no multi-commit coding
effort proceeds on a shaky foundation.

Cloud-execution mode: commit-and-continue. Operator reviews retrospectively.

---

## R1–R8 satisfaction map

### R1 — Window design

- **Plan.** Hardcode the five default windows in
  `src/platform/rigor/walkforward_config.py` as a constant `DEFAULT_WINDOWS:
  list[WalkForwardWindow]`. `WalkForwardConfig` accepts `windows=None` and
  substitutes defaults when None. Tests (commit 2) check default count = 5,
  each window is 15 months (last 9), zero overlap between OOS windows, and
  IS windows correctly flank each OOS.

### R2 — Purge + embargo

- **Plan.** `src/platform/rigor/walkforward_purging.py` exposes two pure
  functions: `purge_is_trades(is_trades, oos_start, oos_end)` removes trades
  whose `[entry_date, exit_date]` interval overlaps `[oos_start, oos_end]`;
  `embargo_oos_trades(oos_trades, oos_start, oos_end, embargo_days=5)`
  removes trades with `entry_date <= oos_start + embargo_days` (trading days,
  Mon-Fri).  Unit tests exercise every boundary combination (before/after/
  straddle).

### R3 — Point-in-time universe

- **Plan.** Three-layer design:
  1. `data/reference/sp100_historical.csv` — curated CSV of additions /
     removals sourced from S&P Dow Jones press releases and Wikipedia
     index-change tables. Columns: ticker, added_date, removed_date,
     company_name, reason.
  2. `src/platform/rigor/walkforward_universe.py` — `load_constituents()`
     loads the CSV into the `sp100_historical_constituents` table (idempotent),
     and `resolve_universe_as_of(date: str) -> list[str]` returns the set of
     tickers whose `added_date <= date < (removed_date or infinity)`.
  3. `src/platform/data_loader.py` — `load_universe_as_of` grows a new
     optional parameter that routes to the new resolver when invoked by
     walk-forward runner.  Existing callers keep current behavior (soft
     migration).

### R4 — Transaction costs

- **Plan.** `src/platform/rigor/walkforward_costs.py` exposes
  `apply_per_side_cost(trade, per_side_bps)` that returns a new trade with
  `entry_price *= (1 + bps/1e4)` and `exit_price *= (1 - bps/1e4)` and
  recomputed `pnl_pct`. Default `per_side_bps = 0.5`; round-trip = 1.0 bp.
  This is additive to whatever the underlying `backtest_engine` has
  already charged; the walk-forward runner passes `commission_bps=0`,
  `slippage_bps=0`, `spread_bps=0` to the engine and applies costs
  uniformly at the walk-forward level.

### R5 — Determinism

- **Plan.** `WalkForwardConfig` has `random_seed: int = 42`. Runner
  propagates it into `BacktestConfig.random_seed` for every IS/OOS
  invocation. Spec hash, code git SHA, data cutoff, seed all persist to
  `walkforward_results` row. Tests assert identical runs produce identical
  structural metrics.

### R6 — Three-state outcome + MDE gate

- **Plan.** Two modules:
  - `walkforward_power.py`: `compute_mde(trades, sharpe, max_hold_days,
    alpha=0.05, power=0.80) -> dict{mde, se_parametric, se_bootstrap,
    n_effective, heavy_tail_flag}`. Newey-West lag = max holding period
    reduces N_effective by the autocovariance correction factor. Bootstrap
    uses `src/diagnostics/bootstrap.py` at 10k resamples; heavy-tail flag
    fires if `se_bootstrap > 1.5 * se_parametric`, and in that case
    `mde` is recomputed using `se_bootstrap` in place of `se_parametric`.
    Reuses `src/diagnostics/power.py:cell_mde` for the z/t arithmetic.
  - `walkforward_metrics.py`: per-window Sharpe, pooled Sharpe, per-window
    MDE, per-window max drawdown, regime bucket (VIX tier) assignment.
- **Outcome state logic** lives in `walkforward_runner.py` (commit 9) and is
  the five-step chain from the spec. Criteria 1-5 return per-criterion
  `(passed: bool, reason: str)` pairs; the outcome is derived from those
  in a single deterministic reducer.

### R7 — Deterministic record-keeping

- **Plan.** Schema includes `code_git_sha`, `spec_hash`, `random_seed`,
  `config_json`. Runner computes spec hash via `src.platform.strategy_spec`
  hash machinery (same as existing backtest_engine uses at `_reproducibility_dict`).

### R8 — Strategy identity firewall + runtime heuristic

- **Plan.** `src/platform/rigor/walkforward_firewall.py` exposes:
  - `validate_derived_from(spec_raw: dict)` — raises if `derived_from` key
    missing (required field). If value is a non-null dict, validates
    structure (source_type in {forensic_audit_ruleset, bootcamp_backtest,
    shadow_trading_cohort, other}; source_date_range has start+end ISO).
  - `assert_no_overlap(derived_from: dict | None, windows: list[WalkForwardWindow])`
    — no-op if None; else iterates the single source_date_range and each
    OOS window; raises `R8ViolationError` on any overlap.
  - `force_bootcamp_off(engine_config)` — returns a shallow copy with
    bootcamp-affecting flags set to False / absent. The current engine
    doesn't accept `bootcamp_mode` directly; instead it reads bootcamp
    state from config (`src/services/bootcamp_state.py`). We inject a
    context-local override using an explicit parameter added to
    `BacktestConfig` (backward-compatible default False — same effective
    behavior as today).
  - `check_provenance_heuristic(spec_path: str, spec_raw: dict,
    db_path: str) -> list[str]` — returns a list of WARNING strings. For
    each forensic-audit run in the audit log with a strategy family string
    matching the spec's `strategy_id` prefix within 30 days of the spec
    file's first git commit timestamp AND `derived_from == null`, emit
    one warning. Heuristic is non-blocking — runner prints warnings and
    continues.

## Identified risks

1. **Data availability.** yfinance + `daily_bars` back to 2019 is broad and
   stable; risk is low for S&P 100 tickers. Pass 2 will audit actual
   coverage. Boundary cases (IPOs, delistings) are handled by the
   point-in-time resolver — trades on delisted tickers will simply not be
   generated after their `removed_date`.

2. **Point-in-time universe accuracy.** Hardcoded CSV is the weakest link.
   Mitigation: the CSV is versioned + reviewed; commit 3 tests verify the
   resolver on three known transition dates (e.g., TSLA joining S&P 100
   in 2020, FB→META rename).

3. **Numerical stability at small OOS N.** The Lo 2002 SE formula blows up
   at `1 + 0.5 * Sharpe^2` for very high Sharpe + tiny N. Tests (commit 7)
   assert: N=20, Sharpe=0.4 gives MDE > 0.3 → INCONCLUSIVE_POWER.
   N=200, Sharpe=0.25 gives MDE ≤ 0.3 but Sharpe < 0.3 → FAIL.
   N=200, Sharpe=0.35 gives PASS.  The bootstrap SE fallback handles
   heavy-tailed distributions where parametric SE under-estimates.

4. **Boundary effects at 2020 COVID and 2022 rate-hike regime breaks.**
   Windows 2 and 4 both straddle an acknowledged regime break. This is by
   design — walk-forward must test through these. Risk is that a valid
   strategy legitimately fails in the straddle window. Criterion 2 allows
   1 of 5 to fail before FAIL overall; this is the intended ≥4/5 threshold.

5. **`known_events.py` 2019–2024 tariff coverage.** Currently covers
   March-April 2026 only. Pass 2 audits whether the module is referenced
   by the walk-forward runner (it is — regime-conditional metrics use
   event categories). If sparse, this is documented as a separate
   prerequisite sprint per the non-goals list; non-blocking for v0.25.0
   because the regime-bucket dimension already exists without event-level
   annotation.

6. **Heavy-tail return distributions.** Real-world trade returns at N=30–100
   frequently exceed the parametric Gaussian assumption. Mitigation is
   the bootstrap SE sanity check (R6). Risk: 10k resamples on every window
   multiplies runtime. Commit 6 measures runtime and, if >30s per window
   at N=200, we reduce to 2k resamples (a deviation from R6's 10k number;
   would require operator sign-off, documented in commit message).

7. **Three-state outcome propagation through the stack.** The most subtle
   failure mode is silent collapse of INCONCLUSIVE to FAIL. Pass 3 audit
   item #4 is an explicit trace of all three states through
   runner → results table → `check_promotion_gate` → dashboard. Tests at
   commits 9, 10, and 13 each exercise at least one INCONCLUSIVE path
   to keep the wiring honest.

8. **`BacktestConfig` does not currently accept `bootcamp_mode`.** Per Pass
   2 item 7, the engine needs a small parameter addition. If this is NOT a
   small addition (i.e., engine refactoring is needed), we HALT per
   prerequisite-blocker rule and document the blocker. Current read: the
   field is a new optional param with a default that keeps existing
   callers behaviorally identical, so this is small.

9. **Dashboard color-coding regressions.** The existing StrategyResearch /
   Diagnostics pages use a shared status-badge scheme. INCONCLUSIVE is
   a new state in the UI vocabulary. Mitigation: amber badge, explicit
   legend at top of the page, matching test assertions on rendered text.

---

## Operator decisions to audit retrospectively

1. **SPDR source selection.** Pass 2 item 8 research picks the point-in-time
   data source. Our default plan is a curated CSV from S&P Dow Jones press
   releases + Wikipedia index-change table (same mechanism as the existing
   `scripts/scrape_sp_changes.py`). Alternatives considered: CRSP (paid),
   Compustat (paid), Bloomberg (paid). Operator may prefer a paid source
   for higher confidence; we flag the choice in commit 3.

2. **Embargo default of 5 trading days.** Literature (López de Prado 2018)
   recommends embargo ≈ max holding period. Lazy Prices has 21-day hold,
   so 5 days is aggressive. Rationale: we apply embargo on top of a purge
   that already removes straddle trades, so the embargo only needs to
   cover signal leakage (news sentiment bleed), not position overlap.
   Operator may revise.

3. **Heavy-tail threshold of 1.5× parametric SE.** This is a judgment call
   not pinned down in R6. We chose 1.5 as a middle ground between 1.2
   (more false alarms) and 2.0 (misses modest heavy tails). Operator may
   revise.

4. **Runtime heuristic 30-day window.** R8(e) heuristic threshold
   is unspecified. We chose 30 days from forensic-audit completion as a
   reasonable "same incident, fresh derivation" window. Operator may revise.

5. **Dashboard color for INCONCLUSIVE_POWER vs INCONCLUSIVE_DATA.** Spec says
   "distinct from INSUFFICIENT_DATA". We chose amber for both with a
   sub-label badge. Operator may prefer two different colors.

---

## Explicit non-goals

Per spec section "Non-goals":

- Incumbent strategy walk-forward (v0.26.1).
- Post-audit ruleset walk-forward (v0.26.2).
- Second strategy spec (v0.27.x).
- CPCV upgrade (v0.30.x).
- Non-contiguous `source_date_range` support (v0.30.x).
- Backtest-engine refactoring — HALT if needed.
- `known_events.py` tariff backfill — separate prerequisite sprint.
