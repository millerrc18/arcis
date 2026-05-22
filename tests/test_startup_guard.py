"""Tests for the ArcisOllamaWatchdog startup guard in watch.py (T5).

Scope:
- _sc_query_running(service_name) helper: RUNNING vs not-running output
- _assert_ollama_watchdog_present(): raises when not RUNNING and escape hatch absent
- _assert_ollama_watchdog_present(): passes (no raise) when RUNNING
- _assert_ollama_watchdog_present(): passes when ARCIS_SKIP_WATCHDOG_GUARD=1

All subprocess calls are mocked — no real 'sc' invocation.
"""

import logging
import os
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from src.scheduler.watch import _sc_query_running, _assert_ollama_watchdog_present

# ---------------------------------------------------------------------------
# Sample sc query output fixtures
# ---------------------------------------------------------------------------

_SC_RUNNING = (
    "SERVICE_NAME: ArcisOllamaWatchdog\n"
    "        TYPE               : 10  WIN32_OWN_PROCESS\n"
    "        STATE              : 4  RUNNING\n"
    "                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)\n"
    "        WIN32_EXIT_CODE    : 0  (0x0)\n"
    "        SERVICE_EXIT_CODE  : 0  (0x0)\n"
    "        CHECKPOINT         : 0x0\n"
    "        WAIT_HINT          : 0x0\n"
)

_SC_STOPPED = (
    "SERVICE_NAME: ArcisOllamaWatchdog\n"
    "        TYPE               : 10  WIN32_OWN_PROCESS\n"
    "        STATE              : 1  STOPPED\n"
    "        WIN32_EXIT_CODE    : 0  (0x0)\n"
    "        SERVICE_EXIT_CODE  : 0  (0x0)\n"
    "        CHECKPOINT         : 0x0\n"
    "        WAIT_HINT          : 0x0\n"
)

_SC_NOT_FOUND = (
    "[SC] EnumQueryServicesStatus:OpenService FAILED 1060:\n\n"
    "The specified service does not exist as an installed service.\n"
)


# ---------------------------------------------------------------------------
# Tests for _sc_query_running helper
# ---------------------------------------------------------------------------

class TestScQueryRunning:
    def test_running_output_returns_true(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=_SC_RUNNING, returncode=0)
            result = _sc_query_running("ArcisOllamaWatchdog")
        assert result is True

    def test_stopped_output_returns_false(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=_SC_STOPPED, returncode=0)
            result = _sc_query_running("ArcisOllamaWatchdog")
        assert result is False

    def test_not_found_output_returns_false(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=_SC_NOT_FOUND, returncode=1060)
            result = _sc_query_running("ArcisOllamaWatchdog")
        assert result is False

    def test_subprocess_exception_returns_false(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("sc not found")):
            result = _sc_query_running("ArcisOllamaWatchdog")
        assert result is False

    def test_uses_service_name_argument(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=_SC_RUNNING, returncode=0)
            _sc_query_running("SomeOtherService")
        args = mock_run.call_args[0][0]
        assert "SomeOtherService" in args


# ---------------------------------------------------------------------------
# Tests for _assert_ollama_watchdog_present guard
# ---------------------------------------------------------------------------

class TestAssertOllamaWatchdogPresent:
    def test_running_guard_passes(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=_SC_RUNNING, returncode=0)
            # Should not raise
            _assert_ollama_watchdog_present()

    def test_not_running_raises(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=_SC_STOPPED, returncode=0)
            env = {k: v for k, v in os.environ.items() if k != "ARCIS_SKIP_WATCHDOG_GUARD"}
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(RuntimeError):
                    _assert_ollama_watchdog_present()

    def test_not_running_logs_loud(self, caplog):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=_SC_STOPPED, returncode=0)
            env = {k: v for k, v in os.environ.items() if k != "ARCIS_SKIP_WATCHDOG_GUARD"}
            with patch.dict(os.environ, env, clear=True):
                with caplog.at_level(logging.CRITICAL):
                    with pytest.raises(RuntimeError):
                        _assert_ollama_watchdog_present()
        # Must emit at least one CRITICAL or ERROR log about the watchdog
        relevant = [
            r for r in caplog.records
            if r.levelno >= logging.ERROR and "watchdog" in r.message.lower()
        ]
        assert relevant, "Expected a loud (ERROR+) log about watchdog not running"

    def test_skip_env_var_bypasses_raise(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=_SC_STOPPED, returncode=0)
            with patch.dict(os.environ, {"ARCIS_SKIP_WATCHDOG_GUARD": "1"}):
                # Should not raise even though service is stopped
                _assert_ollama_watchdog_present()

    def test_skip_env_var_zero_does_not_bypass(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=_SC_STOPPED, returncode=0)
            with patch.dict(os.environ, {"ARCIS_SKIP_WATCHDOG_GUARD": "0"}):
                with pytest.raises(RuntimeError):
                    _assert_ollama_watchdog_present()

    def test_absent_service_raises(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=_SC_NOT_FOUND, returncode=1060)
            env = {k: v for k, v in os.environ.items() if k != "ARCIS_SKIP_WATCHDOG_GUARD"}
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(RuntimeError):
                    _assert_ollama_watchdog_present()

    def test_skip_env_var_truthy_non_one_does_not_bypass(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=_SC_STOPPED, returncode=0)
            with patch.dict(os.environ, {"ARCIS_SKIP_WATCHDOG_GUARD": "true"}):
                with pytest.raises(RuntimeError):
                    _assert_ollama_watchdog_present()
