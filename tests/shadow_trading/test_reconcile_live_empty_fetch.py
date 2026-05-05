"""Wave 7 — tests for Alpaca empty-fetch guard in reconcile_live_trades().

Mirrors Wave 6 (PR #942) which added the same guard to reconcile_paper_trades().

Root cause: if the live broker returns empty positions (transient outage) while
N>=3 active live trades exist, all live trades would be mass-marked stale.
Currently moot since live trading is paper-only post-bootcamp, but hardened
before any live-money flip (trading-safety class).

Tests:
  1. Exception case — broker call raises; 5 live trades must not be stale.
  2. Empty-with-3plus — returns []; 5 live trades; threshold guard fires.
  3. Empty-with-2 — returns []; 2 trades; BOTH should be stale (threshold
     means 2 active is legitimately flat-broker).
  4. Boundary — exactly 3 active; guard fires (locks >= 3 boundary).
  5. Happy path — real positions returned; correct match/stale/orphan split.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.journal.store import initialize_database, insert_shadow_trade
from src.shadow_trading.reconcile import reconcile_live_trades


@pytest.fixture
def tmp_db(tmp_path):
    db = tmp_path / "wave7.sqlite3"
    initialize_database(str(db))
    return str(db)


def _make_open_live_trade(ticker: str, shares: float = 10.0) -> dict:
    et = ZoneInfo("America/New_York")
    now = datetime.now(et).isoformat()
    return {
        "trade_id": str(uuid.uuid4()),
        "ticker": ticker,
        "direction": "long",
        "status": "open",
        "source": "live",
        "desk": "swing",
        "order_type": "bracket",
        "entry_price": 100.0,
        "actual_entry_price": 100.0,
        "stop_price": 95.0,
        "target_1": 105.0,
        "target_2": 110.0,
        "planned_shares": shares,
        "planned_allocation": 1000.0,
        "created_at": "2026-05-03T10:00:00-04:00",
        "updated_at": now,
        "actual_entry_time": "2026-05-03T10:00:00-04:00",
        "alpaca_order_id": str(uuid.uuid4()),
    }


class TestLiveFetchExceptionSkipsStaleMarking:
    def test_live_fetch_exception_skips_stale_marking(self, tmp_db, caplog):
        """Both broker paths raise exception — NONE of the 5 active live trades
        should be marked stale; result['error'] must be populated."""
        for ticker in ("AVGO", "BK", "BMY", "C", "CAT"):
            insert_shadow_trade(_make_open_live_trade(ticker), db_path=tmp_db)

        mock_broker = MagicMock()
        mock_broker.get_all_positions.side_effect = RuntimeError("broker timeout")

        # Both paths fail: broker factory raises (caught), then get_live_positions also raises.
        # Wave 7 must catch both failures and set live_fetch_ok=False rather than propagating.
        with patch(
            "src.trading.broker_factory.get_live_broker",
            return_value=mock_broker,
        ), patch(
            "src.config.load_config",
            return_value={},
        ), patch(
            "src.shadow_trading.reconcile.get_live_positions",
            side_effect=RuntimeError("direct also down"),
        ), caplog.at_level("WARNING"):
            result = reconcile_live_trades(db_path=tmp_db, dry_run=True)

        stale_tickers = set(result.get("stale", []))
        assert stale_tickers == set(), (
            f"Expected no trades marked stale when live broker raises, got {stale_tickers}"
        )
        assert result.get("error") is not None, (
            "result['error'] should be populated when live broker fetch fails"
        )


class TestLiveEmptyWith3PlusActiveSkipsStaleMarking:
    def test_live_empty_with_3plus_active_skips_stale_marking(self, tmp_db, caplog):
        """Broker returns []; 5 active live trades; NONE should be stale
        (transient guard fires). Log must warn about skipping stale closure."""
        for ticker in ("COP", "EMR", "GS", "KO", "PEP"):
            insert_shadow_trade(_make_open_live_trade(ticker), db_path=tmp_db)

        mock_broker = MagicMock()
        mock_broker.get_all_positions.return_value = []

        with patch(
            "src.trading.broker_factory.get_live_broker",
            return_value=mock_broker,
        ), patch(
            "src.config.load_config",
            return_value={},
        ), caplog.at_level("WARNING"):
            result = reconcile_live_trades(db_path=tmp_db, dry_run=True)

        stale_tickers = set(result.get("stale", []))
        assert stale_tickers == set(), (
            f"Expected no trades marked stale when live broker returns [] vs 5 active, "
            f"got {stale_tickers}"
        )
        assert any(
            "Skipping stale closure" in r.message and "live" in r.message.lower()
            for r in caplog.records
        ), (
            "Expected a 'Skipping stale closure' warning in logs when live broker "
            "returns empty vs 5+ active trades"
        )


class TestLiveEmptyWith2ActiveProceedsNormally:
    def test_live_empty_with_2_active_proceeds_normally(self, tmp_db, caplog):
        """Broker returns []; only 2 active live trades; BOTH should be marked
        stale (threshold-of-3 means 2 active = legitimately flat broker).
        This locks the threshold boundary contract."""
        for ticker in ("SPG", "TGT"):
            insert_shadow_trade(_make_open_live_trade(ticker), db_path=tmp_db)

        mock_broker = MagicMock()
        mock_broker.get_all_positions.return_value = []

        with patch(
            "src.trading.broker_factory.get_live_broker",
            return_value=mock_broker,
        ), patch(
            "src.config.load_config",
            return_value={},
        ), caplog.at_level("WARNING"):
            result = reconcile_live_trades(db_path=tmp_db, dry_run=True)

        stale_tickers = set(result.get("stale", []))
        assert "SPG" in stale_tickers, (
            "SPG should be stale when live broker empty and only 2 trades active "
            "(below transient guard threshold)"
        )
        assert "TGT" in stale_tickers, (
            "TGT should be stale when live broker empty and only 2 trades active "
            "(below transient guard threshold)"
        )


class TestLiveEmptyWithExactly3ActiveSkipsStaleMarking:
    def test_live_empty_with_exactly_3_active_skips_stale_marking(self, tmp_db, caplog):
        """Broker returns []; exactly 3 active live trades; NONE should be
        marked stale (>= 3 threshold means 3 = transient guard fires).
        Locks the >= 3 boundary against off-by-one drift."""
        for ticker in ("AAPL", "MSFT", "TSLA"):
            insert_shadow_trade(_make_open_live_trade(ticker), db_path=tmp_db)

        mock_broker = MagicMock()
        mock_broker.get_all_positions.return_value = []

        with patch(
            "src.trading.broker_factory.get_live_broker",
            return_value=mock_broker,
        ), patch(
            "src.config.load_config",
            return_value={},
        ), caplog.at_level("WARNING"):
            result = reconcile_live_trades(db_path=tmp_db, dry_run=True)

        stale_tickers = set(result.get("stale", []))
        assert stale_tickers == set(), (
            f"With exactly 3 active live trades and live broker returning [], "
            f"the transient guard should fire (threshold is >= 3) and NO trades "
            f"should be marked stale. Got stale={stale_tickers}"
        )
        assert any(
            "Skipping stale closure" in r.message
            for r in caplog.records
            if r.levelname == "WARNING"
        ), (
            "Expected the 'Skipping stale closure' WARNING at exactly N=3. "
            "If this fails because no warning fired, >= 3 has regressed to > 3."
        )


class TestLiveReturnsRealPositionsNormalPath:
    def test_live_returns_real_positions_normal_path(self, tmp_db):
        """Happy-path: live broker returns real positions. Verify
        matched/stale/orphan are each classified correctly."""
        insert_shadow_trade(_make_open_live_trade("AAPL"), db_path=tmp_db)
        insert_shadow_trade(_make_open_live_trade("MSFT"), db_path=tmp_db)

        class FakePosition:
            def __init__(self, ticker, qty, avg_cost, current_price, unrealized_pnl, market_value):
                self.ticker = ticker
                self.quantity = qty
                self.avg_cost = avg_cost
                self.current_price = current_price
                self.unrealized_pnl = unrealized_pnl
                self.market_value = market_value

        mock_broker = MagicMock()
        mock_broker.get_all_positions.return_value = [
            FakePosition("AAPL", 10.0, 100.0, 105.0, 50.0, 1050.0),
            FakePosition("GOOG", 5.0, 150.0, 155.0, 25.0, 775.0),
        ]

        with patch(
            "src.trading.broker_factory.get_live_broker",
            return_value=mock_broker,
        ), patch(
            "src.config.load_config",
            return_value={},
        ):
            result = reconcile_live_trades(db_path=tmp_db, dry_run=True)

        stale_tickers = set(result.get("stale", []))
        orphan_tickers = set(result.get("orphaned", []))

        assert "MSFT" in stale_tickers, (
            f"MSFT should be stale (in local, not in live broker), got stale={stale_tickers}"
        )
        assert "AAPL" not in stale_tickers, (
            f"AAPL should be matched (in both), got stale={stale_tickers}"
        )
        assert "GOOG" in orphan_tickers, (
            f"GOOG should be orphaned (in live broker, not in local), got orphans={orphan_tickers}"
        )
        assert result.get("error") is None, (
            "error should be None on happy path"
        )
