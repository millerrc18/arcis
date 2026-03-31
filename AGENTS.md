<!-- Counts verified 2026-03-30: 169 Python files, 77 test files, 1090 tests, 53 CLI commands, 55 API routes, 40 DB tables (active SQLite schema), 59 research docs. -->

# AGENTS.md — Halcyon Lab Governance Document

## Purpose

Halcyon Lab is an autonomous AI trading system that scans, analyzes, and executes equity trades. It combines systematic technical scoring with LLM-generated institutional-quality trade commentary, multi-source data enrichment, bracket orders via Alpaca, a risk governor with kill switch, and a self-improving training pipeline with quality gates.

**Core Principle:** Training data quality is our #1 competitive advantage. Never sacrifice quality for speed.

**Business Model:** Investing returns, not newsletter. Scale by growing capital under management. Family LP structure planned for external capital.

**Long-term Goal:** Quantitatively be the best AI autonomous trading platform with an unbeatable technological moat.

## Current System State

The system is live in **bootcamp mode** — shadow paper trading on Alpaca with halcyon-v1 (fine-tuned Qwen3 8B). Full data enrichment, bracket orders, risk governor, daily/weekly auditor, validation holdout, A/B model evaluation, learned confidence, walk-forward backtesting, 24/7 compute scheduler (73% GPU target), comprehensive data collection pipeline, Telegram push notifications, and a 13-page web dashboard (including Notes, Council, Health, Live Ledger, and System Validation).

**Active Model:** halcyon-v1 (Qwen3 8B fine-tuned on 790 examples via QLoRA)
**Training Data:** 976 self-blinded examples, scored with process-first rubric
**Universe:** S&P 100 (expanding to ~325 stocks in Phase 2)

## Architecture Overview

```
Universe (S&P 100 → expanding to ~325 stocks)
  → Data Ingestion (yfinance OHLCV)
  → Feature Engine (technical indicators, regime, sector, earnings)
  → Data Enrichment (fundamentals, insiders, news, macro)
  → Ranking & Qualification (score 0-100)
  → Risk Governor (8 checks + kill switch)
  → LLM Packet Writer (Ollama/halcyon-v1 → prose commentary)
  → Shadow Execution (Alpaca bracket orders)
  → Training Loop (self-blinding → scoring → leakage check → curriculum SFT → holdout → A/B eval)
  → Data Collection (options chains, VIX, macro, trends — overnight)
```

## Data Sources (7+ enrichment, 12 collection)

### Enrichment (used in every scan)

1. **Technical Data** — Price, volume, moving averages, RSI, ATR, trend state, relative strength
2. **Market Regime** — SPY trend, volatility, breadth, drawdown, regime classification
3. **Sector Context** — Sector relative strength rank, sector average score
4. **Fundamental Snapshot** — SEC EDGAR: revenue, margins, PE, growth rates
5. **Insider Activity** — Finnhub: buy/sell transactions, sentiment classification
6. **Recent News** — Finnhub Company News: headlines, simple sentiment scoring
7. **Macro Context** — FRED: Fed Funds rate, yield curve, unemployment, CPI, GDP + 9 expanded series

### Data Collection (overnight pipeline — 12 collectors, irreplaceable daily snapshots)

1. **Options Chains** — Full EOD chain snapshots via yfinance (strikes, IV, Greeks, OI)
2. **Options Metrics** — Derived signals: IV rank, put/call ratios, IV skew, unusual activity
3. **VIX Term Structure** — VIX, VIX9D, VIX3M, VIX1Y + contango/backwardation classification
4. **CBOE Ratios** — Equity, index, and total put/call ratios
5. **FRED Macro (34+ series)** — Housing, employment, trade, consumer, financial conditions, plus original core
6. **Google Trends (market-wide)** — 8 sentiment terms: crash, recession, inflation, rates, bubble, correction
7. **Earnings Calendar** — Next earnings date for every ticker, flagging imminent reports
8. **SEC EDGAR Filings** — 10-K, 10-Q, 8-K filings with parsed sections (free, 10 req/sec)
9. **Insider Transactions** — Form 4 buy/sell data via Finnhub (nightly)
10. **Short Interest** — FINRA short interest snapshots via Finnhub (biweekly)
11. **Fed Communications** — FOMC statements, minutes, Beige Book, speeches (scraped from federalreserve.gov)
12. **Analyst Estimates** — Consensus recommendations + price targets via Finnhub (batched 20/night)

## Execution

- **Bracket Orders**: Entry + stop-loss + take-profit via Alpaca paper trading
- **Risk Governor**: 8 checks (emergency halt, daily loss, position size, max positions, sector concentration, correlation, volatility halt, duplicate check)
- **Kill Switch**: `halt-trading` command or dashboard button halts all new positions immediately

## Training Pipeline

1. **Self-Blinding Generation**: Claude generates commentary WITHOUT seeing outcomes (2-stage pipeline)
2. **Process-First Quality Scoring**: LLM-as-judge scores 6 dimensions, blind to trade outcome
3. **Outcome Leakage Detection**: Balanced accuracy classifier verifies pipeline integrity
4. **Curriculum Classification**: Easy/medium/hard difficulty → 3-stage curriculum
5. **SFT Training**: Three-stage curriculum with decreasing learning rates (PEFT + TRL 0.24)
6. **Preference Pair Generation / RL Prep**: Preference exports retained, but the planned post-SFT refinement path is Dr. GRPO rather than DPO
7. **Holdout Validation**: 15% chronological holdout with 5-day temporal gap
8. **A/B Shadow Evaluation**: New model runs alongside current model
9. **Auto-Rollback**: Performance regression triggers automatic rollback

## 24/7 Compute Schedule

**Target: 73% GPU utilization** (inference ≤30%, training ≤45%, slack ≥25%)

| Time (ET)       | Task                                                         | GPU Mode         |
| --------------- | ------------------------------------------------------------ | ---------------- |
| 5:15 AM         | Morning VRAM handoff (training → Ollama)                     | Transition       |
| 5:30 AM         | Post-close capture (MFE/MAE update, regime logging)          | Inference        |
| 6:00 AM         | Pre-market refresh + rolling feature computation             | CPU + Inference  |
| 7:00 AM         | Self-blinded training data generation (historical)           | Inference        |
| 8:00 AM         | Morning watchlist                                            | Inference        |
| 8:02 AM         | Overnight news scoring + sentiment analysis                  | Inference        |
| 9:00 AM         | Pre-market candidate analysis                                | Inference        |
| 9:25 AM         | Guard band — verify model warm                               | Idle             |
| 9:30 AM–4:00 PM | Market scans (every 30 min) + between-scan scoring           | Inference        |
| 4:00 PM         | EOD recap + daily P&L                                        | CPU + Inference  |
| 4:15 PM         | Training data scoring (LLM-as-judge, ~50 examples)           | Inference        |
| 5:30 PM         | Post-close capture                                           | CPU              |
| 6:00 PM         | Training data collection from closed trades                  | CPU              |
| 6:45 PM         | Preference pair generation / RL prep                         | Inference        |
| 6:50 PM         | Evening VRAM handoff (Ollama → training subprocess)          | Transition       |
| 7:00 PM         | Walk-forward backtesting                                     | Training         |
| 9:30 PM         | Data collection (12 collectors: options, VIX, FRED 34+, trends, CBOE, earnings, EDGAR, insider, short interest, Fed, analyst) | CPU (concurrent) |
| 10:00 PM        | News ingestion (full universe)                               | CPU (concurrent) |
| 11:00 PM        | Enrichment pre-cache                                         | CPU (concurrent) |
| 11:05 PM        | Auxiliary model training (regime classifier)                 | Training         |
| 1:00 AM         | Feature importance computation                               | Training         |
| 2:30 AM         | Leakage detector with model probing                          | Training         |
| 4:30 AM         | DB maintenance, health checks, backups                       | CPU              |

## Dashboard Pages (13)

- **Dashboard** — KPIs, cumulative P&L, open trades, action buttons, live activity feed
- **Packets** — Trade recommendations with expandable analysis
- **Shadow Ledger** — Open/closed trades with account summary
- **Live Ledger** — Live-trading account summary and history
- **Training** — Pipeline status, version history, action buttons
- **Council** — Vote-first sessions, agent votes, and parameter adjustments
- **Health** — HSHS composite score, radar chart, and live phase weights
- **Validation** — System validation checks and reliability signals
- **CTO Report** — Performance analytics, fund metrics, metric trends
- **Settings** — Configuration, API costs, data collection stats, system health
- **Roadmap** — 6-phase plan with confirmed decision tracking
- **Docs** — 59 research documents plus core governance docs
- **Notes** — Operator notes with pinning, tags, and autosave editing

## CLI Commands (53)

See docs/cli-reference.md for full documentation with options and descriptions.

### Core Pipeline (8)

`init-db`, `demo-packet`, `send-test-email`, `send-test-telegram`, `ingest`, `scan`, `morning-watchlist`, `eod-recap`

### Shadow Trading (4)

`shadow-status`, `shadow-history`, `shadow-close`, `shadow-account`

### Live Trading (4)

`live-status`, `live-history`, `live-close`, `reconcile-live`

### Review & Analysis (6)

`review`, `mark-executed`, `review-scorecard`, `review-bootcamp`, `postmortems`, `postmortem`

### Training — Data (5)

`training-status`, `training-history`, `training-report`, `bootstrap-training`, `backfill-training`

### Training — Quality (5)

`classify-training-data`, `score-training-data`, `validate-training-data`, `generate-contrastive`, `generate-preferences`

### Training — Execution (2)

`train [--force|--rollback|--export]`, `train-pipeline [--force]`

### Evaluation (10)

`cto-report`, `evaluate-holdout`, `model-evaluation-status`, `promote-model`, `feature-importance`, `backtest`, `compare-models`, `check-leakage`, `performance-report`, `evaluate-gate`

### Operations (8)

`collect-data`, `fetch-earnings`, `halt-trading`, `resume-trading`, `preflight`, `council`, `watch [--overnight]`, `dashboard`

## Scope

### In Scope

- S&P 100 universe (expanding to ~325 stocks), long-only equity swing trades (2-15 day holds)
- Systematic scoring + LLM commentary + bracket execution
- Self-improving training pipeline with quality gates
- Risk management with automated safety rails
- Passive options/volatility data collection

### Out of Scope (Current Phase)

- Options trading (passive data collection only — Options Volatility Desk in Phase 3-4)
- Short selling
- High-frequency / intraday trading (Intraday Desk is Phase 6+)
- Live trading with real money (Phase 2)

### Future Desks (Gated by Performance)

Each desk launches only after the previous desk is profitable. See docs/roadmap.md for full specifications.

- **Equity Research Desk** (Phase 2) — Same model, lower thresholds (score ≥ 30), separate paper account, training data volume
- **Options Volatility Desk** (Phase 3-4) — Separate LoRA adapter, credit spreads + iron condors, 15-check non-linear risk governor
- **Equity Momentum Desk** (Phase 5) — Separate LoRA adapter, Russell 1000, breakout/trend-following (LOW correlation with Swing)
- **Intraday Desk** (Phase 6+) — Separate model entirely, 1-min bars, VWAP reversion, requires dedicated GPU + real-time data
- **Future:** Event-Driven Desk, Macro/Rates Desk, Crypto Desk

## Governance Hierarchy

1. **AGENTS.md** — This document. Defines purpose, scope, and constraints
2. **Charter** — Operational rules and risk limits
3. **Blueprint** — Technical architecture (see docs/architecture.md)
4. **Code** — Implementation

## Technology Stack

- **Python 3.12+** — Core runtime
- **FastAPI + Uvicorn** — Dashboard API server
- **React 18 + Vite + Tailwind CSS** — Frontend dashboard
- **SQLite** — Journal, training data, model versions, data collection
- **yfinance** — Market data ingestion + options chains
- **Ollama + halcyon-v1 (Qwen3-8B fine-tuned)** — Local LLM inference
- **PEFT + TRL 0.24 + BitsAndBytes** — Fine-tuning on RTX 3060 12GB
- **Anthropic Claude API (Haiku 4.5)** — Training data generation, quality scoring
- **Alpaca Markets API** — Paper trading execution
- **Finnhub API** — Insider activity, company news
- **FRED API** — Macroeconomic indicators (34+ series)
- **SEC EDGAR** — Fundamental data
- **Telegram Bot API** — Real-time push notifications

## Research Library (59 documents)

See the dashboard Docs page for the complete research library covering:

- Training methodology (formats, rubric, self-blinding, degradation prevention, gaps/innovation, GRPO)
- Strategy (alternative data, Halcyon Framework, optimal universe size, options trading)
- Business (fund path/regulatory/tax, scaling plan)
- Model selection (Qwen3 8B guide)

## Roadmap

See the dashboard Roadmap page or docs/roadmap.md for the 6-phase development plan:

1. **Bootcamp** (current) — Equity Swing Desk, paper $100K, prove edge
2. **Micro Live** — Swing Desk live ($500-$1K) + Research Desk (paper, training data volume)
3. **Growth** — Options Volatility Desk (paper), sector/regime LoRA adapters
4. **Full Autonomous** — Options Desk live ($2-5K), investor-ready track record
5. **Scale Capital** — Equity Momentum Desk, Russell 1000, family LP
6. **Future** — Intraday Desk, event-driven, macro, crypto (scoped, not scheduled)
