#!/usr/bin/env python3
"""Full-regime simulation engine — test strategy across ALL market conditions.

When to run:
    Weekly (Sunday 9:30 PM ET via watch loop) or ad-hoc before due diligence.
    Also auto-triggered after model retrain for regression checks.

What it reads:
    - S&P 100 universe (src/universe/sp100.py)
    - OHLCV data from cache or yfinance (src/simulation/cache.py)
    - Feature engine (src/features/engine.py)
    - Traffic light (src/features/traffic_light.py)
    - Ranker (src/ranking/ranker.py)
    - Setup classifier (src/features/setup_classifier.py)
    - Mechanical bracket simulation (src/attribution/logger.py)

What it writes:
    - simulation_results table in SQLite (one row per scenario per run)

Usage:
    python scripts/simulation_engine.py                          # All 13 scenarios
    python scripts/simulation_engine.py --regime strong_bull     # Single regime
    python scripts/simulation_engine.py --monte-carlo 1000       # With MC resampling
    python scripts/simulation_engine.py --transitions-only        # Just 3 transitions
    python scripts/simulation_engine.py --validate-traffic-light  # Check TL accuracy
    python scripts/simulation_engine.py --clear-cache             # Delete cached data
    python scripts/simulation_engine.py --dry-run                 # Print config only
"""

import argparse
import json
import logging
import sqlite3
import subprocess
import sys
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.attribution.logger import simulate_mechanical_outcome
from src.config import DB_PATH
from src.features.indicators import compute_atr
from src.simulation.cache import (
    CACHE_DIR,
    _add_days,
    _subtract_days,
    clear_cache,
    fetch_cached_ohlcv,
    warm_cache,
)
from src.simulation.monte_carlo import monte_carlo_resample
from src.universe.sp100 import get_sp100_universe

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# ─── 13 Default Scenarios ────────────────────────────────────────────────────
# 10 pure regimes + 3 transitions from design spec.

SCENARIOS = {
    # Pure regimes
    "strong_bull": {"start": "2017-01-01", "end": "2017-12-31", "label": "Strong Bull"},
    "euphoric_bull": {"start": "2021-01-01", "end": "2021-06-30", "label": "Euphoric Bull"},
    "low_volatility": {"start": "2017-06-01", "end": "2017-11-30", "label": "Low Volatility"},
    "high_volatility": {"start": "2018-10-01", "end": "2019-01-31", "label": "High Volatility"},
    "sideways_chop": {"start": "2015-06-01", "end": "2015-12-31", "label": "Sideways Chop"},
    "sector_rotation": {"start": "2016-06-01", "end": "2016-12-31", "label": "Sector Rotation"},
    "rate_hiking": {"start": "2022-03-01", "end": "2022-09-30", "label": "Rate Hiking"},
    "rate_cutting": {"start": "2019-07-01", "end": "2019-12-31", "label": "Rate Cutting"},
    "v_recovery": {"start": "2020-02-01", "end": "2020-06-30", "label": "V-Recovery"},
    "grinding_bear": {"start": "2022-01-01", "end": "2022-10-31", "label": "Grinding Bear"},
    # Transitions
    "bull_to_bear": {"start": "2020-01-01", "end": "2020-04-30", "label": "Bull-to-Bear"},
    "bear_to_bull": {"start": "2020-03-01", "end": "2020-08-31", "label": "Bear-to-Bull"},
    "low_to_high_vol": {"start": "2018-01-01", "end": "2018-04-30", "label": "Low-to-High Vol"},
}

TRANSITION_SCENARIOS = {"bull_to_bear", "bear_to_bull", "low_to_high_vol"}

# ─── Transaction Cost Model (Ralph Loop Iteration 1) ─────────────────────────

TRANSACTION_COSTS = {
    "commission_per_side_bps": 0,
    "slippage_per_side_bps": 3,
    "spread_per_side_bps": 1.5,
}


def apply_costs(entry_price: float, exit_price: float,
                costs: dict = TRANSACTION_COSTS) -> tuple[float, float]:
    """Apply transaction costs to entry/exit prices."""
    total_bps = sum(costs.values())
    entry_adj = entry_price * (1 + total_bps / 10000)
    exit_adj = exit_price * (1 - total_bps / 10000)
    return entry_adj, exit_adj


# ─── VIX Regime Classification ───────────────────────────────────────────────

def classify_vix_regime(vix_value: float | None) -> str:
    """Classify VIX into regime bucket for bracket sizing."""
    if vix_value is None:
        return "normal"
    if vix_value < 12:
        return "low"
    elif vix_value <= 20:
        return "normal"
    elif vix_value <= 30:
        return "elevated"
    else:
        return "extreme"


REGIME_BRACKETS = {
    "low":      {"stop_atr_mult": 2.0, "target_atr_mult": 2.0, "timeout_days": 8},
    "normal":   {"stop_atr_mult": 2.0, "target_atr_mult": 2.0, "timeout_days": 8},
    "elevated": {"stop_atr_mult": 2.5, "target_atr_mult": 2.5, "timeout_days": 7},
    "extreme":  {"stop_atr_mult": 3.0, "target_atr_mult": 3.0, "timeout_days": 5},
}

TARGET_PCT = 0.03
STOP_PCT = 0.05
TIMEOUT_DAYS = 7

# ─── SPY Benchmark ───────────────────────────────────────────────────────────

def compute_benchmark(spy_data, start: str, end: str) -> float:
    """Compute SPY buy-and-hold return for the period."""
    import pandas as pd
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end)
    spy_after_start = spy_data.loc[spy_data.index >= start_dt]
    spy_before_end = spy_data.loc[spy_data.index <= end_dt]
    if spy_after_start.empty or spy_before_end.empty:
        return 0.0
    spy_start_price = float(spy_after_start.iloc[0]["Close"])
    spy_end_price = float(spy_before_end.iloc[-1]["Close"])
    if spy_start_price == 0:
        return 0.0
    return float((spy_end_price - spy_start_price) / spy_start_price * 100)


# ─── Traffic Light Validation (Ralph Loop Iteration 3) ───────────────────────

EXPECTED_TL = {
    "strong_bull": "GREEN",
    "euphoric_bull": "GREEN",
    "low_volatility": "GREEN",
    "high_volatility": "YELLOW",
    "sideways_chop": "GREEN",
    "sector_rotation": "GREEN",
    "rate_hiking": "YELLOW",
    "rate_cutting": "GREEN",
    "v_recovery": "RED",
    "grinding_bear": "YELLOW",
    "bull_to_bear": "GREEN\u2192RED",
    "bear_to_bull": "RED\u2192GREEN",
    "low_to_high_vol": "GREEN\u2192YELLOW",
}


def validate_traffic_light(scenario: str, tl_states: list[str]) -> dict:
    """Check if traffic light correctly identified the regime."""
    expected = EXPECTED_TL.get(scenario, "GREEN")
    majority = max(set(tl_states), key=tl_states.count) if tl_states else "UNKNOWN"

    if "\u2192" in expected:
        states = expected.split("\u2192")
        transitioned = all(s in tl_states for s in states)
        return {"scenario": scenario, "expected": expected,
                "actual_majority": majority, "transitioned": transitioned,
                "correct": transitioned, "tl_distribution": dict(Counter(tl_states))}

    return {"scenario": scenario, "expected": expected,
            "actual_majority": majority, "correct": majority == expected,
            "tl_distribution": dict(Counter(tl_states))}


# ─── Verdict Logic ────────────────────────────────────────────────────────────

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


# ─── Heatmap Output ──────────────────────────────────────────────────────────

def print_heatmap(results: dict[str, dict]):
    """Print the regime heatmap to console."""
    VERDICT_ICONS = {"edge": "\u2705", "neutral": "\u26aa", "marginal": "\u26a0\ufe0f",
                     "bleeds": "\u274c", "insufficient": "\U0001f4ca"}
    header = (f"{'Regime':<25} {'Trades':>6} {'WR':>6} {'PF':>6} {'DD':>7} "
              f"{'Sharpe':>7} {'SPY':>7} {'Excess':>7} {'Verdict':>12}")
    print(header)
    print("-" * len(header))
    for name, r in results.items():
        icon = VERDICT_ICONS.get(r["verdict"], "?")
        excess = r["total_pnl_pct"] - r.get("benchmark_pnl_pct", 0)
        print(f"{name:<25} {r['total_trades']:>6} {r['win_rate']:>5.0%} "
              f"{r.get('profit_factor', 0):>6.2f} {r['max_drawdown_pct']:>6.1f}% "
              f"{r.get('sharpe_ratio', 0):>7.2f} {r.get('benchmark_pnl_pct', 0):>6.1f}% "
              f"{excess:>+6.1f}% {icon} {r['verdict']:>10}")


# ─── Reproducibility (Ralph Loop Iteration 3) ────────────────────────────────

def get_reproducibility_info(seed: int, config: dict) -> dict:
    """Capture reproducibility metadata."""
    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        git_hash = "unknown"
    return {
        "random_seed": seed,
        "git_commit": git_hash,
        "config_snapshot": json.dumps(config),
        "python_version": sys.version,
    }


# ─── Core Scenario Runner ────────────────────────────────────────────────────

def run_scenario(name: str, start: str, end: str, config: dict | None = None) -> dict:
    """Run a single scenario through the Arcis pipeline.

    Pipeline per scan day:
    1. fetch_cached_ohlcv() for universe + SPY (from cache)
    2. Compute ATR, VIX regime, bracket sizing
    3. Rank candidates by momentum (reuses stress_test approach)
    4. simulate_mechanical_outcome() — bracket execution
    5. Apply transaction costs
    6. Track equity curve, P&L, regime stats, traffic light state
    """
    import pandas as pd

    config = config or {}
    scan_interval = config.get("scan_interval_days", 5)
    max_entries = config.get("max_entries_per_scan", 3)
    position_size = config.get("position_size", 2000)
    starting_equity = config.get("starting_equity", 100000)

    print(f"\n{'='*60}")
    print(f"  SCENARIO: {name} ({SCENARIOS.get(name, {}).get('label', name)})")
    print(f"  Period: {start} -> {end}")
    print(f"{'='*60}\n")

    # Fetch SPY data for benchmark and trading days
    extended_start = _subtract_days(start, 60)
    extended_end = _add_days(end, 20)
    spy_data = fetch_cached_ohlcv("SPY", extended_start, extended_end)
    if spy_data is None or spy_data.empty:
        return {"error": "No SPY data", "scenario": name, "start_date": start, "end_date": end}

    # Get trading days within the scenario window
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end)
    spy_in_range = spy_data.loc[(spy_data.index >= start_dt) & (spy_data.index <= end_dt)]
    trading_days = [d.strftime("%Y-%m-%d") for d in spy_in_range.index]
    if not trading_days:
        return {"error": "No trading days", "scenario": name, "start_date": start, "end_date": end}
    print(f"  Trading days: {len(trading_days)}")

    # Fetch VIX for regime brackets + traffic light
    vix_data_raw = fetch_cached_ohlcv("^VIX", extended_start, extended_end)
    vix_data = {}
    if vix_data_raw is not None and not vix_data_raw.empty:
        close_col = vix_data_raw["Close"]
        if isinstance(close_col, pd.DataFrame):
            close_col = close_col.iloc[:, 0]
        vix_data = {d.strftime("%Y-%m-%d"): float(v)
                    for d, v in zip(close_col.index, close_col)}
        print(f"  VIX data: {len(vix_data)} days")

    # Get universe
    universe = get_sp100_universe()
    print(f"  Universe: {len(universe)} tickers")

    # Track results
    trades = []
    equity_curve = [float(starting_equity)]
    monthly_returns = {}
    regime_stats = {}
    tl_states = []
    current_equity = float(starting_equity)

    for day_idx in range(0, len(trading_days), scan_interval):
        day = trading_days[day_idx]
        if day_idx % 20 == 0:
            print(f"  Processing: {day} ({day_idx}/{len(trading_days)} days)")

        # VIX regime
        vix_value = vix_data.get(day)
        regime = classify_vix_regime(vix_value)
        brackets = REGIME_BRACKETS[regime]

        # Traffic light approximation from VIX
        if vix_value is not None:
            if vix_value > 30:
                tl_color = "RED"
            elif vix_value > 20:
                tl_color = "YELLOW"
            else:
                tl_color = "GREEN"
        else:
            tl_color = "GREEN"
        tl_states.append(tl_color)

        # Rank candidates by momentum (mean-reversion heuristic)
        candidates = []
        for ticker in universe[:30]:
            try:
                hist_start = _subtract_days(day, 30)
                hist = fetch_cached_ohlcv(ticker, hist_start, day)
                if hist is None or len(hist) < 15:
                    continue
                close = hist["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                ret_5d = float(close.iloc[-1] / close.iloc[-5] - 1)
                atr = compute_atr(
                    pd.Series(hist["High"].values.flatten()),
                    pd.Series(hist["Low"].values.flatten()),
                    pd.Series(hist["Close"].values.flatten()),
                    period=14,
                )
                candidates.append((ticker, ret_5d, float(close.iloc[-1]), atr))
            except Exception:
                continue

        if not candidates:
            continue

        candidates.sort(key=lambda x: x[1])

        for ticker, _ret_5d, entry_price, atr in candidates[:max_entries]:
            # Bracket sizing
            if atr > 0:
                stop_price = entry_price - (atr * brackets["stop_atr_mult"])
                target_price = entry_price + (atr * brackets["target_atr_mult"])
                timeout = brackets["timeout_days"]
            else:
                target_price = entry_price * (1 + TARGET_PCT)
                stop_price = entry_price * (1 - STOP_PCT)
                timeout = TIMEOUT_DAYS

            # Forward data for outcome simulation
            fwd_start = _add_days(day, 1)
            fwd_end = _add_days(day, timeout + 5)
            try:
                fwd_data = fetch_cached_ohlcv(ticker, fwd_start, fwd_end)
                if fwd_data is None or fwd_data.empty:
                    continue
                ohlcv = fwd_data.reset_index().to_dict("records")
            except Exception:
                continue

            outcome, exit_price, days_held = simulate_mechanical_outcome(
                entry_price, stop_price, target_price, timeout, ohlcv,
            )

            # Apply transaction costs
            entry_adj, exit_adj = apply_costs(entry_price, exit_price)
            pnl_pct = (exit_adj - entry_adj) / entry_adj * 100
            pnl_dollars = pnl_pct / 100 * position_size
            current_equity += pnl_dollars

            trades.append({
                "date": day,
                "ticker": ticker,
                "entry": entry_price,
                "exit": exit_price,
                "entry_adj": entry_adj,
                "exit_adj": exit_adj,
                "outcome": outcome,
                "pnl_pct": round(pnl_pct, 2),
                "pnl_dollars": round(pnl_dollars, 2),
                "days_held": days_held,
                "regime": regime,
                "tl_color": tl_color,
                "vix": vix_value,
            })

            # Regime stats
            if regime not in regime_stats:
                regime_stats[regime] = {"trades": 0, "wins": 0, "losses": 0, "stops": 0}
            regime_stats[regime]["trades"] += 1
            if outcome == "win":
                regime_stats[regime]["wins"] += 1
            elif outcome == "loss":
                regime_stats[regime]["losses"] += 1
                regime_stats[regime]["stops"] += 1

            # Monthly returns
            month_key = day[:7]
            if month_key not in monthly_returns:
                monthly_returns[month_key] = 0.0
            monthly_returns[month_key] += pnl_pct

        equity_curve.append(round(current_equity, 2))

    # ─── Compute summary metrics ─────────────────────────────────────────
    total_trades = len(trades)
    wins = sum(1 for t in trades if t["outcome"] == "win")
    losses = sum(1 for t in trades if t["outcome"] == "loss")
    timeouts = sum(1 for t in trades if t["outcome"] == "timeout")
    win_rate = wins / total_trades if total_trades > 0 else 0
    total_pnl_pct = sum(t["pnl_pct"] for t in trades)
    gross_pnl_pct = sum(t["pnl_pct"] for t in trades if t["pnl_pct"] > 0)

    # Profit factor
    gross_wins = sum(t["pnl_pct"] for t in trades if t["pnl_pct"] > 0)
    gross_losses = abs(sum(t["pnl_pct"] for t in trades if t["pnl_pct"] < 0))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else (
        float("inf") if gross_wins > 0 else 0)

    # Max drawdown
    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # Sharpe ratio (annualized from daily-ish returns)
    import numpy as np
    if len(trades) > 1:
        returns = np.array([t["pnl_pct"] for t in trades])
        sharpe = float(np.mean(returns) / np.std(returns) * np.sqrt(52)) if np.std(returns) > 0 else 0
    else:
        sharpe = 0.0

    # Calmar ratio
    days_in_test = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
    annualized_return = (total_pnl_pct / 100) * (365 / max(days_in_test, 1)) * 100
    calmar = annualized_return / max_dd if max_dd > 0 else 0

    # Benchmark
    benchmark_pnl = compute_benchmark(spy_data, start, end)
    excess_return = total_pnl_pct - benchmark_pnl

    # Transaction cost summary
    total_cost_bps = sum(TRANSACTION_COSTS.values()) * 2  # Round trip

    result = {
        "scenario": name,
        "regime_label": SCENARIOS.get(name, {}).get("label", name),
        "start_date": start,
        "end_date": end,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "timeouts": timeouts,
        "win_rate": round(win_rate, 3),
        "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else 999.0,
        "total_pnl_pct": round(total_pnl_pct, 2),
        "gross_pnl_pct": round(gross_pnl_pct, 2),
        "net_pnl_pct": round(total_pnl_pct, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 3),
        "calmar_ratio": round(calmar, 3),
        "benchmark_pnl_pct": round(benchmark_pnl, 2),
        "excess_return_pct": round(excess_return, 2),
        "transaction_cost_bps": total_cost_bps,
        "monthly_returns": monthly_returns,
        "equity_curve": equity_curve,
        "regime_breakdown": {r: {
            "trades": s["trades"],
            "win_rate": round(s["wins"] / s["trades"], 3) if s["trades"] > 0 else 0,
        } for r, s in regime_stats.items()},
        "tl_states": tl_states,
        "trades": trades,
        "survivorship_bias": True,
    }

    # Verdict
    result["verdict"] = compute_verdict(result, benchmark_pnl)

    print(f"\n  Results: {total_trades} trades | WR: {win_rate:.1%} | "
          f"PF: {profit_factor:.2f} | DD: {max_dd:.1f}% | "
          f"Sharpe: {sharpe:.2f} | Verdict: {result['verdict']}")

    return result


# ─── Storage ──────────────────────────────────────────────────────────────────

def store_result(result: dict, run_id: str, seed: int, config: dict,
                 db_path: str = DB_PATH) -> None:
    """Store simulation result in database."""
    repro = get_reproducibility_info(seed, config)

    # Traffic light validation
    tl_states = result.get("tl_states", [])
    tl_val = validate_traffic_light(result["scenario"], tl_states)

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO simulation_results "
                "(result_id, run_id, scenario, regime_label, start_date, end_date, "
                "total_trades, wins, losses, timeouts, win_rate, profit_factor, "
                "total_pnl_pct, gross_pnl_pct, net_pnl_pct, max_drawdown_pct, "
                "sharpe_ratio, calmar_ratio, benchmark_pnl_pct, excess_return_pct, "
                "transaction_cost_bps, tl_expected, tl_actual_majority, tl_correct, "
                "monthly_returns_json, equity_curve_json, regime_breakdown_json, "
                "model_version, config_json, verdict, survivorship_bias, "
                "random_seed, git_commit, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    run_id,
                    result["scenario"],
                    result.get("regime_label", result["scenario"]),
                    result["start_date"],
                    result["end_date"],
                    result["total_trades"],
                    result["wins"],
                    result["losses"],
                    result["timeouts"],
                    result["win_rate"],
                    result.get("profit_factor", 0),
                    result["total_pnl_pct"],
                    result.get("gross_pnl_pct", 0),
                    result.get("net_pnl_pct", result["total_pnl_pct"]),
                    result["max_drawdown_pct"],
                    result.get("sharpe_ratio", 0),
                    result.get("calmar_ratio", 0),
                    result.get("benchmark_pnl_pct", 0),
                    result.get("excess_return_pct", 0),
                    result.get("transaction_cost_bps", 0),
                    tl_val.get("expected", ""),
                    tl_val.get("actual_majority", ""),
                    1 if tl_val.get("correct") else 0,
                    json.dumps(result.get("monthly_returns", {})),
                    json.dumps(result.get("equity_curve", [])),
                    json.dumps(result.get("regime_breakdown", {})),
                    result.get("model_version", "mechanical_brackets"),
                    repro["config_snapshot"][:10000],
                    result.get("verdict", "unknown"),
                    1 if result.get("survivorship_bias") else 0,
                    repro["random_seed"],
                    repro["git_commit"],
                    datetime.now(ET).isoformat(),
                ),
            )
            conn.commit()
    except Exception as e:
        logger.error("[SIM] Failed to store result for %s: %s", result["scenario"], e)


# ─── CLI Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Full-regime simulation engine")
    parser.add_argument("--regime", type=str, help="Run single regime")
    parser.add_argument("--monte-carlo", type=int, default=0,
                        help="MC simulations (0=disabled)")
    parser.add_argument("--transitions-only", action="store_true")
    parser.add_argument("--validate-traffic-light", action="store_true")
    parser.add_argument("--clear-cache", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model", type=str, default=None,
                        help="Model version tag for results")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.clear_cache:
        clear_cache()
        print("Cache cleared.")
        return

    # Select scenarios
    if args.regime:
        if args.regime not in SCENARIOS:
            print(f"Unknown regime: {args.regime}")
            print(f"Available: {', '.join(SCENARIOS.keys())}")
            return
        scenarios = {args.regime: SCENARIOS[args.regime]}
    elif args.transitions_only:
        scenarios = {k: v for k, v in SCENARIOS.items() if k in TRANSITION_SCENARIOS}
    else:
        scenarios = SCENARIOS

    config = {
        "scan_interval_days": 5,
        "max_entries_per_scan": 3,
        "position_size": 2000,
        "starting_equity": 100000,
        "transaction_costs": TRANSACTION_COSTS,
        "seed": args.seed,
        "model": args.model,
    }

    print("\n" + "=" * 60)
    print("  ARCIS FULL-REGIME SIMULATION ENGINE")
    print(f"  Scenarios: {len(scenarios)}")
    print(f"  Monte Carlo: {args.monte_carlo or 'disabled'}")
    print(f"  Seed: {args.seed}")
    print(f"  Cache dir: {CACHE_DIR}")
    print("=" * 60)

    if args.dry_run:
        print("\n[DRY RUN] Config:")
        print(json.dumps(config, indent=2))
        print("\nScenarios:")
        for name, dates in scenarios.items():
            print(f"  {name}: {dates['start']} -> {dates['end']} ({dates.get('label', '')})")
        return

    # Warm cache
    universe = get_sp100_universe()
    print(f"\n[CACHE] Warming cache for {len(scenarios)} scenarios x {len(universe)} tickers...")
    cache_stats = warm_cache(scenarios, universe)
    print(f"[CACHE] Done: {cache_stats['cached']}/{cache_stats['total']} cached, "
          f"{cache_stats['failed']} failed")

    # Run scenarios
    run_id = str(uuid.uuid4())
    results = {}
    all_trades = []

    for name, dates in scenarios.items():
        result = run_scenario(name, dates["start"], dates["end"], config)
        if "error" not in result:
            results[name] = result
            if args.model:
                result["model_version"] = args.model
            store_result(result, run_id, args.seed, config)
            all_trades.extend(result.get("trades", []))
        else:
            print(f"  [SKIP] {name}: {result['error']}")

    # Print heatmap
    if results:
        print(f"\n{'='*60}")
        print("  REGIME HEATMAP")
        print(f"{'='*60}\n")
        print_heatmap(results)

    # Monte Carlo
    mc_results = None
    if args.monte_carlo > 0 and all_trades:
        print(f"\n[MC] Running {args.monte_carlo} Monte Carlo simulations...")
        mc_results = monte_carlo_resample(
            all_trades, n_simulations=args.monte_carlo, seed=args.seed)
        print(f"[MC] Results:")
        print(f"  Median equity: ${mc_results['median_equity']:,.0f}")
        print(f"  P5 equity:     ${mc_results['p5_equity']:,.0f}")
        print(f"  P95 equity:    ${mc_results['p95_equity']:,.0f}")
        print(f"  P95 drawdown:  {mc_results['p95_dd']:.1f}%")
        print(f"  P(ruin):       {mc_results['probability_of_ruin']:.4f}")

    # Traffic light validation
    if args.validate_traffic_light and results:
        print(f"\n{'='*60}")
        print("  TRAFFIC LIGHT VALIDATION")
        print(f"{'='*60}\n")
        correct = 0
        total = 0
        for name, r in results.items():
            tl_val = validate_traffic_light(name, r.get("tl_states", []))
            total += 1
            if tl_val["correct"]:
                correct += 1
            status = "\u2705" if tl_val["correct"] else "\u274c"
            print(f"  {status} {name}: expected={tl_val['expected']}, "
                  f"actual={tl_val['actual_majority']}, "
                  f"dist={tl_val['tl_distribution']}")
        print(f"\n  Accuracy: {correct}/{total} ({correct/total:.0%})" if total else "")

    print(f"\n[DONE] Run ID: {run_id}")
    print(f"  Scenarios: {len(results)}/{len(scenarios)}")
    print(f"  Total trades: {len(all_trades)}")


if __name__ == "__main__":
    main()
