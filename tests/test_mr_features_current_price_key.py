"""Regression test for MR feature dict `current_price` key (root cause of #52).

The MR scan was silently dropping ~5 tickers per cycle (BAC, CVX, DE, AMZN, AVGO
observed in production logs 2026-05-07/08) because:

1. `compute_mr_features` (src/features/mean_reversion.py:74-85) returned a
   feature dict with `last_close` but NO `current_price` key.
2. `build_packet_from_features` (src/packets/template.py:170) reads
   `features.get("current_price", 0.0)` — got `0` from MR features.
3. The #621 defensive guard (price <= 0) refused to build the packet.
4. Pre-PR-#1036: `enhance_packet_with_llm(None)` crashed with NoneType.
5. Post-PR-#1036: silent skip with `[MR] Skipping <ticker>` log.

Either way: ticker dropped from MR scan output. PR-#1037 (yfinance trailing-
zero sanitizer) was defensive value but didn't address THIS bug — yfinance
data was clean; the bug was purely a feature-dict key naming mismatch.

Pullback scan's `compute_all_features` (src/features/engine.py:173) DOES
return `current_price`, which is why pullback scans never had this issue.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.mean_reversion import compute_mr_features


def _make_ohlcv(n_rows: int = 250, last_price: float = 51.77) -> pd.DataFrame:
    """Build a yfinance-shaped OHLCV df with N rows, last close = last_price.

    250 rows ensures we have >200 for the EMA(200) computation.
    """
    rng = np.random.default_rng(42)
    closes = np.concatenate([
        rng.uniform(50.0, 55.0, n_rows - 1),
        np.array([last_price]),
    ])
    return pd.DataFrame({
        "Open": closes - 0.5,
        "High": closes + 1.0,
        "Low": closes - 1.0,
        "Close": closes,
        "Volume": rng.integers(1_000_000, 50_000_000, n_rows),
    })


def test_mr_features_dict_includes_current_price_key():
    """The fix: compute_mr_features must return `current_price` so
    build_packet_from_features doesn't fall back to its 0.0 default."""
    df = _make_ohlcv(last_price=51.77)
    config = {"strategies": {"mean_reversion": {"enabled": True}}}
    features = compute_mr_features("BAC", df, config)
    assert features is not None
    assert "current_price" in features, (
        "compute_mr_features must include 'current_price' (canonical key consumed "
        "by build_packet_from_features). Pre-fix the dict only had 'last_close', "
        "causing #621 packet refusal on every MR scan."
    )
    assert features["current_price"] == 51.77


def test_mr_features_current_price_matches_last_close():
    """current_price and last_close must point to the same value (alias for
    back-compat: existing callers reading last_close keep working)."""
    df = _make_ohlcv(last_price=274.30)
    config = {"strategies": {"mean_reversion": {"enabled": True}}}
    features = compute_mr_features("AMZN", df, config)
    assert features is not None
    assert features["current_price"] == features["last_close"]


def test_mr_features_current_price_nonzero_for_real_ticker():
    """Direct repro: BAC at $51.77 (the production-observed value 2026-05-08)
    must surface as current_price=51.77, not 0.0."""
    df = _make_ohlcv(last_price=51.77)
    config = {"strategies": {"mean_reversion": {"enabled": True}}}
    features = compute_mr_features("BAC", df, config)
    assert features is not None
    assert features["current_price"] > 0
    assert features["current_price"] == 51.77


def test_build_packet_from_features_accepts_mr_feature_dict():
    """End-to-end: compute_mr_features → build_packet_from_features must NOT
    return None for a healthy MR ticker. Pre-fix this returned None because
    current_price defaulted to 0; post-fix the packet builds successfully."""
    from src.packets.template import build_packet_from_features
    df = _make_ohlcv(last_price=274.30)
    config = {
        "strategies": {"mean_reversion": {"enabled": True}},
        "risk": {"starting_capital": 100_000},
        "risk_governor": {"max_position_pct": 0.25},
    }
    features = compute_mr_features("AMZN", df, config)
    assert features is not None

    # Add the score field that mr_scan_service.py:113 sets before build_packet
    features["_score"] = 75.0
    features["strategy_type"] = "mean_reversion"

    packet = build_packet_from_features("AMZN", features, config, strategy_name="mean_reversion")
    assert packet is not None, (
        "Pre-fix: packet=None due to current_price=0 default → #621 refusal. "
        "Post-fix: packet builds with current_price from MR features."
    )
    assert packet.ticker == "AMZN"


def test_pullback_features_already_have_current_price():
    """Sibling-search check: confirm compute_all_features (pullback scan path)
    ALSO returns current_price. This was working pre-fix; locked here to detect
    if a future refactor accidentally drops it from either schema."""
    from src.features.engine import _compute_price_features
    df = _make_ohlcv(last_price=100.0)
    feat = _compute_price_features(df["Close"], df["High"], df["Low"], df["Volume"])
    assert "current_price" in feat
    assert feat["current_price"] == 100.0
