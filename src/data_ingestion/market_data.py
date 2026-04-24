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


def fetch_ohlcv(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """Fetch daily OHLCV data for a list of tickers.

    Returns a dict mapping ticker -> DataFrame with columns:
    Open, High, Low, Close, Volume, indexed by date.
    Tickers that fail to download are skipped with a warning.
    """
    if not tickers:
        return {}

    # Translate tickers for yfinance compatibility
    download_tickers = [TICKER_MAP.get(t, t) for t in tickers]

    result = {}

    if len(download_tickers) == 1:
        dl_ticker = download_tickers[0]
        orig_ticker = REVERSE_TICKER_MAP.get(dl_ticker, dl_ticker)
        try:
            df = yf.download(dl_ticker, period=period, progress=False, auto_adjust=False)
            if df is not None and not df.empty:
                # Flatten MultiIndex columns if present
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df[["Open", "High", "Low", "Close", "Volume"]]
                result[orig_ticker] = df
            else:
                logger.warning("No data returned for %s", orig_ticker)
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", orig_ticker, e)
        return result

    try:
        raw = yf.download(download_tickers, period=period, progress=False, auto_adjust=False, group_by="ticker")
    except Exception as e:
        logger.warning("Batch download failed: %s", e)
        return result

    if raw is None or raw.empty:
        logger.warning("No data returned from batch download")
        return result

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


def fetch_spy_benchmark(period: str = "1y") -> pd.DataFrame:
    """Fetch daily OHLCV data for SPY benchmark.

    Returns a DataFrame with columns: Open, High, Low, Close, Volume.
    """
    data = fetch_ohlcv(["SPY"], period=period)
    if "SPY" in data:
        return data["SPY"]
    return pd.DataFrame()
