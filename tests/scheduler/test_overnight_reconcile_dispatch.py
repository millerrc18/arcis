"""Test that the scheduler reconcile dispatch iterates swing + every
active research strategy. Task 7d non-negotiable gate."""
import sqlite3
from unittest.mock import patch


def test_reconcile_all_paper_trades_dispatches_swing_plus_active_research(tmp_path):
    """When 2 strategies are in shadow_trading state, reconcile dispatch
    should invoke reconcile_paper_trades 3x: swing + research_A + research_B."""
    db = str(tmp_path / "test.db")
    from src.schema.sqlite import create_all_tables
    from src.platform.promotion import register_strategy
    create_all_tables(db)
    register_strategy(
        "strat_a", "A", "test", spec_hash="x", db_path=db,
    )
    register_strategy(
        "strat_b", "B", "test", spec_hash="y", db_path=db,
    )
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE strategy_registry SET current_status='shadow_trading' "
        "WHERE strategy_id IN ('strat_a','strat_b')",
    )
    conn.commit()
    conn.close()

    with patch(
        "src.shadow_trading.reconcile_dispatch.reconcile_paper_trades"
    ) as mock_recon:
        mock_recon.return_value = {"status": "ok"}
        from src.shadow_trading.reconcile_dispatch import reconcile_all_paper_trades
        results = reconcile_all_paper_trades(db_path=db, dry_run=True)

    # Should have been called 3 times: swing + strat_a + strat_b
    assert mock_recon.call_count == 3
    desks_called = [
        call.kwargs.get("desk") for call in mock_recon.call_args_list
    ]
    assert "swing" in desks_called
    assert "research_strat_a" in desks_called
    assert "research_strat_b" in desks_called
    assert set(results.keys()) == {"swing", "research_strat_a", "research_strat_b"}


def test_reconcile_all_isolates_per_desk_failures(tmp_path):
    """If research_strat_a's reconcile raises, swing + research_strat_b
    should still complete."""
    db = str(tmp_path / "test.db")
    from src.schema.sqlite import create_all_tables
    from src.platform.promotion import register_strategy
    create_all_tables(db)
    register_strategy("strat_a", "A", "test", "x", db_path=db)
    register_strategy("strat_b", "B", "test", "y", db_path=db)
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE strategy_registry SET current_status='shadow_trading'"
    )
    conn.commit()
    conn.close()

    def side_effect(desk, **kwargs):
        if desk == "research_strat_a":
            raise RuntimeError("strat_a API down")
        return {"status": "ok", "desk": desk}

    with patch(
        "src.shadow_trading.reconcile_dispatch.reconcile_paper_trades",
        side_effect=side_effect,
    ):
        from src.shadow_trading.reconcile_dispatch import reconcile_all_paper_trades
        results = reconcile_all_paper_trades(db_path=db, dry_run=True)

    # Even with one failure, the other two desks completed
    assert results["swing"]["status"] == "ok"
    assert "error" in results["research_strat_a"]
    assert "strat_a API down" in results["research_strat_a"]["error"]
    assert results["research_strat_b"]["status"] == "ok"


def test_reconcile_all_zero_active_strategies_only_reconciles_swing(tmp_path):
    """No strategies in shadow_trading state → only swing reconciled."""
    db = str(tmp_path / "test.db")
    from src.schema.sqlite import create_all_tables
    create_all_tables(db)

    with patch(
        "src.shadow_trading.reconcile_dispatch.reconcile_paper_trades"
    ) as mock_recon:
        mock_recon.return_value = {"status": "ok"}
        from src.shadow_trading.reconcile_dispatch import reconcile_all_paper_trades
        results = reconcile_all_paper_trades(db_path=db, dry_run=True)

    assert mock_recon.call_count == 1
    assert mock_recon.call_args.kwargs.get("desk") == "swing"
    assert set(results.keys()) == {"swing"}
