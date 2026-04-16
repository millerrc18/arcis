# Strategy Decision #41: Cold-Store IB Integration — Alpaca-Only Through Phase 1

**Date:** 2026-04-16
**Status:** APPROVED
**Supersedes:** Prior assumption that IB would run in parallel with Alpaca throughout Phase 1
**Related:** SD#25 (original IB live-trading gate), SD#40 (Grafana Cloud observability), SD-41 research synthesis (trade lifecycle optimization)

---

## Decision

**Halt active trading on Interactive Brokers immediately. Retain the account in dormant status. Revisit the IB integration decision at one of three triggers: (a) Phase 1 validation complete with Sharpe ≥ 0.8, (b) Options Volatility Desk prep begins (Phase 3-4, estimated 12-18 months out), or (c) institutional allocator conversations move into due diligence.**

---

## Context

The original Halcyon Lab roadmap envisioned IB as a parallel broker from Phase 1 onward, with gated live trading activation at 60+ closed trades, Sharpe > 1.0, and 30-day Gateway stability. The rationale was: (1) execution quality improvement vs Alpaca's PFOF routing, (2) PortfolioAnalyst GIPS-verified track record, (3) asset class breadth for future desks, (4) portfolio margin economics at scale.

After seven IB integration sprints, IB Gateway operational in Docker, a functional shadow-trading bridge, and the NSSM service managing the connection, the system has accumulated 18 IB shadow log entries but only 2 real IB positions (TGT, COP) — and those were opened under manual conditions during the April 10 cascade recovery, not by the autonomous system.

The cost of maintaining active IB integration during Phase 1 is substantial and ongoing. The benefits are either distant or don't apply at current scale.

---

## Analysis

### The four stated benefits of IB over Alpaca

**1. Execution quality (price improvement).**
- IB reports 100% price improvement on SmartRouted orders. Alpaca routes equity order flow through Citadel/Virtu/Jane Street (PFOF) with more modest price improvement.
- At current $6,600 position sizes, the execution quality differential is roughly 2-5 basis points per trade, or approximately 0.30-0.75% annualized drag at 150 trades/year.
- At $500K+ positions (Phase 3-4 territory), this grows to 5-15 bps per trade or 0.75-2.25% annual drag — material enough to force the switch.
- **Verdict: Real benefit, but immaterial at Phase 1 scale. Relevant in 12-18 months.**

**2. Track record credibility (PortfolioAnalyst GIPS).**
- IB's PortfolioAnalyst provides institutional-grade performance reporting with GIPS-adjacent calculations built in.
- Alpaca provides only basic P&L; no GIPS framework, no attribution analysis.
- The first institutional allocator conversation realistically occurs 18-24 months out (per `From_Solo_AI_Trader_to_Fund_Manager` research doc).
- Switching from Alpaca to IB at the time of fundraising does not forfeit prior track record — both brokers provide monthly statements that can be compiled by an independent CPA.
- **Verdict: Real benefit, but 18-24 months premature. No credibility lost by deferring.**

**3. Asset class breadth (options, futures, bonds, international).**
- Alpaca offers US equities, options, and crypto. Phase 1 (Equity Swing) uses only US equities.
- Phase 3-4 Options Volatility Desk requires options with deep strike coverage — Alpaca's options offering is newer and may have narrower chains on mid-cap names.
- Phase 5+ (Equity Momentum, Intraday) is US equities only, fully covered by Alpaca.
- **Verdict: Real benefit, but Phase 3-4 specific. Not needed through Phase 2.**

**4. Margin economics at scale.**
- IB offers tiered margin rates (4-6% range) and portfolio margin starting at $110K equity, which can 2-3× buying power.
- Alpaca offers flat margin at 3.75% but no portfolio margin option.
- Current shadow equity is $100K. Portfolio margin threshold not yet reached.
- Phase 1 explicitly runs unleveraged per risk scaling tiers (2% risk, no leverage until $25K+ AUM with demonstrated edge).
- **Verdict: Real benefit at $250K+ live capital, irrelevant at current scale.**

### The four real costs of active IB integration during Phase 1

**1. Engineering time.** IB Gateway connection stability, market data subscription errors (10089, 300, 354), reconciliation edge cases, and shadow log sync consume approximately 4-6 hours per week of debugging and monitoring. The April 10 cascade involved IB-specific error paths.

**2. Cognitive load.** Every dashboard page, every sync cycle, every audit has to account for "is this Alpaca or IB?" This complexity has no Phase 1 benefit.

**3. Broker ambiguity in metrics.** Current reporting mixes Alpaca shadow trades with IB paper positions, creating apparent noise in Sharpe and win-rate calculations. Removing IB cleans up the data.

**4. Opportunity cost.** Every Saturday sprint spent on IB stability is a sprint not spent on Sharpe optimization (exit architecture, vol-targeting, regime filters, earnings filter, attribution resolver hardening).

### The alternative: Alpaca-only through Phase 1 and Phase 2

With Alpaca as sole broker:
- One execution path, one data path, one reconciliation surface
- PFOF routing is acceptable at current position sizes (0.30-0.75% drag is within the error bars of the current 0.585 Sharpe)
- Bracket order support is solid and battle-tested
- Paper + live is a single API call difference
- Sync pipeline simplifies dramatically
- NSSM service stops needing to manage two broker connections

### What we preserve by keeping the IB account dormant

- Account opening date (matters for future "longest broker relationship" claims)
- Funding history
- API credentials and paper account
- All integration code (dormant, not deleted)
- The option to reactivate in 2-4 weeks when the trigger conditions are met

---

## Reactivation Triggers

Reactivate IB integration work when **any one** of these is true:

### Trigger A: Phase 1 validation complete
- 50+ closed trades with Sharpe ≥ 0.8 (verified with Deflated Sharpe Ratio)
- Attribution resolver shows LLM adds alpha vs ranker-only
- Zero critical bugs in 30 days
- At this point, live capital grows to $100K-$250K range and IB execution quality begins to matter

### Trigger B: Options Volatility Desk prep begins
- Phase 2 (Equity Research Desk) profitability gates cleared
- Options collectors have 6+ months of data
- Seeking to trade vertical spreads at $15-25K notional
- IB becomes necessary for options chain depth

### Trigger C: Institutional allocator conversations
- A capital allocator (family office, emerging manager fund-of-funds, etc.) enters due diligence
- GIPS-adjacent reporting becomes a deal requirement
- PortfolioAnalyst setup begins 60-90 days before expected first allocation

**None of these are imminent.** The earliest is Trigger A, estimated 6-9 months out based on current trade cadence.

---

## Implementation Plan (Cold Storage, Not Deletion)

### Immediate (this week)

1. **Resolve existing IB positions**
   - Let TGT and COP bracket orders resolve naturally
   - Do not open new IB positions under any circumstance
   - If brackets fail to trigger within normal timeout, close manually via IB TWS

2. **Disable IB scheduler tasks**
   - Add config flag `trading.ib_enabled: false` to `settings.local.yaml`
   - Watch loop checks flag before IB reconciliation, bracket verification, or shadow-log writes
   - Flag defaults to `false` for all new installs

3. **Remove IB from NSSM service dependencies**
   - NSSM no longer waits on IB Gateway startup
   - Watch loop gracefully handles IB Gateway unavailability (already does, but verify)

### Short-term (next 2 weeks)

4. **Add dormant status indicator to dashboard**
   - Broker Comparison page is already replaced with Trade History
   - Settings page shows "IB Integration: Dormant (reactivate in settings)"
   - Clear visual signal that IB is intentionally off, not broken

5. **Maintain IB account active status**
   - Keep minimum balance in IB paper account
   - Log in to IB Client Portal monthly to prevent account dormancy (IB closes accounts after 12 months of inactivity)
   - Preserve API credentials in password manager for reactivation

### Preserved (not deleted)

- All IB integration code in `src/shadow_trading/ib_adapter.py` and related
- `ib_shadow_log` table and sync logic
- IB Gateway Docker configuration
- Sprint documents describing the integration (historical reference)
- `ib_async` package dependency in `requirements.txt`

---

## Risk Register

| Risk | Mitigation |
|---|---|
| Single-broker concentration (all eggs in Alpaca basket) | At $100K shadow equity, manageable. Add as monitored risk when live capital crosses $250K. |
| Alpaca API outage or broker failure | Paper trading history continues locally; brief outages are recoverable. Longer outages require manual intervention. |
| Alpaca changes PFOF or execution policy | Historical precedent: changes are pre-announced 30-60 days. Switching to IB in 60 days is feasible. |
| IB account dormancy closure | Monthly Client Portal login + small maintenance balance prevents this. |
| Sunk-cost reactivation inertia | Explicit trigger conditions in this document prevent indefinite deferral. |

---

## What This Changes Elsewhere

### Updated immediately
- **Phase 1 operational baseline:** Alpaca-only for all shadow and live trading
- **Saturday sprint queue:** IB stability sprints removed; no impact on existing queue
- **Risk scaling tiers (SD#20):** Re-annotate to note "single-broker through $250K, dual-broker at $250K+"
- **MASTER.md Section 2:** Update infrastructure list to reflect IB dormant status
- **Grafana dashboard:** Remove IB-specific panels from watch loop observability (or mark as dormant)

### Unchanged
- **Entry strategy (pullback-in-uptrend):** Unchanged
- **Phase gates and progression criteria:** Unchanged
- **LLM model and training cadence:** Unchanged
- **Research pipeline:** Unchanged
- **Target AUM milestones:** Unchanged

---

## Decision Log

**Considered alternatives:**

1. **Continue active IB + Alpaca in parallel.** Rejected because engineering cost outweighs benefit at current scale and IB's advantages are distant.

2. **Delete IB integration entirely.** Rejected because reactivation would require 30-40 hours of rework. Cold storage is cheap.

3. **Switch primary to IB immediately.** Rejected because Phase 1 is not yet validated, and Alpaca is operationally smoother — stability matters more than execution quality at current scale.

4. **Keep IB for live, Alpaca for paper.** Rejected because it creates two code paths with different semantics and complicates attribution/reporting.

**Chosen path:** Alpaca-only active, IB dormant but preserved, explicit reactivation triggers documented.

**Confidence: HIGH.** All four stated benefits of IB are either immaterial at current scale or 12+ months distant. All four stated costs are active and ongoing.

**Single biggest reason this is the right call:** Engineering time spent on IB stability is engineering time not spent on the 50-trade OOS validation, the earnings filter, the vol-targeting implementation, or the attribution resolver hardening. These are the Phase 1 priorities, and IB has been substituting for them.

---

## Referenced Research

- `docs/research/From_Solo_AI_Trader_to_Fund_Manager__A_Complete_Operational_Roadmap.md` — institutional allocator credibility timeline
- `docs/research/The_Halcyon_Framework__Compute__Value__and_Moat_for_a_Solo_AI_Trading_System.md` — capital scaling milestones
- Web searches (2026-04-16): IB execution quality benchmarks, Alpaca PFOF routing, PortfolioAnalyst GIPS compliance, hedge fund administrator requirements

---

*Authored by Claude, reviewed by Ryan Miller, 2026-04-16.*
