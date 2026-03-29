"""Tests for market event proximity features."""

import csv
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from src.features.event_proximity import (
    get_upcoming_events,
    get_nearest_high_impact_event,
    should_reduce_position_size,
    get_event_proximity_features,
    _load_event_calendar,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the LRU cache between tests."""
    _load_event_calendar.cache_clear()
    yield
    _load_event_calendar.cache_clear()


def _create_temp_calendar(events: list[dict]) -> Path:
    """Create a temporary CSV calendar file."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    writer = csv.DictWriter(tmp, fieldnames=["date", "event_type", "description"])
    writer.writeheader()
    for event in events:
        writer.writerow(event)
    tmp.close()
    return Path(tmp.name)


class TestGetUpcomingEvents:
    """Tests for get_upcoming_events."""

    def test_returns_events_within_window(self):
        today = date(2026, 3, 25)
        path = _create_temp_calendar([
            {"date": "2026-03-26", "event_type": "FOMC", "description": "Rate decision"},
            {"date": "2026-03-28", "event_type": "GDP", "description": "Q4 GDP"},
            {"date": "2026-04-05", "event_type": "NFP", "description": "March jobs"},
        ])
        with patch("src.features.event_proximity.CALENDAR_PATH", path):
            events = get_upcoming_events(days=5, reference_date=today)
        assert len(events) == 2
        assert events[0]["event_type"] == "FOMC"
        assert events[0]["days_away"] == 1
        assert events[1]["event_type"] == "GDP"
        assert events[1]["days_away"] == 3

    def test_returns_empty_for_no_events(self):
        path = _create_temp_calendar([])
        with patch("src.features.event_proximity.CALENDAR_PATH", path):
            events = get_upcoming_events(days=5, reference_date=date(2026, 3, 25))
        assert events == []

    def test_excludes_past_events(self):
        today = date(2026, 3, 25)
        path = _create_temp_calendar([
            {"date": "2026-03-20", "event_type": "CPI", "description": "Past CPI"},
            {"date": "2026-03-26", "event_type": "FOMC", "description": "Future FOMC"},
        ])
        with patch("src.features.event_proximity.CALENDAR_PATH", path):
            events = get_upcoming_events(days=5, reference_date=today)
        assert len(events) == 1
        assert events[0]["event_type"] == "FOMC"


class TestNearestHighImpactEvent:
    """Tests for get_nearest_high_impact_event."""

    def test_finds_high_impact(self):
        today = date(2026, 3, 25)
        path = _create_temp_calendar([
            {"date": "2026-03-26", "event_type": "Earnings", "description": "Not high impact"},
            {"date": "2026-03-27", "event_type": "FOMC", "description": "Rate decision"},
        ])
        with patch("src.features.event_proximity.CALENDAR_PATH", path):
            event = get_nearest_high_impact_event(days=5, reference_date=today)
        assert event is not None
        assert event["event_type"] == "FOMC"

    def test_returns_none_if_no_high_impact(self):
        today = date(2026, 3, 25)
        path = _create_temp_calendar([
            {"date": "2026-03-26", "event_type": "Earnings", "description": "Low impact"},
        ])
        with patch("src.features.event_proximity.CALENDAR_PATH", path):
            event = get_nearest_high_impact_event(days=5, reference_date=today)
        assert event is None


class TestShouldReducePositionSize:
    """Tests for should_reduce_position_size."""

    def test_reduce_for_fomc_tomorrow(self):
        today = date(2026, 3, 25)
        path = _create_temp_calendar([
            {"date": "2026-03-26", "event_type": "FOMC", "description": "Rate decision"},
        ])
        with patch("src.features.event_proximity.CALENDAR_PATH", path):
            should_reduce, reason = should_reduce_position_size(reference_date=today)
        assert should_reduce is True
        assert "FOMC" in reason

    def test_no_reduce_when_clear(self):
        today = date(2026, 3, 25)
        path = _create_temp_calendar([
            {"date": "2026-04-05", "event_type": "NFP", "description": "Far away"},
        ])
        with patch("src.features.event_proximity.CALENDAR_PATH", path):
            should_reduce, reason = should_reduce_position_size(reference_date=today)
        assert should_reduce is False


class TestGetEventProximityFeatures:
    """Tests for get_event_proximity_features."""

    def test_returns_feature_dict(self):
        today = date(2026, 3, 25)
        path = _create_temp_calendar([
            {"date": "2026-03-27", "event_type": "CPI", "description": "March CPI"},
        ])
        with patch("src.features.event_proximity.CALENDAR_PATH", path):
            features = get_event_proximity_features(reference_date=today)
        assert features["event_proximity_type"] == "CPI"
        assert features["event_proximity_days"] == 2
        assert "events_within_3d" in features

    def test_returns_none_fields_when_no_events(self):
        path = _create_temp_calendar([])
        with patch("src.features.event_proximity.CALENDAR_PATH", path):
            features = get_event_proximity_features(reference_date=date(2026, 3, 25))
        assert features["event_proximity_type"] is None
        assert features["event_proximity_days"] is None
