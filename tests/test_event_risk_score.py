"""Tests for event risk scoring."""

import sqlite3
from datetime import date

from src.features.event_risk_score import (
    _sizing_multiplier_from_score,
    compute_event_risk_score,
    compute_market_event_risk,
)
from tests.conftest import init_test_db


def _make_db(db_path: str) -> None:
    init_test_db(db_path, ["earnings_calendar"])
    with sqlite3.connect(db_path) as conn:
        # economic_calendar is not in the schema registry; keep inline DDL
        conn.execute(
            "CREATE TABLE economic_calendar (event_type TEXT, event_date TEXT, description TEXT)"
        )
        conn.commit()


def _insert_earnings(db_path: str, ticker: str, earnings_date: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO earnings_calendar (ticker, earnings_date, collected_at) VALUES (?, ?, ?)",
            (ticker, earnings_date, "2026-01-01T00:00:00"),
        )
        conn.commit()


def _insert_macro(db_path: str, event_type: str, event_date: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO economic_calendar (event_type, event_date, description) VALUES (?, ?, ?)",
            (event_type, event_date, event_type),
        )
        conn.commit()


def test_market_event_risk_scores_macro_events(tmp_path):
    db_path = str(tmp_path / "event-risk.db")
    _make_db(db_path)
    _insert_macro(db_path, "FOMC", "2026-03-11")
    _insert_macro(db_path, "NFP", "2026-03-10")
    _insert_macro(db_path, "CPI", "2026-03-11")

    risk = compute_market_event_risk(
        db_path=db_path,
        reference_date=date(2026, 3, 10),
        settings={"event_risk": {"sizing_floor": 0.25, "block_threshold": 8}},
    )

    assert risk["total_score"] == 4
    assert risk["components"]["fomc"] == 2
    assert risk["components"]["nfp"] == 1
    assert risk["components"]["cpi"] == 1
    assert risk["sizing_multiplier"] == 1.0


def test_market_event_risk_scores_calendar_structure(tmp_path):
    db_path = str(tmp_path / "calendar-risk.db")
    _make_db(db_path)

    risk = compute_market_event_risk(
        db_path=db_path,
        reference_date=date(2026, 3, 20),
        settings={"event_risk": {"sizing_floor": 0.25, "block_threshold": 8}},
    )
    assert risk["components"]["opex"] == 1

    month_end = compute_market_event_risk(
        db_path=db_path,
        reference_date=date(2026, 3, 31),
        settings={"event_risk": {"sizing_floor": 0.25, "block_threshold": 8}},
    )
    assert month_end["components"]["month_end"] == 1


def test_compute_event_risk_score_adds_earnings_and_blocks(tmp_path):
    db_path = str(tmp_path / "ticker-risk.db")
    _make_db(db_path)
    _insert_earnings(db_path, "AAPL", "2026-03-11")

    market_risk = {
        "total_score": 4,
        "components": {"fomc": 2, "nfp": 1, "cpi": 1, "opex": 0, "month_end": 0},
        "sizing_multiplier": 1.0,
    }

    risk = compute_event_risk_score(
        "AAPL",
        db_path=db_path,
        reference_date=date(2026, 3, 10),
        market_risk=market_risk,
        settings={"event_risk": {"sizing_floor": 0.25, "block_threshold": 8}},
    )

    # SD#33 / Sprint H1: earnings within 10 calendar days force a hard block
    # by setting earnings_proximity to block_threshold. Total = market(4)+earnings(8).
    assert risk["total_score"] == 12
    assert risk["components"]["earnings_proximity"] == 8
    assert risk["components"]["earnings_days"] == 1
    assert risk["components"]["earnings_forces_block"] is True
    assert risk["sizing_multiplier"] == 0.0


def test_sizing_multiplier_boundaries():
    assert _sizing_multiplier_from_score(0, floor=0.25, block_threshold=8) == 1.0
    assert _sizing_multiplier_from_score(3, floor=0.25, block_threshold=8) == 1.0
    assert _sizing_multiplier_from_score(4, floor=0.25, block_threshold=8) == 1.0
    assert _sizing_multiplier_from_score(5, floor=0.25, block_threshold=8) == 0.75
    assert _sizing_multiplier_from_score(6, floor=0.25, block_threshold=8) == 0.5
    assert _sizing_multiplier_from_score(7, floor=0.25, block_threshold=8) == 0.25
    assert _sizing_multiplier_from_score(8, floor=0.25, block_threshold=8) == 0.0
