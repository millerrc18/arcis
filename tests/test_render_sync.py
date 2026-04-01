"""Tests for the Render sync background thread."""

import sqlite3
import threading
import time
from unittest.mock import MagicMock, patch, call

import pytest

from src.sync.render_sync import (
    SYNC_TABLES,
    RenderSyncThread,
    TableFetchError,
    _fetch_full_rows,
    _fetch_incremental_rows,
    _fetch_latest_rows,
    _init_sync_state,
    _upsert_to_postgres,
    _replace_latest_in_postgres,
    get_last_synced_at,
    run_sync_cycle,
    set_last_synced_at,
    start_render_sync,
    sync_table,
)


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary SQLite database with test data."""
    db_path = str(tmp_path / "test.sqlite3")
    conn = sqlite3.connect(db_path)

    # Create shadow_trades table
    conn.execute("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            pnl_dollars REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # Create council_sessions and council_votes
    conn.execute("""
        CREATE TABLE council_sessions (
            session_id TEXT PRIMARY KEY,
            session_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE council_votes (
            vote_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            round INTEGER NOT NULL
        )
    """)

    # Create vix_term_structure (latest_only table)
    conn.execute("""
        CREATE TABLE vix_term_structure (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collected_date TEXT NOT NULL,
            vix REAL,
            collected_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE traffic_light_state (
            id INTEGER PRIMARY KEY,
            current_regime TEXT NOT NULL,
            updated_at TEXT
        )
    """)

    # Insert test data
    conn.execute(
        "INSERT INTO shadow_trades VALUES (?, ?, ?, ?, ?, ?)",
        ("t1", "AAPL", "open", None, "2025-01-01T10:00:00", "2025-01-01T10:00:00"),
    )
    conn.execute(
        "INSERT INTO shadow_trades VALUES (?, ?, ?, ?, ?, ?)",
        ("t2", "MSFT", "closed", 150.0, "2025-01-02T10:00:00", "2025-01-02T12:00:00"),
    )
    conn.execute(
        "INSERT INTO shadow_trades VALUES (?, ?, ?, ?, ?, ?)",
        ("t3", "GOOG", "open", None, "2025-01-03T10:00:00", "2025-01-03T10:00:00"),
    )

    conn.execute(
        "INSERT INTO council_sessions VALUES (?, ?, ?)",
        ("s1", "weekly", "2025-01-01T10:00:00"),
    )
    conn.execute(
        "INSERT INTO council_votes VALUES (?, ?, ?, ?)",
        ("v1", "s1", "technician", 1),
    )
    conn.execute(
        "INSERT INTO council_votes VALUES (?, ?, ?, ?)",
        ("v2", "s1", "fundamentalist", 1),
    )

    conn.execute(
        "INSERT INTO vix_term_structure (collected_date, vix, collected_at) VALUES (?, ?, ?)",
        ("2025-01-01", 18.5, "2025-01-01T09:00:00"),
    )
    conn.execute(
        "INSERT INTO vix_term_structure (collected_date, vix, collected_at) VALUES (?, ?, ?)",
        ("2025-01-02", 19.2, "2025-01-02T09:00:00"),
    )
    conn.execute(
        "INSERT INTO traffic_light_state VALUES (?, ?, ?)",
        (1, "GREEN", "2025-01-02T09:05:00"),
    )

    conn.commit()
    conn.close()
    return db_path


# ── Sync state tests ─────────────────────────────────────────────────

class TestSyncState:
    """Tests for sync state tracking."""

    def test_init_sync_state_creates_table(self, test_db):
        _init_sync_state(test_db)
        conn = sqlite3.connect(test_db)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sync_state'"
        ).fetchall()
        conn.close()
        assert len(tables) == 1

    def test_get_last_synced_at_returns_none_when_empty(self, test_db):
        _init_sync_state(test_db)
        result = get_last_synced_at("shadow_trades", test_db)
        assert result is None

    def test_set_and_get_last_synced_at(self, test_db):
        _init_sync_state(test_db)
        set_last_synced_at("shadow_trades", "2025-01-02T10:00:00", test_db)
        result = get_last_synced_at("shadow_trades", test_db)
        assert result == "2025-01-02T10:00:00"

    def test_set_last_synced_at_upserts(self, test_db):
        _init_sync_state(test_db)
        set_last_synced_at("shadow_trades", "2025-01-01T00:00:00", test_db)
        set_last_synced_at("shadow_trades", "2025-01-02T00:00:00", test_db)
        result = get_last_synced_at("shadow_trades", test_db)
        assert result == "2025-01-02T00:00:00"


# ── Incremental fetch tests ──────────────────────────────────────────

class TestIncrementalFetch:
    """Tests for incremental row fetching from SQLite."""

    def test_fetch_all_rows_when_no_since(self, test_db):
        rows, cols = _fetch_incremental_rows(
            "shadow_trades", "updated_at", None, test_db
        )
        assert len(rows) == 3
        assert "trade_id" in cols

    def test_fetch_only_new_rows(self, test_db):
        rows, cols = _fetch_incremental_rows(
            "shadow_trades", "updated_at", "2025-01-01T10:00:00", test_db
        )
        assert len(rows) == 2  # t2 and t3
        tickers = {r["ticker"] for r in rows}
        assert "MSFT" in tickers
        assert "GOOG" in tickers
        assert "AAPL" not in tickers

    def test_fetch_returns_empty_for_nonexistent_table(self, test_db):
        with pytest.raises(TableFetchError, match="nonexistent_table"):
            _fetch_incremental_rows(
                "nonexistent_table", "created_at", None, test_db
            )


# ── Latest-only fetch tests ──────────────────────────────────────────

class TestLatestFetch:
    """Tests for latest-only snapshot fetching."""

    def test_fetch_latest_rows_only(self, test_db):
        rows, cols = _fetch_latest_rows(
            "vix_term_structure", "collected_date", test_db
        )
        assert len(rows) == 1
        assert rows[0]["collected_date"] == "2025-01-02"
        assert rows[0]["vix"] == 19.2


class TestFullFetch:
    """Tests for full-table snapshot fetching."""

    def test_fetch_full_rows(self, test_db):
        rows, cols = _fetch_full_rows("traffic_light_state", test_db)
        assert len(rows) == 1
        assert rows[0]["current_regime"] == "GREEN"
        assert "id" in cols


# ── Postgres upsert tests (mocked) ──────────────────────────────────

class TestPostgresUpsert:
    """Tests for Postgres upsert with mocked connection."""

    def test_upsert_to_postgres_success(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        columns = ["trade_id", "ticker", "status"]
        rows = [
            {"trade_id": "t1", "ticker": "AAPL", "status": "open"},
            {"trade_id": "t2", "ticker": "MSFT", "status": "closed"},
        ]

        count = _upsert_to_postgres(mock_conn, "shadow_trades", "trade_id", columns, rows)

        assert count == 2
        assert mock_cursor.execute.call_count == 2
        mock_conn.commit.assert_called_once()
        mock_cursor.close.assert_called_once()

    def test_upsert_empty_rows_returns_zero(self):
        mock_conn = MagicMock()
        count = _upsert_to_postgres(mock_conn, "shadow_trades", "trade_id", [], [])
        assert count == 0

    def test_upsert_handles_postgres_error(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("connection lost")

        with pytest.raises(Exception, match="connection lost"):
            _upsert_to_postgres(
                mock_conn,
                "shadow_trades",
                "trade_id",
                ["trade_id", "ticker"],
                [{"trade_id": "t1", "ticker": "AAPL"}],
            )

        mock_conn.rollback.assert_called_once()

    def test_replace_latest_in_postgres(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        columns = ["id", "collected_date", "vix"]
        rows = [{"id": 1, "collected_date": "2025-01-02", "vix": 19.2}]

        count = _replace_latest_in_postgres(
            mock_conn, "vix_term_structure", "collected_date", columns, rows
        )

        assert count == 1
        # Should have DELETE + INSERT calls
        assert mock_cursor.execute.call_count == 2
        mock_conn.commit.assert_called_once()


# ── Sync table tests ─────────────────────────────────────────────────

class TestSyncTable:
    """Tests for the sync_table orchestrator."""

    def test_sync_table_incremental(self, test_db):
        _init_sync_state(test_db)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        config = {"mode": "incremental", "time_col": "updated_at", "pk": "trade_id"}
        count = sync_table(mock_conn, "shadow_trades", config, test_db)

        assert count == 3  # All rows (no previous sync)
        # Verify sync state was updated
        last = get_last_synced_at("shadow_trades", test_db)
        assert last == "2025-01-03T10:00:00"

    def test_sync_table_latest_only(self, test_db):
        _init_sync_state(test_db)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        config = {"mode": "latest_only", "time_col": "collected_date", "pk": "id"}
        count = sync_table(mock_conn, "vix_term_structure", config, test_db)

        assert count == 1  # Only latest date's row

    def test_sync_table_full_mode(self, test_db):
        _init_sync_state(test_db)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        config = {"mode": "full", "pk": "id"}
        count = sync_table(mock_conn, "traffic_light_state", config, test_db)

        assert count == 1

    def test_sync_table_rejects_unknown_mode(self, test_db):
        _init_sync_state(test_db)
        mock_conn = MagicMock()

        with pytest.raises(ValueError, match="Unknown sync mode"):
            sync_table(mock_conn, "shadow_trades", {"mode": "mystery", "pk": "trade_id"}, test_db)


# ── Full sync cycle tests ────────────────────────────────────────────

class TestRunSyncCycle:
    """Tests for the full sync cycle."""

    def test_connection_failure_logged(self, test_db):
        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.side_effect = Exception("connection refused")

        with patch.dict("sys.modules", {"psycopg2": mock_psycopg2}):
            summary = run_sync_cycle("postgresql://bad:url@localhost/db", test_db)

        assert len(summary["errors"]) > 0
        assert "connection_failed" in summary["errors"][0]

    def test_sync_cycle_continues_on_table_error(self, test_db):
        _init_sync_state(test_db)
        mock_psycopg2 = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        # Make the cursor raise on the first execute, then succeed
        call_count = [0]
        original_execute = mock_cursor.execute

        def failing_execute(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise Exception("table not found")
            return original_execute(*args, **kwargs)

        mock_cursor.execute.side_effect = failing_execute

        with patch.dict("sys.modules", {"psycopg2": mock_psycopg2}):
            summary = run_sync_cycle("postgresql://test@localhost/db", test_db)

        # Should have errors but also continue trying other tables
        assert "errors" in summary
        assert "timestamp" in summary

    def test_sync_cycle_surfaces_missing_table_error(self, test_db):
        _init_sync_state(test_db)
        mock_psycopg2 = MagicMock()
        mock_conn = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn

        original_config = SYNC_TABLES["shadow_trades"]
        SYNC_TABLES["shadow_trades"] = {
            "mode": "incremental",
            "time_col": "updated_at",
            "pk": "trade_id",
        }

        try:
            with sqlite3.connect(test_db) as conn:
                conn.execute("DROP TABLE shadow_trades")
                conn.commit()

            with patch.dict("sys.modules", {"psycopg2": mock_psycopg2}):
                summary = run_sync_cycle("postgresql://test@localhost/db", test_db)
        finally:
            SYNC_TABLES["shadow_trades"] = original_config

        assert any("shadow_trades:" in err for err in summary["errors"])


# ── Config and start tests ───────────────────────────────────────────

class TestStartRenderSync:
    """Tests for config-driven thread startup."""

    def test_disabled_config_returns_none(self):
        config = {"render": {"enabled": False}}
        result = start_render_sync(config)
        assert result is None

    def test_missing_render_config_returns_none(self):
        config = {}
        result = start_render_sync(config)
        assert result is None

    def test_enabled_but_no_url_returns_none(self):
        config = {"render": {"enabled": True, "database_url": ""}}
        result = start_render_sync(config)
        assert result is None

    @patch("src.sync.render_sync.RenderSyncThread")
    def test_enabled_with_url_starts_thread(self, MockThread):
        mock_instance = MagicMock()
        MockThread.return_value = mock_instance

        config = {
            "render": {
                "enabled": True,
                "database_url": "postgresql://user:pass@host:5432/halcyon",
                "sync_interval_seconds": 60,
            }
        }
        result = start_render_sync(config)

        MockThread.assert_called_once_with(
            database_url="postgresql://user:pass@host:5432/halcyon",
            interval_seconds=60,
            on_commands_pulled=None,
        )
        mock_instance.start.assert_called_once()

    def test_default_interval_is_120(self):
        thread = RenderSyncThread(
            database_url="postgresql://test@localhost/db"
        )
        assert thread.interval_seconds == 120
        assert thread.daemon is True

    def test_thread_stop_event(self):
        thread = RenderSyncThread(
            database_url="postgresql://test@localhost/db"
        )
        assert not thread._stop_event.is_set()
        thread.stop()
        assert thread._stop_event.is_set()


# ── SYNC_TABLES configuration tests ─────────────────────────────────

class TestSyncTablesConfig:
    """Verify the SYNC_TABLES configuration is complete."""

    def test_all_tables_have_required_keys(self):
        for table_name, config in SYNC_TABLES.items():
            assert "mode" in config, f"{table_name} missing 'mode'"
            assert "pk" in config, f"{table_name} missing 'pk'"
            assert config["mode"] in ("incremental", "latest_only", "full"), (
                f"{table_name} has invalid mode: {config['mode']}"
            )

    def test_options_chains_synced(self):
        assert "options_chains" in SYNC_TABLES
        assert SYNC_TABLES["options_chains"]["mode"] == "latest_only"

    def test_google_trends_synced(self):
        assert "google_trends" in SYNC_TABLES
        assert SYNC_TABLES["google_trends"]["mode"] == "latest_only"

    def test_cboe_ratios_synced(self):
        assert "cboe_ratios" in SYNC_TABLES
        assert SYNC_TABLES["cboe_ratios"]["mode"] == "latest_only"

    def test_training_examples_synced(self):
        assert "training_examples" in SYNC_TABLES

    def test_expected_tables_present(self):
        expected = [
            "shadow_trades", "recommendations", "model_versions",
            "metric_snapshots", "audit_reports", "schedule_metrics",
            "earnings_calendar", "options_metrics", "vix_term_structure",
            "macro_snapshots", "council_sessions", "council_votes",
            "api_costs", "training_examples",
        ]
        for table in expected:
            assert table in SYNC_TABLES, f"Missing table: {table}"

    def test_latest_only_tables(self):
        latest_only = [
            name for name, cfg in SYNC_TABLES.items()
            if cfg["mode"] == "latest_only"
        ]
        assert "options_metrics" in latest_only
        assert "vix_term_structure" in latest_only
        assert "macro_snapshots" in latest_only
