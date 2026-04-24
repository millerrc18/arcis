"""Summary analytics -- daily OHLCV rollups, biggest movers, volume analysis."""

from __future__ import annotations

import pandas as pd

from .types import (
    DailySummary,
    DailySummaryResult,
    Mover,
    BiggestMoversResult,
    VolumeStats,
    VolumeAnalysisResult,
)


def daily_summary(df: pd.DataFrame, tickers: list[str] | None = None) -> DailySummaryResult:
    """Aggregate intraday bars into daily OHLCV summaries per ticker.

    Parameters
    ----------
    df:
        Bar DataFrame with columns: timestamp, open, high, low, close,
        volume, vwap, num_transactions, ticker.
    tickers:
        Optional list of tickers to include.  ``None`` means all tickers.

    Returns
    -------
    DailySummaryResult
        Per-ticker, per-date aggregation with daily return and intraday range.
    """
    work = df.copy()
    if tickers is not None:
        work = work[work["ticker"].isin(tickers)]

    work["date"] = pd.to_datetime(work["timestamp"]).dt.date.astype(str)

    summaries: list[DailySummary] = []

    for (ticker, date_str), grp in work.groupby(["ticker", "date"], sort=True):
        grp_sorted = grp.sort_values("timestamp")
        first_open = grp_sorted["open"].iloc[0]
        last_close = grp_sorted["close"].iloc[-1]
        max_high = grp_sorted["high"].max()
        min_low = grp_sorted["low"].min()
        total_vol = grp_sorted["volume"].sum()
        mean_vwap = grp_sorted["vwap"].mean()
        bar_count = len(grp_sorted)

        daily_return = (last_close - first_open) / first_open if first_open != 0 else 0.0
        intraday_range = (max_high - min_low) / first_open if first_open != 0 else 0.0

        summaries.append(
            DailySummary(
                ticker=str(ticker),
                date=str(date_str),
                open=float(first_open),
                high=float(max_high),
                low=float(min_low),
                close=float(last_close),
                volume=float(total_vol),
                vwap=float(mean_vwap),
                bar_count=int(bar_count),
                daily_return=float(daily_return),
                intraday_range=float(intraday_range),
            )
        )

    unique_tickers = {s.ticker for s in summaries}
    unique_dates = {s.date for s in summaries}

    return DailySummaryResult(
        summaries=summaries,
        ticker_count=len(unique_tickers),
        date_count=len(unique_dates),
    )


def biggest_movers(df: pd.DataFrame, date_str: str, n: int = 10) -> BiggestMoversResult:
    """Find the biggest gainers and losers on a specific trading date.

    Parameters
    ----------
    df:
        Bar DataFrame.
    date_str:
        Target date as ``"YYYY-MM-DD"``.
    n:
        Number of top gainers / bottom losers to return.

    Returns
    -------
    BiggestMoversResult
        Top *n* gainers (descending return) and bottom *n* losers (ascending).
    """
    work = df.copy()
    work["date"] = pd.to_datetime(work["timestamp"]).dt.date.astype(str)
    day = work[work["date"] == date_str]

    movers: list[dict] = []
    for ticker, grp in day.groupby("ticker"):
        grp_sorted = grp.sort_values("timestamp")
        first_open = grp_sorted["open"].iloc[0]
        last_close = grp_sorted["close"].iloc[-1]
        total_vol = grp_sorted["volume"].sum()
        ret = (last_close - first_open) / first_open if first_open != 0 else 0.0
        movers.append(
            {
                "ticker": str(ticker),
                "return_pct": float(ret),
                "volume": float(total_vol),
                "close": float(last_close),
            }
        )

    # Sort descending by return for gainers
    movers.sort(key=lambda m: m["return_pct"], reverse=True)
    gainers = [Mover(**m) for m in movers[:n]]

    # Sort ascending by return for losers
    movers.sort(key=lambda m: m["return_pct"])
    losers = [Mover(**m) for m in movers[:n]]

    return BiggestMoversResult(gainers=gainers, losers=losers, date=date_str, n=n)


def volume_analysis(df: pd.DataFrame, tickers: list[str] | None = None) -> VolumeAnalysisResult:
    """Compute per-ticker volume statistics across all bars.

    Parameters
    ----------
    df:
        Bar DataFrame.
    tickers:
        Optional list of tickers to include.

    Returns
    -------
    VolumeAnalysisResult
        Per-ticker total, average, max, and standard deviation of volume.
    """
    work = df.copy()
    if tickers is not None:
        work = work[work["ticker"].isin(tickers)]

    stats: list[VolumeStats] = []
    for ticker, grp in work.groupby("ticker"):
        vol = grp["volume"]
        stats.append(
            VolumeStats(
                ticker=str(ticker),
                total_volume=float(vol.sum()),
                avg_volume=float(vol.mean()),
                max_volume=float(vol.max()),
                volume_std=float(vol.std(ddof=1)) if len(vol) > 1 else 0.0,
            )
        )

    timestamps = pd.to_datetime(work["timestamp"])
    min_date = timestamps.min().strftime("%Y-%m-%d") if len(timestamps) else ""
    max_date = timestamps.max().strftime("%Y-%m-%d") if len(timestamps) else ""
    date_range = f"{min_date} to {max_date}"

    return VolumeAnalysisResult(stats=stats, date_range=date_range)
