"""Sector filter unit tests for v0.26.2-scoped schema extension.

Verifies that `_query_event_rows` honors `universe.sector_filter` as a
hard filter — drops tickers whose GICS sector is not in the allowed list
BEFORE issuing the SQL IN(...) clause.

Uses a synthetic DB with two tickers of different sectors so the filter
effect is observable.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.platform.signal_eval import _query_event_rows
from src.platform.strategy_spec import _from_dict


def _make_spec_raw(sector_filter: list[str] | None) -> dict:
    universe: dict = {"tickers": ["AAPL", "PG"]}  # AAPL=Technology, PG=Consumer Staples
    if sector_filter is not None:
        universe["sector_filter"] = sector_filter
    return {
        "spec_version": 1,
        "strategy_id": "sector_filter_test",
        "display_name": "test",
        "derived_from": None,
        "universe": universe,
        "entry": {
            "kind": "event_driven",
            "event_table": "edgar_filings",
            "event_filter": {"form_type": ["10-K"]},
        },
        "exit": {"kind": "mechanical", "timeout_days": 21},
        "position_sizing": {"method": "fixed_pct_equity", "pct": 0.15},
        "attribution": {"benchmark": "SPY", "metrics": []},
    }


class _Cfg:
    def __init__(self, start, end):
        self.start_date = start
        self.end_date = end


def _seed_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE edgar_filings ("
        "  ticker TEXT, form_type TEXT, filing_date TEXT, "
        "  accession_number TEXT, full_text TEXT, sections_json TEXT"
        ")"
    )
    conn.execute(
        "INSERT INTO edgar_filings VALUES ('AAPL', '10-K', '2023-06-01', 'a1', '', '{}')"
    )
    conn.execute(
        "INSERT INTO edgar_filings VALUES ('PG', '10-K', '2023-06-01', 'p1', '', '{}')"
    )
    conn.commit()
    conn.close()


@pytest.fixture
def synthetic_db(monkeypatch):
    # ignore_cleanup_errors handles Windows SQLite-locking teardown flake.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        db_path = str(Path(td) / "test.db")
        _seed_db(db_path)
        monkeypatch.setenv("PLATFORM_EDGAR_DB", db_path)
        yield db_path


def test_sector_filter_keeps_only_defensive(synthetic_db):
    spec = _from_dict(_make_spec_raw(["Consumer Staples"]), source="test")
    cfg = _Cfg("2023-01-01", "2023-12-31")
    rows = _query_event_rows(spec, cfg)
    tickers = {r["ticker"] for r in rows}
    assert tickers == {"PG"}


def test_sector_filter_empty_universe_after_filter(synthetic_db):
    spec = _from_dict(_make_spec_raw(["Energy"]), source="test")
    cfg = _Cfg("2023-01-01", "2023-12-31")
    rows = _query_event_rows(spec, cfg)
    assert rows == []


def test_no_sector_filter_returns_all(synthetic_db):
    spec = _from_dict(_make_spec_raw(None), source="test")
    cfg = _Cfg("2023-01-01", "2023-12-31")
    rows = _query_event_rows(spec, cfg)
    tickers = {r["ticker"] for r in rows}
    assert tickers == {"AAPL", "PG"}


def test_sector_filter_multiple_sectors(synthetic_db):
    spec = _from_dict(
        _make_spec_raw(["Technology", "Consumer Staples"]), source="test",
    )
    cfg = _Cfg("2023-01-01", "2023-12-31")
    rows = _query_event_rows(spec, cfg)
    tickers = {r["ticker"] for r in rows}
    assert tickers == {"AAPL", "PG"}
