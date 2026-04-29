"""Market data ingestion via yfinance.

Called by: cli/commands.py, evaluation/backtester.py, scheduler/premarket.py, scheduler/watch.py, services/recap_service.py, services/scan_service.py, services/watchlist_service.py, shadow_trading/executor.py, training/bootstrap.py
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_ingestion.py
"""

import logging
import warnings

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# #546 — yfinance >=0.2.50 emits FutureWarning for `auto_adjust=False` even
# when explicitly requested. We need raw OHLCV (no adjustment) for accurate
# slippage/PnL accounting, so we keep the kwarg and just suppress the noise.
# Audit found ~540 instances over 3 days clogging stderr.
warnings.filterwarnings(
    "ignore",
    message=r"YF\.download\(\) has changed argument auto_adjust default to True",
    category=FutureWarning,
)

# Tickers that need translation for yfinance compatibility
TICKER_MAP = {
    "BRK.B": "BRK-B",
}
REVERSE_TICKER_MAP = {v: k for k, v in TICKER_MAP.items()}


def _build_yf_download_kwargs(
    period: str, start: str | None, end: str | None
) -> dict:
    """Construct yf.download kwargs honoring start/end vs period semantics.

    When start or end is provided, those anchors win and ``period`` is
    omitted (yfinance treats date-bounded calls separately from period
    calls). Otherwise the legacy ``period`` form is used.
    """
    kwargs: dict = {"progress": False, "auto_adjust": False}
    if start is not None or end is not None:
        if start is not None:
            kwargs["start"] = start
        if end is not None:
            kwargs["end"] = end
    else:
        kwargs["period"] = period
    return kwargs


def _fetch_single(dl_ticker: str, download_kwargs: dict) -> pd.DataFrame | None:
    """Single-ticker yf.download branch — returns the cleaned DataFrame or None."""
    orig_ticker = REVERSE_TICKER_MAP.get(dl_ticker, dl_ticker)
    try:
        df = yf.download(dl_ticker, **download_kwargs)
        if df is None or df.empty:
            logger.warning("No data returned for %s", orig_ticker)
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df[["Open", "High", "Low", "Close", "Volume"]]
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", orig_ticker, e)
        return None


def _extract_batch_frames(
    raw: pd.DataFrame, download_tickers: list[str]
) -> dict[str, pd.DataFrame]:
    """Extract per-ticker DataFrames from a yfinance batch download response."""
    result: dict[str, pd.DataFrame] = {}
    for dl_ticker in download_tickers:
        orig_ticker = REVERSE_TICKER_MAP.get(dl_ticker, dl_ticker)
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                df = raw[dl_ticker][["Open", "High", "Low", "Close", "Volume"]].copy()
            else:
                df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
            df = df.dropna(how="all")
            if not df.empty:
                result[orig_ticker] = df
            else:
                logger.warning("No data for %s", orig_ticker)
        except Exception as e:
            logger.warning("Failed to extract data for %s: %s", orig_ticker, e)
    return result


def fetch_ohlcv(
    tickers: list[str],
    period: str = "1y",
    *,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Fetch daily OHLCV data for a list of tickers.

    Returns a dict mapping ticker -> DataFrame with columns:
    Open, High, Low, Close, Volume, indexed by date.
    Tickers that fail to download are skipped with a warning.

    Date anchoring (Sprint 1.C.4.5 / #104):
    - When ``start`` and/or ``end`` are provided, yfinance is called with
      those explicit boundaries. Use this for any caller that needs data
      anchored to a HISTORICAL window (backtest test span, walkforward
      fold range, corpus generator). yfinance ``period`` is ignored in
      this path.
    - When neither is provided, the legacy ``period`` semantics apply:
      yfinance returns data from ``today - period`` through ``today``.
      Live callers (mr_scan_service, price_utils, reconcile) keep using
      this path because they always want the most recent N days.
    """
    if not tickers:
        return {}

    download_tickers = [TICKER_MAP.get(t, t) for t in tickers]
    download_kwargs = _build_yf_download_kwargs(period, start, end)

    if len(download_tickers) == 1:
        dl_ticker = download_tickers[0]
        df = _fetch_single(dl_ticker, download_kwargs)
        if df is None:
            return {}
        return {REVERSE_TICKER_MAP.get(dl_ticker, dl_ticker): df}

    try:
        raw = yf.download(download_tickers, group_by="ticker", **download_kwargs)
    except Exception as e:
        logger.warning("Batch download failed: %s", e)
        return {}

    if raw is None or raw.empty:
        logger.warning("No data returned from batch download")
        return {}

    return _extract_batch_frames(raw, download_tickers)


def fetch_spy_benchmark(
    period: str = "1y",
    *,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Fetch daily OHLCV data for SPY benchmark.

    Returns a DataFrame with columns: Open, High, Low, Close, Volume.

    Date anchoring follows ``fetch_ohlcv``: pass ``start``/``end`` for
    historical-window queries, otherwise legacy ``period`` semantics apply.
    """
    data = fetch_ohlcv(["SPY"], period=period, start=start, end=end)
    if "SPY" in data:
        return data["SPY"]
    return pd.DataFrame()
