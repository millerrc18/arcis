"""Simulation engine core — scenario runner, storage, and analysis.

Extracted from scripts/simulation_engine.py for module-level importability.
The script remains a thin CLI wrapper around these functions.

Called by: scheduler.watch, scripts/simulation_engine.py
Calls: simulation.cache, simulation.monte_carlo, attribution.logger,
       features.indicators, universe.sp100
Owns tables: simulation_results
"""

import json
import logging
import sqlite3
import subprocess
import sys
import uuid
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from src.attribution.logger import simulate_mechanical_outcome
from src.config import DB_PATH
from src.utils.db import connect_db
from src.features.indicators import compute_atr
from src.simulation.cache import (
    _add_days,
    _subtract_days,
    fetch_cached_ohlcv,
)
from src.universe.sp100 import get_sp100_universe

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# ─── 13 Default Scenarios ────────────────────────────────────────────────────

SCENARIOS = {
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
    "bull_to_bear": {"start": "2020-01-01", "end": "2020-04-30", "label": "Bull-to-Bear"},
    "bear_to_bull": {"start": "2020-03-01", "end": "2020-08-31", "label": "Bear-to-Bull"},
    "low_to_high_vol": {"start": "2018-01-01", "end": "2018-04-30", "label": "Low-to-High Vol"},
}

TRANSITION_SCENARIOS = {"bull_to_bear", "bear_to_bull", "low_to_high_vol"}

# ─── Transaction Cost Model ─────────────────────────────────────────────────

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


# ─── VIX Regime Classification ──────────────────────────────────────────────

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


# ─── SPY Benchmark ──────────────────────────────────────────────────────────

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


# ─── Traffic Light Validation ────────────────────────────────────────────────

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


# ─── Verdict Logic ───────────────────────────────────────────────────────────

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


# ─── Heatmap Output ─────────────────────────────────────────────────────────

def print_heatmap(results: dict[str, dict]):
    """Print the regime heatmap to console."""
    VERDICT_ICONS = {"edge": "[OK]", "neutral": "[--]", "marginal": "[!!]",
                     "bleeds": "[XX]", "insufficient": "[??]"}
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


# ─── Reproducibility ────────────────────────────────────────────────────────

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


# ─── Core Scenario Runner ───────────────────────────────────────────────────

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
    import numpy as np
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

        # Rank candidates by momentum
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

    # Sharpe ratio (annualized from weekly returns).
    # F-2 / Sprint-0 wave-4a: route through canonical compute_sharpe with
    # `periods_per_year=52` (weekly) and `ddof=0` (preserves legacy
    # `np.std` default — bumping to ddof=1 would silently change every
    # historical simulation report). None → 0 to match legacy contract.
    from src.analytics.canonical_sharpe import compute_sharpe
    if len(trades) > 1:
        returns = [t["pnl_pct"] for t in trades]
        sharpe_canonical = compute_sharpe(returns, periods_per_year=52, ddof=0)
        sharpe = 0.0 if sharpe_canonical is None else float(sharpe_canonical)
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


# ─── Storage ─────────────────────────────────────────────────────────────────

def store_result(result: dict, run_id: str, seed: int, config: dict,
                 db_path: str = DB_PATH) -> None:
    """Store simulation result in database."""
    repro = get_reproducibility_info(seed, config)

    # Traffic light validation
    tl_states = result.get("tl_states", [])
    tl_val = validate_traffic_light(result["scenario"], tl_states)

    try:
        with connect_db(db_path) as conn:
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
