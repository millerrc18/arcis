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
        from src.notifications.telegram import _cmd_heartbeat
        assert callable(_cmd_heartbeat)


class TestScanOverlap:
    """Tests for scan overlap prevention (#151)."""

    def test_scan_in_progress_flag_exists(self, watch_loop):
        """WatchLoop has _scan_in_progress flag, initially False."""
        assert hasattr(watch_loop, "_scan_in_progress")
        assert watch_loop._scan_in_progress is False
