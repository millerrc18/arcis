"""Deterministic ranking and qualification for trade candidates.

Called by: evaluation.backtester, scheduler.premarket, scheduler.watch, services.recap_service, services.scan_service, services.watchlist_service, training.historical_scanner
Calls: config, features.regime
Owns tables: none
Config keys: bootcamp, enabled, packet_worthy_threshold, qualification_threshold, ranking, regime_adaptive, watchlist_threshold
Tests: tests/test_ranking.py, tests/test_regime.py
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.config import load_config

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.platform.strategy_spec import StrategySpec


REGIME_THRESHOLDS = {
    "BULL_LOW_VOL": {"packet_worthy": 40, "position_pct": 1.0},
    "BULL_HIGH_VOL": {"packet_worthy": 50, "position_pct": 0.85},
    "TRANSITION": {"packet_worthy": 60, "position_pct": 0.70},
    "CORRECTION": {"packet_worthy": 65, "position_pct": 0.60},
    "BEAR_EARLY": {"packet_worthy": 75, "position_pct": 0.40},
    "BEAR_ESTABLISHED": {"packet_worthy": 80, "position_pct": 0.30},
    "CRISIS": {"packet_worthy": 90, "position_pct": 0.20},
}


def _is_unit_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 <= value <= 1.0


def _load_strategy_thresholds(
    strategy: "StrategySpec" | None,
    regime_type: str | None,
    config: dict,
) -> dict | None:
    if strategy is None:
        return None

    raw = getattr(strategy, "raw", {}) or {}
    bootcamp_cfg = raw.get("bootcamp")
    sizing_cfg = getattr(strategy, "position_sizing", {}) or {}
    regimes_block = sizing_cfg.get("regimes")
    if not isinstance(bootcamp_cfg, dict) and not (
        sizing_cfg.get("method") == "regime_adaptive" and isinstance(regimes_block, dict)
    ):
        return None

    ranking_cfg = config.get("ranking", {})
    base = {
        "packet_worthy": ranking_cfg.get("packet_worthy_threshold", 70),
        "watchlist": ranking_cfg.get("watchlist_threshold", 45),
        "position_pct": 1.0,
    }

    if isinstance(bootcamp_cfg, dict):
        if "qualification_threshold" in bootcamp_cfg:
            base["packet_worthy"] = bootcamp_cfg["qualification_threshold"]
        if "watchlist_threshold" in bootcamp_cfg:
            base["watchlist"] = bootcamp_cfg["watchlist_threshold"]

    if sizing_cfg.get("method") == "regime_adaptive" and regime_type and isinstance(regimes_block, dict):
        entry = regimes_block.get(regime_type)
        if isinstance(entry, dict):
            if entry.get("packet_worthy") is False:
                logger.info("[RANKER] Strategy disables packet generation in regime %s", regime_type)
                base["packet_worthy"] = float("inf")
                base["watchlist"] = float("inf")
                base["position_pct"] = 0.0
                base["regime_disabled"] = True
                return base

            position_pct = entry.get("position_pct")
            if _is_unit_number(position_pct):
                base["position_pct"] = float(position_pct)

    return base


def _load_thresholds(
    regime_type: str | None = None,
    strategy: "StrategySpec" | None = None,
) -> dict:
    """Load scoring thresholds from config, with defaults.

    If bootcamp is enabled, uses bootcamp-specific thresholds.
    If regime_adaptive is enabled and regime_type is provided, overrides
    the packet_worthy threshold based on market conditions.
    """
    config = load_config()
    strategy_thresholds = _load_strategy_thresholds(strategy, regime_type, config)
    if strategy_thresholds is not None:
        return strategy_thresholds

    bootcamp_cfg = config.get("bootcamp", {})

    if bootcamp_cfg.get("enabled", False):
        thresholds = {
            "packet_worthy": bootcamp_cfg.get("qualification_threshold", 40),
            "watchlist": bootcamp_cfg.get("watchlist_threshold", 25),
            "position_pct": 1.0,
        }
        logger.info("[BOOTCAMP] Using bootcamp thresholds: "
                     "packet_worthy=%s, watchlist=%s",
                     thresholds['packet_worthy'], thresholds['watchlist'])
        return thresholds

    ranking_cfg = config.get("ranking", {})
    base = {
        "packet_worthy": ranking_cfg.get("packet_worthy_threshold", 70),
        "watchlist": ranking_cfg.get("watchlist_threshold", 45),
        "position_pct": 1.0,
    }

    # Regime-adaptive override
    regime_cfg = config.get("regime_adaptive", {})
    if regime_cfg.get("enabled", False) and regime_type:
        regime_overrides = REGIME_THRESHOLDS.get(regime_type, {})
        if regime_overrides:
            old_pw = base["packet_worthy"]
            base["packet_worthy"] = regime_overrides["packet_worthy"]
            base["position_pct"] = regime_overrides["position_pct"]
            logger.info("[RANKER] Regime %s: threshold %d (normal %d), "
                        "position sizing at %.0f%%",
                        regime_type, base["packet_worthy"], old_pw,
                        base["position_pct"] * 100)

    return base


def _regime_adjustment(features: dict) -> float:
    """Compute regime-based score adjustment from -10 to +10."""
    regime = features.get("regime_label", "")
    breadth = features.get("market_breadth_label", "")
    spy_rsi = features.get("spy_rsi_14", 50)

    adj = 0.0

    if regime == "calm_uptrend" and breadth == "healthy":
        adj += 5
    elif regime == "calm_uptrend" and breadth == "narrowing":
        adj += 2
    elif regime == "volatile_uptrend":
        adj += 0
    elif regime == "transitional":
        adj -= 3
    elif regime == "calm_downtrend":
        adj -= 5
    elif regime == "volatile_downtrend":
        adj -= 10

    # SPY overbought/oversold
    if spy_rsi > 75:
        adj -= 3
    elif spy_rsi < 30:
        adj += 3

    logger.debug("Regime adjustment: regime=%s breadth=%s spy_rsi=%.1f adj=%.1f",
                 regime, breadth, spy_rsi, adj)

    return max(-10, min(10, adj))


def _compute_sector_rs(ticker_features: dict, sector_ohlcv: dict | None) -> float | None:
    """Compute relative strength vs sector ETF over 1m/3m/6m periods.

    Returns combined RS score (0-25) or None if sector data unavailable.
    Uses same methodology as existing SPY RS but against sector ETF.
    """
    if not sector_ohlcv:
        return None

    # sector_ohlcv expected to have return fields like sector_return_1m, etc.
    ticker_returns = {
        "1m": ticker_features.get("return_1m", 0),
        "3m": ticker_features.get("return_3m", 0),
        "6m": ticker_features.get("return_6m", 0),
    }
    sector_returns = {
        "1m": sector_ohlcv.get("return_1m", 0),
        "3m": sector_ohlcv.get("return_3m", 0),
        "6m": sector_ohlcv.get("return_6m", 0),
    }

    # Compute excess returns over sector (weighted: 50% 3m, 30% 6m, 20% 1m)
    excess = {}
    for period in ("1m", "3m", "6m"):
        t_ret = ticker_returns[period] or 0
        s_ret = sector_returns[period] or 0
        excess[period] = t_ret - s_ret

    weighted_excess = (
        0.20 * excess["1m"] +
        0.50 * excess["3m"] +
        0.30 * excess["6m"]
    )

    # Classify and score (0-25 scale, matching market RS range)
    if weighted_excess > 5.0:
        return 25  # strong_outperformer vs sector
    elif weighted_excess > 2.0:
        return 15  # outperformer vs sector
    elif weighted_excess > -2.0:
        return 5   # neutral vs sector
    else:
        return 0   # underperformer vs sector


def _as_float(value, default: float | None = None) -> float | None:
    """Coerce a feature value to float. Returns default on None or bad input.

    SQLite REAL columns can return as TEXT after a recovery (#195), so every
    numeric comparison in _score_ticker goes through this — any leaked str
    becomes a usable float instead of raising TypeError on comparison.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _strategy_ranking_config(strategy: "StrategySpec" | None) -> dict | None:
    if strategy is None:
        return None
    raw = getattr(strategy, "raw", {}) or {}
    ranking = raw.get("ranking")
    if not isinstance(ranking, dict):
        return None
    if not any(key in ranking for key in ("bands", "adjustments", "derived_metrics")):
        return None
    return ranking


def _resolve_metric_value(
    name: str,
    features: dict,
    derived_specs: dict[str, dict],
    derived_cache: dict[str, Any],
    resolving: set[str],
) -> Any:
    if name in derived_cache:
        return derived_cache[name]
    if name not in derived_specs:
        return features.get(name)

    if name in resolving:
        return None

    resolving.add(name)
    spec = derived_specs[name]
    op = spec.get("operation")
    inputs = spec.get("inputs")

    if op == "subtract":
        left = _resolve_metric_value(inputs[0], features, derived_specs, derived_cache, resolving)
        right = _resolve_metric_value(inputs[1], features, derived_specs, derived_cache, resolving)
        left_f = _as_float(left)
        right_f = _as_float(right)
        value = None if left_f is None or right_f is None else left_f - right_f
    elif op == "weighted_sum":
        total = 0.0
        value = None
        if isinstance(inputs, dict):
            for metric, weight in inputs.items():
                current = _resolve_metric_value(metric, features, derived_specs, derived_cache, resolving)
                current_f = _as_float(current)
                if current_f is None:
                    value = None
                    break
                total += float(weight) * current_f
            else:
                value = total
    else:
        value = None

    resolving.discard(name)
    derived_cache[name] = value
    return value


def _compute_derived_metric_values(features: dict, ranking_cfg: dict) -> dict[str, Any]:
    derived_specs = ranking_cfg.get("derived_metrics", {})
    if not isinstance(derived_specs, dict) or not derived_specs:
        return {}

    derived_cache: dict[str, Any] = {}
    for name in derived_specs:
        _resolve_metric_value(name, features, derived_specs, derived_cache, set())
    return derived_cache


def _lookup_metric_value(features: dict, derived_values: dict[str, Any], metric: str) -> Any:
    if metric in derived_values:
        return derived_values[metric]
    return features.get(metric)


def _condition_matches(features: dict, derived_values: dict[str, Any], condition: dict) -> bool:
    metric = condition.get("metric")
    op = condition.get("operator")
    threshold = condition.get("threshold")
    value = _lookup_metric_value(features, derived_values, metric)

    if op in ("==", "!="):
        if isinstance(threshold, (int, float)) and not isinstance(threshold, bool):
            value_cmp = _as_float(value)
            if value_cmp is None:
                matched = False
            else:
                matched = value_cmp == float(threshold)
        else:
            matched = value == threshold
        return matched if op == "==" else not matched

    value_f = _as_float(value)
    if value_f is None:
        return False

    if op == ">":
        return value_f > float(threshold)
    if op == ">=":
        return value_f >= float(threshold)
    if op == "<":
        return value_f < float(threshold)
    if op == "<=":
        return value_f <= float(threshold)
    return False


def _band_matches(features: dict, derived_values: dict[str, Any], band: dict) -> bool:
    if "conditions" in band:
        conditions = band.get("conditions", [])
        return all(_condition_matches(features, derived_values, cond) for cond in conditions)

    metric = band.get("metric")
    value = _lookup_metric_value(features, derived_values, metric)
    if "category" in band:
        return value == band.get("category")

    value_f = _as_float(value)
    if value_f is None:
        return False

    lower, upper = band.get("range", [None, None])
    if lower is None or upper is None:
        return False
    return float(lower) <= value_f <= float(upper)


def _band_has_available_value(features: dict, derived_values: dict[str, Any], band: dict) -> bool:
    if "conditions" in band:
        for condition in band.get("conditions", []):
            metric = condition.get("metric")
            value = _lookup_metric_value(features, derived_values, metric)
            threshold = condition.get("threshold")
            if isinstance(threshold, (int, float)) and not isinstance(threshold, bool):
                if _as_float(value) is None:
                    return False
            elif value is None:
                return False
        return True

    metric = band.get("metric")
    value = _lookup_metric_value(features, derived_values, metric)
    if "category" in band:
        return value is not None
    return _as_float(value) is not None


def _blend_metric_key(band: dict, idx: int) -> str:
    metric = band.get("metric")
    if isinstance(metric, str) and metric:
        return f"metric:{metric}"
    return f"compound:{idx}"


def _evaluate_ranking_bands(features: dict, derived_values: dict[str, Any], bands: list[dict]) -> float:
    score = 0.0
    matched_metrics: set[str] = set()
    blend_groups: dict[str, dict[str, dict[str, Any]]] = {}

    for idx, band in enumerate(bands):
        if not isinstance(band, dict):
            continue

        blend_group = band.get("blend_group")
        if blend_group:
            key = _blend_metric_key(band, idx)
            weight = float(band.get("weight", 0.0))
            group_metrics = blend_groups.setdefault(blend_group, {})
            entry = group_metrics.setdefault(
                key,
                {
                    "weight": weight,
                    "available": False,
                    "matched": False,
                    "score": 0.0,
                },
            )
            if _band_has_available_value(features, derived_values, band):
                entry["available"] = True
            if entry["matched"]:
                continue
            if _band_matches(features, derived_values, band):
                entry["matched"] = True
                entry["score"] = float(band.get("score", 0.0))
            continue

        metric = band.get("metric")
        if metric and metric in matched_metrics:
            continue
        if _band_matches(features, derived_values, band):
            score += float(band.get("score", 0.0))
            if metric:
                matched_metrics.add(metric)

    for group_metrics in blend_groups.values():
        declared_total = sum(entry["weight"] for entry in group_metrics.values())
        active_total = sum(
            entry["weight"] for entry in group_metrics.values() if entry["available"]
        )
        if active_total <= 0:
            continue

        contribution = sum(
            entry["weight"] * entry["score"]
            for entry in group_metrics.values()
            if entry["available"]
        )

        # Preserve incumbent parity when a metric is unavailable by reweighting
        # the remaining active metrics back to the group's declared total.
        if active_total < declared_total:
            contribution *= declared_total / active_total

        score += contribution

    return score


def _evaluate_adjustments(features: dict, derived_values: dict[str, Any], adjustments: dict) -> float:
    if not isinstance(adjustments, dict):
        return 0.0

    total = 0.0
    for band in adjustments.get("bands", []):
        if isinstance(band, dict) and _band_matches(features, derived_values, band):
            total += float(band.get("score", 0.0))

    clamp = adjustments.get("clamp")
    if isinstance(clamp, list) and len(clamp) == 2:
        lower = float(clamp[0])
        upper = float(clamp[1])
        total = max(lower, min(upper, total))
    return total


def _score_ticker_from_strategy(features: dict, ranking_cfg: dict) -> tuple[float, dict[str, Any]]:
    derived_values = _compute_derived_metric_values(features, ranking_cfg)
    band_score = _evaluate_ranking_bands(
        features,
        derived_values,
        ranking_cfg.get("bands", []),
    )
    adjustment = _evaluate_adjustments(
        features,
        derived_values,
        ranking_cfg.get("adjustments", {}),
    )
    total = max(0, min(100, band_score + adjustment))
    return total, {
        "bands": band_score,
        "adjustment": adjustment,
        "derived_metrics": derived_values,
    }


def _score_ticker(features: dict) -> float:
    """Score a single ticker on a 0-100 scale. Deterministic, no randomness."""
    score = 0.0

    # Trend state: strong_uptrend=+30, uptrend=+20, neutral=+5
    trend = features.get("trend_state", "")
    if trend == "strong_uptrend":
        score += 30
    elif trend == "uptrend":
        score += 20
    elif trend == "neutral":
        score += 5

    # Two-tier relative strength: 60% vs SPY + 40% vs sector ETF
    market_rs = features.get("relative_strength_state", "")
    market_rs_score = 25 if market_rs == "strong_outperformer" else 15 if market_rs == "outperformer" else 0

    sector_rs_score = _as_float(features.get("_sector_rs_score"))
    if sector_rs_score is not None:
        combined_rs = 0.6 * market_rs_score + 0.4 * sector_rs_score
    else:
        combined_rs = market_rs_score  # Fallback to market-only
    score += combined_rs

    # Pullback depth: narrowed for S&P 100 large-caps
    pullback = _as_float(features.get("pullback_depth_pct"), default=0.0)
    if -8 <= pullback <= -3:
        score += 25
    elif -12 <= pullback < -8:
        score += 10

    # Distance to SMA20 (pulling back toward support: -1% to -5%)
    dist_sma20 = _as_float(features.get("dist_to_sma20_pct"), default=0.0)
    if -5 <= dist_sma20 <= -1:
        score += 10

    # Volume contraction on pullback (increased weight from research)
    vol_ratio = _as_float(features.get("volume_ratio_20d"), default=1.0)
    if vol_ratio < 0.8:
        score += 15

    # Options sentiment (9A) — IV rank and put/call as signals
    iv_rank = _as_float(features.get("iv_rank"))
    pc_vol = _as_float(features.get("put_call_vol_ratio"))
    if iv_rank is not None:
        if iv_rank < 25:
            score += 3  # Cheap options = less fear
        elif iv_rank > 75 and pc_vol and pc_vol > 1.2:
            score -= 3  # High IV + bearish flow = caution

    # Regime adjustment
    adj = _regime_adjustment(features)
    score += adj

    # Cap at 0-100
    return max(0, min(100, score))


def rank_universe(features: dict[str, dict],
                  sector_etf_features: dict[str, dict] | None = None,
                  strategy: "StrategySpec" | None = None) -> list[dict]:
    """Rank all tickers and classify each as packet_worthy, watchlist, or not_interesting.

    Args:
        features: Output of compute_all_features — dict mapping ticker -> feature dict.
        sector_etf_features: Optional dict mapping sector ETF ticker -> feature dict
            with return_1m/3m/6m for two-tier RS. If None, falls back to market-only RS.

    Returns:
        List of dicts with keys: ticker, score, qualification, features.
        Sorted by score descending.
    """
    from src.features.regime import compute_sector_context, classify_regime
    from src.universe.sectors import get_sector_etf

    # Detect current regime for adaptive thresholds
    regime_type = None
    sample_feat = next(iter(features.values()), {})
    if sample_feat:
        try:
            regime_type = classify_regime(sample_feat)
        except Exception as exc:
            # #605 — Don't silently fall through to base thresholds; debug-log
            # so failures in regime classification are visible during runtime.
            logger.debug("[RANKER] classify_regime failed; using base thresholds: %s", exc)

    thresholds = _load_thresholds(regime_type=regime_type, strategy=strategy)
    packet_threshold = thresholds["packet_worthy"]
    watchlist_threshold = thresholds["watchlist"]
    ranking_cfg = _strategy_ranking_config(strategy)

    # Pre-compute sector RS for each ticker (if sector ETF data available)
    if sector_etf_features:
        for ticker, feat in features.items():
            etf = get_sector_etf(ticker)
            if etf and etf in sector_etf_features:
                sector_score = _compute_sector_rs(feat, sector_etf_features[etf])
                if sector_score is not None:
                    feat["_sector_rs_score"] = sector_score

    # First pass: score all tickers and store scores in features
    scored = {}
    for ticker, feat in features.items():
        if ranking_cfg is None:
            score = _score_ticker(feat)
        else:
            score, _details = _score_ticker_from_strategy(feat, ranking_cfg)
        feat["_score"] = score
        scored[ticker] = score

    # Second pass: compute sector context (needs all scores)
    for ticker, feat in features.items():
        try:
            sector_ctx = compute_sector_context(ticker, scored[ticker], features)
            feat.update(sector_ctx)
        except Exception as exc:
            # #605 — Don't silently swallow sector-context failures; debug-log
            # so missing sector_etf data or import errors are visible.
            logger.debug("[RANKER] compute_sector_context failed for %s: %s", ticker, exc)

    # Third pass: classify
    ranked = []
    for ticker, feat in features.items():
        score = scored[ticker]

        if score >= packet_threshold:
            event_risk_level = feat.get("event_risk_level", "none")
            if event_risk_level in ("elevated", "imminent"):
                qualification = "earnings_risk_packet"
            else:
                qualification = "packet_worthy"
        elif score >= watchlist_threshold:
            qualification = "watchlist"
        else:
            qualification = "not_interesting"

        ranked.append({
            "ticker": ticker,
            "score": score,
            "qualification": qualification,
            "features": feat,
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked


def get_top_candidates(ranked: list[dict], max_packets: int = 5,
                        max_watchlist: int = 7) -> dict:
    """Extract top packet-worthy and watchlist candidates.

    Returns:
        {"packet_worthy": [...], "watchlist": [...]} sorted by score descending.
    """
    # Bootcamp overrides: raise caps for high-volume data collection
    config = load_config()
    bootcamp_cfg = config.get("bootcamp", {})
    if bootcamp_cfg.get("enabled", False):
        max_packets = 20
        max_watchlist = 30

    # Include earnings_risk_packet in packet_worthy list with a flag
    packet_worthy = []
    for r in ranked:
        if r["qualification"] in ("packet_worthy", "earnings_risk_packet"):
            entry = dict(r)
            entry["earnings_risk"] = r["qualification"] == "earnings_risk_packet"
            packet_worthy.append(entry)
            if len(packet_worthy) >= max_packets:
                break
    watchlist = [r for r in ranked if r["qualification"] == "watchlist"][:max_watchlist]
    return {
        "packet_worthy": packet_worthy,
        "watchlist": watchlist,
    }
