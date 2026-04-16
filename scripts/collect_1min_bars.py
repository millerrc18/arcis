"""Collect 1-minute OHLCV bars for S&P 100 via yfinance.

Runs nightly via the watch loop overnight schedule (after market close,
after other collectors). Forward-fills the `minute_bars` table so Phase 6
intraday-desk work has historical data to study when the time comes.

Authority: docs/research/deep-research/intraday-desk-feasibility-report.md
Phase 1 decision #3 (begin storing 1-min bars now).

Important limitations:
- yfinance exposes only ~7 trading days of 1-minute history. If the
  collector misses a day, those bars are lost unless manually
  backfilled within 7 days. The overnight schedule wires this to run
  daily to minimize gap risk.
- Previous-trading-day data is available in 1-min granularity. The
  script targets "the trading day that most recently closed" by
  default, which on weekends/holidays is the previous business day.
- Rate-limited at 0.3s/ticker. 102 tickers * 0.3s ≈ 31s wall time per
  day, plus yfinance API latency.

Usage:
    python scripts/collect_1min_bars.py                  # previous trading day
    python scripts/collect_1min_bars.py --date 2026-04-15 # specific date
    python scripts/collect_1min_bars.py --days 3         # last N trading days
    python scripts/collect_1min_bars.py --dry-run        # show counts, skip writes
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DB_PATH  # noqa: E402
from src.universe.sp100 import get_sp100_universe, to_yfinance_ticker  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
RATE_LIMIT_SECONDS = 0.3


def _previous_trading_day(as_of: datetime | None = None) -> datetime:
    """Return the most recent weekday strictly before `as_of` (default: now ET).

    Does NOT attempt to skip US holidays — yfinance returns empty for
    holiday dates, which the collector handles gracefully. Keeping the
    function holiday-agnostic avoids a dependency on a trading-calendar lib.
    """
    now = as_of or datetime.now(ET)
    d = now.date() - timedelta(days=1)
    while d.weekday() >= 5:  # Sat=5, Sun=6
        d -= timedelta(days=1)
    return datetime(d.year, d.month, d.day, tzinfo=ET)


def _fetch_minute_bars(ticker: str, target_date: datetime) -> list[dict]:
    """Fetch 1-minute bars for a single ticker for a single trading day.

    Returns a list of dicts ready for INSERT. Empty list on any failure
    (logged as a warning; callers treat that as a skip).
    """
    try:
        import yfinance as yf
        start = target_date.strftime("%Y-%m-%d")
        end = (target_date + timedelta(days=1)).strftime("%Y-%m-%d")
        data = yf.download(
            to_yfinance_ticker(ticker),
            start=start, end=end, interval="1m",
            progress=False, auto_adjust=True, prepost=False,
        )
        if data.empty:
            return []
        # Flatten yfinance MultiIndex — single-ticker downloads return
        # tuple-keyed columns. Same fix pattern as SD#41 D2.
        if hasattr(data.columns, "get_level_values"):
            data.columns = data.columns.get_level_values(0)
        bars = []
        for idx, row in data.iterrows():
            bars.append({
                "ticker": ticker,
                "timestamp": idx.isoformat(),
                "open": float(row["Open"]) if "Open" in row else None,
                "high": float(row["High"]) if "High" in row else None,
                "low": float(row["Low"]) if "Low" in row else None,
                "close": float(row["Close"]) if "Close" in row else None,
                "volume": int(row["Volume"]) if "Volume" in row else None,
                "trade_count": None,  # yfinance does not expose this
            })
        return bars
    except Exception as exc:
        logger.warning("[1MIN] Fetch failed for %s on %s: %s",
                       ticker, target_date.date(), exc)
        return []


def _upsert_bars(conn: sqlite3.Connection, bars: list[dict]) -> int:
    """Idempotent upsert via INSERT OR REPLACE on the composite PK."""
    if not bars:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO minute_bars "
        "(ticker, timestamp, open, high, low, close, volume, trade_count) "
        "VALUES (:ticker, :timestamp, :open, :high, :low, :close, :volume, :trade_count)",
        bars,
    )
    return len(bars)


def collect(
    target_dates: list[datetime],
    dry_run: bool = False,
    rate_limit_seconds: float = RATE_LIMIT_SECONDS,
) -> dict:
    """Collect bars for every S&P 100 ticker across the given dates.

    Returns summary dict: tickers, dates, bars_collected, empty_ticker_days.
    """
    universe = get_sp100_universe()
    total_bars = 0
    empty_ticker_days = 0

    with sqlite3.connect(DB_PATH) as conn:
        for target in target_dates:
            logger.info("[1MIN] Collecting %s across %d tickers",
                        target.date(), len(universe))
            day_bars = 0
            for ticker in universe:
                bars = _fetch_minute_bars(ticker, target)
                if not bars:
                    empty_ticker_days += 1
                    time.sleep(rate_limit_seconds)
                    continue
                if dry_run:
                    logger.info("[1MIN DRY] %s %s: %d bars",
                                ticker, target.date(), len(bars))
                else:
                    day_bars += _upsert_bars(conn, bars)
                time.sleep(rate_limit_seconds)
            if not dry_run:
                conn.commit()
                total_bars += day_bars
                logger.info("[1MIN] %s complete: %d bars written",
                            target.date(), day_bars)

    # Storage estimate — empirical after first real run.
    if not dry_run and total_bars > 0:
        avg_bytes_per_bar = 60
        mb_today = total_bars * avg_bytes_per_bar / (1024 * 1024)
        mb_per_year = mb_today * 252  # trading days/yr
        logger.info(
            "[1MIN] Storage: %.2f MB written, projected %.0f MB/year",
            mb_today, mb_per_year,
        )

    result = {
        "tickers": len(universe),
        "dates": len(target_dates),
        "bars_collected": total_bars,
        "empty_ticker_days": empty_ticker_days,
    }
    logger.info("[1MIN] Collection complete: %s", result)
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", type=str, default=None,
                        help="Specific date YYYY-MM-DD (default: previous trading day)")
    parser.add_argument("--days", type=int, default=1,
                        help="Backfill last N trading days (default: 1)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch + log counts; skip DB writes")
    return parser.parse_args()


def _resolve_target_dates(args: argparse.Namespace) -> list[datetime]:
    """Convert CLI args into a list of target trading-day datetimes."""
    if args.date:
        d = datetime.fromisoformat(args.date).replace(tzinfo=ET)
        return [d]
    dates = []
    current = _previous_trading_day()
    for _ in range(args.days):
        dates.append(current)
        current = _previous_trading_day(current)
    return dates


if __name__ == "__main__":
    args = _parse_args()
    targets = _resolve_target_dates(args)
    collect(targets, dry_run=args.dry_run)
