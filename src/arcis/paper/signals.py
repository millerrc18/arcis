"""Signal generation from the frozen incumbent for the paper lane.

Generates daily signals from the frozen incumbent strategy (incumbent_v1)
for the paper trading accounts. Same selection for all three accounts —
only execution varies.

LIMITATION (documented): The trend_state and relative_strength_state
classifiers are DEFERRED per CEO decision (2026-10-05) — unknown labels
fail closed. Signal generation therefore scores ONLY the fully-specified
numeric features:
- pullback_depth_pct (D-028 bands)
- dist_to_sma20_pct (D-028 bands)
- volume_ratio_20d (D-028 bands)
- iv_rank (D-028 bands)

This yields a partial score (max 53/100) but preserves the rank ordering
from the specified components. The paper lane is for execution calibration,
not edge discovery, so this is sufficient. Full scoring awaits S02 (legacy
archive) or explicit classifier design.

D-029 default: limit = signal-day close.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from arcis.paper import Signal
from arcis.strategy.features import (
    atr_14,
    dist_to_sma20_pct,
    pullback_depth_pct,
    sma,
    volume_ratio,
)
from arcis.strategy.scoring import (
    score_dist_to_sma20,
    score_pullback_depth,
    score_volume_ratio,
)


@dataclass(frozen=True)
class SignalConfig:
    """Configuration for signal generation."""

    # D-029 default: limit = signal-day close
    limit_rule: str = "signal_close"
    # Fixed notional per trade (sizing is not preregistered)
    notional_per_trade: float = 10000.0
    # Minimum score to emit a signal (of 100 max with D-031 classifiers)
    min_score: int = 50
    # Maximum signals per day (capital constraint: $100k / $10k = 10)
    max_signals: int = 5


def load_bars(symbol: str, data_root: str = "/home/hatch/arcis-data") -> list[dict[str, Any]]:
    """Load daily bars from the local data plane (S03/S04).

    Uses the local parquet files instead of the Alpaca API (paper keys
    don't have market data access).
    """
    import pandas as pd
    path = f"{data_root}/raw/bars/{symbol}.parquet"
    try:
        df = pd.read_parquet(path)
    except FileNotFoundError:
        return []
    # Convert to the bar dict format (parquet uses single-letter cols)
    bars = []
    for _, row in df.iterrows():
        bars.append({
            "c": float(row["c"]),
            "h": float(row["h"]),
            "l": float(row["l"]),
            "v": float(row["v"]),
            "t": str(row["t"]),
        })
    return bars


def score_ticker(symbol: str, bars: list[dict[str, Any]],
                 spy_closes: list[float] | None = None) -> int | None:
    """Score a ticker on the full incumbent (D-031 classifiers + numeric features).

    Returns None if insufficient data. Fail-closed: insufficient bars → None,
    not a zero score.

    D-031: trend_state and relative_strength_state now use the recovered
    5+5 label vocabularies; unlisted labels score 0 (not fail-closed).
    """
    from arcis.strategy.classifiers import (
        classify_trend_state, classify_rs_state, pct_return, slope_direction,
    )
    from arcis.strategy.scoring import (
        score_trend_state, score_relative_strength_state,
    )

    # D-031: 200-row minimum for trend classification
    if len(bars) < 200:
        return None

    closes = [b["c"] for b in bars]
    volumes = [b["v"] for b in bars]

    # Trend state (D-031)
    price = closes[-1]
    sma50_val = sma(closes, 50)
    sma200_val = sma(closes, 200)
    # Slope needs the SMA series, not just the final value
    sma50_series = [sma(closes[:i+1], 50) for i in range(49, len(closes))]
    sma200_series = [sma(closes[:i+1], 200) for i in range(199, len(closes))]
    trend = classify_trend_state(
        price, sma50_val, sma200_val,
        slope_direction(sma50_series), slope_direction(sma200_series),
    )

    # RS state (D-031) — needs SPY for excess returns
    if spy_closes and len(spy_closes) >= len(closes):
        spy = spy_closes[-len(closes):]
        e21 = pct_return(closes, 21) - pct_return(spy, 21)
        e63 = pct_return(closes, 63) - pct_return(spy, 63)
        e126 = pct_return(closes, 126) - pct_return(spy, 126)
        rs = classify_rs_state(e21, e63, e126)
    else:
        rs = "neutral"  # no SPY data → neutral (scores 0)

    # Numeric features (D-027, D-028)
    pb = pullback_depth_pct(closes, lookback=60)
    dist = dist_to_sma20_pct(closes)
    vr = volume_ratio(volumes, period=20)
    # IV rank not available from bars; skip (scores 0)

    score = 0
    score += score_trend_state(trend)
    score += score_relative_strength_state(rs)
    score += score_pullback_depth(pb)
    score += score_dist_to_sma20(dist)
    score += score_volume_ratio(vr)

    return score


def generate_signals(
    as_of: date,
    tickers: list[str],
    config: SignalConfig | None = None,
    data_root: str = "/home/hatch/arcis-data",
) -> list[Signal]:
    """Generate signals for the given date from the frozen incumbent.

    Args:
        as_of: The signal date (t). Signals are for t+1 entry.
        tickers: Universe to scan (e.g., S&P 100).
        config: Signal configuration.
        data_root: Data plane root.

    Returns:
        List of signals, ranked by score, capped at max_signals.
    """
    cfg = config or SignalConfig()
    scored: list[tuple[str, int, float, float, float]] = []

    # Load SPY for RS excess returns (D-031)
    spy_bars = load_bars("SPY", data_root)
    spy_closes = [b["c"] for b in spy_bars] if spy_bars else None

    for symbol in tickers:
        bars = load_bars(symbol, data_root)
        if not bars:
            continue  # fail-closed: skip on missing data

        score = score_ticker(symbol, bars, spy_closes)
        if score is None or score < cfg.min_score:
            continue

        # D-029: limit = signal-day close
        close = bars[-1]["c"]
        atr = atr_14(
            [b["h"] for b in bars],
            [b["l"] for b in bars],
            [b["c"] for b in bars],
        )
        # ATR-based bracket (incumbent_v1.yaml exit spec)
        stop = close - 3.0 * atr
        target = close + 6.0 * atr
        # Apply floors/caps
        stop = max(stop, close * 0.88)  # 12% cap
        stop = min(stop, close * 0.95)  # 5% floor
        target = min(target, close * 1.25)  # 25% cap
        target = max(target, close * 1.10)  # 10% floor

        shares = int(cfg.notional_per_trade / close)
        if shares < 1:
            continue

        scored.append((symbol, score, close, stop, target))

    # Rank by score, take top N
    scored.sort(key=lambda x: x[1], reverse=True)
    signals = []
    for symbol, _score, close, stop, target in scored[:cfg.max_signals]:
        shares = int(cfg.notional_per_trade / close)
        signals.append(Signal(
            symbol=symbol,
            signal_date=as_of,
            limit=close,  # D-029
            stop=stop,
            target=target,
            shares=shares,
        ))

    return signals


def signals_to_orders(signals: list[Signal], account: str,
                      buffer_bp: float) -> list[dict[str, Any]]:
    """Convert signals to orders for the given account.

    Args:
        signals: The signals (same for all accounts).
        account: "A", "B", or "C".
        buffer_bp: Adverse buffer in basis points (R06 conservative).

    Returns:
        List of order dicts ready for AlpacaPaper.place_order.
    """
    from arcis.paper import signal_to_order
    return [signal_to_order(s, account, buffer_bp) for s in signals]
