"""Shared technical indicator utilities.

Provides reusable indicator calculations used across feature modules.
Avoids code duplication between regime.py, setup_classifier.py, and
mean_reversion.py.

Called by: features.regime, features.setup_classifier, features.mean_reversion
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_indicators.py
"""

import pandas as pd


def compute_rsi(close: pd.Series, period: int = 14) -> float:
    """Compute RSI for the most recent value.

    Args:
        close: Series of close prices (oldest first).
        period: RSI lookback period (default 14, use 2 for Connors RSI).

    Returns:
        RSI value 0-100, or 50.0 if insufficient data.
    """
    if len(close) < period + 1:
        return 50.0
    # Flatten MultiIndex columns from yfinance if needed
    if hasattr(close, 'columns'):
        close = close.iloc[:, 0]
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta.clip(upper=0))
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    last_gain = float(avg_gain.iloc[-1])
    last_loss = float(avg_loss.iloc[-1])
    if last_loss == 0:
        return 100.0
    rs = last_gain / last_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def compute_ema(close: pd.Series, period: int) -> float:
    """Compute the most recent EMA value."""
    if hasattr(close, 'columns'):
        close = close.iloc[:, 0]
    if len(close) < period:
        return float(close.iloc[-1]) if len(close) > 0 else 0.0
    return round(float(close.ewm(span=period, adjust=False).mean().iloc[-1]), 4)


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series,
                period: int = 14) -> float:
    """Compute Average True Range for the most recent value."""
    if hasattr(close, 'columns'):
        close = close.iloc[:, 0]
    if hasattr(high, 'columns'):
        high = high.iloc[:, 0]
    if hasattr(low, 'columns'):
        low = low.iloc[:, 0]
    if len(close) < period + 1:
        return 0.0
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()
    val = atr.iloc[-1]
    return round(float(val), 4) if not pd.isna(val) else 0.0


def compute_bollinger_position(close: pd.Series, period: int = 20,
                                num_std: float = 2.0) -> float:
    """Compute position within Bollinger Bands (0 = lower, 1 = upper)."""
    if hasattr(close, 'columns'):
        close = close.iloc[:, 0]
    if len(close) < period:
        return 0.5
    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = sma + num_std * std
    lower = sma - num_std * std
    last_upper = float(upper.iloc[-1])
    last_lower = float(lower.iloc[-1])
    if last_upper == last_lower:
        return 0.5
    return round((float(close.iloc[-1]) - last_lower) / (last_upper - last_lower), 4)
