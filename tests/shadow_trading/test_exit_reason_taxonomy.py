"""Tests for exit_reason controlled vocabulary and coerce_exit_reason helper.

Track 1.5 / B3 — Pass 2 Round 3.

Covers:
- All 8 vocab strings pass through unchanged
- All 9 legacy synonym mappings coerce silently (no warning)
- Out-of-vocab values return 'unknown' with WARNING log
- Warning log format matches [EXIT_REASON_INVALID] received=... fallback=unknown
- Edge cases: empty string, None, broker_exception dynamic string
"""
from __future__ import annotations

import logging

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce(value, ticker=""):
    from src.shadow_trading.exit_reason import coerce_exit_reason
    return coerce_exit_reason(value, ticker=ticker)


# ---------------------------------------------------------------------------
# Vocab pass-through (8 canonical values)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "target_1",
    "target_2",
    "stop_loss",
    "timeout",
    "manual",
    "reconciled",
    "error",
    "unknown",
])
def test_vocab_values_pass_through(value):
    assert _coerce(value) == value


# ---------------------------------------------------------------------------
# Legacy synonym coercions (9 mappings, no warning)
# ---------------------------------------------------------------------------

def test_legacy_synonym_target_1_hit(caplog):
    with caplog.at_level(logging.WARNING):
        result = _coerce("target_1_hit")
    assert result == "target_1"
    assert "EXIT_REASON_INVALID" not in caplog.text


def test_legacy_synonym_target_2_hit(caplog):
    with caplog.at_level(logging.WARNING):
        result = _coerce("target_2_hit")
    assert result == "target_2"
    assert "EXIT_REASON_INVALID" not in caplog.text


def test_legacy_synonym_stop_hit(caplog):
    with caplog.at_level(logging.WARNING):
        result = _coerce("stop_hit")
    assert result == "stop_loss"
    assert "EXIT_REASON_INVALID" not in caplog.text


def test_legacy_synonym_take_profit(caplog):
    with caplog.at_level(logging.WARNING):
        result = _coerce("take_profit")
    assert result == "target_1"
    assert "EXIT_REASON_INVALID" not in caplog.text


def test_legacy_synonym_reconciled_stale(caplog):
    with caplog.at_level(logging.WARNING):
        result = _coerce("reconciled_stale")
    assert result == "reconciled"
    assert "EXIT_REASON_INVALID" not in caplog.text


def test_legacy_synonym_mr_timeout(caplog):
    with caplog.at_level(logging.WARNING):
        result = _coerce("mr_timeout")
    assert result == "timeout"
    assert "EXIT_REASON_INVALID" not in caplog.text


def test_legacy_synonym_rsi_exit(caplog):
    with caplog.at_level(logging.WARNING):
        result = _coerce("rsi_exit")
    assert result == "target_1"
    assert "EXIT_REASON_INVALID" not in caplog.text


def test_legacy_synonym_atr_stop(caplog):
    with caplog.at_level(logging.WARNING):
        result = _coerce("atr_stop")
    assert result == "stop_loss"
    assert "EXIT_REASON_INVALID" not in caplog.text


def test_legacy_synonym_late_fill_reconciled(caplog):
    with caplog.at_level(logging.WARNING):
        result = _coerce("late_fill_reconciled")
    assert result == "reconciled"
    assert "EXIT_REASON_INVALID" not in caplog.text


# ---------------------------------------------------------------------------
# Out-of-vocab: return 'unknown' + warning
# ---------------------------------------------------------------------------

def test_out_of_vocab_returns_unknown():
    assert _coerce("foo_bar") == "unknown"


def test_out_of_vocab_logs_warning(caplog):
    with caplog.at_level(logging.WARNING):
        _coerce("foo_bar")
    assert "EXIT_REASON_INVALID" in caplog.text
    assert "foo_bar" in caplog.text
    assert "fallback=unknown" in caplog.text


def test_out_of_vocab_includes_ticker_in_log(caplog):
    with caplog.at_level(logging.WARNING):
        _coerce("foo_bar", ticker="AAPL")
    assert "AAPL" in caplog.text


def test_broker_exception_dynamic_string(caplog):
    with caplog.at_level(logging.WARNING):
        result = _coerce("broker_exception:APIError")
    assert result == "unknown"
    assert "EXIT_REASON_INVALID" in caplog.text


def test_empty_string_returns_unknown(caplog):
    with caplog.at_level(logging.WARNING):
        result = _coerce("")
    assert result == "unknown"
    assert "EXIT_REASON_INVALID" in caplog.text


def test_none_string_returns_unknown(caplog):
    """coerce_exit_reason with None: logs warning and returns 'unknown' (no raise)."""
    with caplog.at_level(logging.WARNING):
        result = _coerce(None)
    assert result == "unknown"
    assert "EXIT_REASON_INVALID" in caplog.text
