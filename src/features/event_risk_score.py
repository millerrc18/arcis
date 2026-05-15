"""Event calendar risk scoring -- continuous 0-10 additive system.

Called by: services.scan_service
Calls: none
Owns tables: none
Config keys: block_threshold, sizing_floor
Tests: tests/test_event_risk_score.py
"""

import calendar
import csv
import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.utils.db import DBError

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
DEFAULT_DB_PATH = DB_PATH
EVENT_CALENDAR_FALLBACK = Path("data/reference/market_event_calendar.csv")
MACRO_EVENT_TYPES = {"FOMC", "NFP", "CPI"}


def _coerce_date(value: str | date | datetime | None) -> date | None:
    """Convert sqlite/calendar date values to a Python date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:19]).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def _get_table_columns(conn, table_name: str) -> set[str]:
    """Return lowercase column names for a table, or an empty set.

    Sprint 5 §J5/§J6 Phase 2 T2.3 — uses engine_aware_column_info so the
    helper works on both SQLite (PRAGMA-backed) and PostgreSQL
    (information_schema-backed) connections.
    """
    from src.utils.db import engine_aware_column_info

    try:
        rows = engine_aware_column_info(conn, table_name)
    except Exception:
        return set()
    return {str(row["name"]).lower() for row in rows}


def _load_fallback_events(reference_date: date) -> list[dict]:
    """Load macro events from the CSV scaffold when economic_calendar is unavailable."""
    if not EVENT_CALENDAR_FALLBACK.exists():
        return []

    events: list[dict] = []
    try:
        with EVENT_CALENDAR_FALLBACK.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                event_type = (row.get("event_type") or "").strip().upper()
                if event_type not in MACRO_EVENT_TYPES:
                    continue
                event_date = _coerce_date(row.get("date"))
                if event_date is None or event_date < reference_date:
                    continue
                events.append(
                    {
                        "event_type": event_type,
                        "event_date": event_date,
                        "description": (row.get("description") or "").strip(),
                    }
                )
    except Exception as exc:
        logger.warning("[EVENT RISK] Fallback calendar load failed: %s", exc)
        return []

    return events


def _fetch_macro_events(conn: sqlite3.Connection, reference_date: date) -> list[dict]:
    """Fetch upcoming macro events from economic_calendar or the CSV fallback."""
    cols = _get_table_columns(conn, "economic_calendar")
    if not cols:
        return _load_fallback_events(reference_date)

    date_col = "event_date" if "event_date" in cols else "date" if "date" in cols else None
    type_col = "event_type"
    if date_col is None or type_col not in cols:
        return _load_fallback_events(reference_date)

    desc_expr = "description" if "description" in cols else "''"
    placeholders = ", ".join("?" for _ in MACRO_EVENT_TYPES)
    query = (
        f"SELECT {date_col} AS event_date, {type_col} AS event_type, {desc_expr} AS description "
        f"FROM economic_calendar "
        f"WHERE UPPER({type_col}) IN ({placeholders}) AND {date_col} >= ? "
        f"ORDER BY {date_col} ASC"
    )

    try:
        rows = conn.execute(query, (*sorted(MACRO_EVENT_TYPES), reference_date.isoformat())).fetchall()
    except DBError as exc:
        logger.warning("[EVENT RISK] economic_calendar query failed: %s", exc)
        return _load_fallback_events(reference_date)

    events = []
    for row in rows:
        event_date = _coerce_date(row[0])
        event_type = (row[1] or "").upper()
        if event_date is None or event_type not in MACRO_EVENT_TYPES:
            continue
        events.append(
            {
                "event_type": event_type,
                "event_date": event_date,
                "description": row[2] or "",
            }
        )
    return events or _load_fallback_events(reference_date)


def _fetch_next_earnings_date(
    conn: sqlite3.Connection,
    ticker: str,
    reference_date: date,
) -> date | None:
    """Fetch the next known earnings date for a ticker."""
    cols = _get_table_columns(conn, "earnings_calendar")
    if "earnings_date" not in cols:
        return None

    try:
        row = conn.execute(
            "SELECT MIN(earnings_date) FROM earnings_calendar "
            "WHERE ticker = ? AND earnings_date >= ?",
            (ticker, reference_date.isoformat()),
        ).fetchone()
    except DBError as exc:
        logger.warning("[EVENT RISK] earnings_calendar query failed for %s: %s", ticker, exc)
        return None

    if not row:
        return None
    return _coerce_date(row[0])


def _is_third_friday(reference_date: date) -> bool:
    """Return True when the date is the month's standard monthly OpEx."""
    if reference_date.weekday() != 4:
        return False

    fridays = [
        day
        for week in calendar.monthcalendar(reference_date.year, reference_date.month)
        if (day := week[calendar.FRIDAY]) != 0
    ]
    return len(fridays) >= 3 and reference_date.day == fridays[2]


def _last_two_weekdays(reference_date: date) -> set[date]:
    """Approximate the last two trading days of the month using weekdays."""
    last_day = calendar.monthrange(reference_date.year, reference_date.month)[1]
    current = date(reference_date.year, reference_date.month, last_day)
    days: list[date] = []
    while len(days) < 2:
        if current.weekday() < 5:
            days.append(current)
        current -= timedelta(days=1)
    return set(days)


def _sizing_multiplier_from_score(total_score: int, floor: float, block_threshold: int) -> float:
    """Map a 0-10 score to the configured sizing multiplier."""
    if total_score >= block_threshold:
        return 0.0
    if total_score <= 3:
        return 1.0
    if total_score >= 7:
        return round(floor, 3)

    # Linear interpolation: 4 -> 1.0, 7 -> floor.
    progress = (total_score - 4) / 3
    multiplier = 1.0 - progress * (1.0 - floor)
    return round(max(floor, multiplier), 3)


def compute_market_event_risk(
    db_path: str = DEFAULT_DB_PATH,
    reference_date: date | None = None,
    settings: dict | None = None,
) -> dict:
    """Compute the market-wide event risk components once per scan."""
    ref = reference_date or datetime.now(ET).date()
    cfg = (settings or {}).get("event_risk", {})
    floor = float(cfg.get("sizing_floor", 0.25))
    block_threshold = int(cfg.get("block_threshold", 8))

    components = {
        "fomc": 0,
        "nfp": 0,
        "cpi": 0,
        "opex": 0,
        "month_end": 0,
    }

    try:
        # #590 — connect_db applies busy_timeout=30s
        from src.utils.db import connect_db
        with connect_db(db_path) as conn:
            for event in _fetch_macro_events(conn, ref):
                days_away = (event["event_date"] - ref).days
                if event["event_type"] == "FOMC" and days_away <= 2:
                    components["fomc"] = max(components["fomc"], 2)
                elif event["event_type"] == "NFP" and days_away <= 1:
                    components["nfp"] = max(components["nfp"], 1)
                elif event["event_type"] == "CPI" and days_away <= 1:
                    components["cpi"] = max(components["cpi"], 1)
    except Exception as exc:
        logger.warning("[EVENT RISK] Macro event scoring failed: %s", exc)

    if _is_third_friday(ref):
        components["opex"] = 1

    if ref in _last_two_weekdays(ref):
        components["month_end"] = 1

    total_score = int(sum(components.values()))
    return {
        "total_score": total_score,
        "components": components,
        "sizing_multiplier": _sizing_multiplier_from_score(total_score, floor, block_threshold),
    }


def compute_event_risk_score(
    ticker: str,
    db_path: str = DEFAULT_DB_PATH,
    reference_date: date | None = None,
    market_risk: dict | None = None,
    settings: dict | None = None,
) -> dict:
    """Compute the combined market-wide plus ticker-specific event risk score."""
    ref = reference_date or datetime.now(ET).date()
    cfg = (settings or {}).get("event_risk", {})
    floor = float(cfg.get("sizing_floor", 0.25))
    block_threshold = int(cfg.get("block_threshold", 8))

    base = market_risk or compute_market_event_risk(
        db_path=db_path,
        reference_date=ref,
        settings=settings,
    )
    components = dict(base.get("components", {}))

    earnings_score = 0
    next_earnings = None
    try:
        # #590 — connect_db applies busy_timeout=30s
        from src.utils.db import connect_db
        with connect_db(db_path) as conn:
            next_earnings = _fetch_next_earnings_date(conn, ticker, ref)
    except Exception as exc:
        logger.warning("[EVENT RISK] Earnings lookup failed for %s: %s", ticker, exc)

    earnings_forces_block = False
    if next_earnings is not None:
        days_until = (next_earnings - ref).days
        components["earnings_days"] = days_until
        components["earnings_date"] = next_earnings.isoformat()

        # SD#33 / Sprint H1: earnings within ~7 trading days = hard block.
        # 10 calendar days bounds 7 trading days (handles two weekends).
        # Conservative — gap risk cannot be managed by stops or vol targeting,
        # only by not being in the position when earnings prints.
        if days_until <= 10:
            earnings_forces_block = True
            earnings_score = block_threshold

        components["earnings_proximity"] = earnings_score
        components["earnings_forces_block"] = earnings_forces_block
    else:
        components["earnings_proximity"] = 0
        components["earnings_forces_block"] = False

    total_score = int(base.get("total_score", 0) + earnings_score)
    if earnings_forces_block:
        # Floor at block_threshold so the multiplier-derivation always
        # short-circuits to 0.0 regardless of market-wide score.
        total_score = max(total_score, block_threshold)
    return {
        "total_score": total_score,
        "components": components,
        "sizing_multiplier": _sizing_multiplier_from_score(total_score, floor, block_threshold),
    }


def attach_event_risk_scores(
    features: dict[str, dict],
    settings: dict | None = None,
    db_path: str = DEFAULT_DB_PATH,
    reference_date: date | None = None,
) -> dict:
    """Attach event-risk scores and multipliers to every feature dict."""
    market_risk = compute_market_event_risk(
        db_path=db_path,
        reference_date=reference_date,
        settings=settings,
    )

    for ticker, feat in features.items():
        ticker_risk = compute_event_risk_score(
            ticker=ticker,
            db_path=db_path,
            reference_date=reference_date,
            market_risk=market_risk,
            settings=settings,
        )
        feat["market_event_risk"] = market_risk
        feat["event_risk_score"] = ticker_risk["total_score"]
        feat["event_risk_components"] = ticker_risk["components"]
        feat["event_risk_multiplier"] = ticker_risk["sizing_multiplier"]

    return market_risk
