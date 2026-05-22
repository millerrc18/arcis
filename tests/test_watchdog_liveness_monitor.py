"""Tests for the runtime watchdog-liveness monitor in watch.py (T18).

Scope:
- RUNNING→not-RUNNING transition emits a loud Telegram alarm exactly once
- Stale gpu_health_ollama_ok metric corroborates the not-RUNNING signal
- Re-arms after recovery (not-RUNNING→RUNNING→not-RUNNING alarms again)
- No alarm when steadily RUNNING
- Tick is NEVER blocked even if the alarm path raises (fail-soft)

All sc query / subprocess / safe_send / DB reads are mocked — no real
process or network calls.
"""

import os
import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers for building a minimal WatchLoop instance without DB or services
# ---------------------------------------------------------------------------

os.environ.setdefault("ARCIS_SKIP_WATCHDOG_GUARD", "1")


def _make_watch_loop():
    """Return a WatchLoop with a minimal config, no real DB needed."""
    from src.scheduler.watch import WatchLoop

    config = {
        "automation": {
            "scan_interval_minutes": 30,
            "morning_watchlist_hour_et": 8,
            "eod_recap_hour_et": 16,
            "market_open_hour_et": 9,
            "market_open_minute_et": 30,
            "market_close_hour_et": 16,
        },
        "notifications": {},
    }
    return WatchLoop(config)


# ---------------------------------------------------------------------------
# Shared sc-query mock helpers
# ---------------------------------------------------------------------------

_SC_RUNNING = (
    "SERVICE_NAME: ArcisOllamaWatchdog\n"
    "        STATE              : 4  RUNNING\n"
)

_SC_STOPPED = (
    "SERVICE_NAME: ArcisOllamaWatchdog\n"
    "        STATE              : 1  STOPPED\n"
)


def _mock_sc(is_running: bool):
    """Return a mock for subprocess.run matching the RUNNING/STOPPED state."""
    m = MagicMock()
    m.return_value = MagicMock(
        stdout=_SC_RUNNING if is_running else _SC_STOPPED,
        returncode=0,
    )
    return m


# ---------------------------------------------------------------------------
# Test 1 — RUNNING→not-RUNNING transition emits loud Telegram alarm exactly once
# ---------------------------------------------------------------------------

class TestRunningToNotRunningEmitsAlarm:
    def test_transition_sends_alarm_exactly_once(self):
        wl = _make_watch_loop()

        with (
            patch("subprocess.run", _mock_sc(True).return_value.__class__) as _,
            patch(
                "src.scheduler.watch._sc_query_running",
                side_effect=[True, False],  # first tick: RUNNING; second tick: STOPPED
            ),
            patch("src.scheduler.watch.safe_send") as mock_safe_send,
            patch(
                "src.scheduler.watch.WatchLoop._ollama_watchdog_metric_fresh",
                return_value=True,
            ),
        ):
            # First tick — RUNNING, no alarm
            wl.tick_watchdog_liveness()
            mock_safe_send.assert_not_called()

            # Reset cadence gate so second tick fires immediately in test
            wl._watchdog_liveness_last_check = None

            # Second tick — transition to NOT RUNNING, alarm fires via system_event
            wl.tick_watchdog_liveness()
            mock_safe_send.assert_called_once()
            # Verify it is a system_event call with WATCHDOG-related content
            call_args = mock_safe_send.call_args
            event_type = call_args[0][0]
            assert event_type == "system_event"
            event_kwarg = call_args[1].get("event", "")
            assert "WATCHDOG" in event_kwarg.upper()


# ---------------------------------------------------------------------------
# Test 2 — Stale metric corroborates the not-RUNNING signal
# ---------------------------------------------------------------------------

class TestStaleMertricCorroborates:
    def test_stale_metric_when_not_running(self):
        """When sc says STOPPED and metric is stale, alarm still fires."""
        wl = _make_watch_loop()

        with (
            patch(
                "src.scheduler.watch._sc_query_running",
                side_effect=[True, False],
            ),
            patch("src.scheduler.watch.safe_send") as mock_safe_send,
            patch(
                "src.scheduler.watch.WatchLoop._ollama_watchdog_metric_fresh",
                return_value=False,  # stale — corroborates
            ),
        ):
            wl.tick_watchdog_liveness()  # RUNNING: no alarm
            mock_safe_send.assert_not_called()

            # Reset cadence gate so second tick fires immediately in test
            wl._watchdog_liveness_last_check = None

            wl.tick_watchdog_liveness()  # STOPPED + stale: alarm
            mock_safe_send.assert_called_once()

    def test_fresh_metric_does_not_suppress_alarm_on_not_running(self):
        """When sc says STOPPED but metric is still fresh, alarm fires anyway.

        The sc state is authoritative — metric is only corroborating.
        """
        wl = _make_watch_loop()

        with (
            patch(
                "src.scheduler.watch._sc_query_running",
                side_effect=[True, False],
            ),
            patch("src.scheduler.watch.safe_send") as mock_safe_send,
            patch(
                "src.scheduler.watch.WatchLoop._ollama_watchdog_metric_fresh",
                return_value=True,  # fresh — doesn't suppress alarm
            ),
        ):
            wl.tick_watchdog_liveness()  # RUNNING: no alarm
            mock_safe_send.assert_not_called()

            # Reset cadence gate so second tick fires immediately in test
            wl._watchdog_liveness_last_check = None

            wl.tick_watchdog_liveness()  # STOPPED: alarm fires regardless of metric
            mock_safe_send.assert_called_once()


# ---------------------------------------------------------------------------
# Test 3 — Re-arms after recovery
# ---------------------------------------------------------------------------

class TestReArmsAfterRecovery:
    def test_not_running_then_running_then_not_running_alarms_again(self):
        """not-RUNNING → RUNNING → not-RUNNING: alarms twice (re-arm on recovery)."""
        wl = _make_watch_loop()

        sc_states = [True, False, True, False]

        with (
            patch(
                "src.scheduler.watch._sc_query_running",
                side_effect=sc_states,
            ),
            patch("src.scheduler.watch.safe_send") as mock_safe_send,
            patch(
                "src.scheduler.watch.WatchLoop._ollama_watchdog_metric_fresh",
                return_value=True,
            ),
        ):
            wl.tick_watchdog_liveness()  # RUNNING: no alarm
            assert mock_safe_send.call_count == 0

            wl._watchdog_liveness_last_check = None  # reset cadence gate
            wl.tick_watchdog_liveness()  # STOPPED: alarm #1
            assert mock_safe_send.call_count == 1

            wl._watchdog_liveness_last_check = None  # reset cadence gate
            wl.tick_watchdog_liveness()  # RUNNING again: no alarm (recovery)
            assert mock_safe_send.call_count == 1

            wl._watchdog_liveness_last_check = None  # reset cadence gate
            wl.tick_watchdog_liveness()  # STOPPED again: alarm #2 (re-armed)
            assert mock_safe_send.call_count == 2


# ---------------------------------------------------------------------------
# Test 4 — No alarm when steadily RUNNING
# ---------------------------------------------------------------------------

class TestNoAlarmWhenSteadilyRunning:
    def test_multiple_running_ticks_no_alarm(self):
        wl = _make_watch_loop()

        with (
            patch(
                "src.scheduler.watch._sc_query_running",
                return_value=True,
            ),
            patch("src.scheduler.watch.safe_send") as mock_safe_send,
            patch(
                "src.scheduler.watch.WatchLoop._ollama_watchdog_metric_fresh",
                return_value=True,
            ),
        ):
            for _ in range(5):
                wl.tick_watchdog_liveness()

            mock_safe_send.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5 — Fail-soft: alarm path raising must not block the tick
# ---------------------------------------------------------------------------

class TestFailSoft:
    def test_tick_does_not_raise_when_safe_send_raises(self):
        """A broken safe_send must not propagate — tick must complete silently."""
        wl = _make_watch_loop()

        with (
            patch(
                "src.scheduler.watch._sc_query_running",
                side_effect=[True, False],
            ),
            patch(
                "src.scheduler.watch.safe_send",
                side_effect=RuntimeError("Telegram network error"),
            ),
            patch(
                "src.scheduler.watch.WatchLoop._ollama_watchdog_metric_fresh",
                return_value=True,
            ),
        ):
            wl.tick_watchdog_liveness()  # RUNNING: no alarm path touched

            # This tick would trigger the alarm, which raises — must not propagate
            try:
                wl.tick_watchdog_liveness()
            except Exception as exc:
                pytest.fail(
                    f"tick_watchdog_liveness raised despite fail-soft requirement: {exc}"
                )

    def test_tick_does_not_raise_when_sc_query_raises(self):
        """A broken sc query must not propagate — tick must complete silently."""
        wl = _make_watch_loop()

        with (
            patch(
                "src.scheduler.watch._sc_query_running",
                side_effect=OSError("sc.exe not found"),
            ),
            patch("src.scheduler.watch.safe_send") as mock_safe_send,
            patch(
                "src.scheduler.watch.WatchLoop._ollama_watchdog_metric_fresh",
                return_value=True,
            ),
        ):
            try:
                wl.tick_watchdog_liveness()
            except Exception as exc:
                pytest.fail(
                    f"tick_watchdog_liveness raised when sc query errored: {exc}"
                )

    def test_tick_does_not_raise_when_metric_check_raises(self):
        """A broken metric read must not propagate — tick must complete silently."""
        wl = _make_watch_loop()

        with (
            patch(
                "src.scheduler.watch._sc_query_running",
                return_value=True,
            ),
            patch("src.scheduler.watch.safe_send") as mock_safe_send,
            patch(
                "src.scheduler.watch.WatchLoop._ollama_watchdog_metric_fresh",
                side_effect=RuntimeError("DB unavailable"),
            ),
        ):
            try:
                wl.tick_watchdog_liveness()
            except Exception as exc:
                pytest.fail(
                    f"tick_watchdog_liveness raised when metric check errored: {exc}"
                )


# ---------------------------------------------------------------------------
# Test 6 — Cadence gate: ~60s, keyed in _backoff (no alarm spam)
# ---------------------------------------------------------------------------

class TestCadenceGate:
    def test_tick_respects_60s_cadence(self):
        """Two ticks in rapid succession only run the monitor once."""
        from datetime import datetime

        wl = _make_watch_loop()

        call_count = []

        def counting_sc(*_args, **_kwargs):
            call_count.append(1)
            return True

        with (
            patch("src.scheduler.watch._sc_query_running", side_effect=counting_sc),
            patch("src.scheduler.watch.safe_send"),
            patch(
                "src.scheduler.watch.WatchLoop._ollama_watchdog_metric_fresh",
                return_value=True,
            ),
        ):
            # First tick — runs
            wl.tick_watchdog_liveness()
            first_count = len(call_count)
            assert first_count == 1

            # Immediate second tick — cadence gate blocks it
            wl.tick_watchdog_liveness()
            assert len(call_count) == 1  # Still 1 — gate held


# ---------------------------------------------------------------------------
# Test 7 — _ollama_watchdog_metric_fresh helper reads from schedule_metrics
# ---------------------------------------------------------------------------

class TestMetricFreshHelper:
    def test_fresh_when_todays_row_has_positive_value(self, tmp_path):
        """_ollama_watchdog_metric_fresh returns True when today's metric is ok."""
        import sqlite3 as _sqlite3
        from datetime import datetime
        from zoneinfo import ZoneInfo

        db_path = str(tmp_path / "test.sqlite3")
        today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        conn = _sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE schedule_metrics "
            "(id INTEGER PRIMARY KEY, metric_date TEXT, metric_name TEXT, metric_value REAL, details TEXT)"
        )
        conn.execute(
            "INSERT INTO schedule_metrics (metric_date, metric_name, metric_value) VALUES (?, ?, ?)",
            (today, "gpu_health_ollama_ok", 1.0),
        )
        conn.commit()
        conn.close()

        from src.scheduler.watch import WatchLoop
        config = {"automation": {
            "scan_interval_minutes": 30,
            "morning_watchlist_hour_et": 8,
            "eod_recap_hour_et": 16,
            "market_open_hour_et": 9,
            "market_open_minute_et": 30,
            "market_close_hour_et": 16,
        }}
        wl = WatchLoop(config)
        assert wl._ollama_watchdog_metric_fresh(db_path=db_path) is True

    def test_stale_when_no_todays_row(self, tmp_path):
        """_ollama_watchdog_metric_fresh returns False when today's metric absent."""
        import sqlite3 as _sqlite3

        db_path = str(tmp_path / "test.sqlite3")
        conn = _sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE schedule_metrics "
            "(id INTEGER PRIMARY KEY, metric_date TEXT, metric_name TEXT, metric_value REAL, details TEXT)"
        )
        conn.commit()
        conn.close()

        from src.scheduler.watch import WatchLoop
        config = {"automation": {
            "scan_interval_minutes": 30,
            "morning_watchlist_hour_et": 8,
            "eod_recap_hour_et": 16,
            "market_open_hour_et": 9,
            "market_open_minute_et": 30,
            "market_close_hour_et": 16,
        }}
        wl = WatchLoop(config)
        assert wl._ollama_watchdog_metric_fresh(db_path=db_path) is False

    def test_stale_when_todays_row_has_zero_value(self, tmp_path):
        """_ollama_watchdog_metric_fresh returns False when metric_value is 0."""
        import sqlite3 as _sqlite3
        from datetime import datetime
        from zoneinfo import ZoneInfo

        db_path = str(tmp_path / "test.sqlite3")
        today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        conn = _sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE schedule_metrics "
            "(id INTEGER PRIMARY KEY, metric_date TEXT, metric_name TEXT, metric_value REAL, details TEXT)"
        )
        conn.execute(
            "INSERT INTO schedule_metrics (metric_date, metric_name, metric_value) VALUES (?, ?, ?)",
            (today, "gpu_health_ollama_ok", 0.0),
        )
        conn.commit()
        conn.close()

        from src.scheduler.watch import WatchLoop
        config = {"automation": {
            "scan_interval_minutes": 30,
            "morning_watchlist_hour_et": 8,
            "eod_recap_hour_et": 16,
            "market_open_hour_et": 9,
            "market_open_minute_et": 30,
            "market_close_hour_et": 16,
        }}
        wl = WatchLoop(config)
        assert wl._ollama_watchdog_metric_fresh(db_path=db_path) is False
