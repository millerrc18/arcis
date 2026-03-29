# Roadmap Additions — March 28, 2026

## Strategy Decisions (CONFIRMED)

| Decision | Status | Source |
|---|---|---|
| Strategy #2 = Mean Reversion | **CONFIRMED** | Strategy #2 Selection research |
| Strategy #3 = Evolved PEAD (composite earnings info system) | **CONFIRMED** | PEAD Evolved research |
| PEAD signals as pullback enrichment features | **CONFIRMED** for Phase 2 | PEAD Evolved research |
| RL method = Dr. GRPO (`loss_type="dr_grpo"`) | **CONFIRMED** | REINFORCE++ research |
| Skip DPO entirely | **CONFIRMED** | REINFORCE++ + Fin-o1 |
| Breakout = feature within pullback, not separate strategy | **CONFIRMED** | Multi-strategy scaling research |
| Traditional PEAD dead for large caps | **CONFIRMED** | Martineau 2022, Subrahmanyam 2025 |
| Regime: Traffic Light Phase 1, HMM Phase 2-3 | **CONFIRMED** | Regime Detection research |

## Phase 2 Additions (new items from research)

### PEAD Enrichment Features for Pullback Adapter
- Earnings surprise magnitude (Finnhub `company_earnings()`)
- Revenue-EPS concordance (revenue beat + EPS beat = stronger signal)
- Analyst revision velocity (rate of estimate changes in 30 days pre-earnings)
- Recommendation inconsistency (surprise direction vs consensus rating — 2.5-4.5× stronger drift)
- Earnings proximity flag (days to next earnings — affects pullback risk)
- Source: PEAD Evolved research, McCarthy (2025)
- Implementation: add to `src/data_enrichment/` as new module, include in LLM prompt

### Mean Reversion Strategy #2
- Connors RSI(2) primary signal + regime-conditional sizing
- Separate LoRA adapter (different signal source = always separate)
- Separate Alpaca paper account
- Training data: ~20,000-25,000 historical labeled examples available
- Source: Strategy #2 Selection research
- Gate: pullback 100+ trades with PSR >90%

## Phase 3 Additions

### Evolved PEAD as Strategy #3
- NOT traditional beat/miss — composite earnings information system
- 12-quarter elastic net SUE model (trains on SUE_t-1 through SUE_t-12)
- NLP sentiment surprise via FinBERT on Ollama
- Revenue concordance filtering
- Analyst revision velocity as confirming signal
- Recommendation inconsistency as position sizing multiplier
- Entry: day+1 at open +15 minutes
- Exit: triple-barrier at 10 trading days
- Size: quarter-Kelly, max 4 concurrent positions
- Expected: ~15-30 qualifying trades per quarter, Sharpe 0.6-0.9
- Source: PEAD Evolved research, Kaczmarek & Zaremba 2025
- Gate: mean reversion 100+ trades with PSR >90%
- Monitor: quarterly out-of-sample AUC; if <0.55, consider IV crush alternative

### Regime Detection Upgrade
- Phase 2 MVP: Statistical Jump Models via `jumpmodels` Python library
- Phase 3: 2-state HMM ensemble + VIX term structure features
- Source: Quantitative Regime Detection research
- Estimated impact: 15-25% drawdown reduction

## Decision Flags (evaluate at specified gates)

### At 50-trade gate (Phase 1 → Phase 2 transition):
- [ ] Is pullback edge statistically significant? (PSR >90%, MinTRL check)
- [ ] What regime coverage do we have? (need ≥2 distinct regimes)
- [ ] Are PEAD enrichment features ready for pullback adapter?
- [ ] Is mean reversion implementation spec ready?
- [ ] Does the Traffic Light regime system change enough to justify building?

### At 100-trade gate:
- [ ] Is Dr. GRPO ready to fire? (need 100+ closed trades with outcomes)
- [ ] Has the training pipeline run end-to-end at least 4 times (Saturday retrains)?
- [ ] Is mean reversion paper trading generating enough data?
- [ ] What does the alpha decay scorecard show?

### At 200-trade gate (Phase 2 → Phase 3 transition):
- [ ] Is combined pullback + mean reversion SR ≥1.0?
- [ ] Has the correlation between strategies held at ρ ≈ −0.35?
- [ ] Is the evolved PEAD implementation spec ready?
- [ ] Is the 12-quarter elastic net model validated on out-of-sample data?
- [ ] Is the RTX 3090 acquired and tested?

### At Phase 3 entry:
- [ ] Are Options Desk prerequisites met? (VRP research complete, options data >12 months)
- [ ] Has the evolved PEAD composite model been backtested?
- [ ] Is FinBERT running on Ollama for earnings NLP?
- [ ] Is the alpha decay monitoring showing stable or improving metrics?

## Research Pending (from deep research prompts)

| Topic | Status | Fire When |
|---|---|---|
| Constrained Decoding (XGrammar/GBNF) | Ready | Now — could eliminate template fallback |
| Confidence Calibration | Ready | This week — affects position sizing |
| Data-Centric AI Pipelines | Ready | This week — prevent next training disaster |
| Qwen3 Fine-Tuning SOTA | Ready | When convenient — may surface quick wins |
| Strategy #2 Implementation (mean reversion) | Ready | After 50-trade gate (fill in actual performance data) |
| Alpha Decay Monitoring | Ready | Phase 2 entry |

## Council Redesign TODOs (from architecture session March 28)

### Phase 1 (this sprint):
- [ ] Rewrite agents.py with 5 new analytical-lens agents
- [ ] Rewrite protocol.py with vote-first, conditional Round 2
- [ ] Update engine.py with structured JSON storage, 1-2 round flow
- [ ] Create value_tracker.py for counterfactual P&L computation
- [ ] Create council_parameter_log + council_calibrations tables
- [ ] Per-agent value tracking from day 1
- [ ] Daily + weekly session types
- [ ] Rate limiters on parameter auto-application
- [ ] Update Council.jsx with new display (vote cards, value attribution, calibration)

### Phase 2 (after 50-trade gate):
- [ ] Add ticker-level agent recommendations (watch/avoid specific stocks)
- [ ] Monthly planning sessions (requires 3 months calibration data)
- [ ] Agent authority weighting based on calibration accuracy (ECE-based)
- [ ] Auto-tighten council bounds if value-added negative 12+ weeks

## Research-Informed Roadmap Additions (10 new docs, March 29)

### P0 — This Week
- [ ] Change timeout_days: pullback→7 (currently 15, research says 80-85% of edge in days 1-5)
- [ ] Add strategy-specific timeout support (not one-size-fits-all)
- [ ] Alpaca bracket order redundancy sprint: position monitoring, extended hours protection, partial fill handling (9 documented failure modes)

### P1 — Phase 1 (training pipeline)
- [ ] GBNF grammar enforcement via llama-cpp-python (solves 62% fallback rate, Ollama cannot do XML)
- [ ] Switch training from BitsAndBytes to Unsloth (now fits RTX 3060 12GB, 60% lower VRAM)
- [ ] Upgrade TRL 0.24 → 0.29.1 (Dr. GRPO built in)
- [ ] Prompt caching on council sessions (agents share 10K+ prompt, 90% off for agents 2-5)
- [ ] Data quality ingestion gates (Pandera + custom validator, ~50 lines, $0 cost)

### P2 — Phase 2
- [ ] Batch API for overnight scoring/generation (50% discount, Haiku 4.5 for scoring)
- [ ] Conviction calibration (Platt scaling at 50-trade gate, isotonic at 200)
- [ ] Multi-LoRA serving via llama-server (not Ollama, 10-50ms swap, all adapters fit on 3060)
- [ ] MFE/MAE analysis framework for empirical holding period optimization (needs 100+ trades)
- [ ] Numerical hallucination verification pipeline (pre-compute all math, NLI verifier)

### Research Still Pending
18 prompts from docs/sprints/deep-research-prompts-expanded-all.md not yet fired:
- Sector rotation timing models
- Options volatility surface for equity traders  
- Fund formation legal requirements (Wyoming LLC → registered fund)
- Alternative data ROI by source
- Breakout signal integration into pullback adapter
- And 13 more training/infrastructure/business topics

## Research Decisions (5 new docs, March 29 batch 2)

### Decided:
- [DECISION] Traffic Light RED=0.1 stays as safety override. Volatility-adaptive sizing (Nagel 2012: wider stops + smaller positions + shorter holds) → Phase 2 enhancement layered on top
- [DECISION] Event Calendar: implement full 0-10 continuous risk scoring with additive compounding, linear position-size reduction with 25% floor, hard cutoffs above score 8 → weekend mega sprint
- [DECISION] Bracket orders: verify GTC (not DAY) immediately — P0 before Monday open

### New Roadmap Items:
- [ ] P0: Verify bracket orders use time_in_force=GTC (if DAY → urgent fix)
- [ ] P1: Event calendar 0-10 risk scoring system (earnings 5-day, FOMC 2-day, OpEx/NFP/CPI sizing mods)
- [ ] P2: Volatility-adaptive position management (wider ATR stops, ATR-scaled sizing, shorter holds at high VIX)
- [ ] P2: FinBERT on CPU for earnings sentiment (3.9 bps daily alpha, yiyanghkust/finbert-tone, ONNX INT8)
- [ ] P2: Walk-forward backtesting protocol (CPCV, multiple testing correction, DSR)
- [ ] P2: Disaster recovery infrastructure ($300-500: UPS, cellular backup, cloud failover)

## Research Decisions (4 new docs, March 29 batch 3)

### New Roadmap Items:
- [ ] P2: Monthly section ablation feature importance monitoring (35 min/month, no infra change)
- [ ] P2: SEC EDGAR XBRL companyfacts.zip parser for PEAD enrichment (free, quarterly maintenance)
- [ ] P2: Risk budgeting transition: 1/N now → ERC at 200 trades → Kelly at 500 trades
- [ ] DECISION NEEDED: Wyoming LLC formation timing for 475(f) MTM election (75-day window)

### Batch 3 Decisions:
- [DECISION] Tax strategy: Table for later. Need more live capital and trade volume before pursuing TTS/475(f). Wyoming LLC formation not urgent at current $100 live scale.
- [DECISION] Risk budgeting: Equal weight confirmed correct for Phase 1. Transition to ERC at 200+ trades/strategy, Kelly at 500+. No action needed now.

## Research Batch 4: Comprehensive Compendium + Fund Formation (March 29)

### Key New Findings:
- SQLite: 10-20 YEARS before bottleneck. No migration needed. Dual DB architecture confirmed correct.
- Render: can drop from $64/mo → $13-14/mo (free static site for React frontend + cheapest Postgres)
- Windows: Ollama VRAM fragmentation requires daily restarts. NSSM for service management.
- Backtesting: MinBTL formula says Sharpe <1.0 not validatable at 95% with only 30 months of data
- Psychology: 15 pre-commitment rules are highest-value intervention in entire research library
- Competition: basic LLM trading pipeline replicable in a weekend. Moat = proprietary data + track record + discipline
- Fund: $50K-$75K startup, 12-24 month audited track record, not self-sustaining until $5-10M AUM

### New Roadmap Items:
- [ ] P1: Ollama daily VRAM restart in watch.py scheduler (prevents fragmentation)
- [ ] P1: Render cost optimization: React → free static site ($0), downgrade Postgres tier
- [ ] P1: 15 pre-commitment rules document (decision journal, parameter freeze periods, pre-registered analysis)
- [ ] P2: Bayesian phase gate framework (sequential testing, informative priors from research)
- [ ] P2: MinBTL computation for each strategy (how long until we can validate)

### Confirmed:
- [CONFIRMED] SQLite architecture correct, no migration planning needed
- [CONFIRMED] Fund formation tabled (Year 3+ decision, $50K-$75K startup)
- [CONFIRMED] Competitive moat = proprietary training data + auditable track record + execution discipline
