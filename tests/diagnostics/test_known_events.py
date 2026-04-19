"""Regression tests for src/diagnostics/known_events.py.

Guards:
- Schema invariants (ISO dates, category closure, metadata parity).
- 2019-2024 coverage floor — required for v0.26.2's tariff-exclusion rule
  to have real events against walk-forward OOS windows.
- is_known_event() helper behavior.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.diagnostics.known_events import (
    EVENT_CATEGORIES,
    EVENT_METADATA,
    KNOWN_EVENTS,
    is_known_event,
)

WINDOW_START = date(2019, 9, 30)
WINDOW_END = date(2024, 9, 30)
COVERAGE_FLOOR = 8  # minimum events inside the walk-forward OOS window


def test_known_events_schema_invariants() -> None:
    """Every key parses as ISO-8601 date; every label is in EVENT_CATEGORIES."""
    for date_str, label in KNOWN_EVENTS.items():
        # parse — raises ValueError on malformed dates
        parsed = date.fromisoformat(date_str)
        assert parsed.isoformat() == date_str, f"round-trip failed for {date_str}"
        assert label in EVENT_CATEGORIES, (
            f"{date_str} has label {label!r} with no EVENT_CATEGORIES entry"
        )


def test_event_categories_closed_set() -> None:
    """Every label emitted by KNOWN_EVENTS values exists as an EVENT_CATEGORIES key.

    Also: no orphan categories. Every EVENT_CATEGORIES key must be used by at
    least one KNOWN_EVENTS value (prevents dead labels from accumulating).
    """
    used_labels = set(KNOWN_EVENTS.values())
    declared_labels = set(EVENT_CATEGORIES.keys())

    missing = used_labels - declared_labels
    assert not missing, f"labels used in KNOWN_EVENTS but missing in EVENT_CATEGORIES: {missing}"

    orphans = declared_labels - used_labels
    assert not orphans, f"labels declared in EVENT_CATEGORIES but never used: {orphans}"


def test_coverage_count_floor_2019_2024() -> None:
    """At least COVERAGE_FLOOR events fall inside the 2019-09-30 → 2024-09-30 window.

    Required so the tariff-exclusion rule in v0.26.2 has meaningful coverage
    against walk-forward OOS windows (R1: 2019-01-01 → 2024-09-30).
    """
    in_window = [
        d for d in KNOWN_EVENTS
        if WINDOW_START <= date.fromisoformat(d) <= WINDOW_END
    ]
    assert len(in_window) >= COVERAGE_FLOOR, (
        f"only {len(in_window)} events in walk-forward OOS window; "
        f"floor is {COVERAGE_FLOOR}. Events present: {sorted(in_window)}"
    )


def test_metadata_parity_and_required_fields() -> None:
    """EVENT_METADATA has an entry for every KNOWN_EVENTS key with required fields.

    Enforced invariant: `set(KNOWN_EVENTS) == set(EVENT_METADATA)`.
    Required keys per entry: description (non-empty), affected_sectors (list,
    possibly empty), primary_source (non-empty), market_impact_note (non-empty).
    """
    assert set(KNOWN_EVENTS) == set(EVENT_METADATA), (
        f"metadata mismatch: "
        f"in KNOWN_EVENTS only = {set(KNOWN_EVENTS) - set(EVENT_METADATA)}; "
        f"in EVENT_METADATA only = {set(EVENT_METADATA) - set(KNOWN_EVENTS)}"
    )
    for date_str, meta in EVENT_METADATA.items():
        assert meta["description"], f"{date_str}: empty description"
        assert isinstance(meta["affected_sectors"], list), (
            f"{date_str}: affected_sectors must be list, got {type(meta['affected_sectors'])}"
        )
        assert meta["primary_source"], f"{date_str}: empty primary_source"
        assert meta["market_impact_note"], f"{date_str}: empty market_impact_note"


def test_2019_2024_events_have_real_primary_sources() -> None:
    """Events in the 2019-09-30 → 2024-09-30 window must cite external primary sources.

    'internal' is reserved for forward-planning 2026 entries; historical
    events must link to an official government or industry source.
    """
    for date_str in KNOWN_EVENTS:
        parsed = date.fromisoformat(date_str)
        if WINDOW_START <= parsed <= WINDOW_END:
            source = EVENT_METADATA[date_str]["primary_source"]
            assert source != "internal", (
                f"{date_str}: primary_source='internal' is not acceptable for historical events"
            )
            assert source.startswith(("http://", "https://")) or "congress.gov" in source, (
                f"{date_str}: primary_source {source!r} is not a URL"
            )


def test_is_known_event_basic_lookup() -> None:
    """Representative in-window dates return True; nearby non-event dates return False."""
    # Representative hits from the 2019-2024 window
    assert is_known_event("2022-10-07") is True  # BIS chip controls
    assert is_known_event("2022-02-24") is True  # Russia invasion
    assert is_known_event("2024-05-14") is True  # Biden Section 301

    # Nearby non-event dates
    assert is_known_event("2022-10-08") is False  # day after
    assert is_known_event("2022-10-06") is False  # day before
    assert is_known_event("2022-03-01") is False  # between sanctions rounds
    assert is_known_event("2020-05-29") is False  # explicitly excluded candidate


def test_is_known_event_category_filter() -> None:
    """Category filter narrows matches; mismatched category returns False."""
    # Trade Policy dates match when category="Trade Policy"
    assert is_known_event("2022-10-07", category="Trade Policy") is True
    assert is_known_event("2019-10-11", category="Trade Policy") is True

    # But NOT when a different category is requested
    assert is_known_event("2022-10-07", category="Monetary Policy") is False
    assert is_known_event("2022-10-07", category="Inflation Data") is False

    # FOMC_DECISION in 2026 is Monetary Policy, not Trade Policy
    assert is_known_event("2026-03-18", category="Monetary Policy") is True
    assert is_known_event("2026-03-18", category="Trade Policy") is False


def test_is_known_event_missing_date() -> None:
    """Dates not in KNOWN_EVENTS return False regardless of category filter."""
    assert is_known_event("1999-01-01") is False
    assert is_known_event("1999-01-01", category="Trade Policy") is False
    assert is_known_event("", category=None) is False


@pytest.mark.parametrize(
    "label, expected_category",
    [
        ("SANCTIONS_INITIAL", "Trade Policy"),
        ("SANCTIONS_ESCALATION", "Trade Policy"),
        ("EXPORT_CONTROLS", "Trade Policy"),
        ("INDUSTRIAL_POLICY", "Trade Policy"),
        ("TRADE_DISRUPTION", "Trade Policy"),
    ],
)
def test_new_labels_route_to_trade_policy(label: str, expected_category: str) -> None:
    """All v0.25.1 additions roll up to 'Trade Policy' for consumer uniformity."""
    assert EVENT_CATEGORIES[label] == expected_category
