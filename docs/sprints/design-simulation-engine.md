# Design: Full-Regime Simulation Engine

> **Purpose:** Test the Arcis strategy across EVERY market condition — not just crashes.
> **Question answered:** "In which market environments does this strategy make money, break even, or bleed?"
> **Priority:** HIGH — this is the most important validation tool after the 50-trade gate.

---

## Why This Matters

The current stress test only covers 3 crisis scenarios. That tells you "we survive crashes" but doesn't tell you:
- Do we make money in grinding bull markets? (Most of the time)
- Do we bleed during low-volatility sideways chop? (Where pullbacks don't exist)
- Do we catch V-recoveries or get whipsawed by them?
- Does our regime detection actually help or hurt during transitions?
- Which VIX regime produces the best win rate?
- Does the strategy work in rate hiking cycles vs rate cutting cycles?

A fund allocator will ask: "Show me performance broken down by market regime." This engine produces that answer.

---

## Default Scenario Suite (13 regimes: 10 pure + 3 transitions)

Each scenario is a specific historical period chosen to represent a pure example of that market condition:

| # | Regime | Period | SPY Behavior | VIX Range | Why This Tests Us |
|---|---|---|---|---|---|
| 1 | **Strong bull** | Jan 2013 – Dec 2013 | +30%, steady grind up | 12-18 | Pullbacks are shallow and brief — do we catch them? |
| 2 | **Euphoric bull** | Jan 2021 – Nov 2021 | +25%, meme stocks, FOMO | 15-25 | Everything goes up — do we add value over buy-and-hold? |
| 3 | **Low volatility** | Jan 2017 – Oct 2017 | +15%, VIX historically low | 9-12 | Pullbacks barely exist — ATR is tiny, stops are tight |
| 4 | **High volatility** | Oct 2018 – Mar 2019 | -20% then +20% | 18-36 | Whipsaw — stops get hit, then stocks recover without us |
| 5 | **Sideways chop** | Jan 2015 – Dec 2015 | +1%, range-bound | 12-22 | No trend = no pullback setups. Do we correctly sit out? |
| 6 | **Sector rotation** | Jan 2016 – Dec 2016 | +10%, tech→value rotation | 12-20 | Our universe (S&P 100) rotates sectors — do we adapt? |
| 7 | **Rate hiking** | Jan 2022 – Dec 2022 | -19%, Fed aggressive | 20-35 | Growth stocks crushed — do we avoid them via regime? |
| 8 | **Rate cutting** | Jul 2019 – Jan 2020 | +15%, 3 cuts | 12-20 | Easy conditions — do we capture the drift? |
| 9 | **V-recovery** | Mar 2020 – Jun 2020 | -34% then +40% | 20-80 | The fastest crash and recovery ever. Do we buy the dip? |
| 10 | **Grinding bear** | Jan 2022 – Oct 2022 | -25%, slow bleed | 20-35 | No capitulation event — just steady decline. Do we stop trading? |
| 11 | **Bull → Bear transition** | Oct 2007 – Mar 2009 | +5% then -55% | 12-80 | Where stops fail and drawdowns compound. Tests persistence filter speed. |
| 12 | **Bear → Bull transition** | Mar 2009 – Mar 2010 | -10% then +65% | 20-80 | Recovery is violent. Do we re-enter fast enough? |
| 13 | **Low Vol → High Vol** | Jan 2018 – Jun 2018 | Flat then -10% | 9-35 | Volmageddon. VIX 9→35 in 2 weeks. Traffic light must switch instantly. |

---

## Architecture

```
scripts/simulation_engine.py
├── REGIME_SCENARIOS = { ... }      # 10 default scenarios (configurable)
├── run_simulation(scenarios, config) -> SimulationResult
│   ├── For each scenario:
│   │   ├── Fetch OHLCV data (cached locally)
│   │   ├── Run full Arcis pipeline:
│   │   │   ├── compute_all_features()
│   │   │   ├── compute_traffic_light()
│   │   │   ├── rank_universe()
│   │   │   ├── classify_setup()
│   │   │   └── simulate_mechanical_outcome()
│   │   ├── Track: equity curve, trades, drawdown, regime stats
│   │   └── Compute per-regime metrics
│   └── Cross-scenario comparison
├── SimulationResult
│   ├── per_scenario: {regime: {trades, WR, PF, DD, Sharpe, Calmar}}
│   ├── aggregate: {total_trades, total_WR, regime_heatmap}
│   ├── regime_heatmap: which regimes make money vs bleed
│   └── equity_curves: per-scenario equity curves for charting
└── store_simulation_results(result, db_path)
```

---

## Key Design Decisions

### 1. Uses the REAL pipeline (not simplified)
Unlike the current stress test which uses a simplified mean-reversion heuristic, this engine runs the actual `compute_all_features()` → `rank_universe()` → `classify_setup()` pipeline. This means:
- Traffic light actually fires and adjusts sizing
- Setup classifier routes to pullback vs mean reversion vs breakout
- Regime adjustment in the ranker shifts scores
- Event risk score adjusts for FOMC/earnings (if calendar data available for historical period)

### 2. Data caching (critical for speed)
```python
CACHE_DIR = Path("data/simulation_cache/")

def fetch_cached_ohlcv(ticker, start, end):
    """Fetch from cache or yfinance. Cache as parquet for speed."""
    cache_key = f"{ticker}_{start}_{end}.parquet"
    cache_path = CACHE_DIR / cache_key
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    data = yf.download(ticker, start=start, end=end, ...)
    data.to_parquet(cache_path)
    return data
```
First run downloads everything (~20 min for 10 scenarios). Subsequent runs: <2 minutes.

### 3. Configurable via YAML
```yaml
# config/simulation_scenarios.yaml
scenarios:
  strong_bull:
    start: "2013-01-01"
    end: "2013-12-31"
    label: "Strong Bull (2013)"
    expected_regime: "bull"
    
  custom_scenario:
    start: "2024-07-01"
    end: "2024-09-30"
    label: "2024 Yen Unwind"
    expected_regime: "crisis"

settings:
  position_size: 2000          # $2K per position (2% of $100K)
  scan_interval_days: 5        # Scan every 5 trading days
  max_positions_per_scan: 3    # Top 3 candidates per scan
  universe_size: 30            # Top 30 tickers per scan (speed vs coverage)
  cache_enabled: true
```

### 4. Regime heatmap output
The most valuable output — a single table showing performance by regime:

```
Regime           | Trades | WR    | PF   | DD    | Sharpe | Calmar | Verdict
─────────────────┼────────┼───────┼──────┼───────┼────────┼────────┼─────────
Strong bull      |   45   | 58%   | 1.8  | 4.2%  |  1.2   |  2.1   | ✅ EDGE
Euphoric bull    |   52   | 55%   | 1.5  | 5.1%  |  0.9   |  1.4   | ✅ EDGE
Low volatility   |   12   | 42%   | 0.9  | 3.8%  |  0.1   |  0.2   | ⚠️ NEUTRAL
High volatility  |   38   | 44%   | 1.1  | 8.5%  |  0.3   |  0.5   | ⚠️ MARGINAL
Sideways chop    |    8   | 38%   | 0.7  | 6.2%  | -0.2   | -0.3   | ❌ BLEEDS
Sector rotation  |   28   | 50%   | 1.3  | 5.5%  |  0.6   |  0.9   | ✅ EDGE
Rate hiking      |   22   | 41%   | 0.8  | 12.1% | -0.1   | -0.1   | ❌ BLEEDS
Rate cutting     |   35   | 56%   | 1.6  | 3.9%  |  1.1   |  1.9   | ✅ EDGE
V-recovery       |   18   | 61%   | 2.1  | 15.2% |  0.8   |  0.4   | ⚠️ HIGH DD
Grinding bear    |   15   | 33%   | 0.5  | 14.8% | -0.5   | -0.4   | ❌ BLEEDS
```

This immediately tells you: "The strategy makes money in trending markets (bull, rate cutting, rotation) and bleeds in choppy/bearish markets. The traffic light should catch the bear markets — verify it's working."

### 5. Dashboard integration
New dashboard page: **Simulation Engine**
- Regime heatmap table (color-coded by verdict)
- Overlay equity curves (all 10 scenarios on one chart)
- Per-regime breakdown panels (expandable)
- "Run Simulation" button via command queue
- Compare current model version vs previous (did the retrain help or hurt in each regime?)

### 6. Model comparison mode
Run the same scenarios with:
- **Mechanical only** (ranker + brackets, no LLM) — baseline
- **Current model** (ranker + LLM + brackets) — production
- **Previous model** (if available) — regression check

This directly answers: "Does the LLM add value, and in which regimes?"

---

## CLI

```bash
# Run all 13 default scenarios
python scripts/simulation_engine.py

# Run single regime
python scripts/simulation_engine.py --regime strong_bull

# Run with custom config
python scripts/simulation_engine.py --config config/simulation_custom.yaml

# Compare two model versions
python scripts/simulation_engine.py --compare mechanical vs halcyon-v1.0.0

# Run with Monte Carlo (1000 reshuffles per scenario)
python scripts/simulation_engine.py --monte-carlo 1000

# Run transition scenarios only
python scripts/simulation_engine.py --transitions-only

# Validate traffic light detection per scenario
python scripts/simulation_engine.py --validate-traffic-light

# Post-retrain regression check
python scripts/simulation_engine.py --regression-check old_model new_model

# Audit look-ahead bias (log every data access with timestamp)
python scripts/simulation_engine.py --audit-lookahead

# Export allocator PDF report
python scripts/simulation_engine.py --export-pdf report.pdf

# Dry run (show config, don't execute)
python scripts/simulation_engine.py --dry-run
```

---

## Database Schema

```sql
CREATE TABLE simulation_results (
    result_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,              -- Groups all scenarios from one run
    scenario TEXT NOT NULL,
    regime_label TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    total_trades INTEGER,
    wins INTEGER,
    losses INTEGER,
    timeouts INTEGER,
    win_rate REAL,
    profit_factor REAL,
    total_pnl_pct REAL,
    max_drawdown_pct REAL,
    sharpe_ratio REAL,
    calmar_ratio REAL,
    monthly_returns_json TEXT,
    equity_curve_json TEXT,
    regime_breakdown_json TEXT,
    model_version TEXT,
    config_json TEXT,                  -- Full config snapshot for reproducibility
    verdict TEXT,                      -- "edge", "neutral", "marginal", "bleeds"
    survivorship_bias INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);
```

---

## Verdict Logic

```python
def compute_verdict(metrics: dict) -> str:
    """Classify strategy performance in a given regime."""
    sharpe = metrics.get("sharpe_ratio", 0)
    pf = metrics.get("profit_factor", 0)
    wr = metrics.get("win_rate", 0)
    dd = metrics.get("max_drawdown_pct", 100)
    
    if sharpe >= 0.5 and pf >= 1.3 and wr >= 0.45:
        return "edge"           # Strategy has genuine edge in this regime
    elif sharpe >= 0 and pf >= 1.0:
        return "neutral"        # Break-even, not losing money
    elif sharpe >= -0.3 and pf >= 0.8:
        return "marginal"       # Slight bleed, might improve with tuning
    else:
        return "bleeds"         # Strategy loses money in this regime — should sit out
```

When a regime gets "bleeds" verdict, the action item is: verify the traffic light catches this regime and reduces sizing to 0.1× (or halts entirely).

---

## Implementation Priority

1. **Core engine** — `run_simulation()` with 10 scenarios + caching + heatmap output
2. **Schema + storage** — `simulation_results` table via registry
3. **CLI** — `python scripts/simulation_engine.py` with --regime, --config, --dry-run
4. **Dashboard page** — Heatmap + equity curves + run button
5. **Model comparison** — mechanical vs LLM side-by-side
6. **Custom scenarios** — YAML config for user-defined periods

---

## What This Tells Us That Nothing Else Does

- **Where to NOT trade:** If "sideways chop" consistently bleeds, add a chop detector that reduces sizing
- **Model value by regime:** If LLM adds alpha in bulls but hurts in bears, condition LLM usage on regime
- **Traffic light validation:** If we bleed in regimes where the traffic light should protect us, the traffic light thresholds are wrong
- **Regime transition behavior:** Run scenarios that span regime changes (bull→bear) to test transition handling
- **Retraining validation:** After every retrain, run the full suite. If any regime flips from "edge" to "bleeds," the retrain degraded that regime's performance

---

## Ralph Loop Iteration 1: Transaction Costs, Benchmarks, Monte Carlo

### Gap 1: No transaction cost model

The original spec simulates trades at exact close prices with zero friction. This overstates
performance. For S&P 100 large-caps at our position sizes ($2K, ~7-20 shares), costs are small
but non-zero and compound over hundreds of trades.

**Implementation — tiered flat model:**
```python
TRANSACTION_COSTS = {
    "commission_per_side_bps": 0,       # Alpaca = $0; IB ≈ 0.5 bps
    "slippage_per_side_bps": 3,         # S&P 100 market orders: ~1-5 bps
    "spread_per_side_bps": 1.5,         # Large-cap half-spread: ~1-3 bps
}
# Total round-trip: ~9 bps (conservative for S&P 100)
# Applied to every simulated entry AND exit

def apply_transaction_costs(entry_price, exit_price, costs=TRANSACTION_COSTS):
    total_bps = sum(costs.values())
    entry_adj = entry_price * (1 + total_bps / 10000)   # Pay more on entry
    exit_adj = exit_price * (1 - total_bps / 10000)      # Receive less on exit
    return entry_adj, exit_adj
```

At 9 bps round-trip and 200 trades/year, transaction costs consume ~1.8% of capital annually.
Not strategy-killing, but it turns marginal regimes from "neutral" to "bleeds."

### Gap 2: No benchmark comparison

Without a benchmark, "edge" is undefined. Add SPY buy-and-hold for every scenario period:

```python
def compute_benchmark(spy_data, start, end):
    """SPY buy-and-hold return for the scenario period."""
    start_price = spy_data.loc[start]["Close"]
    end_price = spy_data.loc[end]["Close"]
    return (end_price - start_price) / start_price * 100
```

The heatmap output adds a `benchmark_pnl_pct` column. A regime where our strategy returns +5%
but SPY returned +15% is NOT an edge — it's underperformance. The verdict logic must account
for this:

```python
# Updated verdict considers benchmark-relative performance
excess_return = total_pnl_pct - benchmark_pnl_pct
if excess_return > 0 and sharpe >= 0.5:
    return "edge"           # Beats benchmark with acceptable risk
elif total_pnl_pct >= 0:
    return "neutral"        # Positive absolute, but doesn't beat benchmark
```

### Gap 3: No Monte Carlo confidence intervals

A single equity curve per scenario is one path through history. Research consensus (QuantProof,
StrategyQuant, BuildAlpha): run 1,000-5,000 reshuffled trade sequences per scenario to produce
confidence intervals.

```python
def monte_carlo_resample(trades: list[dict], n_simulations: int = 1000,
                          starting_equity: float = 100000) -> dict:
    """Bootstrap resample trades to produce confidence intervals."""
    import numpy as np
    final_equities = []
    max_drawdowns = []

    for _ in range(n_simulations):
        # Resample with replacement — same trades, different order
        resampled = np.random.choice(trades, size=len(trades), replace=True)
        equity = starting_equity
        peak = equity
        max_dd = 0

        for trade in resampled:
            equity += trade["pnl_dollars"]
            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100
            max_dd = max(max_dd, dd)

        final_equities.append(equity)
        max_drawdowns.append(max_dd)

    return {
        "median_equity": np.median(final_equities),
        "p5_equity": np.percentile(final_equities, 5),
        "p95_equity": np.percentile(final_equities, 95),
        "median_dd": np.median(max_drawdowns),
        "p95_dd": np.percentile(max_drawdowns, 95),   # 95% worst-case DD
        "p99_dd": np.percentile(max_drawdowns, 99),
        "probability_of_ruin": sum(1 for e in final_equities if e <= 0) / n_simulations,
    }
```

The dashboard shows confidence bands (5th-95th percentile) around each equity curve, not
just the single historical path. The 95th percentile max drawdown is what you size capital to —
not the backtest drawdown.

### Gap 4: Statistical significance thresholds

A regime with 8 trades is not statistically meaningful. Add minimum trade thresholds:

```python
MIN_TRADES_FOR_VERDICT = 20      # Below this: verdict = "insufficient_data"
MIN_TRADES_FOR_CONFIDENCE = 50   # Below this: Monte Carlo CI are wide, flag as low confidence
```

The heatmap marks regimes with `n < 20` as "⚪ INSUFFICIENT" instead of assigning a
verdict. This prevents false confidence from small samples.

---

## Ralph Loop Iteration 2: Walk-Forward, Transitions, Realistic Sizing

### Gap 5: No walk-forward validation

The original spec tests fixed periods — the strategy sees data from 2013 and we measure
performance on 2013. This is in-sample, not out-of-sample. Walk-forward validation is the
industry standard (Bailey 2014, CSCV).

**Walk-forward mode:**
```python
def walk_forward_validation(full_period_start, full_period_end,
                             train_months=12, test_months=3):
    """Rolling walk-forward: train on N months, test on next M months, roll."""
    results = []
    current = full_period_start
    while current + train_months + test_months <= full_period_end:
        train_end = current + train_months
        test_end = train_end + test_months

        # Train: compute optimal parameters from this period
        # (e.g., ranker weights, bracket multipliers)
        train_params = optimize_on_period(current, train_end)

        # Test: apply those parameters to the next period (out-of-sample)
        test_result = run_scenario_with_params(train_end, test_end, train_params)
        results.append(test_result)

        current += test_months  # Roll forward

    return aggregate_walk_forward_results(results)
```

Walk-forward answers: "Do optimized parameters persist out-of-sample?" If in-sample Sharpe is
1.5 but out-of-sample is 0.3, the strategy is overfit.

**Phase this in:** Walk-forward is a Phase 2 addition. Phase 1 uses fixed periods but clearly
labels results as "in-sample" in the heatmap. Walk-forward produces "out-of-sample" labeled results.

### Gap 6: No regime transition scenarios

Pure regimes are useful but transitions are where strategies fail. Add 3 transition scenarios:

| # | Transition | Period | Why It Breaks Strategies |
|---|---|---|---|
| 11 | **Bull → Bear** | Oct 2007 – Mar 2009 | The transition FROM bull TO bear is where stops fail and drawdowns compound |
| 12 | **Bear → Bull** | Mar 2009 – Mar 2010 | Recovery is violent — do we re-enter fast enough? |
| 13 | **Low Vol → High Vol** | Jan 2018 – Jun 2018 | VIX from 9 to 35 in 2 weeks (Volmageddon). Traffic light must switch fast. |

These test the PERSISTENCE FILTER — does 5 consecutive readings switch fast enough during
sudden regime changes? If not, the traffic light is too slow.

### Gap 7: Position sizing must mirror live system

The original spec uses fixed $2K per position. The live system uses traffic light multipliers
(1.0×/0.5×/0.1×), event risk adjustments, and risk governor limits. The simulation must match:

```python
def compute_position_size(base_size, traffic_light, event_risk_score):
    """Mirror live system sizing: base × traffic_light × event_risk."""
    tl_mult = {"GREEN": 1.0, "YELLOW": 0.5, "RED": 0.1}[traffic_light]
    er_mult = max(0.3, 1.0 - event_risk_score * 0.1)
    return base_size * tl_mult * er_mult
```

This matters because the traffic light SHOULD reduce sizing in bear markets. If the simulation
uses fixed sizing, it can't measure whether the traffic light is actually helping.

### Gap 8: Look-ahead bias prevention

The simulation must never use future data. Specific safeguards:
- OHLCV data for feature computation: only bars BEFORE the scan day
- VIX regime classification: only current-day VIX, not forward
- ATR computation: only trailing 14-day, not centered
- Earnings calendar: only known dates, not future announcements
- Feature enrichment: skip any data source that wouldn't have been available historically

Add an `--audit-lookahead` flag that logs every data access with timestamp to verify no future
data leaks into feature computation.

---

## Ralph Loop Iteration 3: Deflated Sharpe, Reproducibility, Alerting

### Gap 9: Deflated Sharpe Ratio

Bailey & López de Prado (2014) proved that testing multiple strategy configurations inflates
Sharpe ratios. After testing 10 regimes × 3 model versions = 30 configurations, the probability
of finding a Sharpe > 1.0 by chance is non-trivial.

```python
def deflated_sharpe_ratio(sharpe_observed, n_trials, n_trades,
                           skew=0, kurtosis=3):
    """Bailey & López de Prado (2014): correct Sharpe for multiple testing."""
    import scipy.stats as stats
    import numpy as np

    e_max_sharpe = stats.norm.ppf(1 - 1/n_trials) * np.sqrt(1/n_trades)
    # Adjust for non-normal returns (skew, kurtosis)
    adj = 1 - skew * sharpe_observed + (kurtosis - 3) / 4 * sharpe_observed**2

    z = (sharpe_observed - e_max_sharpe) / np.sqrt(adj / n_trades)
    return stats.norm.cdf(z)  # p-value: probability this Sharpe is genuine
```

Any regime showing Sharpe > 1.0 must pass the deflated test (p < 0.05) to get "edge" verdict.
This prevents declaring victory from lucky sequences.

### Gap 10: Reproducibility requirements

Every simulation run must be fully reproducible:

```python
REPRODUCIBILITY = {
    "random_seed": 42,                    # Fixed seed for Monte Carlo
    "config_snapshot": "full YAML dump",  # Exact config used
    "code_version": "git commit hash",    # Exact codebase version
    "data_hash": "SHA256 of cached data", # Verify data hasn't changed
    "python_version": "3.11.x",           # Environment
}
```

Store in `config_json` column. Any user can reproduce exact results by checking out the
same commit with the same data cache.

### Gap 11: Automated traffic light validation

For each scenario, verify the traffic light classification MATCHES the expected regime:

```python
def validate_traffic_light(scenario, expected_regime, actual_tl_states):
    """Check: did our traffic light correctly identify this regime?"""
    expected_tl = {
        "strong_bull": "GREEN",
        "euphoric_bull": "GREEN",
        "low_volatility": "GREEN",
        "high_volatility": "YELLOW",
        "sideways_chop": "GREEN",     # Chop looks GREEN — this is the failure mode
        "rate_hiking": "YELLOW",
        "v_recovery": "RED → GREEN",  # Should transition
        "grinding_bear": "YELLOW → RED",
    }
    actual_majority = max(set(actual_tl_states), key=actual_tl_states.count)
    match = actual_majority == expected_tl.get(scenario, "GREEN")
    return {"scenario": scenario, "expected": expected_tl[scenario],
            "actual": actual_majority, "correct": match}
```

If the traffic light says GREEN during a grinding bear, that's a critical finding —
the regime detection is broken for that condition.

### Gap 12: Post-retrain regression alerting

After every model retrain, automatically run the full simulation suite:

```python
def retrain_regression_check(new_model, old_model):
    """Run full simulation with both models. Flag any regime that degraded."""
    new_results = run_simulation(model=new_model)
    old_results = run_simulation(model=old_model)

    regressions = []
    for regime in SCENARIOS:
        old_verdict = old_results[regime]["verdict"]
        new_verdict = new_results[regime]["verdict"]
        if verdict_rank(new_verdict) < verdict_rank(old_verdict):
            regressions.append({
                "regime": regime,
                "old_verdict": old_verdict,
                "new_verdict": new_verdict,
                "action": "BLOCK DEPLOYMENT — regime degraded"
            })
    return regressions
```

If ANY regime flips from "edge" to "bleeds" after retraining, BLOCK the model deployment
and alert. The retrain may have improved average performance while destroying edge in a
specific market condition.

### Gap 13: Allocator-ready export

Generate a PDF report from simulation results:
- Executive summary: "Strategy performs well in 6/10 regimes, neutral in 2, bleeds in 2"
- Regime heatmap (color-coded table)
- Equity curves with Monte Carlo confidence bands
- Traffic light validation results
- Transaction cost impact analysis
- Benchmark comparison (vs SPY buy-and-hold)
- Deflated Sharpe p-values per regime

This is the document you hand to an allocator during due diligence.

---

## Updated Implementation Priority

1. **Core engine** — 10 scenarios + caching + transaction costs + benchmark (Iteration 1)
2. **Monte Carlo** — 1,000 reshuffles per scenario + confidence intervals (Iteration 1)
3. **Realistic sizing** — Traffic light multiplier + event risk in simulation (Iteration 2)
4. **Transition scenarios** — Bull→Bear, Bear→Bull, LowVol→HighVol (Iteration 2)
5. **Schema + storage** — Updated schema with MC fields + reproducibility (Iteration 3)
6. **Traffic light validation** — Auto-check regime detection per scenario (Iteration 3)
7. **CLI + dashboard** — Heatmap, equity curves, run button
8. **Model comparison** — Mechanical vs LLM vs previous
9. **Deflated Sharpe** — Multiple testing correction (Iteration 3)
10. **Walk-forward** — Rolling train/test validation (Phase 2)
11. **Post-retrain regression** — Auto-run suite after every retrain (Iteration 3)
12. **Allocator PDF export** — Due diligence document generation (Iteration 3)

---

## Updated Database Schema

```sql
CREATE TABLE simulation_results (
    result_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    scenario TEXT NOT NULL,
    regime_label TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    total_trades INTEGER,
    wins INTEGER,
    losses INTEGER,
    timeouts INTEGER,
    win_rate REAL,
    profit_factor REAL,
    total_pnl_pct REAL,
    max_drawdown_pct REAL,
    sharpe_ratio REAL,
    calmar_ratio REAL,
    -- Iteration 1: Benchmark + transaction costs
    benchmark_pnl_pct REAL,            -- SPY buy-and-hold for same period
    excess_return_pct REAL,            -- strategy - benchmark
    transaction_cost_bps REAL,         -- round-trip cost applied
    gross_pnl_pct REAL,                -- before costs
    net_pnl_pct REAL,                  -- after costs
    -- Iteration 1: Monte Carlo
    mc_median_dd REAL,
    mc_p95_dd REAL,                    -- 95th percentile max drawdown
    mc_p5_equity REAL,                 -- 5th percentile final equity
    mc_p95_equity REAL,
    mc_probability_of_ruin REAL,
    mc_n_simulations INTEGER,
    -- Iteration 3: Statistical rigor
    deflated_sharpe_pvalue REAL,       -- Bailey (2014) multiple testing correction
    n_trials_in_run INTEGER,           -- number of configurations tested
    -- Iteration 3: Traffic light validation
    tl_expected TEXT,                   -- expected traffic light state
    tl_actual_majority TEXT,           -- actual majority state during scenario
    tl_correct INTEGER,                -- 1 if match, 0 if mismatch
    -- Standard fields
    monthly_returns_json TEXT,
    equity_curve_json TEXT,
    regime_breakdown_json TEXT,
    model_version TEXT,
    config_json TEXT,
    verdict TEXT,
    statistical_confidence TEXT,        -- "high" (n>=50), "medium" (20-49), "insufficient" (<20)
    survivorship_bias INTEGER DEFAULT 1,
    random_seed INTEGER,
    git_commit TEXT,
    created_at TEXT NOT NULL
);
```
