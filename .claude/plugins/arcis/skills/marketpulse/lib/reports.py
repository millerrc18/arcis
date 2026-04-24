"""Report template functions for MarketPulse.

Composes data loading (CacheManager) + analytics + export into single-call
report generators.  Each function is async and returns the output file Path.

Public API
----------
- :func:`daily_market_report`     -- single-date OHLCV + movers + sector heatmap
- :func:`period_analysis_report`  -- multi-day volatility, volume, correlation
- :func:`correlation_report`      -- pairwise correlation focus report
- :func:`event_study_report`      -- pre/post event-impact analysis
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from .analytics import (
    daily_summary,
    biggest_movers,
    volume_analysis,
    realized_volatility,
    pairwise_correlation,
    sector_rotation,
    sector_heatmap,
    volume_spikes,
    event_impact,
)
from .analytics._base import AnalyticsResult
from .analytics.types import load_sector_map
from .export import to_excel, _result_to_dataframe

if TYPE_CHECKING:
    from .cache import CacheManager


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_bars(
    cm: "CacheManager",
    tickers: list[str],
    from_date: date,
    to_date: date,
    timespan: str = "1min",
    max_rows: int = 500_000,
) -> pd.DataFrame:
    """Async wrapper around CacheManager.get_bars_df."""
    return await cm.get_bars_df(
        tickers=tickers,
        timespan=timespan,
        from_date=from_date,
        to_date=to_date,
        max_rows=max_rows,
    )


def _resolve_output(output: str | Path | None, default_name: str) -> Path:
    """Resolve an output path; defaults to Desktop if not specified.

    Parameters
    ----------
    output:
        Explicit path provided by the caller, or ``None``.
    default_name:
        Filename (with extension) to use when *output* is ``None``.

    Returns
    -------
    Path
        Resolved output path (parent directory created if necessary).
    """
    if output is not None:
        path = Path(output)
    else:
        desktop = Path.home() / "Desktop"
        if not desktop.exists():
            desktop = Path.home()
        path = desktop / default_name

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Report 1: Daily Market Report
# ---------------------------------------------------------------------------


async def daily_market_report(
    cm: "CacheManager",
    tickers: list[str],
    report_date: date,
    timespan: str = "1min",
    index_name: str | None = None,
    output: str | Path | None = None,
) -> Path:
    """Generate a daily market report for one trading date.

    Loads intraday bars for *report_date*, computes daily summaries and
    biggest movers, and optionally adds a sector heatmap sheet.

    Parameters
    ----------
    cm:
        CacheManager for data access.
    tickers:
        List of stock symbols to include.
    report_date:
        The trading date to report on.
    timespan:
        Bar timespan key (default ``"1min"``).
    index_name:
        Optional index name (e.g. ``"SP500"``) for sector enrichment.
        When provided, a ``"Sector Heatmap"`` sheet is added.
    output:
        Output file path.  When ``None``, writes
        ``daily_report_{date}.xlsx`` to the Desktop.

    Returns
    -------
    Path
        Absolute path of the written Excel workbook.

    Raises
    ------
    ValueError
        If no bar data is available for the requested date.
    """
    df = await _load_bars(cm, tickers, report_date, report_date, timespan=timespan)

    if df.empty:
        raise ValueError(
            f"No bar data found for {tickers} on {report_date.isoformat()} "
            f"(timespan={timespan!r}).  Fetch data first."
        )

    summary = daily_summary(df)
    movers = biggest_movers(df, date_str=report_date.isoformat(), n=10)

    summary_df = _result_to_dataframe(summary)
    gainers_df = (
        pd.DataFrame([m.__dict__ for m in movers.gainers])
        if movers.gainers
        else pd.DataFrame()
    )
    losers_df = (
        pd.DataFrame([m.__dict__ for m in movers.losers])
        if movers.losers
        else pd.DataFrame()
    )

    sheets: dict[str, pd.DataFrame] = {
        "Movers - Gainers": gainers_df,
        "Movers - Losers": losers_df,
    }

    if index_name is not None:
        sector_map = load_sector_map(index_name)
        heatmap = sector_heatmap(df, sector_map)
        sheets["Sector Heatmap"] = _result_to_dataframe(heatmap)

    path = _resolve_output(output, f"daily_report_{report_date.isoformat()}.xlsx")

    return to_excel(
        summary_df,
        path=path,
        sheets=sheets,
        sheet_name="Daily Summary",
        return_columns=["daily_return", "return_pct"],
    )


# ---------------------------------------------------------------------------
# Report 2: Period Analysis Report
# ---------------------------------------------------------------------------


async def period_analysis_report(
    cm: "CacheManager",
    tickers: list[str],
    from_date: date,
    to_date: date,
    timespan: str = "1min",
    index_name: str | None = None,
    output: str | Path | None = None,
) -> Path:
    """Generate a multi-day analysis report covering a date range.

    Includes daily summaries, volume statistics, realized volatility,
    volume spikes, and (when multiple tickers are given) pairwise
    correlations.  Optionally adds sector rotation data.

    Parameters
    ----------
    cm:
        CacheManager for data access.
    tickers:
        List of stock symbols to include.
    from_date:
        Start of the reporting period (inclusive).
    to_date:
        End of the reporting period (inclusive).
    timespan:
        Bar timespan key (default ``"1min"``).
    index_name:
        Optional index name for sector enrichment.  When provided, a
        ``"Sector Rotation"`` sheet is added.
    output:
        Output file path.  When ``None``, writes
        ``period_report_{from}_{to}.xlsx`` to the Desktop.

    Returns
    -------
    Path
        Absolute path of the written Excel workbook.

    Raises
    ------
    ValueError
        If no bar data is available for the requested range.
    """
    df = await _load_bars(cm, tickers, from_date, to_date, timespan=timespan)

    if df.empty:
        raise ValueError(
            f"No bar data found for {tickers} between {from_date.isoformat()} "
            f"and {to_date.isoformat()} (timespan={timespan!r}).  Fetch data first."
        )

    summary = daily_summary(df)
    vol_stats = volume_analysis(df)
    rv = realized_volatility(df)
    spikes = volume_spikes(df)

    summary_df = _result_to_dataframe(summary)
    vol_df = _result_to_dataframe(vol_stats)
    rv_df = _result_to_dataframe(rv)
    spikes_df = _result_to_dataframe(spikes)

    sheets: dict[str, pd.DataFrame] = {
        "Volume Stats": vol_df,
        "Volatility": rv_df,
        "Volume Spikes": spikes_df,
    }

    if len(tickers) > 1:
        corr = pairwise_correlation(df)
        pairs_df = _result_to_dataframe(corr)
        corr_matrix_df = pd.DataFrame(
            corr.matrix, index=corr.tickers, columns=corr.tickers
        )
        sheets["Correlation"] = pairs_df
        sheets["Corr Matrix"] = corr_matrix_df

    if index_name is not None:
        sector_map = load_sector_map(index_name)
        rotation = sector_rotation(df, sector_map)
        sheets["Sector Rotation"] = _result_to_dataframe(rotation)

    default_name = (
        f"period_report_{from_date.isoformat()}_{to_date.isoformat()}.xlsx"
    )
    path = _resolve_output(output, default_name)

    return to_excel(
        summary_df,
        path=path,
        sheets=sheets,
        sheet_name="Daily Summary",
        return_columns=["daily_return", "return_pct"],
    )


# ---------------------------------------------------------------------------
# Report 3: Correlation Report
# ---------------------------------------------------------------------------


async def correlation_report(
    cm: "CacheManager",
    tickers: list[str],
    from_date: date,
    to_date: date,
    timespan: str = "1min",
    index_name: str | None = None,
    output: str | Path | None = None,
) -> Path:
    """Generate a pairwise correlation report for a set of tickers.

    Parameters
    ----------
    cm:
        CacheManager for data access.
    tickers:
        At least 2 stock symbols.
    from_date:
        Start of the correlation window (inclusive).
    to_date:
        End of the correlation window (inclusive).
    timespan:
        Bar timespan key (default ``"1min"``).
    index_name:
        Optional index name for sector-level correlation enrichment.
        When provided, ``"Sector Pairs"`` and ``"Sector Matrix"`` sheets
        are added.
    output:
        Output file path.  When ``None``, writes
        ``correlation_report_{from}_{to}.xlsx`` to the Desktop.

    Returns
    -------
    Path
        Absolute path of the written Excel workbook.

    Raises
    ------
    ValueError
        If fewer than 2 tickers are supplied or no data is found.
    """
    if len(tickers) < 2:
        raise ValueError(
            f"correlation_report requires at least 2 tickers; got {len(tickers)}."
        )

    df = await _load_bars(cm, tickers, from_date, to_date, timespan=timespan)

    if df.empty:
        raise ValueError(
            f"No bar data found for {tickers} between {from_date.isoformat()} "
            f"and {to_date.isoformat()} (timespan={timespan!r}).  Fetch data first."
        )

    corr = pairwise_correlation(df)
    pairs_df = _result_to_dataframe(corr)
    corr_matrix_df = pd.DataFrame(
        corr.matrix, index=corr.tickers, columns=corr.tickers
    )

    sheets: dict[str, pd.DataFrame] = {
        "Correlation Matrix": corr_matrix_df,
    }

    if index_name is not None:
        from .analytics import sector_correlation as _sector_corr

        sector_map = load_sector_map(index_name)
        sc = _sector_corr(df, sector_map)
        sector_pairs_df = _result_to_dataframe(sc)
        sector_matrix_df = pd.DataFrame(
            sc.matrix, index=sc.sectors, columns=sc.sectors
        )
        sheets["Sector Pairs"] = sector_pairs_df
        sheets["Sector Matrix"] = sector_matrix_df

    default_name = (
        f"correlation_report_{from_date.isoformat()}_{to_date.isoformat()}.xlsx"
    )
    path = _resolve_output(output, default_name)

    return to_excel(
        pairs_df,
        path=path,
        sheets=sheets,
        sheet_name="Pair Correlations",
        return_columns=["correlation"],
    )


# ---------------------------------------------------------------------------
# Report 4: Event Study Report
# ---------------------------------------------------------------------------


async def event_study_report(
    cm: "CacheManager",
    ticker: str,
    event_date: date,
    from_date: date,
    to_date: date,
    pre_days: int = 5,
    post_days: int = 5,
    timespan: str = "1min",
    output: str | Path | None = None,
) -> Path:
    """Generate an event study report for a single ticker.

    Measures price and volume impact in the windows immediately before and
    after *event_date*.

    Parameters
    ----------
    cm:
        CacheManager for data access.
    ticker:
        Single stock symbol to study.
    event_date:
        The event date (e.g. earnings release, announcement).
    from_date:
        Start of the full data window (inclusive).
    to_date:
        End of the full data window (inclusive).
    pre_days:
        Number of trading days before the event for the pre-window.
    post_days:
        Number of trading days after the event for the post-window.
    timespan:
        Bar timespan key (default ``"1min"``).
    output:
        Output file path.  When ``None``, writes
        ``event_study_{ticker}_{event_date}.xlsx`` to the Desktop.

    Returns
    -------
    Path
        Absolute path of the written Excel workbook.

    Raises
    ------
    ValueError
        If no bar data is available for the requested range.
    """
    df = await _load_bars(cm, [ticker], from_date, to_date, timespan=timespan)

    if df.empty:
        raise ValueError(
            f"No bar data found for {ticker!r} between {from_date.isoformat()} "
            f"and {to_date.isoformat()} (timespan={timespan!r}).  Fetch data first."
        )

    impact = event_impact(
        df,
        ticker=ticker,
        event_date=event_date.isoformat(),
        pre_days=pre_days,
        post_days=post_days,
    )
    summary = daily_summary(df)
    spikes = volume_spikes(df)

    impact_df = _result_to_dataframe(impact)
    summary_df = _result_to_dataframe(summary)
    spikes_df = _result_to_dataframe(spikes)

    sheets: dict[str, pd.DataFrame] = {
        "Daily Summary": summary_df,
        "Volume Spikes": spikes_df,
    }

    default_name = (
        f"event_study_{ticker}_{event_date.isoformat()}.xlsx"
    )
    path = _resolve_output(output, default_name)

    return to_excel(
        impact_df,
        path=path,
        sheets=sheets,
        sheet_name="Event Impact",
        return_columns=["daily_return", "return_pct"],
    )
