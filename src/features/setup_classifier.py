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

WHY rule-based classification instead of ML:
    With <200 closed trades, there is not enough labeled data to train a
    reliable setup classifier. Rules derived from well-established technical
    analysis principles (ADX for trend strength, RSI for momentum) provide
    a deterministic, auditable baseline. Once the signal zoo (setup_signals
    table) accumulates enough classified examples with known outcomes, a
    learned classifier can be trained and compared against these rules as
    a champion-challenger experiment.

WHY 6 setup types:
    - pullback: the primary strategy -- trend continuation after retracement
    - breakout: range expansion with volume confirmation
    - momentum: existing trend acceleration (higher conviction, tighter stops)
    - mean_reversion: extreme oversold in non-trending stock
    - range_bound: no trend, oscillating -- not tradeable, logged for reference
    - breakdown: bearish equivalent of breakout -- not tradeable long, but
      logged to avoid buying "pullbacks" that are actually breakdowns

WHY desk routing:
    equity_swing handles pullback and mean_reversion (hold 3-10 days),
    equity_momentum handles breakout and momentum (hold 1-5 days),
    "none" means the setup is not actionable by any desk (range_bound,
    breakdown). This routing feeds into the scan service's filtering logic.
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
    """Compute ADX (Average Directional Index) for trend strength.

    WHY ADX is the primary discriminator: ADX measures trend STRENGTH
    independent of direction. A high ADX (>25) means the stock is moving
    directionally -- essential for distinguishing pullbacks (trending +
    retracement) from range-bound oscillation (no trend + retracement).
    Without ADX, a stock at its 50-day MA looks identical whether it is
    trending or chopping.

    WHY default to 20.0 on insufficient data: 20 is the boundary between
    "no trend" and "weak trend" -- a neutral assumption when we cannot
    compute the actual value. This prevents small-data stocks from being
    misclassified as strongly trending.
    """
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
    """Compute RSI for the most recent value (delegates to shared utility)."""
    from src.features.indicators import compute_rsi
    return compute_rsi(close, period)


def _volume_profile(volume: pd.Series) -> str:
    """Classify recent volume pattern.

    WHY 5-day vs 20-day comparison: the 5-day window captures the current
    pullback's volume signature, while 20-day is the baseline. A healthy
    pullback shows DECLINING volume (sellers exhausted), while distribution
    shows EXPANDING volume (institutions selling). This is one of the most
    discriminative features for separating buyable pullbacks from breakdowns.

    WHY 1.5x/0.7x thresholds: these are standard technical analysis
    conventions for "significant" volume changes. Below 0.7x = drying up,
    above 1.5x = notably heavy. The range between is normal variation.
    """
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

    # Classification rules (ordered by specificity -- most restrictive first).
    # WHY this order matters: a stock can match multiple patterns. A strong
    # downtrend with RSI<25 matches both "breakdown" and "mean_reversion."
    # By checking breakdown first (requires downtrend + ADX>25 + below 200MA
    # + negative slope + RSI<35), we correctly classify bearish collapses.
    # Mean reversion only fires when the stock is oversold WITHOUT strong
    # directional momentum -- a different and less dangerous pattern.
    setup_type = "range_bound"
    confidence = 0.5
    desk = "none"

    # Breakdown: strong downtrend, expanding volume, below both MAs.
    # WHY desk="none": breakdowns are logged for awareness (avoid buying
    # "pullbacks" that are actually breakdowns) but are not tradeable long.
    if (trend in ("strong_downtrend", "downtrend") and adx > 25
            and price_vs_200 < 0 and sma200_slope == "negative"
            and rsi < 35):
        setup_type = "breakdown"
        confidence = min(0.95, 0.6 + (adx - 25) / 50)
        desk = "none"

    # Mean reversion: extreme oversold without strong trending.
    # WHY RSI<25 (not the common 30): RSI 25-30 in a downtrend is often
    # just "oversold and getting more oversold." Below 25 is the extreme
    # that historically produces snapback rallies even in weak markets.
    elif rsi < 25 and price_vs_200 < 0 and vol_profile in ("expanding", "normal"):
        setup_type = "mean_reversion"
        confidence = min(0.9, 0.5 + (25 - rsi) / 50)
        desk = "equity_swing"

    # Pullback in uptrend: the primary strategy's target setup.
    # WHY -15 < price_vs_50 < 2: the stock must be near or slightly below
    # its 50-day MA (-15% catches deep pullbacks, +2% catches stocks just
    # starting to pull back). Below -15% the pullback is too deep -- likely
    # a trend change, not a retracement.
    # WHY RSI 30-55: below 30 is oversold (mean_reversion territory), above
    # 55 hasn't pulled back enough (momentum or chasing).
    # WHY declining or normal volume: expanding volume during a pullback
    # signals distribution (institutions selling), not healthy retracement.
    elif (trend in ("strong_uptrend", "uptrend") and adx > 25
          and price_vs_200 > 0 and -15 < price_vs_50 < 2
          and vol_profile in ("declining", "normal")
          and 30 <= rsi <= 55):
        setup_type = "pullback"
        confidence = min(0.95, 0.6 + (adx - 25) / 40)
        desk = "equity_swing"

    # Breakout: low ADX (range-bound) transitioning to directional, with
    # expanding volume confirming the breakout is real.
    # WHY ADX<25: a breakout by definition starts from a non-trending state.
    # If ADX is already >25, the stock is already trending (momentum, not breakout).
    elif (adx < 25 and price_vs_50 > 0 and vol_profile == "expanding"
          and 50 <= rsi <= 65):
        setup_type = "breakout"
        confidence = min(0.9, 0.5 + (0.3 if vol_profile == "expanding" else 0))
        desk = "equity_momentum"

    # Momentum: strong existing trend acceleration -- higher conviction but
    # the easy move is behind us. Tighter stops than pullback setups.
    # WHY ADX>30 (stricter than pullback's 25): momentum requires STRONG
    # directional movement, not just "present." The higher bar prevents
    # misclassifying weak trends as momentum.
    elif (adx > 30 and price_vs_200 > 5 and price_vs_50 > 0
          and 55 <= rsi <= 75):
        setup_type = "momentum"
        confidence = min(0.9, 0.5 + (adx - 30) / 40)
        desk = "equity_momentum"

    # Range bound: low ADX, oscillating RSI, no directional bias.
    # WHY desk="none": range-bound stocks are not actionable for trend-
    # following strategies. Logged for the signal zoo but not traded.
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
    """Store a setup classification in the signal zoo table.

    WHY log every classification, not just traded setups: the signal zoo
    accumulates all classified setups (traded and not-traded) so that
    future analysis can measure opportunity cost ("we passed on this
    breakout that would have been a 12% winner") and refine the
    classifier's thresholds based on known outcomes.
    """
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
    """No-op: table provisioning handled by src/schema/registry.py at startup.

    WHY this no-op exists: originally contained DDL, but the schema registry
    migration (PR #189) moved all table definitions to registry.py. The
    function is kept as a no-op because call sites still reference it and
    removing it would require a coordinated multi-file change for zero
    behavioral benefit.
    """
    pass
