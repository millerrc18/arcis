"""Dual-engine regression-lock for short_interest_collector UPSERT path.

Sprint 5 §J5/§J6 Phase 1 T1.1 — pins the migration target
(`engine_aware_upsert(conn, 'short_interest', row_dict, action='ignore')`)
against both SQLite and Postgres so the dialect-impedance is centralised at
the wrapper. The Postgres variant skips cleanly when TEST_DATABASE_URL is
absent (see tests/conftest.py:parametrized_conn).

Pre-migration: collector at src/data_collection/short_interest_collector.py:111
emitted raw `INSERT OR IGNORE INTO short_interest ...` — SQLite-only syntax
that Postgres rejects with `syntax error at or near "OR"`. The migration
swaps the raw INSERT for engine_aware_upsert, which dispatches to:
  - SQLite: `INSERT OR IGNORE INTO ...` (unchanged behaviour)
  - PG    : `INSERT ... ON CONFLICT (ticker, settlement_date) DO NOTHING`

Conflict target is resolved automatically from
TABLES['short_interest'].sync_conflict_col = "ticker, settlement_date".
"""
from __future__ import annotations

from src.utils.db import engine_aware_upsert


def _row(**overrides):
    """Build a minimal short_interest row dict; overrides patch specific fields."""
    base = {
        "ticker": "AAPL",
        "settlement_date": "2026-03-15",
        "short_interest": 5_000_000.0,
        "avg_daily_volume": 1_000_000.0,
        "days_to_cover": 5.0,
        "short_pct_float": 2.5,
        "source": "finnhub",
        "collected_at": "2026-03-16T09:30:00-04:00",
    }
    base.update(overrides)
    return base


def test_engine_aware_upsert_short_interest_first_insert_lands_row(parametrized_conn):
    """First engine_aware_upsert(action='ignore') inserts the row on both engines.

    Asserts the post-migration call shape used by short_interest_collector lands
    a row whose conflict columns match the registry sync_conflict_col target
    ("ticker, settlement_date"). Validates the wrapper resolves the conflict
    target correctly from TABLES['short_interest'].sync_conflict_col rather
    than falling back to the integer PK (which would silently allow duplicate
    settlement-date rows on Postgres).
    """
    row = _row()
    engine_aware_upsert(parametrized_conn, "short_interest", row, action="ignore")

    cur = parametrized_conn.execute(
        "SELECT ticker, settlement_date, short_interest "
        "FROM short_interest WHERE ticker = ? AND settlement_date = ?",
        ("AAPL", "2026-03-15"),
    )
    rows = cur.fetchall()
    assert len(rows) == 1, f"expected 1 row after first insert; got {len(rows)}"
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["settlement_date"] == "2026-03-15"
    # short_interest is REAL; both engines round-trip the float.
    assert float(rows[0]["short_interest"]) == 5_000_000.0


def test_engine_aware_upsert_short_interest_duplicate_ignored_no_overwrite(
    parametrized_conn,
):
    """Second engine_aware_upsert with same (ticker, settlement_date) is ignored.

    Two assertions:
      1. No exception is raised on duplicate insert — the action='ignore' path
         must silently no-op (mirrors `INSERT OR IGNORE` semantics on SQLite
         and `ON CONFLICT DO NOTHING` semantics on PG).
      2. The duplicate must NOT overwrite the original non-conflict columns.
         The original short_interest value (5_000_000) must survive even
         though the duplicate sends a different value (9_999_999) — proving
         the upsert is DO-NOTHING, not DO-UPDATE.

    The second invariant is what distinguishes action='ignore' from
    action='replace' on the engine_aware_upsert dispatch. Without it, the
    migration could silently swap "ignore" for "replace" semantics on PG and
    corrupt non-target columns whenever a tick arrives twice in a single
    biweekly window (e.g. a retry path).
    """
    original = _row(short_interest=5_000_000.0, days_to_cover=5.0)
    engine_aware_upsert(parametrized_conn, "short_interest", original, action="ignore")

    # Duplicate (same conflict key) carrying different non-conflict values —
    # must be ignored without overwriting.
    duplicate = _row(short_interest=9_999_999.0, days_to_cover=99.0)
    engine_aware_upsert(parametrized_conn, "short_interest", duplicate, action="ignore")

    cur = parametrized_conn.execute(
        "SELECT short_interest, days_to_cover FROM short_interest "
        "WHERE ticker = ? AND settlement_date = ?",
        ("AAPL", "2026-03-15"),
    )
    rows = cur.fetchall()
    assert len(rows) == 1, (
        f"duplicate must be ignored — expected 1 row; got {len(rows)}"
    )
    # Original values intact — DO NOTHING, not DO UPDATE.
    assert float(rows[0]["short_interest"]) == 5_000_000.0, (
        "non-conflict column was overwritten — action='ignore' must not "
        "update existing rows"
    )
    assert float(rows[0]["days_to_cover"]) == 5.0


def test_collect_short_interest_dedups_via_engine_aware_upsert(tmp_path):
    """End-to-end SQLite regression: collector dedups by (ticker, settlement_date).

    Goes through the full collector path (collect_short_interest) — including
    the migration site at line 111. Asserts that calling the collector twice
    with identical Finnhub mock data produces exactly one row, proving the
    engine_aware_upsert(action='ignore') dispatch is wired correctly on the
    SQLite path that production currently uses.

    PG end-to-end is exercised by the parametrized_conn-based tests above
    (which call engine_aware_upsert directly with the same row shape the
    collector now builds).
    """
    from unittest.mock import MagicMock, patch

    from src.data_collection.short_interest_collector import collect_short_interest
    from tests.conftest import init_test_db

    db_path = str(tmp_path / "test.db")
    init_test_db(db_path)

    mock_data = {
        "data": [
            {
                "settlementDate": "2026-03-15",
                "shortInterest": 5_000_000,
                "avgDailyShareTradeVolume": 1_000_000,
                "shortInterestPercentFloat": 2.5,
            },
        ],
    }

    with patch(
        "src.data_collection.short_interest_collector._get_finnhub_key",
        return_value="key",
    ), patch(
        "src.data_collection.short_interest_collector.requests.get"
    ) as mock_get, patch(
        "src.data_collection.short_interest_collector.time.sleep"
    ):
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_data
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        # First collection — should insert one row.
        result_1 = collect_short_interest(["AAPL"], db_path=db_path)
        # Second collection with identical settlement_date — should dedup.
        result_2 = collect_short_interest(["AAPL"], db_path=db_path)

    import sqlite3

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM short_interest").fetchone()[0]

    assert count == 1, (
        f"engine_aware_upsert(action='ignore') must dedup by (ticker, "
        f"settlement_date) on SQLite path; got {count} rows after two "
        f"collections"
    )
    assert result_1["records_stored"] == 1
    # cursor.rowcount on INSERT OR IGNORE returns 0 for the dedup'd insert
    # on SQLite (no row affected). Same behaviour expected post-migration.
    assert result_2["records_stored"] == 0


def test_collect_short_interest_routes_through_engine_aware_upsert(tmp_path):
    """Migration witness: collector at :111 calls engine_aware_upsert.

    Sprint 5 §J5/§J6 Phase 1 T1.1 migrated the raw `INSERT OR IGNORE INTO
    short_interest` at short_interest_collector.py:111 to
    `engine_aware_upsert(conn, 'short_interest', row_dict, action='ignore')`.
    This test patches engine_aware_upsert in the collector module's namespace
    and asserts the collector invokes it once per Finnhub data entry. Without
    the migration, this test fails because engine_aware_upsert is never
    called (the collector emits raw SQL via conn.execute instead).

    Also asserts the row_dict shape — every column the original raw INSERT
    populated is present (ticker, settlement_date, short_interest,
    avg_daily_volume, days_to_cover, short_pct_float, source, collected_at),
    and `action='ignore'` is passed. Any future refactor that drops a column
    or flips action to 'replace' surfaces here.
    """
    from unittest.mock import MagicMock, patch

    from src.data_collection.short_interest_collector import collect_short_interest
    from tests.conftest import init_test_db

    db_path = str(tmp_path / "test.db")
    init_test_db(db_path)

    mock_data = {
        "data": [
            {
                "settlementDate": "2026-03-15",
                "shortInterest": 5_000_000,
                "avgDailyShareTradeVolume": 1_000_000,
                "shortInterestPercentFloat": 2.5,
            },
        ],
    }

    with patch(
        "src.data_collection.short_interest_collector._get_finnhub_key",
        return_value="key",
    ), patch(
        "src.data_collection.short_interest_collector.requests.get"
    ) as mock_get, patch(
        "src.data_collection.short_interest_collector.time.sleep"
    ), patch(
        "src.data_collection.short_interest_collector.engine_aware_upsert"
    ) as mock_upsert:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_data
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        collect_short_interest(["AAPL"], db_path=db_path)

    assert mock_upsert.call_count == 1, (
        f"collector must route through engine_aware_upsert exactly once per "
        f"Finnhub data entry; got {mock_upsert.call_count} calls"
    )
    args, kwargs = mock_upsert.call_args
    # Signature: engine_aware_upsert(conn, table_name, row_dict, action=...)
    # The collector must pass 'short_interest' as the table and
    # action='ignore'. The conn arg is engine-managed; row_dict carries the
    # eight columns the prior raw INSERT used.
    # Support both positional and keyword styles for resilience.
    table_name = args[1] if len(args) >= 2 else kwargs.get("table_name")
    row_dict = args[2] if len(args) >= 3 else kwargs.get("row_dict")
    action = args[3] if len(args) >= 4 else kwargs.get("action")
    assert table_name == "short_interest", (
        f"engine_aware_upsert called with table_name={table_name!r}, "
        f"expected 'short_interest'"
    )
    assert action == "ignore", (
        f"engine_aware_upsert called with action={action!r}, expected 'ignore'"
    )
    expected_keys = {
        "ticker",
        "settlement_date",
        "short_interest",
        "avg_daily_volume",
        "days_to_cover",
        "short_pct_float",
        "source",
        "collected_at",
    }
    assert expected_keys.issubset(row_dict.keys()), (
        f"row_dict missing columns from pre-migration raw INSERT: "
        f"{expected_keys - set(row_dict.keys())}"
    )
    assert row_dict["ticker"] == "AAPL"
    assert row_dict["settlement_date"] == "2026-03-15"
    assert row_dict["source"] == "finnhub"
