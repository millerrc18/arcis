"""Tests for WatchLoop._run_platform_shadow_tick (Sprint 4 Task 9).

Non-negotiable gates:
  - test_platform_tick_respects_cadence
  - test_platform_tick_runs_each_strategy_independently
  - test_platform_tick_failure_does_not_kill_swing
"""
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


def _make_watch_loop_with_platform_init(db_path: str):
    """Construct a WatchLoop instance bypassing __init__'s heavy setup,
    then manually init the platform-tick state."""
    from src.scheduler.watch import WatchLoop
    wl = WatchLoop.__new__(WatchLoop)
    wl._last_platform_tick = {}
    wl._db_path = db_path
    return wl


def _seed_active_research_strategy(db_path: str, strategy_id: str) -> None:
    """Register + promote a strategy to shadow_trading status (test shortcut)."""
    from src.platform.promotion import register_strategy
    register_strategy(
        strategy_id, strategy_id.upper(), f"yaml:test/{strategy_id}",
        spec_hash="hashtest", db_path=db_path,
    )
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE strategy_registry SET current_status='shadow_trading' "
        "WHERE strategy_id = ?",
        (strategy_id,),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def tmp_db(tmp_path):
    from src.schema.sqlite import create_all_tables
    db = tmp_path / "test.db"
    create_all_tables(str(db))
    return str(db)


def test_platform_tick_respects_cadence(tmp_db):
    """cadence=600s; last tick 300s ago -> skip; last tick 700s ago -> run."""
    _seed_active_research_strategy(tmp_db, "strat_a")
    wl = _make_watch_loop_with_platform_init(tmp_db)

    fake_spec = MagicMock()
    fake_spec.raw = {"shadow_cadence_seconds": 600}

    with patch(
        "src.platform.strategy_spec.load_spec", return_value=fake_spec,
    ), patch(
        "src.platform.shadow_harness.ShadowHarness"
    ) as mock_harness_cls:
        mock_harness = MagicMock()
        mock_harness.run_one_tick.return_value = {"n_new_positions": 0}
        mock_harness_cls.return_value = mock_harness

        # First tick: no prior — should run
        wl._run_platform_shadow_tick()
        assert mock_harness.run_one_tick.call_count == 1

        # Second tick 300s later: cadence not elapsed — should skip
        wl._last_platform_tick["strat_a"] = datetime.now() - timedelta(seconds=300)
        wl._run_platform_shadow_tick()
        assert mock_harness.run_one_tick.call_count == 1

        # Third tick 700s later: cadence elapsed — should run
        wl._last_platform_tick["strat_a"] = datetime.now() - timedelta(seconds=700)
        wl._run_platform_shadow_tick()
        assert mock_harness.run_one_tick.call_count == 2


def test_platform_tick_runs_each_strategy_independently(tmp_db):
    """Two strategies in shadow_trading -> each is ticked with its own harness."""
    _seed_active_research_strategy(tmp_db, "strat_a")
    _seed_active_research_strategy(tmp_db, "strat_b")
    wl = _make_watch_loop_with_platform_init(tmp_db)

    fake_spec = MagicMock()
    fake_spec.raw = {"shadow_cadence_seconds": 60}

    with patch(
        "src.platform.strategy_spec.load_spec", return_value=fake_spec,
    ), patch(
        "src.platform.shadow_harness.ShadowHarness",
    ) as mock_cls:
        mock_cls.return_value = MagicMock(
            run_one_tick=MagicMock(return_value={"n_new_positions": 0}),
        )
        wl._run_platform_shadow_tick()
    # Two strategies -> two harness instantiations
    assert mock_cls.call_count == 2


def test_platform_tick_failure_does_not_kill_swing(tmp_db):
    """If one strategy's tick raises, _run_platform_shadow_tick must not
    propagate — swing continues."""
    _seed_active_research_strategy(tmp_db, "crash")
    wl = _make_watch_loop_with_platform_init(tmp_db)

    fake_spec = MagicMock()
    fake_spec.raw = {"shadow_cadence_seconds": 60}

    with patch(
        "src.platform.strategy_spec.load_spec", return_value=fake_spec,
    ), patch(
        "src.platform.shadow_harness.ShadowHarness",
    ) as mock_cls:
        mock_cls.return_value = MagicMock(
            run_one_tick=MagicMock(side_effect=RuntimeError("harness crash")),
        )
        # Must not raise
        wl._run_platform_shadow_tick()
    # The tick was recorded even though it crashed — prevents infinite
    # retry loop on a deterministic failure
    assert "crash" in wl._last_platform_tick


def test_platform_tick_zero_active_strategies_is_noop(tmp_db):
    """Empty strategy_registry -> no harness construction, no errors."""
    wl = _make_watch_loop_with_platform_init(tmp_db)
    with patch(
        "src.platform.shadow_harness.ShadowHarness",
    ) as mock_cls:
        wl._run_platform_shadow_tick()
    mock_cls.assert_not_called()
