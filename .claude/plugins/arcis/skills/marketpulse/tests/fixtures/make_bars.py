"""Synthetic OHLCV DataFrame builder for analytics tests.

Generates data matching the schema returned by ``CacheManager.get_bars_df()``:
columns: timestamp, open, high, low, close, volume, vwap, num_transactions, ticker
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def make_bars_df(
    tickers: list[str] | str = "AAPL",
    start: str = "2022-01-03",
    days: int = 5,
    bars_per_day: int = 390,
    seed: int = 42,
    base_price: float = 150.0,
    base_volume: float = 1_000_000.0,
) -> pd.DataFrame:
    """Build a synthetic bar DataFrame for testing analytics functions.

    Parameters
    ----------
    tickers:
        Single ticker string or list of tickers.
    start:
        ISO date string for the first trading day.
    days:
        Number of trading days to generate.
    bars_per_day:
        Number of 1-minute bars per trading day (default 390 = full session).
    seed:
        Base random seed.  Each ticker gets ``seed + i * 1000``.
    base_price:
        Starting price for the first bar.
    base_volume:
        Mean volume per bar.

    Returns
    -------
    pd.DataFrame
        Columns: timestamp, open, high, low, close, volume, vwap,
        num_transactions, ticker.  Sorted by (ticker, timestamp).
    """
    if isinstance(tickers, str):
        tickers = [tickers]

    frames: list[pd.DataFrame] = []

    for i, ticker in enumerate(tickers):
        rng = np.random.RandomState(seed + i * 1000)
        rows: list[dict] = []

        current_date = datetime.strptime(start, "%Y-%m-%d")
        price = base_price
        days_generated = 0

        while days_generated < days:
            # Skip weekends
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue

            # Market open at 14:30 UTC (9:30 ET)
            market_open = current_date.replace(
                hour=14, minute=30, second=0, microsecond=0
            )

            for bar_idx in range(bars_per_day):
                ts = market_open + timedelta(minutes=bar_idx)

                # ~0.1% std per bar return
                ret = rng.normal(0.0, 0.001)
                bar_open = price
                bar_close = bar_open * (1 + ret)

                # High/low spread around open-close range
                spread = abs(bar_close - bar_open) + bar_open * rng.uniform(0.0002, 0.001)
                bar_high = max(bar_open, bar_close) + spread * rng.uniform(0.1, 0.5)
                bar_low = min(bar_open, bar_close) - spread * rng.uniform(0.1, 0.5)

                # Volume with some noise
                vol = max(100, rng.normal(base_volume / bars_per_day, base_volume / bars_per_day * 0.3))

                # VWAP approximation: weighted average of OHLC
                vwap = (bar_open + bar_high + bar_low + bar_close) / 4.0

                num_tx = max(1, int(rng.poisson(50)))

                rows.append({
                    "timestamp": ts,
                    "open": round(bar_open, 4),
                    "high": round(bar_high, 4),
                    "low": round(bar_low, 4),
                    "close": round(bar_close, 4),
                    "volume": round(vol, 2),
                    "vwap": round(vwap, 4),
                    "num_transactions": num_tx,
                    "ticker": ticker,
                })

                price = bar_close

            days_generated += 1
            current_date += timedelta(days=1)

        df = pd.DataFrame(rows)
        frames.append(df)

    result = pd.concat(frames, ignore_index=True)
    result = result.sort_values(["ticker", "timestamp"]).reset_index(drop=True)
    return result
