"""Parametrized dual-engine tests for `_store_snapshot` UPSERT path and
_collect_gpu_metrics() multi-GPU parser (#117 hotfix).

Sprint 5 §J5/§J6 Phase 1 T1.12 — migration of `system_metrics`
`INSERT OR REPLACE` (dynamic-placeholder build) to the central
`engine_aware_upsert(action='replace')` helper.

The audit at docs/audits/2026-05-11-modified-a-migration/replace-semantics-audit.md
classifies `system_metrics` as `in_place_update`:
  - no incoming FKs, no triggers, no rowid dependencies
  - production writer generates a fresh UUID per call (so REPLACE is dead-code
    in production), but the dispatch table still routes via the audit gate

This test uses a DETERMINISTIC `snapshot_id` (NOT `uuid.uuid4()`) so the
second insert collides with the first on PK and the REPLACE/UPDATE path
is actually exercised — that's the entire point of the engine-aware
dispatch and the audit decision must remain enforced.

PG variant skips cleanly when `TEST_DATABASE_URL` is not set (CI laptops).
See test_db_engine_aware_upsert.py for fixture pattern.
"""

import json
import os
import sqlite3
import subprocess
import unittest.mock as mock

import pytest


TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_sqlite_ddl(table_name):
    from src.schema.registry import TABLES

    td = TABLES[table_name]
    cols = []
    for c in td.columns:
        nn = "" if c.nullable else " NOT NULL"
        cols.append(f"{c.name} {c.type}{nn}")
    pk = td.primary_key if isinstance(td.primary_key, list) else [td.primary_key]
    cols.append(f"PRIMARY KEY ({', '.join(pk)})")
    body = ",\n    ".join(cols)
    return f"CREATE TABLE {table_name} (\n    {body}\n);"


def _build_pg_ddl(table_name):
    from src.schema.postgres import generate_create_table_sql
    from src.schema.registry import TABLES

    return generate_create_table_sql(TABLES[table_name])


@pytest.fixture
def sqlite_conn():
    """In-memory SQLite connection with row_factory=sqlite3.Row."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def pg_conn():
    """Live psycopg2 wrapper. Skips if TEST_DATABASE_URL not set."""
    if not _PG_AVAILABLE:
        pytest.skip("TEST_DATABASE_URL not set or not postgres://")

    import psycopg2
    import psycopg2.extras

    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(
        TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )
    wrapper = PostgresConnectionWrapper(raw)
    yield wrapper
    try:
        wrapper.rollback()
    except Exception:
        pass
    wrapper.close()


def _setup_table(conn, table_name):
    """Drop+recreate `table_name` on whichever engine `conn` is for."""
    from src.utils.db import PostgresConnectionWrapper

    if isinstance(conn, PostgresConnectionWrapper):
        cur = conn.cursor()
        cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        cur.execute(_build_pg_ddl(table_name))
        conn.commit()
    else:
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.execute(_build_sqlite_ddl(table_name))
        conn.commit()


def _get_conn(request):
    engine = request.param
    if engine == "sqlite":
        return request.getfixturevalue("sqlite_conn")
    elif engine == "postgres":
        return request.getfixturevalue("pg_conn")
    raise ValueError(f"unknown engine: {engine}")


@pytest.fixture(params=["sqlite", "postgres"])
def conn_engine(request):
    return _get_conn(request)


def _count_rows(conn, table):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
    row = cur.fetchone()
    return row["c"] if hasattr(row, "keys") and "c" in row.keys() else row[0]


def _fetch_by_snapshot(conn, snapshot_id):
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM system_metrics WHERE snapshot_id=?", (snapshot_id,)
    )
    return cur.fetchone()


# ---------------------------------------------------------------------------
# T1.12 Tests
# ---------------------------------------------------------------------------


def _make_snapshot(snapshot_id, timestamp, *, gpu_util=50.0, cpu_pct=25.0):
    """Build a complete system_metrics row dict.

    All 15 columns of the registry table are populated. Caller passes a
    deterministic `snapshot_id` so a second call with the same id triggers
    the in-place-update branch of `engine_aware_upsert`.
    """
    return {
        "snapshot_id": snapshot_id,
        "timestamp": timestamp,
        "gpu_util_pct": gpu_util,
        "gpu_vram_used_mb": 4096.0,
        "gpu_vram_total_mb": 24576.0,
        "gpu_temp_c": 65.0,
        "gpu_power_w": 250.0,
        "cpu_pct": cpu_pct,
        "ram_used_mb": 16000.0,
        "ram_total_mb": 64000.0,
        "disk_used_gb": 500.0,
        "disk_total_gb": 2000.0,
        "ollama_status": "running",
        "ollama_model": "halcyon-v1.0.0",
        "python_rss_mb": 350.0,
    }


def test_store_snapshot_inserts_new_row(conn_engine):
    """T1.12 #1: first call to `_store_snapshot` inserts a brand-new row."""
    from src.monitoring import system_metrics as sm_module

    conn = conn_engine
    _setup_table(conn, "system_metrics")

    snap = _make_snapshot("deterministic-snap-001", "2026-05-11T00:00:00")
    # Patch connect_db so _store_snapshot uses our fixture's conn directly
    # (sidesteps DB_PATH resolution and lets the test exercise both engines).
    original_connect_db = sm_module.connect_db
    try:
        sm_module.connect_db = lambda _path: _NoCloseConn(conn)
        sm_module._store_snapshot(snap, db_path="ignored")
    finally:
        sm_module.connect_db = original_connect_db
    conn.commit()

    assert _count_rows(conn, "system_metrics") == 1
    fetched = _fetch_by_snapshot(conn, "deterministic-snap-001")
    assert fetched["gpu_util_pct"] == 50.0
    assert fetched["cpu_pct"] == 25.0
    assert fetched["timestamp"] == "2026-05-11T00:00:00"


def test_store_snapshot_replaces_existing_row(conn_engine):
    """T1.12 #2: same PK on second call updates non-target columns.

    Deterministic snapshot_id forces the conflict — exercising the
    `in_place_update` branch on PG and `INSERT OR REPLACE` natively on
    SQLite. Both must converge on a single-row table with the second
    call's values.
    """
    from src.monitoring import system_metrics as sm_module

    conn = conn_engine
    _setup_table(conn, "system_metrics")

    snap1 = _make_snapshot(
        "deterministic-snap-002", "2026-05-11T00:00:00",
        gpu_util=10.0, cpu_pct=5.0,
    )
    snap2 = _make_snapshot(
        "deterministic-snap-002",  # same PK -> conflict
        "2026-05-11T00:05:00",
        gpu_util=90.0, cpu_pct=80.0,
    )

    original_connect_db = sm_module.connect_db
    try:
        sm_module.connect_db = lambda _path: _NoCloseConn(conn)
        sm_module._store_snapshot(snap1, db_path="ignored")
        sm_module._store_snapshot(snap2, db_path="ignored")
    finally:
        sm_module.connect_db = original_connect_db
    conn.commit()

    assert _count_rows(conn, "system_metrics") == 1
    fetched = _fetch_by_snapshot(conn, "deterministic-snap-002")
    assert fetched["gpu_util_pct"] == 90.0
    assert fetched["cpu_pct"] == 80.0
    assert fetched["timestamp"] == "2026-05-11T00:05:00"


def test_store_snapshot_dispatches_through_engine_aware_upsert(monkeypatch):
    """T1.12 #3: `_store_snapshot` MUST call `engine_aware_upsert`.

    This pins the migration: after T1.12 the function dispatches through
    the central helper rather than building dynamic placeholders inline.
    Asserts the helper is called with table='system_metrics',
    action='replace', and a dict of the full row.
    """
    from src.monitoring import system_metrics as sm_module

    captured = {}

    def fake_upsert(conn, table_name, row_dict, action="replace"):
        captured["table_name"] = table_name
        captured["row_dict"] = dict(row_dict)
        captured["action"] = action

    # Patch engine_aware_upsert at the symbol the module imports it as.
    monkeypatch.setattr(sm_module, "engine_aware_upsert", fake_upsert, raising=True)

    # Patch connect_db so we don't actually open a database file.
    class _StubConn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def commit(self):
            pass

    monkeypatch.setattr(sm_module, "connect_db", lambda _path: _StubConn(), raising=True)

    snap = _make_snapshot("dispatch-test-snap", "2026-05-11T00:00:00")
    sm_module._store_snapshot(snap, db_path="ignored")

    assert captured["table_name"] == "system_metrics"
    assert captured["action"] == "replace"
    # Every column the writer produced must be passed through.
    assert captured["row_dict"]["snapshot_id"] == "dispatch-test-snap"
    assert captured["row_dict"]["gpu_util_pct"] == 50.0
    assert captured["row_dict"]["ollama_status"] == "running"
    assert captured["row_dict"]["timestamp"] == "2026-05-11T00:00:00"


# ---------------------------------------------------------------------------
# #117 hotfix: _collect_gpu_metrics() multi-GPU parser tests
# ---------------------------------------------------------------------------

_BASELINE_JSON_PATH = (
    "data/contracts/nvidia-smi-watchloop/2026-05-26T02-23-36Z.json"
)


def _make_completed_process(stdout, returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_collect_gpu_metrics_multi_gpu_uses_first_row():
    """#117: dual-GPU stdout must parse first row only; gpu_power_w must not crash."""
    from src.monitoring.system_metrics import _collect_gpu_metrics

    dual_gpu_stdout = "1, 2817, 24576, 67, 91.65\n0, 93, 12288, 57, 8.31\n"
    with mock.patch("subprocess.run", return_value=_make_completed_process(dual_gpu_stdout)):
        result = _collect_gpu_metrics()

    assert result["gpu_util_pct"] == 1.0
    assert result["gpu_vram_used_mb"] == 2817.0
    assert result["gpu_vram_total_mb"] == 24576.0
    assert result["gpu_temp_c"] == 67.0
    assert result["gpu_power_w"] == 91.65


def test_collect_gpu_metrics_single_gpu_unchanged():
    """#117: single-GPU stdout must still parse correctly (regression guard)."""
    from src.monitoring.system_metrics import _collect_gpu_metrics

    single_gpu_stdout = "42, 4096, 24576, 58, 175.30\n"
    with mock.patch("subprocess.run", return_value=_make_completed_process(single_gpu_stdout)):
        result = _collect_gpu_metrics()

    assert result["gpu_util_pct"] == 42.0
    assert result["gpu_vram_used_mb"] == 4096.0
    assert result["gpu_vram_total_mb"] == 24576.0
    assert result["gpu_temp_c"] == 58.0
    assert result["gpu_power_w"] == 175.30


def test_collect_gpu_metrics_value_error_returns_none_with_warning():
    """#117: malformed stdout must return _gpu_none() AND log a warning (visible parse drift)."""
    from src.monitoring.system_metrics import _collect_gpu_metrics

    malformed_stdout = "not_a_number, 4096, 24576, 58, 175.30\n"
    with mock.patch("subprocess.run", return_value=_make_completed_process(malformed_stdout)):
        with mock.patch("src.monitoring.system_metrics.logger") as mock_logger:
            result = _collect_gpu_metrics()

    assert result == {
        "gpu_util_pct": None,
        "gpu_vram_used_mb": None,
        "gpu_vram_total_mb": None,
        "gpu_temp_c": None,
        "gpu_power_w": None,
    }
    mock_logger.warning.assert_called_once()


def test_collect_gpu_metrics_committed_baseline_matches():
    """#117 regression-lock: verbatim stdout from the committed ContractCheck baseline
    must parse to non-None values for all 5 keys after the hotfix."""
    from src.monitoring.system_metrics import _collect_gpu_metrics

    with open(_BASELINE_JSON_PATH, encoding="utf-8") as fh:
        baseline = json.load(fh)

    baseline_stdout = baseline["stdout"]
    with mock.patch("subprocess.run", return_value=_make_completed_process(baseline_stdout)):
        result = _collect_gpu_metrics()

    assert result["gpu_util_pct"] is not None
    assert result["gpu_vram_used_mb"] is not None
    assert result["gpu_vram_total_mb"] is not None
    assert result["gpu_temp_c"] is not None
    assert result["gpu_power_w"] is not None


# ---------------------------------------------------------------------------
# Test helper
# ---------------------------------------------------------------------------


class _NoCloseConn:
    """Pass-through wrapper that suppresses close() so the fixture owns lifecycle.

    `_store_snapshot` uses `with connect_db(db_path) as conn:` which on SQLite
    invokes `__exit__` -> conn.close(). The test fixture must own the
    connection lifecycle so we can SELECT from it after the upsert.
    On the PG path, the wrapper's __exit__ commits/closes the wrapped conn.
    """

    def __init__(self, inner):
        self._inner = inner

    def __enter__(self):
        return self._inner

    def __exit__(self, *args):
        # Commit so the fixture can SELECT the upserted row, but don't close.
        try:
            self._inner.commit()
        except Exception:
            pass
        return False

    def __getattr__(self, name):
        return getattr(self._inner, name)
