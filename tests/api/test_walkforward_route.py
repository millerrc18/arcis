"""Tests for T10 — gate_version + excess_sharpe_min_used in GET run response."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from src.api.cloud_routes.walkforward import get_run, list_runs
from src.schema.sqlite import create_all_tables


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "wf_t10.sqlite3"
    create_all_tables(str(db))
    monkeypatch.setenv("ARCIS_DB_PATH", str(db))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("src.api.cloud_routes.walkforward.DB_PATH", str(db))
    return str(db)


def _seed_run_with_gate(
    db_path: str,
    run_id: str,
    gate_version: str,
    excess_sharpe_min_used: float | None,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO walkforward_results ("
        "run_id, strategy_id, spec_hash, random_seed, outcome_state, "
        "reason, pooled_sharpe, pooled_mde, heavy_tail_flag, "
        "heavy_tail_window_count, n_windows, n_windows_pass, "
        "n_windows_fail, n_windows_inconclusive_data, "
        "n_windows_inconclusive_power, derived_from_source_type, "
        "effective_universe_size, max_drawdown_pct, vix_tier_coverage, "
        "gate_version, excess_sharpe_min_used, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?, ?, ?, ?, ?)",
        (run_id, "s1", "hash_" + run_id, 42, "PASS", "walkforward_pass",
         0.55, 0.25, 0, 0, 5, 4, 0, 1, 0, None, 95, 0.10, 3,
         gate_version, excess_sharpe_min_used,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_walkforward_route_includes_gate_version(tmp_db):
    _seed_run_with_gate(tmp_db, "r_t10_gv", "v2", None)
    run = await get_run("r_t10_gv")
    assert "gate_version" in run
    assert run["gate_version"] == "v2"


@pytest.mark.asyncio
async def test_walkforward_route_includes_excess_sharpe_min_used(tmp_db):
    _seed_run_with_gate(tmp_db, "r_t10_esm", "v1", 0.35)
    run = await get_run("r_t10_esm")
    assert "excess_sharpe_min_used" in run
    assert run["excess_sharpe_min_used"] == pytest.approx(0.35)


@pytest.mark.asyncio
async def test_walkforward_route_excess_sharpe_min_used_nullable(tmp_db):
    _seed_run_with_gate(tmp_db, "r_t10_null", "v1", None)
    run = await get_run("r_t10_null")
    assert "excess_sharpe_min_used" in run
    assert run["excess_sharpe_min_used"] is None


@pytest.mark.asyncio
async def test_list_runs_includes_gate_version_and_excess_sharpe_min_used(tmp_db):
    """Sibling-search lock (PM review of PR #1097): list_runs uses an explicit
    column projection (not SELECT *), so the new T4 columns must be in the
    projection or the list endpoint silently drops them. Pins both columns
    surface in the list response just like the single-row GET.
    """
    _seed_run_with_gate(tmp_db, "r_t10_list_a", "v2", 0.4)
    _seed_run_with_gate(tmp_db, "r_t10_list_b", "v1", None)
    result = await list_runs(limit=50, strategy_id=None, outcome_state=None)
    assert result["count"] == 2
    rows_by_id = {r["run_id"]: r for r in result["runs"]}
    assert "gate_version" in rows_by_id["r_t10_list_a"]
    assert rows_by_id["r_t10_list_a"]["gate_version"] == "v2"
    assert rows_by_id["r_t10_list_a"]["excess_sharpe_min_used"] == pytest.approx(0.4)
    assert rows_by_id["r_t10_list_b"]["gate_version"] == "v1"
    assert rows_by_id["r_t10_list_b"]["excess_sharpe_min_used"] is None
