# SD#41 REVISED: Trade Lifecycle Optimization — Diagnostic-First Plan

**Date:** 2026-04-16 (revised same-day after forensic analysis)
**Status:** APPROVED — supersedes prior SD#41 synthesis
**Supersedes:** `docs/research/SD-41-trade-lifecycle-synthesis.md` (2026-04-15 version)
**Authority:** `docs/research/deep-research/Arcis-Forensic-Analysis-2026-04-16.pdf` (Category 2 forensic research)
**Applies:** Category 2 (own data forensics) overrides Category 1 (literature) per our research methodology rule.

---

## BLUF

The forensic analysis of 78 closed trades (not 23 — the prior figure was stale) produced three findings that invalidate yesterday's Phase 1 implementation plan:

1. **Per-trade Sharpe of 3.38 is real math but it's SPY beta during a bull run, not strategy alpha.** Mean excess vs SPY over 75 matched periods: +0.039% with t=0.098. The strategy is statistically indistinguishable from a passive SPY overlay with matched exposure.

2. **Regime and sector instrumentation is broken.** regime_at_entry is NULL for 67% of trades, and NULL trades outperform every labeled regime by 25+ percentage points. sector_context is 100% NULL. market_regime is 74% NULL. Any Phase 1 lever that depends on regime or sector filtering cannot be tested on current data.

3. **The attribution resolver shows 100% loss on 1,600 resolved pairs.** Either the LLM is a perfect filter (extraordinary claim requiring extraordinary evidence) or the ranker-only simulation has a methodology bug. Cannot be used as evidence of LLM alpha until investigated.

**Revised verdict:** DIAGNOSTIC. Halt all Phase 1 optimization work. Fix three data-quality issues first, then run a new 150-trade OOS validation with a redefined gate: **Excess-return Sharpe > 0.5 at t > 2.0**, not "per-trade Sharpe > 1.0" (which is trivially met by SPY beta).

Probability Arcis has non-SPY alpha worth optimizing: **15-30%** pending SPY-neutral re-measurement on fresh OOS trades.

---

## What Changed From the Prior SD#41 Synthesis

The prior synthesis built on the premise that:
- N = 23 closed trades
- Sharpe = 0.585
- Capture ratio likely below 0.50 (truncated exits leaving alpha on table)
- Stale trades biasing Sharpe up (winners giving back MFE)
- 3% stop too tight for volatile names
- Phase 1 levers ranked: vol-targeting → VIX → sector cap → time-decay

Every one of those premises was wrong or materially different in the actual data:

| Prior premise | Forensic reality | Impact |
|---|---|---|
| N = 23 | **N = 78** | 4× larger dataset — inferences are more statistically powerful |
| Sharpe = 0.585 | **Sharpe = 3.38** (per-trade) | CI [2.80, 3.96], passes every Bonferroni and DSR bar |
| Alpha vs SPY not measured | **Alpha vs SPY = +0.039%, t=0.098** | Strategy may be pure SPY beta |
| Capture ratio < 0.50 | **Mean 0.75, median 0.84** | Exits are already capturing most of MFE |
| Stale trades biasing UP | **Stales are +0.40% mean; excluding them RAISES Sharpe** | Opposite direction |
| 3% stop too tight | **3% ≈ Sweeney 95th-pct winner MAE (3.01%)** | Current stop is approximately correct |
| Vol-targeting primary lever | **Vol-targeting did nothing in sim (market was benign)** | Lever wasn't triggered in this regime |
| VIX scaling high priority | **vix_at_entry 95% NULL** | Cannot be tested — infrastructure gap |
| Sector cap high priority | **sector_context 100% NULL** | Cannot be tested without manual GICS lookup |

The Kaminski-Lo mean-reversion finding IS confirmed (82% of entries have negative autocorr), which validates the decision to not tighten stops. That's the one piece of the prior plan that survives.

---

## The Three Critical Diagnostics (Must Precede Any Optimization)

### Diagnostic 1: SPY-Matched Excess Return Instrumentation

**The problem:** We cannot distinguish alpha from beta in our current data. The per-trade Sharpe 3.38 could reflect genuine strategy edge OR it could reflect being 60-80% invested in SPY-correlated names during a period when SPY returned ~12% in 22 days.

**The fix:** Add three columns to `shadow_trades` and populate for every trade going forward:
- `spy_return_over_hold`: SPY total return (entry date close → exit date close)
- `excess_return`: `pnl_pct - spy_return_over_hold`
- `realized_sector`: GICS sector from manual lookup table (until `sector_context` classifier is fixed)

**Backfill:** Compute these three fields for all 78 existing closed trades using yfinance (already available in the stack). One-time backfill script.

**New headline metric:** Excess-return Sharpe, not raw Sharpe. Every dashboard, every report, every evaluation uses excess from this point forward. Raw Sharpe becomes a secondary metric.

**Gate redefinition:** IB live trading gate becomes:
- Excess-return Sharpe ≥ 0.5 at t ≥ 2.0
- N ≥ 150 OOS trades (not 50)
- Raw Sharpe gate (≥ 1.0) is deprecated — trivially passed by SPY beta

### Diagnostic 2: Attribution Resolver Methodology Audit

**The problem:** The resolver reports 100% of 1,600 resolved pairs as "loss" for the ranker-only counterfactual. Zero winners. This is either:

**(a)** The LLM is an extraordinary alpha source rejecting 100% of losers — an extreme claim requiring extreme evidence
**(b)** The ranker-only simulation uses stop/target parameters that produce structural losses (e.g., 10% stop, 2% target with wide bracket → most trades hit stop before target)
**(c)** Pre-filtered quality skew — rejected trades are systematically the worst setups, and the simulation uses conservative exits that compound the disadvantage

**The fix:**
1. Read `src/attribution_resolver.py` (or wherever the logic lives) and document:
   - Stop/target parameters used in ranker-only counterfactual
   - Resolution criteria — does any trade ever resolve as "win" in the simulation?
   - Timeout handling — are unresolved trades defaulted to loss?
2. **Independent spot-check:** Pick 10 rejected trades. Manually compute their forward 7-day returns vs a realistic 2%/3%/7-day bracket. Do they hit target or stop at the reported rates?
3. **Document findings** in `docs/research/attribution-resolver-audit.md`. Classify as Possibility A, B, or C.
4. If bug (Possibility B/C): fix the resolver before it produces more misleading data.

**Until this is resolved:** Do not cite attribution data as evidence of LLM value. Do not include LLM alpha claims in any investor materials or training documentation.

### Diagnostic 3: Regime and Sector Classifier Repair

**The problem:**
- `regime_at_entry` is NULL for 52 of 78 trades (67%). NULL trades have 78.8% WR vs GREEN-regime trades at 53.8%. This is not possible under a correct regime taxonomy.
- `market_regime` (from `recommendations`) is NULL for 58 of 78 trades. NULL trades have 79.3% WR vs calm_uptrend 42.9% and volatile_uptrend 46.2%.
- `sector_context` is 100% NULL.

**Three competing hypotheses for the NULL-outperforms-labeled pattern:**

**(a)** Classifier runs intermittently. Most of the time it's silent (NULL); when it runs, it happens to label during transient adverse conditions
**(b)** Labels are survivorship-biased. Calm_uptrend may mean "tops immediately before retrace"; volatile_uptrend may mean "post-spike pullbacks that fail more often"
**(c)** Data corruption. Metadata was added late; only recent trades have non-NULL values; recent trades happened to be in a worse regime period

**The fix:**
1. Audit the regime classifier code path. Document when it runs vs when it doesn't.
2. Check whether regime_at_entry was added to `shadow_trades` schema recently — if so, older trades have NULL by construction and the "anomaly" is just timing.
3. Build the manual GICS sector lookup table for S&P 100 (one-time 102-ticker CSV).
4. Backfill `realized_sector` for all 78 existing trades.
5. Run a second classifier diagnostic: compute VIX, SPY 5-day return, and breadth at entry for all 52 NULL-regime trades. Do they cluster in benign conditions? (If yes, hypothesis (a) is supported.)

**Until this is resolved:** Do not use regime filtering in any lever. Do not train the LLM on regime-conditional prompts. The regime signal as currently captured is unreliable.

---

## The Revised Sprint Queue

The prior Saturday sprint queue prioritized Phase 1 optimization levers. The revised queue leads with diagnostics:

| # | Sprint | Priority | Gate |
|---|--------|----------|------|
| 0 | **SPY-matched excess return instrumentation** | CRITICAL | Must complete before any lever testing |
| 1 | **Attribution resolver methodology audit** | CRITICAL | Determines whether LLM adds value or is a methodology artifact |
| 2 | **Regime classifier diagnostic + sector_context GICS backfill** | CRITICAL | Required to test any regime/sector lever |
| 3 | **IB cold-storage sprint** (already spec'd) | HIGH | Frees engineering time for the above |
| 4 | **Earnings filter (SD#33)** | HIGH (preserved) | Gap risk is independent of alpha-vs-beta question |
| 5 | **Attribution resolver hardening** (separate from audit #1) | HIGH | Production fix if audit reveals bugs |
| 6 | Time-decay exits on high-MFE stales | MEDIUM | Gated on excess-Sharpe ≥ 0.3 in first 30 OOS trades |
| 7 | Sector concentration cap (max 4/sector) | MEDIUM | Gated on Diagnostic 3 complete |
| 8 | Vol-targeted gross exposure | LOW | Gated on Diagnostic 1 + volatile regime to test against |
| 9 | VIX step function | LOW | Gated on Diagnostic 3 + populated `vix_at_entry` |
| 10 | Regime classifier v2 | DEFERRED | Rebuild, don't patch |

**Everything downstream of #10 in the prior queue is deferred** until the diagnostics close and the 150-trade excess-return OOS window validates real alpha.

---

## The Revised OOS Validation Window

Prior plan: 50 trades, gate "Sharpe ≥ 0.3" (vs noise) / "Sharpe ≥ 1.0" (IB gate).

Revised plan: **Two-stage OOS validation** gated on Diagnostic 1 completion.

### Stage 1: 30-trade alpha existence test

- **Gate:** Excess-return mean > 0 at t > 1.0 OR continue to Stage 2 for more statistical power
- **Stopping rule:** If t(excess) < 0.5 after 30 trades, halt. Strategy is not demonstrating alpha even with bull-market tailwind reduced.
- **Parameters:** No changes. Run with current config. Earnings filter (Sprint 4) is allowed during window as it's risk control, not alpha optimization.
- **Calendar time:** ~7-8 weeks at current cadence.

### Stage 2: 120-trade alpha validation (if Stage 1 clears)

- **Gate:** Excess-return Sharpe ≥ 0.5 at t ≥ 2.0 over 150 cumulative OOS trades
- **This is the new IB live trading gate.**
- **Calendar time:** ~25-30 weeks total from today, assuming ~5-6 trades/week.

### If the strategy fails the excess-Sharpe gate

If excess-Sharpe stays in [-0.2, +0.3] with t < 1.5 after 150 trades, the honest conclusion is that **Arcis is SPY beta with slightly better variance, not an alpha strategy**. At that point the business decision is:

**Option A:** Redeploy as "SPY beta tracker with AI commentary" — low-value, not a fund thesis, but operationally sound
**Option B:** Change the core strategy — move away from pullback-in-uptrend to something less correlated with SPY drift (e.g., long-short, pairs, event-driven)
**Option C:** Shut down and take the learnings elsewhere

This contingency should be acknowledged in the business plan. The fund thesis requires demonstrated alpha, not demonstrated beta-tracking.

---

## What This Means for the Business Plan

The Halcyon Lab business plan currently assumes demonstrated alpha from Phase 1 unlocks Phase 2 desks. The forensic findings don't invalidate this, but they raise the bar:

- **Fund break-even target (~$2M AUM):** unchanged, but now gated on excess-Sharpe ≥ 0.5 validation
- **Timeline to fund:** was 18-24 months, now likely 24-30 months (diagnostics + revised OOS window add 3-6 months)
- **Second desk decision point:** was "after 50 trades", now "after 150 OOS trades with excess-Sharpe validated"
- **Institutional allocator materials:** cannot cite Sharpe 3.38 headline — must cite excess-Sharpe. If excess-Sharpe is not yet validated, be silent on Sharpe claims entirely.

---

## What This Means for the Training Pipeline

Training data generation continues uninterrupted — the LLM's job is to produce process-driven commentary independent of whether the strategy has alpha. BUT:

- **Do not train the LLM on regime-conditional prompts** until Diagnostic 3 is closed. Current regime labels are unreliable.
- **Do not cite LLM filter accuracy** (the 100% rejection accuracy from attribution) until Diagnostic 2 is closed.
- **Self-blinding discipline is now more important, not less** — the strategy may be SPY beta, so the model must not learn to "predict SPY direction" which would be a trivial and unprofitable shortcut.

---

## Permanent Methodology Guardrails (Reinforced)

The forensic report surfaces a critical meta-lesson: we built yesterday's plan on descriptive statistics (23 trades, Sharpe 0.585) that were already stale AND never validated against SPY. Two guardrails from this:

1. **Every Sharpe claim must specify raw vs excess vs alpha.** A report that says "Sharpe 3.38" without context is misleading.
2. **Every metric update must refresh the trade count.** The "23 trades" figure propagated through prior research docs without anyone noticing the actual database had 78.
3. **Category 2 forensics (own data) must run before Category 1 (literature) when both are available.** We ran literature first yesterday; that was the wrong order.
4. **Attribution claims require methodology review.** "100% rejection accuracy" should have triggered immediate skepticism, not been reported as a prior expectation.

These are now permanent. Every future SD document starts with a dataset snapshot that lists current N, date range, and whether SPY-matched benchmarks are available.

---

## Decision Log

- **Authored:** 2026-04-15 (original)
- **Revised:** 2026-04-16 after forensic analysis produced
- **Original findings preserved** in `docs/research/SD-41-trade-lifecycle-synthesis.md` as historical record
- **Supersedes:** the sprint priority ordering in the original (diagnostics now lead)
- **Preserves:** the Instance 2 statistical discipline, the hard forbiddens (no DRL, no VPIN, no tight stops on pullbacks), the methodology guardrails
- **Gates redefined:**
  - IB live trading gate: raw Sharpe ≥ 1.0 → excess-return Sharpe ≥ 0.5 at t ≥ 2.0 over 150 OOS trades
  - Phase 2 desk gate: "after 50 trades" → "after 150 OOS trades with excess-Sharpe validated"
  - Phase 3 desk gate: unchanged (requires Phase 2 validation first)

**Confidence: HIGH.** The forensic report is based on 78 trades of actual data, with SPY-matched benchmarks computed explicitly, with multiple independent statistical tests (Spearman, Bonferroni, Deflated Sharpe, Bayesian posterior). The three diagnostic issues are specific, falsifiable, and each has a defined resolution path.

The uncomfortable part — that current performance may be SPY beta — is the correct epistemic state. Acting on this now costs 3-6 months. Not acting on this costs the fund thesis.
