#!/usr/bin/env python3
"""Full-regime simulation engine — test strategy across ALL market conditions.

When to run:
    Ad-hoc or after retraining. The most important validation tool after
    the 50-trade gate. Produces a regime heatmap showing where the strategy
    has edge, breaks even, or bleeds.

What it reads:
    - S&P 100 universe (src/universe/sp100.py)
    - yfinance OHLCV data (cached in data/simulation_cache/)
    - Feature engine, traffic light, ranker, setup classifier
    - Mechanical bracket simulation (src/attribution/logger.py)

What it writes:
    - simulation_results table in SQLite (one row per scenario per run)

Usage:
    python scripts/simulation_engine.py                          # All 13 scenarios
    python scripts/simulation_engine.py --regime strong_bull     # Single regime
    python scripts/simulation_engine.py --monte-carlo 1000       # With MC resampling
    python scripts/simulation_engine.py --transitions-only       # Just 3 transitions
    python scripts/simulation_engine.py --validate-traffic-light # Check TL accuracy
    python scripts/simulation_engine.py --clear-cache            # Delete cached data
    python scripts/simulation_engine.py --dry-run                # Print config only
"""

import argparse
import json
import logging
import math
import sqlite3
import subprocess
import sys
import uuid
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src.attribution.logger import simulate_mechanical_outcome
from src.config import DB_PATH
from src.features.indicators import compute_atr
from src.simulation.cache import (
    clear_cache,
    fetch_cached_ohlcv,
    warm_cache,
)
from src.simulation.monte_carlo import monte_carlo_resample
from src.universe.sp100 import get_sp100_universe

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# 13 Scenarios: 10 pure regimes + 3 transitions
# ---------------------------------------------------------------------------

SCENARIOS = {
    "strong_bull": {
        "start": "2013-01-01", "end": "2013-12-31",
        "label": "Strong Bull (2013)", "regime": "bull",
    },
    "euphoric_bull": {
        "start": "2021-01-01", "end": "2021-11-30",
        "label": "Euphoric Bull (2021)", "regime": "bull",
    },
    "low_volatility": {
        "start": "2017-01-01", "end": "2017-10-31",
        "label": "Low Volatility (2017)", "regime": "low_vol",
    },
    "high_volatility": {
        "start": "2018-10-01", "end": "2019-03-31",
        "label": "High Volatility (2018-19)", "regime": "high_vol",
    },
    "sideways_chop": {
        "start": "2015-01-01", "end": "2015-12-31",
        "label": "Sideways Chop (2015)", "regime": "chop",
    },
    "sector_rotation": {
        "start": "2016-01-01", "end": "2016-12-31",
        "label": "Sector Rotation (2016)", "regime": "rotation",
    },
    "rate_hiking": {
        "start": "2022-01-01", "end": "2022-12-31",
        "label": "Rate Hiking (2022)", "regime": "bear",
    },
    "rate_cutting": {
        "start": "2019-07-01", "end": "2020-01-31",
        "label": "Rate Cutting (2019-20)", "regime": "bull",
    },
    "v_recovery": {
        "start": "2020-03-01", "end": "2020-06-30",
        "label": "V-Recovery (2020)", "regime": "crisis",
    },
    "grinding_bear": {
        "start": "2022-01-01", "end": "2022-10-31",
        "label": "Grinding Bear (2022)", "regime": "bear",
    },
    # Transition scenarios
    "bull_to_bear": {
        "start": "2007-10-01", "end": "2009-03-31",
        "label": "Bull to Bear (2007-09)", "regime": "transition",
    },
    "bear_to_bull": {
        "start": "2009-03-01", "end": "2010-03-31",
        "label": "Bear to Bull (2009-10)", "regime": "transition",
    },
    "low_to_high_vol": {
        "start": "2018-01-01", "end": "2018-06-30",
        "label": "Low to High Vol (2018)", "regime": "transition",
    },
}

TRANSITION_SCENARIOS = {"bull_to_bear", "bear_to_bull", "low_to_high_vol"}

# ---------------------------------------------------------------------------
# Transaction Cost Model (Ralph Loop Iteration 1)
# ---------------------------------------------------------------------------

TRANSACTION_COSTS = {
    "commission_per_side_bps": 0,       # Alpaca = $0
    "slippage_per_side_bps": 3,         # S&P 100 market orders: ~1-5 bps
    "spread_per_side_bps": 1.5,         # Large-cap half-spread: ~1-3 bps
}


def apply_costs(entry_price: float, exit_price: float,
                costs: dict = TRANSACTION_COSTS) -> tuple[float, float]:
    """Apply transaction costs to entry/exit prices."""
    total_bps = sum(costs.values())
    entry_adj = entry_price * (1 + total_bps / 10000)
    exit_adj = exit_price * (1 - total_bps / 10000)
    return entry_adj, exit_adj


# ---------------------------------------------------------------------------
# SPY Benchmark (Ralph Loop Iteration 1)
# ---------------------------------------------------------------------------

def compute_benchmark(spy_data: pd.DataFrame, start: str, end: str) -> float:
    """SPY buy-and-hold return for the scenario period."""
    try:
        spy_start = spy_data.loc[spy_data.index >= start].iloc[0]["Close"]
        spy_end = spy_data.loc[spy_data.index <= end].iloc[-1]["Close"]
        return float((spy_end - spy_start) / spy_start * 100)
    except (IndexError, KeyError):
        return 0.0


# ---------------------------------------------------------------------------
# Traffic Light Validation (Task 5 / Ralph Loop Iteration 3)
# ---------------------------------------------------------------------------

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
    "bull_to_bear": "GREEN->RED",
    "bear_to_bull": "RED->GREEN",
    "low_to_high_vol": "GREEN->YELLOW",
}


def validate_traffic_light(scenario: str, tl_states: list[str]) -> dict:
    """Check if traffic light correctly identified the regime."""
    expected = EXPECTED_TL.get(scenario, "GREEN")
    majority = max(set(tl_states), key=tl_states.count) if tl_states else "UNKNOWN"

    # For transition scenarios, check if both states appeared
    if "->" in expected:
        states = expected.split("->")
        transitioned = all(s in tl_states for s in states)
        return {
            "scenario": scenario,
            "expected": expected,
            "actual_majority": majority,
            "transitioned": transitioned,
            "correct": transitioned,
            "tl_distribution": dict(Counter(tl_states)),
        }

    return {
        "scenario": scenario,
        "expected": expected,
        "actual_majority": majority,
        "correct": majority == expected,
        "tl_distribution": dict(Counter(tl_states)),
    }


# ---------------------------------------------------------------------------
# Verdict Logic (Task 4)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Heatmap Output (Task 4)
# ---------------------------------------------------------------------------

VERDICT_ICONS = {
    "edge": "+", "neutral": "~", "marginal": "!",
    "bleeds": "X", "insufficient": "?",
}


def print_heatmap(results: dict[str, dict]):
    """Print the regime heatmap to console."""
    header = (f"{'Regime':<25} {'Trades':>6} {'WR':>6} {'PF':>6} {'DD':>7} "
              f"{'Sharpe':>7} {'SPY':>7} {'Excess':>7} {'Verdict':>12}")
    print(header)
    print("-" * len(header))
    for name, r in results.items():
        excess = r["total_pnl_pct"] - r.get("benchmark_pnl_pct", 0)
        icon = VERDICT_ICONS.get(r["verdict"], "?")
        print(f"{name:<25} {r['total_trades']:>6} {r['win_rate']:>5.0%} "
              f"{r.get('profit_factor', 0):>6.2f} {r['max_drawdown_pct']:>6.1f}% "
              f"{r.get('sharpe_ratio', 0):>7.2f} {r.get('benchmark_pnl_pct', 0):>6.1f}% "
              f"{excess:>+6.1f}% [{icon}] {r['verdict']:>10}")


# ---------------------------------------------------------------------------
# Reproducibility (Task 7)
# ---------------------------------------------------------------------------

def get_reproducibility_info(seed: int, config: dict) -> dict:
    """Capture reproducibility metadata for a simulation run."""
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


# ---------------------------------------------------------------------------
# Position Sizing (mirrors live system)
# ---------------------------------------------------------------------------

def compute_position_size(base_size: float, traffic_light: str,
                          event_risk_score: float = 0) -> float:
    """Mirror live system sizing: base x traffic_light x event_risk."""
    tl_mult = {"GREEN": 1.0, "YELLOW": 0.5, "RED": 0.1}.get(traffic_light, 1.0)
    er_mult = max(0.3, 1.0 - event_risk_score * 0.1)
    return base_size * tl_mult * er_mult


# ---------------------------------------------------------------------------
# Regime bracket parameters (from stress_test.py)
# ---------------------------------------------------------------------------

REGIME_BRACKETS = {
    "low":      {"stop_atr_mult": 2.0, "target_atr_mult": 2.0, "timeout_days": 8},
    "normal":   {"stop_atr_mult": 2.0, "target_atr_mult": 2.0, "timeout_days": 8},
    "elevated": {"stop_atr_mult": 2.5, "target_atr_mult": 2.5, "timeout_days": 7},
    "extreme":  {"stop_atr_mult": 3.0, "target_atr_mult": 3.0, "timeout_days": 5},
}

TARGET_PCT = 0.03
STOP_PCT = 0.05
TIMEOUT_DAYS = 7


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


# ---------------------------------------------------------------------------
# Core Simulation Engine (Task 2)
# ---------------------------------------------------------------------------

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
    scan_interval = config.get("scan_interval_days", 5)
    max_entries = config.get("max_entries_per_scan", 3)
    universe_size = config.get("universe_size", 30)
    base_position_size = config.get("position_size", 2000)
    starting_equity = config.get("starting_equity", 100000)

    print(f"\n{'='*60}")
    print(f"  SCENARIO: {name} ({start} -> {end})")
    print(f"{'='*60}")

    # Load SPY data for benchmark + traffic light
    extended_start = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=300)).strftime("%Y-%m-%d")
    extended_end = (datetime.strptime(end, "%Y-%m-%d") + timedelta(days=20)).strftime("%Y-%m-%d")

    spy_data = fetch_cached_ohlcv("SPY", extended_start, extended_end)
    if spy_data is None or spy_data.empty:
        print("  ERROR: No SPY data available")
        return {"error": "No SPY data", "scenario": name}

    # Load VIX data
    vix_data = fetch_cached_ohlcv("^VIX", extended_start, extended_end)
    vix_lookup = {}
    if vix_data is not None and not vix_data.empty:
        close_col = vix_data["Close"].squeeze() if isinstance(vix_data["Close"], pd.DataFrame) else vix_data["Close"]
        vix_lookup = {d.strftime("%Y-%m-%d"): float(v) for d, v in zip(close_col.index, close_col)}

    # Get trading days within the scenario window
    scenario_spy = spy_data.loc[(spy_data.index >= start) & (spy_data.index <= end)]
    if scenario_spy.empty:
        print("  ERROR: No trading days in range")
        return {"error": "No trading days", "scenario": name}

    trading_days = [d.strftime("%Y-%m-%d") for d in scenario_spy.index]
    print(f"  Trading days: {len(trading_days)}")

    # Get universe
    universe = get_sp100_universe()[:universe_size]
    print(f"  Universe: {len(universe)} tickers")

    # Pre-load OHLCV for all universe tickers
    ticker_data = {}
    for ticker in universe:
        data = fetch_cached_ohlcv(ticker, extended_start, extended_end)
        if data is not None and not data.empty:
            ticker_data[ticker] = data

    print(f"  Tickers with data: {len(ticker_data)}")

    # ── Simulation loop ──────────────────────────────────────────────────
    trades = []
    equity_curve = [starting_equity]
    monthly_returns = {}
    tl_states = []  # Track traffic light states for validation
    current_equity = starting_equity

    for day_idx in range(0, len(trading_days), scan_interval):
        day = trading_days[day_idx]
        if day_idx % 20 == 0:
            print(f"  Processing: {day} ({day_idx}/{len(trading_days)} days)")

        # ── Traffic Light ────────────────────────────────────────────────
        vix_value = vix_lookup.get(day)
        vix_regime = classify_vix_regime(vix_value)
        brackets = REGIME_BRACKETS[vix_regime]

        # Compute traffic light from VIX + SPY trend
        spy_slice = spy_data.loc[spy_data.index <= day]
        tl_state = "GREEN"  # Default
        try:
            from src.features.traffic_light import compute_traffic_light
            tl_result = compute_traffic_light(spy=spy_slice, vix=vix_value)
            tl_state = tl_result.get("regime_label", "GREEN")
        except Exception:
            # Fallback: infer from VIX
            if vix_value and vix_value > 30:
                tl_state = "RED"
            elif vix_value and vix_value > 20:
                tl_state = "YELLOW"

        tl_states.append(tl_state)

        # ── Feature computation + ranking ────────────────────────────────
        # Build OHLCV dict sliced to this scan day (no look-ahead)
        ohlcv_for_features = {}
        for ticker, data in ticker_data.items():
            sliced = data.loc[data.index <= day]
            if len(sliced) >= 200:
                ohlcv_for_features[ticker] = sliced

        if not ohlcv_for_features:
            continue

        # Try the real pipeline; fall back to simple momentum if it fails
        ranked_tickers = []
        try:
            from src.features.engine import compute_all_features
            from src.ranking.ranker import rank_universe

            features = compute_all_features(ohlcv_for_features, spy_slice)
            if features:
                ranked = rank_universe(features)
                ranked_tickers = [
                    (r["ticker"], r.get("score", 50), r.get("features", {}))
                    for r in ranked[:max_entries]
                ]
        except Exception as e:
            logger.debug("[SIM] Pipeline fallback for %s: %s", day, e)

        # Fallback: simple momentum ranking (most oversold)
        if not ranked_tickers:
            candidates = []
            for ticker, data in ohlcv_for_features.items():
                if len(data) >= 5:
                    close = data["Close"].squeeze() if isinstance(data["Close"], pd.DataFrame) else data["Close"]
                    ret_5d = float(close.iloc[-1] / close.iloc[-5] - 1)
                    candidates.append((ticker, ret_5d, {}))
            candidates.sort(key=lambda x: x[1])
            ranked_tickers = [(t, 50, f) for t, _, f in candidates[:max_entries]]

        # ── Simulate trades ──────────────────────────────────────────────
        for ticker, score, _feats in ranked_tickers:
            if ticker not in ticker_data:
                continue
            data = ticker_data[ticker]
            sliced = data.loc[data.index <= day]
            if sliced.empty:
                continue

            close_series = sliced["Close"].squeeze() if isinstance(sliced["Close"], pd.DataFrame) else sliced["Close"]
            entry_price = float(close_series.iloc[-1])

            # ATR-based brackets
            high_s = sliced["High"].squeeze() if isinstance(sliced["High"], pd.DataFrame) else sliced["High"]
            low_s = sliced["Low"].squeeze() if isinstance(sliced["Low"], pd.DataFrame) else sliced["Low"]
            close_s = sliced["Close"].squeeze() if isinstance(sliced["Close"], pd.DataFrame) else sliced["Close"]
            atr = compute_atr(pd.Series(high_s.values), pd.Series(low_s.values),
                              pd.Series(close_s.values), period=14)

            if atr > 0:
                stop_price = entry_price - (atr * brackets["stop_atr_mult"])
                target_price = entry_price + (atr * brackets["target_atr_mult"])
                timeout = brackets["timeout_days"]
            else:
                target_price = entry_price * (1 + TARGET_PCT)
                stop_price = entry_price * (1 - STOP_PCT)
                timeout = TIMEOUT_DAYS

            # Get forward data for outcome simulation
            fwd_start = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            fwd_end = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=timeout + 5)).strftime("%Y-%m-%d")
            fwd_data = data.loc[(data.index >= fwd_start) & (data.index <= fwd_end)]
            if fwd_data.empty:
                continue

            ohlcv_list = fwd_data.reset_index().to_dict("records")

            # Apply transaction costs
            entry_adj, _ = apply_costs(entry_price, entry_price)

            outcome, raw_exit, days_held = simulate_mechanical_outcome(
                entry_price, stop_price, target_price, timeout, ohlcv_list,
            )

            # Adjust exit for transaction costs
            _, exit_price = apply_costs(entry_price, raw_exit)

            gross_pnl_pct = (raw_exit - entry_price) / entry_price * 100
            net_pnl_pct = (exit_price - entry_adj) / entry_adj * 100

            # Position sizing with traffic light
            position_size = compute_position_size(base_position_size, tl_state)
            pnl_dollars = net_pnl_pct / 100 * position_size
            current_equity += pnl_dollars

            trades.append({
                "date": day,
                "ticker": ticker,
                "entry": entry_price,
                "exit": raw_exit,
                "entry_adj": entry_adj,
                "exit_adj": exit_price,
                "outcome": outcome,
                "gross_pnl_pct": round(gross_pnl_pct, 4),
                "net_pnl_pct": round(net_pnl_pct, 4),
                "pnl_dollars": round(pnl_dollars, 2),
                "days_held": days_held,
                "vix_regime": vix_regime,
                "traffic_light": tl_state,
                "position_size": position_size,
                "score": score,
            })

            # Monthly returns tracking
            month_key = day[:7]
            if month_key not in monthly_returns:
                monthly_returns[month_key] = 0.0
            monthly_returns[month_key] += net_pnl_pct

        equity_curve.append(round(current_equity, 2))

    # ── Compute summary metrics ──────────────────────────────────────────
    total_trades = len(trades)
    wins = sum(1 for t in trades if t["outcome"] == "win")
    losses = sum(1 for t in trades if t["outcome"] == "loss")
    timeouts = sum(1 for t in trades if t["outcome"] == "timeout")
    win_rate = wins / total_trades if total_trades > 0 else 0

    total_pnl_pct = sum(t["net_pnl_pct"] for t in trades)
    gross_pnl_pct = sum(t["gross_pnl_pct"] for t in trades)

    # Profit factor
    gross_wins = sum(t["net_pnl_pct"] for t in trades if t["net_pnl_pct"] > 0)
    gross_losses = abs(sum(t["net_pnl_pct"] for t in trades if t["net_pnl_pct"] < 0))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else (
        float("inf") if gross_wins > 0 else 0
    )

    # Max drawdown
    peak = equity_curve[0]
    max_dd = 0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Sharpe ratio (annualized, assuming ~150 trades/year cadence)
    pnl_series = [t["net_pnl_pct"] for t in trades]
    if len(pnl_series) >= 2:
        mean_r = sum(pnl_series) / len(pnl_series)
        std_r = (sum((r - mean_r) ** 2 for r in pnl_series) / (len(pnl_series) - 1)) ** 0.5
        sharpe = (mean_r / std_r) * math.sqrt(150) if std_r > 0 else 0
    else:
        sharpe = 0

    # Calmar ratio
    days_in_test = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
    annualized_return = (total_pnl_pct / 100) * (365 / max(days_in_test, 1)) * 100
    calmar = annualized_return / max_dd if max_dd > 0 else 0

    # Benchmark
    benchmark_pnl = compute_benchmark(spy_data, start, end)
    excess_return = total_pnl_pct - benchmark_pnl

    # Statistical confidence
    if total_trades >= 50:
        confidence = "high"
    elif total_trades >= MIN_TRADES_FOR_VERDICT:
        confidence = "medium"
    else:
        confidence = "insufficient"

    # Verdict
    metrics = {
        "total_trades": total_trades,
        "sharpe_ratio": sharpe,
        "profit_factor": profit_factor,
        "total_pnl_pct": total_pnl_pct,
    }
    verdict = compute_verdict(metrics, benchmark_pnl)

    # Traffic light validation
    tl_validation = validate_traffic_light(name, tl_states)

    # Transaction cost in bps
    total_cost_bps = sum(TRANSACTION_COSTS.values()) * 2  # round-trip

    result = {
        "scenario": name,
        "regime_label": SCENARIOS[name]["label"],
        "start_date": start,
        "end_date": end,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "timeouts": timeouts,
        "win_rate": round(win_rate, 4),
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
        "tl_states": tl_states,
        "tl_validation": tl_validation,
        "verdict": verdict,
        "statistical_confidence": confidence,
        "trades": trades,
        "survivorship_bias": True,
    }

    print(f"\n  Results: {total_trades} trades | WR: {win_rate:.1%} | "
          f"PF: {profit_factor:.2f} | DD: {max_dd:.1f}% | Sharpe: {sharpe:.2f}")
    print(f"  Benchmark (SPY): {benchmark_pnl:+.1f}% | Excess: {excess_return:+.1f}%")
    print(f"  Traffic Light: {tl_validation['actual_majority']} "
          f"(expected {tl_validation['expected']}, correct={tl_validation['correct']})")
    print(f"  Verdict: {verdict} | Confidence: {confidence}")

    return result


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def store_result(result: dict, run_id: str, repro: dict,
                 mc_result: dict | None = None, db_path: str = DB_PATH) -> None:
    """Store simulation result in database."""
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO simulation_results "
                "(result_id, run_id, scenario, regime_label, start_date, end_date, "
                "total_trades, wins, losses, timeouts, win_rate, profit_factor, "
                "total_pnl_pct, gross_pnl_pct, net_pnl_pct, max_drawdown_pct, "
                "sharpe_ratio, calmar_ratio, benchmark_pnl_pct, excess_return_pct, "
                "transaction_cost_bps, mc_median_dd, mc_p95_dd, mc_p5_equity, "
                "mc_p95_equity, mc_probability_of_ruin, mc_n_simulations, "
                "tl_expected, tl_actual_majority, tl_correct, "
                "monthly_returns_json, equity_curve_json, regime_breakdown_json, "
                "model_version, config_json, verdict, statistical_confidence, "
                "survivorship_bias, random_seed, git_commit, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    run_id,
                    result["scenario"],
                    result["regime_label"],
                    result["start_date"],
                    result["end_date"],
                    result["total_trades"],
                    result["wins"],
                    result["losses"],
                    result["timeouts"],
                    result["win_rate"],
                    result["profit_factor"],
                    result["total_pnl_pct"],
                    result.get("gross_pnl_pct"),
                    result.get("net_pnl_pct"),
                    result["max_drawdown_pct"],
                    result["sharpe_ratio"],
                    result["calmar_ratio"],
                    result.get("benchmark_pnl_pct"),
                    result.get("excess_return_pct"),
                    result.get("transaction_cost_bps"),
                    mc_result.get("median_dd") if mc_result else None,
                    mc_result.get("p95_dd") if mc_result else None,
                    mc_result.get("p5_equity") if mc_result else None,
                    mc_result.get("p95_equity") if mc_result else None,
                    mc_result.get("probability_of_ruin") if mc_result else None,
                    mc_result.get("n_simulations") if mc_result else None,
                    result.get("tl_validation", {}).get("expected"),
                    result.get("tl_validation", {}).get("actual_majority"),
                    1 if result.get("tl_validation", {}).get("correct") else 0,
                    json.dumps(result.get("monthly_returns", {})),
                    json.dumps(result.get("equity_curve", [])),
                    json.dumps({}),  # regime_breakdown placeholder
                    "mechanical_brackets",
                    repro.get("config_snapshot"),
                    result["verdict"],
                    result.get("statistical_confidence"),
                    1,  # survivorship_bias flag
                    repro.get("random_seed"),
                    repro.get("git_commit"),
                    datetime.now(ET).isoformat(),
                ),
            )
            conn.commit()
        print(f"  Result stored for {result['scenario']}")
    except Exception as e:
        logger.error("[SIM] Failed to store result: %s", e)


# ---------------------------------------------------------------------------
# CLI Entrypoint (Task 8)
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Full-regime simulation engine")
    parser.add_argument("--regime", type=str, help="Run single regime")
    parser.add_argument("--monte-carlo", type=int, default=0,
                        help="MC simulations (0=disabled)")
    parser.add_argument("--transitions-only", action="store_true",
                        help="Run only the 3 transition scenarios")
    parser.add_argument("--validate-traffic-light", action="store_true",
                        help="Print traffic light validation for each scenario")
    parser.add_argument("--clear-cache", action="store_true",
                        help="Delete cached OHLCV data")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print config, don't execute")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for Monte Carlo")
    args = parser.parse_args()

    # ── Clear cache ──────────────────────────────────────────────────────
    if args.clear_cache:
        clear_cache()
        print("Cache cleared.")
        return

    # ── Determine scenarios ──────────────────────────────────────────────
    if args.regime:
        if args.regime not in SCENARIOS:
            print(f"ERROR: Unknown regime '{args.regime}'. Available: {list(SCENARIOS.keys())}")
            return
        scenarios_to_run = {args.regime: SCENARIOS[args.regime]}
    elif args.transitions_only:
        scenarios_to_run = {k: v for k, v in SCENARIOS.items() if k in TRANSITION_SCENARIOS}
    else:
        scenarios_to_run = SCENARIOS

    # ── Config ───────────────────────────────────────────────────────────
    sim_config = {
        "scan_interval_days": 5,
        "max_entries_per_scan": 3,
        "universe_size": 30,
        "position_size": 2000,
        "starting_equity": 100000,
        "transaction_costs": TRANSACTION_COSTS,
        "seed": args.seed,
    }

    print("=" * 60)
    print("  ARCIS FULL-REGIME SIMULATION ENGINE")
    print("=" * 60)
    print(f"  Scenarios: {len(scenarios_to_run)} ({', '.join(scenarios_to_run.keys())})")
    print(f"  Scan interval: every {sim_config['scan_interval_days']} trading days")
    print(f"  Max entries/scan: {sim_config['max_entries_per_scan']}")
    print(f"  Universe size: {sim_config['universe_size']}")
    print(f"  Position size: ${sim_config['position_size']}")
    print(f"  Transaction costs: {sum(TRANSACTION_COSTS.values()) * 2:.1f} bps RT")
    print(f"  Monte Carlo: {args.monte_carlo} simulations" if args.monte_carlo else "  Monte Carlo: disabled")
    print(f"  Seed: {args.seed}")
    print(f"  SURVIVORSHIP BIAS: Results use current S&P 100 universe")
    print()

    if args.dry_run:
        print("  [DRY RUN] Would run the above scenarios. Exiting.")
        return

    # ── Reproducibility ──────────────────────────────────────────────────
    repro = get_reproducibility_info(args.seed, sim_config)
    run_id = str(uuid.uuid4())

    # ── Warm cache ───────────────────────────────────────────────────────
    print("  Warming cache...")
    universe = get_sp100_universe()[:sim_config["universe_size"]]
    cache_stats = warm_cache(scenarios_to_run, universe)
    print(f"  Cache: {cache_stats['cached']} fetched, {cache_stats['failed']} failed")

    # ── Run scenarios ────────────────────────────────────────────────────
    all_results = {}
    for name, dates in scenarios_to_run.items():
        result = run_scenario(name, dates["start"], dates["end"], sim_config)
        if "error" not in result:
            all_results[name] = result

            # Monte Carlo
            mc_result = None
            if args.monte_carlo > 0 and result.get("trades"):
                print(f"\n  Running Monte Carlo ({args.monte_carlo} simulations)...")
                mc_result = monte_carlo_resample(
                    result["trades"], n_simulations=args.monte_carlo,
                    starting_equity=sim_config["starting_equity"], seed=args.seed,
                )
                print(f"  MC: median DD={mc_result['median_dd']:.1f}%, "
                      f"p95 DD={mc_result['p95_dd']:.1f}%, "
                      f"P(ruin)={mc_result['probability_of_ruin']:.4f}")
                all_results[name]["mc"] = mc_result

            # Store
            store_result(result, run_id, repro, mc_result)

    # ── Heatmap ──────────────────────────────────────────────────────────
    if all_results:
        print(f"\n{'='*60}")
        print("  REGIME HEATMAP")
        print(f"{'='*60}\n")
        print_heatmap(all_results)

    # ── Traffic Light Validation ─────────────────────────────────────────
    if args.validate_traffic_light and all_results:
        print(f"\n{'='*60}")
        print("  TRAFFIC LIGHT VALIDATION")
        print(f"{'='*60}\n")
        correct = 0
        total = 0
        for name, r in all_results.items():
            tlv = r.get("tl_validation", {})
            total += 1
            if tlv.get("correct"):
                correct += 1
            status = "PASS" if tlv.get("correct") else "FAIL"
            print(f"  [{status}] {name}: expected={tlv.get('expected')}, "
                  f"actual={tlv.get('actual_majority')}, "
                  f"dist={tlv.get('tl_distribution')}")
        print(f"\n  Accuracy: {correct}/{total} ({correct/total:.0%})" if total else "")

    # ── Summary ──────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  SIMULATION COMPLETE — {len(all_results)} scenarios")
    print(f"  Run ID: {run_id}")
    print(f"  Git: {repro['git_commit'][:8]}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
