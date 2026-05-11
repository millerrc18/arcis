"""Tests for fed_collector engine-aware UPSERT migration.

Sprint 5 §J5/§J6 Phase 1 T1.3: replaces the INSERT OR IGNORE site at
src/data_collection/fed_collector.py:128 with engine_aware_upsert(conn,
'fed_communications', row_dict, action='ignore'). The parametrized test
below exercises both SQLite and PostgreSQL engines via the shared
`parametrized_conn` fixture (tests/conftest.py T0.9). The PG variant is
SKIPPED when TEST_DATABASE_URL is unset.

The fed_communications table uses sync_conflict_col=(comm_type, date, title)
so the UPSERT dedup target spans those three columns, not the integer PK.
"""

import pytest


def _row_kwargs(**overrides):
    """Return a fed_communications kwargs dict matching `_store_fed_item`'s signature.

    Overrides win over defaults so individual tests can vary the dedup
    target (comm_type, filing_date, title) or any other column.
    """
    base = {
        "comm_type": "speech",
        "title": "Powell remarks on inflation",
        "filing_date": "2026-05-11",
        "speaker": "Jerome Powell",
        "full_url": "https://www.federalreserve.gov/newsevents/speech/powell20260511a.htm",
        "full_text": "Sample speech text.",
        "word_count": 3,
        "collected_at": "2026-05-11T12:00:00",
    }
    base.update(overrides)
    return base


def test_store_fed_item_first_insert_then_duplicate_ignored(parametrized_conn):
    """T1.3: _store_fed_item routes through engine_aware_upsert(action='ignore').

    First call inserts the row. Second call with the same (comm_type, date,
    title) dedup target is silently ignored — the row count stays at 1 and
    the originally-stored values remain. Exercises SQLite and PostgreSQL.
    """
    from src.data_collection.fed_collector import _store_fed_item

    conn = parametrized_conn

    first = _row_kwargs(full_text="Original speech text.")
    second = _row_kwargs(full_text="Attempted overwrite — must be ignored.")

    stored1 = _store_fed_item(conn, **first)
    stored2 = _store_fed_item(conn, **second)
    conn.commit()

    assert stored1 == 1
    # SQLite's INSERT OR IGNORE returns 1 from .execute regardless of whether
    # the row was actually inserted; the function returns 1 unconditionally
    # when no IntegrityError fires. The DEDUP correctness check is the
    # row-count assertion immediately below — that's the real invariant.
    assert stored2 == 1

    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS c FROM fed_communications "
        "WHERE comm_type=? AND date=? AND title=?",
        (first["comm_type"], first["filing_date"], first["title"]),
    )
    row = cur.fetchone()
    count = row["c"] if hasattr(row, "keys") and "c" in row.keys() else row[0]
    assert count == 1, "duplicate should have been ignored, only one row expected"

    cur.execute(
        "SELECT full_text FROM fed_communications "
        "WHERE comm_type=? AND date=? AND title=?",
        (first["comm_type"], first["filing_date"], first["title"]),
    )
    fetched = cur.fetchone()
    full_text = fetched["full_text"] if hasattr(fetched, "keys") else fetched[0]
    assert full_text == "Original speech text.", (
        "INSERT OR IGNORE / DO NOTHING must preserve the first row's "
        "values — the second call should NOT have overwritten them"
    )
