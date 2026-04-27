"""Feature engine for pullback-in-trend setup analysis.

Called by: evaluation.backtester, features.regime, scheduler.premarket, scheduler.watch, services.recap_service, services.scan_service, services.watchlist_service, training.bootstrap, training.historical_scanner
Calls: features.earnings, features.event_proximity, features.regime, features.setup_classifier, universe.sectors
Owns tables: none
Config keys: none
Tests: tests/test_features.py

WHY these specific features:
    The feature set is designed around the 7 signal dimensions of a pullback-
    in-trend setup. Each feature maps to a specific trading question:

    1. TREND (sma50_slope, sma200_slope, trend_state):
       Is the stock in a sustained uptrend? Both slope AND ordering matter --
       price above MAs with negative slopes is a distribution top, not a trend.

    2. RELATIVE STRENGTH (rs_vs_spy_1m/3m/6m, relative_strength_state):
       Is this stock outperforming the market? Three timeframes catch both
       recent momentum (1m) and structural leadership (6m). A stock strong
       on all three is in a different category than one with only recent momentum.

    3. PULLBACK DEPTH (pullback_depth_pct, dist_to_sma20_pct):
       Has the stock pulled back enough to offer entry? Too shallow = chasing,
       too deep = broken trend. The -3% to -8% sweet spot is where pullback
       setups have historically highest win rates.

    4. VOLATILITY (atr_14, atr_pct):
       How much does this stock move? ATR sets stop distance and position size.
       ATR as % of price normalizes across $20 and $200 stocks.

    5. VOLUME (volume_ratio_20d):
       Is the pullback on declining volume (healthy) or expanding volume
       (distribution)? This is one of the most discriminative features for
       pullback quality -- see setup_classifier.py.

    6. EVENT RISK (earnings_date, hold_overlaps_earnings, event_risk_level):
       Will an earnings report or macro event hit during the expected hold?
       Martineau (2022) showed PEAD is dead for large-cap, but binary event
       risk (gap risk) remains a real position-sizing concern.

    7. REGIME (market_trend, volatility_regime, breadth, regime_label):
       What is the broad market doing? Pullback setups in bear markets have
       <40% win rates regardless of individual stock quality. Regime features
       come from features/regime.py and are merged into every ticker's dict.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING

import pandas as pd

from src.features.indicators import _slope_direction

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.platform.strategy_spec import StrategySpec


class FeatureComputationError(RuntimeError):
    """Raised when a majority of shared enrichment paths fail.

    Sprint 0/Wave 5a: feature computation must fail-CLOSED, not silently
    return defaults. If 3+ of the 4 shared loaders (regime, options,
    event_proximity, sector_profiles) fail in the same call, the engine
    is in degraded state and downstream consumers must not get permissive
    defaults that look like real signal.
    """


def _coerce_as_of(as_of: date | str | None) -> date | None:
    """Normalize as_of input to a date, or None.

    Accepts ISO date strings, date/datetime instances, or None.
    """
    if as_of is None:
        return None
    if isinstance(as_of, datetime):
        return as_of.date()
    if isinstance(as_of, date):
        return as_of
    if isinstance(as_of, str):
        try:
            return date.fromisoformat(as_of[:10])
        except (ValueError, TypeError):
            return None
    return None


def _slice_to_as_of(df: pd.DataFrame, as_of: date | None) -> pd.DataFrame:
    """Slice a DataFrame to rows on or before as_of.

    Returns the original frame when as_of is None (legacy/live behavior).
    Used by compute_features so historical/backtest callers passing full
    history don't leak future rows into iloc[-1] / rolling computations.
    """
    if as_of is None:
        return df
    if df is None or df.empty:
        return df
    cutoff = pd.Timestamp(as_of)
    try:
        return df[df.index <= cutoff]
    except Exception:
        # Fall back if index isn't comparable (e.g. non-datetime index).
        return df


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
    """Classify relative strength state.

    WHY 3 timeframes voted equally: a stock outperforming on all three
    (1m, 3m, 6m) has structural leadership -- it is outperforming both
    recently and historically. A stock outperforming on 1m but underperforming
    on 6m is a recent reversal (less reliable). Equal voting across timeframes
    is deliberate -- #6 mandates equal weight until 200+ trades validate
    whether any timeframe is more predictive than others.
    """
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


def _compute_price_features(
    close: "pd.Series", high: "pd.Series", low: "pd.Series", volume: "pd.Series",
) -> dict:
    """Compute price, MA, ATR, and volume features from OHLCV series."""
    current_price = float(close.iloc[-1])
    sma_20 = close.rolling(20).mean()
    sma_50 = close.rolling(50).mean()
    sma_200 = close.rolling(200).mean()
    sma_50_val = float(sma_50.iloc[-1])
    sma_200_val = float(sma_200.iloc[-1])
    sma_20_val = float(sma_20.iloc[-1])
    price_vs_sma50_pct = (current_price / sma_50_val - 1) * 100
    price_vs_sma200_pct = (current_price / sma_200_val - 1) * 100
    dist_to_sma20_pct = (current_price / sma_20_val - 1) * 100
    sma50_slope = _slope_direction(sma_50.dropna())
    sma200_slope = _slope_direction(sma_200.dropna())
    trend_state = _classify_trend(current_price, sma_50_val, sma_200_val,
                                   sma50_slope, sma200_slope)
    high_50d = float(close.iloc[-50:].max())
    pullback_depth_pct = (current_price / high_50d - 1) * 100
    tr_high_low = high - low
    tr_high_prev = (high - close.shift(1)).abs()
    tr_low_prev = (low - close.shift(1)).abs()
    true_range = pd.concat([tr_high_low, tr_high_prev, tr_low_prev], axis=1).max(axis=1)
    atr_14 = float(true_range.rolling(14).mean().iloc[-1])
    atr_pct = atr_14 / current_price * 100
    avg_vol_20d = float(volume.rolling(20).mean().iloc[-1])
    volume_ratio_20d = float(volume.iloc[-1]) / avg_vol_20d if avg_vol_20d > 0 else 1.0
    return {
        "current_price": current_price, "sma_50": sma_50_val, "sma_200": sma_200_val,
        "price_vs_sma50_pct": round(price_vs_sma50_pct, 2),
        "price_vs_sma200_pct": round(price_vs_sma200_pct, 2),
        "dist_to_sma20_pct": round(dist_to_sma20_pct, 2),
        "sma50_slope": sma50_slope, "sma200_slope": sma200_slope,
        "trend_state": trend_state,
        "pullback_depth_pct": round(pullback_depth_pct, 2),
        "atr_14": round(atr_14, 4), "atr_pct": round(atr_pct, 2),
        "volume_ratio_20d": round(volume_ratio_20d, 2),
    }


def _compute_relative_strength(close: "pd.Series", spy_close: "pd.Series") -> dict:
    """Compute relative strength vs SPY across 1m, 3m, 6m timeframes."""
    rs_vs_spy_1m = _pct_return(close, 21) - _pct_return(spy_close, 21)
    rs_vs_spy_3m = _pct_return(close, 63) - _pct_return(spy_close, 63)
    rs_vs_spy_6m = _pct_return(close, 126) - _pct_return(spy_close, 126)
    relative_strength_state = _classify_relative_strength(
        rs_vs_spy_1m, rs_vs_spy_3m, rs_vs_spy_6m,
    )
    return {
        "rs_vs_spy_1m": round(rs_vs_spy_1m, 2),
        "rs_vs_spy_3m": round(rs_vs_spy_3m, 2),
        "rs_vs_spy_6m": round(rs_vs_spy_6m, 2),
        "relative_strength_state": relative_strength_state,
    }


def compute_features(
    ticker: str,
    ohlcv: pd.DataFrame,
    spy: pd.DataFrame,
    as_of: date | str | None = None,
) -> dict:
    """Compute all features for a single ticker.

    Args:
        ticker: The ticker symbol.
        ohlcv: DataFrame with Open, High, Low, Close, Volume columns.
        spy: SPY benchmark DataFrame with the same columns.
        as_of: Point-in-time cutoff (date/datetime/ISO string or None).
            Slices both frames to index <= as_of to prevent future-row
            leakage on historical/backtest callers.

    Returns:
        A flat dict of computed features.
    """
    cutoff = _coerce_as_of(as_of)
    if cutoff is not None:
        ohlcv = _slice_to_as_of(ohlcv, cutoff)
        spy = _slice_to_as_of(spy, cutoff)

    price_feat = _compute_price_features(
        ohlcv["Close"], ohlcv["High"], ohlcv["Low"], ohlcv["Volume"],
    )
    rs_feat = _compute_relative_strength(ohlcv["Close"], spy["Close"])
    return {
        "ticker": ticker,
        **price_feat,
        **rs_feat,
        "earnings_date": None,
        "hold_overlaps_earnings": False,
        "days_to_earnings": None,
        "event_risk_level": "none",
    }


def compute_all_features(ohlcv_data: dict[str, pd.DataFrame],
                          spy: pd.DataFrame,
                          strategy: "StrategySpec" | None = None,
                          as_of: date | str | None = None) -> dict[str, dict]:
    """Compute features for all tickers in the OHLCV data dict.

    WHY 200-row minimum: SMA200 requires 200 data points. Stocks with less
    history (recent IPOs, newly added to universe) cannot be reliably assessed
    for trend and are skipped. This is a hard requirement, not configurable.

    WHY regime/options/events/sectors are loaded ONCE before the loop:
    These are shared resources -- market regime is the same for all tickers,
    options metrics come from a single DB query, event proximity is calendar-
    based. Computing them once avoids N redundant DB queries and API calls
    where N is the universe size (~200 tickers).

    Args:
        ohlcv_data: Map of ticker -> OHLCV DataFrame.
        spy: SPY benchmark DataFrame.
        strategy: Optional StrategySpec controlling enrichment chain.
        as_of: Point-in-time cutoff propagated to compute_features +
            earnings + event_proximity. None preserves live-scan behavior.

    Sprint 0/Wave 5a (ENGINE-FAIL-LOUD): the 4 shared enrichment loaders
    (regime, options, event_proximity, sector_profiles) are tracked. If
    >50% (3 or 4 of 4) fail in the same call, FeatureComputationError is
    raised — feature output that mostly comes from defaults must not be
    treated as real signal. Per-ticker partial failures (setup_classifier,
    sector lookup) are recorded as `_partial_failure_count` on the output
    dict (only when >0, to preserve fixture hashes for tickers with zero
    partials). The two large fan-out helpers (load_shared_enrichments and
    enrich_ticker) live in engine_helpers.py.
    """
    from src.features.engine_helpers import enrich_ticker, load_shared_enrichments

    chain = _strategy_enrichment_chain(strategy)
    sector_enabled = chain is None or "sector" in chain
    cutoff = _coerce_as_of(as_of)

    regime, options_data, event_features, sector_profiles, shared_path_failures = (
        load_shared_enrichments(spy, ohlcv_data, sector_enabled, cutoff)
    )

    if shared_path_failures > 4 // 2:
        # >50% of the shared enrichment loaders failed; downstream output
        # would be mostly defaults. Fail-CLOSED rather than emit silent
        # permissive features. CLAUDE.md: "raise, never silent."
        raise FeatureComputationError(
            f"{shared_path_failures}/4 shared enrichment "
            f"loaders failed (regime/options/event_proximity/sector_profiles); "
            f"refusing to emit features dominated by defaults"
        )

    results = {}
    for ticker, df in ohlcv_data.items():
        if len(df) < 200:
            logger.warning("%s has only %d rows (need 200+), skipping", ticker, len(df))
            continue
        try:
            results[ticker] = enrich_ticker(
                ticker, df, spy, cutoff,
                regime, options_data, event_features, sector_profiles,
                sector_enabled,
            )
        except FeatureComputationError:
            raise
        except Exception as e:
            logger.warning("Failed to compute features for %s: %s", ticker, e)
    return results


def _strategy_enrichment_chain(strategy: "StrategySpec" | None) -> set[str] | None:
    if strategy is None:
        return None
    raw = getattr(strategy, "raw", {}) or {}
    enrichment = raw.get("enrichment")
    if not isinstance(enrichment, dict):
        return None
    chain = enrichment.get("chain")
    if not isinstance(chain, list) or not chain:
        return None
    return {item for item in chain if isinstance(item, str) and item}


# Re-export loaders + sector helper from engine_helpers for backward-compat
# with tests that patch `src.features.engine._load_*` and `_add_sector_features`.
from src.features.engine_helpers import (  # noqa: E402  -- intentional late import
    _add_sector_features,
    _load_event_proximity,
    _load_options_metrics,
    _load_sector_profiles,
)

# These imports must be referenced so static analysis doesn't drop them; they
# are part of the engine.py public surface for tests + helpers.
__all__ = [
    "FeatureComputationError",
    "compute_all_features",
    "compute_features",
    "_add_sector_features",
    "_load_event_proximity",
    "_load_options_metrics",
    "_load_sector_profiles",
]
