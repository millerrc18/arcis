# Sprint: Full-Regime Simulation Engine (v3 — Ralph ×3)

> **Priority:** HIGH — most important validation tool after the 50-trade gate
> **Estimated time:** 6-8 hours CC time (split into Sprint A: engine + Sprint B: dashboard)
> **Access:** LOCAL — CC has full access to codebase, tests, database, yfinance
> **Tag as v0.16.0 after merge.**
> **Design spec:** `docs/sprints/design-simulation-engine.md` (651 lines — READ FIRST)

> ⚠️ **Read first:**
> - `MASTER.md` (repo root)
> - `docs/sprints/design-simulation-engine.md` — full design spec with Ralph Loop iterations
> - `scripts/stress_test.py` (434 lines) — existing stress test to learn from and reuse

---

## Pre-Flight

1. Read `MASTER.md`
2. Read `docs/sprints/design-simulation-engine.md` (the full design spec with all 3 Ralph iterations)
3. Read `scripts/stress_test.py` — the existing stress test. Reuse: `simulate_mechanical_outcome()`,
   `classify_vix_regime()`, `store_result()` pattern, equity curve tracking
4. Run `python -m pytest tests/ -x -q` — record baseline
5. Verify dependencies:
   ```bash
   python -c "import yfinance; print('yfinance OK')"
   python -c "import numpy; print('numpy OK')"
   python -c "import pandas; print('pandas OK')"
   python -c "from sklearn.linear_model import LogisticRegression; print('sklearn OK')"
   ```
6. Check disk space for data cache: `df -h /home` or equivalent (need ~500MB for cached OHLCV)

---

## Task 1: Data Cache Layer

**Create `src/simulation/cache.py`:**

```python
"""OHLCV data cache for simulation engine — avoids re-fetching from yfinance.

First run downloads all data (~20 min for 13 scenarios × 103 tickers).
Subsequent runs: <2 min reading from parquet cache.

Cache location: data/simulation_cache/
Cache key format: {ticker}_{start}_{end}.parquet
Cache invalidation: manual delete or --clear-cache CLI flag
"""

import hashlib
import logging
from pathlib import Path
import pandas as pd
import yfinance as yf
from src.universe.sp100 import get_sp100_universe, to_yfinance_ticker

logger = logging.getLogger(__name__)
CACHE_DIR = Path("data/simulation_cache")

def fetch_cached_ohlcv(ticker: str, start: str, end: str,
                        cache_dir: Path = CACHE_DIR) -> pd.DataFrame | None:
    """Fetch OHLCV from cache or yfinance. Cache as parquet for speed."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Sanitize ticker for filename (BRK.B -> BRK_B)
    safe_ticker = ticker.replace(".", "_").replace("/", "_")
    cache_key = f"{safe_ticker}_{start}_{end}.parquet"
    cache_path = cache_dir / cache_key

    if cache_path.exists():
        return pd.read_parquet(cache_path)

    try:
        data = yf.download(to_yfinance_ticker(ticker), start=start, end=end,
                           progress=False, auto_adjust=True)
        if data is not None and not data.empty:
            # Fix yfinance MultiIndex columns
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            data.to_parquet(cache_path)
            return data
    except Exception as e:
        logger.warning("[SIM-CACHE] Failed to fetch %s: %s", ticker, e)
    return None

def warm_cache(scenarios: dict, universe: list[str],
               cache_dir: Path = CACHE_DIR) -> dict:
    """Pre-download all OHLCV data for all scenarios. Returns stats."""
    total = 0
    cached = 0
    failed = 0
    for name, dates in scenarios.items():
        # Extend range by 30 days before start (for feature lookback)
        # and 20 days after end (for forward outcome simulation)
        extended_start = _subtract_days(dates["start"], 60)
        extended_end = _add_days(dates["end"], 20)
        for ticker in universe:
            total += 1
            result = fetch_cached_ohlcv(ticker, extended_start, extended_end, cache_dir)
            if result is not None:
                cached += 1
            else:
                failed += 1
            if total % 50 == 0:
                print(f"  Cache warming: {total} fetched, {failed} failed")
    # Also cache SPY and VIX
    for idx_ticker in ["SPY", "^VIX"]:
        for name, dates in scenarios.items():
            fetch_cached_ohlcv(idx_ticker, _subtract_days(dates["start"], 60),
                               _add_days(dates["end"], 20), cache_dir)
    return {"total": total, "cached": cached, "failed": failed}

def clear_cache(cache_dir: Path = CACHE_DIR):
    """Delete all cached parquet files."""
    import shutil
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        logger.info("[SIM-CACHE] Cache cleared: %s", cache_dir)
```

---

## Task 2: Core Simulation Engine

**Create `scripts/simulation_engine.py`:**

13 default scenarios (10 pure regimes + 3 transitions from design spec).

```python
"""Full-regime simulation engine — test strategy across ALL market conditions.

Usage:
    python scripts/simulation_engine.py                          # All 13 scenarios
    python scripts/simulation_engine.py --regime strong_bull     # Single regime
    python scripts/simulation_engine.py --monte-carlo 1000       # With MC resampling
    python scripts/simulation_engine.py --transitions-only        # Just 3 transitions
    python scripts/simulation_engine.py --validate-traffic-light  # Check TL accuracy
    python scripts/simulation_engine.py --clear-cache             # Delete cached data
    python scripts/simulation_engine.py --dry-run                 # Print config only
"""
```

**13 SCENARIOS dict** — copy exactly from design spec (Section "Default Scenario Suite").

**Core function `run_scenario()`:**

For each scenario, run the REAL pipeline (not the simplified stress test heuristic):

```python
def run_scenario(name: str, start: str, end: str, config: dict) -> dict:
    """Run a single scenario through the real Arcis pipeline.

    Pipeline per scan day:
    1. fetch_cached_ohlcv() for universe + SPY (from cache)
    2. compute_all_features() — 7 dimensions, ~40 features
    3. compute_traffic_light() — VIX + SPY/200DMA + HY credit
    4. rank_universe() — 0-100 score per ticker
    5. classify_setup() — route to pullback/MR/breakout
    6. Apply risk governor checks (position limits, sector limits)
    7. simulate_mechanical_outcome() — bracket execution
    8. Track equity curve, P&L, regime stats
    """
```

**Key implementation details:**
- Scan every `scan_interval_days` (default 5) trading days
- Top `max_entries_per_scan` (default 3) candidates per scan
- Position size: `base_size * traffic_light_multiplier * event_risk_multiplier`
- Track per-scan traffic light state for validation
- Do NOT call Ollama/LLM — simulation uses ranker + mechanical brackets only
  (LLM comparison mode is a separate feature for later)

**Transaction cost model (from Ralph Loop Iteration 1):**

```python
TRANSACTION_COSTS = {
    "commission_per_side_bps": 0,
    "slippage_per_side_bps": 3,
    "spread_per_side_bps": 1.5,
}

def apply_costs(entry_price, exit_price, costs=TRANSACTION_COSTS):
    total_bps = sum(costs.values())
    entry_adj = entry_price * (1 + total_bps / 10000)
    exit_adj = exit_price * (1 - total_bps / 10000)
    return entry_adj, exit_adj
```

**SPY benchmark (from Ralph Loop Iteration 1):**

```python
def compute_benchmark(spy_data, start, end):
    spy_start = spy_data.loc[spy_data.index >= start].iloc[0]["Close"]
    spy_end = spy_data.loc[spy_data.index <= end].iloc[-1]["Close"]
    return float((spy_end - spy_start) / spy_start * 100)
```

---

## Task 3: Monte Carlo Module

**Create `src/simulation/monte_carlo.py`:**

```python
"""Monte Carlo resampling for simulation confidence intervals.

Reshuffles trade sequences 1,000+ times to produce:
- 5th/95th percentile equity bounds
- 95th percentile worst-case drawdown
- Probability of ruin
"""

import numpy as np

def monte_carlo_resample(trades: list[dict], n_simulations: int = 1000,
                          starting_equity: float = 100000,
                          seed: int = 42) -> dict:
    """Bootstrap resample trades to produce confidence intervals."""
    rng = np.random.RandomState(seed)  # Reproducible
    pnl_array = np.array([t["pnl_dollars"] for t in trades])

    final_equities = []
    max_drawdowns = []

    for _ in range(n_simulations):
        resampled = rng.choice(pnl_array, size=len(pnl_array), replace=True)
        equity = starting_equity
        peak = equity
        max_dd = 0.0

        for pnl in resampled:
            equity += pnl
            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)

        final_equities.append(equity)
        max_drawdowns.append(max_dd)

    fe = np.array(final_equities)
    md = np.array(max_drawdowns)

    return {
        "n_simulations": n_simulations,
        "seed": seed,
        "median_equity": float(np.median(fe)),
        "p5_equity": float(np.percentile(fe, 5)),
        "p95_equity": float(np.percentile(fe, 95)),
        "median_dd": float(np.median(md)),
        "p95_dd": float(np.percentile(md, 95)),
        "p99_dd": float(np.percentile(md, 99)),
        "probability_of_ruin": float(np.sum(fe <= 0) / n_simulations),
    }
```

---

## Task 4: Verdict Logic + Heatmap Output

**Add to `scripts/simulation_engine.py`:**

```python
MIN_TRADES_FOR_VERDICT = 20

def compute_verdict(metrics: dict, benchmark_pnl: float = 0) -> str:
    """Classify strategy performance in a regime."""
    n = metrics.get("total_trades", 0)
    if n < MIN_TRADES_FOR_VERDICT:
        return "insufficient"

    sharpe = metrics.get("sharpe_ratio", 0)
    pf = metrics.get("profit_factor", 0)
    excess = metrics.get("total_pnl_pct", 0) - benchmark_pnl

    if excess > 0 and sharpe >= 0.5 and pf >= 1.3:
        return "edge"
    elif metrics.get("total_pnl_pct", 0) >= 0 and pf >= 1.0:
        return "neutral"
    elif sharpe >= -0.3 and pf >= 0.8:
        return "marginal"
    else:
        return "bleeds"

def print_heatmap(results: dict[str, dict]):
    """Print the regime heatmap to console."""
    VERDICT_ICONS = {"edge": "✅", "neutral": "⚪", "marginal": "⚠️",
                     "bleeds": "❌", "insufficient": "📊"}
    header = f"{'Regime':<25} {'Trades':>6} {'WR':>6} {'PF':>6} {'DD':>7} {'Sharpe':>7} {'SPY':>7} {'Excess':>7} {'Verdict':>12}"
    print(header)
    print("-" * len(header))
    for name, r in results.items():
        icon = VERDICT_ICONS.get(r["verdict"], "?")
        excess = r["total_pnl_pct"] - r.get("benchmark_pnl_pct", 0)
        print(f"{name:<25} {r['total_trades']:>6} {r['win_rate']:>5.0%} "
              f"{r.get('profit_factor',0):>6.2f} {r['max_drawdown_pct']:>6.1f}% "
              f"{r.get('sharpe_ratio',0):>7.2f} {r.get('benchmark_pnl_pct',0):>6.1f}% "
              f"{excess:>+6.1f}% {icon} {r['verdict']:>10}")
```

---

## Task 5: Traffic Light Validation (Ralph Loop Iteration 3)

```python
EXPECTED_TL = {
    "strong_bull": "GREEN",
    "euphoric_bull": "GREEN",
    "low_volatility": "GREEN",
    "high_volatility": "YELLOW",
    "sideways_chop": "GREEN",
    "sector_rotation": "GREEN",
    "rate_hiking": "YELLOW",
    "rate_cutting": "GREEN",
    "v_recovery": "RED",       # Should be RED during crash, then transition
    "grinding_bear": "YELLOW",  # Should be YELLOW->RED
    "bull_to_bear": "GREEN→RED",
    "bear_to_bull": "RED→GREEN",
    "low_to_high_vol": "GREEN→YELLOW",
}

def validate_traffic_light(scenario: str, tl_states: list[str]) -> dict:
    """Check if traffic light correctly identified the regime."""
    expected = EXPECTED_TL.get(scenario, "GREEN")
    majority = max(set(tl_states), key=tl_states.count) if tl_states else "UNKNOWN"

    # For transition scenarios, check if both states appeared
    if "→" in expected:
        states = expected.split("→")
        transitioned = all(s in tl_states for s in states)
        return {"scenario": scenario, "expected": expected,
                "actual_majority": majority, "transitioned": transitioned,
                "correct": transitioned, "tl_distribution": dict(Counter(tl_states))}

    return {"scenario": scenario, "expected": expected,
            "actual_majority": majority, "correct": majority == expected,
            "tl_distribution": dict(Counter(tl_states))}
```

---

## Task 6: Schema + Storage

**Add to `src/schema/registry.py`:**

```python
"simulation_results": {
    "columns": [
        ("result_id", "TEXT PRIMARY KEY"),
        ("run_id", "TEXT NOT NULL"),
        ("scenario", "TEXT NOT NULL"),
        ("regime_label", "TEXT NOT NULL"),
        ("start_date", "TEXT NOT NULL"),
        ("end_date", "TEXT NOT NULL"),
        ("total_trades", "INTEGER"),
        ("wins", "INTEGER"),
        ("losses", "INTEGER"),
        ("timeouts", "INTEGER"),
        ("win_rate", "REAL"),
        ("profit_factor", "REAL"),
        ("total_pnl_pct", "REAL"),
        ("gross_pnl_pct", "REAL"),
        ("net_pnl_pct", "REAL"),
        ("max_drawdown_pct", "REAL"),
        ("sharpe_ratio", "REAL"),
        ("calmar_ratio", "REAL"),
        ("benchmark_pnl_pct", "REAL"),
        ("excess_return_pct", "REAL"),
        ("transaction_cost_bps", "REAL"),
        ("mc_median_dd", "REAL"),
        ("mc_p95_dd", "REAL"),
        ("mc_p5_equity", "REAL"),
        ("mc_p95_equity", "REAL"),
        ("mc_probability_of_ruin", "REAL"),
        ("mc_n_simulations", "INTEGER"),
        ("tl_expected", "TEXT"),
        ("tl_actual_majority", "TEXT"),
        ("tl_correct", "INTEGER"),
        ("monthly_returns_json", "TEXT"),
        ("equity_curve_json", "TEXT"),
        ("regime_breakdown_json", "TEXT"),
        ("model_version", "TEXT"),
        ("config_json", "TEXT"),
        ("verdict", "TEXT"),
        ("statistical_confidence", "TEXT"),
        ("survivorship_bias", "INTEGER DEFAULT 1"),
        ("random_seed", "INTEGER"),
        ("git_commit", "TEXT"),
        ("created_at", "TEXT NOT NULL"),
    ],
},
```

Register in the TABLES dict. Run `python -m src.main validate-schema --fix` after.

---

## Task 7: Reproducibility (Ralph Loop Iteration 3)

Every simulation run captures:
```python
import subprocess

def get_reproducibility_info(seed: int, config: dict) -> dict:
    git_hash = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    return {
        "random_seed": seed,
        "git_commit": git_hash,
        "config_snapshot": json.dumps(config),
        "python_version": sys.version,
    }
```

Store in `config_json` and `random_seed` + `git_commit` columns.

---

## Task 8: CLI Entrypoint

Wire everything together in `scripts/simulation_engine.py` `main()`:

```python
def main():
    parser = argparse.ArgumentParser(description="Full-regime simulation engine")
    parser.add_argument("--regime", type=str, help="Run single regime")
    parser.add_argument("--monte-carlo", type=int, default=0, help="MC simulations (0=disabled)")
    parser.add_argument("--transitions-only", action="store_true")
    parser.add_argument("--validate-traffic-light", action="store_true")
    parser.add_argument("--clear-cache", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.clear_cache:
        clear_cache()
        return

    # Print config
    # Warm cache
    # Run scenarios
    # Print heatmap
    # Run Monte Carlo if requested
    # Validate traffic light if requested
    # Store results
```

---

## Task 9: API Endpoint + Dashboard Wiring

**Add to `src/api/routes/system.py`:**
```python
@router.get("/simulation/results")
def simulation_results():
    """Get simulation results for dashboard display."""
    # Query simulation_results table, return as JSON
    # Include latest run's heatmap data
```

**Add to `src/api/routes/actions.py` command handler:**
```python
# In the command dispatch for "simulation":
elif command_name == "simulation":
    subprocess.Popen([sys.executable, "scripts/simulation_engine.py", "--monte-carlo", "1000"])
```

---

## Tests

**Create `tests/test_simulation_engine.py`:**
- `test_cache_fetch_and_store()` — verify parquet caching works
- `test_cache_warm_with_mock_yfinance()` — mock yfinance, verify cache population
- `test_run_scenario_minimal()` — run 1 scenario with 5 tickers, 10 trading days, verify output structure
- `test_transaction_cost_application()` — verify costs reduce P&L correctly
- `test_benchmark_computation()` — verify SPY buy-and-hold calculation
- `test_monte_carlo_deterministic()` — verify same seed produces same results
- `test_monte_carlo_confidence_intervals()` — verify p5 < median < p95
- `test_verdict_logic_all_cases()` — test edge/neutral/marginal/bleeds/insufficient
- `test_verdict_insufficient_trades()` — verify <20 trades = "insufficient"
- `test_traffic_light_validation()` — verify transition detection for "→" scenarios
- `test_heatmap_output_format()` — verify print_heatmap produces correct table
- `test_reproducibility_info()` — verify git hash and config captured
- `test_schema_registered()` — verify simulation_results in registry

---

## Verification

```bash
python -m pytest tests/ -x -q                            # Pass count >= baseline
python -m pytest tests/test_simulation_engine.py -v       # All new tests pass
cd frontend && npm run build && cd ..                     # Succeeds

# Smoke test: run 1 scenario
python scripts/simulation_engine.py --regime strong_bull --dry-run
python scripts/simulation_engine.py --regime low_volatility

# Verify cache works (second run should be fast)
time python scripts/simulation_engine.py --regime low_volatility
# Expected: <30 seconds on second run

# Full run (if time allows)
python scripts/simulation_engine.py --monte-carlo 500
```

---

## Commit Strategy

```bash
# Commit 1: Cache + core engine
git add src/simulation/ scripts/simulation_engine.py
git commit -m "feat: full-regime simulation engine — 13 scenarios with data caching

10 pure regimes + 3 transitions. Uses real Arcis pipeline (features,
traffic light, ranker, setup classifier). Data cache: 20 min first run,
<2 min cached. Transaction cost model (9 bps RT). SPY benchmark.
Regime heatmap with verdict logic (edge/neutral/marginal/bleeds)."

# Commit 2: Monte Carlo + traffic light validation
git add src/simulation/monte_carlo.py
git commit -m "feat: Monte Carlo resampling + traffic light validation

1000-shuffle bootstrap for confidence intervals (p5/p95 equity, p95 DD,
probability of ruin). Traffic light validation checks regime detection
accuracy per scenario, including transition detection for →scenarios."

# Commit 3: Schema + tests + reproducibility
git add src/schema/registry.py tests/test_simulation_engine.py src/api/
git commit -m "feat: simulation schema, API endpoint, tests, reproducibility

simulation_results table with MC fields, TL validation, benchmark.
Reproducibility: fixed seed, git hash, config snapshot.
API endpoint for dashboard. 13 test cases."

# Tag + push
git tag -a v0.16.0 -m "v0.16.0 — Full-regime simulation engine: 13 scenarios, Monte Carlo, traffic light validation"
git push origin main && git push origin v0.16.0
```

Update MASTER.md and RELEASES.md.
