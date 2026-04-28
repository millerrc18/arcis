# Methodology Toolkit

> Quick reference for the statistical-rigor modules added by the 2026-04-27 audit.
> All modules live under `src/methods/` and `src/analytics/` and are pure-function (no I/O, no DB).
> Most shelf modules are NOT yet wired into the production promotion path — draw from them when evaluating a strategy.
> Exceptions are listed in the **Wired** section below.

## Wired (production callers exist)

| Module | Wired as of | Description |
|---|---|---|
| `src/cost_model/calibration.py` | Sprint 1.B (#79) | `get_calibrated_cost_model()` is called at `backtest_model()` init; calibrated `median_round_trip_cost_bps` is deducted from each trade's `pnl_pct`. Falls back to zero-cost with a warning log if the JSON is absent. |
| `src/data_ingestion/risk_free_rate.py` | Sprint 1.B (#80) | FRED DGS3MO/DTB3 rf-rate adapter. Wired into `src/evaluation/backtester.py` via `rf_source='fred'` (default). Provides per-trade daily decimal rf: `(annualized_pct / 100) / 252`. Tests mock FRED HTTP; no live network calls in CI. |
| `src/methods/promotion_gate.py` | Sprint 1.B (#49) | 4-of-5 voting gate (PSR + PBO + MC permutation + White RC + IS-vs-OOS). Fires automatically after every `run_fine_tune()` call; decision recorded in `model_versions.status`. Available via `python -m src.main run-promotion-gate <version_name>`. See §4.6 of `docs/research/pre-registration-stage1.md` for the binding pre-registration. |

---

## Pre-conditions

Before invoking any toolkit method, the input return series must come from:

1. **Canonical excess returns** — produced by `src.analytics.canonical_sharpe.rf_adjusted_excess_sharpe` and friends. The series is `pnl_pct - rf_period`. Caller subtracts rf; toolkit functions assume excess input.
2. **Fully-instrumented trades only** — filtered via `src.analytics.instrumentation_filter.filter_fully_instrumented`. Drops rows missing any of `pnl_pct`, `actual_entry_time`, `actual_exit_time`, `excess_return`. Empty strings count as missing (SQLite doesn't enforce types, and the writer signals "tried but no data" via `''`).
3. **Quarantine-filtered** — `COALESCE(quarantined, 0) = 0` excludes rows from the pre-#651 cascade window or any future flagged window.

If any of these is skipped, the toolkit's outputs are technically valid but operationally meaningless — you'd be measuring noise from bad data.

---

## Decision tree: which method when?

```
Question I'm trying to answer                       → Use this method
──────────────────────────────────────────────────────────────────────
"Is my Sharpe statistically distinguishable from 0?" → PSR (T2.04)
"Did my strategy survive a search over N candidates?" → DSR (T2.04)
"Do I even have enough trades to declare significance?" → MinTRL (T2.04 / T1.08)
"Is my Sharpe an artifact of overfitting to training?" → PBO (T2.06)
"Is my Sharpe robust to autocorrelated returns?"     → Block bootstrap (T2.02)
"Could random label permutation produce my Sharpe?"  → MC permutation (T2.03)
"Among N candidate strategies, did the BEST really beat 0?" → White RC (T2.05)
"Did my walk-forward folds have look-ahead leakage?" → CPCV (T2.01)
"Should I promote this strategy past Stage 2?"       → Promotion gate (T2.04, ≥4-of-5)
```

---

## The methods

### <a id="cpcv"></a> CPCV — Combinatorial Purged Cross-Validation

**Module:** `src/methods/cpcv.py` (commit `c5ed544`)
**What it answers:** Did each fold's OOS performance survive the held-out test window without leaking from neighboring training observations?
**Reference:** López de Prado 2018 §7.4
**Key params:** K=5 folds (default), embargo=10 sessions (default)
**Returns:** Per-fold OOS rf-adjusted Sharpe via canonical formula
**Variant included:** `cpcv_anchored` for anchored walk-forward (training window grows from index 0)
**Cost:** O(K · N) — cheap
**When to skip:** If your strategy has no sequential dependence (e.g., daily mean-reversion with no carry), the embargo isn't load-bearing.

### <a id="block-bootstrap"></a> Block bootstrap

**Module:** `src/methods/block_bootstrap.py` (commit `0d63dbd`)
**What it answers:** What is the 95% confidence interval of my rf-adjusted excess Sharpe under realistic (auto-correlated) return dynamics?
**Reference:** Politis & Romano 1994 (stationary block bootstrap), Politis & White 1994 (auto block-length)
**Key params:** 10000 resamples (default), block length auto-selected via Politis-White (simplified bandwidth-truncated estimator)
**Returns:** `(ci_lower, ci_upper)` tuple
**Cost:** ~30s for default 10000 × 300; pure-Python inner loop is the bottleneck (vectorization is a future perf task)
**When to use:** Any time you're reporting a Sharpe CI to a stakeholder. The IID bootstrap (which `stage1_baseline_recompute.py` currently uses) is documented as optimistic. Replace it once T2.02's perf is acceptable for the recompute.

### <a id="mc-permutation"></a> MC Permutation

**Module:** `src/methods/mc_permutation.py` (commit `7be5bf2`)
**What it answers:** What's the empirical p-value of my observed Sharpe under the null hypothesis "trade-direction labels are random"?
**Method:** Shuffle long/short labels, recompute statistic, repeat 1000 times. Empirical p = fraction of permutations producing statistic ≥ observed.
**Returns:** float p-value in [0, 1]
**Cost:** O(N_perms · N_trades) — fast
**When to use:** Cross-check on PSR — they should broadly agree. Disagreement suggests non-Gaussian return distribution.
**Limitation:** Single-strategy only. For multi-strategy comparison use White RC.

### <a id="white-rc"></a> White Reality Check

**Module:** `src/methods/white_rc.py` (commit `d957579`)
**What it answers:** Among N candidate strategies tested, did the BEST one's Sharpe survive after accounting for data-snooping?
**Reference:** White 2000
**Method:** Stationary bootstrap (reuses T2.02's resampler) applied jointly across all strategies' returns; null distribution is the max statistic per resample.
**Critical detail:** Same block indices applied to all strategies — preserves cross-sectional dependence.
**Returns:** Nominal-p (unadjusted)
**When to use:** Before declaring "strategy X works" if you've actually evaluated several variants. Without White RC you've data-snooped.

### <a id="psr-dsr"></a> PSR / DSR / MinTRL

**Module:** `src/methods/psr.py` (commit `29efa3c`) — re-exports canonical implementations from `src/platform/rigor/dsr.py` + `src/evaluation/statistics.py`
**Reference:** Bailey & López de Prado 2012 (PSR + DSR), Bailey & López de Prado 2014 (MinTRL)

| Function | Answers | Returns |
|---|---|---|
| `psr(returns, sr_benchmark=0.0)` | "Probability my true Sharpe exceeds the benchmark" | Probability in [0, 1] |
| `dsr(returns, n_trials, sr_benchmark=0.0)` | "PSR adjusted for the multiple-testing inherent in trying `n_trials` strategies" | Probability in [0, 1] |
| `mintrl(returns, alpha=0.05)` | "Minimum N to declare Sharpe ≠ 0 at α" | Integer count |

**The DSR vs PSR gap:** When `n_trials > 1`, DSR < PSR — that's the search-burden penalty. If you tested 10 strategy variants and picked the best, DSR with `n_trials=10` is the honest probability. Failing to deflate is the `dsr() always triggers 'trials_sr_variance missing' RuntimeWarning` notice you see in tests — pass a real `trials_sr_variance` from your trials registry to silence it.

**MinTRL gotcha:** The default `target_sharpe=0` is the LOOSEST possible MinTRL. To declare "Sharpe > 1.0", MinTRL is much higher. T1.08's instrumentation filter uses target=0 because Stage-1 only asks "can we even report this?" not "is it good?"

### Promotion gate (≥4-of-5) — WIRED into post-train flow as of Sprint 1.B (#49)

**Module:** `src/methods/promotion_gate.py` (commit `29efa3c`)
**Wired:** Fires automatically after every `run_fine_tune()`. Decision recorded in `model_versions.status` (`'promoted'` / `'rejected_by_gate'` / `'pending_review'`). Operator-demand re-run: `python -m src.main run-promotion-gate <version_name>`.
**What it does:** Runs the 5 statistical tests (CPCV, block bootstrap, MC perm, PSR/DSR, White RC) and returns a single decision.

```python
result = promotion_gate(returns, n_trials=10, alpha=0.05)
# result["decision"]: "promote" | "defer" | "reject"
# result["votes"]: {method: passed_bool}
# result["mintrl"]: int
# result["details"]: per-method stats
```

**Decision rules:**
- **Defer** if N < MinTRL (track record insufficient)
- **Promote** if ≥4 of 5 pass at α AND zero "inverse hard-blocks" (e.g., MC perm p > 1−α with negative mean — strategy actually has *negative* edge)
- **Reject** otherwise

**Why ≥4-of-5 not 5-of-5:** No single test should be a single point of failure. One marginal failure (e.g., p=0.051 vs threshold 0.05) shouldn't kill promotion if every other test screams "yes." The 4-of-5 voting threshold is borrowed from physics multi-source detection — robust to one detector being noisy.

**Why not 3-of-5:** Empirically, 3-of-5 passes with a high false-promote rate; 4-of-5 is the sweet spot per the decision-matrix calibration in `tests/methods/test_promotion_gate.py`.

### <a id="pbo"></a> PBO — Probability of Backtest Overfitting

**Module:** `src/methods/pbo.py` (commit `f9c261d`)
**What it answers:** What fraction of the time does the IS-best strategy underperform OOS-median? (PBO = 0.5 means the best in-sample is essentially random out-of-sample.)
**Reference:** Bailey, Borwein, López de Prado, Zhu 2014
**Method:** Combinatorially Symmetric Cross-Validation (CSCV) with S even partitions
**Returns:** PBO in [0, 1] (lower is better; 0 = no overfitting, 0.5 = random)
**Cost:** O(C(S, S/2)) — S=8 gives 70 splits (default for CI), S=16 gives 12,870 (default for production)
**When to use:** Before claiming a strategy works. PBO complements the in-sample/out-of-sample story — PSR tells you "is this Sharpe real?", PBO tells you "if I pick the best of 10 candidates, what's the chance the best is just noise?"

---

## Worked example: Stage-2 promotion check

After 150 OOS live trades with `n_trials=10` candidate strategies tested:

```python
import sqlite3
from src.utils.db import connect_db
from src.analytics.instrumentation_filter import filter_fully_instrumented
from src.methods.promotion_gate import promotion_gate

with connect_db() as conn:
    rows = [dict(r) for r in conn.execute("""
        SELECT * FROM shadow_trades
        WHERE status IN ('closed','stopped_out','target_hit','manually_closed')
          AND COALESCE(quarantined, 0) = 0
          AND actual_exit_time >= ?  -- stage-2 start
    """, (stage_2_start,))]

clean = filter_fully_instrumented(rows)
returns = [r["excess_return"] for r in clean]

result = promotion_gate(returns, n_trials=10, alpha=0.05)
print(result["decision"])      # "promote" / "defer" / "reject"
print(result["votes"])          # which tests passed
print(result["details"])        # full stats per test
```

If `decision == "promote"` AND the SPY-relative Sharpe is now significant (it wasn't at Stage 1), the operator authorizes Stage-3 ramp.

---

## What's NOT in the toolkit (yet)

- **SPA (Hansen 2005)** — superior version of White RC. Out of scope per T2.05 fence.
- **Combinatorial CPCV** — full version that tests on every C(K, 2) pair of folds, not just single folds. Out of scope per T2.01 fence.
- **Vectorized block bootstrap** — current implementation is pure-Python inner loop; vectorization is a future perf task.
- **ERC (Equal Risk Contribution) iterative allocator** — out of scope per T2.12a fence (basic inverse-vol risk parity is what shipped).
- **Factor-alpha promotion-gate wiring** — T2.16a is core; T2.16b wiring is deferred.

---

## Cross-references

- **Audit spec** that mandated these: [`docs/audits/2026-04-27-trading-readiness/audit-spec.md`](audits/2026-04-27-trading-readiness/audit-spec.md) §8
- **Audit shipped doc:** [`docs/audits/2026-04-27-trading-readiness/SHIPPED.md`](audits/2026-04-27-trading-readiness/SHIPPED.md)
- **Pre-conditions modules:** `src/analytics/canonical_sharpe.py` (T1.03), `src/analytics/instrumentation_filter.py` (T1.08)
- **CLAUDE.md governance** of the test floor and DDL rules
