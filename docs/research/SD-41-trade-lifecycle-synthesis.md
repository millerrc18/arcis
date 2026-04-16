# SD#41: Trade Lifecycle Optimization — Research Synthesis & Decision Framework

**Date:** 2026-04-15
**Status:** APPROVED — adopts methodology from Instance 2, implementation details from Instance 1
**Supersedes:** Prior Saturday sprint queue ordering
**Related research:** `Every_Lever_to_Push_Arcis_from_0_585_to_1_5_Sharpe.pdf` (Instance 1), `deep-research-sharpe-optimization-instance-2.md` (Instance 2)

---

## BLUF

Two deep research instances were run on the same prompt. Instance 1 (Claude Research) recommended stacking 7 levers including ATR-scaled trailing stops. Instance 2 (local CC plugin) counter-recommended far more restraint: reserve 50 OOS trades before changing anything, limit to 5 techniques, and warned that tight stops on mean-reverting processes *destroy* alpha (Kaminski-Lo 2014).

**Instance 2's methodology wins.** Instance 1's lever list remains useful but must be filtered through Instance 2's statistical discipline.

**Final Phase 1 plan:** 4 levers (not 7), preceded by a 50-trade pre-optimization OOS validation, followed by 100-trade post-implementation evaluation using Deflated Sharpe Ratio. Earnings filter stays at Saturday #1 (gap risk insurance). Vol-targeting becomes Saturday #2 (was regime classifier). ATR-scaled stops deferred pending MAE analysis.

**Expected realistic outcome:** Sharpe 0.78-1.13 after Phase 1 (Instance 1's discounted estimate), sufficient to credibly enable IB live trading gate (>1.0). Phase 2 target Sharpe 1.3-1.5 requires a second uncorrelated desk (per Instance 2: "a Sharpe above 1.5 from a single equity strategy is rare in published literature").

---

## The Central Tension Between the Two Reports

### Instance 1's Core Claim
"Replace fixed brackets with ATR-scaled trailing stops as the #1 lever. Your 3% fixed stop sits inside 1.5× ATR for volatile names, below the 2.0× ATR minimum. ATR-scaled stops solve this automatically. Expected Sharpe lift: +0.25 to +0.45."

### Instance 2's Counter-Claim
"Your pullback entry is structurally a mean-reversion bet inside a momentum filter. Kaminski-Lo (2014) proved stops destroy alpha in mean-reverting processes — the stop trigger correlates with imminent reversal, so you exit precisely when expected return turns positive. Connors abandoned fixed stops on RSI(2) entries for exactly this reason. ATR-scaling doesn't fix this; it may make it worse on tight multiples."

### Resolution

Both are partially correct. The disambiguation:
- Your **trend filter** (entering only in uptrends) is momentum-flavored → stops help here (Han-Zhou-Zhu 2014, stops more than double momentum Sharpe).
- Your **pullback entry** (buying weakness) is mean-reversion-flavored → tight stops hurt here (Kaminski-Lo).

**The hybrid solution:**
1. **Catastrophic stop only** at max(3× ATR(14), 5% of entry) — only triggers on thesis-breaking moves (earnings gap, news, flash crash), not routine pullback noise.
2. **Trend-break stop** at the portfolio level: if SPY closes below its 50-day EMA during the trade, exit all positions (regime change).
3. **Time-decay exits** as the primary exit mechanism (Kaminski-Lo explicitly: "time, not price, is the right exit dimension for mean-reversion bets").

This is rigorously consistent with the published evidence on the specific return process of a pullback strategy. The current 3% stop should be **widened to 5%** or removed entirely in favor of vol-targeting (per Carver's argument).

---

## The Statistical Reality Check

Instance 2's most important contribution is this table, which we cannot argue with:

| Quantity | Value | Source |
|---|---|---|
| Observed Sharpe | 0.585 | 23 closed trades |
| SE(Sharpe) | 0.226 | Lo (2002) formula |
| **95% CI on true Sharpe** | **[0.14, 1.03]** | SR ± 1.96·SE |
| IB gate threshold (>1.0) | 1.000 | **inside the CI** |
| Observed t-statistic | 2.806 | SR·√N |
| Bonferroni critical t (M=25) | 3.214 | α=0.05 corrected |
| Multi-test significance | **FAIL** | 2.806 < 3.214 |
| Expected max in-sample inflation (M=25) | +0.57 Sharpe | Bailey-Borwein-López de Prado-Zhu 2014 |

**What this means in plain English:**
1. We cannot statistically distinguish current Sharpe from "passing the IB gate." The gate sits inside the 95% CI.
2. If we test 25 techniques, the winning technique is expected to lose 0.57 Sharpe points out-of-sample.
3. We need ~100 trades to halve the SE to 0.10, ~250 trades for SE ≈ 0.06.

**Operational implication:** We have been conflating "research shows X might help" with "we have statistical evidence X will help our system." These are radically different claims.

---

## The Contrarian's Veto — Pre-Optimization OOS Validation

Before any Phase 1 implementation, we must run **50 fresh trades with current parameters** as pre-optimization OOS validation.

| Realized OOS Sharpe | Interpretation | Action |
|---|---|---|
| < 0.3 | Strategy is dead — the 0.585 was noise | Halt, diagnose edge, possibly revert to deterministic ranker |
| 0.3 - 0.8 | Strategy is real but mediocre | Phase 1 levers appropriate, modest lift expected |
| > 0.8 | Strategy is strong | Phase 1 levers should push past 1.0 cleanly |

**At current trading cadence (~4 trades/week), 50 trades = 12-13 weeks.** This is uncomfortable but statistically honest. We cannot skip this.

**The trap to avoid:** Changing parameters during the OOS window. Every optimization during validation destroys the statistical power of the validation itself.

---

## Audit the Reconciled-Stale Trades FIRST

Instance 2's Skeptic raised a specific concern that demands immediate action:

> "The 56.5% T1-hit rate is suspicious in combination with 65.2% win rate. The 34.8% reconciled-stale exits are a red flag — those are trades that did nothing for 7 days, and treating them as wins (if positive) or losses (if negative) at exit may be biasing the reported metrics. Audit these 8 trades before optimizing."

**Required analysis (immediate, before anything else):**

1. Pull all 8 reconciled_stale trades from `shadow_trades` table
2. Compute distribution of pnl_pct at exit
3. Compute distribution of MFE (max favorable excursion) during the hold
4. Compute distribution of MAE (max adverse excursion) during the hold
5. Categorize:
   - **Systematically positive near-zero exits** (e.g., mostly +0.5% to +1.5%): strategy has less edge than it looks, and these drag Sharpe
   - **Randomly distributed around zero**: probably fine, these are legitimate timeouts
   - **High MFE with low realized exit**: trailing stop or partial exit could have captured the MFE — strong signal that exit architecture is the problem

This analysis drives everything downstream. If the 8 stale trades are systematically "winners that gave back" MFE, that's evidence for partial exits. If they're "pure noise," they're evidence for time-decay cuts without extra machinery.

---

## Phase 1: The Four Levers (Post-OOS Validation)

If OOS validation clears (Sharpe ≥ 0.3 over 50 trades), implement **exactly these four changes, no others**:

### Lever 1: Daily Vol-Targeted Gross Exposure (Highest Priority)

**Source:** Moreira & Muir (2017) "Volatility-Managed Portfolios" JF 72(4):1611-1644. Sharpe lift +27% on market factor, alpha 4.86%/year, t=4.39.

**Implementation:**
```python
# Compute 30-day realized vol of portfolio returns
realized_vol_30d = daily_returns[-30:].std() * sqrt(252)

# Scale gross exposure inversely
target_vol = 0.15  # 15% annualized
gross_exposure_scalar = min(1.0, target_vol / realized_vol_30d)

# Applied to max position count
max_positions = int(15 * gross_exposure_scalar)
```

In calm markets (vol ~15%): 15 positions. In elevated vol (25%): 9 positions. In crisis (40%): 5-6 positions.

**Why this is the single highest-confidence lever:**
- Largest effect size in the literature with peer-reviewed replication
- Applies to every trade simultaneously (compounds powerfully)
- Mathematically subsumes stop-losses (Carver's argument) — reduces the need for per-trade stops
- Implementation is trivial (one weekend)

**Expected Sharpe lift:** +0.15 to +0.30 (both reports agree within this range)

### Lever 2: VIX Threshold Step Function (Second Priority)

**Source:** Bansal & Stivers (2023) + general regime-conditional risk premia literature.

**Implementation:**
```python
def vix_exposure_factor(vix: float) -> float:
    if vix < 15:    return 1.00
    if vix < 22:    return 0.80
    if vix < 30:    return 0.50
    if vix < 40:    return 0.25
    return 0.0  # halt new entries above VIX 40
```

Stacked with vol-targeting via **minimum**, not multiplication (Instance 2's key insight — don't triple-count correlated regime signals):
```python
final_gross = min(vol_target_scalar, vix_scalar)
```

**Expected Sharpe lift:** +0.10 to +0.20

### Lever 3: Sector Concentration Cap

**Source:** Pairwise correlation amplification — 15 S&P 100 positions with ρ=0.6 have effective heat 3× naive (Instance 2 §3.1).

**Implementation:**
```python
# At entry, reject trade if:
if sector_position_count[candidate.gics_sector] >= 4:
    skip_trade(reason="sector_cap_4")

# Additional cap on correlated sector pairs
if sector_pair_count[("Technology", "Communication Services")] >= 6:
    skip_trade(reason="sector_pair_cap_6")
```

**Expected Sharpe lift:** +0.05 to +0.15

### Lever 4: Time-Decay Exits Replacing Fixed 7-Day Timeout

**Source:** Kaminski-Lo (2014) — time is the right exit dimension for mean-reversion. Current 34.8% reconciled_stale rate indicates the timeout is too blunt.

**Implementation:**
```
Day 0 (entry):
  - Stop = max(entry - 3·ATR(14), entry × 0.95)  # catastrophic only
  - T1 = entry × 1.02 (keep for now; revisit in Phase 2)
  - T2 = entry × 1.04
  - No trailing stop in Phase 1

Day 3:
  - If unrealized P&L > 0: raise stop to breakeven
  - Otherwise: no change

Day 5:
  - Force partial exit: sell 50% at market price regardless of P&L
  - Reset stop on remainder to Chandelier(5, 2.5)

Day 7:
  - Force exit of remaining position

Day 10 (hard cap):
  - Scheduler safety — should never reach this
```

**Critical difference from current system:** The 3% fixed stop is **widened to 5% catastrophic** to avoid Kaminski-Lo failure mode. Vol-targeting (Lever 1) handles the risk-sizing that the tight stop was doing.

**Expected Sharpe lift:** +0.05 to +0.15 primarily through converting stale timeouts into partial captures

### What Phase 1 Deliberately Does NOT Include

These were recommended by Instance 1 but deferred per Instance 2:
- **ATR-scaled per-stock brackets** — defer until MAE analysis (Phase 2)
- **Chandelier trailing on initial position** — Kaminski-Lo risk on mean-reverting entries
- **Entry quality scoring (RSI(2) + volume + sector)** — defer until N ≥ 100 trades enable feature importance analysis
- **200-day MA trend filter** — redundant with vol-targeting at this scale
- **Market breadth gating** — correlated with VIX scaling, triple-counts regime signal
- **Bayesian bracket adaptation** — requires stable MAE baseline first
- **Inverse-ATR position sizing** — vol-targeting at portfolio level achieves similar result with less complexity

---

## Phase 2 (After 250 Cumulative Trades)

Only if Phase 1 validates Sharpe ≥ 0.8:

1. **MAE/MFE calibrated stops** (Sweeney 1996) — set stop at 95th percentile of winner MAE after ≥50 winners
2. **ATR-based per-stock bracket sizing** (now that Kaminski-Lo is mitigated by vol-targeting)
3. **Kritzman-Li turbulence filter** (2010 FAJ) — add as third regime signal
4. **Connors RSI(2) entry quality filter** (take trades only with RSI(2) < 10)
5. **Beta-parity position weighting** (Roncalli 2013)

---

## Phase 3 (After 500 Cumulative Trades, Sharpe ≥ 1.0 Validated)

Only if Phase 2 validates:

1. **Meta-labeling ML overlay** (López de Prado 2018 ch. 3.6)
2. **Options-implied signals** (Cremers-Weinbaum put-call IV spread)
3. **Bhansali SPY put hedging with monetization**
4. **CVaR-based position sizing** (Rockafellar-Uryasev 2000)
5. **Avellaneda-Stoikov inventory penalty** for correlation-aware entry

---

## Hard Forbiddens (Across All Phases Until New Evidence)

- **Deep Reinforcement Learning for exit optimization** — Bandarupalli (2024) shows DRL underperforms B&H on 2024 data, no OOS evidence at retail scale
- **VPIN for entry timing** — wrong timescale (minute/hour, not day), contested predictive power (Andersen-Bondarenko 2014)
- **Per-stock ATR multiplier grid search** — overfits trivially
- **Optimizing more than 5 parameters simultaneously**
- **Skipping the OOS reserve**
- **Tight stops (<3%) on pullback entries** — Kaminski-Lo failure mode

---

## Methodology Guardrails (Permanent)

These apply to ALL future research and implementation, not just this sprint:

1. **Reserve OOS data** before testing any change. Don't use the next 50 trades to "improve" anything during validation.
2. **Limit techniques to 5 per sprint**, not 25. Document the choice in writing before implementing.
3. **Compute Deflated Sharpe Ratio** on every comparison: `DSR = Φ((SR_obs − E[max SR | M trials, true=0]) / SE(SR))`. Report alongside raw SR.
4. **Walk-forward / purged k-fold validation** before any claim of improvement.
5. **Set stopping rules before starting**: if first 50 OOS trades after a change produce Sharpe < 0.5, revert.
6. **Vol-targeting is the baseline**. Anything more complex must beat vol-targeting OOS on its own merits.
7. **Halt at trial-multiplicity 5** per sprint. Sixth experiment requires significant new evidence.
8. **Document the audit of reconciled_stale trades** before any optimization sprint.

---

## Revised Saturday Sprint Queue

| # | Sprint | Priority | CC Time | Spec |
|---|--------|----------|---------|------|
| **0** | **Reconciled-stale trade audit (analysis, not code)** | **CRITICAL BLOCKER** | 1 hr | Inline in this doc |
| 1 | Earnings filter (SD#33) | CRITICAL | 4-6 hrs | `sprint-earnings-regime-retrain.md` Sprint 1 |
| 2 | **Vol-targeted gross exposure (NEW — replaces regime classifier as #2)** | HIGH | 2-3 hrs | To be written |
| 3 | **VIX step function (NEW)** | HIGH | 1 hr | To be written |
| 4 | **Sector concentration cap (NEW)** | HIGH | 1 hr | To be written |
| 5 | **Time-decay exits replacing timeout (NEW)** | HIGH | 3-4 hrs | To be written |
| 6 | Attribution resolver hardening | HIGH | 2-3 hrs | `sprint-attribution-resolver.md` |
| 7 | Regime classifier v2 (SD#35) | MEDIUM (was HIGH) | 3-4 hrs | Demoted — VIX step function covers much of the value |
| 8 | Retraining cadence (SD#34) | MEDIUM | 2-3 hrs | Ongoing |

**Note on regime classifier demotion:** Instance 2 argued that three regime filters (VIX + turbulence + breadth) should be combined via `min()`, not multiplication, because they're correlated. A proper regime classifier would add a fourth correlated signal. The simpler VIX step function captures 60-70% of the value with 20% of the complexity. Revisit after Phase 1.

---

## Expected Outcomes

### Phase 1 Complete (50 OOS + 100 post-implementation trades ≈ 9 months)

- **Expected Sharpe:** 0.78 - 1.13 (Instance 1's discounted estimate, ratified by Instance 2)
- **Probability of clearing IB gate (>1.0):** 45-60% (Instance 2)
- **Probability of validating real edge:** 70-85% (if OOS Sharpe ≥ 0.5, strategy is almost certainly real)

### Phase 2 Complete (250 cumulative trades ≈ 18-24 months)

- **Expected Sharpe:** 1.0 - 1.3
- **Single-strategy Sharpe 1.5+ from pullback alone:** unlikely per Instance 2 ("rare in published literature")
- **Path to Sharpe 1.5+:** requires second uncorrelated desk (research analyst, options volatility, or intraday)

### Critical Caveat

Both reports emphasize: **these numbers assume the underlying edge is real.** Until OOS validates, all projections are conditional. Harvey-Liu data-mining discount suggests true Sharpe could be closer to 0.3 than 0.585. The reconciled-stale audit and 50-trade OOS validation are the two gates that determine whether this entire program is worth pursuing.

---

## Immediate Next Actions

1. **Tonight:** Query the 8 reconciled_stale trades, generate MAE/MFE distribution analysis, document results in `docs/research/reconciled-stale-audit.md`
2. **This week:** Write CC sprint specs for Levers 1-4 (one spec per lever, Ralph-looped 3x as usual)
3. **Next 12-13 weeks:** Run 50 OOS trades with current parameters as pre-optimization validation (no changes)
4. **Concurrently:** Implement earnings filter (Saturday #1) — this is risk control, not parameter optimization, so it's allowed during OOS window (though document in case it affects Sharpe)
5. **After 50 OOS trades clear gate:** Deploy Levers 1-4 simultaneously, run 100 trades, evaluate with DSR

---

## Decision Log

- **Authored:** 2026-04-15
- **Instance 1 (Claude Research) findings:** Adopted partially — implementation detail for Levers 1-4
- **Instance 2 (local CC plugin) findings:** Adopted fully — methodology, statistical discipline, hard forbiddens
- **Saturday sprint queue updated:** Vol-targeting added as #2, Regime classifier demoted to #7
- **Phase gates established:** 50-trade OOS pre-validation, 100-trade post-implementation DSR evaluation, 250-trade Phase 2 gate, 500-trade Phase 3 gate
- **Single biggest behavioral change:** Stop treating "research shows X helps" as evidence. Require OOS validation on Arcis-specific data before claims of improvement.
