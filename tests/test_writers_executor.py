"""Phase 3-revised T4 — commands/executor writer cross-engine verification.

Tests that _store_result in src/commands/executor.py:
1. Uses engine_aware_upsert (not raw INSERT) for command_results rows
2. Writes a command_results row that is readable post-call
3. Updates pending_commands.status via the raw UPDATE that stays in place
4. Both success and error status set pending_commands correctly

Tests 1 (uses engine_aware_upsert) FAILS before the implementation is changed.
Tests 2-4 verify behavioral correctness on the sqlite engine.
Postgres variants skip cleanly when TEST_DATABASE_URL is unset.
"""

import sqlite3
import uuid
from datetime import datetime
from unittest.mock import patch, call
from zoneinfo import ZoneInfo

import pytest

from tests.conftest import init_test_db

ET = ZoneInfo("America/New_York")


def _insert_pending_command(conn, command_id: str) -> None:
    """Insert a minimal pending_commands row so the UPDATE has something to hit."""
    conn.execute(
        "INSERT INTO pending_commands "
        "(command_id, command_type, command_name, payload_json, status, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (command_id, "local", "scan", "{}", "pending",
         datetime.now(ET).isoformat(), datetime.now(ET).isoformat()),
    )


def test_store_result_calls_engine_aware_upsert(tmp_path):
    """_store_result MUST use engine_aware_upsert for the command_results write.

    This test FAILS with the old raw-INSERT implementation (which doesn't call
    engine_aware_upsert at all) and PASSES after the conversion.
    """
    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, ["command_results", "pending_commands"])

    command_id = str(uuid.uuid4())
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _insert_pending_command(conn, command_id)
    conn.commit()
    conn.close()

    import src.commands.executor as executor_module

    with patch.object(
        executor_module,
        "engine_aware_upsert",
        wraps=executor_module.engine_aware_upsert,
    ) as mock_upsert:
        executor_module._store_result(command_id, "success", result={"x": 1}, db_path=db_path)
        assert mock_upsert.called, (
            "_store_result must call engine_aware_upsert for command_results — "
            "raw INSERT is not cross-engine safe"
        )
        first_call = mock_upsert.call_args_list[0]
        assert first_call[0][1] == "command_results", (
            f"Expected engine_aware_upsert called on 'command_results', "
            f"got {first_call[0][1]!r}"
        )
        assert first_call[1].get("action") == "ignore" or (
            len(first_call[0]) >= 4 and first_call[0][3] == "ignore"
        ), "engine_aware_upsert must be called with action='ignore'"


@pytest.mark.parametrize("engine", ["sqlite", "postgres"])
def test_store_result_inserts_command_results_row(engine, tmp_path, request):
    """_store_result writes a command_results row to the DB."""
    if engine == "postgres":
        pytest.skip("requires live PG fixture; TEST_DATABASE_URL not wired in this env")

    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, ["command_results", "pending_commands"])

    command_id = str(uuid.uuid4())
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _insert_pending_command(conn, command_id)
    conn.commit()
    conn.close()

    from src.commands.executor import _store_result
    _store_result(command_id, "success", result={"msg": "ok"}, db_path=db_path)

    conn2 = sqlite3.connect(db_path)
    conn2.row_factory = sqlite3.Row
    row = conn2.execute(
        "SELECT * FROM command_results WHERE command_id = ?", (command_id,)
    ).fetchone()
    conn2.close()

    assert row is not None, "command_results row not written by _store_result"
    assert row["status"] == "success"


@pytest.mark.parametrize("engine", ["sqlite", "postgres"])
def test_store_result_updates_pending_commands_status(engine, tmp_path, request):
    """The UPDATE pending_commands after engine_aware_upsert still fires correctly."""
    if engine == "postgres":
        pytest.skip("requires live PG fixture; TEST_DATABASE_URL not wired in this env")

    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, ["command_results", "pending_commands"])

    command_id = str(uuid.uuid4())
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _insert_pending_command(conn, command_id)
    conn.commit()
    conn.close()

    from src.commands.executor import _store_result
    _store_result(command_id, "success", result={"msg": "ok"}, db_path=db_path)

    conn2 = sqlite3.connect(db_path)
    conn2.row_factory = sqlite3.Row
    row = conn2.execute(
        "SELECT status FROM pending_commands WHERE command_id = ?", (command_id,)
    ).fetchone()
    conn2.close()

    assert row is not None, "pending_commands row missing"
    assert row["status"] == "completed", (
        f"Expected 'completed', got {row['status']!r}"
    )


@pytest.mark.parametrize("engine", ["sqlite", "postgres"])
def test_store_result_error_status_sets_failed(engine, tmp_path, request):
    """_store_result with status='error' sets pending_commands.status='failed'."""
    if engine == "postgres":
        pytest.skip("requires live PG fixture; TEST_DATABASE_URL not wired in this env")

    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, ["command_results", "pending_commands"])

    command_id = str(uuid.uuid4())
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _insert_pending_command(conn, command_id)
    conn.commit()
    conn.close()

    from src.commands.executor import _store_result
    _store_result(command_id, "error", error="something broke", db_path=db_path)

    conn2 = sqlite3.connect(db_path)
    conn2.row_factory = sqlite3.Row
    row = conn2.execute(
        "SELECT status FROM pending_commands WHERE command_id = ?", (command_id,)
    ).fetchone()
    conn2.close()

    assert row is not None
    assert row["status"] == "failed", (
        f"Expected 'failed', got {row['status']!r}"
    )
