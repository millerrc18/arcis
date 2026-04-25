"""Pullback logistic regression feature extractors.

Called by: T2.14b (model wiring — not yet implemented)
Calls: src.features.indicators
Owns tables: none
Config keys: none
Tests: tests/features/test_pullback_logistic.py

Pure-function feature extractors over OHLCV data for the pullback
logistic regression signal redesign.  Each function accepts a pandas
DataFrame (Open, High, Low, Close, Volume, date-indexed) and returns a
scalar float.  The top-level function `extract_pullback_features` returns
a dict{feature_name: float} for a single ticker as-of the last row.

SIGN CONVENTIONS (more-bullish → larger value unless noted):
  pullback_depth_pct:    0 at peak; goes negative as price falls; mild
                         negative (-3 to -5) is the bullish sweet spot;
                         large negative (< -15) is bearish.
  dist_from_sma20_pct:   positive = above SMA20 (bullish bias); negative
                         = below (healthy pullback if small, bearish if large).
  dist_from_sma50_pct:   same sign convention as dist_from_sma20_pct.
  volume_ratio_20d:      < 1.0 on a pullback = declining volume (bullish);
                         > 1.5 = heavy selling (bearish).
  rsi_14:                35–55 = pullback zone (bullish); < 30 = oversold;
                         > 60 = extended (not yet pulled back).
  atr_pct:               normalised daily range; higher = more volatile.
                         Direction-neutral; useful as a scaling feature.
  prior_n_day_drawdown:  return from rolling 5-day peak to current close;
                         negative = price is below recent peak.
  up_days_in_5:          count of up-close days in last 5 bars (0–5);
                         higher is more bullish (momentum confirmation).

WHY no model training or scoring here: this module covers only T2.14a
(feature extraction). Model training is T2.14b; scoring is T2.14c.
"""

import math

import numpy as np
import pandas as pd

from src.features.indicators import compute_rsi, compute_atr

_REQUIRED_COLS = {"Open", "High", "Low", "Close", "Volume"}
_N_DAY_WINDOW = 5   # used for prior_n_day_drawdown and up_days_in_5


def _pullback_depth_pct(close: pd.Series) -> float:
    """Pct distance from the rolling 20-day high to the current close.

    Returns 0 when the close equals the 20-day high; negative when below.
    """
    window = min(20, len(close))
    rolling_high = close.rolling(window).max()
    peak = rolling_high.iloc[-1]
    current = close.iloc[-1]
    if peak == 0:
        return 0.0
    return float(round((current - peak) / peak * 100, 4))


def _dist_from_sma_pct(close: pd.Series, period: int) -> float:
    """Pct distance of the last close from an SMA.

    Returns NaN when there are fewer bars than the SMA period.
    """
    if len(close) < period:
        return float("nan")
    sma = close.rolling(period).mean().iloc[-1]
    if pd.isna(sma) or sma == 0:
        return float("nan")
    return float(round((close.iloc[-1] - sma) / sma * 100, 4))


def _volume_ratio_20d(volume: pd.Series) -> float:
    """Ratio of the last bar's volume to the 20-day average volume.

    Returns 1.0 when there is insufficient history.
    """
    if len(volume) < 20:
        return 1.0
    avg20 = volume.iloc[-20:].mean()
    if avg20 == 0:
        return 1.0
    return float(round(volume.iloc[-1] / avg20, 4))


def _atr_pct(high: pd.Series, low: pd.Series, close: pd.Series) -> float:
    """ATR as a percentage of the last close price.

    Returns 0.0 when there is insufficient data.
    """
    atr = compute_atr(high, low, close, period=14)
    current = float(close.iloc[-1])
    if current == 0:
        return 0.0
    return float(round(atr / current * 100, 4))


def _prior_n_day_drawdown(close: pd.Series, n: int = _N_DAY_WINDOW) -> float:
    """Pct return from the rolling n-day peak to the current close.

    Negative means the close is below the recent peak (drawdown in progress).
    """
    window = min(n, len(close))
    peak = close.rolling(window).max().iloc[-1]
    current = close.iloc[-1]
    if peak == 0:
        return 0.0
    return float(round((current - peak) / peak * 100, 4))


def _up_days_in_5(close: pd.Series, n: int = _N_DAY_WINDOW) -> float:
    """Count of days where close > previous close in the last n bars."""
    if len(close) < 2:
        return 0.0
    tail = close.iloc[-(n + 1):]
    up = (tail.diff() > 0).sum()
    return float(int(up))


def extract_pullback_features(ohlcv: pd.DataFrame) -> dict:
    """Extract all pullback logistic features for a single ticker.

    Args:
        ohlcv: DataFrame with columns Open, High, Low, Close, Volume,
               indexed by date (oldest row first).  Must have ≥ 1 row.

    Returns:
        Dict mapping feature name to float.  Features that require SMA50
        return NaN when fewer than 50 rows are present; all other features
        return finite floats regardless of data length.

    Raises:
        ValueError: if ohlcv is empty.
        TypeError / AttributeError: if ohlcv is not a DataFrame.
    """
    if ohlcv.empty:
        raise ValueError(
            "extract_pullback_features: ohlcv DataFrame is empty — no rows to process."
        )

    close = ohlcv["Close"].astype(float)
    high = ohlcv["High"].astype(float)
    low = ohlcv["Low"].astype(float)
    volume = ohlcv["Volume"].astype(float)

    return {
        "pullback_depth_pct": _pullback_depth_pct(close),
        "dist_from_sma20_pct": _dist_from_sma_pct(close, 20),
        "dist_from_sma50_pct": _dist_from_sma_pct(close, 50),
        "volume_ratio_20d": _volume_ratio_20d(volume),
        "rsi_14": float(compute_rsi(close, 14)),
        "atr_pct": _atr_pct(high, low, close),
        "prior_n_day_drawdown": _prior_n_day_drawdown(close),
        "up_days_in_5": _up_days_in_5(close),
    }
