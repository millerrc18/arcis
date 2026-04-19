"""Tests for /api/walkforward/* routes."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from src.api.cloud_routes.walkforward import (
    get_run,
    get_run_trades,
    get_run_windows,
    list_runs,
)
from src.schema.sqlite import create_all_tables


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Fresh SQLite DB, wired via ARCIS_DB_PATH env var."""
    db = tmp_path / "wf_api.sqlite3"
    create_all_tables(str(db))
    monkeypatch.setenv("ARCIS_DB_PATH", str(db))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Force re-import of DB_PATH to pick up env override (the cached constant
    # was set at src.config import time; tests re-bind it directly).
    monkeypatch.setattr("src.api.cloud_routes.walkforward.DB_PATH", str(db))
    return str(db)


def _seed_run(
    db_path: str, run_id: str, strategy_id: str,
    outcome_state: str, reason: str, pooled_sharpe: float = 0.5,
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
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?, ?, ?)",
        (run_id, strategy_id, "hash_" + run_id, 42, outcome_state, reason,
         pooled_sharpe, 0.25, 0, 0, 5, 4, 0, 1, 0, None, 95, 0.10, 3,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def _seed_trade(
    db_path: str, trade_id: str, run_id: str, window_index: int,
    *, is_in_is_window: int = 0, vix_tier: str = "medium",
    sharpe_observed: float = 0.45,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO walkforward_trades ("
        "trade_id, run_id, window_index, is_in_is_window, ticker, "
        "entry_date, pnl_pct, vix_tier, sharpe_observed, bootstrap_se, "
        "mde_value) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (trade_id, run_id, window_index, is_in_is_window, "AAPL",
         "2020-01-15", 0.01, vix_tier, sharpe_observed, 0.30, 0.25),
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_list_runs_empty(tmp_db):
    result = await list_runs(limit=50, strategy_id=None, outcome_state=None)
    assert result == {"runs": [], "count": 0}


@pytest.mark.asyncio
async def test_list_runs_returns_three_state_outcomes(tmp_db):
    _seed_run(tmp_db, "r1", "s1", "PASS", "walkforward_pass")
    _seed_run(tmp_db, "r2", "s1", "INCONCLUSIVE", "power_inconclusive")
    _seed_run(tmp_db, "r3", "s2", "FAIL", "criterion_4_drawdown")
    result = await list_runs(limit=50, strategy_id=None, outcome_state=None)
    assert result["count"] == 3
    states = {r["outcome_state"] for r in result["runs"]}
    assert states == {"PASS", "FAIL", "INCONCLUSIVE"}


@pytest.mark.asyncio
async def test_list_runs_filters_by_outcome_state(tmp_db):
    _seed_run(tmp_db, "r1", "s1", "PASS", "walkforward_pass")
    _seed_run(tmp_db, "r2", "s1", "INCONCLUSIVE", "coverage_inconclusive")
    result = await list_runs(
        limit=50, strategy_id=None, outcome_state="INCONCLUSIVE",
    )
    assert result["count"] == 1
    assert result["runs"][0]["outcome_state"] == "INCONCLUSIVE"


@pytest.mark.asyncio
async def test_list_runs_filters_by_strategy_id(tmp_db):
    _seed_run(tmp_db, "r1", "s1", "PASS", "walkforward_pass")
    _seed_run(tmp_db, "r2", "s2", "FAIL", "criterion_4_drawdown")
    result = await list_runs(
        limit=50, strategy_id="s2", outcome_state=None,
    )
    assert result["count"] == 1
    assert result["runs"][0]["strategy_id"] == "s2"


@pytest.mark.asyncio
async def test_get_run_returns_full_shape(tmp_db):
    _seed_run(tmp_db, "r1", "s1", "PASS", "walkforward_pass", pooled_sharpe=0.7)
    run = await get_run("r1")
    assert run["run_id"] == "r1"
    assert run["outcome_state"] == "PASS"
    assert run["reason"] == "walkforward_pass"
    assert run["pooled_sharpe"] == 0.7


@pytest.mark.asyncio
async def test_get_run_404_when_missing(tmp_db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await get_run("nope")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_run_windows_aggregates(tmp_db):
    _seed_run(tmp_db, "r1", "s1", "PASS", "walkforward_pass")
    _seed_trade(tmp_db, "t1", "r1", 0, vix_tier="low")
    _seed_trade(tmp_db, "t2", "r1", 0, vix_tier="medium")
    _seed_trade(tmp_db, "t3", "r1", 1, vix_tier="high")
    result = await get_run_windows("r1")
    assert result["run_id"] == "r1"
    assert result["outcome_state"] == "PASS"
    windows_by_idx = {w["window_index"]: w for w in result["windows"]}
    assert windows_by_idx[0]["n_trades"] == 2
    assert windows_by_idx[0]["distinct_vix_tiers"] == 2
    assert windows_by_idx[1]["n_trades"] == 1


@pytest.mark.asyncio
async def test_get_run_trades_filters_window_index(tmp_db):
    _seed_run(tmp_db, "r1", "s1", "PASS", "walkforward_pass")
    _seed_trade(tmp_db, "t1", "r1", 0)
    _seed_trade(tmp_db, "t2", "r1", 1)
    result = await get_run_trades("r1", window_index=0, limit=500)
    assert result["count"] == 1
    assert result["trades"][0]["window_index"] == 0


@pytest.mark.asyncio
async def test_get_run_trades_excludes_is_trades(tmp_db):
    _seed_run(tmp_db, "r1", "s1", "PASS", "walkforward_pass")
    _seed_trade(tmp_db, "t1", "r1", 0, is_in_is_window=0)
    _seed_trade(tmp_db, "t2", "r1", 0, is_in_is_window=1)  # IS side
    result = await get_run_trades("r1", window_index=None, limit=500)
    assert result["count"] == 1
    assert result["trades"][0]["trade_id"] == "t1"


@pytest.mark.asyncio
async def test_get_run_windows_404_when_run_missing(tmp_db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await get_run_windows("nope")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_run_trades_404_when_run_missing(tmp_db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await get_run_trades("nope", window_index=0, limit=100)
    assert exc.value.status_code == 404
