"""Sector analytics -- rotation, heatmap, and relative strength."""

from __future__ import annotations

import pandas as pd

from .types import (
    SectorPerformance,
    SectorRotationResult,
    SectorHeatmapCell,
    SectorHeatmapResult,
    RelativeStrengthTicker,
    RelativeStrengthResult,
)


def _daily_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate intraday bars to daily OHLCV per ticker.

    Returns a DataFrame with columns: date, ticker, open, close, volume.
    """
    work = df.copy()
    work["_date"] = pd.to_datetime(work["timestamp"]).dt.date
    grouped = work.sort_values("timestamp").groupby(["ticker", "_date"])

    daily = pd.DataFrame({
        "open": grouped["open"].first(),
        "close": grouped["close"].last(),
        "volume": grouped["volume"].sum(),
    }).reset_index().rename(columns={"_date": "date"})

    return daily


def sector_rotation(
    df: pd.DataFrame,
    sector_map: dict[str, str],
) -> SectorRotationResult:
    """Rank sectors by average daily return over the period.

    Parameters
    ----------
    df:
        Bar DataFrame with columns: timestamp, open, high, low, close,
        volume, vwap, num_transactions, ticker.
    sector_map:
        Maps ticker -> GICS sector name.

    Returns
    -------
    SectorRotationResult
        Sectors sorted by average return (best first), with volume and
        ticker counts.
    """
    known = set(sector_map.keys())
    work = df[df["ticker"].isin(known)].copy()

    daily = _daily_ohlcv(work)

    # Daily return per ticker
    daily["daily_return"] = (daily["close"] - daily["open"]) / daily["open"]
    daily["daily_return"] = daily["daily_return"].fillna(0.0)

    # Map ticker -> sector
    daily["sector"] = daily["ticker"].map(sector_map)

    # Aggregate per sector
    sector_agg = daily.groupby("sector").agg(
        avg_return=("daily_return", "mean"),
        total_volume=("volume", "sum"),
        ticker_count=("ticker", "nunique"),
    ).reset_index()

    # Sort best performing first
    sector_agg = sector_agg.sort_values("avg_return", ascending=False)

    sectors = [
        SectorPerformance(
            sector=str(row["sector"]),
            avg_return=float(row["avg_return"]),
            total_volume=float(row["total_volume"]),
            ticker_count=int(row["ticker_count"]),
        )
        for _, row in sector_agg.iterrows()
    ]

    # Date range string
    timestamps = pd.to_datetime(work["timestamp"])
    min_date = timestamps.min().strftime("%Y-%m-%d") if len(timestamps) else ""
    max_date = timestamps.max().strftime("%Y-%m-%d") if len(timestamps) else ""
    period = f"{min_date} to {max_date}"

    return SectorRotationResult(sectors=sectors, period=period)


def sector_heatmap(
    df: pd.DataFrame,
    sector_map: dict[str, str],
) -> SectorHeatmapResult:
    """Build a sector x date grid of average daily returns.

    Parameters
    ----------
    df:
        Bar DataFrame.
    sector_map:
        Maps ticker -> GICS sector name.

    Returns
    -------
    SectorHeatmapResult
        Grid of (sector, date, avg_return) cells plus unique sector and
        date lists for rendering axes.
    """
    known = set(sector_map.keys())
    work = df[df["ticker"].isin(known)].copy()

    daily = _daily_ohlcv(work)

    # Daily return per ticker
    daily["daily_return"] = (daily["close"] - daily["open"]) / daily["open"]
    daily["daily_return"] = daily["daily_return"].fillna(0.0)

    # Map ticker -> sector
    daily["sector"] = daily["ticker"].map(sector_map)
    daily["date_str"] = daily["date"].astype(str)

    # Average return per (sector, date)
    grid = (
        daily.groupby(["sector", "date_str"])["daily_return"]
        .mean()
        .reset_index()
    )

    cells = [
        SectorHeatmapCell(
            sector=str(row["sector"]),
            date=str(row["date_str"]),
            avg_return=float(row["daily_return"]),
        )
        for _, row in grid.iterrows()
    ]

    unique_sectors = sorted(grid["sector"].unique().tolist())
    unique_dates = sorted(grid["date_str"].unique().tolist())

    return SectorHeatmapResult(
        cells=cells,
        sectors=unique_sectors,
        dates=unique_dates,
    )


def relative_strength(
    df: pd.DataFrame,
    sector_map: dict[str, str],
    benchmark_tickers: list[str] | None = None,
) -> RelativeStrengthResult:
    """Compute relative-strength ratios for mapped tickers vs. a benchmark.

    Parameters
    ----------
    df:
        Bar DataFrame.
    sector_map:
        Maps ticker -> GICS sector name.  Only these tickers are scored.
    benchmark_tickers:
        Optional explicit benchmark tickers.  If ``None``, uses the
        equal-weighted average of all tickers in *sector_map*.

    Returns
    -------
    RelativeStrengthResult
        Per-ticker RS ratio (>1 = outperforming benchmark).
    """
    known = set(sector_map.keys())
    work = df[df["ticker"].isin(known)].copy()

    daily = _daily_ohlcv(work)

    # Cumulative return per ticker: last close / first close - 1
    ticker_returns: dict[str, float] = {}
    for ticker, grp in daily.sort_values("date").groupby("ticker"):
        first_close = grp["close"].iloc[0]
        last_close = grp["close"].iloc[-1]
        if first_close != 0:
            ticker_returns[str(ticker)] = (last_close / first_close) - 1.0
        else:
            ticker_returns[str(ticker)] = 0.0

    # Benchmark return
    if benchmark_tickers is not None:
        bench_rets = [
            ticker_returns[t] for t in benchmark_tickers if t in ticker_returns
        ]
        benchmark_return = sum(bench_rets) / len(bench_rets) if bench_rets else 0.0
        benchmark_label = ",".join(benchmark_tickers)
    else:
        all_rets = list(ticker_returns.values())
        benchmark_return = sum(all_rets) / len(all_rets) if all_rets else 0.0
        benchmark_label = "equal-weight"

    # RS ratio per ticker
    tickers_out: list[RelativeStrengthTicker] = []
    for ticker in sorted(ticker_returns.keys()):
        ret = ticker_returns[ticker]
        rs = (1.0 + ret) / (1.0 + benchmark_return) if (1.0 + benchmark_return) != 0 else 0.0
        tickers_out.append(
            RelativeStrengthTicker(
                ticker=ticker,
                rs_ratio=float(rs),
                ticker_return=float(ret),
                benchmark_return=float(benchmark_return),
            )
        )

    return RelativeStrengthResult(
        tickers=tickers_out,
        benchmark=benchmark_label,
    )
