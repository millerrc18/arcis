# Arcis — System State Document
## March 27, 2026, 3:00 AM ET

> This document captures the complete state of Arcis at the end of the first build marathon.
> It serves as the baseline for all future progress tracking.

---

## System Identity

**Name:** Arcis
**Brand:** Arcis Palette H (Electric Focus: blue #3B82F6, teal #14B8A6, graphite #050507)
**Domain:** halcyonlab.app (IONOS, 2-year prepaid)
**Tagline:** Systematic Equity Research
**Business model:** Returns-based. Scale capital under management, not subscriptions.
**Moat:** Training data quality — hardest to replicate, compounds over time.

---

## Codebase Metrics

| Metric | Count |
|--------|-------|
| Python files | 121+ |
| Lines of code | 22,174+ |
| Tests | 638 (50 test files) |
| Database tables | 25 local + 5 new collector tables |
| API routes (local) | 62 |
| API routes (cloud) | 16 (19+ more coming in Sprint v5) |
| CLI commands | 49 |
| React pages | 11 |
| React components | 37+ |
| Research documents | 35 |
| Data collectors | 12 (13th — research — coming) |

---

## Infrastructure

### Local Machine
- **GPU:** NVIDIA RTX 3060 12GB VRAM
- **RAM:** 32GB
- **OS:** Windows
- **Python:** 3.12
- **LLM:** Ollama → halcyonlatest (Qwen3 8B Q8_0 GGUF, 8.7GB)
- **Database:** SQLite (ai_research_desk.sqlite3)
- **Training:** PEFT + TRL 0.24 + BitsAndBytes

### Cloud
- **Frontend:** Render static site (halcyonlab.app)
- **API:** Render Starter plan ($7/mo) — Python/FastAPI
- **Database:** Render Postgres ($7/mo)
- **Domain:** IONOS (halcyonlab.app, 2-year prepaid)
- **Sync:** Every 2 minutes, 17 tables, ~1,000+ rows/cycle

### External Services
- **Brokerage:** Alpaca ($100K paper + $100 live)
- **AI:** Anthropic Claude API (Sonnet for council + training data)
- **Market data:** yfinance (being replaced by Polygon.io $29/mo)
- **Enrichment:** Finnhub (fundamentals, insider, news, analyst estimates)
- **Macro:** FRED (33 series)
- **Filings:** SEC EDGAR (10-K, 10-Q, 8-K)
- **Notifications:** Telegram (12 commands, 22/27 notification types)
- **Email:** Gmail SMTP (daily summary mode)

### Monthly Costs
| Item | Cost |
|------|------|
| Render API + Postgres | $14/mo |
| Claude API | ~$30-50/mo |
| Domain | $0 (prepaid) |
| **Total current** | **~$44-64/mo** |
| Polygon.io (planned) | +$29/mo |
| Unusual Whales (Phase 3) | +$50/mo |

---

## Trading State

| Metric | Value |
|--------|-------|
| Open positions (paper) | 18 |
| Closed trades | 2 (CSCO +4.4%, LIN +3.6%) |
| Win rate | 100% (2/2 — not statistically meaningful) |
| Paper starting capital | $100,000 |
| Live starting capital | $100 |
| Live positions | 0 (buying power exhausted — live exit bug) |
| Strategy | Pullback-in-uptrend |
| Universe | S&P 100 (~103 tickers) |
| Hold period | 2-15 days |
| Position sizing | 1-2% risk per trade |

---

## Training Pipeline State

| Metric | Value |
|--------|-------|
| Total examples | 978 |
| Sources | 704 historical_backfill, 194 blinded_win, 77 blinded_loss, 3 synthetic_claude |
| Curriculum stages | 976 structure, 0 evidence, 0 decision, 2 null |
| Quality scores (Claude) | 0/978 scored |
| Quality scores (Ollama) | ~200 scored (avg 3.1-3.2) |
| Active model | halcyonlatest (Qwen3 8B Q8_0 GGUF) |
| Training method | QLoRA (PEFT + TRL 0.24) |
| Retrain schedule | Saturday weekly |
| LLM template fallback rate | 62% (root cause: training data format mismatch) |

### Training Data Issues Found (7)
1. 🔴 Format mismatch: training data has markdown headers + bold, parser expects clean XML
2. 🔴 976/978 examples are curriculum_stage "structure" — 3-stage curriculum unused
3. 🟡 Conviction format: `5.5/10` with bold, parser regex only matches integers
4. 🟡 Zero Claude quality scores across all 978 examples
5. 🟡 704 backfill examples missing regime context
6. ✅ Self-blinding working correctly
7. ✅ Data collector architecture is clean

---

## 24-Hour Schedule (27 events, all wired)

| Time | Event | Status |
|------|-------|--------|
| 5:15 AM | VRAM → inference | ✅ |
| 6:00 AM | Pre-market refresh + brief | ✅ |
| 6:02 AM | Rolling features | ✅ (no Telegram) |
| 7:00 AM | Premarket training gen | ✅ (no Telegram) |
| 8:00 AM | Earnings proximity + watchlist | ✅ |
| 8:02 AM | News scoring | ✅ (no Telegram) |
| 8:30 AM | AI Council (5 agents) | ✅ |
| 9:00 AM | Premarket candidates | ✅ (no Telegram) |
| 9:25 AM | Ollama warm-up | ✅ |
| 9:30-4:00 | Market scans (every 30 min) | ✅ |
| 9:30-4:00 | Between-scan scoring | ✅ |
| 4:00 PM | EOD recap + P&L report | ✅ |
| 4:15 PM | Daily audit | ✅ |
| 4:30 PM | Training collection + data asset report | ✅ |
| 5:00 PM | Training trigger check | ✅ |
| 5:30 PM | Post-close capture | ✅ |
| 6:00 PM | Overnight training collection | ✅ |
| 6:50 PM | VRAM → training | 🔴 BROKEN (Ollama won't release VRAM) |
| 9:30 PM | 12 data collectors | ✅ |
| 10:00 PM | News ingestion | ✅ |
| 11:00 PM | Enrichment precache | ✅ |
| Sat 9 AM | Saturday retrain report | ✅ |
| Sun 8 PM | Weekly digest | ✅ |

---

## Known Bugs (from comprehensive audit)

### 🔴 Critical (9)
| # | Bug | Status |
|---|-----|--------|
| 0A | Live trades never close (place_live_exit never called) | In Sprint v5 |
| 0B | Risk governor blocks all trades (18 open > limit 10) | In Sprint v5 + manual config fix |
| 0C | Starting capital $1,000 not $100,000 | In Sprint v5 + manual config fix |
| 0D | LLM 100% timeout (first scan) + 62% parse failure | In Sprint v5 + Follow-up #1 |
| 0E | Trade management KeyError ('action') | In Sprint v5 |
| 0F | VRAM handoff fails (Ollama holds 1.3GB) | In Sprint v5 |
| 0G | SPY close returns $0.00 | In Sprint v5 |
| 0H | Double logging every packet | In Sprint v5 |
| 0I | Apple meta tag deprecated | In Sprint v5 |

### 🟡 High Priority (6)
| # | Issue | Status |
|---|-------|--------|
| H1 | 6 tables not in Render sync | In Sprint v5 |
| H2 | 13+ cloud API endpoints missing | In Sprint v5 |
| H3 | Docs page JS crash (.map error) | In Sprint v5 |
| H4 | First scan summary never fires | In Sprint v5 |
| H5 | Risk governor default too low (10) | In Sprint v5 |
| H6 | Training data format mismatch | In Follow-up #1 |

---

## Sprint History

| Sprint | Content | Status |
|--------|---------|--------|
| v1 | Mega Sprint (9 WS: Council, Render, classifier, features, etc.) | ✅ Complete |
| v2 | Cleanup (flywheel, live trading, auth, logging, docs) | ✅ Complete |
| v3 | Notifications + Dashboard Brand Overhaul (12 notifications, Arcis prelaunch brand) | ✅ Complete |
| v4 | Free Data Collectors (5 new, FRED expansion, Trends fix) | ✅ Complete |
| v5 | Critical fixes + Cloud API + Dashboard 2.0 + Ops + Research-informed | 🔄 In progress (CC working) |
| v5-FU1 | Training data cleanup + Observability + Visualizations | 📋 Queued |
| v5-FU2 | Research Intelligence Collector (#13) | 📋 Queued |

---

## Research Library (35 documents)

### Strategy & Markets
1. SP100 Pullback Trading Profiles (complete constituent database)
2. SP100 Current Market Assessment (March 2026)
3. US Equity Market Regime Timeline 2015-2026 (33 periods)
4. Multi-Strategy Pattern Classification
5. Alternative Data Signals Cost-Benefit Analysis
6. Market Event Calendar 2020-2027
7. Optimal Trading Universe Size (325 stocks)

### Training & Model
8. Best Local LLM for Financial Analysis (Qwen selection guide)
9. Training Data Strategies for Small Financial LLMs
10. Optimal Training Formats for Equity Commentary
11. Gold-Standard Rubric for Scoring Commentary
12. Preventing Model Degradation in Iterative QLoRA
13. Prompt Engineering for Self-Blinding Pipelines
14. GRPO for Financial LLMs on Consumer Hardware
15. Halcyon v2 Training Dataset Specification

### Infrastructure & Operations
16. Arcis Framework (Compute, Value, Moat)
17. Optimal 24x7 GPU Schedule
18. Data Infrastructure Audit Per Desk
19. Market Data APIs Comparison 2026
20. Halcyon Scaling Plan Through 2026

### Business & Legal
21. AI-Powered Equity Research Business Plan
22. Arcis Business Plan Operating Manual
23. From Solo Trader to Fund Manager (Operational Roadmap)
24. Arcis Complete Brand Identity System
25. Competitive Benchmarking Report
26. Options Trading Education Plan

### Deep Research (received this session)
27. LLC + Section 475 MTM Election Playbook
28. Breakout Strategy Implementation Spec
29. Walk-Forward Validation Framework (50/100/200/500 trade gates)
30. SEC EDGAR Filing Analysis for Trading Signals

### Synthesis
31. Perplexity Deep Research Playbook (18-month roadmap, training data scaling, regime intelligence, competitive moat, API budget optimization)

### Pending
32. Advanced Risk Management (SEC EDGAR filed, deep research pending)

---

## 18-Month Roadmap Summary

| Quarter | Phase | Key Milestone | Gate |
|---------|-------|---------------|------|
| Q1 (Apr-Jun 2026) | Bootcamp hardening | 50 closed trades, 2,200 examples | Win rate ≥45%, PF ≥1.3, DD ≤12% |
| Q2 (Jul-Sep 2026) | Walk-forward + LLC | 100 trades, Wyoming LLC formed | PSR >90%, Sharpe >0 |
| Q3 (Oct-Dec 2026) | Breakout R&D + scaling | 200 trades, 5,000 examples | Sharpe ≥1.0, PSR ≥95% |
| Q4 (Jan-Mar 2027) | Capital scaling | $100→$1,000 live, breakout paper | PSR >90%, DD <15% |
| Q5 (Apr-Jun 2027) | Investor readiness | 500 trades, $5K-$10K live | DSR >0.95, PSR ≥99% |

### Capital Scaling Gates (performance-based, not time-based)
- $100 → $1,000: 100+ trades, PSR >90%, DD <15%
- $1,000 → $5,000: 100-150 more trades, PSR >90% Sharpe >0.2
- $5,000 → $10,000: Another 100-150 trades, DSR >0.95

### API Budget Plan ($100 total)
- Months 1-3: ~$30 (quality scoring existing examples, regime gap filling)
- Months 4-9: ~$40 (DPO pairs from live trades, scoring new examples)
- Months 10-18: ~$30 (regime-diverse corner cases, GRPO reward data)

---

## Pending Manual Actions

### Urgent (before market open)
- [ ] Change API_SECRET on Render from test123
- [ ] Change starting_capital: 1000 → 100000 in settings.local.yaml
- [ ] Change risk_governor.max_open_positions: 10 → 50 in settings.local.yaml

### This Weekend
- [ ] Rotate Anthropic API key (exposed in conversation)
- [ ] Rotate Finnhub API key (exposed in conversation)
- [ ] Buy $100 Anthropic API credits (prepaid Visa)
- [ ] Set up Termius SSH on phone → Tailscale IP

### When CC Finishes Sprint v5
- [ ] git pull + restart watch loop
- [ ] Run render_migrate.py (if new tables added)
- [ ] Verify all dashboard pages work on halcyonlab.app

### When CC Finishes Follow-up #1
- [ ] Run training data cleanup scripts (5 scripts in order)
- [ ] Run quality scoring on all 978 examples (~$5-8 API)
- [ ] Verify 100% parser success rate

### Weekly Ritual (Sunday nights)
- [ ] Export 20 recent training examples → upload for Claude review
- [ ] Upload arcis.log for anomaly analysis
- [ ] Screenshot dashboard → review with Claude
- [ ] Review research digest (once collector #13 is live)
- [ ] Prepare Monday action items

---

## Key Decisions Made

1. **Business model:** Returns-based fund, not newsletter/signals. Scale capital, not subscriptions.
2. **Training data is the moat.** Not the model, not the returns — the curated, regime-diverse, live-anchored training corpus.
3. **Self-blinding is architectural, not instructional.** Claude never sees outcomes during training data generation.
4. **Separate LoRA adapters per strategy.** Pullback and breakout get independent models.
5. **Performance-gated milestones.** Every phase transition requires passing quantitative gates.
6. **50 trades is a filter, not a verdict.** 200+ trades needed for moderate edge detection.
7. **The $100 live account is strategically essential.** Auditable real-money track record for institutional capital.
8. **Weekly Saturday retrain, not nightly.** 90% lower cost, equal results.
9. **Keep Claude API for council + training data.** Local LLM for these tasks causes model collapse.
10. **Wyoming LLC in Phase 2.** Section 475 MTM within 75 days of formation.

---

*This document was generated at the end of the first build marathon (March 26-27, 2026). The system is live, the watch loop is running, and the first pre-market brief fires at 6:00 AM.*
