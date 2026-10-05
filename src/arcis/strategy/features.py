"""Incumbent pullback ranker — technical feature computation.

Clean-room implementation. All indicators use Wilder's smoothing where
specified. Known-answer tests in tests/test_ranker.py.
"""

from __future__ import annotations


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
    """Current volume divided by `period`-day average volume."""
    if len(volumes) < period:
        raise ValueError(f"need {period} volumes, got {len(volumes)}")
    avg = sum(volumes[-period:]) / period
    if avg == 0:
        return 0.0
    return volumes[-1] / avg


def pullback_depth_pct(closes: list[float], lookback: int = 60) -> float:
    """Pullback depth: (current - recent high) / recent high * 100.

    Negative value indicates a pullback. E.g., -5.0 means 5% below
    the recent high.
    """
    if len(closes) < 2:
        raise ValueError("need at least 2 closes")
    window = closes[-lookback:] if len(closes) >= lookback else closes
    recent_high = max(window)
    if recent_high == 0:
        return 0.0
    return (closes[-1] - recent_high) / recent_high * 100.0


def dist_to_sma20_pct(closes: list[float]) -> float:
    """Distance to 20-day SMA as a percentage. Negative = below SMA."""
    if len(closes) < 20:
        raise ValueError(f"need 20 closes, got {len(closes)}")
    sma20 = sma(closes, 20)
    if sma20 == 0:
        return 0.0
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
