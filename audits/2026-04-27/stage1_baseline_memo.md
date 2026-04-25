<!--
PLACEHOLDER MEMO — generated 2026-04-25 against an empty in-memory fixture
to capture the template structure. The operator regenerates this memo against
the prod DB (C:/arcis/data/ai_research_desk.sqlite3) by running:
    python scripts/stage1_baseline_recompute.py
…then signs off with `git commit -s audits/2026-04-27/stage1_baseline_memo.md`.
-->

# Stage-1 Baseline Recompute Memo

**Date:** 2026-04-27
**Audit spec:** §9 item 9 (honest Stage-1 Sharpe)
**Generator:** scripts/stage1_baseline_recompute.py (T1.02)

## Trade Counts

- N total closed shadow_trades in window: **0**
- N quarantined (excluded; pre-#651 cascade per T1.01): **0**
- N fully-instrumented (per T1.08 four-column predicate): **0**

## Three Sharpe Figures (canonical, T1.03 / §F-2)

All Sharpe values are annualized (sqrt(252)), sample stdev (ddof=1).

### 1. raw_sharpe (no benchmark)

- Point estimate: **undefined (n<2 or zero variance)**
- 95% bootstrap CI (IID, n_resamples=10000) on per-period mean return:
  [undefined, undefined] (insufficient sample)

### 2. spy_relative_sharpe (vs SPY total return)

- Point estimate: **undefined (n<2 or zero variance)**
- 95% bootstrap CI (IID) on per-period (pnl_pct - spy_pct) diff series:
  [undefined, undefined] (insufficient sample)
- Per-period SPY return is `spy_return_over_hold` from the row (src.analytics.spy_benchmark; close-to-close auto-adjusted).

### 3. rf_adjusted_excess_sharpe (canonical, vs FRED 3-month T-bill)

- Point estimate: **undefined (n<2 or zero variance)**
- 95% bootstrap CI (IID) on per-period (pnl_pct - rf) diff series:
  [undefined, undefined] (insufficient sample)
- **Inline rf constant (DA-9 fix; pending T2.10 FRED integration):**
  - rf_period (per-period, daily): `0.0001`
  - Window: `2026-04-23 (single trading day approximation)`
  - Source: placeholder constant — T2.10 will swap in the FRED 3-month T-bill (DTB3) series with proper per-day interpolation. Until then, this single-day approximation is the documented assumption.

## Bootstrap Methodology

- Engine: `src.diagnostics.bootstrap.bootstrap_ci` (IID percentile bootstrap, 10,000 resamples, seed=42).
- **Caveat:** IID bootstrap assumes per-period returns are independent. For trades with overlapping holding periods this assumption is violated; the reported CIs are therefore optimistic. Block bootstrap (T2.02) is the Track-2 follow-up that addresses this.

## Power Assessment (T1.08, Bailey-LdP MinTRL)

- N (fully-instrumented): **0**
- MinTRL (target Sharpe = 0, alpha = 0.05): **4.8415**
- Verdict: **UNDERPOWERED**
- Detail: Stage-1 sample is underpowered; reported Sharpe is not statistically reliable. Consider deferring promotion until N >= MinTRL. (n=0, MinTRL=4.84, alpha=0.05)

> Stage-1 sample is underpowered; reported Sharpe is not statistically reliable. Consider deferring promotion until N >= MinTRL.


## Methodology Version Hashes

- Canonical Sharpe module SHA (T1.03): `1928710`
- Block-bootstrap (T2.02) SHA: *pending — Track 2 dependency*
- FRED rf-rate series version (T2.10): *pending — Track 2 dependency*

## Pre-#651 Row Exclusion

- Quarantined rows excluded (pre-#651 cascade, T1.01): **0**
- Cutoff: `2026-04-22T20:00:00-04:00` (per scripts/quarantine_pre_651.py).

## Stage-2 Promotion Bootstrap CI (placeholder)

*This section is reserved for the block-bootstrap CI numbers produced once T2.02 (block bootstrap) lands. Until then, the IID figures above are the best-available estimate and should NOT be used as a Stage-2 promotion gate.*

## Sign-off

Sign-off is NOT performed by the script. Operator must review this memo and commit with `git commit -s` to attach a Signed-off-by trailer.
