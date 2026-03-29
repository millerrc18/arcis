"""Feature engine for pullback-in-trend setup analysis."""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def _slope_direction(series: pd.Series, window: int = 10) -> str:
    """Classify the slope of a series over the last `window` periods."""
    if len(series) < window:
        return "flat"
    recent = series.iloc[-window:]
    diff = recent.iloc[-1] - recent.iloc[0]
    threshold = 0.001 * abs(recent.iloc[0]) if recent.iloc[0] != 0 else 0.01
    if diff > threshold:
        return "positive"
    elif diff < -threshold:
        return "negative"
    return "flat"


def _classify_trend(price: float, sma50: float, sma200: float,
                     sma50_slope: str, sma200_slope: str) -> str:
    """Classify trend state based on price, MAs, and slopes."""
    if price > sma50 > sma200 and sma50_slope == "positive" and sma200_slope == "positive":
        return "strong_uptrend"
    if price > sma50 and sma50 > sma200:
        return "uptrend"
    if price < sma50 < sma200 and sma50_slope == "negative" and sma200_slope == "negative":
        return "strong_downtrend"
    if price < sma50 and sma50 < sma200:
        return "downtrend"
    return "neutral"


def _pct_return(series: pd.Series, periods: int) -> float:
    """Calculate percent return over the last N periods."""
    if len(series) < periods + 1:
        return 0.0
    return (series.iloc[-1] / series.iloc[-periods - 1] - 1) * 100


def _classify_relative_strength(rs_1m: float, rs_3m: float, rs_6m: float) -> str:
    """Classify relative strength state."""
    positive_count = sum(1 for rs in [rs_1m, rs_3m, rs_6m] if rs > 0)
    negative_count = sum(1 for rs in [rs_1m, rs_3m, rs_6m] if rs < 0)

    if positive_count == 3:
        return "strong_outperformer"
    if positive_count >= 2:
        return "outperformer"
    if negative_count == 3:
        return "strong_underperformer"
    if negative_count >= 2:
        return "underperformer"
    return "neutral"


def compute_features(ticker: str, ohlcv: pd.DataFrame, spy: pd.DataFrame) -> dict:
    """Compute all features for a single ticker.

    Args:
        ticker: The ticker symbol.
        ohlcv: DataFrame with Open, High, Low, Close, Volume columns.
        spy: SPY benchmark DataFrame with the same columns.

    Returns:
        A flat dict of computed features.
    """
    close = ohlcv["Close"]
    high = ohlcv["High"]
    low = ohlcv["Low"]
    volume = ohlcv["Volume"]
    current_price = float(close.iloc[-1])

    # Moving averages
    sma_20 = close.rolling(20).mean()
    sma_50 = close.rolling(50).mean()
    sma_200 = close.rolling(200).mean()

    sma_50_val = float(sma_50.iloc[-1])
    sma_200_val = float(sma_200.iloc[-1])
    sma_20_val = float(sma_20.iloc[-1])

    # Percent distance from MAs
    price_vs_sma50_pct = (current_price / sma_50_val - 1) * 100
    price_vs_sma200_pct = (current_price / sma_200_val - 1) * 100
    dist_to_sma20_pct = (current_price / sma_20_val - 1) * 100

    # Slopes
    sma50_slope = _slope_direction(sma_50.dropna())
    sma200_slope = _slope_direction(sma_200.dropna())

    # Trend state
    trend_state = _classify_trend(current_price, sma_50_val, sma_200_val,
                                   sma50_slope, sma200_slope)

    # Relative strength vs SPY
    spy_close = spy["Close"]
    ticker_ret_1m = _pct_return(close, 21)
    spy_ret_1m = _pct_return(spy_close, 21)
    ticker_ret_3m = _pct_return(close, 63)
    spy_ret_3m = _pct_return(spy_close, 63)
    ticker_ret_6m = _pct_return(close, 126)
    spy_ret_6m = _pct_return(spy_close, 126)

    rs_vs_spy_1m = ticker_ret_1m - spy_ret_1m
    rs_vs_spy_3m = ticker_ret_3m - spy_ret_3m
    rs_vs_spy_6m = ticker_ret_6m - spy_ret_6m

    relative_strength_state = _classify_relative_strength(rs_vs_spy_1m, rs_vs_spy_3m, rs_vs_spy_6m)

    # Pullback depth: decline from 50-day high
    high_50d = float(close.iloc[-50:].max())
    pullback_depth_pct = (current_price / high_50d - 1) * 100

    # ATR (14-day)
    tr_high_low = high - low
    tr_high_prev = (high - close.shift(1)).abs()
    tr_low_prev = (low - close.shift(1)).abs()
    true_range = pd.concat([tr_high_low, tr_high_prev, tr_low_prev], axis=1).max(axis=1)
    atr_14 = float(true_range.rolling(14).mean().iloc[-1])
    atr_pct = atr_14 / current_price * 100

    # Volume ratio
    avg_vol_20d = float(volume.rolling(20).mean().iloc[-1])
    last_vol = float(volume.iloc[-1])
    volume_ratio_20d = last_vol / avg_vol_20d if avg_vol_20d > 0 else 1.0

    return {
        "ticker": ticker,
        "current_price": current_price,
        "sma_50": sma_50_val,
        "sma_200": sma_200_val,
        "price_vs_sma50_pct": round(price_vs_sma50_pct, 2),
        "price_vs_sma200_pct": round(price_vs_sma200_pct, 2),
        "sma50_slope": sma50_slope,
        "sma200_slope": sma200_slope,
        "trend_state": trend_state,
        "rs_vs_spy_1m": round(rs_vs_spy_1m, 2),
        "rs_vs_spy_3m": round(rs_vs_spy_3m, 2),
        "rs_vs_spy_6m": round(rs_vs_spy_6m, 2),
        "relative_strength_state": relative_strength_state,
        "pullback_depth_pct": round(pullback_depth_pct, 2),
        "atr_14": round(atr_14, 4),
        "atr_pct": round(atr_pct, 2),
        "dist_to_sma20_pct": round(dist_to_sma20_pct, 2),
        "volume_ratio_20d": round(volume_ratio_20d, 2),
        # Earnings fields — populated by compute_all_features after this call
        "earnings_date": None,
        "hold_overlaps_earnings": False,
        "days_to_earnings": None,
        "event_risk_level": "none",
    }


def compute_all_features(ohlcv_data: dict[str, pd.DataFrame],
                          spy: pd.DataFrame) -> dict[str, dict]:
    """Compute features for all tickers in the OHLCV data dict.

    Skips tickers with fewer than 200 rows of data.
    Adds earnings date, event-risk classification, and market regime for each ticker.
    """
    from src.features.earnings import get_next_earnings_date, check_earnings_overlap
    from src.features.regime import compute_market_regime

    # Compute market regime ONCE for all tickers
    try:
        regime = compute_market_regime(spy, ohlcv_data)
    except Exception as e:
        logger.warning("Failed to compute market regime: %s", e)
        regime = {}

    # Load options metrics ONCE for all tickers
    options_data = _load_options_metrics()

    # Load event proximity features ONCE
    event_features = _load_event_proximity()

    # Load sector profiles ONCE
    sector_profiles = _load_sector_profiles()

    results = {}
    for ticker, df in ohlcv_data.items():
        if len(df) < 200:
            logger.warning("%s has only %d rows (need 200+), skipping", ticker, len(df))
            continue
        try:
            feat = compute_features(ticker, df, spy)

            # Earnings lookup and event-risk classification
            earnings_date = get_next_earnings_date(ticker)
            earnings_info = check_earnings_overlap(earnings_date)
            feat["earnings_date"] = earnings_info["earnings_date"]
            feat["hold_overlaps_earnings"] = earnings_info["hold_overlaps_earnings"]
            feat["days_to_earnings"] = earnings_info["days_to_earnings"]
            feat["event_risk_level"] = earnings_info["event_risk_level"]

            # Merge market regime into every ticker's features
            feat.update(regime)

            # Options metrics (9A)
            if ticker in options_data:
                feat.update(options_data[ticker])

            # Event proximity (9B) — same for all tickers
            feat.update(event_features)

            # Sector conditioning (9C)
            _add_sector_features(feat, ticker, sector_profiles)

            # Setup classification (Workstream 5)
            try:
                from src.features.setup_classifier import classify_setup, log_setup_signal
                classification = classify_setup(feat, df)
                feat["setup_type"] = classification["setup_type"]
                feat["setup_confidence"] = classification["confidence"]
                feat["setup_desk"] = classification["tradeable_by_desk"]
                log_setup_signal(ticker, classification, feat,
                                 regime=regime.get("regime_label", ""))
            except Exception as e:
                logger.debug("Setup classification failed for %s: %s", ticker, e)
                feat["setup_type"] = "unknown"
                feat["setup_confidence"] = 0.0
                feat["setup_desk"] = "none"

            results[ticker] = feat
        except Exception as e:
            logger.warning("Failed to compute features for %s: %s", ticker, e)
    return results


def _load_options_metrics() -> dict[str, dict]:
    """Load latest options metrics per ticker from the database."""
    import sqlite3
    result = {}
    try:
        with sqlite3.connect("ai_research_desk.sqlite3") as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT ticker, iv_rank, pc_vol_ratio, pc_oi_ratio,
                          iv_skew, unusual_flag
                   FROM options_metrics
                   WHERE collected_at = (SELECT MAX(collected_at) FROM options_metrics)"""
            ).fetchall()
            for row in rows:
                result[row["ticker"]] = {
                    "iv_rank": row["iv_rank"],
                    "put_call_vol_ratio": row["pc_vol_ratio"],
                    "put_call_oi_ratio": row["pc_oi_ratio"],
                    "iv_skew": row["iv_skew"],
                    "unusual_options_activity": bool(row["unusual_flag"]),
                }
    except Exception as e:
        logger.debug("Options metrics not available: %s", e)
    return result


def _load_event_proximity() -> dict:
    """Load event proximity features (shared across all tickers)."""
    try:
        from src.features.event_proximity import get_event_proximity_features
        return get_event_proximity_features()
    except Exception as e:
        logger.debug("Event proximity not available: %s", e)
        return {
            "event_proximity_type": None,
            "event_proximity_days": None,
            "event_proximity_desc": None,
            "events_within_3d": 0,
        }


def _load_sector_profiles() -> dict:
    """Load sector profiles from JSON reference file."""
    import json
    from pathlib import Path

    path = Path("data/reference/sector_profiles.json")
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.debug("Sector profiles not available: %s", e)
        return {}


def _add_sector_features(feat: dict, ticker: str, sector_profiles: dict):
    """Add GICS sector and sector-specific context to feature dict."""
    try:
        from src.universe.sectors import SECTOR_MAP
        sector = SECTOR_MAP.get(ticker, "Unknown")
        feat["sector"] = sector

        profile = sector_profiles.get(sector, {})
        feat["sector_pullback_depth"] = profile.get("typical_pullback_depth", "n/a")
        feat["sector_recovery_speed"] = profile.get("recovery_speed", "n/a")
        feat["sector_key_factors"] = profile.get("key_factors", [])
    except Exception:
        feat["sector"] = "Unknown"
        feat["sector_pullback_depth"] = "n/a"
        feat["sector_recovery_speed"] = "n/a"
        feat["sector_key_factors"] = []
