"""Point-in-time S&P 100 universe resolver (R3 — no survivorship bias).

Called by: src.platform.rigor.walkforward_runner.
Calls: sqlite3, csv.
Owns tables: sp100_historical_constituents (populated by load_constituents).
Config keys: none.
Tests: tests/platform/rigor/test_walkforward_universe.py.

Source of truth: data/reference/sp100_historical.csv, curated from S&P Dow
Jones Indices press releases and Wikipedia index-change tables. See
docs/sprints/walkforward_v1_research_findings.md Item 8 for the choice
rationale and alternatives considered.

The resolver is offline and deterministic: given a date, it queries the
SQLite mirror of the CSV and returns the set of tickers whose
(added_date <= date < removed_date_or_infinity).
"""

from __future__ import annotations

import csv
import sqlite3
from src.utils.db import connect_db
from datetime import date
from pathlib import Path

_CSV_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data" / "reference" / "sp100_historical.csv"
)

# Expected header — deliberately rigid so a drifting CSV schema is loud.
_EXPECTED_HEADER = ("ticker", "added_date", "removed_date", "company_name", "reason")


class HistoricalConstituentsError(RuntimeError):
    """CSV missing, malformed, or inconsistent with the registered schema."""


def load_constituents_from_csv(
    csv_path: Path | str = _CSV_PATH,
) -> list[dict]:
    """Read the curated CSV into a list of row dicts. Raises on I/O or schema
    drift — never silently masks a missing file."""
    p = Path(csv_path)
    if not p.exists():
        raise HistoricalConstituentsError(
            f"historical S&P 100 CSV not found at {p}"
        )
    with open(p, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = tuple(next(reader, []))
        if header != _EXPECTED_HEADER:
            raise HistoricalConstituentsError(
                f"CSV header mismatch: got {header}, expected {_EXPECTED_HEADER}"
            )
        rows: list[dict] = []
        for raw in reader:
            if not raw or not raw[0].strip():
                continue
            record = dict(zip(header, raw))
            record["ticker"] = record["ticker"].strip()
            record["added_date"] = record["added_date"].strip()
            record["removed_date"] = (record.get("removed_date") or "").strip() or None
            record["company_name"] = (record.get("company_name") or "").strip() or None
            record["reason"] = (record.get("reason") or "").strip() or None
            rows.append(record)
    return rows


def populate_constituents_table(
    db_path: str, csv_path: Path | str = _CSV_PATH,
) -> int:
    """Load CSV into sp100_historical_constituents. Idempotent via
    INSERT OR REPLACE on composite (ticker, added_date). Returns row count."""
    rows = load_constituents_from_csv(csv_path)
    conn = connect_db(db_path)
    try:
        for r in rows:
            conn.execute(
                "INSERT OR REPLACE INTO sp100_historical_constituents "
                "(ticker, added_date, removed_date, company_name, reason) "
                "VALUES (?, ?, ?, ?, ?)",
                (r["ticker"], r["added_date"], r["removed_date"],
                 r["company_name"], r["reason"]),
            )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def resolve_universe_as_of(
    as_of_date: str, db_path: str,
) -> list[str]:
    """Return the list of S&P 100 tickers that were constituents on
    as_of_date (inclusive). Tickers appear alphabetically sorted.

    Semantics:
        ticker is a member iff:
          added_date <= as_of_date AND
          (removed_date IS NULL OR as_of_date < removed_date)

    If the table is empty (resolver not populated), returns []. Caller
    is responsible for populating first — we do NOT auto-populate to keep
    side effects explicit.
    """
    # Validate input shape loudly
    try:
        date.fromisoformat(as_of_date)
    except ValueError as e:
        raise ValueError(f"as_of_date not ISO yyyy-mm-dd: {as_of_date!r}") from e

    conn = connect_db(db_path)
    try:
        rows = conn.execute(
            "SELECT ticker FROM sp100_historical_constituents "
            "WHERE added_date <= ? "
            "AND (removed_date IS NULL OR removed_date > ?) "
            "ORDER BY ticker",
            (as_of_date, as_of_date),
        ).fetchall()
    finally:
        conn.close()
    # A single ticker may appear twice (e.g., removed then re-added) — dedupe
    return sorted({r[0] for r in rows})


def resolve_universe_size(as_of_date: str, db_path: str) -> int:
    """Count of resolved tickers on as_of_date."""
    return len(resolve_universe_as_of(as_of_date, db_path))
