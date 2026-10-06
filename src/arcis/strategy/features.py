"""Incumbent pullback ranker — technical feature computation.

Clean-room implementation. All indicators use Wilder's smoothing where
specified. Known-answer tests in tests/test_ranker.py.
"""

from __future__ import annotations

# --- Pinned lookback / session parameters (D-027, CEO decision 2026-10-05) ---
# The frozen incumbent_v1.yaml never specified these values; they are
# resolved here as a dated implementation decision, not a preregistration
# change. Units are trading sessions (not calendar days): this is a
# daily-bar system. 21/63/126 are the market-standard 1m/3m/6m session
# counts.
PULLBACK_LOOKBACK_SESSIONS = 60
SECTOR_RS_SESSIONS_1M = 21
SECTOR_RS_SESSIONS_3M = 63
SECTOR_RS_SESSIONS_6M = 126


def sma(values: list[float], period: int) -> float:
    """Simple moving average of the last `period` values."""
    if len(values) < period:
        raise ValueError(f"need {period} values, got {len(values)}")
    return sum(values[-period:]) / period


def _wilder_smooth(values: list[float], period: int) -> list[float]:
    """Wilder's smoothing: first value is SMA, then recursive.

    Returns the full smoothed series (same length as input).
    """
    if len(values) < period:
        raise ValueError(f"need {period} values, got {len(values)}")
    smoothed = [0.0] * len(values)
    smoothed[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        smoothed[i] = (smoothed[i - 1] * (period - 1) + values[i]) / period
    return smoothed


def rsi_14(closes: list[float]) -> float:
    """14-period RSI using Wilder's smoothing. Range [0, 100]."""
    if len(closes) < 15:
        raise ValueError(f"need 15 closes for RSI14, got {len(closes)}")
    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = _wilder_smooth(gains, 14)[-1]
    avg_loss = _wilder_smooth(losses, 14)[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr_14(highs: list[float], lows: list[float],
           closes: list[float]) -> float:
    """14-period ATR using Wilder's smoothing."""
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs, lows, closes must have same length")
    if len(closes) < 15:
        raise ValueError(f"need 15 bars for ATR14, got {len(closes)}")
    true_ranges = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        true_ranges.append(tr)
    return _wilder_smooth(true_ranges, 14)[-1]


def volume_ratio(volumes: list[float], period: int = 20) -> float:
    """Current volume divided by `period`-day average volume.

    Raises ValueError if the average is zero (degenerate data;
    fail-closed instead of returning 0.0 which would score +15).
    """
    if len(volumes) < period:
        raise ValueError(f"need {period} volumes, got {len(volumes)}")
    avg = sum(volumes[-period:]) / period
    if avg == 0:
        raise ValueError("zero average volume: degenerate data")
    return volumes[-1] / avg


def pullback_depth_pct(closes: list[float],
                       lookback: int = PULLBACK_LOOKBACK_SESSIONS) -> float:
    """Pullback depth: (current - recent high) / recent high * 100.

    Negative value indicates a pullback. E.g., -5.0 means 5% below
    the recent high.

    Raises ValueError if recent high is zero (degenerate data), or if
    fewer than `lookback` closes are available (fail-closed: measuring
    the pullback over a truncated window would silently understate it).

    Default lookback is PULLBACK_LOOKBACK_SESSIONS (D-027).
    """
    if len(closes) < lookback:
        raise ValueError(f"need {lookback} closes for pullback lookback, "
                         f"got {len(closes)}")
    window = closes[-lookback:]
    recent_high = max(window)
    if recent_high == 0:
        raise ValueError("zero recent high: degenerate data")
    return (closes[-1] - recent_high) / recent_high * 100.0


def dist_to_sma20_pct(closes: list[float]) -> float:
    """Distance to 20-day SMA as a percentage. Negative = below SMA.

    Raises ValueError if SMA is zero (degenerate data).
    """
    if len(closes) < 20:
        raise ValueError(f"need 20 closes, got {len(closes)}")
    sma20 = sma(closes, 20)
    if sma20 == 0:
        raise ValueError("zero SMA20: degenerate data")
    return (closes[-1] - sma20) / sma20 * 100.0


def excess_return(symbol_closes: list[float], benchmark_closes: list[float],
                  periods: int) -> float:
    """Excess return over `periods`: symbol return minus benchmark return.

    Returns are simple (not log): (last / first) - 1.
    """
    if len(symbol_closes) < periods + 1 or len(benchmark_closes) < periods + 1:
        raise ValueError(f"need {periods + 1} closes")
    sym_ret = symbol_closes[-1] / symbol_closes[-periods - 1] - 1.0
    bench_ret = benchmark_closes[-1] / benchmark_closes[-periods - 1] - 1.0
    return sym_ret - bench_ret


def sector_weighted_excess(sector_closes: list[float],
                           spy_closes: list[float],
                           sessions_1m: int = SECTOR_RS_SESSIONS_1M,
                           sessions_3m: int = SECTOR_RS_SESSIONS_3M,
                           sessions_6m: int = SECTOR_RS_SESSIONS_6M) -> float:
    """Weighted sector excess return vs SPY, in percentage points.

    0.20 * excess_1m + 0.50 * excess_3m + 0.30 * excess_6m
    (config/incumbent_v1.yaml sector_rs formula).

    Default session counts are the D-027 pins (21/63/126); explicit
    arguments still override.

    Returns percentage points (not fractions) to match the D-026 Set A
    scoring bands. A units slip here would silently misband every sector,
    so this is covered by an end-to-end test through score_sector_rs.

    Raises ValueError on misaligned inputs: session counts must satisfy
    0 < s1 < s3 < s6 (a zero count would silently return 0.0; a negative
    count would wrap around the series), and both close series must have
    equal length (a length mismatch means the two series end on different
    dates, silently biasing the excess).
    """
    if not (0 < sessions_1m < sessions_3m < sessions_6m):
        raise ValueError(
            "session counts must satisfy 0 < s1m < s3m < s6m, got "
            f"({sessions_1m}, {sessions_3m}, {sessions_6m})")
    if len(sector_closes) != len(spy_closes):
        raise ValueError(
            "sector_closes and spy_closes must have equal length, got "
            f"{len(sector_closes)} and {len(spy_closes)}")
    e1 = excess_return(sector_closes, spy_closes, sessions_1m)
    e3 = excess_return(sector_closes, spy_closes, sessions_3m)
    e6 = excess_return(sector_closes, spy_closes, sessions_6m)
    return (0.20 * e1 + 0.50 * e3 + 0.30 * e6) * 100.0
