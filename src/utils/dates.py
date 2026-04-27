"""Canonical date-coercion helpers.

Called by: features.engine, features.earnings, features.event_proximity,
  scripts.fetch_earnings_calendar
Calls: nothing
Owns tables: none
Config keys: none
Tests: tests/test_b2_5_methodology.py
"""
from __future__ import annotations

from datetime import date, datetime


def coerce_as_of(
    value: date | datetime | str | None,
    default_today: bool = False,
) -> date | None:
    """Normalize a date-like value to a date.

    Args:
        value: A date, datetime, ISO-8601 string, or None.
        default_today: When True and value is None or unparseable, return
            date.today() instead of None. Event-proximity callers use this
            (live-scan default to today); engine/earnings callers use False
            to preserve explicit None semantics.

    Returns:
        A date, or None (when default_today=False and value is absent/invalid),
        or date.today() (when default_today=True and value is absent/invalid).
    """
    _fallback = date.today() if default_today else None

    if value is None:
        return _fallback
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except (ValueError, TypeError):
            return _fallback
    return _fallback
