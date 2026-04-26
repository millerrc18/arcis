"""Tests for nightly exit reconciliation pass.

Track 1.5 / B3 — Pass 2 Round 3.

All tests use an in-memory SQLite DB seeded with synthetic shadow_trades rows.
The reconciliation function is called with a :memory: path to avoid touching prod.

Covers:
- target_1 / target_2 clean and anomaly cases
- stop_loss clean and anomaly (1% slippage tolerance)
- timeout clean and anomaly
- timeout with NULL duration_days falls back to computed days
- manual / reconciled / error / unknown — no price check, no anomaly
- NULL bracket target skipped with RECONCILE_SKIP log
- Output dict has all required keys
- 24-hour window filter (48h-ago row excluded)
- quarantined=1 excluded
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone


import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _now_iso(offset_hours: float = 0) -> str:
    """Return ISO timestamp relative to now (UTC), offset by hours."""
    dt = datetime.now(timezone.utc) - timedelta(hours=offset_hours)
    return dt.isoformat()


def _create_db() -> sqlite3.Connection:
    """Return an in-memory connection with the minimal shadow_trades schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            ticker TEXT,
            status TEXT,
            exit_reason TEXT,
            actual_exit_time TEXT,
            actual_exit_price REAL,
            actual_entry_time TEXT,
            actual_entry_price REAL,
            entry_price REAL,
            stop_price REAL,
            target_1 REAL,
            target_2 REAL,
            duration_days INTEGER,
            timeout_days INTEGER,
            direction TEXT DEFAULT 'long',
            quarantined INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def _insert(conn, trade_id, **kwargs):
    defaults = {
        "ticker": "AAPL",
        "status": "closed",
        "exit_reason": "unknown",
        "actual_exit_time": _now_iso(1),  # 1h ago = within 24h window
        "actual_exit_price": 100.0,
        "actual_entry_time": _now_iso(25),  # 25h ago
        "actual_entry_price": 100.0,
        "entry_price": 100.0,
        "stop_price": 95.0,
        "target_1": 110.0,
        "target_2": 120.0,
        "duration_days": 1,
        "timeout_days": 15,
        "direction": "long",
        "quarantined": 0,
    }
    defaults.update(kwargs)
    cols = ", ".join(defaults.keys())
    placeholders = ", ".join("?" for _ in defaults)
    conn.execute(
        f"INSERT INTO shadow_trades (trade_id, {cols}) VALUES (?, {placeholders})",
        [trade_id] + list(defaults.values()),
    )
    conn.commit()


def _run(conn) -> dict:
    from src.shadow_trading.exit_reconciliation import run_exit_reconciliation
    return run_exit_reconciliation(conn=conn)


# ---------------------------------------------------------------------------
# target_1
# ---------------------------------------------------------------------------

def test_target_1_clean():
    conn = _create_db()
    _insert(conn, "t1", exit_reason="target_1", actual_exit_price=120.0, target_1=119.0)
    result = _run(conn)
    assert "t1" not in result["flagged_trade_ids"]
    assert result["by_reason"]["target_1"]["anomalies"] == 0


def test_target_1_anomaly():
    conn = _create_db()
    _insert(conn, "t1a", exit_reason="target_1", actual_exit_price=115.0, target_1=119.0)
    result = _run(conn)
    assert "t1a" in result["flagged_trade_ids"]
    assert result["by_reason"]["target_1"]["anomalies"] == 1


# ---------------------------------------------------------------------------
# target_2
# ---------------------------------------------------------------------------

def test_target_2_clean():
    conn = _create_db()
    _insert(conn, "t2", exit_reason="target_2", actual_exit_price=130.0, target_2=128.0)
    result = _run(conn)
    assert "t2" not in result["flagged_trade_ids"]
    assert result["by_reason"]["target_2"]["anomalies"] == 0


def test_target_2_anomaly():
    conn = _create_db()
    _insert(conn, "t2a", exit_reason="target_2", actual_exit_price=125.0, target_2=128.0)
    result = _run(conn)
    assert "t2a" in result["flagged_trade_ids"]
    assert result["by_reason"]["target_2"]["anomalies"] == 1


# ---------------------------------------------------------------------------
# stop_loss (1% slippage tolerance)
# ---------------------------------------------------------------------------

def test_stop_loss_clean():
    """Exit at 95 with stop=96: within 1% tolerance (96*1.01=96.96), no anomaly."""
    conn = _create_db()
    _insert(conn, "sl", exit_reason="stop_loss", actual_exit_price=95.0, stop_price=96.0)
    result = _run(conn)
    assert "sl" not in result["flagged_trade_ids"]
    assert result["by_reason"]["stop_loss"]["anomalies"] == 0


def test_stop_loss_anomaly():
    """Exit at 105 with stop=96: well above 96*1.01=96.96, anomaly."""
    conn = _create_db()
    _insert(conn, "sla", exit_reason="stop_loss", actual_exit_price=105.0, stop_price=96.0)
    result = _run(conn)
    assert "sla" in result["flagged_trade_ids"]
    assert result["by_reason"]["stop_loss"]["anomalies"] == 1


# ---------------------------------------------------------------------------
# timeout
# ---------------------------------------------------------------------------

def test_timeout_clean():
    conn = _create_db()
    _insert(conn, "to", exit_reason="timeout", duration_days=8, timeout_days=8)
    result = _run(conn)
    assert "to" not in result["flagged_trade_ids"]
    assert result["by_reason"]["timeout"]["anomalies"] == 0


def test_timeout_anomaly():
    conn = _create_db()
    _insert(conn, "toa", exit_reason="timeout", duration_days=3, timeout_days=15)
    result = _run(conn)
    assert "toa" in result["flagged_trade_ids"]
    assert result["by_reason"]["timeout"]["anomalies"] == 1


def test_timeout_null_duration_uses_fallback():
    """duration_days=NULL with entry 20h ago, timeout_days=15 — computed days < 1, fallback fires but
    should NOT flag because the fallback COALESCE path is tested: we use actual_entry_time 20 days ago."""
    conn = _create_db()
    # 20 days old entry, no duration_days => computed ~20 days >= 15 => no anomaly
    conn.execute("""
        INSERT INTO shadow_trades
        (trade_id, ticker, status, exit_reason, actual_exit_time, actual_exit_price,
         actual_entry_time, actual_entry_price, entry_price, stop_price, target_1, target_2,
         duration_days, timeout_days, direction, quarantined)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ["tofb", "AAPL", "closed", "timeout",
          _now_iso(1), 100.0,
          _now_iso(24 * 20), 100.0, 100.0, 95.0, 110.0, 120.0,
          None, 15, "long", 0])
    conn.commit()
    result = _run(conn)
    assert "tofb" not in result["flagged_trade_ids"]


# ---------------------------------------------------------------------------
# No-check reasons: manual, reconciled, error, unknown
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("reason", ["manual", "reconciled", "error", "unknown"])
def test_no_price_check_reasons(reason):
    conn = _create_db()
    # Deliberately set prices that would trigger anomaly for target_1 logic
    _insert(conn, f"nc_{reason}", exit_reason=reason,
            actual_exit_price=50.0, target_1=200.0)
    result = _run(conn)
    assert f"nc_{reason}" not in result["flagged_trade_ids"]


# ---------------------------------------------------------------------------
# NULL bracket target skipped
# ---------------------------------------------------------------------------

def test_null_bracket_skipped(caplog):
    import logging
    conn = _create_db()
    conn.execute("""
        INSERT INTO shadow_trades
        (trade_id, ticker, status, exit_reason, actual_exit_time, actual_exit_price,
         actual_entry_time, actual_entry_price, entry_price, stop_price, target_1, target_2,
         duration_days, timeout_days, direction, quarantined)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ["tnull", "AAPL", "closed", "target_1",
          _now_iso(1), 100.0,
          _now_iso(25), 100.0, 100.0, 95.0,
          None, 0.0,   # target_1=NULL
          1, 15, "long", 0])
    conn.commit()
    with caplog.at_level(logging.WARNING):
        result = _run(conn)
    assert "tnull" not in result["flagged_trade_ids"]
    assert "RECONCILE_SKIP" in caplog.text


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

def test_output_structure():
    conn = _create_db()
    _insert(conn, "os1", exit_reason="target_1", actual_exit_price=120.0, target_1=119.0)
    _insert(conn, "os2", exit_reason="stop_loss", actual_exit_price=105.0, stop_price=96.0)
    result = _run(conn)
    required_keys = {"reconciliation_date", "anomaly_count", "flagged_trade_ids", "by_reason"}
    assert required_keys.issubset(result.keys())
    by_reason = result["by_reason"]
    for key in ("target_1", "target_2", "stop_loss", "timeout",
                "reconciled", "manual", "error", "unknown"):
        assert key in by_reason


# ---------------------------------------------------------------------------
# 24-hour window filter
# ---------------------------------------------------------------------------

def test_only_last_24h():
    conn = _create_db()
    # 48h-ago row: should be excluded
    _insert(conn, "old", exit_reason="target_1",
            actual_exit_price=115.0, target_1=119.0,
            actual_exit_time=_now_iso(48))
    # 12h-ago row: should be included and flagged
    _insert(conn, "recent", exit_reason="target_1",
            actual_exit_price=115.0, target_1=119.0,
            actual_exit_time=_now_iso(12))
    result = _run(conn)
    assert "old" not in result["flagged_trade_ids"]
    assert "recent" in result["flagged_trade_ids"]


# ---------------------------------------------------------------------------
# Quarantined excluded
# ---------------------------------------------------------------------------

def test_quarantined_excluded():
    conn = _create_db()
    _insert(conn, "quar", exit_reason="target_1",
            actual_exit_price=115.0, target_1=119.0,
            quarantined=1)
    result = _run(conn)
    assert "quar" not in result["flagged_trade_ids"]
    assert result["total_closed"] == 0


# ---------------------------------------------------------------------------
# Direction handling — PR-690 O2
# ---------------------------------------------------------------------------

def test_short_trade_stop_loss_anomaly_inverts():
    """For a short, stop_price is ABOVE entry. An exit BELOW stop_price by
    >1% (stop * 0.99 = 100.98) is the broker-slippage anomaly that should fire.

    Long-only logic (exit > stop * 1.01) would NOT have flagged this row;
    direction-aware logic (exit < stop * 0.99) DOES.
    """
    conn = _create_db()
    # short with stop=102, exit=95: exit is well below stop * 0.99 = 100.98
    _insert(
        conn, "shsl_anom",
        direction="short",
        exit_reason="stop_loss",
        stop_price=102.0,
        actual_exit_price=95.0,
    )
    result = _run(conn)
    assert "shsl_anom" in result["flagged_trade_ids"]
    assert result["by_reason"]["stop_loss"]["anomalies"] == 1


def test_short_trade_stop_loss_clean_within_tolerance():
    """Short with stop=100, exit=99.5: above the 1% lower bound (99.0),
    so no anomaly even though exit < stop."""
    conn = _create_db()
    _insert(
        conn, "shsl_clean",
        direction="short",
        exit_reason="stop_loss",
        stop_price=100.0,
        actual_exit_price=99.5,
    )
    result = _run(conn)
    assert "shsl_clean" not in result["flagged_trade_ids"]
    assert result["by_reason"]["stop_loss"]["anomalies"] == 0


def test_short_trade_target_1_anomaly_inverts():
    """For a short, target_1 is BELOW entry. Saying we hit target_1 but
    exit_price > target_1 is the anomaly (we didn't actually reach it).

    Long-only logic would have flagged this only if exit < t1; for a short
    that case is the clean (target reached) path."""
    conn = _create_db()
    _insert(
        conn, "sht1_anom",
        direction="short",
        exit_reason="target_1",
        target_1=90.0,
        actual_exit_price=95.0,  # didn't reach 90 from above
    )
    result = _run(conn)
    assert "sht1_anom" in result["flagged_trade_ids"]
    assert result["by_reason"]["target_1"]["anomalies"] == 1


def test_short_trade_target_1_clean():
    """Short with target_1=90, exit=88: hit the target from above, clean."""
    conn = _create_db()
    _insert(
        conn, "sht1_clean",
        direction="short",
        exit_reason="target_1",
        target_1=90.0,
        actual_exit_price=88.0,
    )
    result = _run(conn)
    assert "sht1_clean" not in result["flagged_trade_ids"]
    assert result["by_reason"]["target_1"]["anomalies"] == 0


def test_short_trade_target_2_anomaly_inverts():
    """Symmetric to target_1 — short with target_2 below entry, exit
    above target_2 means we didn't actually reach it."""
    conn = _create_db()
    _insert(
        conn, "sht2_anom",
        direction="short",
        exit_reason="target_2",
        target_2=80.0,
        actual_exit_price=85.0,  # didn't reach 80 from above
    )
    result = _run(conn)
    assert "sht2_anom" in result["flagged_trade_ids"]
    assert result["by_reason"]["target_2"]["anomalies"] == 1


def test_unknown_direction_logs_warning_returns_false(caplog):
    """A row with direction='sideways' (unknown) for a price-based reason
    must NOT flag (fail-safe) and MUST emit EXIT_RECON_UNKNOWN_DIRECTION."""
    import logging as _logging
    conn = _create_db()
    # Price would have flagged as long-stop_loss anomaly (exit 105 > 96*1.01)
    _insert(
        conn, "udir",
        direction="sideways",
        exit_reason="stop_loss",
        stop_price=96.0,
        actual_exit_price=105.0,
    )
    with caplog.at_level(_logging.WARNING):
        result = _run(conn)
    assert "udir" not in result["flagged_trade_ids"]
    assert "EXIT_RECON_UNKNOWN_DIRECTION" in caplog.text
    assert "udir" in caplog.text


def test_long_trade_stop_loss_anomaly_still_fires():
    """Regression: explicit direction='long' must preserve the original
    long-only anomaly behavior."""
    conn = _create_db()
    _insert(
        conn, "lsl_anom",
        direction="long",
        exit_reason="stop_loss",
        stop_price=96.0,
        actual_exit_price=105.0,
    )
    result = _run(conn)
    assert "lsl_anom" in result["flagged_trade_ids"]


def test_default_direction_treated_as_long():
    """Rows with direction NULL fall back to 'long' for backward compat
    with the historical long-only fleet."""
    conn = _create_db()
    # Insert with direction=NULL explicitly
    conn.execute("""
        INSERT INTO shadow_trades
        (trade_id, ticker, status, exit_reason, actual_exit_time, actual_exit_price,
         actual_entry_time, actual_entry_price, entry_price, stop_price, target_1, target_2,
         duration_days, timeout_days, direction, quarantined)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ["nodir", "AAPL", "closed", "stop_loss",
          _now_iso(1), 105.0,
          _now_iso(25), 100.0, 100.0, 96.0, 110.0, 120.0,
          1, 15, None, 0])
    conn.commit()
    result = _run(conn)
    # 105 > 96*1.01=96.96 → flagged under long fallback
    assert "nodir" in result["flagged_trade_ids"]


# ---------------------------------------------------------------------------
# Slippage tolerance constant — PR-690 O3
# ---------------------------------------------------------------------------

def test_slippage_tolerance_constant_used():
    """The slippage tolerance must be defined as a named module constant
    (not a magic literal). This guards against regression to `* 1.01`."""
    import inspect

    from src.shadow_trading import exit_reconciliation as mod

    assert hasattr(mod, "_STOP_LOSS_SLIPPAGE_TOLERANCE"), (
        "Module must expose _STOP_LOSS_SLIPPAGE_TOLERANCE as a named constant"
    )
    assert mod._STOP_LOSS_SLIPPAGE_TOLERANCE == 0.01

    src = inspect.getsource(mod._check_trade)
    # No magic literals in the stop_loss branch.
    assert "* 1.01" not in src, "_check_trade must reference the constant, not 1.01"
    assert "* 0.99" not in src, "_check_trade must reference the constant, not 0.99"
    # Constant is referenced at least twice (long + short branches, post-O2).
    assert src.count("_STOP_LOSS_SLIPPAGE_TOLERANCE") >= 2
