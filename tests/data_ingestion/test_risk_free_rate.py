"""Tests for src/data_ingestion/risk_free_rate.py — FRED DTB3 ingestion.

Per CLAUDE.md: all FRED HTTP is mocked. No live network calls in pytest.

Coverage:
- DTB3 fetch returns a per-day decimal rate (annualized %% / 100 / 252).
- Cache hit on repeated call for the same date — only one HTTP call.
- Missing-API-key path raises CollectorConfigError.
- Missing date interpolates from the most-recent prior observation
  (DTB3 publishes on banking days; weekends/holidays roll forward).
- A FRED "." sentinel (missing observation) is skipped.
"""
from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch

import pytest


def _fake_dtb3_response(observations):
    """Build a fake `requests.get` JSON-bearing response for FRED."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"observations": observations}
    return resp


def test_get_rf_rate_returns_daily_decimal():
    """get_rf_rate(date) returns annualized %% / 100 / 252 (per-day decimal)."""
    from src.data_ingestion import risk_free_rate as rf

    rf._cache_clear()
    fake = _fake_dtb3_response([
        {"date": "2026-04-23", "value": "4.20"},
    ])
    with patch.object(rf, "_get_fred_api_key", return_value="TESTKEY"):
        with patch("src.data_ingestion.risk_free_rate.requests.get",
                   return_value=fake) as mock_get:
            rate = rf.get_rf_rate(dt.date(2026, 4, 23))

    # 4.20 %% annualized / 100 / 252 trading days ≈ 0.000167
    assert rate == pytest.approx(0.0420 / 252, rel=1e-9)
    assert mock_get.call_count == 1


def test_get_rf_rate_cache_hit_avoids_second_http():
    """Calling get_rf_rate twice for the same date hits the cache the second time."""
    from src.data_ingestion import risk_free_rate as rf

    rf._cache_clear()
    fake = _fake_dtb3_response([
        {"date": "2026-04-23", "value": "4.20"},
    ])
    with patch.object(rf, "_get_fred_api_key", return_value="TESTKEY"):
        with patch("src.data_ingestion.risk_free_rate.requests.get",
                   return_value=fake) as mock_get:
            r1 = rf.get_rf_rate(dt.date(2026, 4, 23))
            r2 = rf.get_rf_rate(dt.date(2026, 4, 23))

    assert r1 == r2
    assert mock_get.call_count == 1


def test_get_rf_rate_missing_api_key_raises():
    """If FRED_API_KEY is unresolvable, raise CollectorConfigError per project convention."""
    from src.data_collection.errors import CollectorConfigError
    from src.data_ingestion import risk_free_rate as rf

    rf._cache_clear()
    with patch.object(rf, "_get_fred_api_key", return_value=None):
        with pytest.raises(CollectorConfigError, match="FRED_API_KEY"):
            rf.get_rf_rate(dt.date(2026, 4, 23))


def test_get_rf_rate_interpolates_to_most_recent_prior_observation():
    """Asking for a weekend date returns the prior banking day's rate."""
    from src.data_ingestion import risk_free_rate as rf

    rf._cache_clear()
    # FRED returns Friday's observation when we ask through Saturday.
    fake = _fake_dtb3_response([
        {"date": "2026-04-24", "value": "4.20"},
    ])
    with patch.object(rf, "_get_fred_api_key", return_value="TESTKEY"):
        with patch("src.data_ingestion.risk_free_rate.requests.get",
                   return_value=fake):
            # Saturday — no FRED publication.
            rate = rf.get_rf_rate(dt.date(2026, 4, 25))

    assert rate == pytest.approx(0.0420 / 252, rel=1e-9)


def test_get_rf_rate_skips_dot_sentinel():
    """FRED uses '.' to mark a missing observation; we must skip it
    and fall through to the next available row."""
    from src.data_ingestion import risk_free_rate as rf

    rf._cache_clear()
    fake = _fake_dtb3_response([
        {"date": "2026-04-23", "value": "."},
        {"date": "2026-04-22", "value": "4.10"},
    ])
    with patch.object(rf, "_get_fred_api_key", return_value="TESTKEY"):
        with patch("src.data_ingestion.risk_free_rate.requests.get",
                   return_value=fake):
            rate = rf.get_rf_rate(dt.date(2026, 4, 23))

    assert rate == pytest.approx(0.0410 / 252, rel=1e-9)


def test_get_rf_rate_no_observations_raises_keyerror():
    """If FRED returns zero usable observations, raise KeyError —
    callers must decide how to fall back (no silent zero-rate)."""
    from src.data_ingestion import risk_free_rate as rf

    rf._cache_clear()
    fake = _fake_dtb3_response([])
    with patch.object(rf, "_get_fred_api_key", return_value="TESTKEY"):
        with patch("src.data_ingestion.risk_free_rate.requests.get",
                   return_value=fake):
            with pytest.raises(KeyError):
                rf.get_rf_rate(dt.date(2026, 4, 23))


def test_get_rf_rate_uses_dtb3_series():
    """Sanity: we hit the FRED DTB3 endpoint, not a different series."""
    from src.data_ingestion import risk_free_rate as rf

    rf._cache_clear()
    fake = _fake_dtb3_response([
        {"date": "2026-04-23", "value": "4.20"},
    ])
    with patch.object(rf, "_get_fred_api_key", return_value="TESTKEY"):
        with patch("src.data_ingestion.risk_free_rate.requests.get",
                   return_value=fake) as mock_get:
            rf.get_rf_rate(dt.date(2026, 4, 23))

    args, kwargs = mock_get.call_args
    params = kwargs.get("params") or (args[1] if len(args) > 1 else {})
    assert params.get("series_id") == "DTB3"
