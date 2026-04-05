#!/usr/bin/env python3
"""Historical stress test — replay through crisis periods.

When to run:
    Ad-hoc or weekly (Sunday evening via watch loop). Run manually before
    any allocator due-diligence meeting or after changing bracket parameters.

What it reads:
    - S&P 100 universe (src/universe/sp100.py)
    - yfinance OHLCV data for SPY, VIX, and each universe ticker
    - ATR indicator computation (src/features/indicators.py)
    - Mechanical bracket simulation (src/attribution/logger.py)

What it writes:
    - stress_test_results table in SQLite (one row per scenario)

Prerequisites:
    - yfinance installed and network access to Yahoo Finance
    - Database exists at the path configured in src/config.DB_PATH

Runs pure ranker + mechanical brackets (no LLM) through 3 crisis scenarios
to answer the allocator's #1 due diligence question: "How would this
strategy have performed in a crash?"

Usage:
    python scripts/stress_test.py                    # All 3 scenarios
    python scripts/stress_test.py --scenario 2020    # Single scenario
    python scripts/stress_test.py --dry-run           # Print config only

Scenarios:
    2008_financial_crisis: Sep 2008 - Mar 2009
    2020_covid_crash:      Feb 2020 - Apr 2020
    2022_bear_market:      Jan 2022 - Oct 2022
"""

import argparse
import json
import logging
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.attribution.logger import simulate_mechanical_outcome
from src.config import DB_PATH
from src.features.indicators import compute_atr

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

SCENARIOS = {
    "2008_financial_crisis": {"start": "2008-09-01", "end": "2009-03-31"},
    "2020_covid_crash": {"start": "2020-02-01", "end": "2020-04-30"},
    "2022_bear_market": {"start": "2022-01-01", "end": "2022-10-31"},
}

# Regime-aware bracket parameters (from full-strategy-RESULTS.md Deliverable 3).
# In extreme VIX regimes, wider stops avoid whipsaw exits but the shorter
# timeout limits drawdown duration — a deliberate tradeoff from backtesting.
REGIME_BRACKETS = {
    "low":      {"stop_atr_mult": 2.0, "target_atr_mult": 2.0, "timeout_days": 8},
    "normal":   {"stop_atr_mult": 2.0, "target_atr_mult": 2.0, "timeout_days": 8},
    "elevated": {"stop_atr_mult": 2.5, "target_atr_mult": 2.5, "timeout_days": 7},
    "extreme":  {"stop_atr_mult": 3.0, "target_atr_mult": 3.0, "timeout_days": 5},
}

# Fallback fixed brackets (used when ATR unavailable).
# These are intentionally conservative — the asymmetric 3% target / 5% stop
# reflects that without ATR we cannot size to volatility, so we widen stops
# to avoid premature exit from normal noise.
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


def get_stress_test_universe(scenario_start: str) -> list[str]:
    """Get universe of tickers with available data for test period.

    Filters to tickers that actually have OHLCV data in the test range.
    Survivorship bias is noted but not eliminated.
    """
    from src.universe.sp100 import get_sp100_universe, to_yfinance_ticker
    import yfinance as yf

    all_tickers = get_sp100_universe()
    valid = []
    excluded = 0

    for ticker in all_tickers:
        try:
            data = yf.download(
                to_yfinance_ticker(ticker), start=scenario_start,
                end=(datetime.strptime(scenario_start, "%Y-%m-%d") + timedelta(days=5)).strftime("%Y-%m-%d"),
                progress=False, auto_adjust=True,
            )
            if data is not None and len(data) >= 1:
                valid.append(ticker)
            else:
                excluded += 1
        except Exception:
            excluded += 1

    logger.warning("[STRESS] Excluded %d tickers (no data for %s). "
                   "SURVIVORSHIP BIAS: results may overstate performance.",
                   excluded, scenario_start)
    return valid


def run_scenario(name: str, start: str, end: str) -> dict:
    """Run a single stress test scenario.

    For each trading day: simulate entering top-ranked tickers with
    mechanical brackets and track outcomes.
    """
    import yfinance as yf
    from src.universe.sp100 import to_yfinance_ticker

    print(f"\n{'='*50}")
    print(f"  SCENARIO: {name}")
    print(f"  Period: {start} -> {end}")
    print(f"{'='*50}\n")

    # Get trading days
    spy_data = yf.download("SPY", start=start, end=end, progress=False, auto_adjust=True)
    if spy_data is None or spy_data.empty:
        return {"error": "No SPY data for period", "scenario": name}

    trading_days = [d.strftime("%Y-%m-%d") for d in spy_data.index]
    print(f"  Trading days: {len(trading_days)}")

    # Fetch VIX data for regime-aware brackets
    vix_data = None
    try:
        vix_raw = yf.download("^VIX", start=start, end=end, progress=False, auto_adjust=True)
        if vix_raw is not None and not vix_raw.empty:
            vix_data = {d.strftime("%Y-%m-%d"): float(v)
                        for d, v in zip(vix_raw.index, vix_raw["Close"])}
            print(f"  VIX data: {len(vix_data)} days loaded")
    except Exception as e:
        logger.warning("[STRESS] VIX fetch failed, using fixed brackets: %s", e)

    # Get universe (with survivorship bias caveat)
    universe = get_stress_test_universe(start)
    print(f"  Universe: {len(universe)} tickers")

    # Track results
    trades = []
    equity_curve = [100000.0]  # Start with $100K (matches live starting capital)
    monthly_returns = {}
    regime_stats = {}  # {regime: {"trades": 0, "wins": 0, "stops": 0}}

    current_equity = 100000.0
    # Fixed $2K per position (2% of capital). This matches the live risk
    # governor's planned_risk_pct_max = 2%, keeping simulation comparable.
    position_size = 2000

    # Scan every 5 trading days (not daily) to simulate realistic entry frequency.
    # Weekly-ish cadence also keeps the yfinance API call count manageable.
    for day_idx in range(0, len(trading_days), 5):
        day = trading_days[day_idx]
        if day_idx % 20 == 0:
            print(f"  Processing: {day} ({day_idx}/{len(trading_days)} days)")

        # Determine VIX regime for this day
        vix_value = vix_data.get(day) if vix_data else None
        regime = classify_vix_regime(vix_value)
        brackets = REGIME_BRACKETS[regime]

        # Pick top 3 tickers by simple momentum (lowest 5-day return = oversold).
        # This is a mean-reversion heuristic that matches the live scan strategy.
        candidates = []
        for ticker in universe[:30]:  # Limit to 30 for speed (full universe takes hours)
            try:
                hist_start = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
                hist = yf.download(to_yfinance_ticker(ticker), start=hist_start, end=day, progress=False, auto_adjust=True)
                if hist is not None and len(hist) >= 15:
                    ret_5d = (hist["Close"].iloc[-1] / hist["Close"].iloc[-5] - 1)
                    # Compute ATR for regime-aware stop sizing
                    import pandas as pd
                    atr = compute_atr(
                        pd.Series(hist["High"].values.flatten()),
                        pd.Series(hist["Low"].values.flatten()),
                        pd.Series(hist["Close"].values.flatten()),
                        period=14,
                    )
                    candidates.append((ticker, float(ret_5d), float(hist["Close"].iloc[-1]), atr))
            except Exception:
                continue

        if not candidates:
            continue

        # Sort by 5d return ascending (most oversold first)
        candidates.sort(key=lambda x: x[1])

        for ticker, ret_5d, entry_price, atr in candidates[:3]:
            # Regime-aware bracket sizing (ATR-based if available)
            if atr > 0:
                stop_price = entry_price - (atr * brackets["stop_atr_mult"])
                target_price = entry_price + (atr * brackets["target_atr_mult"])
                timeout = brackets["timeout_days"]
            else:
                # Fallback to fixed percentages
                target_price = entry_price * (1 + TARGET_PCT)
                stop_price = entry_price * (1 - STOP_PCT)
                timeout = TIMEOUT_DAYS

            # Fetch forward data for outcome simulation
            fwd_start = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            fwd_end = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=timeout + 2)).strftime("%Y-%m-%d")
            try:
                fwd_data = yf.download(to_yfinance_ticker(ticker), start=fwd_start, end=fwd_end, progress=False, auto_adjust=True)
                if fwd_data is None or fwd_data.empty:
                    continue
                ohlcv = fwd_data.reset_index().to_dict("records")
            except Exception:
                continue

            outcome, exit_price, days_held = simulate_mechanical_outcome(
                entry_price, stop_price, target_price, timeout, ohlcv,
            )

            pnl_pct = (exit_price - entry_price) / entry_price * 100
            pnl_dollars = pnl_pct / 100 * position_size
            current_equity += pnl_dollars

            trades.append({
                "date": day,
                "ticker": ticker,
                "entry": entry_price,
                "exit": exit_price,
                "outcome": outcome,
                "pnl_pct": round(pnl_pct, 2),
                "days_held": days_held,
                "regime": regime,
                "vix": vix_value,
                "atr_mult": brackets["stop_atr_mult"] if atr > 0 else None,
            })

            # Track regime stats
            if regime not in regime_stats:
                regime_stats[regime] = {"trades": 0, "wins": 0, "losses": 0, "stops": 0}
            regime_stats[regime]["trades"] += 1
            if outcome == "win":
                regime_stats[regime]["wins"] += 1
            elif outcome == "loss":
                regime_stats[regime]["losses"] += 1
                regime_stats[regime]["stops"] += 1

            # Track monthly returns
            month_key = day[:7]  # YYYY-MM
            if month_key not in monthly_returns:
                monthly_returns[month_key] = 0.0
            monthly_returns[month_key] += pnl_pct

        equity_curve.append(round(current_equity, 2))

    # Compute summary metrics
    total_trades = len(trades)
    wins = sum(1 for t in trades if t["outcome"] == "win")
    losses = sum(1 for t in trades if t["outcome"] == "loss")
    timeouts = sum(1 for t in trades if t["outcome"] == "timeout")

    win_rate = wins / total_trades if total_trades > 0 else 0
    total_pnl_pct = sum(t["pnl_pct"] for t in trades)

    # Max drawdown — the single most important crisis metric.
    # Allocators compare this to benchmark drawdowns during the same period.
    peak = equity_curve[0]
    max_dd = 0
    max_dd_duration = 0
    dd_start = 0
    for i, eq in enumerate(equity_curve):
        if eq > peak:
            peak = eq
            dd_start = i
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd
            max_dd_duration = i - dd_start

    # Calmar ratio: annualized return / max drawdown.
    # Industry rule of thumb: Calmar > 1.0 is acceptable, > 2.0 is strong.
    days_in_test = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
    annualized_return = (total_pnl_pct / 100) * (365 / max(days_in_test, 1)) * 100
    calmar = annualized_return / max_dd if max_dd > 0 else 0

    # Build regime breakdown with stop analysis
    regime_breakdown = {}
    for r, stats in regime_stats.items():
        regime_breakdown[r] = {
            "trades": stats["trades"],
            "win_rate": round(stats["wins"] / stats["trades"], 3) if stats["trades"] > 0 else 0,
            "stop_trigger_pct": round(stats["stops"] / stats["trades"] * 100, 1) if stats["trades"] > 0 else 0,
            "atr_mult": REGIME_BRACKETS[r]["stop_atr_mult"],
        }

    result = {
        "scenario": name,
        "start_date": start,
        "end_date": end,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "timeouts": timeouts,
        "win_rate": round(win_rate, 3),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "max_drawdown_duration_days": max_dd_duration,
        "calmar_ratio": round(calmar, 3),
        "monthly_returns": monthly_returns,
        "equity_curve": equity_curve,
        "regime_breakdown": regime_breakdown,
        "universe_size": len(universe),
        # Explicitly flagged so downstream consumers (dashboard, reports) can
        # display a caveat. True survivorship-bias removal requires historical
        # index membership data from scrape_sp_changes.py.
        "survivorship_bias": True,
    }

    print(f"\n  Results: {total_trades} trades | WR: {win_rate:.1%} | "
          f"DD: {max_dd:.1f}% | Calmar: {calmar:.2f}")
    if regime_breakdown:
        print(f"  Regime breakdown:")
        for r, s in sorted(regime_breakdown.items()):
            print(f"    {r}: {s['trades']} trades, WR={s['win_rate']:.0%}, "
                  f"stop trigger={s['stop_trigger_pct']:.0f}% (ATR×{s['atr_mult']})")

    return result


def store_result(result: dict, db_path: str = DB_PATH) -> None:
    """Store stress test result in database."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO stress_test_results "
                "(result_id, scenario, start_date, end_date, total_trades, "
                "win_rate, total_pnl_pct, max_drawdown_pct, max_drawdown_duration_days, "
                "calmar_ratio, monthly_returns_json, regime_breakdown_json, "
                "equity_curve_json, model_version, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    result["scenario"],
                    result["start_date"],
                    result["end_date"],
                    result["total_trades"],
                    result["win_rate"],
                    result["total_pnl_pct"],
                    result["max_drawdown_pct"],
                    result["max_drawdown_duration_days"],
                    result["calmar_ratio"],
                    json.dumps(result.get("monthly_returns", {})),
                    json.dumps(result.get("regime_breakdown", {})),
                    json.dumps(result.get("equity_curve", [])),
                    result.get("model_version", "mechanical_brackets"),
                    datetime.now(ET).isoformat(),
                ),
            )
            conn.commit()
        print(f"  Result stored in DB for {result['scenario']}")
    except Exception as e:
        logger.error("[STRESS] Failed to store result: %s", e)


def main():
    parser = argparse.ArgumentParser(description="Historical stress test")
    parser.add_argument("--scenario", type=str, help="Run single scenario (2008/2020/2022)")
    parser.add_argument("--dry-run", action="store_true", help="Print config only")
    args = parser.parse_args()

    print("=" * 50)
    print("  ARCIS HISTORICAL STRESS TEST")
    print("=" * 50)
    print(f"  Scenarios: {list(SCENARIOS.keys())}")
    print(f"  Fallback: {TARGET_PCT:.0%} target / {STOP_PCT:.0%} stop / {TIMEOUT_DAYS}d timeout")
    print(f"  Regime brackets (ATR-based):")
    for regime, params in REGIME_BRACKETS.items():
        print(f"    {regime:>10}: {params['stop_atr_mult']}x ATR stop / "
              f"{params['target_atr_mult']}x ATR target / {params['timeout_days']}d")
    print(f"  SURVIVORSHIP BIAS: Results use current S&P 100 universe")
    print()

    if args.dry_run:
        print("  [DRY RUN] Would run the above scenarios. Exiting.")
        return

    scenarios_to_run = SCENARIOS
    if args.scenario:
        key = f"{args.scenario}_" if not args.scenario.startswith("20") else args.scenario
        matches = {k: v for k, v in SCENARIOS.items() if args.scenario in k}
        if not matches:
            print(f"  ERROR: Unknown scenario '{args.scenario}'")
            return
        scenarios_to_run = matches

    for name, dates in scenarios_to_run.items():
        result = run_scenario(name, dates["start"], dates["end"])
        if "error" not in result:
            store_result(result)

    print("\n" + "=" * 50)
    print("  STRESS TEST COMPLETE")
    print("=" * 50)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
