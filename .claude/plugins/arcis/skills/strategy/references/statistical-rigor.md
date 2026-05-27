# Statistical Rigor — DSR + PSR + CSCV + trials_registry

Read-only reference for the `arcis:strategy` skill. Cited by `analyze` verb prose.

## 1. Deflated Sharpe Ratio (DSR)

DSR is the multiplicity-corrected Sharpe ratio: observed SR deflated by `E[max SR]` across `N_eff` i.i.d. noise trials.

- `src/platform/rigor/dsr.py` — `deflated_sharpe_ratio(trade_returns, n_trials, trials_sr_variance=None) -> dict`.
- Return keys: `SR_hat, skew, kurt, T, E_SR_max, PSR, DSR`.
- Formula: `DSR = PSR(SR_hat, sr_benchmark = E[max SR | N_eff])` from extreme-value theory (Bailey-López de Prado 2014 Eq. 8).
- Threshold: `DSR > 0.95` — significant at 95% confidence.

## 2. Probabilistic Sharpe Ratio (PSR)

Pre-multiplicity probability the true SR exceeds a benchmark.

- `probabilistic_sharpe_ratio(sr_hat, sr_benchmark=0, T, skew, kurt) -> float`. Pearson (non-excess) kurtosis; Normal = 3.
- Surfaced alongside DSR. At small T (<30), PSR is the operator-facing primary gate (see §3).

## 3. T < 30 small-sample fallback

Per `dsr.py:85`:

```python
if T < 30:
    warnings.warn(
        f"T={T}<30; DSR unreliable. Use PSR as primary "
        "gate at this sample size.",
        RuntimeWarning,
    )
```

When the skill detects this RuntimeWarning during DSR compute, the AN5 output surfaces PSR as the primary gate and labels DSR `unreliable_small_T`.

## 4. Paper-erratum note (Bailey-López de Prado 2014)

The paper's worked example (N=100, T=1250, SR_ann=2.5, skew=-3, kurt=10, p.9) states BOTH `DSR=0.9004` AND `SR*_0_ann=0.5429`, but these cannot both hold for any single V[SR_n]:

- `V = 0.5/250    → SR*_0_ann = 1.79       DSR = 0.9004` matches DSR claim
- `V = 0.046/250  → SR*_0_ann = 0.5429     DSR = 0.9998` matches SR*_0 claim

This is a paper-exposition inconsistency (erratum), NOT an implementation bug. The regression guard at `tests/platform/rigor/test_dsr.py::test_dsr_paper_example_reproduction` verifies each formula in isolation against the V matching its claimed output. Citation: Bailey, D. & López de Prado, M. (2014). "The Deflated Sharpe Ratio." JPM 40(5):94-107. SSRN 2460551.

## 5. trials_registry — N_eff bookkeeping

`src/platform/rigor/trials.py` owns the `trials_registry` table.

- `get_current_n_eff(db_path)` — global count of rows; used as `N` in DSR's `E[max SR]` formula. Every backtest counts, including parameter sweeps.
- `record_trial(strategy_id, spec_hash, sr_raw, sr_ann, n_trades, skew, kurt, passed_dsr_gate, params_searched_json, n_params_searched, db_path) -> trial_id` — writes one row.
- `get_variance_for_strategy_family(family=<str|None>, db_path)` — v0.25 implementation reads GLOBAL trial variance (no WHERE family=… clause at `trials.py:97`; family parameter currently IGNORED). Returns empirical variance when ≥20 trials exist globally, else the documented fallback below.

## 6. Variance fallback constant (verbatim from trials.py:33)

```python
# Documented fallback when variance estimator has insufficient sample.
# Per Bailey-Lopez de Prado 2014, typical V for a diversified strategy
# pool lands in [0.01, 0.05] (annualized). Fallback at 0.02 — mid-range.
# v0.25 work: replace with family-specific empirical variance.
_VARIANCE_FALLBACK = 0.02 / 250  # per-observation, not annualized
```

`RuntimeWarning` is emitted at `trials.py:109`:

```python
warnings.warn(
    f"[TRIALS] Fewer than 20 recorded trials (have {len(sr_values)}); "
    f"using _VARIANCE_FALLBACK={_VARIANCE_FALLBACK}. v0.25 work: "
    "replace with empirical family variance.",
    RuntimeWarning,
)
```

The skill MUST NOT change these constants. They are the documented v1 contract; tightening to family-specific empirical variance is a v0.25 follow-up.

## 7. Dual-write rationale (Decision DD-5)

**Both backtest AND analyze record a trial.**

- **Backtest verb (Phase B6 / B7):** records ONE trial after persist completes — each backtest is a "trial attempt" and bumps N_eff for subsequent analyze. `passed_dsr_gate=0` (backtest does not compute DSR).
- **Analyze verb (Phase AN3):** records ONE additional trial entry — each analyze is itself a search-step (operator examined a result + computed DSR). `passed_dsr_gate=1 if DSR > 0.95 else 0`.

**Why both?** `scripts/run_backtest.py` does NOT call `record_trial()` (FA11 cross-cutting concern) — historical N_eff is undercounted. The skill fills the gap. Recording in both phases conservatively bumps N_eff and keeps DSR's multiplicity correction defensible. Alternative considered and rejected (DD-5 §13): skill records ONLY in backtest — rejected because examining N results to pick the best IS the multiplicity DSR is designed to correct, so each analyze IS a search step.

## 8. DA3 family-variance threshold

BEFORE DSR compute in Phase AN3, the skill queries:

```sql
SELECT COUNT(DISTINCT strategy_id) FROM trials_registry
```

If the count is `> 3`, the global-variance approximation (v0.25 limitation — `trials.py:97`) no longer reasonably stands in for family-specific variance. The skill MUST escalate to AskUserQuestion with two options:

- "Proceed with global-variance DSR (will surface ⚠ degraded-approximation banner)"
- "Cancel — file follow-up task to wire family WHERE clause in trials.py:97"

On Cancel: STOP. Write `arcis_strategy.analyze.deferred_family_variance` audit event with `{distinct_strategy_ids}`.

On Proceed: continue, and prepend a ⚠ banner to AN5 output noting the degraded approximation.

## 9. DA13 variance_source classification

After DSR compute, the skill classifies the variance source for the audit event:

- `'empirical'` — `get_variance_for_strategy_family` returned a value from ≥20 trials (no RuntimeWarning AND returned value != `_VARIANCE_FALLBACK`).
- `'fallback'` — returned value equals `_VARIANCE_FALLBACK = 0.02/250` but RuntimeWarning did NOT fire (defensive — reserved for edge cases; trials.py:109 normally always warns when fallback is used).
- `'fallback_with_warning'` — RuntimeWarning fired at `trials.py:109` (common path when trials_registry has fewer than 20 rows).

Captured by wrapping the call in `warnings.catch_warnings(record=True)` and inspecting the warning list for `'fallback'` / `'_VARIANCE_FALLBACK'`. Persisted to audit-event params: `variance_source` (one of three values above), `trials_count_at_analyze_time` (frozen N for forensic replay), `fallback_warning_fired` (explicit boolean). Forensic recovery 6 months later can read `params.variance_source` to determine if the fallback was active for a given analyze run.

## 10. CSCV (Combinatorially Symmetric Cross-Validation)

`src/platform/rigor/cscv.py` — `pbo_from_pnl_matrix(pnl_matrix, S=16) -> dict`.

- Input: T×N matrix (T daily observations × N strategy configs).
- Returns: `{PBO, logit_distribution, performance_degradation_points}`.
- Reject threshold: `PBO > 0.5`.
- Needs ≥2 distinct backtest configs to be meaningful.
- Known failures: blind to look-ahead bugs; blind to regime shifts outside sample; homogeneous-strategy degeneracy (Vojtko-Padyšák 2021).

**Skill semantics (Phase AN4):** CSCV is INFORMATIONAL. If `< 2` prior `backtest_results` rows exist for the strategy_id, surface "CSCV unavailable: <2 backtests for $STRATEGY_ID" as an informational line; do NOT fail. If `>= 2`: pull all per-result daily PnL via JOIN to `backtest_trades`, construct the matrix, call `pbo_from_pnl_matrix`, surface result.
