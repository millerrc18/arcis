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
    assert result == "reconciled_stale"
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


# ---------------------------------------------------------------------------
# Promoted first-class vocab values (pass-through, no warning)
# ---------------------------------------------------------------------------

def test_reconciled_stale_passes_through(caplog):
    with caplog.at_level(logging.WARNING):
        result = _coerce("reconciled_stale")
    assert result == "reconciled_stale"
    assert "EXIT_REASON_INVALID" not in caplog.text


def test_exit_overshoot_detected_passes_through(caplog):
    with caplog.at_level(logging.WARNING):
        result = _coerce("exit_overshoot_detected")
    assert result == "exit_overshoot_detected"
    assert "EXIT_REASON_INVALID" not in caplog.text


def test_qty_mismatch_partial_fill_passes_through(caplog):
    with caplog.at_level(logging.WARNING):
        result = _coerce("qty_mismatch_partial_fill")
    assert result == "qty_mismatch_partial_fill"
    assert "EXIT_REASON_INVALID" not in caplog.text


# ---------------------------------------------------------------------------
# EXCLUDED_FROM_OUTCOME_STATS + outcome_stats_filter_sql helper
# ---------------------------------------------------------------------------
# Class of bug discovered 2026-05-04: `reconciled_stale` rows from reconcile.py
# were polluting the dashboard win-rate (6 real wins / 21 total closed = 28.6%
# instead of 6/6 = 100%). Synthetic closures must be excluded from outcome
# aggregations.

def test_excluded_from_outcome_stats_includes_reconciled_stale():
    """reconciled_stale must be in the exclusion set — the original bug class."""
    from src.shadow_trading.exit_reason import EXCLUDED_FROM_OUTCOME_STATS
    assert "reconciled_stale" in EXCLUDED_FROM_OUTCOME_STATS


def test_excluded_from_outcome_stats_is_frozenset():
    """Exclusion set is immutable and a subset of CONTROLLED_VOCAB."""
    from src.shadow_trading.exit_reason import EXCLUDED_FROM_OUTCOME_STATS, CONTROLLED_VOCAB
    assert isinstance(EXCLUDED_FROM_OUTCOME_STATS, frozenset)
    assert EXCLUDED_FROM_OUTCOME_STATS.issubset(CONTROLLED_VOCAB), (
        "Every excluded reason must also be a valid vocab entry"
    )


def test_outcome_stats_filter_sql_contains_reconciled_stale():
    """Helper emits SQL that excludes reconciled_stale."""
    from src.shadow_trading.exit_reason import outcome_stats_filter_sql
    fragment = outcome_stats_filter_sql()
    assert "reconciled_stale" in fragment
    assert fragment.startswith("AND ")
    assert "exit_reason" in fragment
    assert "NOT IN" in fragment


def test_outcome_stats_filter_sql_handles_null_exit_reason():
    """Filter must allow exit_reason IS NULL — pre-vocab rows shouldn't get excluded."""
    from src.shadow_trading.exit_reason import outcome_stats_filter_sql
    fragment = outcome_stats_filter_sql()
    assert "IS NULL" in fragment


def test_outcome_stats_filter_sql_executes_against_sqlite_in_memory():
    """End-to-end: filter SQL works against a real SQLite instance and excludes
    reconciled_stale rows while keeping target_1 / NULL exit_reason rows."""
    import sqlite3
    from src.shadow_trading.exit_reason import outcome_stats_filter_sql

    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            status TEXT,
            exit_reason TEXT,
            pnl_dollars REAL
        )
    """)
    conn.executemany(
        "INSERT INTO shadow_trades (trade_id, status, exit_reason, pnl_dollars) VALUES (?, ?, ?, ?)",
        [
            ("real-win-1", "closed", "target_1", 100.0),
            ("real-loss-1", "closed", "stop_loss", -50.0),
            ("synthetic-1", "closed", "reconciled_stale", 0.0),
            ("synthetic-pnl", "closed", "reconciled_stale", 64.86),  # mirrors ETN case
            ("legacy-null", "closed", None, 25.0),
        ],
    )
    conn.commit()
    rows = conn.execute(
        f"SELECT trade_id FROM shadow_trades WHERE status = 'closed' {outcome_stats_filter_sql()}"
    ).fetchall()
    trade_ids = {r[0] for r in rows}
    assert trade_ids == {"real-win-1", "real-loss-1", "legacy-null"}
    assert "synthetic-1" not in trade_ids, "reconciled_stale (zero pnl) must be excluded"
    assert "synthetic-pnl" not in trade_ids, (
        "reconciled_stale (non-zero pnl from _estimate_exit_pnl) must ALSO be excluded — "
        "the ETN case from 2026-05-04 had a real-looking pnl but was still a synthetic closure"
    )
    conn.close()


def test_outcome_stats_filter_sql_executes_against_sqlite_with_other_clauses():
    """Filter combines correctly with other WHERE conditions (the production usage shape)."""
    import sqlite3
    from src.shadow_trading.exit_reason import outcome_stats_filter_sql

    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            status TEXT,
            actual_exit_time TEXT,
            quarantined INTEGER,
            exit_reason TEXT,
            pnl_dollars REAL
        )
    """)
    conn.executemany(
        "INSERT INTO shadow_trades VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("a", "closed", "2026-05-01T10:00:00", 0, "target_1", 100.0),
            ("b", "closed", "2026-05-01T10:00:00", 0, "reconciled_stale", 0.0),
            ("c", "closed", "2020-01-01T00:00:00", 0, "target_1", 50.0),  # before cutoff
            ("d", "closed", "2026-05-01T10:00:00", 1, "target_1", 50.0),  # quarantined
        ],
    )
    conn.commit()
    rows = conn.execute(
        f"SELECT trade_id FROM shadow_trades WHERE status = 'closed' "
        f"AND actual_exit_time >= ? AND COALESCE(quarantined, 0) = 0 "
        f"{outcome_stats_filter_sql()} "
        f"ORDER BY trade_id",
        ("2026-04-01T00:00:00",),
    ).fetchall()
    assert [r[0] for r in rows] == ["a"], (
        "Expected only 'a' — 'b' excluded by reconciled_stale, "
        "'c' excluded by date cutoff, 'd' excluded by quarantined"
    )
    conn.close()


# ---------------------------------------------------------------------------
# Wave 4 H4 — retry_exit vocabulary assertions
# ---------------------------------------------------------------------------

def test_retry_exit_in_vocab():
    """retry_exit must be present in CONTROLLED_VOCAB (Wave 4 H4 addition)."""
    from src.shadow_trading.exit_reason import CONTROLLED_VOCAB
    assert "retry_exit" in CONTROLLED_VOCAB


def test_retry_exit_not_excluded_from_outcome_stats():
    """retry_exit is a real fill with real P&L — must NOT be in EXCLUDED_FROM_OUTCOME_STATS."""
    from src.shadow_trading.exit_reason import EXCLUDED_FROM_OUTCOME_STATS
    assert "retry_exit" not in EXCLUDED_FROM_OUTCOME_STATS
