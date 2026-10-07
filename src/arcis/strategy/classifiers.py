"""Legacy classifiers: trend_state and relative_strength_state.

Clean-room reimplementation from config/classifiers_v1.yaml (D-031).
Recovered from the 2026-09-28 legacy archive; logic identical across all
versions. No legacy code was read or ported.

D-031: 5+5 label vocabularies; unlisted labels score 0 (matching legacy
ranker.py:491-501), not fail-closed.
"""

from __future__ import annotations


def slope_direction(values: list[float], window: int = 10) -> str:
    """Classify the slope of a series as positive, negative, or flat.

    Uses the last `window` values. diff = last - first.
    threshold = 0.1% of |first| (or 0.01 if first == 0).
    Returns 'positive' if diff > threshold, 'negative' if diff < -threshold,
    'flat' otherwise. All comparisons strict.
    """
    if len(values) < window:
        return "flat"
    recent = values[-window:]
    first = recent[0]
    last = recent[-1]
    diff = last - first
    threshold = 0.001 * abs(first) if first != 0 else 0.01
    if diff > threshold:
        return "positive"
    if diff < -threshold:
        return "negative"
    return "flat"


def classify_trend_state(
    price: float,
    sma50: float,
    sma200: float,
    sma50_slope: str,
    sma200_slope: str,
) -> str:
    """Classify trend state. First match wins. All comparisons strict.

    Rules (classifiers_v1.yaml):
      strong_uptrend: price > sma50 > sma200 AND both slopes positive
      uptrend: price > sma50 AND sma50 > sma200
      strong_downtrend: price < sma50 < sma200 AND both slopes negative
      downtrend: price < sma50 AND sma50 < sma200
      neutral: otherwise
    """
    if (price > sma50 > sma200
            and sma50_slope == "positive"
            and sma200_slope == "positive"):
        return "strong_uptrend"
    if price > sma50 and sma50 > sma200:
        return "uptrend"
    if (price < sma50 < sma200
            and sma50_slope == "negative"
            and sma200_slope == "negative"):
        return "strong_downtrend"
    if price < sma50 and sma50 < sma200:
        return "downtrend"
    return "neutral"


def classify_rs_state(
    excess_21: float,
    excess_63: float,
    excess_126: float,
) -> str:
    """Classify relative strength state.

    Count positives (P) and negatives (M) among the three excess returns.
    Exactly 0 counts as neither.
      P == 3 → strong_outperformer
      P >= 2 → outperformer
      M == 3 → strong_underperformer
      M >= 2 → underperformer
      else → neutral
    """
    excesses = [excess_21, excess_63, excess_126]
    p = sum(1 for e in excesses if e > 0)
    m = sum(1 for e in excesses if e < 0)
    if p == 3:
        return "strong_outperformer"
    if p >= 2:
        return "outperformer"
    if m == 3:
        return "strong_underperformer"
    if m >= 2:
        return "underperformer"
    return "neutral"


def pct_return(closes: list[float], n: int) -> float:
    """N-row percent return: (last / close N rows earlier - 1) * 100.

    Returns 0.0 if fewer than N+1 rows (matches legacy).
    """
    if len(closes) < n + 1:
        return 0.0
    return (closes[-1] / closes[-n - 1] - 1) * 100
