"""Tests for the 2026-04-13 reconciler + governor + IB-id hotfix branch.

Covers:
  * reconcile_paper_trades skips stale closure for IB-broker trades when the
    IB fetch raises or returns 0 positions vs. multiple active local trades.
  * _enforce_position_cap rejects trades once the combined open count hits
    the stricter of risk.max_open_positions or shadow_trading.max_positions.
  * Paper-IB entry path stores integer IB order IDs in broker_order_id and
    leaves alpaca_order_id NULL (prevents the UUID-parse crash in #420).
"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.journal.store import initialize_database, insert_shadow_trade
from src.shadow_trading.executor import (
    _count_live_open_positions,
    _enforce_position_cap,
    _governor_cap,
)
from src.shadow_trading.reconcile import reconcile_paper_trades


@pytest.fixture
def tmp_db(tmp_path):
    db = tmp_path / "hotfix.sqlite3"
    initialize_database(str(db))
    return str(db)


def _make_open_trade(ticker: str, broker: str = "alpaca", shares: float = 10.0) -> dict:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import uuid as _uuid
    et = ZoneInfo("America/New_York")
    now = datetime.now(et).isoformat()
    return {
        "trade_id": str(_uuid.uuid4()),
        "ticker": ticker,
        "direction": "long",
        "status": "open",
        "source": "paper",
        "broker": broker,
        "order_type": "bracket",
        "entry_price": 100.0,
        "actual_entry_price": 100.0,
        "stop_price": 95.0,
        "target_1": 105.0,
        "target_2": 110.0,
        "planned_shares": shares,
        "created_at": now,
        "updated_at": now,
        "actual_entry_time": now,
        "alpaca_order_id": str(_uuid.uuid4()),
    }


class TestGovernorCap:
    def test_prefers_stricter_cap(self):
        cfg = {"risk": {"max_open_positions": 5},
               "shadow_trading": {"max_positions": 10}}
        assert _governor_cap(cfg) == 5

    def test_falls_back_when_only_one_set(self):
        assert _governor_cap({"shadow_trading": {"max_positions": 7}}) == 7
        assert _governor_cap({"risk": {"max_open_positions": 3}}) == 3

    def test_default_when_none_configured(self):
        assert _governor_cap({}) == 10

    def test_ignores_non_positive(self):
        cfg = {"risk": {"max_open_positions": 0},
               "shadow_trading": {"max_positions": 8}}
        assert _governor_cap(cfg) == 8

    def test_bootcamp_enabled_uses_bootcamp_cap(self):
        """Bootcamp override matches executor.open_shadow_trade and
        risk.governor.check_trade behavior so all three surfaces agree."""
        cfg = {
            "bootcamp": {"enabled": True, "max_positions": 50},
            "risk": {"max_open_positions": 5},
            "shadow_trading": {"max_positions": 10},
        }
        assert _governor_cap(cfg) == 50

    def test_bootcamp_disabled_uses_strict_min(self):
        cfg = {
            "bootcamp": {"enabled": False, "max_positions": 50},
            "risk": {"max_open_positions": 5},
            "shadow_trading": {"max_positions": 10},
        }
        assert _governor_cap(cfg) == 5

    def test_bootcamp_enabled_default_is_50(self):
        cfg = {"bootcamp": {"enabled": True}}
        assert _governor_cap(cfg) == 50

    def test_bootcamp_enabled_with_invalid_cap_uses_default(self):
        cfg = {"bootcamp": {"enabled": True, "max_positions": 0}}
        assert _governor_cap(cfg) == 50
        cfg = {"bootcamp": {"enabled": True, "max_positions": -1}}
        assert _governor_cap(cfg) == 50

    def test_bootcamp_missing_falls_through(self):
        """No bootcamp key at all should behave like disabled."""
        cfg = {"risk": {"max_open_positions": 3},
               "shadow_trading": {"max_positions": 10}}
        assert _governor_cap(cfg) == 3


class TestEnforcePositionCap:
    def test_rejects_when_at_cap(self, tmp_db, caplog):
        cfg = {"risk": {"max_open_positions": 2}}
        for ticker in ("AAPL", "MSFT"):
            insert_shadow_trade(_make_open_trade(ticker), db_path=tmp_db)
        with caplog.at_level("WARNING"):
            allowed = _enforce_position_cap(cfg, tmp_db, "NVDA")
        assert allowed is False
        assert any("Max positions reached" in r.message for r in caplog.records)

    def test_allows_below_cap(self, tmp_db):
        cfg = {"risk": {"max_open_positions": 5}}
        for ticker in ("AAPL", "MSFT"):
            insert_shadow_trade(_make_open_trade(ticker), db_path=tmp_db)
        assert _enforce_position_cap(cfg, tmp_db, "NVDA") is True

    def test_ignores_quarantined(self, tmp_db):
        cfg = {"risk": {"max_open_positions": 2}}
        for ticker in ("AAPL", "MSFT"):
            t = _make_open_trade(ticker)
            t["quarantined"] = 1
            insert_shadow_trade(t, db_path=tmp_db)
        assert _count_live_open_positions(tmp_db) == 0
        assert _enforce_position_cap(cfg, tmp_db, "NVDA") is True

    def test_counts_paper_and_live_combined(self, tmp_db):
        cfg = {"risk": {"max_open_positions": 3}}
        paper = _make_open_trade("AAPL")
        live = _make_open_trade("MSFT")
        live["source"] = "live"
        insert_shadow_trade(paper, db_path=tmp_db)
        insert_shadow_trade(live, db_path=tmp_db)
        assert _count_live_open_positions(tmp_db) == 2
        # cap=3; one more allowed
        assert _enforce_position_cap(cfg, tmp_db, "NVDA") is True
        # fill the cap with a 3rd
        insert_shadow_trade(_make_open_trade("GOOG"), db_path=tmp_db)
        assert _enforce_position_cap(cfg, tmp_db, "NVDA") is False


class TestReconcilerBrokerUnreachableGuard:
    @patch("src.shadow_trading.reconcile.load_config")
    def _stub_paper_routing(self, monkeypatch_lc):
        pass

    def test_skips_ib_stale_when_ib_fetch_raises(self, tmp_db, caplog):
        """IB connect fails — IB-broker trades must NOT be marked stale."""
        # Local state: 2 IB trades and 1 Alpaca trade, Alpaca has neither.
        insert_shadow_trade(_make_open_trade("COP", broker="ib"), db_path=tmp_db)
        insert_shadow_trade(_make_open_trade("TGT", broker="ib"), db_path=tmp_db)
        insert_shadow_trade(_make_open_trade("AAPL", broker="alpaca"), db_path=tmp_db)

        def fake_get_all_positions():
            return []  # paper Alpaca returns empty

        class FailingIB:
            def __init__(self, *a, **kw): pass
            def _ensure_connected(self):
                raise ConnectionError("IB Gateway unreachable")
            def get_all_positions(self):
                return []

        with patch("src.shadow_trading.alpaca_adapter.get_all_positions",
                   fake_get_all_positions), \
             patch("src.config.load_config",
                   return_value={"live_trading": {"ib": {"paper_routing": True,
                                                         "host": "127.0.0.1",
                                                         "port": 4002,
                                                         "client_id": 1}}}), \
             patch("src.trading.ib_broker.IBBroker", FailingIB), \
             caplog.at_level("WARNING"):
            result = reconcile_paper_trades(db_path=tmp_db, dry_run=True)

        stale_tickers = {s["ticker"] for s in result.get("stale", [])}
        assert "COP" not in stale_tickers
        assert "TGT" not in stale_tickers
        assert "AAPL" in stale_tickers  # Alpaca-broker stale still closed
        assert any("IB fetch failed" in r.message
                   or "IB Gateway unreachable" in r.message
                   for r in caplog.records)

    def test_skips_ib_stale_when_ib_returns_zero_with_active_trades(self, tmp_db, caplog):
        """IB connects but returns 0 positions vs 3+ active — skip as suspicious."""
        for t in ("COP", "TGT", "NEE"):
            insert_shadow_trade(_make_open_trade(t, broker="ib"), db_path=tmp_db)

        class EmptyIB:
            def __init__(self, *a, **kw): pass
            def _ensure_connected(self): return
            def get_all_positions(self): return []

        with patch("src.shadow_trading.alpaca_adapter.get_all_positions",
                   lambda: []), \
             patch("src.config.load_config",
                   return_value={"live_trading": {"ib": {"paper_routing": True,
                                                         "host": "127.0.0.1",
                                                         "port": 4002,
                                                         "client_id": 1}}}), \
             patch("src.trading.ib_broker.IBBroker", EmptyIB), \
             caplog.at_level("WARNING"):
            result = reconcile_paper_trades(db_path=tmp_db, dry_run=True)

        stale_tickers = {s["ticker"] for s in result.get("stale", [])}
        assert stale_tickers == set(), (
            "Expected no IB trades marked stale when IB returns 0 vs 3 active, "
            f"got {stale_tickers}"
        )


class TestIBOrderIDFieldSeparation:
    """Integer IB order IDs must NOT be stored in alpaca_order_id."""

    def test_paper_ib_path_stores_id_in_broker_order_id(self, tmp_db):
        # Read the source to confirm the fix is present at the intended sites.
        # Behavioral end-to-end is covered by the reconciler + bracket_monitor
        # tests in their respective PRs; here we pin the storage contract.
        import src.shadow_trading.executor as exec_mod
        src = open(exec_mod.__file__, encoding="utf-8").read()
        assert 'trade_data["broker_order_id"] = str(order.order_id)' in src
        assert 'trade_data["alpaca_order_id"] = None' in src

    def test_no_integer_assignment_to_alpaca_order_id_in_ib_branches(self):
        """Guard against regression of the routing bug."""
        import src.shadow_trading.executor as exec_mod
        src = open(exec_mod.__file__, encoding="utf-8").read()
        # The old line `trade_data["alpaca_order_id"] = order.order_id` used in
        # the IB-paper route must no longer appear immediately inside the
        # `if _paper_broker_name == "ib"` branch.
        ib_branch_idx = src.find('if _paper_broker_name == "ib"')
        assert ib_branch_idx != -1
        # Find the next ~40 lines of the branch
        snippet = src[ib_branch_idx:ib_branch_idx + 1500]
        # alpaca_order_id should only be set to None in this branch, never to order.order_id
        assert 'trade_data["alpaca_order_id"] = order.order_id' not in snippet
