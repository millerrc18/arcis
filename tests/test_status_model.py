"""Tests for shadow trade status model."""
from src.shadow_trading.models import TERMINAL_STATUSES, ACTIVE_STATUSES


def test_terminal_statuses_defined():
    assert "closed" in TERMINAL_STATUSES
    assert "rejected" in TERMINAL_STATUSES
    assert "exit_abandoned" in TERMINAL_STATUSES


def test_active_statuses_defined():
    assert "open" in ACTIVE_STATUSES
    assert "pending" in ACTIVE_STATUSES
    assert "exit_pending" in ACTIVE_STATUSES
    assert "exit_failed" in ACTIVE_STATUSES


def test_no_overlap():
    assert TERMINAL_STATUSES.isdisjoint(ACTIVE_STATUSES)


def test_failed_is_terminal():
    assert "failed" in TERMINAL_STATUSES
    assert "rejected" in TERMINAL_STATUSES
