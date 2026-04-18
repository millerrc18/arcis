"""Tests for desk routing in reconcile_paper_trades / reconcile_live_trades.

CRITICAL per Sprint 4 plan (Issue A): reconcile is ACTIVE code called
from 4 scheduler paths. Incorrect desk routing causes research positions
to be polled from swing Alpaca (404 silent drop) or worse, swing positions
polled from research Alpaca.
"""
import sqlite3
from unittest.mock import patch

import pytest

from src.journal.store import initialize_database, insert_shadow_trade


@pytest.fixture
def tmp_db_with_mixed_desks(tmp_path):
    """Seed a test DB with 2 swing + 2 research_lazy_prices_v1 open positions."""
    db = str(tmp_path / "test.db")
    initialize_database(db)
    for i, (ticker, desk) in enumerate([
        ("AAPL", "swing"), ("MSFT", "swing"),
        ("NVDA", "research_lazy_prices_v1"),
        ("GOOGL", "research_lazy_prices_v1"),
    ]):
        insert_shadow_trade(
            {
                "trade_id": f"t{i}",
                "ticker": ticker,
                "planned_shares": 10,
                "entry_price": 100.0,
                "desk": desk,
                "source": "paper",
                "status": "open",
                "direction": "long",
                "created_at": "2026-04-01T09:30:00",
                "updated_at": "2026-04-01T09:30:00",
            },
            db,
        )
    return db


def test_reconcile_paper_trades_filters_by_desk(tmp_db_with_mixed_desks):
    """reconcile_paper_trades(desk='swing') should only process swing rows."""
    from src.shadow_trading.reconcile import reconcile_paper_trades
    with patch(
        "src.shadow_trading.reconcile.get_all_positions"
    ) as mock_positions, patch(
        "src.shadow_trading.reconcile.cancel_orders_for_ticker",
        return_value=0,
    ):
        mock_positions.return_value = []  # no open positions on Alpaca
        result = reconcile_paper_trades(
            desk="swing", dry_run=True, db_path=tmp_db_with_mixed_desks,
        )
    # The desk filter must have prevented research rows from being touched.
    assert result.get("desk") == "swing"
    # Only swing rows should be in local_count (2 swing rows seeded)
    assert result["local_count"] == 2


def test_reconcile_paper_trades_research_uses_research_client(
    tmp_db_with_mixed_desks,
):
    """CRITICAL: reconcile_paper_trades(desk='research_lazy_prices_v1') must
    route Alpaca queries through the research client."""
    from src.shadow_trading.reconcile import reconcile_paper_trades
    with patch(
        "src.shadow_trading.reconcile.get_all_positions"
    ) as mock_positions, patch(
        "src.shadow_trading.reconcile.cancel_orders_for_ticker",
        return_value=0,
    ):
        mock_positions.return_value = []
        result = reconcile_paper_trades(
            desk="research_lazy_prices_v1", dry_run=True,
            db_path=tmp_db_with_mixed_desks,
        )
    # Must have called get_all_positions with desk='research_lazy_prices_v1'
    assert mock_positions.called
    for call in mock_positions.call_args_list:
        called_desk = (
            call.kwargs.get("desk")
            or (call.args[0] if call.args else None)
        )
        assert called_desk == "research_lazy_prices_v1", (
            f"reconcile routed research-desk query through desk={called_desk!r} "
            "— would silently 404 the position on swing Alpaca"
        )
    # Only research rows in local_count (2 research rows seeded)
    assert result.get("desk") == "research_lazy_prices_v1"
    assert result["local_count"] == 2


def test_reconcile_default_desk_swing_backward_compat(tmp_db_with_mixed_desks):
    """reconcile_paper_trades() with no desk kwarg defaults to swing."""
    from src.shadow_trading.reconcile import reconcile_paper_trades
    with patch(
        "src.shadow_trading.reconcile.get_all_positions", return_value=[],
    ) as mock_positions, patch(
        "src.shadow_trading.reconcile.cancel_orders_for_ticker",
        return_value=0,
    ):
        result = reconcile_paper_trades(
            dry_run=True, db_path=tmp_db_with_mixed_desks,
        )
    # Default behavior unchanged: only swing desk touched.
    assert result.get("desk") == "swing"
    for call in mock_positions.call_args_list:
        called_desk = (
            call.kwargs.get("desk")
            or (call.args[0] if call.args else None)
        )
        assert called_desk in ("swing", None)


def test_reconcile_live_trades_rejects_research_desk():
    """Live is swing-only (parallel to place_live_entry guardrail).
    Research-desk live reconcile must raise ValueError."""
    from src.shadow_trading.reconcile import reconcile_live_trades
    with pytest.raises(ValueError, match="live"):
        reconcile_live_trades(desk="research_lazy_prices_v1", dry_run=True)


def test_reconcile_live_trades_accepts_swing_desk(tmp_db_with_mixed_desks):
    """reconcile_live_trades(desk='swing') proceeds normally.

    Must use the tmp_db fixture — without db_path, falls through to the
    module-level DB_PATH default, which resolves to a real file on
    developer machines (who ran prior backtests) but NOT on clean CI,
    causing `sqlite3.OperationalError: no such table: shadow_trades`.
    """
    from src.shadow_trading.reconcile import reconcile_live_trades
    with patch(
        "src.shadow_trading.reconcile.get_live_positions", return_value=[],
    ), patch(
        "src.shadow_trading.alpaca_adapter.get_live_positions", return_value=[],
    ):
        # Should not raise
        result = reconcile_live_trades(
            desk="swing", dry_run=True, db_path=tmp_db_with_mixed_desks,
        )
    assert result.get("desk") == "swing"
