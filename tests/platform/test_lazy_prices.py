"""Tests for Lazy Prices feature providers."""
import sqlite3

import pytest

from src.platform.features.cosine_similarity import cosine_similarity_yoy
from src.platform.features.event_providers import find_filing_events


def test_lazy_prices_cosine_computation_matches_manual(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE edgar_filings (
            ticker TEXT, cik TEXT, form_type TEXT, filing_date TEXT,
            accession_number TEXT PRIMARY KEY, sections_json TEXT
        );
        INSERT INTO edgar_filings VALUES
            ('AAPL', '320193', '10-K', '2022-10-28', 'ACCESS_A',
             '{"item_1a": "risk factor text alpha beta gamma delta"}'),
            ('AAPL', '320193', '10-K', '2023-11-03', 'ACCESS_B',
             '{"item_1a": "risk factor text alpha beta gamma delta epsilon"}');
    """)
    conn.commit()
    conn.close()
    cos = cosine_similarity_yoy(
        "AAPL", "ACCESS_B", "item_1a", db_path=str(db),
    )
    assert cos is not None
    # Texts are very similar (4 of 5 tokens shared), so cosine > 0.5 and < 1.0
    assert 0.5 < cos < 1.0


def test_lazy_prices_cosine_returns_none_on_missing_prior_year(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE edgar_filings (
            ticker TEXT, cik TEXT, form_type TEXT, filing_date TEXT,
            accession_number TEXT PRIMARY KEY, sections_json TEXT
        );
        INSERT INTO edgar_filings VALUES
            ('AAPL', '320193', '10-K', '2023-11-03', 'ACCESS_B',
             '{"item_1a": "risk factor text v2"}');
    """)
    conn.commit()
    conn.close()
    cos = cosine_similarity_yoy(
        "AAPL", "ACCESS_B", "item_1a", db_path=str(db),
    )
    assert cos is None  # no prior year


def test_find_filing_events_filters_by_form_and_ticker(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE edgar_filings (
            ticker TEXT, cik TEXT, form_type TEXT, filing_date TEXT,
            accession_number TEXT PRIMARY KEY, sections_json TEXT
        );
        INSERT INTO edgar_filings VALUES
            ('AAPL', '320193', '10-K', '2023-11-03', 'A1', '{}'),
            ('AAPL', '320193', '10-Q', '2023-08-04', 'A2', '{}'),
            ('MSFT', '789019', '10-K', '2023-07-27', 'A3', '{}'),
            ('ZZZ', '999999', '10-K', '2023-05-10', 'A4', '{}');
    """)
    conn.commit()
    conn.close()
    events = find_filing_events(
        tickers=["AAPL", "MSFT"],
        start_date="2023-01-01",
        end_date="2023-12-31",
        form_types=["10-K"],
        db_path=str(db),
    )
    accessions = [e["accession_number"] for e in events]
    assert "A1" in accessions
    assert "A3" in accessions
    assert "A2" not in accessions  # filtered by form_type
    assert "A4" not in accessions  # filtered by ticker
