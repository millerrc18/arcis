"""Tests for src.platform.shadow_harness — live shadow-trading harness.

NON-NEGOTIABLE gates (Sprint 4 plan):
  - test_harness_reconcile_uses_research_client
  - test_harness_bracket_monitor_uses_research_client
  - ShadowHarness.halt() closes only this strategy's positions
  - verify_accounts_distinct called at startup
"""
import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.platform.shadow_harness import ShadowHarness
from src.platform.strategy_spec import StrategySpec


def _test_spec(strategy_id: str = "test_strat") -> StrategySpec:
    return StrategySpec(
        strategy_id=strategy_id,
        display_name=strategy_id.upper(),
        universe={"tickers": "sp100"},
        entry={"kind": "scheduled", "day_of_week": "Monday", "time": "close"},
        exit={
            "kind": "mechanical", "timeout_days": 21,
            "stop": {"method": "pct", "value": 0.02},
            "target": {"method": "pct", "value": 0.03},
        },
        position_sizing={"method": "fixed_pct_equity", "pct": 0.15,
                         "max_concurrent": 5},
        attribution={"benchmark": "SPY_matched_window",
                     "metrics": ["sharpe"]},
        raw={"shadow_cadence_seconds": 600},
        source="test",
    )


@pytest.fixture
def tmp_db(tmp_path):
    db = tmp_path / "test.db"
    from src.schema.sqlite import create_all_tables
    create_all_tables(str(db))
    return str(db)


@pytest.fixture
def harness_with_verify_mocked(tmp_db):
    """Construct a ShadowHarness where verify_accounts_distinct is mocked
    to a no-op (for tests that don't specifically verify its invocation)."""
    spec = _test_spec("test_strat_default")
    with patch(
        "src.platform.shadow_harness.verify_accounts_distinct",
    ):
        yield ShadowHarness(spec, db_path=tmp_db)


def test_harness_writes_shadow_trade_with_correct_desk_tag(tmp_db):
    """New trades must land at desk='research_<strategy_id>'."""
    spec = _test_spec("strat_a")
    with patch("src.platform.shadow_harness.verify_accounts_distinct"):
        harness = ShadowHarness(spec, db_path=tmp_db)
    fake_cands = [
        {"ticker": "AAPL", "as_of": "2026-04-17T10:00:00",
         "signal_strength": 0.9, "metadata": {},
         "shares": 10, "price": 100.0},
    ]
    with patch(
        "src.platform.shadow_harness.place_bracket_order"
    ) as mock_place, patch.object(
        harness, "_find_candidates", return_value=fake_cands,
    ), patch.object(
        harness, "_is_within_hard_limits", return_value=(True, None),
    ):
        mock_place.return_value = {
            "order_id": "O1", "entry_price": 100.0, "shares": 10,
        }
        result = harness.run_one_tick(as_of=datetime(2026, 4, 17, 10, 0))

    assert result["n_new_positions"] == 1
    # Verify shadow_trades row has the right desk
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT desk FROM shadow_trades WHERE ticker = 'AAPL'"
    ).fetchone()
    conn.close()
    assert row["desk"] == "research_strat_a"


def test_harness_reconcile_uses_research_client(tmp_db):
    """NON-NEGOTIABLE: harness.run_one_tick, when it invokes reconcile
    (for its own open positions), must pass desk='research_<id>'."""
    spec = _test_spec("strat_b")
    with patch("src.platform.shadow_harness.verify_accounts_distinct"):
        harness = ShadowHarness(spec, db_path=tmp_db)
    with patch(
        "src.platform.shadow_harness.reconcile_paper_trades"
    ) as mock_recon:
        mock_recon.return_value = {"status": "ok"}
        harness._reconcile_open_positions()
    assert mock_recon.called
    for call in mock_recon.call_args_list:
        assert call.kwargs.get("desk") == "research_strat_b"


def test_harness_bracket_monitor_uses_research_client(tmp_db):
    """NON-NEGOTIABLE: if the harness polls bracket order status,
    it must use the research Alpaca client via desk kwarg."""
    spec = _test_spec("strat_c")
    with patch("src.platform.shadow_harness.verify_accounts_distinct"):
        harness = ShadowHarness(spec, db_path=tmp_db)
    with patch(
        "src.platform.shadow_harness.get_order_status"
    ) as mock_status:
        mock_status.return_value = {"status": "filled"}
        harness._poll_order_status("order_id_xyz")
    assert mock_status.called
    assert mock_status.call_args.kwargs.get("desk") == "research_strat_c"


def test_harness_halt_closes_only_this_strategy_positions(tmp_db):
    """ShadowHarness.halt() must close positions tagged with THIS
    strategy's desk, not swing and not other research strategies."""
    spec = _test_spec("strat_d")
    conn = sqlite3.connect(tmp_db)
    for i, (ticker, desk) in enumerate([
        ("AAPL", "swing"),
        ("MSFT", "research_strat_d"),
        ("NVDA", "research_other_strat"),
    ]):
        conn.execute(
            """INSERT INTO shadow_trades
               (trade_id, ticker, planned_shares, entry_price, desk,
                actual_entry_time, actual_exit_time, created_at, updated_at)
               VALUES (?, ?, 10, 100.0, ?, '2026-04-01', NULL,
                       '2026-04-01', '2026-04-01')""",
            (f"t{i}", ticker, desk),
        )
    conn.commit()
    conn.close()

    with patch("src.platform.shadow_harness.verify_accounts_distinct"):
        harness = ShadowHarness(spec, db_path=tmp_db)
    with patch(
        "src.platform.shadow_harness.place_paper_exit"
    ) as mock_exit, patch(
        "src.platform.shadow_harness.cancel_orders_for_ticker",
    ) as mock_cancel:
        mock_exit.return_value = {"status": "ok"}
        closed = harness.halt()
    # Must have closed MSFT only (the one desk='research_strat_d' open row)
    closed_tickers = [c["ticker"] for c in closed]
    assert closed_tickers == ["MSFT"]
    # exit function invoked with desk='research_strat_d'
    for call in mock_exit.call_args_list:
        assert call.kwargs.get("desk") == "research_strat_d"


def test_harness_verify_accounts_distinct_on_init(tmp_db):
    """ShadowHarness.__init__ should invoke verify_accounts_distinct."""
    spec = _test_spec("strat_e")
    with patch(
        "src.platform.shadow_harness.verify_accounts_distinct"
    ) as mock_verify:
        ShadowHarness(spec, db_path=tmp_db)
    assert mock_verify.called


def test_harness_get_open_positions_filters_by_strategy(tmp_db):
    """get_open_positions returns only this strategy's desk rows."""
    spec = _test_spec("strat_f")
    conn = sqlite3.connect(tmp_db)
    for i, (ticker, desk) in enumerate([
        ("AAPL", "swing"), ("MSFT", "research_strat_f"),
        ("NVDA", "research_strat_f"), ("GOOGL", "research_other"),
    ]):
        conn.execute(
            """INSERT INTO shadow_trades
               (trade_id, ticker, planned_shares, entry_price, desk,
                actual_entry_time, actual_exit_time, created_at, updated_at)
               VALUES (?, ?, 10, 100.0, ?, '2026-04-01', NULL,
                       '2026-04-01', '2026-04-01')""",
            (f"t{i}", ticker, desk),
        )
    conn.commit()
    conn.close()

    with patch("src.platform.shadow_harness.verify_accounts_distinct"):
        harness = ShadowHarness(spec, db_path=tmp_db)
    open_positions = harness.get_open_positions()
    tickers = {p["ticker"] for p in open_positions}
    assert tickers == {"MSFT", "NVDA"}
