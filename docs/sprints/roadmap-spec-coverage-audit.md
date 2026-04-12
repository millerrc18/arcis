# Roadmap Item → Spec/Plan Coverage Audit

**Date:** April 12, 2026
**Purpose:** Ensure every pending/in-progress roadmap item has a linked spec or implementation plan.

---

## Coverage Key
- ✅ **Spec exists** — linked below
- ⚠️ **Partial** — research exists but no implementation plan
- ❌ **No spec** — needs to be written
- 🔧 **Operational** — not a code task, no CC sprint needed

---

## Phase 1 — In Progress / Pending

| # | Item | Status | Spec/Plan | Gap |
|---|------|--------|-----------|-----|
| 1 | Alpha attribution experiment | in-progress | ✅ `sprint-ib-complete-lineup.md` (attribution wiring in DB-2a Task 6) | Attribution hooks disconnected — DB-2a fixes |
| 2 | Paper-trade mean reversion (Strategy #2) | in-progress | ✅ `Strategy_2_Selection__Mean_Reversion_Wins.md` | Accumulating trades, no sprint needed |
| 3 | Manual backfill pipeline | in-progress | ✅ `sprint-manual-backfill.md` | ✅ Complete — 703 imported |
| 4 | Conviction calibration logging | pending | ✅ `capital-velocity-optimization.md` + `LLM_Conviction_Score_Calibration_for_Trading.md` | time_to_mfe in DB-1 Task 9, calibration at 100+ trades |
| 5 | Open Collective2 account | pending | 🔧 `From_Solo_AI_Trader_to_Fund_Manager.md` | Ryan manual task — ~$99/mo, sign up |
| 6 | Expand training XML 7→11 sections | pending | ⚠️ `sprint-xml-expansion.md` exists | Needs review — may be outdated |
| 7 | iOS app (Capacitor) | pending | ✅ `sprint-ios-capacitor.md` | Ready for CC when prioritized |
| 8 | PRODUCTION_MODEL config key | pending | ❌ | **Needs spec** — 1-page design: config key specifies exact model name, startup validates against Ollama |
| 9 | IB shadow mode | pending | ✅ `sprint-ib-tests-shadow.md` | ✅ Complete — merged |
| 10 | Stress test data caching | pending | ❌ | **Needs spec** — cache yfinance downloads locally, ~5 min vs 45-90 min |
| 11 | Stress test survivorship bias fix | pending | ⚠️ Referenced in roadmap research | **Needs spec** — use historical S&P 100 membership |
| 12 | Stress test: 4 additional scenarios | pending | ✅ `sprint-dashboard-fixes.md` DB-3 Task 6 | Covered in dashboard sprint |
| 13 | Stress test: use Alpaca historical API | pending | ❌ | **Needs spec** — replace yfinance with Alpaca bars API |
| 14 | Full-regime simulation engine | pending | ✅ `sprint-simulation-engine.md` + `design-simulation-engine.md` | Exists on stale branch `feat/simulation-engine` — review |
| 15 | Hold period analysis at 50 trades | pending | ✅ `capital-velocity-optimization.md` Component 2 | Triggered at 50-trade milestone |
| 16 | Monthly salary injection tracking | pending | ⚠️ Referenced in Scaling Levers research | **Needs spec** — dashboard widget, DCA tracking |

## Phase 2 — Pending

| # | Item | Status | Spec/Plan | Gap |
|---|------|--------|-----------|-----|
| 17 | Form Wyoming LLC | pending | 🔧 `Algorithmic_Trader_Tax_Strategy_TTS_475f.md` + `Fund_Formation_Roadmap.md` | Ryan manual — legal/tax, target July 2026 |
| 18 | Section 475 MTM election | pending | 🔧 `Algorithmic_Trader_Tax_Strategy_TTS_475f.md` | Ryan manual — within 75 days of LLC formation |
| 19 | Polygon.io Starter ($29/mo) | pending | 🔧 `Market_Data_APIs_Comprehensive_Comparison_2026.md` | Ryan manual — subscribe when budget allows |
| 20 | CPA for trader taxation | pending | 🔧 `Algorithmic_Trader_Tax_Strategy_TTS_475f.md` | Ryan manual |
| 21 | Random-entry benchmark (Account #2) | pending | ⚠️ `Walk-Forward_Backtesting_Protocol.md` references it | **Needs spec** — second Alpaca paper account, random stock + same exits |
| 22 | Universe expansion (103→~325) | pending | ✅ `Optimal_Trading_Universe_Size.md` | Research done, implementation plan needed |
| 23 | Research Analyst desk (Account #3) | pending | ⚠️ Referenced in MASTER.md | **Needs spec** — relaxed thresholds, 3-5x data, tagged research_desk |
| 24 | Parametric VaR (Ledoit-Wolf) | pending | ⚠️ `Risk_Budgeting_for_3-Strategy_Equity_System.md` | **Needs implementation plan** — formulas exist, no sprint |
| 25 | Correlation-adjusted sizing | pending | ⚠️ Referenced in risk research | **Needs spec** — sliding scale by correlation bucket |
| 26 | Execution infrastructure (slippage + TCA) | pending | ⚠️ `ib-paper-fill-simulation.md` has context | **Needs spec** — 9 bps RT model, arrival price tracking |
| 27 | Performance attribution system | pending | ❌ | **Needs spec** — decompose alpha by source (strategy vs pipeline vs LLM) |
| 28 | Portfolio-level VaR + correlation monitoring | pending | ⚠️ `Risk_Budgeting.md` | **Needs implementation plan** |
| 29 | Stop-loss methodology documentation + audit | pending | ⚠️ Spread across multiple docs | **Needs consolidation** — formal exit decision tree doc |
| 30 | 7-scenario stress testing | pending | ✅ `sprint-dashboard-fixes.md` DB-3 Task 6 | Covered |
| 31 | Isolation Forest anomaly detection | pending | ✅ `llm-authority-boundaries.md` Tier 2 | **Needs implementation plan** — research exists |
| 32 | FinBERT material event alerts | pending | ✅ `Financial_NLP_FinBERT_Deployment.md` + `llm-authority-boundaries.md` | **Needs implementation plan** |
| 33 | Market regime narrative enrichment | pending | ✅ `llm-authority-boundaries.md` Tier 2 | **Needs implementation plan** |
| 34 | Paper-to-live concordance testing | pending | ⚠️ `Walk-Forward_Backtesting_Protocol.md` | **Needs spec** — KS test on P&L distributions |
| 35 | Scale training data to 3,000+ | pending | ✅ `Preventing_Model_Degradation.md` + `sprint-manual-backfill.md` | Roadmap: backfill → DPO pairs → regime-diverse synthetic |
| 36 | Scale live $100→$1,000 | pending | 🔧 `Halcyon_Lab_Scaling_Plan_Through_2026.md` | Gated on 100+ trades, PSR >90% |
| 37 | Dedicated Arcis machine (~$1,500) | pending | 🔧 Referenced in hardware roadmap | Ryan manual — hardware purchase |
| 38 | Dead man's switch (Raspberry Pi) | pending | ❌ | **Needs spec** — independent watchdog, stale >4hr = stop, >48hr = flatten |

## Phase 3 — Pending

| # | Item | Status | Spec/Plan | Gap |
|---|------|--------|-----------|-----|
| 39 | Breakout indicators | pending | ⚠️ `Multi-Strategy_Pattern_Classification.md` | **Needs implementation plan** |
| 40 | Breakout paper trading + labeling | pending | ⚠️ Same research | **Needs spec** — triple-barrier labeling, 300-500 setups |
| 41 | Separate breakout LoRA adapter | pending | ✅ `Multi-LoRA_Serving_on_Consumer_GPUs.md` | Research complete |
| 42 | GRPO training experiments | pending | ✅ `GRPO_for_Financial_LLMs_on_Consumer_Hardware.md` | Blocked on RTX 3090 + 100 trades |
| 43 | Fama-French factor exposure | pending | ❌ | **Needs spec** — 5-factor model, detect hidden tilts |
| 44 | Series 65 exam study | pending | 🔧 | Ryan manual — 40-80 hrs study |
| 45 | Options: covered calls | pending | ✅ `AI-Powered_Options_Trading.md` + `Options_Trading_Education_Plan.md` | Research done |
| 46 | Options: vertical spreads | pending | ✅ Same | Research done |
| 47 | Scale live $1K→$5K | pending | 🔧 | Gated on metrics |
| 48 | Account-size risk scaling | pending | ✅ `Scaling_Levers_5K_to_3M.md` | Tier structure defined, needs implementation sprint |
| 49 | Leveraged ETF evaluation | pending | ⚠️ `Scaling_Levers_5K_to_3M.md` | **Needs spec** — UPRO/TQQQ for 1-5 day pullbacks |

## Phase 4+ — Pending

| # | Item | Status | Spec/Plan | Gap |
|---|------|--------|-----------|-----|
| 50 | IB live trading activation | pending | ✅ `sprint-ib-complete-lineup.md` IB-6 | ✅ Sprint complete |
| 51 | Process separation | pending | ❌ | **Needs spec** — Signal/Risk/Exec/Watch as 4 processes |
| 52 | Activate Reg T margin | pending | ⚠️ `Scaling_Levers_5K_to_3M.md` | Research exists, no sprint |
| 53 | MES futures | pending | ⚠️ Same | Research exists, no sprint |
| 54 | Fund formation items (audit, PPM, GIPS, etc.) | pending | 🔧 `Fund_Formation_Roadmap.md` | Ryan + legal, Year 3+ |

---

## Summary

| Status | Count | % |
|--------|-------|---|
| ✅ Spec exists | 21 | 39% |
| ⚠️ Research exists, needs implementation plan | 17 | 31% |
| ❌ No spec at all | 8 | 15% |
| 🔧 Operational (not code) | 8 | 15% |
| **Total** | **54** | |

## Items Needing New Specs (Priority Order)

### Must-write (Phase 1-2, will be needed within 3 months):
1. **Random-entry benchmark** (#21) — strongest proof of model value-add
2. **Research Analyst desk** (#23) — second data generation path
3. **Execution infrastructure / TCA** (#26) — required before scaling
4. **Performance attribution** (#27) — no spec at all, gap assessment flagged this
5. **Dead man's switch** (#38) — safety critical
6. **PRODUCTION_MODEL config key** (#8) — prevents wrong-model inference

### Should-write (Phase 2-3, 3-6 months):
7. **Correlation-adjusted sizing** (#25)
8. **Paper-to-live concordance** (#34)
9. **Isolation Forest implementation** (#31)
10. **FinBERT implementation** (#32)
11. **Breakout strategy implementation** (#39, #40)
12. **Process separation** (#51)

### Can-defer (Phase 3+):
13. Fama-French factor exposure (#43)
14. Leveraged ETF evaluation (#49)
15. Stress test caching (#10)
16. Stress test survivorship fix (#11)
17. Stress test Alpaca API (#13)
