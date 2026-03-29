"""Tests for earnings date overlap and event-risk classification."""

from datetime import date, timedelta

from src.features.earnings import check_earnings_overlap


def test_earnings_5_days_out_is_elevated():
    future = (date.today() + timedelta(days=5)).isoformat()
    result = check_earnings_overlap(future)
    assert result["event_risk_level"] == "elevated"
    assert result["hold_overlaps_earnings"] is True
    assert result["days_to_earnings"] == 5


def test_earnings_2_days_out_is_imminent():
    future = (date.today() + timedelta(days=2)).isoformat()
    result = check_earnings_overlap(future)
    assert result["event_risk_level"] == "imminent"
    assert result["hold_overlaps_earnings"] is True
    assert result["days_to_earnings"] == 2


def test_earnings_20_days_out_is_none():
    future = (date.today() + timedelta(days=20)).isoformat()
    result = check_earnings_overlap(future)
    assert result["event_risk_level"] == "none"
    assert result["hold_overlaps_earnings"] is False
    assert result["days_to_earnings"] == 20


def test_no_earnings_date_is_none():
    result = check_earnings_overlap(None)
    assert result["event_risk_level"] == "none"
    assert result["hold_overlaps_earnings"] is False
    assert result["days_to_earnings"] is None
    assert result["earnings_date"] is None


def test_earnings_0_days_out_is_imminent():
    today = date.today().isoformat()
    result = check_earnings_overlap(today)
    assert result["event_risk_level"] == "imminent"
    assert result["hold_overlaps_earnings"] is True
    assert result["days_to_earnings"] == 0


def test_earnings_3_days_out_is_imminent():
    future = (date.today() + timedelta(days=3)).isoformat()
    result = check_earnings_overlap(future)
    assert result["event_risk_level"] == "imminent"
    assert result["hold_overlaps_earnings"] is True


def test_earnings_10_days_out_is_elevated():
    future = (date.today() + timedelta(days=10)).isoformat()
    result = check_earnings_overlap(future)
    assert result["event_risk_level"] == "elevated"
    assert result["hold_overlaps_earnings"] is True


def test_earnings_11_days_out_is_none():
    future = (date.today() + timedelta(days=11)).isoformat()
    result = check_earnings_overlap(future)
    assert result["event_risk_level"] == "none"
    assert result["hold_overlaps_earnings"] is False


def test_past_earnings_is_none():
    past = (date.today() - timedelta(days=5)).isoformat()
    result = check_earnings_overlap(past)
    assert result["event_risk_level"] == "none"
    assert result["hold_overlaps_earnings"] is False
