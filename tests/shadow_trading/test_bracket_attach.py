"""Tests for `src/shadow_trading/bracket_attach.py`.

Backfills OCO protection (sell-limit at target_1 + sell-stop at
stop_price) onto open shadow_trades that the broker shows unprotected.
Designed to fix the 2026-05-15 unprotected-position class: orphan-
backfilled positions never had a bracket, and bracket-canceled
positions lost theirs to a reconciler mis-fire.
"""
from __future__ import annotations

import enum
from unittest.mock import MagicMock, patch

import pytest


# ── Local OrderStatus that mimics alpaca-py regular-Enum behavior ─────────────


class _LocalOrderStatus(enum.Enum):
    NEW = "new"
    HELD = "held"
    ACCEPTED = "accepted"
    PENDING_NEW = "pending_new"
    FILLED = "filled"
    CANCELED = "canceled"


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_broker_position(ticker: str, qty: float, current_price: float) -> MagicMock:
    pos = MagicMock()
    pos.qty = str(qty)
    pos.current_price = str(current_price)
    pos.symbol = ticker
    return pos


def _make_broker_order(parent_status: _LocalOrderStatus, leg_statuses: list[_LocalOrderStatus] | None = None) -> MagicMock:
    """Mimic an alpaca-py Order with optional bracket legs."""
    order = MagicMock()
    order.id = "broker-oid-abc"
    order.status = parent_status
    order.legs = []
    for s in leg_statuses or []:
        leg = MagicMock()
        leg.status = s
        order.legs.append(leg)
    return order


def _make_oco_submit_response() -> MagicMock:
    """Return a fake submit_order response for an OCO order."""
    order = MagicMock()
    order.id = "new-oco-oid-xyz"
    order.status = _LocalOrderStatus.PENDING_NEW
    leg = MagicMock()
    leg.status = _LocalOrderStatus.HELD
    order.legs = [leg]
    return order


@pytest.fixture
def trade_db(tmp_path):
    """Build a temp SQLite DB with shadow_trades + one open position."""
    import sqlite3
    db = str(tmp_path / "trades.sqlite3")
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            ticker TEXT,
            status TEXT,
            order_type TEXT,
            alpaca_order_id TEXT,
            planned_shares REAL,
            entry_price REAL,
            actual_entry_price REAL,
            stop_price REAL,
            target_1 REAL,
            quarantined INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        INSERT INTO shadow_trades
        (trade_id, ticker, status, order_type, alpaca_order_id, planned_shares,
         entry_price, actual_entry_price, stop_price, target_1, quarantined)
        VALUES
        ('t-AMZN', 'AMZN', 'open', 'reconciled', NULL, 12.0, 274.30, 274.30, 259.82, 285.15, 0)
    """)
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def client_factory():
    """Returns a function that builds a configured mock Alpaca client."""
    def _build(
        position: MagicMock | None = None,
        existing_order: MagicMock | None = None,
        open_orders: list | None = None,
        submit_response: MagicMock | None = None,
        submit_error: Exception | None = None,
    ) -> MagicMock:
        client = MagicMock()
        if position:
            client.get_open_position.return_value = position
        else:
            client.get_open_position.side_effect = Exception("no position")
        if existing_order:
            client.get_order_by_id.return_value = existing_order
        else:
            client.get_order_by_id.side_effect = Exception("no order")
        client.get_orders.return_value = open_orders or []
        if submit_error:
            client.submit_order.side_effect = submit_error
        else:
            client.submit_order.return_value = submit_response or _make_oco_submit_response()
        return client
    return _build


# ── Happy path ────────────────────────────────────────────────────────────────


class TestAttachBracketsHappyPath:
    @patch("src.shadow_trading.bracket_attach._get_trading_client")
    def test_submits_oco_and_updates_db(self, mock_get_client, trade_db, client_factory):
        """Clean unprotected position → submits OCO + writes new oid to DB."""
        from src.shadow_trading.bracket_attach import attach_brackets_for_unprotected_positions
        mock_get_client.return_value = client_factory(
            position=_make_broker_position("AMZN", 12.0, 270.00),
            submit_response=_make_oco_submit_response(),
        )

        result = attach_brackets_for_unprotected_positions(db_path=trade_db)

        assert len(result["submitted"]) == 1
        assert result["submitted"][0][0] == "AMZN"
        assert result["submitted"][0][1] == "new-oco-oid-xyz"

        # DB updated
        import sqlite3
        conn = sqlite3.connect(trade_db)
        row = conn.execute("SELECT alpaca_order_id, order_type FROM shadow_trades WHERE ticker='AMZN'").fetchone()
        conn.close()
        assert row[0] == "new-oco-oid-xyz", f"alpaca_order_id not updated, got {row[0]!r}"
        assert row[1] == "bracket", f"order_type not upgraded to bracket, got {row[1]!r}"


# ── Skip reasons ──────────────────────────────────────────────────────────────


class TestAttachBracketsSkips:
    @patch("src.shadow_trading.bracket_attach._get_trading_client")
    def test_skips_when_position_missing(self, mock_get_client, trade_db, client_factory):
        from src.shadow_trading.bracket_attach import attach_brackets_for_unprotected_positions
        mock_get_client.return_value = client_factory(position=None)
        result = attach_brackets_for_unprotected_positions(db_path=trade_db)
        assert len(result["submitted"]) == 0
        assert any(t[0] == "AMZN" and "no broker position" in t[1].lower() for t in result["skipped"])

    @patch("src.shadow_trading.bracket_attach._get_trading_client")
    def test_skips_when_qty_mismatch(self, mock_get_client, trade_db, client_factory):
        from src.shadow_trading.bracket_attach import attach_brackets_for_unprotected_positions
        mock_get_client.return_value = client_factory(
            position=_make_broker_position("AMZN", 8.0, 270.00),  # broker has 8, planned 12
        )
        result = attach_brackets_for_unprotected_positions(db_path=trade_db)
        assert len(result["submitted"]) == 0
        assert any("qty mismatch" in t[1].lower() for t in result["skipped"])

    @patch("src.shadow_trading.bracket_attach._get_trading_client")
    def test_skips_when_stop_above_current(self, mock_get_client, trade_db, client_factory):
        from src.shadow_trading.bracket_attach import attach_brackets_for_unprotected_positions
        # Position price at $259 — below the $259.82 stop. Submitting would
        # fire the stop immediately.
        mock_get_client.return_value = client_factory(
            position=_make_broker_position("AMZN", 12.0, 259.00),
        )
        result = attach_brackets_for_unprotected_positions(db_path=trade_db)
        assert len(result["submitted"]) == 0
        assert any("stop" in t[1].lower() and "current" in t[1].lower() for t in result["skipped"])

    @patch("src.shadow_trading.bracket_attach._get_trading_client")
    def test_skips_when_target_below_current(self, mock_get_client, trade_db, client_factory):
        from src.shadow_trading.bracket_attach import attach_brackets_for_unprotected_positions
        # Position price at $290 — above the $285.15 target. Submitting would
        # fire the limit immediately.
        mock_get_client.return_value = client_factory(
            position=_make_broker_position("AMZN", 12.0, 290.00),
        )
        result = attach_brackets_for_unprotected_positions(db_path=trade_db)
        assert len(result["submitted"]) == 0
        assert any("target" in t[1].lower() and "current" in t[1].lower() for t in result["skipped"])

    @patch("src.shadow_trading.bracket_attach._get_trading_client")
    def test_skips_when_existing_open_orders(self, mock_get_client, trade_db, client_factory):
        from src.shadow_trading.bracket_attach import attach_brackets_for_unprotected_positions
        existing = MagicMock()
        mock_get_client.return_value = client_factory(
            position=_make_broker_position("AMZN", 12.0, 270.00),
            open_orders=[existing],
        )
        result = attach_brackets_for_unprotected_positions(db_path=trade_db)
        assert len(result["submitted"]) == 0
        assert any("open order" in t[1].lower() for t in result["skipped"])

    @patch("src.shadow_trading.bracket_attach._get_trading_client")
    def test_skips_when_already_protected(self, mock_get_client, trade_db, client_factory):
        """Trade has alpaca_order_id pointing to an active bracket → skip."""
        from src.shadow_trading.bracket_attach import attach_brackets_for_unprotected_positions
        import sqlite3
        # Wire an existing alpaca_order_id onto the trade
        conn = sqlite3.connect(trade_db)
        conn.execute("UPDATE shadow_trades SET alpaca_order_id=?, order_type='bracket' WHERE ticker='AMZN'", ("existing-oid",))
        conn.commit()
        conn.close()

        active_order = _make_broker_order(
            parent_status=_LocalOrderStatus.FILLED,  # entry filled
            leg_statuses=[_LocalOrderStatus.NEW, _LocalOrderStatus.HELD],  # both legs active
        )
        mock_get_client.return_value = client_factory(
            position=_make_broker_position("AMZN", 12.0, 270.00),
            existing_order=active_order,
        )
        result = attach_brackets_for_unprotected_positions(db_path=trade_db)
        assert len(result["submitted"]) == 0
        assert any("already protected" in t[1].lower() for t in result["skipped"])


# ── Flags ─────────────────────────────────────────────────────────────────────


class TestAttachBracketsFlags:
    @patch("src.shadow_trading.bracket_attach._get_trading_client")
    def test_dry_run_does_not_submit(self, mock_get_client, trade_db, client_factory):
        from src.shadow_trading.bracket_attach import attach_brackets_for_unprotected_positions
        client = client_factory(
            position=_make_broker_position("AMZN", 12.0, 270.00),
        )
        mock_get_client.return_value = client

        result = attach_brackets_for_unprotected_positions(db_path=trade_db, dry_run=True)

        client.submit_order.assert_not_called()
        # DRY_RUN entry recorded so caller knows what WOULD have happened
        assert len(result["submitted"]) == 1
        assert result["submitted"][0][1] == "DRY_RUN"

    @patch("src.shadow_trading.bracket_attach._get_trading_client")
    def test_ticker_filter_limits_scope(self, mock_get_client, trade_db, client_factory):
        """ticker_filter=['ETN'] should ignore AMZN in the DB."""
        from src.shadow_trading.bracket_attach import attach_brackets_for_unprotected_positions
        client = client_factory(
            position=_make_broker_position("AMZN", 12.0, 270.00),
        )
        mock_get_client.return_value = client

        result = attach_brackets_for_unprotected_positions(db_path=trade_db, ticker_filter=["ETN"])

        # No AMZN action because filter excludes it; no ETN in DB so nothing scanned
        assert len(result["submitted"]) == 0
        assert len(result["skipped"]) == 0
        assert result["scanned"] == 0


# ── Per-ticker isolation ──────────────────────────────────────────────────────


class TestAttachBracketsIsolation:
    @patch("src.shadow_trading.bracket_attach._get_trading_client")
    def test_failure_does_not_halt_batch(self, mock_get_client, tmp_path, client_factory):
        """One ticker's submit failure must not prevent other tickers from succeeding."""
        from src.shadow_trading.bracket_attach import attach_brackets_for_unprotected_positions

        # Build a DB with two open trades.
        import sqlite3
        db = str(tmp_path / "trades.sqlite3")
        conn = sqlite3.connect(db)
        conn.execute("""
            CREATE TABLE shadow_trades (
                trade_id TEXT PRIMARY KEY,
                ticker TEXT,
                status TEXT,
                order_type TEXT,
                alpaca_order_id TEXT,
                planned_shares REAL,
                entry_price REAL,
                actual_entry_price REAL,
                stop_price REAL,
                target_1 REAL,
                quarantined INTEGER DEFAULT 0
            )
        """)
        conn.executemany(
            "INSERT INTO shadow_trades VALUES (?, ?, 'open', 'reconciled', NULL, ?, ?, ?, ?, ?, 0)",
            [
                ("t-AAA", "AAA", 10.0, 100.0, 100.0, 90.0, 110.0),
                ("t-BBB", "BBB", 10.0, 100.0, 100.0, 90.0, 110.0),
            ],
        )
        conn.commit()
        conn.close()

        # AAA fails to submit; BBB succeeds.
        position = _make_broker_position("X", 10.0, 100.0)
        position.qty = "10"
        position.current_price = "100"

        def get_position_side_effect(symbol):
            return position

        def submit_side_effect(request):
            if request.symbol == "AAA":
                raise RuntimeError("broker rejected AAA")
            return _make_oco_submit_response()

        client = MagicMock()
        client.get_open_position.side_effect = get_position_side_effect
        client.get_orders.return_value = []
        client.submit_order.side_effect = submit_side_effect
        mock_get_client.return_value = client

        result = attach_brackets_for_unprotected_positions(db_path=db)

        assert len(result["submitted"]) == 1
        assert result["submitted"][0][0] == "BBB"
        assert len(result["failed"]) == 1
        assert result["failed"][0][0] == "AAA"
