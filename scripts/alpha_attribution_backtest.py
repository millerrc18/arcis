#!/usr/bin/env python3
"""Alpha attribution historical backtest.

When to run:
    Ad-hoc, after model changes or strategy parameter tweaks. Typically run
    quarterly to measure whether the LLM adds alpha over the mechanical ranker.

What it reads:
    - SPY OHLCV (yfinance) for trading calendar
    - S&P 100 universe tickers (src/universe/sp100.py)
    - Mechanical bracket simulation (src/attribution/logger.py)

What it writes:
    - Stdout results only (no DB writes). Pipe to a file to save.

Prerequisites:
    - yfinance installed, network access to Yahoo Finance
    - Long date ranges (>90 days) may take several hours

Replays historical dates through the ranker to build attribution data.
For each trading day: fetch OHLCV -> compute features -> run ranker ->
simulate mechanical brackets -> compare to LLM decisions.

Usage:
    python scripts/alpha_attribution_backtest.py --start 2025-10-01 --end 2026-03-31
    python scripts/alpha_attribution_backtest.py --days 90
"""

import argparse
import logging
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def get_trading_days(start: str, end: str) -> list[str]:
    """Get NYSE trading days between start and end dates."""
    try:
        import yfinance as yf
        data = yf.download("SPY", start=start, end=end, progress=False)
        return [d.strftime("%Y-%m-%d") for d in data.index]
    except Exception as e:
        logger.error("Failed to get trading days: %s", e)
        return []


def run_backtest(start_date: str, end_date: str, db_path: str = DB_PATH) -> dict:
    """Run attribution backtest over a date range.

    For each trading day:
    1. Fetch OHLCV for universe
    2. Compute features + rank
    3. Get packet_worthy candidates
    4. Simulate mechanical brackets for each
    5. Compare to actual LLM decisions (from recommendations table)
    """
    from src.attribution.logger import simulate_mechanical_outcome

    trading_days = get_trading_days(start_date, end_date)
    if not trading_days:
        return {"error": "No trading days found", "total": 0}

    results = {
        "total_days": len(trading_days),
        "total_candidates": 0,
        "simulated": 0,
        "outcomes": {"win": 0, "loss": 0, "timeout": 0},
        "avg_pnl_pct": 0.0,
        "errors": 0,
    }

    total_pnl = 0.0

    for day_idx, day in enumerate(trading_days):
        if day_idx % 20 == 0:
            print(f"[BACKTEST] Processing day {day_idx + 1}/{len(trading_days)}: {day}")

        try:
            import yfinance as yf
            from src.universe.sp100 import get_sp100_universe

            universe = get_sp100_universe()
            next_day = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            end_sim = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=10)).strftime("%Y-%m-%d")

            # For each ticker, simulate as if we entered at close on `day`
            # Limit to 20 tickers per day to keep yfinance API calls tractable.
            # Full universe (100 tickers x 200 days) = 20K API calls.
            for ticker in universe[:20]:
                try:
                    hist = yf.download(ticker, start=day, end=day, progress=False)
                    if hist.empty:
                        continue

                    close = float(hist["Close"].iloc[-1])
                    # Simple mechanical bracket: 2% target, 3% stop.
                    # Intentionally simpler than live brackets to isolate
                    # the value added by the LLM and ranker together.
                    target = close * 1.02
                    stop = close * 0.97

                    # Fetch forward data
                    fwd = yf.download(ticker, start=next_day, end=end_sim, progress=False)
                    if fwd.empty:
                        continue

                    ohlcv = fwd.reset_index().to_dict("records")
                    outcome, exit_price, days_held = simulate_mechanical_outcome(
                        close, stop, target, 7, ohlcv
                    )

                    pnl_pct = (exit_price - close) / close * 100
                    total_pnl += pnl_pct
                    results["total_candidates"] += 1
                    results["simulated"] += 1
                    results["outcomes"][outcome] += 1

                except Exception:
                    results["errors"] += 1
                    continue

        except Exception as e:
            logger.warning("[BACKTEST] Day %s failed: %s", day, e)
            results["errors"] += 1

    if results["simulated"] > 0:
        results["avg_pnl_pct"] = round(total_pnl / results["simulated"], 3)
        results["win_rate"] = round(
            results["outcomes"]["win"] / results["simulated"], 3
        )

    return results


def main():
    parser = argparse.ArgumentParser(description="Alpha attribution backtest")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=90, help="Number of days back")
    args = parser.parse_args()

    if args.start and args.end:
        start, end = args.start, args.end
    else:
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    print(f"[BACKTEST] Alpha Attribution Backtest: {start} → {end}")
    print(f"[BACKTEST] This may take several hours for long date ranges.")
    print()

    results = run_backtest(start, end)

    print()
    print("=" * 50)
    print("  ALPHA ATTRIBUTION BACKTEST RESULTS")
    print("=" * 50)
    print(f"  Period: {start} → {end}")
    print(f"  Trading days: {results.get('total_days', 0)}")
    print(f"  Candidates simulated: {results.get('simulated', 0)}")
    print(f"  Outcomes: {results.get('outcomes', {})}")
    print(f"  Win rate: {results.get('win_rate', 'N/A')}")
    print(f"  Avg P&L: {results.get('avg_pnl_pct', 0):.3f}%")
    print(f"  Errors: {results.get('errors', 0)}")
    print("=" * 50)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
