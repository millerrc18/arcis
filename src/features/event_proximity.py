"""Market event proximity features (FOMC, CPI, NFP, GDP).

Loads the pre-generated market_event_calendar.csv and provides
proximity-based features for the feature engine and risk governor.
"""

import csv
import logging
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

CALENDAR_PATH = Path("data/reference/market_event_calendar.csv")

# Events that warrant position-size reduction when within 1 trading day
HIGH_IMPACT_EVENTS = {"FOMC", "CPI", "NFP", "GDP", "PCE"}


@lru_cache(maxsize=1)
def _load_event_calendar() -> list[dict]:
    """Load the market event calendar CSV into memory.

    Cached — only reads once per process lifetime (422 rows, trivial).
    """
    if not CALENDAR_PATH.exists():
        logger.warning("[EVENTS] Calendar file not found: %s", CALENDAR_PATH)
        return []

    events = []
    try:
        with open(CALENDAR_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    event_date = date.fromisoformat(row.get("date", "")[:10])
                    events.append({
                        "date": event_date,
                        "event_type": row.get("event_type", "").strip(),
                        "description": row.get("description", "").strip(),
                    })
                except (ValueError, TypeError):
                    continue
    except Exception as e:
        logger.warning("[EVENTS] Failed to load calendar: %s", e)
        return []

    logger.info("[EVENTS] Loaded %d events from calendar", len(events))
    return events


def get_upcoming_events(days: int = 3, reference_date: date | None = None) -> list[dict]:
    """Get market events within N calendar days.

    Returns list of {date, event_type, description, days_away},
    sorted by date ascending.
    """
    ref = reference_date or date.today()
    horizon = ref + timedelta(days=days)
    calendar = _load_event_calendar()

    upcoming = []
    for event in calendar:
        if ref <= event["date"] <= horizon:
            upcoming.append({
                **event,
                "days_away": (event["date"] - ref).days,
            })

    return sorted(upcoming, key=lambda e: e["date"])


def get_nearest_high_impact_event(days: int = 5,
                                   reference_date: date | None = None) -> dict | None:
    """Get the nearest high-impact event (FOMC, CPI, NFP, GDP, PCE).

    Returns the closest event dict or None if nothing within the window.
    """
    upcoming = get_upcoming_events(days, reference_date)
    for event in upcoming:
        if event["event_type"].upper() in HIGH_IMPACT_EVENTS:
            return event
    return None


def should_reduce_position_size(reference_date: date | None = None) -> tuple[bool, str]:
    """Check if position size should be reduced due to imminent macro event.

    Returns (should_reduce, reason).
    Risk governor calls this to apply a 25% reduction.
    """
    event = get_nearest_high_impact_event(days=1, reference_date=reference_date)
    if event:
        return True, (f"{event['event_type']} in {event['days_away']} day(s): "
                      f"{event['description']}")
    return False, ""


def get_event_proximity_features(reference_date: date | None = None) -> dict:
    """Get event proximity features for the feature engine.

    Returns dict with nearest event info for inclusion in feature dict.
    """
    nearest = get_nearest_high_impact_event(days=5, reference_date=reference_date)
    upcoming_3d = get_upcoming_events(days=3, reference_date=reference_date)

    if nearest:
        return {
            "event_proximity_type": nearest["event_type"],
            "event_proximity_days": nearest["days_away"],
            "event_proximity_desc": nearest["description"],
            "events_within_3d": len(upcoming_3d),
        }
    return {
        "event_proximity_type": None,
        "event_proximity_days": None,
        "event_proximity_desc": None,
        "events_within_3d": len(upcoming_3d),
    }
