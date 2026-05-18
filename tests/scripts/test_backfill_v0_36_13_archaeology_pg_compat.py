"""W21 P1-1 fix regression-lock for scripts/backfill_v0.36.13_archaeology.py.

Two PG-compat bugs were fixed in v0.36.15 (W21 P1-1):

1. Raw psycopg2 connection has no `execute()` method. The script's
   `conn.execute(...)` calls failed with AttributeError. Fix: wrap with
   `PostgresConnectionWrapper` from `src.utils.db`.

2. The regime-table probe did `SELECT 1 FROM <name> LIMIT 1` and caught
   the error generically. On PG, the failed query aborts the surrounding
   transaction, causing every subsequent query to fail with
   `current transaction is aborted, commands ignored until end of
   transaction block`. Fix: probe via `information_schema.tables` instead.

These tests pin the two fixes as file-content regression-locks. Behavioral
testing of the script against a real PG would require additional fixture
infrastructure (a test PG with the right schema) — out of scope for a
one-shot recovery script.
"""

import os


_SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "scripts", "backfill_v0.36.13_archaeology.py",
)


def _load_source() -> str:
    with open(_SCRIPT_PATH, encoding="utf-8") as f:
        return f.read()


def test_uses_postgres_connection_wrapper():
    """Raw psycopg2 conn must be wrapped with PostgresConnectionWrapper."""
    source = _load_source()
    assert "PostgresConnectionWrapper" in source, (
        "scripts/backfill_v0.36.13_archaeology.py must wrap psycopg2 "
        "connections with PostgresConnectionWrapper. Raw psycopg2 conns "
        "have no execute() method."
    )


def test_psycopg2_connect_uses_realdict_cursor():
    """psycopg2.connect must use RealDictCursor for the wrapper to work."""
    source = _load_source()
    assert "RealDictCursor" in source, (
        "scripts/backfill_v0.36.13_archaeology.py must pass "
        "cursor_factory=psycopg2.extras.RealDictCursor to psycopg2.connect() "
        "so PostgresConnectionWrapper returns name-keyed rows."
    )


def test_regime_probe_uses_information_schema():
    """Regime table probe must use information_schema to avoid PG tx-abort."""
    source = _load_source()
    assert "information_schema.tables" in source, (
        "scripts/backfill_v0.36.13_archaeology.py must probe regime tables "
        "via information_schema.tables. Direct `SELECT FROM <name>` on a "
        "missing relation aborts the surrounding PG transaction, breaking "
        "every subsequent query in the script."
    )
