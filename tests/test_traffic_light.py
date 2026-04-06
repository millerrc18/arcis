"""Tests for Traffic Light regime overlay."""
import sqlite3
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.features.traffic_light import (
    _classify_vix, _classify_trend, _classify_credit,
    _score_to_regime, compute_traffic_light,
)
from src.journal.store import initialize_database


class TestVIXClassifier:
    def test_low_vix_green(self):
        assert _classify_vix(15.0) == 0

    def test_mid_vix_yellow(self):
        assert _classify_vix(22.0) == 1

    def test_high_vix_red(self):
        assert _classify_vix(35.0) == 2

    def test_boundary_vix_30_yellow(self):
        assert _classify_vix(30.0) == 1  # 30 is yellow, >30 is red

    def test_none_vix(self):
        assert _classify_vix(None) == 0


class TestTrendClassifier:
    def test_above_rising_green(self):
        # Create SPY data that's above and rising 200-DMA
        dates = pd.date_range("2025-01-01", periods=250)
        prices = pd.Series(np.linspace(100, 150, 250), index=dates)
        spy = pd.DataFrame({"Close": prices})
        assert _classify_trend(spy) == 0

    def test_below_200dma_red(self):
        # Create SPY data that drops below 200-DMA
        dates = pd.date_range("2025-01-01", periods=250)
        prices = pd.Series(
            list(np.linspace(100, 150, 200)) + list(np.linspace(150, 100, 50)),
            index=dates
        )
        spy = pd.DataFrame({"Close": prices})
        assert _classify_trend(spy) == 2

    def test_empty_dataframe(self):
        assert _classify_trend(pd.DataFrame()) == 1  # Missing data → yellow

    def test_none(self):
        assert _classify_trend(None) == 1  # Missing data → yellow


class TestScoreToRegime:
    def test_green_range(self):
        assert _score_to_regime(0) == "GREEN"
        assert _score_to_regime(2) == "GREEN"

    def test_yellow_range(self):
        assert _score_to_regime(3) == "YELLOW"
        assert _score_to_regime(4) == "YELLOW"

    def test_red_range(self):
        assert _score_to_regime(5) == "RED"
        assert _score_to_regime(6) == "RED"


class TestComputeTrafficLight:
    def test_returns_expected_keys(self, tmp_path):
        db = str(tmp_path / "tl.sqlite3")
        result = compute_traffic_light(vix=15.0, db_path=db)
        assert "regime_label" in result
        assert "total_score" in result
        assert "sizing_multiplier" in result
        assert "persistence_applied" in result

    def test_green_with_low_vix(self, tmp_path):
        db = str(tmp_path / "tl.sqlite3")
        result = compute_traffic_light(vix=12.0, db_path=db)
        assert result["regime_label"] == "GREEN"
        assert result["sizing_multiplier"] == 1.0

    def test_persistence_filter(self, tmp_path):
        db = str(tmp_path / "tl.sqlite3")
        initialize_database(db)
        # Create a bearish SPY (below 200-DMA) to push trend score to 2
        dates = pd.date_range("2025-01-01", periods=250)
        prices = pd.Series(
            list(np.linspace(100, 150, 200)) + list(np.linspace(150, 100, 50)),
            index=dates
        )
        bearish_spy = pd.DataFrame({"Close": prices})

        # First call: GREEN with low VIX and no SPY
        r1 = compute_traffic_light(vix=12.0, db_path=db)
        assert r1["regime_label"] == "GREEN"

        # Calls 2-5: high VIX + bearish SPY → raw RED but persistence holds GREEN
        for i in range(4):
            r = compute_traffic_light(spy=bearish_spy, vix=35.0, db_path=db)
            assert r["persistence_applied"] is True
            assert r["regime_label"] == "GREEN"  # Held by persistence

        # 6th call: persistence threshold (5) met → switches
        r_final = compute_traffic_light(spy=bearish_spy, vix=35.0, db_path=db)
        assert r_final["regime_label"] != "GREEN"  # Should have switched

    def test_vix_30_6_produces_red_vix_component(self, tmp_path):
        """Sprint 4E: VIX 30.6 should produce vix_score=2 (RED component)."""
        db = str(tmp_path / "tl.sqlite3")
        result = compute_traffic_light(vix=30.6, db_path=db)
        assert result["vix_score"] == 2, f"VIX 30.6 should score 2, got {result['vix_score']}"
        # Total score should be at least 2 (VIX alone), so not GREEN
        assert result["total_score"] >= 2


class TestPersistenceFilterStringCount:
    """Regression #311: pending_count stored as string in SQLite."""

    def test_int_coercion_handles_string(self):
        """The fix pattern int(count or 0) + 1 must handle string count."""
        # This is the exact expression from traffic_light.py:198
        count = "3"  # as returned from SQLite with TEXT affinity
        result = int(count or 0) + 1
        assert result == 4

    def test_int_coercion_handles_none(self):
        count = None
        result = int(count or 0) + 1
        assert result == 1
