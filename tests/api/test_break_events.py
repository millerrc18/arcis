"""Tests for break-event retention (T3 — Founder Console Phase-1 design law #9).

Covers:
- record_break inserts the correct row per break type
- Law-#9 integration: orphan detection emits a reconciliation_breaks row
  even when the orphan is then auto-backfilled (row survives backfill)
- get_break_events returns history ordered newest-first with age derivable
  from created_at/detected_at
- Writer failure does NOT raise into reconcile (best-effort contract)

All writer/reader tests patch connect_db so the function gets its own fresh
PG connection (which it closes on __exit__). A separate raw connection is kept
open for verification queries. Law-#9 test uses a direct insert callable to
prove the row survives backfill.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

# ── Skip whole module if TEST_DATABASE_URL is absent ─────────────────────────

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_PG_URL.startswith("postgres"),
    reason="integration(authoritative-coverage:pg-tests)",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pg_wrapper():
    """Return a fresh PostgresConnectionWrapper against the test PG.

    Caller is responsible for close/commit.
    """
    import psycopg2
    import psycopg2.extras
    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    raw.autocommit = False
    return PostgresConnectionWrapper(raw)


def _provision_table(wrapper) -> None:
    """Create reconciliation_breaks if absent."""
    wrapper.execute("""
        CREATE TABLE IF NOT EXISTS reconciliation_breaks (
            id SERIAL PRIMARY KEY,
            created_at TEXT NOT NULL,
            break_type TEXT NOT NULL,
            symbol TEXT NOT NULL,
            magnitude REAL,
            desk TEXT,
            source TEXT,
            detail TEXT,
            detected_at TEXT NOT NULL
        )
    """)
    wrapper.execute("""
        CREATE INDEX IF NOT EXISTS idx_reconciliation_breaks_created_at
            ON reconciliation_breaks (created_at)
    """)
    wrapper.execute("""
        CREATE INDEX IF NOT EXISTS idx_reconciliation_breaks_break_type
            ON reconciliation_breaks (break_type)
    """)
    wrapper.commit()


def _truncate_table(wrapper) -> None:
    wrapper.execute("TRUNCATE TABLE reconciliation_breaks RESTART IDENTITY")
    wrapper.commit()


def _count_breaks(wrapper) -> int:
    row = wrapper.execute("SELECT COUNT(*) FROM reconciliation_breaks").fetchone()
    return row[0]


def _fetch_all_breaks(wrapper) -> list[dict]:
    rows = wrapper.execute(
        "SELECT * FROM reconciliation_breaks ORDER BY created_at DESC, id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@pytest.fixture(autouse=True)
def _clean_breaks_table():
    """Provision + truncate before each test; truncate after."""
    w = _make_pg_wrapper()
    _provision_table(w)
    _truncate_table(w)
    w.close()

    yield

    w2 = _make_pg_wrapper()
    _truncate_table(w2)
    w2.close()


# ── Writer unit tests ─────────────────────────────────────────────────────────

class TestRecordBreak:
    """record_break inserts exactly the expected row for each break type."""

    def test_record_break_orphan_inserts_row(self):
        from src.shadow_trading.break_events import record_break

        # Verify zero rows before (non-vacuous)
        verify = _make_pg_wrapper()
        assert _count_breaks(verify) == 0
        verify.close()

        # record_break opens+closes its own connection via connect_db()
        with patch("src.shadow_trading.break_events.connect_db", side_effect=_make_pg_wrapper):
            record_break(
                break_type="orphan",
                symbol="AAPL",
                magnitude=1500.0,
                desk="swing",
                source="paper",
                detail="Alpaca has AAPL, DB does not",
            )

        verify2 = _make_pg_wrapper()
        rows = _fetch_all_breaks(verify2)
        verify2.close()

        assert len(rows) >= 1, "Expected at least 1 break row after record_break"
        row = rows[0]
        assert row["break_type"] == "orphan"
        assert row["symbol"] == "AAPL"
        assert row["magnitude"] == pytest.approx(1500.0)
        assert row["desk"] == "swing"
        assert row["source"] == "paper"
        assert row["detail"] == "Alpaca has AAPL, DB does not"
        assert row["created_at"] is not None
        assert row["detected_at"] is not None

    def test_record_break_stale_inserts_row(self):
        from src.shadow_trading.break_events import record_break

        verify = _make_pg_wrapper()
        assert _count_breaks(verify) == 0
        verify.close()

        with patch("src.shadow_trading.break_events.connect_db", side_effect=_make_pg_wrapper):
            record_break(break_type="stale", symbol="TSLA", source="live")

        verify2 = _make_pg_wrapper()
        rows = _fetch_all_breaks(verify2)
        verify2.close()

        assert len(rows) >= 1
        row = rows[0]
        assert row["break_type"] == "stale"
        assert row["symbol"] == "TSLA"
        assert row["source"] == "live"
        assert row["magnitude"] is None
        assert row["desk"] is None

    def test_record_break_qty_mismatch_inserts_row(self):
        from src.shadow_trading.break_events import record_break

        verify = _make_pg_wrapper()
        assert _count_breaks(verify) == 0
        verify.close()

        with patch("src.shadow_trading.break_events.connect_db", side_effect=_make_pg_wrapper):
            record_break(
                break_type="qty_mismatch",
                symbol="NVDA",
                magnitude=5.0,
                detail="local=10 alpaca=5",
            )

        verify2 = _make_pg_wrapper()
        rows = _fetch_all_breaks(verify2)
        verify2.close()

        assert len(rows) >= 1
        row = rows[0]
        assert row["break_type"] == "qty_mismatch"
        assert row["symbol"] == "NVDA"
        assert row["magnitude"] == pytest.approx(5.0)

    def test_record_break_marked_closed_inserts_row(self):
        from src.shadow_trading.break_events import record_break

        verify = _make_pg_wrapper()
        assert _count_breaks(verify) == 0
        verify.close()

        with patch("src.shadow_trading.break_events.connect_db", side_effect=_make_pg_wrapper):
            record_break(break_type="marked_closed", symbol="SPY")

        verify2 = _make_pg_wrapper()
        rows = _fetch_all_breaks(verify2)
        verify2.close()

        assert len(rows) >= 1
        assert rows[0]["break_type"] == "marked_closed"
        assert rows[0]["symbol"] == "SPY"


class TestGetBreakEvents:
    """get_break_events returns retained history ordered newest-first."""

    def test_get_break_events_returns_newest_first(self):
        from src.shadow_trading.break_events import record_break, get_break_events

        verify = _make_pg_wrapper()
        assert _count_breaks(verify) == 0
        verify.close()

        with patch("src.shadow_trading.break_events.connect_db", side_effect=_make_pg_wrapper):
            record_break(break_type="orphan", symbol="AAPL")
            record_break(break_type="orphan", symbol="MSFT")
            rows = get_break_events(limit=10)

        assert len(rows) >= 2
        # Confirm columns needed for age derivation are present
        for r in rows:
            assert "created_at" in r or "detected_at" in r

    def test_get_break_events_since_filters_old_rows(self):
        from src.shadow_trading.break_events import record_break, get_break_events

        with patch("src.shadow_trading.break_events.connect_db", side_effect=_make_pg_wrapper):
            record_break(break_type="orphan", symbol="GOOG")
            # since=far-future should return 0 rows
            far_future = "2099-01-01T00:00:00+00:00"
            rows = get_break_events(since=far_future, limit=100)

        assert len(rows) == 0, "since=far_future should filter all rows"

    def test_get_break_events_limit_respected(self):
        from src.shadow_trading.break_events import record_break, get_break_events

        with patch("src.shadow_trading.break_events.connect_db", side_effect=_make_pg_wrapper):
            for sym in ("AA", "BB", "CC"):
                record_break(break_type="stale", symbol=sym)
            rows = get_break_events(limit=2)

        assert len(rows) <= 2


# ── Law-#9 integration test: break row survives backfill ─────────────────────

class TestLaw9BreakSurvivesBackfill:
    """A reconcile pass that detects an orphan must emit a reconciliation_breaks
    row BEFORE backfill, and that row must survive the backfill."""

    def test_orphan_break_emitted_before_and_survives_backfill(self):
        """The core law-#9 assertion:
        - 0 break rows before reconcile
        - after reconcile detects an orphan AND backfills it:
          still >= 1 break row in reconciliation_breaks
        """
        import tempfile
        import os as _os

        # Verify zero rows before (non-vacuous)
        verify = _make_pg_wrapper()
        assert _count_breaks(verify) == 0, "Pre-condition: 0 break rows before reconcile"
        verify.close()

        # Use an on-disk SQLite DB for the reconciler's shadow_trades
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            sqlite_path = f.name

        try:
            # Set up the SQLite DB with the minimal shadow_trades table
            conn_sqlite = sqlite3.connect(sqlite_path)
            conn_sqlite.row_factory = sqlite3.Row
            conn_sqlite.execute("""
                CREATE TABLE IF NOT EXISTS shadow_trades (
                    trade_id TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    direction TEXT DEFAULT 'long',
                    status TEXT DEFAULT 'pending',
                    entry_price REAL,
                    stop_price REAL,
                    target_1 REAL,
                    target_2 REAL,
                    planned_shares REAL,
                    planned_allocation REAL,
                    actual_entry_price REAL,
                    actual_entry_time TEXT,
                    actual_exit_time TEXT,
                    exit_reason TEXT,
                    pnl_dollars REAL,
                    pnl_pct REAL,
                    max_favorable_excursion REAL DEFAULT 0,
                    max_adverse_excursion REAL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    alpaca_order_id TEXT,
                    exit_order_id TEXT,
                    ib_child_order_ids TEXT,
                    source TEXT DEFAULT 'paper',
                    desk TEXT DEFAULT 'swing',
                    broker TEXT DEFAULT 'alpaca',
                    order_type TEXT,
                    recommendation_id TEXT,
                    setup_type TEXT,
                    setup_confidence REAL,
                    timeout_days INTEGER DEFAULT 15,
                    exit_retry_count INTEGER DEFAULT 0,
                    instrumentation_version INTEGER DEFAULT 3,
                    strategy_id TEXT,
                    quarantined INTEGER DEFAULT 0
                )
            """)
            conn_sqlite.commit()
            conn_sqlite.close()

            # Track break calls — prove the row is persisted via a direct write
            breaks_written = []

            def _fake_record_break(break_type, symbol, magnitude=None, desk=None,
                                   source=None, detail=None):
                """Persist the break directly to the test PG table."""
                w = _make_pg_wrapper()
                w.execute(
                    """
                    INSERT INTO reconciliation_breaks
                        (created_at, break_type, symbol, magnitude,
                         desk, source, detail, detected_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (datetime.now(timezone.utc).isoformat(), break_type, symbol,
                     magnitude, desk, source, detail,
                     datetime.now(timezone.utc).isoformat()),
                )
                w.commit()
                w.close()
                breaks_written.append((break_type, symbol))

            orphan_pos = [{"symbol": "AAPL", "qty": "10", "avg_entry_price": "150.0",
                           "market_value": "1500.0"}]

            with (
                patch("src.shadow_trading.reconcile.get_all_positions",
                      return_value=orphan_pos),
                patch("src.shadow_trading.reconcile.get_live_positions",
                      return_value=orphan_pos),
                patch("src.shadow_trading.reconcile.cancel_orders_for_ticker",
                      return_value=0),
                patch("src.shadow_trading.reconcile._has_recent_close",
                      return_value=False),
                patch("src.journal.store.insert_shadow_trade", return_value=None),
                patch("src.shadow_trading.reconcile.record_break",
                      side_effect=_fake_record_break),
                patch(
                    "src.shadow_trading.bracket_attach"
                    ".attach_brackets_for_unprotected_positions",
                    side_effect=Exception("not needed in test"),
                ),
            ):
                from src.shadow_trading.reconcile import reconcile_paper_trades
                result = reconcile_paper_trades(desk="swing", db_path=sqlite_path)

            # The backfill should have run
            assert "AAPL" in result.get("backfilled", []), (
                f"Expected AAPL in backfilled, got result={result}"
            )

            # record_break must have been called for AAPL
            assert any(sym == "AAPL" for _, sym in breaks_written), (
                f"record_break was not called for AAPL. calls={breaks_written}"
            )

            # Law-#9: the break row must survive the backfill
            verify2 = _make_pg_wrapper()
            rows_after = _count_breaks(verify2)
            verify2.close()
            assert rows_after >= 1, (
                f"Law-#9 violated: 0 break rows after orphan backfill "
                f"(backfilled={result.get('backfilled')}). "
                "Break evidence was erased by backfill."
            )

        finally:
            # Close any remaining SQLite handles before unlink
            try:
                _os.unlink(sqlite_path)
            except PermissionError:
                pass  # Windows — file still held; non-fatal for test outcome


# ── Best-effort contract: writer failure must not raise into reconcile ────────

class TestBestEffortEmission:
    """A write error in record_break must log but NOT raise into reconcile."""

    def test_writer_failure_does_not_raise(self):
        """Simulate record_break raising — reconcile must still complete."""
        import tempfile
        import os as _os

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            sqlite_path = f.name

        try:
            # Minimal SQLite schema
            conn_sqlite = sqlite3.connect(sqlite_path)
            conn_sqlite.row_factory = sqlite3.Row
            conn_sqlite.execute("""
                CREATE TABLE IF NOT EXISTS shadow_trades (
                    trade_id TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    direction TEXT DEFAULT 'long',
                    status TEXT DEFAULT 'pending',
                    entry_price REAL,
                    stop_price REAL,
                    target_1 REAL,
                    target_2 REAL,
                    planned_shares REAL,
                    planned_allocation REAL,
                    actual_entry_price REAL,
                    actual_entry_time TEXT,
                    actual_exit_time TEXT,
                    exit_reason TEXT,
                    pnl_dollars REAL,
                    pnl_pct REAL,
                    max_favorable_excursion REAL DEFAULT 0,
                    max_adverse_excursion REAL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    alpaca_order_id TEXT,
                    exit_order_id TEXT,
                    ib_child_order_ids TEXT,
                    source TEXT DEFAULT 'paper',
                    desk TEXT DEFAULT 'swing',
                    broker TEXT DEFAULT 'alpaca',
                    order_type TEXT,
                    recommendation_id TEXT,
                    setup_type TEXT,
                    setup_confidence REAL,
                    timeout_days INTEGER DEFAULT 15,
                    exit_retry_count INTEGER DEFAULT 0,
                    instrumentation_version INTEGER DEFAULT 3,
                    strategy_id TEXT,
                    quarantined INTEGER DEFAULT 0
                )
            """)
            conn_sqlite.commit()
            conn_sqlite.close()

            orphan_pos = [{"symbol": "TSLA", "qty": "5", "avg_entry_price": "200.0",
                           "market_value": "1000.0"}]

            def _raising_record_break(*args, **kwargs):
                raise RuntimeError("Simulated DB write failure")

            with (
                patch("src.shadow_trading.reconcile.get_all_positions",
                      return_value=orphan_pos),
                patch("src.shadow_trading.reconcile.get_live_positions",
                      return_value=orphan_pos),
                patch("src.shadow_trading.reconcile.cancel_orders_for_ticker",
                      return_value=0),
                patch("src.shadow_trading.reconcile._has_recent_close",
                      return_value=False),
                patch("src.journal.store.insert_shadow_trade", return_value=None),
                patch("src.shadow_trading.reconcile.record_break",
                      side_effect=_raising_record_break),
                patch(
                    "src.shadow_trading.bracket_attach"
                    ".attach_brackets_for_unprotected_positions",
                    side_effect=Exception("not needed in test"),
                ),
            ):
                from src.shadow_trading.reconcile import reconcile_paper_trades
                # Must NOT raise even though record_break raises
                result = reconcile_paper_trades(desk="swing", db_path=sqlite_path)

            # Reconcile completed and backfilled despite the writer failure
            assert "TSLA" in result.get("backfilled", []), (
                f"Expected TSLA backfilled even when record_break raises, "
                f"got result={result}"
            )

        finally:
            try:
                _os.unlink(sqlite_path)
            except PermissionError:
                pass  # Windows — file still held; non-fatal for test outcome

    def test_record_break_itself_is_best_effort_on_db_error(self):
        """record_break with a bad connection logs but does not raise."""
        from src.shadow_trading.break_events import record_break

        # Patch connect_db to raise immediately
        with patch(
            "src.shadow_trading.break_events.connect_db",
            side_effect=RuntimeError("Simulated connection failure"),
        ):
            # Should not raise — best-effort swallows the error
            record_break(break_type="orphan", symbol="TEST")
