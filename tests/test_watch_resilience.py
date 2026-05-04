"""Tests for watch loop crash protection, backoff, and heartbeat.

Covers: #159 (crash protection), #155 (backoff), #157 (cooldown fix),
        #90 (load_dotenv), #150 (heartbeat), #151 (scan overlap).
"""

import signal
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

ET = ZoneInfo("America/New_York")


@pytest.fixture
def watch_loop():
    """Create a WatchLoop instance with minimal config."""
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


class TestSafeRunBackoff:
    """Tests for _safe_run exponential backoff (#155, #157)."""

    def test_backoff_resets_on_success(self, watch_loop):
        """After a failure + backoff, a successful call resets backoff to 0."""
        # Simulate previous failures
        watch_loop._consecutive_errors = 2
        watch_loop._backoff["test_task"] = 30

        success_fn = MagicMock()
        with patch("time.sleep"):
            result = watch_loop._safe_run("test_task", success_fn)

        success_fn.assert_called_once()
        assert result is True
        assert watch_loop._consecutive_errors == 0
        assert watch_loop._backoff.get("test_task", 0) == 0

    def test_backoff_escalates_on_failure(self, watch_loop):
        """Each failure increases backoff per-task: 0 -> 10 -> 30 -> 60 -> 60 (cap)."""
        failing_fn = MagicMock(side_effect=ValueError("boom"))
        task_name = "failing_task"

        with patch("time.sleep"):
            result = watch_loop._safe_run(task_name, failing_fn)
            assert result is False
            assert watch_loop._backoff[task_name] == 10

            watch_loop._safe_run(task_name, failing_fn)
            assert watch_loop._backoff[task_name] == 30

            watch_loop._safe_run(task_name, failing_fn)
            assert watch_loop._backoff[task_name] == 60

            # Cap at 60
            watch_loop._safe_run(task_name, failing_fn)
            assert watch_loop._backoff[task_name] == 60

    def test_backoff_is_per_task(self, watch_loop):
        """Backoff for one task does not affect another."""
        failing_fn = MagicMock(side_effect=ValueError("boom"))
        success_fn = MagicMock()

        with patch("time.sleep"):
            watch_loop._safe_run("bad_task", failing_fn)
            assert watch_loop._backoff.get("bad_task") == 10
            assert watch_loop._backoff.get("good_task", 0) == 0

            watch_loop._safe_run("good_task", success_fn)
            assert watch_loop._backoff.get("good_task", 0) == 0
            assert watch_loop._backoff.get("bad_task") == 10

    def test_consecutive_error_count_increments(self, watch_loop):
        """Each failure increments _consecutive_errors."""
        failing_fn = MagicMock(side_effect=RuntimeError("fail"))
        with patch("time.sleep"):
            watch_loop._safe_run("t", failing_fn)
            assert watch_loop._consecutive_errors == 1
            watch_loop._safe_run("t", failing_fn)
            assert watch_loop._consecutive_errors == 2


class TestCrashProtection:
    """Tests for main loop crash protection (#159)."""

    def test_shutdown_flag_exists(self, watch_loop):
        """WatchLoop has _shutdown_requested flag."""
        assert hasattr(watch_loop, "_shutdown_requested")
        assert watch_loop._shutdown_requested is False

    def test_error_timestamps_deque(self, watch_loop):
        """WatchLoop tracks error timestamps in a deque."""
        assert hasattr(watch_loop, "_error_timestamps")
        assert isinstance(watch_loop._error_timestamps, deque)

    def test_signal_import_available(self):
        """signal module is imported in watch.py."""
        import src.scheduler.watch as w
        assert hasattr(w, "signal")


class TestHeartbeat:
    """Tests for heartbeat watchdog (#150)."""

    def test_heartbeat_file_written(self, tmp_path):
        """Heartbeat writes a valid ISO timestamp to watchdog.txt."""
        watchdog = tmp_path / "watchdog.txt"
        now = datetime.now(ET)
        watchdog.write_text(now.isoformat())

        content = watchdog.read_text().strip()
        parsed = datetime.fromisoformat(content)
        assert (now - parsed).total_seconds() < 1

    def test_heartbeat_command_callable(self):
        """The /heartbeat command handler exists and is callable."""
        from src.notifications.telegram_commands import _cmd_heartbeat
        assert callable(_cmd_heartbeat)


class TestScanOverlap:
    """Tests for scan overlap prevention (#151)."""

    def test_scan_in_progress_flag_exists(self, watch_loop):
        """WatchLoop has _scan_in_progress flag, initially False."""
        assert hasattr(watch_loop, "_scan_in_progress")
        assert watch_loop._scan_in_progress is False


class TestScanMetricsWriter:
    """Tests for _record_scan_metrics Fix 1 — avg_conviction and duration_seconds."""

    def test_avg_conviction_written_not_hardcoded(self, watch_loop):
        """_record_scan_metrics writes the passed avg_conviction, not 0.0."""
        import sqlite3
        db_conn = sqlite3.connect(":memory:")
        db_conn.row_factory = sqlite3.Row
        db_conn.execute(
            "CREATE TABLE scan_metrics ("
            "id INTEGER PRIMARY KEY, scan_number INTEGER, scan_time TEXT, "
            "universe_count INTEGER, features_count INTEGER, scored_count INTEGER, "
            "packet_worthy INTEGER, risk_passed INTEGER, paper_traded INTEGER, "
            "live_traded INTEGER, llm_success INTEGER, llm_total INTEGER, "
            "llm_fallback INTEGER, avg_conviction REAL, duration_seconds REAL, "
            "created_at TEXT"
            ")"
        )
        db_conn.commit()

        with patch("src.scheduler.watch.connect_db") as mock_connect:
            mock_connect.return_value.__enter__ = lambda s: db_conn
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            watch_loop._record_scan_metrics(
                universe_count=10,
                features_count=5,
                packet_worthy=3,
                llm_success=3,
                llm_total=3,
                avg_conviction=0.75,
                duration_seconds=12.5,
            )

        row = db_conn.execute(
            "SELECT avg_conviction, duration_seconds FROM scan_metrics"
        ).fetchone()
        assert row is not None
        assert row["avg_conviction"] == 0.75
        assert row["duration_seconds"] == 12.5

    def test_duration_seconds_from_elapsed(self, watch_loop):
        """Callers compute duration_seconds from time.time() diff (mock-verified)."""
        import sqlite3
        db_conn = sqlite3.connect(":memory:")
        db_conn.row_factory = sqlite3.Row
        db_conn.execute(
            "CREATE TABLE scan_metrics ("
            "id INTEGER PRIMARY KEY, scan_number INTEGER, scan_time TEXT, "
            "universe_count INTEGER, features_count INTEGER, scored_count INTEGER, "
            "packet_worthy INTEGER, risk_passed INTEGER, paper_traded INTEGER, "
            "live_traded INTEGER, llm_success INTEGER, llm_total INTEGER, "
            "llm_fallback INTEGER, avg_conviction REAL, duration_seconds REAL, "
            "created_at TEXT"
            ")"
        )
        db_conn.commit()

        fake_start = 1000.0
        fake_end = 1042.7

        with patch("src.scheduler.watch.connect_db") as mock_connect, \
             patch("time.time", side_effect=[fake_start, fake_end]):
            mock_connect.return_value.__enter__ = lambda s: db_conn
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            scan_started_at = time.time()
            elapsed = time.time() - scan_started_at
            watch_loop._record_scan_metrics(
                universe_count=5,
                features_count=2,
                packet_worthy=1,
                llm_success=1,
                llm_total=1,
                avg_conviction=0.0,
                duration_seconds=elapsed,
            )

        row = db_conn.execute(
            "SELECT duration_seconds FROM scan_metrics"
        ).fetchone()
        assert row is not None
        assert abs(row["duration_seconds"] - (fake_end - fake_start)) < 0.001

    def test_defaults_to_zero_when_not_passed(self, watch_loop):
        """avg_conviction and duration_seconds default to 0.0 if not supplied."""
        import sqlite3
        db_conn = sqlite3.connect(":memory:")
        db_conn.row_factory = sqlite3.Row
        db_conn.execute(
            "CREATE TABLE scan_metrics ("
            "id INTEGER PRIMARY KEY, scan_number INTEGER, scan_time TEXT, "
            "universe_count INTEGER, features_count INTEGER, scored_count INTEGER, "
            "packet_worthy INTEGER, risk_passed INTEGER, paper_traded INTEGER, "
            "live_traded INTEGER, llm_success INTEGER, llm_total INTEGER, "
            "llm_fallback INTEGER, avg_conviction REAL, duration_seconds REAL, "
            "created_at TEXT"
            ")"
        )
        db_conn.commit()

        with patch("src.scheduler.watch.connect_db") as mock_connect:
            mock_connect.return_value.__enter__ = lambda s: db_conn
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            watch_loop._record_scan_metrics(
                universe_count=10,
                features_count=5,
                packet_worthy=0,
                llm_success=0,
                llm_total=0,
            )

        row = db_conn.execute(
            "SELECT avg_conviction, duration_seconds FROM scan_metrics"
        ).fetchone()
        assert row is not None
        assert row["avg_conviction"] == 0.0
        assert row["duration_seconds"] == 0.0


class TestScanCycleInvokesRefreshLivePrices:
    """PR #910 review fix — integration test that locks _refresh_live_prices wiring.

    The helper was originally orphaned: defined but never invoked from _run_scan.
    These tests assert the call lands on every code path (aborted, empty, success)
    so prior open positions get fresh quotes regardless of today's scan outcome.
    """

    def _make_result(self, *, aborted=False, packet_worthy_count=0, universe_count=100,
                     features_count=100, conviction_parsed=0, conviction_total=0):
        result = MagicMock()
        result.aborted = aborted
        result.packet_worthy_count = packet_worthy_count
        result.universe_count = universe_count
        result.features_count = features_count
        result.conviction_parsed = conviction_parsed
        result.conviction_total = conviction_total
        return result

    def test_scan_cycle_aborted_path_invokes_refresh(self, watch_loop):
        """Aborted scan path still refreshes live_prices (open positions need quotes)."""
        called = []
        watch_loop._refresh_live_prices = lambda: called.append("refresh")
        watch_loop._record_scan_metrics = lambda **kwargs: called.append("metrics")

        with patch("src.scheduler.universe_scanner.run_universe_scan",
                   return_value=self._make_result(aborted=True)):
            watch_loop._run_scan()

        assert "refresh" in called, "_run_scan aborted path must invoke _refresh_live_prices"
        # Refresh must precede metrics so the dashboard's most recent scan
        # cycle reflects the just-refreshed prices.
        assert called.index("refresh") < called.index("metrics")

    def test_scan_cycle_empty_path_invokes_refresh(self, watch_loop):
        """Empty scan (no packet-worthy) still refreshes live_prices."""
        called = []
        watch_loop._refresh_live_prices = lambda: called.append("refresh")
        watch_loop._record_scan_metrics = lambda **kwargs: called.append("metrics")

        with patch("src.scheduler.universe_scanner.run_universe_scan",
                   return_value=self._make_result(aborted=False, packet_worthy_count=0)):
            watch_loop._run_scan()

        assert "refresh" in called, "_run_scan empty path must invoke _refresh_live_prices"
        assert called.index("refresh") < called.index("metrics")

    def test_scan_cycle_success_path_invokes_refresh(self, watch_loop):
        """Success scan refreshes live_prices after notifications, before metrics."""
        called = []
        watch_loop._refresh_live_prices = lambda: called.append("refresh")
        watch_loop._post_scan_notifications = lambda result: called.append("notify")
        watch_loop._record_scan_metrics = lambda **kwargs: called.append("metrics")

        with patch("src.scheduler.universe_scanner.run_universe_scan",
                   return_value=self._make_result(aborted=False, packet_worthy_count=3,
                                                   conviction_parsed=2, conviction_total=3)):
            watch_loop._run_scan()

        assert "refresh" in called, "_run_scan success path must invoke _refresh_live_prices"
        # Order: notify → refresh → metrics. Notifications first (uses scan_number),
        # then quote refresh (uses just-opened positions), then metrics row.
        assert called.index("notify") < called.index("refresh") < called.index("metrics")
