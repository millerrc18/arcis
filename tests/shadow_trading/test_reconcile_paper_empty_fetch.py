"""Wave 6 — tests for Alpaca empty-fetch guard in reconcile_paper_trades().

Root cause: on 2026-05-04, a transient empty Alpaca response caused 13 real
broker positions (AVGO, BK, BMY, C, CAT, COP, EMR, GS, KO, PEP, SPG, TGT,
TXN) to be falsely marked reconciled_stale. The reconciler had no guard for
the case where get_all_positions() raises OR returns [] while local active
trades exist.

Wave 5 (PR #937) added an anti-re-backfill guard but did NOT fix the root
cause. Wave 6 mirrors the IB-side pattern (lines 562-584 + 588-591 in
reconcile.py) on the Alpaca side.

Tests:
  1. Exception case — get_all_positions() raises; 5 alpaca trades must not
     be marked stale.
  2. Empty-with-3plus — returns []; 5 alpaca trades; threshold check.
  3. Empty-with-2 — returns []; 2 trades; BOTH should be stale (threshold-of-3
     means 2 active is legitimately flat-broker).
  4. Happy path — returns real positions; correct match/stale/orphan split.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from src.journal.store import initialize_database, insert_shadow_trade
from src.shadow_trading.reconcile import reconcile_paper_trades


@pytest.fixture
def tmp_db(tmp_path):
    db = tmp_path / "wave6.sqlite3"
    initialize_database(str(db))
    return str(db)


def _make_open_trade(ticker: str, broker: str = "alpaca", shares: float = 10.0) -> dict:
    et = ZoneInfo("America/New_York")
    now = datetime.now(et).isoformat()
    return {
        "trade_id": str(uuid.uuid4()),
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
        "created_at": "2026-05-03T10:00:00-04:00",
        "updated_at": now,
        "actual_entry_time": "2026-05-03T10:00:00-04:00",
        "alpaca_order_id": str(uuid.uuid4()),
    }


class TestAlpacaFetchExceptionSkipsStaleMarking:
    def test_alpaca_fetch_exception_skips_stale_marking(self, tmp_db, caplog):
        """get_all_positions() raises — NONE of the 5 active alpaca trades
        should be marked stale; log must mention 'Alpaca API unreachable'."""
        for ticker in ("AVGO", "BK", "BMY", "C", "CAT"):
            insert_shadow_trade(_make_open_trade(ticker, broker="alpaca"), db_path=tmp_db)

        with patch(
            "src.shadow_trading.reconcile.get_all_positions",
            side_effect=RuntimeError("rate limit exceeded"),
        ), patch(
            "src.config.load_config",
            return_value={"trading": {"ib_enabled": False}},
        ), caplog.at_level("WARNING"):
            result = reconcile_paper_trades(db_path=tmp_db, dry_run=True)

        stale_tickers = {s["ticker"] for s in result.get("stale", [])}
        assert stale_tickers == set(), (
            f"Expected no trades marked stale on Alpaca API exception, got {stale_tickers}"
        )
        assert any(
            "Alpaca API unreachable" in r.message for r in caplog.records
        ), "Expected 'Alpaca API unreachable' in log when get_all_positions raises"


class TestAlpacaEmptyWith3PlusActiveSkipsStaleMarking:
    def test_alpaca_empty_with_3plus_active_skips_stale_marking(self, tmp_db, caplog):
        """get_all_positions() returns []; 5 active alpaca trades; NONE should
        be stale (transient guard fires). Log must mention '0 positions but
        local has'."""
        for ticker in ("COP", "EMR", "GS", "KO", "PEP"):
            insert_shadow_trade(_make_open_trade(ticker, broker="alpaca"), db_path=tmp_db)

        with patch(
            "src.shadow_trading.reconcile.get_all_positions",
            return_value=[],
        ), patch(
            "src.config.load_config",
            return_value={"trading": {"ib_enabled": False}},
        ), caplog.at_level("WARNING"):
            result = reconcile_paper_trades(db_path=tmp_db, dry_run=True)

        stale_tickers = {s["ticker"] for s in result.get("stale", [])}
        assert stale_tickers == set(), (
            f"Expected no trades marked stale when Alpaca returns [] vs 5 active, "
            f"got {stale_tickers}"
        )
        assert any(
            "0 positions but local has" in r.message for r in caplog.records
        ), "Expected transient-guard log when Alpaca returns 0 vs 5 active trades"


class TestAlpacaEmptyWith2ActiveProceedsNormally:
    def test_alpaca_empty_with_2_active_proceeds_normally(self, tmp_db, caplog):
        """get_all_positions() returns []; only 2 active alpaca trades; BOTH
        should be marked stale (threshold-of-3 means 2 active = legitimately
        flat broker). This locks the threshold contract."""
        for ticker in ("SPG", "TGT"):
            insert_shadow_trade(_make_open_trade(ticker, broker="alpaca"), db_path=tmp_db)

        with patch(
            "src.shadow_trading.reconcile.get_all_positions",
            return_value=[],
        ), patch(
            "src.config.load_config",
            return_value={"trading": {"ib_enabled": False}},
        ), caplog.at_level("WARNING"):
            result = reconcile_paper_trades(db_path=tmp_db, dry_run=True)

        stale_tickers = {s["ticker"] for s in result.get("stale", [])}
        assert "SPG" in stale_tickers, (
            "SPG should be stale when Alpaca empty and only 2 trades active "
            "(below transient guard threshold)"
        )
        assert "TGT" in stale_tickers, (
            "TGT should be stale when Alpaca empty and only 2 trades active "
            "(below transient guard threshold)"
        )


class TestAlpacaEmptyAtBoundaryThresholdSkipsStaleMarking:
    """Lock the >= 3 boundary on _TRANSIENT_EMPTY_FETCH_THRESHOLD.

    Tests at exactly N=3 are the canonical defense against off-by-one drift
    in the transient-empty guard.  The other tests use N=5 (above) and N=2
    (below) — neither pins the boundary itself.  If a future refactor changes
    `>= 3` to `> 3` (or vice versa), this test catches it.
    """

    def test_alpaca_empty_with_exactly_3_active_skips_stale_marking(self, tmp_db, caplog):
        """get_all_positions() returns []; exactly 3 active alpaca trades;
        NONE should be marked stale (>= 3 threshold means 3 active = transient guard fires)."""
        for ticker in ("AAPL", "MSFT", "TSLA"):
            insert_shadow_trade(_make_open_trade(ticker, broker="alpaca"), db_path=tmp_db)

        with patch(
            "src.shadow_trading.reconcile.get_all_positions",
            return_value=[],
        ), patch(
            "src.config.load_config",
            return_value={"trading": {"ib_enabled": False}},
        ), caplog.at_level("WARNING"):
            result = reconcile_paper_trades(db_path=tmp_db, dry_run=True)

        stale_tickers = {s["ticker"] for s in result.get("stale", [])}
        assert stale_tickers == set(), (
            f"With exactly 3 active alpaca trades and Alpaca returning [], "
            f"the transient guard should fire (threshold is >= 3) and NO trades "
            f"should be marked stale. Got stale={stale_tickers}"
        )
        # Verify the transient-empty warning fired (not the exception-path warning)
        assert any(
            "0 positions but local has 3 active" in r.message
            for r in caplog.records
            if r.levelname == "WARNING"
        ), (
            "Expected the transient-empty WARNING to fire at exactly N=3. "
            "If this test starts failing because the warning text changed, "
            "update the assertion — but if it fails because no warning fired, "
            "the >= 3 threshold has regressed to > 3."
        )


class TestAlpacaReturnsRealPositionsNormalPath:
    def test_alpaca_returns_real_positions_normal_path(self, tmp_db, caplog):
        """Happy-path: Alpaca returns real positions. Verify matched/stale/orphan
        are each classified correctly after the fix."""
        # Local: AAPL (open), MSFT (open — will be stale), no GOOG
        insert_shadow_trade(_make_open_trade("AAPL", broker="alpaca"), db_path=tmp_db)
        insert_shadow_trade(_make_open_trade("MSFT", broker="alpaca"), db_path=tmp_db)

        # Alpaca: AAPL (matched), GOOG (orphan), no MSFT (stale)
        alpaca_positions = [
            {"symbol": "AAPL", "qty": "10.0", "avg_entry_price": "100.0",
             "current_price": "105.0"},
            {"symbol": "GOOG", "qty": "5.0", "avg_entry_price": "150.0",
             "current_price": "155.0"},
        ]

        with patch(
            "src.shadow_trading.reconcile.get_all_positions",
            return_value=alpaca_positions,
        ), patch(
            "src.config.load_config",
            return_value={"trading": {"ib_enabled": False}},
        ):
            result = reconcile_paper_trades(db_path=tmp_db, dry_run=True)

        stale_tickers = {s["ticker"] for s in result.get("stale", [])}
        orphan_tickers = {o["ticker"] for o in result.get("orphaned", [])}

        assert "MSFT" in stale_tickers, (
            f"MSFT should be stale (in local, not in Alpaca), got stale={stale_tickers}"
        )
        assert "AAPL" not in stale_tickers, (
            f"AAPL should be matched (in both), got stale={stale_tickers}"
        )
        assert "GOOG" in orphan_tickers, (
            f"GOOG should be orphaned (in Alpaca, not in local), got orphans={orphan_tickers}"
        )
        assert result.get("matched", 0) >= 1, (
            f"Expected at least 1 matched trade, got {result.get('matched', 0)}"
        )
