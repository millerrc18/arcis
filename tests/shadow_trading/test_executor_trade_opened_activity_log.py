"""Regression-locks: open_shadow_trade MUST write a TRADE_OPENED row to
activity_log.

Sprint 0 / Wave 1c / EXEC-TRADEOPENED — DASHBOARD VISIBILITY BUG.

Pre-fix history: src/shadow_trading/executor.py:1217-1219 referenced two
local variables that were not in scope of `open_shadow_trade`:

    "shares": shares,                     # ← `shares` not defined
    "source": source_filter or "paper",   # ← `source_filter` is a
                                          #    parameter of a DIFFERENT
                                          #    function (check_and_manage_
                                          #    open_trades).

The local for share count is `planned_shares`. The whole block is wrapped
in `except Exception:` with DEBUG-level logging at the catch site, so the
NameError was silently swallowed every entry. Net effect: dashboard
"trades opened" feed had been blind since the commit shipped.

This test calls `open_shadow_trade` with a minimal valid trade dict +
mocks for the heavy guards (validator, risk governor, alpaca broker,
websocket broadcast) and asserts:
- Pre-fix: zero rows with event_type='trade_opened' (NameError swallowed).
- Post-fix: exactly one row with the correct trade_id / ticker / shares
  in the JSON payload.
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# #613 — log_activity refuses to write under pytest unless this env var is
# set. Our regression test is the legitimate consumer that asserts the
# write actually happens (the whole point of the fix).
@pytest.fixture(autouse=True)
def _opt_in_activity_writes(monkeypatch):
    monkeypatch.setenv("ARCIS_LOG_ACTIVITY_IN_PYTEST", "1")


def _make_test_db(tmp_path) -> str:
    """Create a test DB using the schema registry — includes activity_log."""
    db_path = str(tmp_path / "test_trade_opened.sqlite3")
    from src.journal.store import initialize_database
    initialize_database(db_path)
    # initialize_database creates shadow_trades + dependencies but not
    # activity_log; create that explicitly via the schema registry.
    from tests.conftest import init_test_db
    init_test_db(db_path, ["activity_log"])
    return db_path


def _make_packet(ticker: str = "TROPENED") -> SimpleNamespace:
    """Minimal TradePacket-shaped SimpleNamespace that satisfies executor."""
    ps = SimpleNamespace(
        allocation_dollars=1000.0,
        allocation_pct=1.0,
        estimated_risk_dollars=50.0,
        entry_price=100.0,
        stop_level=95.0,
        target_1=110.0,
        shares=10,
    )
    return SimpleNamespace(
        ticker=ticker,
        company_name="Test Corp",
        entry_zone="100.00",
        stop_invalidation="95.00",
        targets="110.00/120.00",
        position_sizing=ps,
        confidence=7.0,
        llm_conviction=8,
        setup_type="pullback",
        recommendation="Buy",
        deeper_analysis="Test thesis",
        expected_hold_period="5-7 days",
        event_risk="Normal",
        llm_timeout_days=15,
    )


def _make_config() -> dict:
    """Minimal config that lets a paper entry pass all upstream guards."""
    return {
        "shadow_trading": {"enabled": True, "max_positions": 10, "timeout_days": 15},
        "risk_governor": {"enabled": False},
        "risk": {"base_risk_pct": 1.0, "starting_capital": 100000},
        "bootcamp": {"enabled": False},
        "trading": {"ib_enabled": False},
        "live_trading": {},
        "strategies": {"pullback": {}},
    }


def test_open_shadow_trade_writes_TRADE_OPENED_to_activity_log(tmp_path, monkeypatch):
    """Regression lock: a successful paper entry MUST create exactly one
    activity_log row with event_type='trade_opened' and a JSON detail
    payload that contains the correct trade_id, ticker, shares, and source.

    Pre-fix this test fails with `count == 0` because the NameError
    on `shares` / `source_filter` was silently swallowed.
    """
    db_path = _make_test_db(tmp_path)
    ticker = "TROPENED"
    packet = _make_packet(ticker)
    config = _make_config()

    # NB: we do NOT monkeypatch activity_logger.DB_PATH. The executor now
    # explicitly forwards its `db_path` parameter to log_activity, and the
    # #647 guard refuses writes when db_path equals DB_PATH. Leaving DB_PATH
    # at its prod value plus passing the tmp path keeps the guard happy
    # (tmp path != DB_PATH and does not contain "ai_research_desk").

    mock_governor = MagicMock()
    mock_governor.check_trade.return_value = {
        "approved": True,
        "effective_allocation_dollars": 1000.0,
    }

    # Bracket order returns a successful fill so trade_data["status"]="open"
    # and the trade_id is non-None — both conditions are required for the
    # activity_log block to run.
    mock_bracket_resp = {
        "order_id": "alpaca-test-order-xyz",
        "filled_avg_price": 100.0,
    }

    from src.shadow_trading.executor import open_shadow_trade

    with patch("src.shadow_trading.executor.load_config", return_value=config), \
         patch("src.llm.validator.validate_llm_output", return_value=(True, "ok")), \
         patch("src.risk.governor.RiskGovernor", return_value=mock_governor), \
         patch("src.risk.governor.get_portfolio_state", return_value={}), \
         patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[]), \
         patch("src.shadow_trading.executor._enforce_position_cap", return_value=True), \
         patch("src.shadow_trading.executor._check_paper_buying_power", return_value=True), \
         patch("src.shadow_trading.executor._select_paper_broker",
               return_value=("alpaca", None)), \
         patch("src.shadow_trading.executor._verify_and_update", lambda *a, **kw: None), \
         patch("src.shadow_trading.alpaca_adapter.place_bracket_order",
               return_value=mock_bracket_resp), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]), \
         patch("src.api.websocket.broadcast_sync", lambda *a, **kw: None), \
         patch("src.shadow_trading.executor._check_open_milestones", lambda *a, **kw: None), \
         patch("src.shadow_trading.executor._check_sector_exposure", lambda *a, **kw: None):

        trade_id = open_shadow_trade(
            "rec-tropened-1",
            packet,
            {"strategy_type": "pullback"},
            db_path=db_path,
        )

    assert trade_id is not None, "Trade must have been opened"

    # Sanity: shadow_trades has the row.
    with sqlite3.connect(db_path) as conn:
        st_row = conn.execute(
            "SELECT trade_id, status, planned_shares FROM shadow_trades WHERE ticker = ?",
            (ticker,),
        ).fetchone()
    assert st_row is not None, "shadow_trades row must exist"
    assert st_row[1] == "open", f"Expected status=open, got {st_row[1]}"
    expected_planned_shares = st_row[2]

    # Core assertion: activity_log MUST have a TRADE_OPENED row.
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT event_type, detail FROM activity_log WHERE event_type = 'trade_opened'"
        ).fetchall()

    assert len(rows) == 1, (
        f"Expected exactly 1 activity_log row with event_type='trade_opened', got "
        f"{len(rows)}. Pre-fix this is 0 because NameError on `shares`/`source_filter` "
        f"was silently swallowed at DEBUG level. The dashboard 'trades opened' feed has "
        f"been blind since the commit shipped."
    )

    event_type, detail = rows[0]
    assert event_type == "trade_opened"

    # Detail is a JSON-stringified dict (no metadata, so plain JSON, not "text | json").
    payload = json.loads(detail)
    assert payload["trade_id"] == trade_id, (
        f"trade_id mismatch: expected {trade_id}, got {payload['trade_id']}"
    )
    assert payload["ticker"] == ticker, (
        f"ticker mismatch: expected {ticker}, got {payload['ticker']}"
    )
    assert payload["shares"] == expected_planned_shares, (
        f"shares mismatch: expected planned_shares={expected_planned_shares}, "
        f"got {payload['shares']} — pre-fix the key was sourced from undefined `shares` "
        f"variable; post-fix it must come from `planned_shares` local."
    )
    assert payload["source"] == "paper", (
        f"source mismatch: expected 'paper', got {payload['source']!r} — pre-fix the key "
        f"was sourced from undefined `source_filter` variable; post-fix it must come "
        f"from trade_data.get('source', 'paper')."
    )
    assert "entry_price" in payload, "entry_price must be in payload"


def test_activity_log_swallow_handler_logs_at_warning_level(tmp_path, monkeypatch, caplog):
    """The catch-block around the activity_log call must log at WARNING+,
    not DEBUG. Reasoning: the activity_log IS the observability mechanism;
    failures of observability infrastructure must not themselves be
    invisible. Pre-fix it was DEBUG, which is why the NameError went
    unnoticed.
    """
    import logging
    db_path = _make_test_db(tmp_path)
    ticker = "WLOG"
    packet = _make_packet(ticker)
    config = _make_config()

    # Force activity_logger.log_activity to raise so the catch block runs.
    def _boom(*args, **kwargs):
        raise RuntimeError("synthetic failure to test log level")

    monkeypatch.setattr("src.utils.activity_logger.log_activity", _boom)

    mock_governor = MagicMock()
    mock_governor.check_trade.return_value = {
        "approved": True,
        "effective_allocation_dollars": 1000.0,
    }

    from src.shadow_trading.executor import open_shadow_trade

    caplog.set_level(logging.DEBUG, logger="src.shadow_trading.executor")

    with patch("src.shadow_trading.executor.load_config", return_value=config), \
         patch("src.llm.validator.validate_llm_output", return_value=(True, "ok")), \
         patch("src.risk.governor.RiskGovernor", return_value=mock_governor), \
         patch("src.risk.governor.get_portfolio_state", return_value={}), \
         patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[]), \
         patch("src.shadow_trading.executor._enforce_position_cap", return_value=True), \
         patch("src.shadow_trading.executor._check_paper_buying_power", return_value=True), \
         patch("src.shadow_trading.executor._select_paper_broker",
               return_value=("alpaca", None)), \
         patch("src.shadow_trading.executor._verify_and_update", lambda *a, **kw: None), \
         patch("src.shadow_trading.alpaca_adapter.place_bracket_order",
               return_value={"order_id": "x", "filled_avg_price": 100.0}), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]), \
         patch("src.api.websocket.broadcast_sync", lambda *a, **kw: None), \
         patch("src.shadow_trading.executor._check_open_milestones", lambda *a, **kw: None), \
         patch("src.shadow_trading.executor._check_sector_exposure", lambda *a, **kw: None):

        open_shadow_trade(
            "rec-wlog-1",
            packet,
            {"strategy_type": "pullback"},
            db_path=db_path,
        )

    swallow_records = [
        r for r in caplog.records
        if "[EXECUTOR] activity_log TRADE_OPENED failed" in r.getMessage()
    ]
    assert len(swallow_records) >= 1, (
        "Catch-block log entry not found — open_shadow_trade may not have reached "
        "the activity_log block, or the log message text changed."
    )
    record = swallow_records[0]
    assert record.levelno >= logging.WARNING, (
        f"Catch-block log level must be WARNING+ (was {record.levelname}). The "
        f"activity_log is observability infrastructure; failures of the "
        f"observability mechanism itself must not be invisible. Pre-fix this was "
        f"DEBUG, which is why the silent NameError went unnoticed."
    )
