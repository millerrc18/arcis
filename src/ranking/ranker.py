"""Deterministic ranking and qualification for trade candidates.

Called by: evaluation.backtester, scheduler.premarket, scheduler.watch, services.recap_service, services.scan_service, services.watchlist_service, training.historical_scanner
Calls: config, features.regime
Owns tables: none
Config keys: bootcamp, enabled, packet_worthy_threshold, qualification_threshold, ranking, regime_adaptive, watchlist_threshold
Tests: tests/test_ranking.py, tests/test_regime.py
"""

import logging

from src.config import load_config

logger = logging.getLogger(__name__)


REGIME_THRESHOLDS = {
    "BULL_LOW_VOL": {"packet_worthy": 40, "position_pct": 1.0},
    "BULL_HIGH_VOL": {"packet_worthy": 50, "position_pct": 0.85},
    "TRANSITION": {"packet_worthy": 60, "position_pct": 0.70},
    "CORRECTION": {"packet_worthy": 65, "position_pct": 0.60},
    "BEAR_EARLY": {"packet_worthy": 75, "position_pct": 0.40},
    "BEAR_ESTABLISHED": {"packet_worthy": 80, "position_pct": 0.30},
    "CRISIS": {"packet_worthy": 90, "position_pct": 0.20},
}


def _load_thresholds(regime_type: str | None = None) -> dict:
    """Load scoring thresholds from config, with defaults.

    If bootcamp is enabled, uses bootcamp-specific thresholds.
    If regime_adaptive is enabled and regime_type is provided, overrides
    the packet_worthy threshold based on market conditions.
    """
    config = load_config()
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

    # Relative strength
    rs = features.get("relative_strength_state", "")
    if rs == "strong_outperformer":
        score += 25
    elif rs == "outperformer":
        score += 15

    # Pullback depth (sweet spot: -3% to -10%)
    pullback = features.get("pullback_depth_pct", 0.0)
    if -10 <= pullback <= -3:
        score += 25
    elif -15 <= pullback < -10:
        score += 10

    # Distance to SMA20 (pulling back toward support: -1% to -5%)
    dist_sma20 = features.get("dist_to_sma20_pct", 0.0)
    if -5 <= dist_sma20 <= -1:
        score += 10

    # Volume contraction on pullback
    vol_ratio = features.get("volume_ratio_20d", 1.0)
    if vol_ratio < 0.8:
        score += 10

    # Options sentiment (9A) — IV rank and put/call as signals
    iv_rank = features.get("iv_rank")
    pc_vol = features.get("put_call_vol_ratio")
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


def rank_universe(features: dict[str, dict]) -> list[dict]:
    """Rank all tickers and classify each as packet_worthy, watchlist, or not_interesting.

    Args:
        features: Output of compute_all_features — dict mapping ticker -> feature dict.

    Returns:
        List of dicts with keys: ticker, score, qualification, features.
        Sorted by score descending.
    """
    from src.features.regime import compute_sector_context, classify_regime

    # Detect current regime for adaptive thresholds
    regime_type = None
    sample_feat = next(iter(features.values()), {})
    if sample_feat:
        try:
            regime_type = classify_regime(sample_feat)
        except Exception:
            pass

    thresholds = _load_thresholds(regime_type=regime_type)
    packet_threshold = thresholds["packet_worthy"]
    watchlist_threshold = thresholds["watchlist"]

    # First pass: score all tickers and store scores in features
    scored = {}
    for ticker, feat in features.items():
        score = _score_ticker(feat)
        feat["_score"] = score
        scored[ticker] = score

    # Second pass: compute sector context (needs all scores)
    for ticker, feat in features.items():
        try:
            sector_ctx = compute_sector_context(ticker, scored[ticker], features)
            feat.update(sector_ctx)
        except Exception:
            pass

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
