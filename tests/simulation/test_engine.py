"""Parametrized dual-engine tests for src/simulation/engine.store_result.

Sprint 5 §J5/§J6 Phase 1 T1.14 — migrate `INSERT OR REPLACE INTO
simulation_results ...` at src/simulation/engine.py:504 → engine_aware_upsert.

T0.12 audit (replace-semantics-audit.md §5.6) classified simulation_results
as `in_place_update` (no incoming FKs, no triggers, no rowid readers; UUID-
per-call PK means the REPLACE branch never actually fires in production —
every call is functionally an INSERT). This test pins the in-place-update
behavior by deterministically supplying the same `result_id` PK across two
inserts and asserting the second updates rather than duplicates.

Parametrized over [sqlite, postgres] via `parametrized_conn` fixture (T0.9).
PG variant skips cleanly when TEST_DATABASE_URL is unset.
"""

import sqlite3

import pytest


def _build_result(scenario: str = "strong_bull",
                  total_trades: int = 45,
                  verdict: str = "edge") -> dict:
    """Construct a minimal simulation result dict for store_result()."""
    return {
        "scenario": scenario,
        "regime_label": "Strong Bull",
        "start_date": "2017-01-01",
        "end_date": "2017-12-31",
        "total_trades": total_trades,
        "wins": 30,
        "losses": 10,
        "timeouts": 5,
        "win_rate": 0.667,
        "profit_factor": 1.5,
        "total_pnl_pct": 12.5,
        "gross_pnl_pct": 13.0,
        "net_pnl_pct": 12.5,
        "max_drawdown_pct": -5.5,
        "sharpe_ratio": 1.2,
        "calmar_ratio": 2.3,
        "benchmark_pnl_pct": 8.0,
        "excess_return_pct": 4.5,
        "transaction_cost_bps": 9.0,
        "tl_states": ["GREEN", "GREEN", "GREEN"],
        "monthly_returns": {"2017-01": 1.5},
        "equity_curve": [100000, 101500],
        "regime_breakdown": {"normal": {"trades": total_trades}},
        "model_version": "mechanical_brackets",
        "verdict": verdict,
        "survivorship_bias": True,
    }


def _count_rows(conn, table: str) -> int:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
    row = cur.fetchone()
    if hasattr(row, "keys") and "c" in row.keys():
        return row["c"]
    return row[0]


def _select_by_result_id(conn, result_id: str):
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM simulation_results WHERE result_id=?", (result_id,)
    )
    return cur.fetchone()


def test_store_result_uses_engine_aware_upsert_on_both_engines(
    parametrized_conn, monkeypatch
):
    """T1.14: store_result must dedup via engine_aware_upsert on both engines.

    Inserts twice with the same deterministic `result_id` PK and verifies
    the second call updates the row rather than duplicating it. This
    exercises:
        - SQLite path: INSERT OR REPLACE (in_place_update semantic)
        - PG path: INSERT ... ON CONFLICT (result_id) DO UPDATE SET ...

    Because `store_result` generates `str(uuid.uuid4())` internally, the
    test monkeypatches `uuid.uuid4` to a fixed value so both calls hit the
    same PK and the replace branch actually fires.
    """
    from src.simulation import engine as sim_engine

    conn = parametrized_conn

    # Phase 1 helper: bootstrap simulation_results table on SQLite. On PG,
    # parametrized_conn (pg_wrapper) already created it via generate_create_sql.
    if isinstance(conn, sqlite3.Connection):
        # tmp_path-backed init_test_db already created the schema; just verify
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='simulation_results'"
        )
        assert cur.fetchone() is not None, (
            "simulation_results not bootstrapped on SQLite conn"
        )

    # Monkeypatch store_result internals so:
    #   - `connect_db(db_path)` returns the test fixture conn (with no-op
    #     close + commit, since the fixture owns the lifecycle)
    #   - `uuid.uuid4()` returns a deterministic value so two calls share PK
    class _ConnGuard:
        """Pass-through context manager that does not close the underlying conn.

        store_result uses `with connect_db(db_path) as conn:`, which would
        close the fixture-owned connection on __exit__. We wrap so __exit__
        is a no-op (the fixture is responsible for teardown).
        """

        def __init__(self, inner):
            self._inner = inner

        def __enter__(self):
            return self._inner

        def __exit__(self, exc_type, exc_val, exc_tb):
            # Don't close; fixture owns lifecycle. Commit on success.
            if exc_type is None:
                self._inner.commit()
            return False

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(
        "src.simulation.engine.connect_db",
        lambda _path: _ConnGuard(conn),
    )

    fixed_uuid = "test-fixed-uuid-deterministic-pk"

    class _FixedUUID:
        def __str__(self):
            return fixed_uuid

    monkeypatch.setattr(
        "src.simulation.engine.uuid.uuid4", lambda: _FixedUUID()
    )

    # First insert
    sim_engine.store_result(
        result=_build_result(total_trades=45, verdict="edge"),
        run_id="test-run-1",
        seed=42,
        config={"foo": "bar"},
        db_path="ignored",
    )
    assert _count_rows(conn, "simulation_results") == 1, (
        "first store_result should insert one row"
    )
    fetched = _select_by_result_id(conn, fixed_uuid)
    assert fetched is not None
    assert fetched["total_trades"] == 45
    assert fetched["verdict"] == "edge"

    # Second insert with SAME result_id (PK) but different payload — must
    # update in-place, not duplicate.
    sim_engine.store_result(
        result=_build_result(total_trades=99, verdict="bleeds"),
        run_id="test-run-2",
        seed=43,
        config={"foo": "baz"},
        db_path="ignored",
    )
    assert _count_rows(conn, "simulation_results") == 1, (
        "second store_result with same PK should REPLACE/UPDATE, not duplicate"
    )
    updated = _select_by_result_id(conn, fixed_uuid)
    assert updated is not None
    assert updated["total_trades"] == 99
    assert updated["verdict"] == "bleeds"
    assert updated["run_id"] == "test-run-2"


def test_store_result_no_literal_insert_or_replace_in_source():
    """T1.14 lock-in: simulation/engine.py must not contain `INSERT OR REPLACE`.

    Pins the migration to engine_aware_upsert so a future refactor cannot
    silently regress to a literal SQLite-only statement. The wrapper is the
    only sanctioned upsert path post-T1.14 (Modified-A migration).
    """
    from pathlib import Path

    engine_path = (
        Path(__file__).resolve().parents[2] / "src" / "simulation" / "engine.py"
    )
    source = engine_path.read_text(encoding="utf-8")
    assert "INSERT OR REPLACE" not in source, (
        "src/simulation/engine.py must not contain literal `INSERT OR REPLACE` "
        "after T1.14 migration; use engine_aware_upsert(action='replace') "
        "via src.utils.db instead."
    )
