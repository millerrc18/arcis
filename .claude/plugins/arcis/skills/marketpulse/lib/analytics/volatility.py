"""Volatility analytics -- realized vol, intraday profile, vol surface, Garman-Klass."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .types import (
    TickerVolatility,
    RealizedVolatilityResult,
    IntradayVolBucket,
    IntradayVolProfileResult,
    VolSurfacePoint,
    VolSurfaceResult,
    GarmanKlassResult,
)


def realized_volatility(
    df: pd.DataFrame,
    window: str = "1d",
    tickers: list[str] | None = None,
) -> RealizedVolatilityResult:
    """Compute realized volatility from close-to-close log returns.

    Parameters
    ----------
    df:
        Bar DataFrame with columns: timestamp, open, high, low, close,
        volume, vwap, num_transactions, ticker.
    window:
        ``"1d"`` uses daily closing prices (last close per day per ticker).
        ``"intraday"`` uses bar-level log returns.
    tickers:
        Optional list of tickers to include.  ``None`` means all tickers.

    Returns
    -------
    RealizedVolatilityResult
        Per-ticker annualized and daily volatility.
    """
    work = df.copy()
    if tickers is not None:
        work = work[work["ticker"].isin(tickers)]

    volatilities: list[TickerVolatility] = []

    for ticker, grp in work.groupby("ticker"):
        grp = grp.sort_values("timestamp")

        if window == "1d":
            # Get last close per trading day
            grp = grp.copy()
            grp["_date"] = pd.to_datetime(grp["timestamp"]).dt.date
            daily_closes = grp.groupby("_date")["close"].last()
            log_returns = np.log(daily_closes / daily_closes.shift(1)).dropna()
            daily_vol = float(log_returns.std(ddof=1)) if len(log_returns) > 1 else 0.0
            annualized_vol = daily_vol * np.sqrt(252)
            num_periods = len(log_returns)
        else:
            # Intraday: bar-level log returns
            closes = grp["close"]
            log_returns = np.log(closes / closes.shift(1)).dropna()
            bar_vol = float(log_returns.std(ddof=1)) if len(log_returns) > 1 else 0.0

            # Estimate bars per day from data
            grp_copy = grp.copy()
            grp_copy["_date"] = pd.to_datetime(grp_copy["timestamp"]).dt.date
            bars_per_day = grp_copy.groupby("_date").size().mean()

            daily_vol = bar_vol * np.sqrt(bars_per_day)
            annualized_vol = bar_vol * np.sqrt(252 * bars_per_day)
            num_periods = len(log_returns)

        volatilities.append(
            TickerVolatility(
                ticker=str(ticker),
                annualized_vol=float(annualized_vol),
                daily_vol=float(daily_vol),
                num_periods=int(num_periods),
            )
        )

    return RealizedVolatilityResult(volatilities=volatilities, window=window)


def intraday_vol_profile(
    df: pd.DataFrame,
    ticker: str,
    bucket_minutes: int = 30,
) -> IntradayVolProfileResult:
    """Compute average volatility by time-of-day bucket for a single ticker.

    Parameters
    ----------
    df:
        Bar DataFrame.
    ticker:
        Single ticker to analyse.
    bucket_minutes:
        Bucket width in minutes (e.g., 30 groups 14:30-14:59 together).

    Returns
    -------
    IntradayVolProfileResult
        List of buckets with average bar-level volatility per time slot.
    """
    work = df[df["ticker"] == ticker].copy()
    work = work.sort_values("timestamp")

    # Compute bar-level log returns
    work["_log_return"] = np.log(work["close"] / work["close"].shift(1))

    # Extract time-of-day bucket
    ts = pd.to_datetime(work["timestamp"])
    work["_hour"] = ts.dt.hour
    work["_minute"] = (ts.dt.minute // bucket_minutes) * bucket_minutes

    # Drop the first bar (NaN return) and group
    valid = work.dropna(subset=["_log_return"])

    buckets: list[IntradayVolBucket] = []
    for (hour, minute), grp in valid.groupby(["_hour", "_minute"], sort=True):
        avg_vol = float(grp["_log_return"].std(ddof=1)) if len(grp) > 1 else 0.0
        buckets.append(
            IntradayVolBucket(
                hour=int(hour),
                minute=int(minute),
                avg_vol=avg_vol,
                bar_count=len(grp),
            )
        )

    return IntradayVolProfileResult(ticker=ticker, buckets=buckets)


def vol_surface(
    df: pd.DataFrame,
    windows: list[int] | None = None,
    tickers: list[str] | None = None,
) -> VolSurfaceResult:
    """Compute realized volatility across multiple lookback windows.

    Parameters
    ----------
    df:
        Bar DataFrame.
    windows:
        List of lookback windows in trading days.  Default ``[5, 10, 21, 63]``.
    tickers:
        Optional list of tickers to include.

    Returns
    -------
    VolSurfaceResult
        Cross-product of tickers x windows with annualized vol for each.
    """
    if windows is None:
        windows = [5, 10, 21, 63]

    work = df.copy()
    if tickers is not None:
        work = work[work["ticker"].isin(tickers)]

    points: list[VolSurfacePoint] = []

    for ticker, grp in work.groupby("ticker"):
        grp = grp.sort_values("timestamp").copy()
        grp["_date"] = pd.to_datetime(grp["timestamp"]).dt.date
        daily_closes = grp.groupby("_date")["close"].last()

        for w in windows:
            tail = daily_closes.iloc[-w:] if len(daily_closes) >= w else daily_closes
            log_returns = np.log(tail / tail.shift(1)).dropna()
            if len(log_returns) > 1:
                vol = float(log_returns.std(ddof=1)) * np.sqrt(252)
            else:
                vol = 0.0

            points.append(
                VolSurfacePoint(
                    ticker=str(ticker),
                    window_days=w,
                    annualized_vol=float(vol),
                )
            )

    return VolSurfaceResult(points=points, windows=windows)


def garman_klass_vol(
    df: pd.DataFrame,
    tickers: list[str] | None = None,
) -> list[GarmanKlassResult]:
    """Compute Garman-Klass volatility estimator per ticker.

    The Garman-Klass estimator uses OHLC prices::

        GK_i = 0.5 * ln(H/L)^2 - (2*ln(2) - 1) * ln(C/O)^2

    The per-bar GK values are averaged and square-rooted to yield daily vol,
    then annualized by ``sqrt(252 * bars_per_day)``.

    Parameters
    ----------
    df:
        Bar DataFrame.
    tickers:
        Optional list of tickers to include.

    Returns
    -------
    list[GarmanKlassResult]
        One result per ticker with raw and annualized GK volatility.
    """
    work = df.copy()
    if tickers is not None:
        work = work[work["ticker"].isin(tickers)]

    results: list[GarmanKlassResult] = []

    for ticker, grp in work.groupby("ticker"):
        grp = grp.sort_values("timestamp").copy()

        log_hl = np.log(grp["high"] / grp["low"])
        log_co = np.log(grp["close"] / grp["open"])

        gk_per_bar = 0.5 * log_hl**2 - (2 * np.log(2) - 1) * log_co**2

        mean_gk = float(gk_per_bar.mean())
        gk_vol = float(np.sqrt(max(mean_gk, 0.0)))

        # Estimate bars per day
        grp["_date"] = pd.to_datetime(grp["timestamp"]).dt.date
        bars_per_day = float(grp.groupby("_date").size().mean())

        annualized_gk_vol = gk_vol * np.sqrt(252 * bars_per_day)

        results.append(
            GarmanKlassResult(
                ticker=str(ticker),
                gk_vol=gk_vol,
                annualized_gk_vol=float(annualized_gk_vol),
                num_bars=len(grp),
            )
        )

    return results
