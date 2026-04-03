# Arcis Implementation Plan: Sprints 3–7

**Date:** April 2, 2026
**Scope:** 5 sprints covering the core strategic priorities from deep research synthesis
**Dependencies:** Sprint 2 (Bug Bash) must complete first — #182 (reconciliation crash) and #183 (conviction parsing) are blockers

---

## Sprint 3: Alpha Attribution Experiment

> **Priority:** EXISTENTIAL — answers "does the LLM add alpha?"
> **Estimated CC time:** 4–6 hours
> **Dependencies:** Bug Bash (#183 conviction parsing fixed — otherwise all paired trades use default conviction)
> **Files touched:** ~6 new + 3 modified

### Why This Is Sprint 3

Every downstream decision — GRPO investment, training data pipeline, hardware upgrades, fund formation narrative — depends on whether the LLM adds alpha over the deterministic ranker. The research says we need 200+ paired trades for statistical power (6–8 months at current pace). Starting the clock NOW is the single highest-leverage action.

### Architecture

The system already supports dual execution (paper + live on same scan). The alpha attribution experiment adds a THIRD execution path:

```
Scan → Rank Universe → packet_worthy candidates
                           ├── LLM Portfolio (existing): enhance_packet_with_llm → open_shadow_trade
                           └── Ranker-Only Portfolio (NEW): skip LLM → open_ranker_trade
```

Both portfolios see identical candidates at the same time. The ranker-only portfolio takes ALL ranker-qualified candidates (no LLM filter). The LLM portfolio continues as-is (LLM may reject or upgrade candidates via conviction scoring).

### Implementation

**Task 1: Schema — `attribution_trades` table**
New table in schema registry. One row per ranker-qualified candidate per scan:

| Column | Type | Purpose |
|---|---|---|
| `attribution_id` | TEXT PK | UUID |
| `recommendation_id` | TEXT FK | Links to recommendations |
| `ticker` | TEXT | |
| `scan_timestamp` | TEXT | When the ranker qualified this candidate |
| `ranker_score` | REAL | Deterministic ranker score (0–100) |
| `llm_conviction` | INTEGER | LLM conviction (NULL if LLM skipped/failed) |
| `llm_action` | TEXT | `taken`, `rejected`, `parse_failed`, `conviction_none` |
| `ranker_only_entry` | REAL | Entry price at qualification time |
| `ranker_only_stop` | REAL | Mechanical stop (same brackets as LLM portfolio) |
| `ranker_only_target` | REAL | Mechanical target |
| `ranker_only_outcome` | TEXT | `win`, `loss`, `timeout`, `pending` |
| `ranker_only_pnl_pct` | REAL | Simulated P&L |
| `llm_portfolio_outcome` | TEXT | What the LLM portfolio did (same categories) |
| `llm_portfolio_pnl_pct` | REAL | Actual LLM portfolio P&L (NULL if not taken) |
| `pair_type` | TEXT | `both_taken`, `llm_rejected`, `llm_upgraded` |
| `created_at` | TEXT | |

This is NOT a second Alpaca account — it's a simulation ledger that tracks what the ranker alone WOULD have done. Simulated outcomes computed at trade close using the mechanical bracket parameters.

**Task 2: Attribution logger in watch.py scan flow**
After ranking (line ~555 in `_run_scan`), before LLM enhancement:
```python
# Log every packet_worthy candidate to attribution table
for candidate in packet_worthy:
    log_attribution_candidate(candidate, scan_timestamp)
```

After LLM processing, update the attribution row:
```python
# Record what the LLM did
update_attribution_llm_action(candidate, llm_conviction, action)
```

**Task 3: Ranker-only outcome simulator**
Post-close job (runs after reconciliation at 4:30 PM):
- For each `pending` attribution row, fetch current price
- Compute mechanical outcome: did price hit stop, target, or timeout?
- Update `ranker_only_outcome` and `ranker_only_pnl_pct`
- Cross-reference with `shadow_trades` to fill `llm_portfolio_outcome`

**Task 4: Historical backtest variant**
Script: `scripts/alpha_attribution_backtest.py`
- Uses existing `backtester.py` infrastructure
- For each historical date: run ranker → record all qualified candidates → compute mechanical outcomes
- Retroactively tests how many of the 13 closed winners would have been taken by ranker alone
- GPU idle time during market hours handles this

**Task 5: Dashboard — Attribution page**
New dashboard page showing:
- Paired trade count (progress toward 200)
- Win rate: LLM portfolio vs ranker-only
- McNemar's test p-value (updates live as data accumulates)
- Category breakdown: `both_taken`, `llm_rejected`, `llm_upgraded`
- "Is the LLM adding alpha?" verdict with confidence interval

**Task 6: Tests + SYSTEM_STATE.md**
- Unit tests for attribution logger, outcome simulator
- Integration test: mock scan → attribution rows created
- SYSTEM_STATE.md: attribution experiment started, paired trade count

### Key Design Decisions
- **Simulation, not second Alpaca account** — avoids doubling buying power usage and position tracking complexity. The research says matched pairs on the same candidates is statistically superior to independent portfolios anyway.
- **`pair_type` classification** is the most informative column — `llm_rejected` trades (ranker approved, LLM said no) directly measure whether the LLM's filter adds value.
- **Attribution table separate from shadow_trades** — clean separation of concerns. shadow_trades is the real trading ledger; attribution_trades is the experiment ledger.

---

## Sprint 4: Mean Reversion Paper Trading (Strategy #2)

> **Priority:** HIGH — bear market insurance + 2–3x data generation
> **Estimated CC time:** 4–6 hours
> **Dependencies:** Sprint 3 not required. Bug Bash (#182 reconciliation) is a soft dependency.
> **Files touched:** ~5 new + 4 modified

### Why This Is Sprint 4

The deep research unanimously says start NOW: generates 130–390 labeled examples in 6 months of paper trading, provides bear market insurance for flywheel continuity (pullback strategy goes silent when 200-day MA rolls over), and costs zero capital.

### Architecture

Mean reversion runs as a **second strategy within the same watch loop**, not a second instance. The existing `strategy_type` column in `shadow_trades` (already `default="pullback"`) differentiates trades.

```
Watch Loop Scan
  ├── Pullback Scanner (existing): EMA/pullback/uptrend filters → rank → LLM → trade
  └── Mean Reversion Scanner (NEW): RSI(2) < 10 + above 200 EMA → rank → trade (no LLM initially)
```

### Implementation

**Task 1: Mean Reversion Feature Engine**
New file: `src/features/mean_reversion.py`
- RSI(2) computation (Connors RSI variant)
- Distance from 200 EMA (must be above for uptrend filter)
- 3-day cumulative return (streak of down days)
- Bollinger Band position (how far below lower band)
- Volume spike detection (capitulation volume)

Scoring: simple weighted sum of these 5 factors. No LLM involvement initially — pure rules-based to generate labeled data for future model training.

**Task 2: Strategy config in settings.yaml**
```yaml
strategies:
  pullback:
    enabled: true
    # existing pullback config
  mean_reversion:
    enabled: true
    paper_only: true  # NEVER live until Phase 2 gate
    universe: sp100
    rsi_period: 2
    rsi_entry_threshold: 10  # RSI(2) < 10
    rsi_exit_threshold: 70   # RSI(2) > 70
    require_above_200ema: true
    max_positions: 5
    holding_period: 5  # days
    stop_atr_multiple: 2.5
    target_type: rsi_exit  # exit when RSI(2) > 70, not fixed target
```

**Task 3: Integrate into watch loop**
In `_run_scan()` (watch.py), after the pullback scan:
```python
# Mean Reversion scan (parallel strategy)
if self.config.get("strategies", {}).get("mean_reversion", {}).get("enabled"):
    mr_candidates = scan_mean_reversion(features, self.config)
    for candidate in mr_candidates:
        # Skip LLM — pure rules-based for data generation
        open_shadow_trade(rec_id, packet, feat, strategy_type="mean_reversion")
```

**Task 4: Exit logic for mean reversion**
Mean reversion exits differently from pullback:
- Exit when RSI(2) > 70 (target)
- Stop at 2.5× ATR below entry
- Timeout at 5 days (not 8)

The reconciliation loop needs to check strategy_type and apply the correct exit rules.

**Task 5: Dashboard — Strategy filter**
Add strategy_type filter to Shadow Ledger and Performance pages. Users should see pullback-only, MR-only, or combined views.

**Task 6: Tests + docs**
- Unit tests for RSI(2) computation, mean reversion scorer
- Integration test: mock features → MR candidates identified
- Verify MR trades tagged with `strategy_type="mean_reversion"` in shadow_trades

### Key Design Decisions
- **No LLM** for mean reversion initially. This is deliberate — generates pure rules-based labeled data that will later train a mean reversion LoRA adapter.
- **`paper_only: true`** is a hard gate. The executor MUST check this flag and refuse to open live MR trades until the config is changed in Phase 2.
- **Same Alpaca paper account** — MR trades coexist with pullback trades, differentiated by `strategy_type`. This means buying power is shared, which is fine for paper trading.
- **RSI(2) > 70 exit** is not a bracket order — it's a conditional exit checked every scan. This means MR trades need the 15-minute position monitor (Sprint 5) more than pullback trades do.

---

## Sprint 5: Multi-Cadence Scanning

> **Priority:** HIGH — biggest architectural improvement to the scan pipeline
> **Estimated CC time:** 6–8 hours (largest sprint — pure refactor)
> **Dependencies:** Sprint 4 (mean reversion benefits from position-level monitoring). Bug Bash required.
> **Files touched:** ~4 modified heavily (watch.py is 3,031 lines — this is major surgery)

### Why This Is Sprint 5

The scanning intervals research conclusively showed: 30-minute monolithic scan is too fast for 8/11 dimensions and too slow for position monitoring near exits. Splitting into 4 tiers reduces API calls by 60% and GPU load by 40%. The single largest architectural improvement available.

### Architecture

Replace the monolithic `_run_scan()` with 4 independent cadences:

```
┌─────────────────────────────────────────────────────────┐
│  Tier 1: Position Monitor (every 15 min)                │
│  - Open positions only (not full universe)               │
│  - Price refresh for held tickers                        │
│  - Stop/target proximity check                           │
│  - Mean reversion RSI(2) exit check                      │
│  - Alpaca reconciliation                                 │
│  API: ~50 yfinance calls (held tickers only)             │
├─────────────────────────────────────────────────────────┤
│  Tier 2: Price/Technical Scan (every 30 min)            │
│  - Full S&P 100 universe OHLCV                           │
│  - Feature computation (EMAs, RSI, ATR, volume)          │
│  - Ranking + candidate identification                    │
│  - LLM packet generation for qualifiers                  │
│  - Shadow trade execution                                │
│  API: ~100 yfinance calls (batch), ~10 LLM inferences   │
├─────────────────────────────────────────────────────────┤
│  Tier 3: Sentiment/Regime Scan (every 60 min)           │
│  - VIX + term structure refresh                          │
│  - News sentiment (Finnhub)                              │
│  - Options flow (when active)                            │
│  - Sector rotation state                                 │
│  API: ~200 Finnhub calls, ~5 yfinance                    │
├─────────────────────────────────────────────────────────┤
│  Tier 4: Fundamentals (daily pre-market 7:30 AM)        │
│  - FRED macro data                                       │
│  - SEC EDGAR filings check                               │
│  - FMP analyst estimates + earnings cal                   │
│  - Insider transaction updates                            │
│  API: ~200 FMP, ~50 FRED, ~100 EDGAR                     │
└─────────────────────────────────────────────────────────┘
```

### Implementation

**Task 1: Extract scan components from watch.py**
The 3,031-line `watch.py` is the #1 file size violator. This sprint extracts scan logic into focused modules:
- `src/scheduler/position_monitor.py` — Tier 1
- `src/scheduler/universe_scanner.py` — Tier 2
- `src/scheduler/sentiment_scanner.py` — Tier 3
- `src/scheduler/fundamentals_refresh.py` — Tier 4

`watch.py` becomes the orchestrator — schedules each tier on its cadence, handles timing conflicts.

**Task 2: Stale data detection**
New: `src/data_enrichment/staleness.py`

| Dimension | Acceptable | Warning | Critical |
|---|---|---|---|
| Price (yfinance) | <35 min | 35–60 min | >60 min |
| VIX | <65 min | 65–120 min | >120 min |
| News (Finnhub) | <2 hours | 2–4 hours | >4 hours |
| Fundamentals | <26 hours | 26–48 hours | >48 hours |
| Macro (FRED) | <26 hours | same | same |
| Options | <65 min | 65–120 min | >120 min |

Each enricher call checks data freshness. If critical, the dimension is excluded from the feature vector and flagged in logs.

**Task 3: Timing orchestrator in watch.py**
Replace the single `_should_scan()` with:
```python
def _tick(self, now):
    if self._should_monitor_positions(now):   # every 15 min
        self._run_position_monitor()
    if self._should_scan_universe(now):        # every 30 min
        self._run_universe_scan()
    if self._should_refresh_sentiment(now):    # every 60 min
        self._run_sentiment_refresh()
    # Tier 4 runs at pre-market only (7:30 AM) — already handled
```

**Task 4: Data freshness table**
New table in schema registry: `data_freshness`
- Tracks last-fetch timestamp per source per ticker
- Enables the scan loop to skip sources that are still fresh
- Dashboard page shows data freshness status (green/yellow/red per dimension)

**Task 5: Tests**
- Unit tests for each extracted scanner module
- Integration test: verify 4 tiers fire at correct intervals
- Staleness detection tests: mock stale data → correct behavior

### Key Design Decisions
- **Extract, don't rewrite.** The scan logic inside `_run_scan()` works. We're extracting it into modules and adding scheduling, not reimplementing.
- **watch.py stays as orchestrator** — it owns the main loop, timing, and state. The extracted modules are stateless functions.
- **No async rewrite.** The current synchronous pattern works. Async would help with API parallelism but adds complexity disproportionate to the benefit for 100 tickers.
- **Tier 2 (universe scan) runs at 30 min — unchanged from today.** The improvement is that Tiers 1/3/4 no longer piggyback on it.

### Risk: watch.py is 3,031 lines
This is a REFACTOR sprint. The golden rule applies: **refactor by extraction, not rewrite.** Every extracted function must be called from the same place in watch.py with the same parameters. No behavior changes during extraction.

---

## Sprint 6: Outcome-Conditioned Training Pipeline

> **Priority:** MEDIUM-HIGH — 3–5x data yield per closed trade
> **Estimated CC time:** 3–4 hours
> **Dependencies:** Sprint 2 (conviction parsing fix). Sprint 4 (mean reversion generates additional trades for training).
> **Files touched:** ~3 modified + 2 new

### Why This Is Sprint 6

Currently: 1 training example per closed trade. The research says we should generate 3–5 examples per trade using different prompt templates based on outcome type. A $5K→$860 P&L trade that wins teaches different lessons than one that loses, times out, or gets passed on.

### Architecture

```
Closed Trade
  ├── Type: WIN → Winner prompt (emphasize thesis validation, what worked)
  ├── Type: LOSS → Loss prompt (emphasize risk weighting, what was missed)
  ├── Type: TIMEOUT → Timeout prompt (emphasize signal decay, entry timing)
  └── Type: PASS (ranker qualified, not taken) → PASS prompt (justify the skip)

Each type generates:
  1. Pre-entry analysis (what the setup looked like)
  2. Contrastive example (what the OPPOSITE decision would have produced)
  3. Management-during-hold (what happened between entry and exit)
```

### Implementation

**Task 1: Outcome-conditioned prompt templates**
New file: `src/training/outcome_prompts.py`

4 system prompt templates, each tailored to the outcome type:
- `WINNER_SYSTEM_PROMPT` — "Analyze this setup that resulted in a profitable trade. Emphasize which signals correctly predicted the move..."
- `LOSER_SYSTEM_PROMPT` — "Analyze this setup that resulted in a loss. Identify which risk factors were underweighted..."
- `TIMEOUT_SYSTEM_PROMPT` — "Analyze this setup where the trade reached its holding period without hitting stop or target. Assess signal strength and timing..."
- `PASS_SYSTEM_PROMPT` — "Analyze this setup that was identified by the quantitative scanner but should NOT be traded. Justify why this setup should be passed..."

Each prompt maintains the self-blinding architecture — NO outcome information in the prompt. The outcome type determines WHICH prompt template to use, but the template itself doesn't reveal the outcome.

**Task 2: Contrastive example generator**
For each closed trade, generate a second example where the model argues the OPPOSITE position:
- WIN trade → generate a "why I would PASS" example using the same features
- LOSS trade → generate a "why I would BUY" example (the model's original thesis was wrong — what would a correct one look like?)

This creates natural DPO pairs: (correct analysis, incorrect analysis) for the same setup.

**Task 3: Update `collect_training_examples_from_closed_trades()`**
In `src/training/data_collector.py`, modify the collection loop:
```python
for trade in closed_trades_without_examples:
    outcome_type = classify_outcome(trade)  # WIN/LOSS/TIMEOUT
    
    # Primary example (outcome-conditioned prompt)
    prompt = get_outcome_prompt(outcome_type)
    example_1 = generate_training_example(prompt, features)
    
    # Contrastive example (opposite decision)
    contrastive_prompt = get_contrastive_prompt(outcome_type)
    example_2 = generate_training_example(contrastive_prompt, features)
    
    # Management example (for wins/losses only, not timeouts)
    if outcome_type in ('WIN', 'LOSS'):
        mgmt_prompt = get_management_prompt(outcome_type)
        example_3 = generate_training_example(mgmt_prompt, features)
```

**Task 4: Add 8 outcome metadata columns to shadow_trades**
Via schema registry (approved as Strategy Decision #24):
- `regime_at_entry TEXT` — HMM regime label at entry
- `regime_at_exit TEXT` — HMM regime label at exit
- `vix_at_entry REAL` — VIX level at entry
- `vix_at_exit REAL` — VIX level at exit
- `time_to_target_days INTEGER` — days from entry to first target hit (NULL if not hit)
- `drawdown_from_mfe REAL` — unrealized gain given back before exit (MFE - exit price)
- `concurrent_positions INTEGER` — how many other positions were open at entry
- `ranking_at_entry INTEGER` — rank among all candidates at entry time

Populate these columns in `open_shadow_trade()` (entry columns) and `close_shadow_trade()` (exit columns).

**Task 5: Tests + quality metrics**
- Verify 3–5 examples generated per closed trade (up from 1)
- Verify self-blinding maintained — TF-IDF leakage detector still passes
- Verify contrastive examples have opposite stance from primary
- Track example count per outcome type in training report

### Key Design Decisions
- **Self-blinding is sacrosanct.** The outcome type determines which TEMPLATE to use, but the template itself never reveals the outcome. This is the architectural guarantee.
- **Contrastive pairs feed DPO.** Even though we're skipping DPO for now (per Fin-o1), generating contrastive pairs NOW means the data is ready when we revisit DPO at 200+ trades.
- **Claude Haiku 4.5 handles all generation** at ~$0.07/day. At 3–5 examples per trade × ~35 trades/month = 105–175 examples/month vs current ~35. Cost scales linearly but stays under $0.25/day.

---

## Sprint 7: Historical Stress Testing

> **Priority:** MEDIUM — answers the allocator's #1 due diligence question
> **Estimated CC time:** 2–3 hours
> **Dependencies:** Sprint 3 (uses same backtester infrastructure). No hard blockers.
> **Files touched:** 1 new script + 1 modified (backtester)

### Why This Is Sprint 7

The full strategy research identified worst-case drawdown as "napkin math" (estimated 10–12% from back-of-envelope ATR analysis). Any serious allocator conversation requires validated stress test results. This runs on idle GPU overnight — zero opportunity cost.

### Architecture

Extends the existing `src/evaluation/backtester.py` (210 lines) to replay the pullback strategy through 3 historical crisis periods:

```
scripts/stress_test.py
  ├── 2008 Financial Crisis (Sep 2008 – Mar 2009): VIX 80+, -57% S&P 500
  ├── 2020 COVID Crash (Feb 2020 – Apr 2020): VIX 82, -34% in 23 days
  └── 2022 Bear Market (Jan 2022 – Oct 2022): VIX 35, -27% over 10 months
```

### Implementation

**Task 1: Stress test script**
New file: `scripts/stress_test.py`

```python
def run_stress_test(scenario: str, start_date: str, end_date: str) -> dict:
    """
    Replay the pullback strategy through a historical crisis.
    
    For each trading day in the period:
    1. Fetch historical OHLCV for S&P 100
    2. Compute features as-of that date (no lookahead)
    3. Run ranker with current thresholds
    4. Simulate bracket order entries/exits
    5. Track portfolio equity curve, max drawdown, trade count
    
    Returns: {
        scenario, period, total_trades, win_rate, max_drawdown,
        max_drawdown_duration_days, sharpe, profit_factor,
        trades_per_month, equity_curve: [{date, equity}],
        regime_breakdown: {regime: {trades, win_rate, avg_pnl}},
        worst_trade, best_trade, monthly_returns
    }
    """
```

Three predefined scenarios:
```python
SCENARIOS = {
    "2008_financial_crisis": {"start": "2008-09-01", "end": "2009-03-31"},
    "2020_covid_crash":      {"start": "2020-02-01", "end": "2020-04-30"},
    "2022_bear_market":      {"start": "2022-01-01", "end": "2022-10-31"},
}
```

**Task 2: Extend backtester with stress-specific metrics**
Add to `src/evaluation/backtester.py`:
- `max_drawdown_duration_days` — longest peak-to-recovery period
- `calmar_ratio` — annualized return / max drawdown
- `monthly_returns` — for consistency analysis
- `regime_breakdown` — how the strategy performs in each VIX regime
- `trade_gap_days` — longest period with no new trades (tests the "bear market silence" problem)

**Task 3: VIX-regime validation**
The stress test validates the ATR-based stop widening by regime:
- Normal (VIX <20): 2.0× ATR stop → how many stops triggered?
- Elevated (VIX 20–30): 2.5× ATR → how many stops triggered?
- Crisis (VIX >30): 3.0× ATR → how many stops triggered?

Output: "At 3.0× ATR in Crisis regime, X% of positions still hit their stops. Recommendation: adjust to Y.Z× ATR."

**Task 4: Dashboard — Stress Test Results page**
Display results for all 3 scenarios:
- Equity curves overlaid on S&P 500 drawdown
- Max drawdown per scenario
- Trade frequency per scenario (validates bear market silence problem)
- Regime-by-regime performance table

**Task 5: Scheduled overnight execution**
Add stress testing to the GPU compute schedule:
- Runs Sunday nights after weekly retrain
- Re-runs automatically when model version changes (new retrain = new stress test)
- Results stored in `stress_test_results` table (schema registry)
- Dashboard shows "Last stress tested: {date}, model: {version}"

### Key Design Decisions
- **No LLM in stress test** — pure ranker + mechanical brackets. This tests the FLOOR of system performance (what happens without AI). If the floor is acceptable, the LLM can only improve it.
- **Point-in-time data only** — every feature computed as-of the historical date. No survivorship bias (use the S&P 100 membership as-of each date, not today's). Practically, yfinance returns delisted tickers for historical periods.
- **GPU time: 2–4 hours total** for all 3 scenarios. Run once, then re-run only on model changes. This is the single best use of overnight idle GPU.

---

## Dependency Graph

```
Bug Bash (#2) ─────┬──── Alpha Attribution (#3)
                    │         │
                    │         ├──── Stress Testing (#7)
                    │         │     (uses same backtester)
                    │         │
                    ├──── Mean Reversion (#4)
                    │         │
                    │         └──── Multi-Cadence (#5)
                    │               (MR needs position-level RSI checks)
                    │
                    └──── Training Pipeline (#6)
                          (benefits from MR generating more trades)
```

**Parallel execution possible:** Sprints 3, 4, and 6 have no mutual dependencies. If Ryan has multiple CC sessions or wants to queue prompts, these can run in parallel.

**Sprint 7 depends on Sprint 3** only because it extends the same backtester module. Could run in parallel if they modify different functions.

---

## Execution Timeline

| Week | Sprint | Deliverable |
|---|---|---|
| Week 1 | #3 Alpha Attribution | Attribution table logging, historical backtest script, dashboard page |
| Week 1–2 | #4 Mean Reversion | RSI(2) scanner, MR config, paper trading live |
| Week 2–3 | #5 Multi-Cadence | watch.py extraction, 4-tier scheduling, staleness detection |
| Week 3 | #6 Training Pipeline | Outcome-conditioned prompts, contrastive pairs, 8 metadata columns |
| Week 3–4 | #7 Stress Testing | 2008/2020/2022 replay, stress results dashboard |

**After all 5 sprints complete:**
- Alpha attribution experiment running (clock started on 200-trade target)
- Mean reversion generating 2–3x more labeled data
- Scan pipeline optimized (60% fewer API calls)
- Training yield at 3–5x per trade
- Stress test results ready for allocator conversations
- GPU utilization: 4.4% → estimated 35–50% during market hours
