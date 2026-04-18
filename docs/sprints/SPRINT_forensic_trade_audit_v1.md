# Sprint Spec: Forensic Audit of 85-Trade Cohort

**Branch:** `feat/forensic-trade-audit-v1`
**Target tag:** none (diagnostic — no version bump)
**Priority:** HIGH — pairs with regime diagnostic; independent & parallelizable

---

## Objective

Produce a complete forensic profile of the closed-trade cohort answering the
questions a risk committee would ask before deploying real capital. Understand
**what actually happened** in enough depth that the `excess-Sharpe ~ 0` finding
is either corroborated or explained.

## Questions (Q1-Q8)

- Q1: Real beta decomposition (trade/cap/equal/notional-weighted + rolling)
- Q2: P&L distribution (Gini, top-K concentration, Wilcoxon)
- Q3: Slippage vs theoretical (distribution, correlations)
- Q4: Exit type attribution (frequency, mean return, Sharpe per exit type)
- Q5: Holding-period attribution (per-day return contribution, path plot)
- Q6: Time clustering (autocorrelation at lags 1/5/10/20)
- Q7: Selection vs holding split (day-1 vs day-2+ excess, with CIs)
- Q8: Sector concentration (per-sector stats)

All answers must be numerical with CI/error bars. No qualitative hand-waving.

## Deliverables

1. `scripts/diagnostics/forensic_trade_audit_v1.py`
2. `tests/diagnostics/test_forensic_audit.py` (>= 8 tests)
3. `docs/diagnostics/forensic-audit-YYYY-MM-DD.md`
4. `docs/diagnostics/forensic-audit-YYYY-MM-DD/` (plots)
