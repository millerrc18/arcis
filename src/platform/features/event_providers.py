"""DB-backed event lookup for event_driven strategies.

Called by: src.platform.backtest_engine (event_driven dispatch path),
           src.platform.shadow_harness (Sprint 4).
Calls: sqlite3, src.config.
Owns tables: none (read-only from edgar_filings, analyst_estimates).
Config keys: PLATFORM_EDGAR_DB (optional env override for edgar_filings DB).
Tests: tests/platform/test_lazy_prices.py.
"""
from __future__ import annotations

import os
import sqlite3

from src.config import DB_PATH


def _db_path() -> str:
    return os.environ.get("PLATFORM_EDGAR_DB", DB_PATH)


def find_filing_events(
    tickers: list[str],
    start_date: str,
    end_date: str,
    form_types: list[str] | None = None,
    db_path: str | None = None,
) -> list[dict]:
    """Return edgar_filings rows matching the filter. Used by backtest engine."""
    db = db_path or _db_path()
    form_types = form_types or ["10-K", "10-Q"]
    if not tickers:
        return []
    placeholders_t = ",".join("?" * len(tickers))
    placeholders_f = ",".join("?" * len(form_types))
    q = (
        f"SELECT ticker, cik, form_type, filing_date, accession_number, "
        f"       sections_json "
        f"FROM edgar_filings "
        f"WHERE ticker IN ({placeholders_t}) "
        f"  AND form_type IN ({placeholders_f}) "
        f"  AND filing_date BETWEEN ? AND ? "
        f"ORDER BY filing_date"
    )
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            q, (*tickers, *form_types, start_date, end_date),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
