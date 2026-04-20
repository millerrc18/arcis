"""Tests for find_candidates_for_date — Sprint 4 cont. Step A.

Non-negotiable gate #5: returns a non-empty list when criteria met.
"""
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from src.platform.signal_eval import find_candidates_for_date
from src.platform.strategy_spec import load_spec, StrategySpec


def _lazy_prices_spec() -> StrategySpec:
    """Load the real lazy_prices_v1 YAML spec so tests exercise the
    actual signal + combinator wiring."""
    return load_spec("lazy_prices_v1")


def _seeded_edgar_db(tmp_path, fixture_date: str = "2023-11-03") -> str:
    """Seed a temp SQLite DB with edgar_filings that include a
    low-cosine-similarity item_1a filing — should trigger signal."""
    db = str(tmp_path / "test.db")
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE edgar_filings (
            ticker TEXT, cik TEXT, form_type TEXT, filing_date TEXT,
            accession_number TEXT PRIMARY KEY, filing_url TEXT,
            full_text TEXT, sections_json TEXT
        )
    """)
    # Two AAPL 10-Ks: prior year with placeholder text, current year
    # with substantially different item_1a → cosine well below 0.75.
    conn.execute("""
        INSERT INTO edgar_filings VALUES
            ('AAPL', '320193', '10-K', '2022-10-27', 'ACC_PRIOR',
             'https://...', 'prior year risk factors foo',
             ?)
    """, (json.dumps({"item_1a_cosine_yoy": None, "item_1a": "alpha beta gamma delta"}),))
    conn.execute("""
        INSERT INTO edgar_filings VALUES
            ('AAPL', '320193', '10-K', ?, 'ACC_CURRENT',
             'https://...', 'completely different risk factors xyz',
             ?)
    """, (fixture_date, json.dumps({
        "item_1a_cosine_yoy": 0.40,   # well below 0.75 threshold
        "item_7_cosine_yoy": 0.92,    # above threshold — with combinator='any', item_1a fires
        "item_1a": "xyz gamma epsilon phi omega theta",
    })))
    conn.commit()
    conn.close()
    return db


def test_find_candidates_returns_nonempty_on_signal_match(tmp_path):
    """NON-NEGOTIABLE GATE #5: a seeded low-cosine filing must trigger
    a candidate."""
    db = _seeded_edgar_db(tmp_path)
    spec = _lazy_prices_spec()
    # Override universe to AAPL only so we don't need real sp100 data
    spec.universe = {"tickers": ["AAPL"]}
    as_of = datetime(2023, 11, 5)  # 2 trading days after filing
    candidates = find_candidates_for_date(
        spec, db_path=db, as_of=as_of,
    )
    assert isinstance(candidates, list)
    assert len(candidates) >= 1, (
        f"expected ≥1 candidate with cosine 0.40 < 0.75 threshold "
        f"and combinator='any'; got {len(candidates)}"
    )
    c = candidates[0]
    assert c["ticker"] == "AAPL"
    assert c["as_of"]
    # metadata should include the filing accession so we can dedup later
    assert c.get("metadata", {}).get("filing_accession") == "ACC_CURRENT"


def test_find_candidates_empty_when_no_match(tmp_path):
    """No filings within the as_of window → empty list, no error."""
    db = _seeded_edgar_db(tmp_path, fixture_date="2020-01-01")  # way in past
    spec = _lazy_prices_spec()
    spec.universe = {"tickers": ["AAPL"]}
    as_of = datetime(2024, 1, 1)  # 4 years after the filing
    candidates = find_candidates_for_date(spec, db_path=db, as_of=as_of)
    # filing_date_within_days: 5 → 4-year-old filing is outside window
    assert candidates == []


def test_find_candidates_dedupes_already_open_positions(tmp_path):
    """If a candidate already has an open shadow_trades row for the
    strategy's desk, don't re-emit. Prevents double-entry on consecutive ticks."""
    db = _seeded_edgar_db(tmp_path)
    # Seed an open shadow_trade for AAPL on the research desk
    from src.schema.sqlite import create_all_tables
    create_all_tables(db)
    conn = sqlite3.connect(db)
    conn.execute("""
        INSERT INTO shadow_trades
            (trade_id, ticker, planned_shares, entry_price, desk,
             source, status, direction, created_at, updated_at)
        VALUES ('t1', 'AAPL', 10, 100.0, 'research_lazy_prices_v1',
                'paper', 'open', 'long',
                '2023-11-04', '2023-11-04')
    """)
    conn.commit()
    conn.close()

    spec = _lazy_prices_spec()
    spec.universe = {"tickers": ["AAPL"]}
    as_of = datetime(2023, 11, 5)
    candidates = find_candidates_for_date(
        spec, db_path=db, as_of=as_of,
    )
    # AAPL already has open position → no new candidate for AAPL
    aapl_candidates = [c for c in candidates if c["ticker"] == "AAPL"]
    assert len(aapl_candidates) == 0, (
        "already-open AAPL position should dedupe; got "
        f"{len(aapl_candidates)} candidates"
    )


def _scheduled_spec(strategy_id: str = "sched_test") -> StrategySpec:
    return StrategySpec(
        strategy_id=strategy_id,
        display_name="S",
        universe={"tickers": ["AAPL"]},
        entry={"kind": "scheduled", "day_of_week": "Monday", "time": "close"},
        exit={"kind": "mechanical", "timeout_days": 5,
              "stop": {"method": "pct", "value": 0.02},
              "target": {"method": "pct", "value": 0.03}},
        position_sizing={"method": "fixed_pct_equity", "pct": 0.15,
                         "max_concurrent": 1},
        attribution={"benchmark": "SPY_matched_window", "metrics": ["sharpe"]},
        raw={}, source="test",
    )


def test_find_candidates_scheduled_kind_fires_on_trigger_match(tmp_path):
    """#494: scheduled specs now resolve candidates on trigger-match days.
    A Monday spec on 2023-11-06 (Monday) must emit one AAPL candidate."""
    db = _seeded_edgar_db(tmp_path)
    spec = _scheduled_spec()
    as_of = datetime(2023, 11, 6)  # Monday
    candidates = find_candidates_for_date(spec, db_path=db, as_of=as_of)
    assert len(candidates) == 1
    assert candidates[0]["ticker"] == "AAPL"
    assert candidates[0]["metadata"].get("trigger") == "scheduled"


def test_find_candidates_scheduled_kind_empty_on_trigger_miss(tmp_path):
    """Monday-trigger spec on a Tuesday returns []."""
    db = _seeded_edgar_db(tmp_path)
    spec = _scheduled_spec()
    as_of = datetime(2023, 11, 7)  # Tuesday
    assert find_candidates_for_date(spec, db_path=db, as_of=as_of) == []
