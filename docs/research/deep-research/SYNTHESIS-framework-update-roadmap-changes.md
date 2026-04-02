# Arcis Framework Update + Roadmap Changes — Deep Research Synthesis

**Date:** April 2, 2026
**Based on:** 3 completed deep research outputs (2,452 lines total) + April 1 operational findings
**Decision required:** Ryan approves/rejects each proposed change

---

## Executive Summary

Three deep research outputs + one day of live system operations exposed **8 strategic gaps** and validated **5 existing decisions.** The most urgent finding: the entire AI thesis is unvalidated — we don't know if the LLM adds alpha over the deterministic ranker. The second most urgent: mean reversion paper-trading should start NOW (Phase 1), not Phase 2. The third: the GPU sits 95% idle while there are existential experiments to run.

---

## Part 1: Halcyon Framework Updates

### 1.1 GPU Utilization Framework — MAJOR REVISION

**Current framework:** Target 75% sustained (inference ≤30%, training ≤45%, slack ≥25%)
**Reality:** 4.4% utilization during market hours. 95% idle.

**Proposed update:**

| Time Block | Current | Proposed | Activity |
|---|---|---|---|
| Market hours (9:30–4:00) | 4.4% (inference only) | 30–40% | Inference + alpha backtest + nightly eval warmup |
| Post-close (4:00–7:00) | ~5% (training collection) | 40–60% | Stress testing + Monte Carlo + outcome-conditioned training gen |
| Overnight (7:00–5:15) | ~10% (weekend training) | 50–70% | Continuous evaluation + parameter backtesting + scenario gen |
| Weekend | Training only | 70–80% | Full retrain + exhaustive backtest + stress test suite |

**GPU Activity Priority Stack (from research):**

| Rank | Activity | GPU hrs/day | Value | Status |
|---|---|---|---|---|
| 1 | Alpha attribution backtest (ranker-only comparison) | 1–2 | EXISTENTIAL | **NEW — build immediately** |
| 2 | Historical stress testing (2008, 2020, 2022) | 2–4 periodic | HIGH | **NEW — Phase 1** |
| 3 | Continuous nightly evaluation (canary monitoring) | 0.1 | HIGH | Exists but not wired into schedule |
| 4 | Monte Carlo position sizing | 0.5–1 | MEDIUM-HIGH | **NEW — Phase 2** |
| 5 | Ensemble inference (3–5 prompt variants) | 0.5–1 | MEDIUM | **NEW — Phase 2** |
| 6 | Exhaustive parameter backtesting | 2–4 weekend | MEDIUM | **NEW — with overfitting guardrails** |
| 7 | Synthetic scenario generation | 1–2 weekly | MEDIUM | **NEW — Phase 2** |
| 8 | Strategy discovery/mutation | 2–4 weekend | LOW-MEDIUM | **DEFER — overfitting risk too high** |

### 1.2 Training Data Framework — EXPANDED

**Current:** 7 XML-tagged input sections per training example
**Research finding:** Only 7–8 orthogonal dimensions for S&P 100, but current 7 sections only capture ~5. Three free additions close the gap.

**Proposed: 11-section architecture (hard cap from 300–1K token budget)**

| # | Section | Source | Status | Research Verdict |
|---|---|---|---|---|
| 1 | `<price>` | yfinance | ✅ Active | Keep |
| 2 | `<trend>` | Computed | ✅ Active | Keep |
| 3 | `<momentum>` | Computed | ✅ Active | Keep |
| 4 | `<regime>` | yfinance + FRED | ✅ Active | Keep + add credit spreads (FRED HY OAS, IG) |
| 5 | `<fundamentals>` | SEC EDGAR + FMP | ✅ Active | Keep + add earnings revision momentum |
| 6 | `<macro>` | FRED | ✅ Active | Keep + add GSCPI, ISM |
| 7 | `<sentiment>` | Finnhub | ✅ Active | Keep |
| 8 | `<options>` | Unusual Whales + yfinance | Passive collection | **NEW — activate when budget allows ($50/mo)** |
| 9 | `<intermarket>` | yfinance | Not built | **NEW — free: gold/copper, DXY, BTC, sector ETF RS** |
| 10 | `<calendar>` | Static + FMP | Not built | **NEW — free: FOMC proximity, OpEx, earnings density** |
| 11 | `<earnings_revisions>` | FMP | Not built | **NEW — highest-value unbuilt signal per research** |

**Key change:** Adopt Trading-R1's random source subsetting — for each training example, randomly include/exclude 2–3 sections. This teaches the model to reason with incomplete information and prevents over-reliance on any single dimension.

### 1.3 Scanning Cadence Framework — NEW

**Current:** Monolithic 30-minute scan cycle (everything refreshed together)
**Research finding:** 30 min is too fast for 8/11 dimensions, too slow for position monitoring near exits.

**Proposed: 4-tier multi-cadence architecture**

| Tier | Interval | What | API Budget |
|---|---|---|---|
| **Position Monitor** | 15 min | Open positions: price, stop/target proximity, bracket status | ~200 yfinance/day |
| **Price/Technical** | 30 min | Full universe: OHLCV, EMAs, RSI, ATR, volume, ranking | ~1,400 yfinance/day |
| **Sentiment/Regime** | 60 min | VIX, news, options flow (if active), sector rotation | ~400 Finnhub/day |
| **Fundamentals** | Daily (pre-market) | FRED macro, insider filings, analyst estimates, earnings cal | ~200 FMP + FRED/day |

**Single largest architectural improvement:** Splitting position monitoring from universe scanning. A stock near its stop needs 15-minute checks; a stock 40% above the pullback zone doesn't need checking for hours.

### 1.4 Exit Management Framework — NEW

**Current:** Pure mechanical bracket orders (stop + target + 8-day timeout)
**Research finding:** Mechanical brackets are optimal through 200 trades. But simple rule-based enhancements add ~0.15 Sharpe without LLM involvement.

**Proposed phased approach:**

| Phase | Trades | Exit Strategy | Additions |
|---|---|---|---|
| **1 (now → 50)** | 13→50 | Pure mechanical brackets | Fix live stop to 2.0× ATR (currently 1.0×!), begin MFE/MAE logging |
| **2 (50 → 200)** | 50→200 | Mechanical + rule-based enhancements | Time-based stop tightening (2.0× → 1.5× by day 5), signal exit (close > 5-day SMA) |
| **3 (200 → 500)** | 200→500 | Evaluate LLM pilot | LLM thesis invalidation detection on days 5–7 only (narrow pilot) |
| **4 (500+)** | 500+ | Full active if pilot validates | Separate exit-specialist LoRA adapter, daily conviction updates past day 3 |

### 1.5 Flywheel Optimization — NEW

**Current:** ~1 training example per closed trade
**Research finding:** 5 categories of signal waste. Should generate 3–5 examples per trade.

**Proposed changes:**

1. **Outcome-conditioned training prompts** — Different prompts for winners (emphasize thesis validation), losers (emphasize risk weighting), timeouts (emphasize signal decay), PASS decisions (equally valuable). Yield: 1→3-5 examples per trade.

2. **8 new outcome metadata columns** in shadow_trades:
   - `regime_at_entry`, `regime_at_exit`, `vix_at_entry`, `vix_at_exit`
   - `time_to_target_days`, `drawdown_from_mfe`
   - `concurrent_positions`, `ranking_at_entry`

3. **Model improvement delta tracking** — Measure actual improvement per retrain cycle. If improvement < threshold, skip retraining (saves compute, prevents model churn).

4. **Cross-strategy learning** — When mean reversion paper-trading generates data, it teaches the pullback model about regime transitions (and vice versa).

---

## Part 2: Proposed Roadmap Changes

### IMMEDIATE ACTIONS (This Week)

| # | Action | Source | Expected Value | Current Status |
|---|---|---|---|---|
| **A1** | Fix live trading stop from 1.0× to 2.0× ATR | Full strategy research | CRITICAL — prevents artificial win-rate depression | Not done |
| **A2** | Fix conviction parsing (99% broken) | April 1 log review (#183) | CRITICAL — all trades using default conviction=5 | Issue filed |
| **A3** | Fix intra-day reconciliation crash (`now` not defined) | April 1 log review (#182) | CRITICAL — reconciliation completely dead | Issue filed |
| **A4** | Fix live trades bypassing risk governor | April 1 log review | CRITICAL — real money at risk | Fix deployed, needs restart |
| **A5** | Move database off OneDrive | DB corruption incident (#181) | HIGH — prevents data loss | CC working on it |

### PHASE 1 ADDITIONS (Next 30 Days)

| # | Action | Source | Decision Required |
|---|---|---|---|
| **P1** | **Launch parallel ranker-only shadow portfolio** | Full strategy Deliverable 1 | **[APPROVE/REJECT]** — Second Alpaca paper account, same entry criteria minus LLM. This is the alpha attribution experiment. Research says 200+ paired trades needed for statistical power. |
| **P2** | **Paper-trade mean reversion strategy (Strategy #2)** | Full strategy Part 2 — "YES, unambiguously" | **[APPROVE/REJECT]** — Currently gated to Phase 2. Research says start NOW: generates 130–390 labeled examples in 6 months, provides bear market insurance for flywheel continuity, costs zero capital. |
| **P3** | **Open Collective2 strategy account** | Full strategy Deliverable 11 | **[APPROVE/REJECT]** — Track record clock starts immediately. Independently verified by third party. Top decile strategies earn $12–36K/year. Cost: ~$99/month. |
| **P4** | **Add 8 outcome metadata columns to shadow_trades** | Full strategy Deliverable 20 | **[APPROVE/REJECT]** — Via schema registry. Captures regime, VIX, time-to-target, drawdown-from-MFE, concurrent positions. +40% signal capture per trade. |
| **P5** | **Run alpha attribution backtest on historical data** | Full strategy Deliverable 1 | **[APPROVE/REJECT]** — Use idle GPU to retroactively test ranker-only vs ranker+LLM on historical candidates. 1–2 days compute. |
| **P6** | **Run historical stress tests (2008, 2020, 2022)** | Full strategy Deliverable 23 | **[APPROVE/REJECT]** — Answers the allocator's #1 question: "what happens in a crash?" Currently "napkin math." 1 week of overnight GPU. |
| **P7** | **Implement multi-cadence scanning (4-tier)** | Scanning intervals research | **[APPROVE/REJECT]** — Reduces API calls 60%, GPU load 40%. Highest-ROI architectural change. |
| **P8** | **Implement outcome-conditioned training prompts** | Full strategy Deliverable 20 | **[APPROVE/REJECT]** — 3–5x data yield per closed trade. Different prompts for winners/losers/timeouts/passes. |

### PHASE 1→2 GATE CHANGES

| Item | Current | Proposed | Justification |
|---|---|---|---|
| Trade count gate | 50 trades | 50 trades (no change) | — |
| Alpha attribution | Not required | **ADD: Alpha attribution experiment running with ≥50 paired trades** | Can't scale what we can't validate |
| Mean reversion paper data | Not started | **ADD: ≥100 paper trades on Strategy #2** | Bear market insurance, correlation data |
| Stress test | Not required | **ADD: Historical stress test completed (2008, 2020, 2022)** | Due diligence requirement |

### OPTIONS TIMING — MOVED UP

| Item | Current Roadmap | Proposed | Justification |
|---|---|---|---|
| Options paper-trading | Phase 3–4 ($50K+ AUM) | **Phase 2 ($15–25K AUM) with vertical spreads only** | Research derived minimum capital: $15K for defined-risk spreads satisfying 2% max loss, <50bps bid-ask drag, positive EV after theta. Naked options destroy small accounts but verticals are viable earlier. |

### PHASE 2 SERVER — CONFIRMED + EXPANDED

The dedicated trading server spec (~$1,300) is confirmed. Add:
- **Collective2 strategy sync** — auto-publishes trades for verified track record
- **Ranker-only shadow portfolio** — runs permanently alongside LLM portfolio
- **Mean reversion strategy** — second watch loop instance with different config
- **Local PostgreSQL 16** — replaces SQLite, eliminates corruption class

### REVENUE SEQUENCING — NEW

| Month | Revenue Stream | Milestone |
|---|---|---|
| 0 (now) | Personal trading returns + capital injections ($1K/mo) | Start |
| 3 | Open Collective2 account | Track record clock starts |
| 6 | Phase 1 gate passed → go live with $5–10K | Verifiable live returns begin |
| 12 | Signal marketplace revenue ($200–$1K/mo) + RIA outreach | First external revenue |
| 18 | Wyoming LLC + Section 475(f) | Legal entity |
| 24 | Fund formation at $1–2M AUM | Management + performance fees |
| 36 | Fund self-sustaining at $2M+ AUM | Day job optional |

### STRATEGY DECISIONS — UPDATED

| # | Strategy | Current | Proposed | Research Source |
|---|---|---|---|---|
| 1 | Pullback | LIVE (Phase 1) | No change | — |
| 2 | Mean Reversion | Phase 2 (gated) | **START PAPER-TRADING NOW** | Full strategy: "YES, unambiguously" |
| 3 | Evolved PEAD | Phase 3 | No change (PEAD dead for large caps) | Martineau 2022 |
| 4 | Momentum | Phase 5 | No change | — |
| 5 | Options (vertical spreads) | Phase 3–4 at $50K | **MOVE TO Phase 2 at $15–25K** | Full strategy Deliverable 8 |

---

## Part 3: Framework Validated (No Change Needed)

These existing decisions were confirmed by the research:

1. **Equal weight (1/N) beats optimization until 200+ trades** ✅ Confirmed
2. **Weekly Saturday retrain = nightly at 90% lower cost** ✅ Confirmed
3. **Self-blinding is architectural, not instructional** ✅ Confirmed
4. **Training data quality > quantity** ✅ Confirmed (LIMA, AlpaGasus)
5. **S&P 100 universe is correct for Phase 1** ✅ Confirmed (expand to S&P 500 in Phase 2–3)
6. **8-day timeout captures >90% of pullback alpha** ✅ Confirmed
7. **ATR-based stop widening by VIX regime** ✅ Confirmed (2.0×/2.5×/3.0×)
8. **Fund path: LLC → incubator → registered fund** ✅ Confirmed (break-even ~$2M AUM)

---

## Part 4: Action Priority Matrix

**Do in this order. Items higher up are more valuable AND more urgent.**

### Tier 1: Do Today
1. Fix live trading stop 1.0× → 2.0× ATR (10 minutes)
2. Fix conviction parsing (#183) — all trades using wrong size
3. Fix intra-day reconciliation crash (#182) — one line
4. Restart watch loop to deploy risk governor fix

### Tier 2: Do This Week
5. Launch alpha attribution experiment (parallel ranker-only portfolio)
6. Open Collective2 account (track record clock starts)
7. Add 8 outcome metadata columns via schema registry
8. Wire nightly canary monitoring into compute schedule

### Tier 3: Do This Month
9. Paper-trade mean reversion Strategy #2
10. Run historical stress tests (2008, 2020, 2022)
11. Implement multi-cadence scanning (4-tier)
12. Implement outcome-conditioned training prompts (3–5x yield)
13. Build alpha attribution backtest on historical data

### Tier 4: Phase 2 (After Gate)
14. Implement time-based stop tightening + signal exit
15. Deploy VIX-adaptive bracket parameters
16. Build dedicated trading server ($1,300)
17. Paper-trade options vertical spreads at $15–25K
18. Register Darwinex DARWIN (second track record)
19. File Wyoming LLC + Section 475(f)

---

*Every action feeds the same flywheel: more trades → more data → better model → better trades → more AUM → more revenue → more compute → wider moat. The binding constraint is the 200-trade statistical threshold. Every action should accelerate reaching that threshold.*
