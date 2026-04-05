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

## Default Scenario Suite (10 regimes, one of each)

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
# Run all 10 default scenarios
python scripts/simulation_engine.py

# Run single regime
python scripts/simulation_engine.py --regime strong_bull

# Run with custom config
python scripts/simulation_engine.py --config config/simulation_custom.yaml

# Compare two model versions
python scripts/simulation_engine.py --compare mechanical vs halcyon-v1.0.0

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
