"""Tests for _check_ollama_health_or_restart (T6 — delete unpinned restart spawn).

Regression lock: after the fix, subprocess.Popen must NEVER be called when
Ollama is unhealthy.  The function must return False and log the watchdog-
owns-recovery message.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.llm.client import _check_ollama_health_or_restart


# ---------------------------------------------------------------------------
# Healthy path
# ---------------------------------------------------------------------------

def test_healthy_probe_returns_true():
    """When is_llm_available() is True, return True without spawning anything."""
    with patch("src.llm.client.is_llm_available", return_value=True), \
         patch("subprocess.Popen") as mock_popen:
        result = _check_ollama_health_or_restart()

    assert result is True
    mock_popen.assert_not_called()


# ---------------------------------------------------------------------------
# Unhealthy path — the core regression lock
# ---------------------------------------------------------------------------

def test_unhealthy_probe_returns_false():
    """When Ollama is unresponsive, function returns False."""
    with patch("src.llm.client.is_llm_available", return_value=False):
        result = _check_ollama_health_or_restart()

    assert result is False


def test_unhealthy_probe_never_calls_subprocess_popen():
    """Core regression lock: subprocess.Popen must NEVER be called on unhealthy."""
    with patch("src.llm.client.is_llm_available", return_value=False), \
         patch("subprocess.Popen") as mock_popen:
        _check_ollama_health_or_restart()

    mock_popen.assert_not_called()


def test_unhealthy_probe_logs_watchdog_owns_recovery(caplog):
    """Unhealthy path must log the watchdog-owns-recovery message."""
    with caplog.at_level(logging.WARNING, logger="src.llm.client"):
        with patch("src.llm.client.is_llm_available", return_value=False):
            _check_ollama_health_or_restart()

    joined = " ".join(caplog.messages)
    assert "ArcisOllamaWatchdog" in joined
    assert "failing soft" in joined or "fail" in joined.lower()
