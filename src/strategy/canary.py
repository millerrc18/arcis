"""Canary rules-based scoring — a simple baseline to compare against the LLM.

Called by: llm.packet_writer
Calls: none
Owns tables: none
Config keys: none
Tests: none

Runs alongside the LLM. If the LLM template fallback rate exceeds 50%,
the canary score is logged for comparison.
"""

import logging

logger = logging.getLogger(__name__)


def canary_score(features: dict) -> int:
    """Pure rules-based conviction score (1-10) — no LLM needed."""
    score = 5  # neutral

    trend = features.get("trend_state", "")
    if trend == "strong_uptrend":
        score += 1
    elif trend == "downtrend":
        score -= 1

    pullback = features.get("pullback_depth_pct", 0) or 0
    if 3.0 <= pullback <= 8.0:
        score += 1
    elif pullback > 12.0:
        score -= 1

    vol_ratio = features.get("volume_ratio_20d", 1.0) or 1.0
    if vol_ratio < 0.8:
        score += 1

    rsi = features.get("rsi_14", 50) or 50
    if rsi < 40:
        score += 1
    elif rsi > 75:
        score -= 1

    rs = features.get("relative_strength_state", "")
    if rs == "strong_rs":
        score += 1

    atr_pct = features.get("atr_pct", 0) or 0
    if atr_pct > 3.0:
        score -= 1

    return max(1, min(10, score))


def log_canary_comparison(ticker: str, llm_conviction: int | None,
                          features: dict) -> None:
    """Log canary score alongside LLM conviction for comparison."""
    c_score = canary_score(features)
    llm_str = str(llm_conviction) if llm_conviction else "template"
    logger.info("[CANARY] %s: rules=%d, llm=%s", ticker, c_score, llm_str)
