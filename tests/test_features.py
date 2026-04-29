"""Tests for the feature engine using synthetic data only."""

import sqlite3
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.features.engine import compute_features, compute_all_features
from tests.conftest import init_test_db


def _make_uptrend_ohlcv(n: int = 250, start_price: float = 100.0) -> pd.DataFrame:
    """Create a synthetic uptrending OHLCV DataFrame."""
    dates = pd.bdate_range(end=pd.Timestamp('2026-03-20'), periods=n)
    # Steady uptrend: ~0.1% daily gain
    close = start_price * np.cumprod(1 + np.full(n, 0.001))
    # Add small recent pullback in last 5 days
    close[-5:] = close[-6] * np.array([0.995, 0.993, 0.991, 0.992, 0.993])
    high = close * 1.01
    low = close * 0.99
    open_ = close * 1.002
    volume = np.full(n, 1_000_000.0)
    # Reduce recent volume for volume contraction signal
    volume[-5:] = 700_000.0

    return pd.DataFrame({
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }, index=dates)


def _make_spy_ohlcv(n: int = 250, start_price: float = 450.0) -> pd.DataFrame:
    """Create a synthetic SPY DataFrame with modest uptrend."""
    dates = pd.bdate_range(end=pd.Timestamp('2026-03-20'), periods=n)
    close = start_price * np.cumprod(1 + np.full(n, 0.0003))
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


EXPECTED_KEYS = [
    "ticker", "current_price",
    "sma_50", "sma_200",
    "price_vs_sma50_pct", "price_vs_sma200_pct",
    "sma50_slope", "sma200_slope", "trend_state",
    "rs_vs_spy_1m", "rs_vs_spy_3m", "rs_vs_spy_6m",
    "relative_strength_state",
    "pullback_depth_pct", "atr_14", "atr_pct",
    "dist_to_sma20_pct", "volume_ratio_20d",
]


def test_all_keys_present():
    ohlcv = _make_uptrend_ohlcv()
    spy = _make_spy_ohlcv()
    features = compute_features("TEST", ohlcv, spy)
    for key in EXPECTED_KEYS:
        assert key in features, f"Missing key: {key}"


def test_uptrend_classification():
    ohlcv = _make_uptrend_ohlcv()
    spy = _make_spy_ohlcv()
    features = compute_features("TEST", ohlcv, spy)
    assert features["trend_state"] in ("strong_uptrend", "uptrend"), \
        f"Expected uptrend, got {features['trend_state']}"


def test_pullback_depth():
    ohlcv = _make_uptrend_ohlcv()
    spy = _make_spy_ohlcv()
    features = compute_features("TEST", ohlcv, spy)
    # The synthetic data has a small pullback in the last 5 days
    assert features["pullback_depth_pct"] < 0, "Pullback depth should be negative"
    assert features["pullback_depth_pct"] > -5, "Pullback should be shallow"


def test_relative_strength_outperformer():
    ohlcv = _make_uptrend_ohlcv()
    spy = _make_spy_ohlcv()  # SPY trends slower than the ticker
    features = compute_features("TEST", ohlcv, spy)
    assert features["relative_strength_state"] in ("strong_outperformer", "outperformer"), \
        f"Expected outperformer, got {features['relative_strength_state']}"


def test_volume_ratio():
    ohlcv = _make_uptrend_ohlcv()
    spy = _make_spy_ohlcv()
    features = compute_features("TEST", ohlcv, spy)
    # Recent volume is 700k vs 20-day avg that includes 1M days
    assert features["volume_ratio_20d"] < 1.0, "Volume ratio should be below 1 due to contraction"


def test_compute_all_features_skips_short():
    ohlcv = _make_uptrend_ohlcv(n=100)  # Too short
    spy = _make_spy_ohlcv()
    result = compute_all_features({"SHORT": ohlcv}, spy)
    assert "SHORT" not in result


def test_compute_all_features_processes_valid():
    ohlcv = _make_uptrend_ohlcv()
    spy = _make_spy_ohlcv()
    result = compute_all_features({"GOOD": ohlcv}, spy)
    assert "GOOD" in result
    assert "ticker" in result["GOOD"]


# ---------------------------------------------------------------------------
# #858 Option A — _load_options_metrics PIT routing tests
# ---------------------------------------------------------------------------


class TestLoadOptionsMetricsPIT:
    """Tests for the as_of parameter in engine_helpers._load_options_metrics (#858).

    Verifies that:
    - Default (as_of=None) preserves runtime behavior (per-ticker latest snapshot)
    - as_of='YYYY-MM-DD' filters by `collected_date <= as_of` (PIT compliance)
    - The loader's per-ticker SELECT (not a single global MAX) ensures every
      ticker with data gets its most recent visible snapshot
    - The loader's per-row dict aliases `iv_skew` -> `iv_skew_25d` (the prompt
      key in src.llm.packet_writer._interpret_skew + Section 8 prompt template)
    - The loader's SELECT now includes `iv_percentile` and `atm_iv_30d` (both
      populated in the schema; previously dropped)
    """

    @staticmethod
    def _seed(db_path: str, rows: list[dict]) -> None:
        """Insert synthetic options_metrics rows."""
        conn = sqlite3.connect(db_path)
        try:
            for r in rows:
                conn.execute(
                    "INSERT INTO options_metrics "
                    "(collected_at, collected_date, ticker, iv_rank, iv_percentile, "
                    " put_call_volume_ratio, put_call_oi_ratio, atm_iv_30d, "
                    " iv_skew, unusual_volume_flag) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        r["collected_at"], r["collected_date"], r["ticker"],
                        r.get("iv_rank"), r.get("iv_percentile"),
                        r.get("put_call_volume_ratio"), r.get("put_call_oi_ratio"),
                        r.get("atm_iv_30d"), r.get("iv_skew"),
                        r.get("unusual_volume_flag", 0),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def test_default_no_as_of_returns_global_latest(self, tmp_path, monkeypatch):
        """Default (None) preserves runtime behavior: returns latest snapshot per ticker."""
        from src.features import engine_helpers

        db = str(tmp_path / "opts.db")
        init_test_db(db, ["options_metrics"])
        # Two snapshots for AAPL — should return the more recent one.
        self._seed(db, [
            {
                "collected_at": "2024-06-01T16:00:00", "collected_date": "2024-06-01",
                "ticker": "AAPL", "iv_rank": 0.30, "iv_percentile": 0.40,
                "put_call_volume_ratio": 0.8, "put_call_oi_ratio": 0.9,
                "atm_iv_30d": 0.20, "iv_skew": 0.01, "unusual_volume_flag": 0,
            },
            {
                "collected_at": "2024-09-01T16:00:00", "collected_date": "2024-09-01",
                "ticker": "AAPL", "iv_rank": 0.55, "iv_percentile": 0.60,
                "put_call_volume_ratio": 1.1, "put_call_oi_ratio": 1.0,
                "atm_iv_30d": 0.25, "iv_skew": 0.03, "unusual_volume_flag": 1,
            },
        ])

        monkeypatch.setattr(engine_helpers, "DB_PATH", db)
        result = engine_helpers._load_options_metrics()

        assert "AAPL" in result
        # Should be the most recent (2024-09-01) snapshot.
        assert result["AAPL"]["iv_rank"] == pytest.approx(0.55)
        assert result["AAPL"]["unusual_options_activity"] is True

    def test_as_of_filters_to_historical_view(self, tmp_path, monkeypatch):
        """as_of='YYYY-MM-DD' returns the most recent snapshot <= as_of, not the latest."""
        from src.features import engine_helpers

        db = str(tmp_path / "opts.db")
        init_test_db(db, ["options_metrics"])
        # AAPL: 3 snapshots 2024-06-01, 2024-09-01, 2024-12-01.
        # At as_of='2024-08-01', visible snapshots: only 2024-06-01.
        self._seed(db, [
            {
                "collected_at": "2024-06-01T16:00:00", "collected_date": "2024-06-01",
                "ticker": "AAPL", "iv_rank": 0.30, "iv_percentile": 0.40,
                "put_call_volume_ratio": 0.8, "put_call_oi_ratio": 0.9,
                "atm_iv_30d": 0.20, "iv_skew": 0.01, "unusual_volume_flag": 0,
            },
            {
                "collected_at": "2024-09-01T16:00:00", "collected_date": "2024-09-01",
                "ticker": "AAPL", "iv_rank": 0.55, "iv_percentile": 0.60,
                "put_call_volume_ratio": 1.1, "put_call_oi_ratio": 1.0,
                "atm_iv_30d": 0.25, "iv_skew": 0.03, "unusual_volume_flag": 1,
            },
            {
                "collected_at": "2024-12-01T16:00:00", "collected_date": "2024-12-01",
                "ticker": "AAPL", "iv_rank": 0.80, "iv_percentile": 0.85,
                "put_call_volume_ratio": 1.4, "put_call_oi_ratio": 1.2,
                "atm_iv_30d": 0.30, "iv_skew": 0.05, "unusual_volume_flag": 1,
            },
        ])

        monkeypatch.setattr(engine_helpers, "DB_PATH", db)
        result = engine_helpers._load_options_metrics(as_of="2024-08-01")

        assert "AAPL" in result
        # Must be the 2024-06-01 row — NOT 2024-09-01 (PIT violation) or 2024-12-01.
        assert result["AAPL"]["iv_rank"] == pytest.approx(0.30), (
            "PIT violation: post-as_of options snapshot leaked into historical view"
        )
        assert result["AAPL"]["unusual_options_activity"] is False

    def test_iv_skew_25d_alias(self, tmp_path, monkeypatch):
        """The dict key the LLM prompt reads is `iv_skew_25d` (not `iv_skew`).

        src/llm/packet_writer.py:129 (`_interpret_skew`) and the Section 8
        prompt template at packet_writer.py:260 read `features.get('iv_skew_25d')`.
        Loader must alias the schema column `iv_skew` to that key.
        """
        from src.features import engine_helpers

        db = str(tmp_path / "opts.db")
        init_test_db(db, ["options_metrics"])
        self._seed(db, [
            {
                "collected_at": "2024-06-01T16:00:00", "collected_date": "2024-06-01",
                "ticker": "AAPL", "iv_rank": 0.50, "iv_percentile": 0.55,
                "put_call_volume_ratio": 1.0, "put_call_oi_ratio": 0.95,
                "atm_iv_30d": 0.22, "iv_skew": 0.07, "unusual_volume_flag": 0,
            },
        ])

        monkeypatch.setattr(engine_helpers, "DB_PATH", db)
        result = engine_helpers._load_options_metrics()

        assert "AAPL" in result
        assert "iv_skew_25d" in result["AAPL"], (
            "Loader must expose `iv_skew_25d` so packet_writer's _interpret_skew "
            "and Section 8 prompt template populate (not render 'n/a')"
        )
        assert result["AAPL"]["iv_skew_25d"] == pytest.approx(0.07)
        # The legacy key MUST NOT be returned — prevents silent prompt drift.
        assert "iv_skew" not in result["AAPL"]

    def test_iv_percentile_and_atm_iv_30d_returned(self, tmp_path, monkeypatch):
        """Previously-dropped columns (iv_percentile, atm_iv_30d) are now in the result."""
        from src.features import engine_helpers

        db = str(tmp_path / "opts.db")
        init_test_db(db, ["options_metrics"])
        self._seed(db, [
            {
                "collected_at": "2024-06-01T16:00:00", "collected_date": "2024-06-01",
                "ticker": "AAPL", "iv_rank": 0.50, "iv_percentile": 0.65,
                "put_call_volume_ratio": 1.0, "put_call_oi_ratio": 0.95,
                "atm_iv_30d": 0.28, "iv_skew": 0.02, "unusual_volume_flag": 0,
            },
        ])

        monkeypatch.setattr(engine_helpers, "DB_PATH", db)
        result = engine_helpers._load_options_metrics()

        assert "AAPL" in result
        assert "iv_percentile" in result["AAPL"]
        assert result["AAPL"]["iv_percentile"] == pytest.approx(0.65)
        assert "atm_iv_30d" in result["AAPL"]
        assert result["AAPL"]["atm_iv_30d"] == pytest.approx(0.28)

    def test_per_ticker_latest(self, tmp_path, monkeypatch):
        """Every ticker with data appears in result, with its own latest snapshot.

        The current global MAX(collected_at) bug excludes tickers whose latest
        date != the globally-latest date. Fix returns per-ticker max.
        """
        from src.features import engine_helpers

        db = str(tmp_path / "opts.db")
        init_test_db(db, ["options_metrics"])
        # AAPL last seen 2024-12-01; MSFT last seen 2024-11-01.
        # Pre-fix: only AAPL would appear (its date == global MAX).
        # Post-fix: BOTH appear, each with its own latest snapshot.
        self._seed(db, [
            {
                "collected_at": "2024-12-01T16:00:00", "collected_date": "2024-12-01",
                "ticker": "AAPL", "iv_rank": 0.80, "iv_percentile": 0.85,
                "put_call_volume_ratio": 1.4, "put_call_oi_ratio": 1.2,
                "atm_iv_30d": 0.30, "iv_skew": 0.05, "unusual_volume_flag": 1,
            },
            {
                "collected_at": "2024-11-01T16:00:00", "collected_date": "2024-11-01",
                "ticker": "MSFT", "iv_rank": 0.45, "iv_percentile": 0.50,
                "put_call_volume_ratio": 0.95, "put_call_oi_ratio": 0.90,
                "atm_iv_30d": 0.18, "iv_skew": 0.01, "unusual_volume_flag": 0,
            },
        ])

        monkeypatch.setattr(engine_helpers, "DB_PATH", db)
        result = engine_helpers._load_options_metrics()

        assert "AAPL" in result
        assert "MSFT" in result, (
            "Per-ticker latest: MSFT must appear even though its latest date "
            "(2024-11-01) is older than AAPL's (2024-12-01); the global "
            "MAX(collected_at) subquery excluded it pre-fix."
        )
        assert result["AAPL"]["iv_rank"] == pytest.approx(0.80)
        assert result["MSFT"]["iv_rank"] == pytest.approx(0.45)


def test_compute_all_features_with_as_of_propagates_to_options_loader():
    """compute_all_features routes its as_of to engine._load_options_metrics.

    Integration test: when compute_all_features is called with as_of, the
    options loader receives that same as_of. Mirrors the #854/#856/#857
    Phase 2 PIT plumbing so historical decision points see PIT-clean
    options data.
    """
    ohlcv = _make_uptrend_ohlcv()
    spy = _make_spy_ohlcv()

    captured: dict = {}

    def fake_options_loader(as_of=None):
        captured["as_of"] = as_of
        return {}

    with patch(
        "src.features.engine._load_options_metrics", side_effect=fake_options_loader,
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
        compute_all_features({"GOOD": ohlcv}, spy, as_of="2024-06-15")

    assert "as_of" in captured, (
        "_load_options_metrics was not called with an as_of kwarg — "
        "the PIT plumbing didn't reach the options loader."
    )
    assert captured["as_of"] == "2024-06-15", (
        f"Expected as_of='2024-06-15' propagated to loader; got {captured['as_of']!r}"
    )
