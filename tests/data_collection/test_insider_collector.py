"""Tests for src/data_collection/insider_collector.py — Sprint 5 §J5/§J6 Phase 1 T1.6.

Verifies the plain INSERT at :118 has been converted to `engine_aware_upsert(
conn, 'insider_transactions', row_dict, action='ignore')` and that the dedup
behaviour matches the helper contract on both engines.

Note on the conflict target: `insider_transactions` declares
`primary_key='id'` and `sync_conflict_col=None` in `src/schema/registry.py`,
so `_resolve_conflict_target` resolves to `['id']`. With explicit `id` values,
the helper dedupes; with auto-increment `id` (the production code path), every
insert generates a fresh `id` and no conflict fires — preserving the current
no-dedup behaviour. See the T1.6 dispatch concerns in the agent status report
for the wider context.

Mocks Finnhub via the `requests.get` patch pattern established by
`tests/test_data_collectors.py::TestInsiderTransactions`.
"""

import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest


TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_db():
    """SQLite tmp database with the insider_transactions table provisioned."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    from tests.conftest import init_test_db

    init_test_db(path, ["insider_transactions"])
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass  # Windows file locking — cleaned up on next reboot


@pytest.fixture
def sqlite_conn(sqlite_db):
    """sqlite3.Connection bound to the provisioned schema."""
    conn = sqlite3.connect(sqlite_db)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def pg_conn():
    """psycopg2 wrapper bound to TEST_DATABASE_URL. Skips when unset.

    Bootstraps `insider_transactions` from the registry's PG DDL and drops
    the table on teardown so this fixture is self-contained.
    """
    if not _PG_AVAILABLE:
        pytest.skip("TEST_DATABASE_URL not set or not postgres://")

    import psycopg2
    import psycopg2.extras

    from src.schema.postgres import generate_create_sql
    from src.schema.registry import TABLES
    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(
        TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )
    raw.autocommit = True
    cur = raw.cursor()
    cur.execute("DROP TABLE IF EXISTS insider_transactions CASCADE")
    cur.execute(generate_create_sql(TABLES["insider_transactions"]))
    cur.close()
    raw.autocommit = False
    wrapper = PostgresConnectionWrapper(raw)
    try:
        yield wrapper
    finally:
        try:
            wrapper.rollback()
        except Exception:
            pass
        try:
            raw.autocommit = True
            cleanup = raw.cursor()
            cleanup.execute("DROP TABLE IF EXISTS insider_transactions CASCADE")
            cleanup.close()
        finally:
            raw.close()


def _get_conn(request):
    engine = request.param
    if engine == "sqlite":
        return request.getfixturevalue("sqlite_conn")
    if engine == "postgres":
        return request.getfixturevalue("pg_conn")
    raise ValueError(f"unknown engine: {engine!r}")


@pytest.fixture(params=["sqlite", "postgres"])
def conn_engine(request):
    return _get_conn(request)


# ---------------------------------------------------------------------------
# Test 1: engine_aware_upsert(action='ignore') with explicit conflict-key id
# dedupes a repeated row across both engines (parametrized).
# ---------------------------------------------------------------------------


def test_insider_transactions_upsert_ignore_dedupes_on_conflict_key(conn_engine):
    """T1.6: action='ignore' on insider_transactions with same conflict key (`id`)
    leaves the existing row intact and raises no exception (PM TEST_STRATEGY).

    The conflict target for `insider_transactions` resolves to the PK `id`
    (see `_resolve_conflict_target` in src/utils/db.py — falls back to
    `primary_key` when `sync_conflict_col` is None). Supplying the same `id`
    twice exercises the dedup branch on both engines.
    """
    from src.utils.db import engine_aware_upsert

    conn = conn_engine

    row = {
        "id": 12345,
        "ticker": "AAPL",
        "insider_name": "Tim Cook",
        "title": "CEO",
        "transaction_type": "S",
        "transaction_date": "2026-05-01",
        "filing_date": "2026-05-05",
        "shares": 1000.0,
        "price": 150.0,
        "value": 150000.0,
        "shares_after": 999000.0,
        "ownership_type": None,
        "source": "finnhub",
        "collected_at": "2026-05-05T12:00:00",
    }

    # (1) first insert lands row
    engine_aware_upsert(conn, "insider_transactions", row, action="ignore")
    conn.commit()

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM insider_transactions")
    first_count_row = cur.fetchone()
    first_count = (
        first_count_row["c"]
        if hasattr(first_count_row, "keys") and "c" in first_count_row.keys()
        else first_count_row[0]
    )
    assert first_count == 1

    # (2) duplicate insert with same conflict key — no exception, row count
    # remains 1 (the new behavior)
    duplicate = dict(row)
    duplicate["insider_name"] = "Someone Else"  # would-be-overwritten value
    engine_aware_upsert(conn, "insider_transactions", duplicate, action="ignore")
    conn.commit()

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM insider_transactions")
    second_count_row = cur.fetchone()
    second_count = (
        second_count_row["c"]
        if hasattr(second_count_row, "keys") and "c" in second_count_row.keys()
        else second_count_row[0]
    )
    assert second_count == 1

    # Confirm DO NOTHING semantics — original insider_name preserved
    cur = conn.cursor()
    cur.execute("SELECT insider_name FROM insider_transactions WHERE id=?", (12345,))
    row_after = cur.fetchone()
    fetched_name = (
        row_after["insider_name"]
        if hasattr(row_after, "keys") and "insider_name" in row_after.keys()
        else row_after[0]
    )
    assert fetched_name == "Tim Cook"


# ---------------------------------------------------------------------------
# Test 2: integration — collect_insider_transactions wires the helper.
# Verifies that the production code path (no explicit id) calls through to
# the engine_aware_upsert helper without raising and writes the row.
# ---------------------------------------------------------------------------


def test_collect_insider_transactions_uses_engine_aware_upsert(sqlite_db):
    """T1.6: collector wires into engine_aware_upsert and stores the API row."""
    from src.data_collection.insider_collector import collect_insider_transactions

    mock_data = {
        "data": [
            {
                "name": "Tim Cook",
                "position": "CEO",
                "transactionCode": "S",
                "transactionDate": "2026-05-01",
                "filingDate": "2026-05-05",
                "change": -1000,
                "transactionPrice": 150.0,
                "share": 999000,
            },
        ],
    }

    with patch(
        "src.data_collection.insider_collector._get_finnhub_key",
        return_value="test-key",
    ), patch(
        "src.data_collection.insider_collector.requests.get"
    ) as mock_get, patch(
        "src.data_collection.insider_collector.time.sleep"
    ), patch(
        "src.data_collection.insider_collector.engine_aware_upsert",
        wraps=__import__(
            "src.utils.db", fromlist=["engine_aware_upsert"]
        ).engine_aware_upsert,
    ) as mock_helper:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_data
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = collect_insider_transactions(["AAPL"], db_path=sqlite_db)

    # The helper was called once per filing (one filing in this mock).
    assert mock_helper.called, "engine_aware_upsert was not invoked from the collector"
    helper_calls = mock_helper.call_args_list
    assert len(helper_calls) == 1
    call_kwargs = helper_calls[0].kwargs
    call_args = helper_calls[0].args
    # Positional or keyword — verify table + action regardless
    table_arg = call_args[1] if len(call_args) > 1 else call_kwargs.get("table_name")
    action_arg = call_kwargs.get("action", call_args[3] if len(call_args) > 3 else None)
    assert table_arg == "insider_transactions"
    assert action_arg == "ignore"

    # Row stored in DB.
    assert result["transactions_stored"] == 1
    with sqlite3.connect(sqlite_db) as verify:
        verify.row_factory = sqlite3.Row
        rows = verify.execute(
            "SELECT ticker, insider_name, filing_date FROM insider_transactions"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["insider_name"] == "Tim Cook"
    assert rows[0]["filing_date"] == "2026-05-05"
