"""Sprint 0 Wave 5a — PIT-FEATURES + ENGINE-FAIL-LOUD regression tests.

Covers four bug classes:
  1. ENGINE-PIT — compute_features must respect as_of and slice frames.
  2. ENGINE-FAIL — compute_all_features must raise FeatureComputationError
     when >50% of shared enrichment loaders fail; partial failures must
     surface as _partial_failure_count and log at WARNING.
  3. EARNINGS-PIT — get_next_earnings_date / check_earnings_overlap must
     accept as_of and never reach back to date.today() when as_of is set.
  4. EVENT-PROXIMITY-PIT — get_event_proximity_features must respect
     as_of (reference_date) and never silently use date.today().
"""

from __future__ import annotations

import csv
import logging
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.features.engine import (
    FeatureComputationError,
    compute_all_features,
    compute_features,
)
from src.features.earnings import (
    check_earnings_overlap,
    get_next_earnings_date,
)
from src.features.event_proximity import (
    _load_event_calendar,
    get_event_proximity_features,
    get_upcoming_events,
)


# ---------------------------------------------------------------------------
# Synthetic OHLCV builders
# ---------------------------------------------------------------------------


def _make_ohlcv(n: int = 250, start_price: float = 100.0,
                end_date: pd.Timestamp = pd.Timestamp("2026-03-20")) -> pd.DataFrame:
    dates = pd.bdate_range(end=end_date, periods=n)
    rng = np.random.default_rng(42)
    drift = np.full(n, 0.0008)
    noise = rng.normal(0, 0.005, n)
    close = start_price * np.cumprod(1 + drift + noise)
    high = close * 1.01
    low = close * 0.99
    open_ = close * 1.002
    volume = np.full(n, 1_000_000.0)
    return pd.DataFrame({
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }, index=dates)


def _make_spy(n: int = 250, start_price: float = 450.0,
              end_date: pd.Timestamp = pd.Timestamp("2026-03-20")) -> pd.DataFrame:
    dates = pd.bdate_range(end=end_date, periods=n)
    rng = np.random.default_rng(7)
    drift = np.full(n, 0.0003)
    noise = rng.normal(0, 0.003, n)
    close = start_price * np.cumprod(1 + drift + noise)
    high = close * 1.005
    low = close * 0.995
    open_ = close * 1.001
    volume = np.full(n, 50_000_000.0)
    return pd.DataFrame({
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }, index=dates)


# ---------------------------------------------------------------------------
# Bug 1: ENGINE-PIT — compute_features respects as_of
# ---------------------------------------------------------------------------


def test_compute_features_respects_as_of():
    """When as_of is in the middle of the frame, no row beyond as_of is used.

    Strategy: build a frame that extends well past as_of, then run with
    as_of mid-frame. Compare the result to a manually-sliced frame
    computed without as_of. They must agree exactly: this proves
    compute_features only saw rows <= as_of.
    """
    # Frame: 800 business days ending 2026-03-20. as_of=2024-01-15 sits
    # ~550 days from end and ~250 days from start, leaving plenty of
    # history for SMA200 in the as_of slice.
    end = pd.Timestamp("2026-03-20")
    ohlcv = _make_ohlcv(n=800, end_date=end)
    spy = _make_spy(n=800, end_date=end)

    as_of = date(2025, 1, 15)
    sliced_ohlcv = ohlcv[ohlcv.index <= pd.Timestamp(as_of)]
    sliced_spy = spy[spy.index <= pd.Timestamp(as_of)]

    # Both must have enough rows to compute.
    assert len(sliced_ohlcv) >= 200, "fixture too short — bump n"

    legacy = compute_features("TEST", sliced_ohlcv, sliced_spy)
    pit = compute_features("TEST", ohlcv, spy, as_of=as_of)

    # Every numeric/categorical key must match — slicing in compute_features
    # with as_of must produce identical output to caller-pre-sliced frames.
    for key in ("current_price", "sma_50", "sma_200", "trend_state",
                "pullback_depth_pct", "atr_14", "rs_vs_spy_1m",
                "rs_vs_spy_3m", "rs_vs_spy_6m", "volume_ratio_20d"):
        assert pit[key] == legacy[key], (
            f"as_of={as_of}: key {key!r} differs "
            f"(pit={pit[key]!r}, legacy={legacy[key]!r}) — "
            f"compute_features leaked future rows"
        )

    # Double-guard: current_price must equal the close at as_of, not the
    # close at end of frame.
    expected_current = float(sliced_ohlcv["Close"].iloc[-1])
    end_current = float(ohlcv["Close"].iloc[-1])
    assert pit["current_price"] == pytest.approx(expected_current)
    assert pit["current_price"] != pytest.approx(end_current), (
        "compute_features leaked end-of-frame close into as_of result"
    )


def test_compute_features_legacy_no_as_of_unchanged():
    """Calling compute_features without as_of preserves legacy behavior."""
    ohlcv = _make_ohlcv()
    spy = _make_spy()

    legacy = compute_features("TEST", ohlcv, spy)
    explicit_none = compute_features("TEST", ohlcv, spy, as_of=None)

    assert legacy == explicit_none
    # current_price equals end-of-frame close (live-scan behavior).
    assert legacy["current_price"] == pytest.approx(float(ohlcv["Close"].iloc[-1]))


def test_compute_features_accepts_iso_string_as_of():
    """as_of accepts ISO date strings, not just date objects."""
    end = pd.Timestamp("2026-03-20")
    ohlcv = _make_ohlcv(n=800, end_date=end)
    spy = _make_spy(n=800, end_date=end)

    via_date = compute_features("TEST", ohlcv, spy, as_of=date(2025, 1, 15))
    via_str = compute_features("TEST", ohlcv, spy, as_of="2025-01-15")

    # Cross-check key by key — direct dict equality breaks because dicts
    # may contain NaN values which compare false to themselves; the
    # current synthetic frame doesn't produce NaN here, but using
    # explicit per-key comparison is robust regardless.
    for key in via_date:
        a = via_date[key]
        b = via_str[key]
        if isinstance(a, float) and np.isnan(a):
            assert isinstance(b, float) and np.isnan(b), f"key {key!r}"
        else:
            assert a == b, f"key {key!r}: date={a!r} str={b!r}"


# ---------------------------------------------------------------------------
# Bug 2: ENGINE-FAIL — fail-loud on majority enrichment failure
# ---------------------------------------------------------------------------


def _make_universe() -> dict[str, pd.DataFrame]:
    return {
        "AAPL": _make_ohlcv(),
        "MSFT": _make_ohlcv(start_price=200.0),
    }


def test_engine_fail_loud_on_majority_failure(caplog):
    """3 of 4 shared enrichment loaders fail -> FeatureComputationError."""
    spy = _make_spy()
    ohlcv_data = _make_universe()

    with patch(
        "src.features.regime.compute_market_regime",
        side_effect=RuntimeError("regime DB down"),
    ), patch(
        "src.features.engine._load_options_metrics",
        side_effect=RuntimeError("options DB unreachable"),
    ), patch(
        "src.features.engine._load_event_proximity",
        side_effect=RuntimeError("event calendar corrupt"),
    ), patch(
        "src.features.engine._load_sector_profiles",
        return_value={},
    ):
        with caplog.at_level(logging.WARNING, logger="src.features.engine"):
            with pytest.raises(FeatureComputationError) as exc_info:
                compute_all_features(ohlcv_data, spy)

    msg = str(exc_info.value)
    assert "3/4" in msg
    assert "shared enrichment" in msg.lower()

    # All three failures must have been logged at WARNING.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("regime" in r.getMessage().lower() for r in warnings)
    assert any("options" in r.getMessage().lower() for r in warnings)
    assert any("event proximity" in r.getMessage().lower() for r in warnings)


def test_engine_fail_loud_on_all_four_failures():
    """4 of 4 shared loaders fail -> FeatureComputationError."""
    spy = _make_spy()
    ohlcv_data = _make_universe()

    with patch(
        "src.features.regime.compute_market_regime",
        side_effect=RuntimeError("regime down"),
    ), patch(
        "src.features.engine._load_options_metrics",
        side_effect=RuntimeError("options down"),
    ), patch(
        "src.features.engine._load_event_proximity",
        side_effect=RuntimeError("events down"),
    ), patch(
        "src.features.engine._load_sector_profiles",
        side_effect=RuntimeError("sectors down"),
    ):
        with pytest.raises(FeatureComputationError) as exc_info:
            compute_all_features(ohlcv_data, spy)
    assert "4/4" in str(exc_info.value)


def test_engine_partial_failure_logged_at_warning(caplog):
    """1 of 4 shared loaders fails -> WARNING log + no raise.

    With 1 of 4 failed, threshold (>50%) is not crossed; engine should
    still produce features, but the failure must be visible at WARNING.
    """
    spy = _make_spy()
    ohlcv_data = _make_universe()

    with patch(
        "src.features.regime.compute_market_regime",
        side_effect=RuntimeError("regime degraded"),
    ), patch(
        "src.features.engine._load_options_metrics",
        return_value={},
    ), patch(
        "src.features.engine._load_event_proximity",
        return_value={
            "event_proximity_type": None,
            "event_proximity_days": None,
            "event_proximity_desc": None,
            "events_within_3d": 0,
        },
    ), patch(
        "src.features.engine._load_sector_profiles",
        return_value={},
    ), patch(
        "src.features.earnings.get_next_earnings_date",
        return_value=None,
    ):
        with caplog.at_level(logging.WARNING, logger="src.features.engine"):
            result = compute_all_features(ohlcv_data, spy)

    # Did NOT raise — partial degradation is allowed.
    assert "AAPL" in result
    assert "MSFT" in result

    # WARNING was logged for the regime failure.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("regime" in r.getMessage().lower() for r in warnings), (
        f"expected regime WARNING, got: {[r.getMessage() for r in warnings]}"
    )


def test_engine_per_ticker_partial_failure_count(caplog):
    """When per-ticker setup_classifier fails, _partial_failure_count surfaces.

    Healthy tickers must NOT carry _partial_failure_count (preserves the
    sprint_F fixture hashes for tickers that didn't degrade).
    """
    spy = _make_spy()
    ohlcv_data = _make_universe()

    def _fail_for_aapl(feat, df):
        if feat.get("ticker") == "AAPL":
            raise RuntimeError("setup classifier crash for AAPL")
        return {
            "setup_type": "pullback",
            "confidence": 0.7,
            "tradeable_by_desk": "intraday",
        }

    with patch(
        "src.features.engine._load_options_metrics",
        return_value={},
    ), patch(
        "src.features.engine._load_event_proximity",
        return_value={
            "event_proximity_type": None,
            "event_proximity_days": None,
            "event_proximity_desc": None,
            "events_within_3d": 0,
        },
    ), patch(
        "src.features.engine._load_sector_profiles",
        return_value={},
    ), patch(
        "src.features.earnings.get_next_earnings_date",
        return_value=None,
    ), patch(
        "src.features.setup_classifier.classify_setup",
        side_effect=_fail_for_aapl,
    ), patch(
        "src.features.setup_classifier.log_setup_signal",
        return_value=None,
    ):
        with caplog.at_level(logging.WARNING, logger="src.features.engine"):
            result = compute_all_features(ohlcv_data, spy)

    # AAPL: setup_classifier raised -> partial failure count == 1.
    assert "AAPL" in result
    assert result["AAPL"].get("_partial_failure_count") == 1
    assert result["AAPL"]["setup_type"] == "unknown"

    # MSFT: clean run -> no _partial_failure_count key.
    assert "MSFT" in result
    assert "_partial_failure_count" not in result["MSFT"]


# ---------------------------------------------------------------------------
# Bug 3: EARNINGS-PIT
# ---------------------------------------------------------------------------


def test_check_earnings_overlap_respects_as_of():
    """check_earnings_overlap days_to_earnings is anchored to as_of, not today."""
    earnings = "2024-02-01"
    as_of = date(2024, 1, 15)

    out = check_earnings_overlap(earnings, as_of=as_of)

    assert out["days_to_earnings"] == 17  # Feb 1 - Jan 15 = 17 days
    assert out["hold_overlaps_earnings"] is False  # >10 days
    assert out["event_risk_level"] == "none"


def test_check_earnings_overlap_imminent_via_as_of():
    """as_of close to earnings -> imminent classification."""
    earnings = "2024-01-17"
    as_of = date(2024, 1, 15)

    out = check_earnings_overlap(earnings, as_of=as_of)

    assert out["days_to_earnings"] == 2
    assert out["event_risk_level"] == "imminent"


def test_check_earnings_overlap_no_as_of_uses_today():
    """Backward compat: omit as_of -> uses date.today()."""
    today = date.today()
    earnings = (today + timedelta(days=5)).isoformat()

    out = check_earnings_overlap(earnings)

    assert out["days_to_earnings"] == 5


def test_get_next_earnings_date_respects_as_of_via_cache():
    """get_next_earnings_date forwards as_of to the cached lookup."""
    captured = {}

    def _fake_get(ticker, days, as_of=None):
        captured["ticker"] = ticker
        captured["days"] = days
        captured["as_of"] = as_of
        return {"earnings_date": "2024-02-15"}

    with patch(
        "scripts.fetch_earnings_calendar.get_earnings_within_days",
        side_effect=_fake_get,
    ):
        result = get_next_earnings_date("AAPL", as_of=date(2024, 1, 15))

    assert result == "2024-02-15"
    assert captured["ticker"] == "AAPL"
    assert captured["days"] == 90
    assert captured["as_of"] == date(2024, 1, 15)


def test_get_next_earnings_date_with_as_of_skips_yfinance():
    """When as_of is set and cache misses, yfinance fallback is suppressed.

    yfinance would return today's-view earnings — that's future-leaking in
    a historical scan. Must return None instead of querying yfinance.
    """
    with patch(
        "scripts.fetch_earnings_calendar.get_earnings_within_days",
        return_value=None,
    ), patch("yfinance.Ticker") as yf_ticker:
        result = get_next_earnings_date("AAPL", as_of=date(2024, 1, 15))

    assert result is None
    yf_ticker.assert_not_called()


def test_get_next_earnings_date_no_as_of_allows_yfinance():
    """Live scan (no as_of): yfinance fallback is still allowed."""
    with patch(
        "scripts.fetch_earnings_calendar.get_earnings_within_days",
        return_value=None,
    ), patch("yfinance.Ticker") as yf_ticker:
        # yf may raise; we only care that it was at least attempted.
        yf_ticker.side_effect = RuntimeError("offline test")
        result = get_next_earnings_date("AAPL")

    assert result is None
    yf_ticker.assert_called()


# ---------------------------------------------------------------------------
# Bug 4: EVENT-PROXIMITY-PIT
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_calendar():
    """Build a temp calendar with events around 2024-01-15."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline="",
    )
    writer = csv.DictWriter(tmp, fieldnames=["date", "event_type", "description"])
    writer.writeheader()
    for row in [
        {"date": "2024-01-13", "event_type": "FOMC", "description": "Past FOMC"},
        {"date": "2024-01-17", "event_type": "CPI", "description": "Future CPI"},
        {"date": "2024-01-19", "event_type": "GDP", "description": "Future GDP"},
        {"date": "2026-04-26", "event_type": "FOMC", "description": "Way later"},
    ]:
        writer.writerow(row)
    tmp.close()
    path = Path(tmp.name)

    _load_event_calendar.cache_clear()
    yield path
    _load_event_calendar.cache_clear()


def test_get_event_proximity_features_respects_as_of(temp_calendar):
    """reference_date=2024-01-15 surfaces 2024-01-17 CPI, not the 2026 FOMC."""
    with patch(
        "src.features.event_proximity.CALENDAR_PATH",
        temp_calendar,
    ):
        feats = get_event_proximity_features(reference_date=date(2024, 1, 15))

    assert feats["event_proximity_type"] == "CPI"
    assert feats["event_proximity_days"] == 2  # Jan 17 - Jan 15
    assert feats["events_within_3d"] == 1  # only CPI within 3d


def test_get_event_proximity_features_excludes_past_events(temp_calendar):
    """Events before reference_date must not surface."""
    with patch(
        "src.features.event_proximity.CALENDAR_PATH",
        temp_calendar,
    ):
        feats = get_event_proximity_features(reference_date=date(2024, 1, 15))
        upcoming = get_upcoming_events(days=10, reference_date=date(2024, 1, 15))

    # The 2024-01-13 FOMC must not appear as upcoming.
    assert all(e["event_type"] != "FOMC" or e["days_away"] >= 0 for e in upcoming)
    types = {e["event_type"] for e in upcoming}
    assert "CPI" in types
    assert "GDP" in types


def test_event_calendar_cache_invalidates_on_mtime_change(temp_calendar):
    """Rewriting the calendar invalidates the LRU cache.

    Sprint 0/Wave 5a EVENT-PROXIMITY-PIT: previous lru_cache(maxsize=1) was
    held for the full process lifetime — operators had no way to reload
    without restarting. New cache key includes file mtime.
    """
    import time

    with patch(
        "src.features.event_proximity.CALENDAR_PATH",
        temp_calendar,
    ):
        first = get_upcoming_events(
            days=400, reference_date=date(2024, 1, 1),
        )
        first_count = len(first)
        assert first_count >= 3  # at least 2024-01-13/17/19

        # Rewrite the calendar with one new event AFTER bumping mtime.
        time.sleep(0.05)  # ensure mtime changes on coarse-resolution FS
        with open(temp_calendar, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["date", "event_type", "description"],
            )
            writer.writeheader()
            writer.writerow({
                "date": "2024-02-01",
                "event_type": "FOMC",
                "description": "Solo event after rewrite",
            })

        # Force mtime to be strictly later (some filesystems have 1s resolution).
        new_mtime = temp_calendar.stat().st_mtime + 2.0
        import os
        os.utime(temp_calendar, (new_mtime, new_mtime))

        second = get_upcoming_events(
            days=400, reference_date=date(2024, 1, 1),
        )

    assert len(second) == 1, (
        f"cache did not invalidate on mtime change: "
        f"first count={first_count}, second={len(second)}"
    )
    assert second[0]["event_type"] == "FOMC"
    assert second[0]["description"] == "Solo event after rewrite"


def test_get_event_proximity_features_iso_string_reference():
    """reference_date accepts ISO strings, not just date objects."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline="",
    )
    writer = csv.DictWriter(
        tmp, fieldnames=["date", "event_type", "description"],
    )
    writer.writeheader()
    writer.writerow({
        "date": "2024-01-17",
        "event_type": "CPI",
        "description": "test",
    })
    tmp.close()
    path = Path(tmp.name)

    _load_event_calendar.cache_clear()
    try:
        with patch(
            "src.features.event_proximity.CALENDAR_PATH",
            path,
        ):
            via_date = get_event_proximity_features(
                reference_date=date(2024, 1, 15),
            )
            via_str = get_event_proximity_features(
                reference_date="2024-01-15",
            )
    finally:
        _load_event_calendar.cache_clear()

    assert via_date == via_str
    assert via_date["event_proximity_type"] == "CPI"
