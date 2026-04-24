"""Correlation analytics -- pairwise, sector, and rolling correlation."""

from __future__ import annotations

import pandas as pd

from .types import (
    PairCorrelation,
    PairwiseCorrelationResult,
    SectorCorrelationPair,
    SectorCorrelationResult,
    RollingCorrelationPoint,
    RollingCorrelationResult,
)


def _daily_closes(df: pd.DataFrame) -> pd.DataFrame:
    """Extract the last close per (ticker, date) pair.

    Returns a DataFrame with columns: date, ticker, close.
    """
    work = df.copy()
    work["_date"] = pd.to_datetime(work["timestamp"]).dt.date
    daily = (
        work.sort_values("timestamp")
        .groupby(["ticker", "_date"])["close"]
        .last()
        .reset_index()
        .rename(columns={"_date": "date"})
    )
    return daily


def pairwise_correlation(
    df: pd.DataFrame,
    tickers: list[str] | None = None,
) -> PairwiseCorrelationResult:
    """Compute Pearson correlation of daily returns across tickers.

    Parameters
    ----------
    df:
        Bar DataFrame with columns: timestamp, open, high, low, close,
        volume, vwap, num_transactions, ticker.
    tickers:
        Optional list of tickers to include.  ``None`` means all tickers.

    Returns
    -------
    PairwiseCorrelationResult
        NxN correlation matrix and individual pair correlations.
    """
    work = df.copy()
    if tickers is not None:
        work = work[work["ticker"].isin(tickers)]

    daily = _daily_closes(work)

    # Pivot: rows = date, columns = ticker, values = close
    pivoted = daily.pivot(index="date", columns="ticker", values="close")

    # Daily returns via pct_change
    returns = pivoted.pct_change().dropna()

    # Pearson correlation matrix
    corr_matrix = returns.corr()

    ticker_list = list(corr_matrix.columns)
    matrix = corr_matrix.values.tolist()

    # Build individual pairs (upper triangle, excluding diagonal)
    pairs: list[PairCorrelation] = []
    for i, t_a in enumerate(ticker_list):
        for j, t_b in enumerate(ticker_list):
            if j > i:
                pairs.append(
                    PairCorrelation(
                        ticker_a=t_a,
                        ticker_b=t_b,
                        correlation=float(corr_matrix.iloc[i, j]),
                    )
                )

    return PairwiseCorrelationResult(
        pairs=pairs,
        tickers=ticker_list,
        matrix=matrix,
    )


def sector_correlation(
    df: pd.DataFrame,
    sector_map: dict[str, str],
) -> SectorCorrelationResult:
    """Compute Pearson correlation between sector return series.

    Parameters
    ----------
    df:
        Bar DataFrame.
    sector_map:
        Maps ticker -> GICS sector name (e.g. ``{"AAPL": "Tech"}``).

    Returns
    -------
    SectorCorrelationResult
        Sector-level NxN correlation matrix and individual sector pairs.
    """
    work = df.copy()

    # Filter to tickers present in the sector map
    known_tickers = set(sector_map.keys())
    work = work[work["ticker"].isin(known_tickers)]

    daily = _daily_closes(work)

    # Pivot to get per-ticker daily closes
    pivoted = daily.pivot(index="date", columns="ticker", values="close")

    # Daily returns
    returns = pivoted.pct_change().dropna()

    # Equal-weighted average return per sector per day
    sector_returns: dict[str, pd.Series] = {}
    for sector in sorted(set(sector_map.values())):
        sector_tickers = [t for t, s in sector_map.items() if s == sector and t in returns.columns]
        if sector_tickers:
            sector_returns[sector] = returns[sector_tickers].mean(axis=1)

    sector_df = pd.DataFrame(sector_returns)

    # Pearson correlation
    corr_matrix = sector_df.corr()

    sector_list = list(corr_matrix.columns)
    matrix = corr_matrix.values.tolist()

    # Build individual pairs (upper triangle)
    pairs: list[SectorCorrelationPair] = []
    for i, s_a in enumerate(sector_list):
        for j, s_b in enumerate(sector_list):
            if j > i:
                pairs.append(
                    SectorCorrelationPair(
                        sector_a=s_a,
                        sector_b=s_b,
                        correlation=float(corr_matrix.iloc[i, j]),
                    )
                )

    return SectorCorrelationResult(
        pairs=pairs,
        sectors=sector_list,
        matrix=matrix,
    )


def rolling_correlation(
    df: pd.DataFrame,
    ticker_a: str,
    ticker_b: str,
    window: int = 21,
) -> RollingCorrelationResult:
    """Compute rolling Pearson correlation between two tickers.

    Parameters
    ----------
    df:
        Bar DataFrame.
    ticker_a:
        First ticker symbol.
    ticker_b:
        Second ticker symbol.
    window:
        Rolling window in trading days (default 21).

    Returns
    -------
    RollingCorrelationResult
        Time series of rolling correlation values.
    """
    work = df[df["ticker"].isin([ticker_a, ticker_b])].copy()

    daily = _daily_closes(work)

    # Pivot: rows = date, columns = ticker
    pivoted = daily.pivot(index="date", columns="ticker", values="close")

    # Daily returns
    returns = pivoted.pct_change().dropna()

    # Rolling correlation
    rolling_corr = returns[ticker_a].rolling(window=window).corr(returns[ticker_b])
    rolling_corr = rolling_corr.dropna()

    points: list[RollingCorrelationPoint] = []
    for date_val, corr_val in rolling_corr.items():
        points.append(
            RollingCorrelationPoint(
                timestamp=str(date_val),
                correlation=float(corr_val),
            )
        )

    return RollingCorrelationResult(
        ticker_a=ticker_a,
        ticker_b=ticker_b,
        window=window,
        points=points,
    )
