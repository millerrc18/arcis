"""Market regime indicators: SPY trend, volatility, breadth, RSI, sector context.

Called by: features.engine, ranking.ranker, scheduler.watch, training.historical_scanner
Calls: features.engine, universe.sectors
Owns tables: none
Config keys: none
Tests: tests/test_regime.py
"""

import numpy as np
import pandas as pd

from src.features.engine import _slope_direction
from src.features.indicators import compute_rsi as _compute_rsi


def _classify_volatility(realized_vol: float) -> str:
    """Classify volatility regime from 20-day realized vol (annualized)."""
    if realized_vol < 12:
        return "low"
    elif realized_vol <= 20:
        return "normal"
    elif realized_vol <= 30:
        return "elevated"
    else:
        return "extreme"


def _classify_market_trend(
    price: float, sma50: float, sma200: float,
    sma50_slope: str, sma200_slope: str,
) -> str:
    """Classify broad market trend from SPY."""
    if price > sma50 > sma200 and sma50_slope == "positive" and sma200_slope == "positive":
        return "strong_uptrend"
    if price > sma50 and sma50 > sma200:
        return "uptrend"
    if price < sma50 < sma200 and sma50_slope == "negative" and sma200_slope == "negative":
        return "strong_downtrend"
    if price < sma50 and sma50 < sma200:
        return "downtrend"
    return "neutral"


def compute_market_regime(spy: pd.DataFrame, ohlcv_data: dict[str, pd.DataFrame]) -> dict:
    """Compute market-wide regime indicators from SPY and universe data.

    Returns dict with keys:
        market_trend, volatility_regime, vix_proxy, spy_rsi_14,
        spy_above_sma50, spy_above_sma200, spy_sma50_slope,
        spy_drawdown_from_high, spy_20d_return, market_breadth_pct,
        market_breadth_label, regime_label
    """
    close = spy["Close"]
    current_price = float(close.iloc[-1])

    # Moving averages
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    sma50_val = float(sma50.iloc[-1])
    sma200_val = float(sma200.iloc[-1])

    sma50_slope = _slope_direction(sma50.dropna())
    sma200_slope = _slope_direction(sma200.dropna())

    # Market trend
    market_trend = _classify_market_trend(
        current_price, sma50_val, sma200_val, sma50_slope, sma200_slope
    )

    # Volatility: 20-day realized vol, annualized
    daily_returns = close.pct_change().dropna()
    realized_vol_20d = float(daily_returns.iloc[-20:].std() * np.sqrt(252) * 100)
    volatility_regime = _classify_volatility(realized_vol_20d)

    # RSI
    spy_rsi_14 = _compute_rsi(close, 14)

    # SPY above MAs
    spy_above_sma50 = current_price > sma50_val
    spy_above_sma200 = current_price > sma200_val

    # Drawdown from 252-day high
    high_252d = float(close.iloc[-252:].max()) if len(close) >= 252 else float(close.max())
    spy_drawdown = round((current_price / high_252d - 1) * 100, 2)

    # 20-day return
    spy_20d_return = round((current_price / float(close.iloc[-21]) - 1) * 100, 2) if len(close) >= 21 else 0.0

    # Breadth: % of universe above own 50-day SMA
    above_sma50_count = 0
    total_count = 0
    for ticker, df in ohlcv_data.items():
        if len(df) < 50:
            continue
        ticker_close = df["Close"]
        ticker_sma50 = float(ticker_close.rolling(50).mean().iloc[-1])
        ticker_price = float(ticker_close.iloc[-1])
        total_count += 1
        if ticker_price > ticker_sma50:
            above_sma50_count += 1

    market_breadth_pct = round(above_sma50_count / total_count * 100, 1) if total_count > 0 else 50.0

    if market_breadth_pct >= 65:
        market_breadth_label = "healthy"
    elif market_breadth_pct >= 40:
        market_breadth_label = "narrowing"
    else:
        market_breadth_label = "weak"

    # Regime label compositing
    is_uptrend = market_trend in ("strong_uptrend", "uptrend")
    is_downtrend = market_trend in ("strong_downtrend", "downtrend")
    is_volatile = volatility_regime in ("elevated", "extreme")

    if is_uptrend and not is_volatile:
        regime_label = "calm_uptrend"
    elif is_uptrend and is_volatile:
        regime_label = "volatile_uptrend"
    elif is_downtrend and not is_volatile:
        regime_label = "calm_downtrend"
    elif is_downtrend and is_volatile:
        regime_label = "volatile_downtrend"
    else:
        regime_label = "transitional"

    return {
        "market_trend": market_trend,
        "volatility_regime": volatility_regime,
        "vix_proxy": round(realized_vol_20d, 1),
        "spy_rsi_14": spy_rsi_14,
        "spy_above_sma50": spy_above_sma50,
        "spy_above_sma200": spy_above_sma200,
        "spy_sma50_slope": sma50_slope,
        "spy_drawdown_from_high": spy_drawdown,
        "spy_20d_return": spy_20d_return,
        "market_breadth_pct": market_breadth_pct,
        "market_breadth_label": market_breadth_label,
        "regime_label": regime_label,
    }


def classify_regime(regime_data: dict) -> str:
    """Classify current market into one of 7 categorical regime types.

    Uses the raw regime data from compute_market_regime() to produce a
    higher-level classification for threshold and sizing decisions.

    Returns one of:
        BULL_LOW_VOL, BULL_HIGH_VOL, TRANSITION, CORRECTION,
        BEAR_EARLY, BEAR_ESTABLISHED, CRISIS
    """
    vix_proxy = regime_data.get("vix_proxy", 15)
    spy_above_200 = regime_data.get("spy_above_sma200", True)
    spy_above_50 = regime_data.get("spy_above_sma50", True)
    regime_label = regime_data.get("regime_label", "transitional")
    drawdown = regime_data.get("spy_drawdown_from_high", 0)
    breadth_pct = regime_data.get("market_breadth_pct", 50)

    # Crisis: VIX > 35 or drawdown > 20%
    if vix_proxy > 35 or drawdown < -20:
        return "CRISIS"

    # Bear established: below both MAs, drawdown > 15%
    if not spy_above_200 and not spy_above_50 and drawdown < -15:
        return "BEAR_ESTABLISHED"

    # Bear early: below 200MA, drawdown 10-15%
    if not spy_above_200 and drawdown < -10:
        return "BEAR_EARLY"

    # Correction: VIX 25-35, drawdown 5-10%
    if vix_proxy > 25 and drawdown < -5:
        return "CORRECTION"

    # Transition: VIX 20-35 grinding, narrow breadth, or mixed signals
    if regime_label == "transitional" or (vix_proxy > 20 and breadth_pct < 40):
        return "TRANSITION"

    # Bull with elevated vol
    if spy_above_200 and spy_above_50 and vix_proxy > 20:
        return "BULL_HIGH_VOL"

    # Bull low vol — default when everything looks good
    if spy_above_200 and spy_above_50:
        return "BULL_LOW_VOL"

    return "TRANSITION"


def compute_sector_context(ticker: str, score: float, all_features: dict) -> dict:
    """Compare ticker against its sector peers.

    Returns:
        sector, sector_rs_rank, sector_avg_score, sector_peer_count
    """
    from src.universe.sectors import SECTOR_MAP

    sector = SECTOR_MAP.get(ticker, "Unknown")

    # Find peers in same sector
    peer_scores = []
    for t, feat in all_features.items():
        if SECTOR_MAP.get(t) == sector:
            peer_score = feat.get("_score", 0)
            peer_scores.append((t, peer_score))

    if not peer_scores:
        return {
            "sector": sector,
            "sector_rs_rank": "unknown",
            "sector_avg_score": 0.0,
            "sector_peer_count": 0,
        }

    peer_scores.sort(key=lambda x: -x[1])
    sector_avg = sum(s for _, s in peer_scores) / len(peer_scores)
    rank_pos = next((i for i, (t, _) in enumerate(peer_scores) if t == ticker), len(peer_scores))
    pct = rank_pos / len(peer_scores) if peer_scores else 1.0

    if pct <= 0.25:
        rank_label = "top_quartile"
    elif pct <= 0.5:
        rank_label = "upper_half"
    elif pct <= 0.75:
        rank_label = "lower_half"
    else:
        rank_label = "bottom_quartile"

    return {
        "sector": sector,
        "sector_rs_rank": rank_label,
        "sector_avg_score": round(sector_avg, 1),
        "sector_peer_count": len(peer_scores),
    }
