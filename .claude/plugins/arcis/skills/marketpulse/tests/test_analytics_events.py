"""Tests for MarketPulse event analytics module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ensure lib is importable
# ---------------------------------------------------------------------------
_MP_ROOT = Path(__file__).resolve().parent.parent
if str(_MP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MP_ROOT))

from tests.fixtures.make_bars import make_bars_df  # noqa: E402
from lib.analytics.events import (  # noqa: E402
    volume_spikes,
    price_gaps,
    anomaly_detection,
    event_impact,
)


# ---------------------------------------------------------------------------
# volume_spikes
# ---------------------------------------------------------------------------


class TestVolumeSpikes:
    """Tests for the ``volume_spikes`` function."""

    def test_volume_spikes_detection(self):
        """Injecting a 10x volume bar should be detected as a spike."""
        df = make_bars_df("AAPL", days=5, bars_per_day=50, seed=42)
        # Inject a massive volume spike at row 100 (well past the 20-bar warm-up)
        mean_vol = df["volume"].mean()
        df.loc[100, "volume"] = mean_vol * 10

        result = volume_spikes(df, threshold=3.0)

        assert len(result.spikes) >= 1
        # The injected spike should be among detected spikes
        injected_ts = df.loc[100, "timestamp"]
        ts_iso = injected_ts.isoformat() if hasattr(injected_ts, "isoformat") else str(injected_ts)
        injected_found = any(s.timestamp == ts_iso for s in result.spikes)
        assert injected_found, "Injected volume spike was not detected"

        # Spike ratio should be > threshold for the injected bar
        for s in result.spikes:
            assert s.spike_ratio > result.threshold

    def test_volume_spikes_threshold(self):
        """threshold=10 should find fewer spikes than threshold=2."""
        df = make_bars_df("AAPL", days=5, bars_per_day=50, seed=42)
        # Inject a few spikes
        mean_vol = df["volume"].mean()
        df.loc[50, "volume"] = mean_vol * 5
        df.loc[100, "volume"] = mean_vol * 8
        df.loc[150, "volume"] = mean_vol * 12

        result_low = volume_spikes(df, threshold=2.0)
        result_high = volume_spikes(df, threshold=10.0)

        assert len(result_low.spikes) >= len(result_high.spikes)
        assert result_low.threshold == 2.0
        assert result_high.threshold == 10.0

    def test_volume_spikes_ticker_filter(self):
        """tickers=["AAPL"] only returns AAPL spikes when multi-ticker data."""
        df = make_bars_df(["AAPL", "MSFT"], days=5, bars_per_day=50, seed=42)
        # Inject spikes in both tickers
        mean_vol = df["volume"].mean()
        # AAPL rows are first (sorted by ticker, timestamp)
        aapl_rows = df[df["ticker"] == "AAPL"].index
        msft_rows = df[df["ticker"] == "MSFT"].index
        df.loc[aapl_rows[100], "volume"] = mean_vol * 10
        df.loc[msft_rows[100], "volume"] = mean_vol * 10

        result = volume_spikes(df, threshold=3.0, tickers=["AAPL"])

        for s in result.spikes:
            assert s.ticker == "AAPL", f"Expected only AAPL, got {s.ticker}"


# ---------------------------------------------------------------------------
# price_gaps
# ---------------------------------------------------------------------------


class TestPriceGaps:
    """Tests for the ``price_gaps`` function."""

    def test_price_gaps_detection(self):
        """Synthetic data over 10 days should produce gap results (possibly small)."""
        df = make_bars_df("AAPL", days=10, bars_per_day=50, seed=42)

        # Use a very low threshold to catch any synthetic overnight movement
        result = price_gaps(df, threshold=0.0001)

        assert isinstance(result.gaps, list)
        assert result.threshold == 0.0001
        # With 10 days of random walks, there should be at least some gaps
        # (9 overnight transitions)
        for g in result.gaps:
            assert g.ticker == "AAPL"
            assert g.direction in ("up", "down")
            assert abs(g.gap_pct) > result.threshold

    def test_price_gaps_threshold(self):
        """threshold=0.001 should find more (or equal) gaps than threshold=0.05."""
        df = make_bars_df("AAPL", days=10, bars_per_day=50, seed=42)

        result_low = price_gaps(df, threshold=0.001)
        result_high = price_gaps(df, threshold=0.05)

        assert len(result_low.gaps) >= len(result_high.gaps)


# ---------------------------------------------------------------------------
# anomaly_detection
# ---------------------------------------------------------------------------


class TestAnomalyDetection:
    """Tests for the ``anomaly_detection`` function."""

    def test_anomaly_detection_return(self):
        """Injecting an extreme return bar should be detected with metric='return'."""
        df = make_bars_df("AAPL", days=5, bars_per_day=390, seed=42)
        # Inject a huge price jump at bar 500 (well past 60-bar warm-up)
        df.loc[500, "close"] = df.loc[500, "open"] * 1.10  # 10% jump in one bar

        result = anomaly_detection(df, z_threshold=3.0)

        return_anomalies = [a for a in result.anomalies if a.metric == "return"]
        assert len(return_anomalies) >= 1, "Extreme return not detected as anomaly"
        assert result.z_threshold == 3.0

    def test_anomaly_detection_volume(self):
        """Injecting extreme volume should be detected with metric='volume'."""
        df = make_bars_df("AAPL", days=5, bars_per_day=390, seed=42)
        # Inject massive volume at bar 500
        mean_vol = df["volume"].mean()
        df.loc[500, "volume"] = mean_vol * 50

        result = anomaly_detection(df, z_threshold=3.0)

        vol_anomalies = [a for a in result.anomalies if a.metric == "volume"]
        assert len(vol_anomalies) >= 1, "Extreme volume not detected as anomaly"


# ---------------------------------------------------------------------------
# event_impact
# ---------------------------------------------------------------------------


class TestEventImpact:
    """Tests for the ``event_impact`` function."""

    def test_event_impact_pre_post(self):
        """Pre and post windows should have correct day counts."""
        df = make_bars_df("AAPL", days=20, bars_per_day=50, seed=42)

        # Pick a date in the middle of the data
        dates = sorted(df["timestamp"].dt.date.astype(str).unique())
        mid_date = dates[len(dates) // 2]

        result = event_impact(df, ticker="AAPL", event_date=mid_date, pre_days=3, post_days=3)

        assert result.ticker == "AAPL"
        assert result.event_date == mid_date
        assert result.pre_window_days <= 3
        assert result.post_window_days <= 3
        assert result.pre_window_days > 0
        assert result.post_window_days > 0

    def test_event_impact_change(self):
        """return_change and volume_change should be computed correctly."""
        df = make_bars_df("AAPL", days=20, bars_per_day=50, seed=42)

        dates = sorted(df["timestamp"].dt.date.astype(str).unique())
        mid_date = dates[len(dates) // 2]

        result = event_impact(df, ticker="AAPL", event_date=mid_date, pre_days=5, post_days=5)

        # return_change = post_avg_return - pre_avg_return
        assert abs(result.return_change - (result.post_avg_return - result.pre_avg_return)) < 1e-10

        # volume_change should be a float (can be positive or negative)
        assert isinstance(result.volume_change, float)

        # If pre_avg_volume > 0, verify formula
        if result.pre_avg_volume > 0:
            expected_vc = (result.post_avg_volume - result.pre_avg_volume) / result.pre_avg_volume
            assert abs(result.volume_change - expected_vc) < 1e-10


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerializationEvents:
    """Verify to_dict() produces JSON-safe output for event types."""

    def test_to_dict_events(self):
        """All event result types should produce JSON-safe dicts via to_dict()."""
        df = make_bars_df("AAPL", days=5, bars_per_day=50, seed=42)
        mean_vol = df["volume"].mean()
        df.loc[100, "volume"] = mean_vol * 10

        # VolumeSpikeResult
        vs_result = volume_spikes(df, threshold=3.0)
        vs_dict = vs_result.to_dict()
        assert isinstance(vs_dict, dict)
        assert "spikes" in vs_dict
        assert "threshold" in vs_dict
        assert isinstance(vs_dict["spikes"], list)

        # PriceGapResult
        pg_result = price_gaps(df, threshold=0.0001)
        pg_dict = pg_result.to_dict()
        assert isinstance(pg_dict, dict)
        assert "gaps" in pg_dict
        assert "threshold" in pg_dict

        # AnomalyDetectionResult
        ad_result = anomaly_detection(df, z_threshold=3.0)
        ad_dict = ad_result.to_dict()
        assert isinstance(ad_dict, dict)
        assert "anomalies" in ad_dict
        assert "z_threshold" in ad_dict

        # EventImpactResult
        dates = sorted(df["timestamp"].dt.date.astype(str).unique())
        mid_date = dates[len(dates) // 2]
        ei_result = event_impact(df, ticker="AAPL", event_date=mid_date)
        ei_dict = ei_result.to_dict()
        assert isinstance(ei_dict, dict)
        assert "ticker" in ei_dict
        assert "event_date" in ei_dict
        assert "return_change" in ei_dict
        assert "volume_change" in ei_dict
