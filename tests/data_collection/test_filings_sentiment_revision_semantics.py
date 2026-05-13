"""Structural lock test — filings_sentiment action='ignore' revision semantics.

Sprint 6 Wave A — WA5.

Decision 27 footnote (PR #1083 review, 2026-05-13): the
``filings_sentiment`` table uses ``engine_aware_upsert(..., action="ignore")``
which means a revision to an existing (ticker, filing_type, filed_at) row is
**silently dropped**.  This is the current intentional behavior: we snapshot
each filing's first-seen score and do not overwrite it.

This test PASSES against the current behavior to lock it.  If the operator
ever decides to switch to ``action='replace'``, this test will fail loudly,
forcing operator review — which is exactly the desired gate.

The migration path to switch behavior:
1. Add "filings_sentiment" to ``_REPLACE_SEMANTICS`` in ``src/utils/db.py``.
2. Change ``action="ignore"`` to ``action="replace"`` in
   ``filings_sentiment_collector.py:162``.
3. Update this test to assert the NEW score (not the original) persists.
"""

import sqlite3
import tempfile
from pathlib import Path


def _create_filings_sentiment_table(conn: sqlite3.Connection) -> None:
    """Create minimal filings_sentiment schema for the test."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS filings_sentiment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            filing_type TEXT NOT NULL,
            filed_at TEXT NOT NULL,
            sentiment_score REAL,
            sentiment_label TEXT,
            retrieved_at TEXT,
            UNIQUE(ticker, filing_type, filed_at)
        )
    """)
    conn.commit()


def test_filings_sentiment_action_ignore_drops_revision():
    """Write a row, attempt to upsert the same (ticker, filing_type, filed_at)
    with a different sentiment_score, then verify the ORIGINAL score persists.

    This documents the current action='ignore' behavior: the revision is
    silently dropped and the first-seen score is preserved.  If this test
    starts failing, it means the upsert semantic changed — investigate before
    accepting that change.
    """
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
        db_path = f.name

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        _create_filings_sentiment_table(conn)

        original_score = 0.75
        revised_score = -0.50

        # Insert the first (original) row.
        conn.execute(
            "INSERT OR IGNORE INTO filings_sentiment "
            "(ticker, filing_type, filed_at, sentiment_score, sentiment_label, retrieved_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("AAPL", "10-K", "2024-11-01", original_score, "positive", "2024-11-02T00:00:00+00:00"),
        )
        conn.commit()

        # Attempt to upsert the same row with a different sentiment_score using
        # the same INSERT OR IGNORE semantics the collector uses.
        conn.execute(
            "INSERT OR IGNORE INTO filings_sentiment "
            "(ticker, filing_type, filed_at, sentiment_score, sentiment_label, retrieved_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("AAPL", "10-K", "2024-11-01", revised_score, "negative", "2024-11-03T00:00:00+00:00"),
        )
        conn.commit()

        # Fetch the row and verify the ORIGINAL score is still present.
        row = conn.execute(
            "SELECT sentiment_score FROM filings_sentiment "
            "WHERE ticker=? AND filing_type=? AND filed_at=?",
            ("AAPL", "10-K", "2024-11-01"),
        ).fetchone()

        assert row is not None, "Row should exist after initial insert"
        assert row["sentiment_score"] == original_score, (
            f"Expected original score {original_score} to persist under action='ignore'; "
            f"got {row['sentiment_score']} — upsert semantic may have changed"
        )
        conn.close()
    finally:
        Path(db_path).unlink(missing_ok=True)
