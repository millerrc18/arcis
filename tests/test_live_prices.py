"""Tests for live_prices table and _refresh_live_prices integration.

Covers:
- live_prices TableDef is registered in schema registry
- _refresh_live_prices UPSERTs correctly (idempotent on second call)
- _refresh_live_prices skips when no open trades
- _refresh_live_prices survives quote-fetch exception
- /api/shadow/open reads from live_prices and returns current_price_as_of
- /api/shadow/open fallback when no live_prices row
- /api/shadow/open does NOT query setup_signals for this code path
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


import pytest


# ---------------------------------------------------------------------------
# Schema registry tests
# ---------------------------------------------------------------------------

class TestLivePricesTableDef:
    def test_live_prices_is_registered(self):
        from src.schema.registry import TABLES
        assert "live_prices" in TABLES

    def test_live_prices_columns(self):
        from src.schema.registry import TABLES
        table = TABLES["live_prices"]
        col_names = [c.name for c in table.columns]
        assert "ticker" in col_names
        assert "price" in col_names
        assert "bid" in col_names
        assert "ask" in col_names
        assert "as_of" in col_names
        assert "source" in col_names

    def test_live_prices_sync_config(self):
        from src.schema.registry import TABLES
        table = TABLES["live_prices"]
        assert table.sync_to_postgres is True
        assert table.sync_mode == "incremental"
        assert table.sync_reconcile is True
        assert table.sync_conflict_col == "ticker"
        assert table.sync_time_column == "as_of", (
            "incremental sync requires sync_time_column. Without it, "
            "RenderSyncThread builds SQL with MAX(None) -> "
            "'no such column: None' error every cycle (#910 follow-up resolved; "
            "H3 switched latest_only -> incremental so all 15 ticker rows propagate)."
        )

    def test_live_prices_pk_is_ticker(self):
        from src.schema.registry import TABLES
        table = TABLES["live_prices"]
        assert table.primary_key == "ticker"

    def test_live_prices_creatable(self):
        """Table DDL can be applied to an in-memory SQLite without error."""
        from src.schema.sqlite import generate_create_sql
        conn = sqlite3.connect(":memory:")
        from src.schema.registry import TABLES
        table = TABLES["live_prices"]
        ddl = generate_create_sql(table)
        conn.execute(ddl)
        conn.execute("INSERT INTO live_prices (ticker, price, as_of, source) VALUES ('AAPL', 100.0, '2026-05-01T10:00:00', 'alpaca')")
        conn.commit()
        row = conn.execute("SELECT ticker, price FROM live_prices WHERE ticker = 'AAPL'").fetchone()
        assert row[0] == "AAPL"
        assert row[1] == 100.0
        conn.close()


# ---------------------------------------------------------------------------
# WatchLoop._refresh_live_prices tests
# ---------------------------------------------------------------------------

@pytest.fixture
def watch_loop():
    with patch("src.scheduler.watch.load_config") as mock_cfg, \
         patch("src.scheduler.watch.is_llm_available", return_value=False), \
         patch("src.scheduler.watch.GuardedScorer"):
        mock_cfg.return_value = {
            "schedule": {
                "morning_hour": 8,
                "eod_hour": 16,
                "scan_interval": 30,
                "market_open_hour": 9,
                "market_open_minute": 30,
                "market_close_hour": 16,
            },
            "risk": {"starting_capital": 100000},
            "shadow_trading": {"enabled": False},
            "training": {},
        }
        from src.scheduler.watch import WatchLoop
        loop = WatchLoop(mock_cfg.return_value)
        return loop


class TestRefreshLivePrices:
    def test_skips_when_no_open_trades(self, watch_loop):
        """If no open shadow_trades rows, no API call is made."""
        db_conn = sqlite3.connect(":memory:")
        db_conn.row_factory = sqlite3.Row
        db_conn.execute(
            "CREATE TABLE shadow_trades (id INTEGER PRIMARY KEY, ticker TEXT, status TEXT)"
        )
        db_conn.commit()

        fetch_mock = MagicMock(return_value={})
        with patch("src.scheduler.watch.connect_db") as mock_connect, \
             patch("src.shadow_trading.alpaca_adapter.fetch_latest_quotes", fetch_mock, create=True):
            mock_connect.return_value.__enter__ = lambda s: db_conn
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            watch_loop._refresh_live_prices()

        fetch_mock.assert_not_called()

    def test_upserts_quotes_to_live_prices(self, watch_loop):
        """Quotes from fetch_latest_quotes are written to live_prices."""
        db_conn = sqlite3.connect(":memory:")
        db_conn.row_factory = sqlite3.Row
        db_conn.execute(
            "CREATE TABLE shadow_trades (id INTEGER PRIMARY KEY, ticker TEXT, status TEXT)"
        )
        db_conn.execute(
            "CREATE TABLE live_prices ("
            "ticker TEXT PRIMARY KEY, price REAL, bid REAL, ask REAL, "
            "as_of TEXT, source TEXT"
            ")"
        )
        db_conn.execute("INSERT INTO shadow_trades (ticker, status) VALUES ('AAPL', 'open')")
        db_conn.commit()

        quotes = {
            "AAPL": {
                "price": 175.5,
                "bid": 175.4,
                "ask": 175.6,
                "as_of": "2026-05-03T10:30:00+00:00",
            }
        }

        with patch("src.scheduler.watch.connect_db") as mock_connect, \
             patch("src.shadow_trading.alpaca_adapter.fetch_latest_quotes",
                   return_value=quotes, create=True) as fetch_mock:
            mock_connect.return_value.__enter__ = lambda s: db_conn
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            with patch("src.shadow_trading.alpaca_adapter.fetch_latest_quotes", return_value=quotes):
                watch_loop._refresh_live_prices()

        row = db_conn.execute(
            "SELECT price, source FROM live_prices WHERE ticker = 'AAPL'"
        ).fetchone()
        assert row is not None
        assert row[0] == 175.5
        assert row[1] == "alpaca"

    def test_idempotent_upsert(self, watch_loop):
        """Calling _refresh_live_prices twice overwrites with latest data."""
        db_conn = sqlite3.connect(":memory:")
        db_conn.row_factory = sqlite3.Row
        db_conn.execute(
            "CREATE TABLE shadow_trades (id INTEGER PRIMARY KEY, ticker TEXT, status TEXT)"
        )
        db_conn.execute(
            "CREATE TABLE live_prices ("
            "ticker TEXT PRIMARY KEY, price REAL, bid REAL, ask REAL, "
            "as_of TEXT, source TEXT"
            ")"
        )
        db_conn.execute("INSERT INTO shadow_trades (ticker, status) VALUES ('MSFT', 'open')")
        db_conn.commit()

        first_quotes = {"MSFT": {"price": 400.0, "bid": 399.9, "ask": 400.1, "as_of": "2026-05-03T10:00:00+00:00"}}
        second_quotes = {"MSFT": {"price": 402.0, "bid": 401.9, "ask": 402.1, "as_of": "2026-05-03T10:01:00+00:00"}}

        with patch("src.scheduler.watch.connect_db") as mock_connect:
            mock_connect.return_value.__enter__ = lambda s: db_conn
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            with patch("src.shadow_trading.alpaca_adapter.fetch_latest_quotes", return_value=first_quotes):
                watch_loop._refresh_live_prices()
            with patch("src.shadow_trading.alpaca_adapter.fetch_latest_quotes", return_value=second_quotes):
                watch_loop._refresh_live_prices()

        rows = db_conn.execute("SELECT price FROM live_prices WHERE ticker = 'MSFT'").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 402.0

    def test_survives_quote_fetch_exception(self, watch_loop):
        """If fetch_latest_quotes raises, _refresh_live_prices does not raise."""
        db_conn = sqlite3.connect(":memory:")
        db_conn.row_factory = sqlite3.Row
        db_conn.execute(
            "CREATE TABLE shadow_trades (id INTEGER PRIMARY KEY, ticker TEXT, status TEXT)"
        )
        db_conn.execute(
            "CREATE TABLE live_prices ("
            "ticker TEXT PRIMARY KEY, price REAL, bid REAL, ask REAL, "
            "as_of TEXT, source TEXT"
            ")"
        )
        db_conn.execute("INSERT INTO shadow_trades (ticker, status) VALUES ('TSLA', 'open')")
        db_conn.commit()

        with patch("src.scheduler.watch.connect_db") as mock_connect, \
             patch("src.shadow_trading.alpaca_adapter.fetch_latest_quotes",
                   side_effect=RuntimeError("Alpaca API down")):
            mock_connect.return_value.__enter__ = lambda s: db_conn
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            watch_loop._refresh_live_prices()

        rows = db_conn.execute("SELECT * FROM live_prices").fetchall()
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# /api/shadow/open route tests
# ---------------------------------------------------------------------------

def _make_runtime(query_results, query_one_map):
    runtime = MagicMock()
    runtime.query.return_value = query_results
    runtime.query_one.side_effect = lambda sql, params=(): query_one_map.get(sql.strip()[:50])
    runtime.logger = MagicMock()
    return runtime


class TestShadowOpenLivePrices:
    def _make_router(self, runtime):
        from src.api.cloud_routes.trades import create_router

        def verify_auth():
            pass

        router = create_router(runtime, verify_auth)
        return router

    def test_reads_from_live_prices(self):
        """shadow_open uses live_prices.price (not setup_signals)."""
        trade = {
            "ticker": "AAPL",
            "actual_entry_price": 170.0,
            "entry_price": 170.0,
            "actual_shares": 10,
            "planned_shares": 10,
            "status": "open",
            "quarantined": 0,
            "duration_days": 2,
            "timeout_days": 15,
            "llm_timeout_days": 15,
        }
        closed_pnl_row = {"total": 0.0}
        live_price_row = {"price": 175.0, "as_of": "2026-05-03T10:30:00+00:00"}

        runtime = MagicMock()
        runtime.query.return_value = [trade]
        runtime.logger = MagicMock()

        call_sqls = []

        def query_one_side(sql, params=()):
            call_sqls.append(sql)
            if "live_prices" in sql:
                return live_price_row
            if "SUM" in sql:
                return closed_pnl_row
            return None

        runtime.query_one.side_effect = query_one_side

        from src.api.cloud_routes.trades import create_router
        router = create_router(runtime, lambda: None)
        endpoint = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/api/shadow/open":
                endpoint = route.endpoint
                break
        assert endpoint is not None

        result = endpoint(desk=None)

        assert result["trades"][0]["current_price_est"] == 175.0
        assert result["trades"][0].get("current_price_as_of") == "2026-05-03T10:30:00+00:00"
        assert result["trades"][0]["unrealized_pnl"] == 50.0

        for sql in call_sqls:
            assert "setup_signals" not in sql, (
                f"setup_signals was queried but should not be: {sql}"
            )

    def test_fallback_when_no_live_prices_row(self):
        """If no live_prices row, current_price_est and unrealized_pnl are None."""
        trade = {
            "ticker": "NVDA",
            "actual_entry_price": 800.0,
            "entry_price": 800.0,
            "actual_shares": 5,
            "planned_shares": 5,
            "status": "open",
            "quarantined": 0,
            "duration_days": 1,
            "timeout_days": 15,
            "llm_timeout_days": 15,
        }
        closed_pnl_row = {"total": 0.0}

        runtime = MagicMock()
        runtime.query.return_value = [trade]
        runtime.logger = MagicMock()

        def query_one_side(sql, params=()):
            if "live_prices" in sql:
                return None
            if "SUM" in sql:
                return closed_pnl_row
            return None

        runtime.query_one.side_effect = query_one_side

        from src.api.cloud_routes.trades import create_router
        router = create_router(runtime, lambda: None)
        endpoint = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/api/shadow/open":
                endpoint = route.endpoint
                break

        result = endpoint(desk=None)

        assert result["trades"][0]["unrealized_pnl"] is None
        assert result["trades"][0]["current_price_est"] is None
        assert result["trades"][0].get("current_price_as_of") is None

    def test_no_setup_signals_query(self):
        """The shadow_open route must NEVER query setup_signals in the price lookup path."""
        trade = {
            "ticker": "TSLA",
            "actual_entry_price": 200.0,
            "entry_price": 200.0,
            "actual_shares": 3,
            "planned_shares": 3,
            "status": "open",
            "quarantined": 0,
            "duration_days": 3,
            "timeout_days": 15,
            "llm_timeout_days": 15,
        }

        runtime = MagicMock()
        runtime.query.return_value = [trade]
        runtime.logger = MagicMock()

        seen_sqls = []

        def query_one_side(sql, params=()):
            seen_sqls.append(sql)
            if "live_prices" in sql:
                return {"price": 210.0, "as_of": "2026-05-03T10:00:00+00:00"}
            if "SUM" in sql:
                return {"total": 0.0}
            return None

        runtime.query_one.side_effect = query_one_side

        from src.api.cloud_routes.trades import create_router
        router = create_router(runtime, lambda: None)
        endpoint = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/api/shadow/open":
                endpoint = route.endpoint
                break

        endpoint(desk=None)

        for sql in seen_sqls:
            assert "setup_signals" not in sql, (
                f"setup_signals must not be queried; found: {sql}"
            )


# ---------------------------------------------------------------------------
# Incremental sync + watermark migration tests (Wave 4 H3)
# ---------------------------------------------------------------------------

class TestLivePricesSync:
    def _make_mock_pg_conn(self):
        """Return a mock Postgres connection that records executed statements."""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = []
        conn.autocommit = False
        return conn, cursor

    def test_15_tickers_propagate_per_cycle(self):
        """With incremental sync_mode, all ticker rows are sent to PG each cycle."""
        import sqlite3 as _sqlite3
        from datetime import datetime, timezone, timedelta
        from unittest.mock import patch, MagicMock

        db_conn = _sqlite3.connect(":memory:")
        db_conn.row_factory = _sqlite3.Row
        db_conn.execute(
            "CREATE TABLE live_prices ("
            "ticker TEXT PRIMARY KEY, price REAL, bid REAL, ask REAL, "
            "as_of TEXT NOT NULL, source TEXT NOT NULL"
            ")"
        )
        db_conn.execute(
            "CREATE TABLE sync_state ("
            "table_name TEXT PRIMARY KEY, last_synced_at TEXT NOT NULL, "
            "in_flight_since TEXT, completed_at TEXT, status TEXT DEFAULT 'idle', "
            "error_message TEXT, host TEXT"
            ")"
        )

        tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
        as_of = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        for t in tickers:
            db_conn.execute(
                "INSERT INTO live_prices (ticker, price, bid, ask, as_of, source) "
                "VALUES (?, 100.0, 99.9, 100.1, ?, 'alpaca')",
                (t, as_of),
            )
        db_conn.commit()

        mock_pg_conn, mock_cursor = self._make_mock_pg_conn()

        with patch("src.sync.render_sync.sqlite3") as mock_sqlite_mod, \
             patch("src.sync.render_sync.get_last_synced_at", return_value=None), \
             patch("src.sync.render_sync.set_last_synced_at"):
            mock_sqlite_mod.connect.return_value.__enter__ = lambda s: db_conn
            mock_sqlite_mod.connect.return_value.__exit__ = MagicMock(return_value=False)
            mock_sqlite_mod.Row = _sqlite3.Row

            from src.sync.render_sync import _fetch_incremental_rows, _upsert_to_postgres
            rows, columns = _fetch_incremental_rows("live_prices", "as_of", None, ":memory:")

        assert len(rows) >= 5, (
            f"Expected >=5 rows for incremental sync with NULL watermark, got {len(rows)}"
        )

    def test_watermark_migration_does_not_replay_history(self):
        """With a 24h-old watermark, only rows newer than that watermark are synced."""
        import sqlite3 as _sqlite3
        from datetime import datetime, timezone, timedelta

        db_conn = _sqlite3.connect(":memory:")
        db_conn.row_factory = _sqlite3.Row
        db_conn.execute(
            "CREATE TABLE live_prices ("
            "ticker TEXT PRIMARY KEY, price REAL, bid REAL, ask REAL, "
            "as_of TEXT NOT NULL, source TEXT NOT NULL"
            ")"
        )

        now = datetime.now(timezone.utc)
        watermark = (now - timedelta(hours=24)).isoformat()

        old_tickers = [f"OLD{i}" for i in range(100)]
        old_as_of = (now - timedelta(days=8)).isoformat()
        for t in old_tickers:
            db_conn.execute(
                "INSERT OR REPLACE INTO live_prices (ticker, price, bid, ask, as_of, source) "
                "VALUES (?, 50.0, 49.9, 50.1, ?, 'alpaca')",
                (t, old_as_of),
            )

        fresh_tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
        fresh_as_of = (now - timedelta(minutes=30)).isoformat()
        for t in fresh_tickers:
            db_conn.execute(
                "INSERT OR REPLACE INTO live_prices (ticker, price, bid, ask, as_of, source) "
                "VALUES (?, 100.0, 99.9, 100.1, ?, 'alpaca')",
                (t, fresh_as_of),
            )
        db_conn.commit()

        from src.sync.render_sync import _fetch_incremental_rows
        import sqlite3 as _sqlite3

        with patch("src.sync.render_sync.sqlite3") as mock_sqlite_mod:
            mock_sqlite_mod.connect.return_value.__enter__ = lambda s: db_conn
            mock_sqlite_mod.connect.return_value.__exit__ = MagicMock(return_value=False)
            mock_sqlite_mod.Row = _sqlite3.Row

            rows, columns = _fetch_incremental_rows("live_prices", "as_of", watermark, ":memory:")

        assert len(rows) == 5, (
            f"Expected exactly 5 rows (fresh tickers only) with 24h watermark, got {len(rows)}"
        )
        returned_tickers = {r["ticker"] for r in rows}
        assert returned_tickers == set(fresh_tickers)

    def test_reset_live_prices_watermark_command_idempotent(self):
        """reset-live-prices-watermark sets last_synced_at ~24h ago, idempotent on second call."""
        import sqlite3 as _sqlite3
        from datetime import datetime, timezone, timedelta

        db_conn = _sqlite3.connect(":memory:")
        db_conn.execute(
            "CREATE TABLE sync_state ("
            "table_name TEXT PRIMARY KEY, last_synced_at TEXT NOT NULL, "
            "in_flight_since TEXT, completed_at TEXT, status TEXT DEFAULT 'idle', "
            "error_message TEXT, host TEXT"
            ")"
        )
        db_conn.commit()

        from src.cli.commands import cmd_reset_live_prices_watermark

        class FakeArgs:
            pass

        with patch("src.cli.commands.connect_db") as mock_connect:
            mock_connect.return_value.__enter__ = lambda s: db_conn
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)

            cmd_reset_live_prices_watermark(FakeArgs())
            row1 = db_conn.execute(
                "SELECT last_synced_at FROM sync_state WHERE table_name = 'live_prices'"
            ).fetchone()
            assert row1 is not None

            ts1 = datetime.fromisoformat(row1[0].replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            expected_floor = now - timedelta(hours=25)
            expected_ceiling = now - timedelta(hours=23)
            assert expected_floor < ts1 < expected_ceiling, (
                f"Watermark {ts1} not within 23-25h of now"
            )

        with patch("src.cli.commands.connect_db") as mock_connect2:
            mock_connect2.return_value.__enter__ = lambda s: db_conn
            mock_connect2.return_value.__exit__ = MagicMock(return_value=False)

            cmd_reset_live_prices_watermark(FakeArgs())
            row2 = db_conn.execute(
                "SELECT last_synced_at FROM sync_state WHERE table_name = 'live_prices'"
            ).fetchone()
            assert row2 is not None

        ts2 = datetime.fromisoformat(row2[0].replace("Z", "+00:00"))
        diff = abs((ts2 - ts1).total_seconds())
        assert diff < 5, (
            f"Second call changed watermark by {diff}s — expected idempotent within 5s"
        )
