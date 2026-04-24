"""Pattern analytics -- intraday patterns, day-of-week effects, monthly seasonality."""

from __future__ import annotations

import calendar

import numpy as np
import pandas as pd
from scipy.stats import ttest_ind

from .types import (
    IntradayBucket,
    IntradayPatternsResult,
    DayOfWeekStats,
    DayOfWeekResult,
    MonthStats,
    MonthlySeasonalityResult,
)

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def intraday_patterns(
    df: pd.DataFrame,
    ticker: str,
    bucket_minutes: int = 30,
) -> IntradayPatternsResult:
    """Compute average bar-level return and volume by time-of-day bucket.

    Parameters
    ----------
    df:
        Bar DataFrame with columns: timestamp, open, high, low, close,
        volume, vwap, num_transactions, ticker.
    ticker:
        Single ticker to analyse.
    bucket_minutes:
        Bucket width in minutes (e.g., 30 groups 14:30-14:59 together).

    Returns
    -------
    IntradayPatternsResult
        List of buckets with average bar return, average volume, and bar count.
    """
    work = df[df["ticker"] == ticker].copy()
    work = work.sort_values("timestamp")

    # Compute bar-level return: close/open - 1
    work["_bar_return"] = work["close"] / work["open"] - 1

    # Extract time-of-day bucket
    ts = pd.to_datetime(work["timestamp"])
    work["_hour"] = ts.dt.hour
    work["_minute"] = (ts.dt.minute // bucket_minutes) * bucket_minutes

    buckets: list[IntradayBucket] = []
    for (hour, minute), grp in work.groupby(["_hour", "_minute"], sort=True):
        avg_return = float(grp["_bar_return"].mean())
        avg_volume = float(grp["volume"].mean())
        bar_count = len(grp)
        buckets.append(
            IntradayBucket(
                hour=int(hour),
                minute=int(minute),
                avg_return=avg_return,
                avg_volume=avg_volume,
                bar_count=bar_count,
            )
        )

    return IntradayPatternsResult(ticker=ticker, buckets=buckets)


def day_of_week_effects(
    df: pd.DataFrame,
    ticker: str,
) -> DayOfWeekResult:
    """Analyse return and volume patterns by day of the week.

    Parameters
    ----------
    df:
        Bar DataFrame.
    ticker:
        Single ticker to analyse.

    Returns
    -------
    DayOfWeekResult
        Statistics per weekday (Mon-Fri) with t-test vs other days.
    """
    work = df[df["ticker"] == ticker].copy()
    work = work.sort_values("timestamp")

    ts = pd.to_datetime(work["timestamp"])
    work["_date"] = ts.dt.date

    # Compute daily return: (last close - first open) / first open
    daily = work.groupby("_date").agg(
        first_open=("open", "first"),
        last_close=("close", "last"),
        daily_volume=("volume", "sum"),
    )
    daily["daily_return"] = (daily["last_close"] - daily["first_open"]) / daily["first_open"]
    daily["_dow"] = pd.to_datetime(daily.index).dayofweek  # 0=Monday

    all_returns = daily["daily_return"].values

    days: list[DayOfWeekStats] = []
    for dow in range(5):
        mask = daily["_dow"] == dow
        day_data = daily[mask]
        other_data = daily[~mask]

        if len(day_data) == 0:
            continue

        avg_return = float(day_data["daily_return"].mean())
        avg_volume = float(day_data["daily_volume"].mean())
        sample_count = len(day_data)

        # T-test: this day's returns vs all other days' returns
        t_stat = None
        p_value = None
        if len(day_data) >= 2 and len(other_data) >= 2:
            t_result = ttest_ind(
                day_data["daily_return"].values,
                other_data["daily_return"].values,
                equal_var=False,
            )
            t_stat = float(t_result.statistic)
            p_value = float(t_result.pvalue)

        days.append(
            DayOfWeekStats(
                day_name=_DAY_NAMES[dow],
                day_number=dow,
                avg_return=avg_return,
                avg_volume=avg_volume,
                sample_count=sample_count,
                t_stat=t_stat,
                p_value=p_value,
            )
        )

    return DayOfWeekResult(ticker=ticker, days=days)


def monthly_seasonality(
    df: pd.DataFrame,
    ticker: str,
) -> MonthlySeasonalityResult:
    """Analyse return and volume patterns by calendar month.

    Parameters
    ----------
    df:
        Bar DataFrame.
    ticker:
        Single ticker to analyse.

    Returns
    -------
    MonthlySeasonalityResult
        Statistics per calendar month that appears in the data.
    """
    work = df[df["ticker"] == ticker].copy()
    work = work.sort_values("timestamp")

    ts = pd.to_datetime(work["timestamp"])
    work["_date"] = ts.dt.date

    # Compute daily return: (last close - first open) / first open
    daily = work.groupby("_date").agg(
        first_open=("open", "first"),
        last_close=("close", "last"),
        daily_volume=("volume", "sum"),
    )
    daily["daily_return"] = (daily["last_close"] - daily["first_open"]) / daily["first_open"]
    daily["_month"] = pd.to_datetime(daily.index).month

    months: list[MonthStats] = []
    for month_num, grp in daily.groupby("_month", sort=True):
        avg_return = float(grp["daily_return"].mean())
        avg_volume = float(grp["daily_volume"].mean())
        sample_count = len(grp)
        month_name = calendar.month_name[int(month_num)]

        months.append(
            MonthStats(
                month=int(month_num),
                month_name=month_name,
                avg_return=avg_return,
                avg_volume=avg_volume,
                sample_count=sample_count,
            )
        )

    return MonthlySeasonalityResult(ticker=ticker, months=months)
