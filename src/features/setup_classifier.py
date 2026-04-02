"""Rule-based setup type classifier for equity trades.

Called by: features.engine
Calls: none
Owns tables: setup_signals
Config keys: none
Tests: tests/test_setup_classifier.py

Uses 5 discriminative features (ADX, ATR/price ratio, volume profile,
price vs MAs, RSI) to classify every scanned stock into one of 6
setup types. Each classification includes confidence and desk routing.

Reference: Multi-Strategy Pattern Classification for Equity Trading research.
"""

import logging
import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def _compute_adx(high: pd.Series, low: pd.Series, close: pd.Series,
                 period: int = 14) -> float:
    """Compute ADX (Average Directional Index) for trend strength."""
    if len(close) < period * 2:
        return 20.0  # neutral default

    # True Range
    tr_hl = high - low
    tr_hpc = (high - close.shift(1)).abs()
    tr_lpc = (low - close.shift(1)).abs()
    tr = pd.concat([tr_hl, tr_hpc, tr_lpc], axis=1).max(axis=1)

    # Directional Movement
    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    # Smoothed averages
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)

    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1))
    adx = dx.rolling(period).mean()

    val = adx.iloc[-1]
    return float(val) if pd.notna(val) else 20.0


def _compute_rsi(close: pd.Series, period: int = 14) -> float:
    """Compute RSI for the most recent value."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    last_loss = loss.iloc[-1]
    if last_loss == 0:
        return 100.0
    rs = gain.iloc[-1] / last_loss
    return round(100 - (100 / (1 + rs)), 1)


def _volume_profile(volume: pd.Series) -> str:
    """Classify recent volume pattern."""
    if len(volume) < 20:
        return "normal"
    recent_5d = volume.iloc[-5:].mean()
    avg_20d = volume.iloc[-20:].mean()
    if avg_20d == 0:
        return "normal"
    ratio = recent_5d / avg_20d
    if ratio > 1.5:
        return "expanding"
    elif ratio < 0.7:
        return "declining"
    return "normal"


def classify_setup(features: dict, ohlcv: pd.DataFrame | None = None) -> dict:
    """Classify the current setup type for a stock.

    Uses 5 discriminative features:
    1. ADX (trend strength): >25 = trending, <20 = ranging
    2. ATR/price ratio (normalized volatility)
    3. Volume profile: declining on retracement vs expanding on breakout
    4. Price vs MAs: above 200MA pulling to 50MA = pullback
    5. RSI context: 30-50 in uptrend = pullback, <25 = extreme mean reversion

    Args:
        features: Feature dict from the feature engine (must have trend_state,
                  price_vs_sma50_pct, price_vs_sma200_pct, etc.)
        ohlcv: Optional raw OHLCV DataFrame for computing ADX if not in features.

    Returns:
        {
            "setup_type": "pullback" | "breakout" | "momentum" | "mean_reversion" | "range_bound" | "breakdown",
            "confidence": 0.0-1.0,
            "features_used": {"adx": 32.5, ...},
            "tradeable_by_desk": "equity_swing" | "equity_momentum" | "none"
        }
    """
    # Extract or compute features
    adx = features.get("adx")
    rsi = features.get("rsi_14")
    vol_profile = features.get("volume_profile")

    if ohlcv is not None and adx is None:
        adx = _compute_adx(ohlcv["High"], ohlcv["Low"], ohlcv["Close"])

    if ohlcv is not None and rsi is None:
        rsi = _compute_rsi(ohlcv["Close"])

    if ohlcv is not None and vol_profile is None:
        vol_profile = _volume_profile(ohlcv["Volume"])

    # Defaults
    adx = adx or 20.0
    rsi = rsi or 50.0
    vol_profile = vol_profile or "normal"
    atr_ratio = features.get("atr_pct", 1.5)

    price_vs_200 = features.get("price_vs_sma200_pct", 0)
    price_vs_50 = features.get("price_vs_sma50_pct", 0)
    sma200_slope = features.get("sma200_slope", "flat")
    trend = features.get("trend_state", "neutral")

    features_used = {
        "adx": round(adx, 1),
        "rsi": round(rsi, 1),
        "atr_ratio": round(atr_ratio, 2),
        "volume_profile": vol_profile,
        "price_vs_200ma": round(price_vs_200, 1),
        "price_vs_50ma": round(price_vs_50, 1),
    }

    # Classification rules (ordered by specificity)
    setup_type = "range_bound"
    confidence = 0.5
    desk = "none"

    # Breakdown: strong downtrend, expanding volume, below both MAs
    if (trend in ("strong_downtrend", "downtrend") and adx > 25
            and price_vs_200 < 0 and sma200_slope == "negative"
            and rsi < 35):
        setup_type = "breakdown"
        confidence = min(0.95, 0.6 + (adx - 25) / 50)
        desk = "none"

    # Mean reversion: extreme oversold
    elif rsi < 25 and price_vs_200 < 0 and vol_profile in ("expanding", "normal"):
        setup_type = "mean_reversion"
        confidence = min(0.9, 0.5 + (25 - rsi) / 50)
        desk = "equity_swing"

    # Pullback in uptrend: ADX > 25, above 200MA, pulling back to 50MA
    elif (trend in ("strong_uptrend", "uptrend") and adx > 25
          and price_vs_200 > 0 and -15 < price_vs_50 < 2
          and vol_profile in ("declining", "normal")
          and 30 <= rsi <= 55):
        setup_type = "pullback"
        confidence = min(0.95, 0.6 + (adx - 25) / 40)
        desk = "equity_swing"

    # Breakout: low ADX rising, price breaking above range, expanding volume
    elif (adx < 25 and price_vs_50 > 0 and vol_profile == "expanding"
          and 50 <= rsi <= 65):
        setup_type = "breakout"
        confidence = min(0.9, 0.5 + (0.3 if vol_profile == "expanding" else 0))
        desk = "equity_momentum"

    # Momentum: strong trend, well above MAs, sustained volume
    elif (adx > 30 and price_vs_200 > 5 and price_vs_50 > 0
          and 55 <= rsi <= 75):
        setup_type = "momentum"
        confidence = min(0.9, 0.5 + (adx - 30) / 40)
        desk = "equity_momentum"

    # Range bound: low ADX, oscillating, low volume
    elif adx < 20 and 40 <= rsi <= 60:
        setup_type = "range_bound"
        confidence = 0.6
        desk = "none"

    return {
        "setup_type": setup_type,
        "confidence": round(confidence, 2),
        "features_used": features_used,
        "tradeable_by_desk": desk,
    }


def log_setup_signal(ticker: str, classification: dict, features: dict,
                     regime: str = "", db_path: str = DB_PATH):
    """Store a setup classification in the signal zoo table."""
    _ensure_setup_signals_table(db_path)

    signal_id = str(uuid.uuid4())[:8]
    now = datetime.now(ET)

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """INSERT INTO setup_signals
                   (signal_id, created_at, ticker, date, setup_type, confidence,
                    theoretical_entry, theoretical_stop, theoretical_target,
                    regime, adx, atr_ratio, rsi, volume_profile)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    signal_id,
                    now.isoformat(),
                    ticker,
                    now.strftime("%Y-%m-%d"),
                    classification["setup_type"],
                    classification["confidence"],
                    features.get("current_price"),
                    None,  # theoretical_stop — filled by packet builder
                    None,  # theoretical_target
                    regime,
                    classification["features_used"].get("adx"),
                    classification["features_used"].get("atr_ratio"),
                    classification["features_used"].get("rsi"),
                    classification["features_used"].get("volume_profile"),
                ),
            )
    except Exception as e:
        logger.debug("Failed to log setup signal: %s", e)


def _ensure_setup_signals_table(db_path: str = DB_PATH):
    """Create the setup_signals table if it doesn't exist."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS setup_signals (
                    signal_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    date TEXT NOT NULL,
                    setup_type TEXT NOT NULL,
                    confidence REAL,
                    theoretical_entry REAL,
                    theoretical_stop REAL,
                    theoretical_target REAL,
                    regime TEXT,
                    adx REAL,
                    atr_ratio REAL,
                    rsi REAL,
                    volume_profile TEXT,
                    actual_return_1d REAL,
                    actual_return_5d REAL,
                    actual_return_10d REAL,
                    actual_return_20d REAL,
                    was_traded INTEGER DEFAULT 0
                )
            """)
    except Exception as e:
        logger.debug("setup_signals table creation error: %s", e)
