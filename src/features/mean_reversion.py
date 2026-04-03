"""Mean reversion feature engine — RSI(2) Connors-style scanner.

Identifies extreme oversold conditions in quality stocks above their
200 EMA for mean reversion paper trading (Strategy #2).

Called by: scheduler.watch
Calls: features.indicators, data_ingestion.market_data
Owns tables: none
Config keys: strategies.mean_reversion.*
Tests: tests/test_mean_reversion.py
"""

import logging

import pandas as pd

from src.features.indicators import (
    compute_atr,
    compute_bollinger_position,
    compute_ema,
    compute_rsi,
)

logger = logging.getLogger(__name__)


def compute_mr_features(ticker: str, ohlcv: pd.DataFrame,
                        config: dict | None = None) -> dict | None:
    """Compute mean reversion features for a single ticker.

    Returns feature dict if the ticker qualifies for MR scanning,
    None if insufficient data.
    """
    if ohlcv is None or len(ohlcv) < 200:
        return None

    cfg = (config or {}).get("strategies", {}).get("mean_reversion", {})
    rsi_period = cfg.get("rsi_period", 2)
    rsi_entry = cfg.get("rsi_entry_threshold", 10)

    close = ohlcv["Close"]
    high = ohlcv["High"]
    low = ohlcv["Low"]

    rsi_2 = compute_rsi(close, period=rsi_period)
    ema_200 = compute_ema(close, period=200)
    atr_14 = compute_atr(high, low, close, period=14)
    bb_position = compute_bollinger_position(close, period=20)

    # 3-day cumulative return
    if len(close) >= 4:
        cum_return_3d = round(
            (close.iloc[-1] / close.iloc[-4] - 1) * 100, 2
        )
    else:
        cum_return_3d = 0.0

    # Volume spike detection
    if len(ohlcv) >= 20:
        vol = ohlcv["Volume"]
        avg_vol_20 = vol.iloc[-20:].mean()
        volume_ratio = round(vol.iloc[-1] / avg_vol_20, 2) if avg_vol_20 > 0 else 1.0
    else:
        volume_ratio = 1.0

    # Distance from 200 EMA
    last_close = close.iloc[-1]
    distance_from_200ema = round(
        (last_close - ema_200) / ema_200 * 100, 2
    ) if ema_200 > 0 else 0.0

    return {
        "ticker": ticker,
        "rsi_2": rsi_2,
        "ema_200": ema_200,
        "atr_14": atr_14,
        "bollinger_position": bb_position,
        "cum_return_3d": cum_return_3d,
        "volume_ratio": volume_ratio,
        "distance_from_200ema": distance_from_200ema,
        "last_close": round(last_close, 2),
        "above_200ema": last_close > ema_200,
    }


def scan_for_mr_candidates(
    ohlcv_dict: dict[str, pd.DataFrame],
    config: dict | None = None,
) -> list[dict]:
    """Scan universe for mean reversion entry candidates.

    Entry criteria (Connors RSI(2) style):
    1. RSI(2) < entry threshold (default 10)
    2. Price above 200 EMA (quality filter)
    3. Not already in extreme territory for too long

    Returns list of qualified candidates sorted by RSI(2) ascending
    (most oversold first).
    """
    cfg = (config or {}).get("strategies", {}).get("mean_reversion", {})

    if not cfg.get("enabled", False):
        return []

    rsi_entry = cfg.get("rsi_entry_threshold", 10)
    require_above_200ema = cfg.get("require_above_200ema", True)
    max_positions = cfg.get("max_positions", 5)

    candidates = []

    for ticker, df in ohlcv_dict.items():
        try:
            features = compute_mr_features(ticker, df, config)
            if features is None:
                continue

            # Entry filters
            if features["rsi_2"] > rsi_entry:
                continue
            if require_above_200ema and not features["above_200ema"]:
                continue

            candidates.append(features)
        except Exception as e:
            logger.debug("[MR] Feature computation failed for %s: %s", ticker, e)

    # Sort by RSI(2) ascending — most oversold first
    candidates.sort(key=lambda x: x["rsi_2"])

    if len(candidates) > max_positions:
        candidates = candidates[:max_positions]

    logger.info("[MR] Found %d mean reversion candidates", len(candidates))
    return candidates


def compute_mr_exit_signal(
    ticker: str,
    ohlcv: pd.DataFrame,
    entry_price: float,
    config: dict | None = None,
) -> dict | None:
    """Check if a mean reversion position should be exited.

    Exit criteria:
    1. RSI(2) > exit threshold (default 70) — mean reversion target
    2. Stop: price < entry - ATR * stop_multiple (default 2.5)
    3. Timeout: held > max holding days (default 5)

    Returns exit signal dict or None if no exit.
    """
    if ohlcv is None or len(ohlcv) < 3:
        return None

    cfg = (config or {}).get("strategies", {}).get("mean_reversion", {})
    rsi_exit = cfg.get("rsi_exit_threshold", 70)
    stop_multiple = cfg.get("stop_atr_multiple", 2.5)

    close = ohlcv["Close"]
    rsi_2 = compute_rsi(close, period=2)
    atr_14 = compute_atr(ohlcv["High"], ohlcv["Low"], close, period=14)

    last_close = close.iloc[-1]

    # RSI exit
    if rsi_2 > rsi_exit:
        pnl_pct = round((last_close - entry_price) / entry_price * 100, 2)
        return {
            "ticker": ticker,
            "exit_reason": "rsi_exit",
            "rsi_2": rsi_2,
            "exit_price": round(last_close, 2),
            "pnl_pct": pnl_pct,
        }

    # ATR stop
    stop_price = entry_price - (atr_14 * stop_multiple)
    if last_close < stop_price:
        pnl_pct = round((last_close - entry_price) / entry_price * 100, 2)
        return {
            "ticker": ticker,
            "exit_reason": "atr_stop",
            "exit_price": round(last_close, 2),
            "stop_price": round(stop_price, 2),
            "pnl_pct": pnl_pct,
        }

    return None
