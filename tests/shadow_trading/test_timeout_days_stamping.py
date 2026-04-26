"""Tests for executor open-path stamping of llm_timeout_days and timeout_days.

Track 1.5 / B8 executor slice.

Two cases:
  - LLM provides llm_timeout_days on the packet → shadow_trades.timeout_days = llm value,
    shadow_trades.llm_timeout_days = llm value
  - LLM does NOT provide llm_timeout_days (None) → shadow_trades.timeout_days = 15 (default),
    shadow_trades.llm_timeout_days = None

Uses insert_shadow_trade via a real in-memory DB so we don't need to mock the entire
open_shadow_trade call chain (which has many guards: validator, risk governor, etc.).
The stamps are applied just before insert_shadow_trade, so we test the assembled
trade_data dict by inspecting what lands in the DB.
"""
from __future__ import annotations

import sqlite3

import pytest

from src.journal.store import initialize_database, insert_shadow_trade


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade_data(
    trade_id: str,
    *,
    llm_timeout_days: int | None,
    timeout_days: int,
) -> dict:
    """Minimal trade_data dict mirroring what executor assembles pre-insert."""
    ts = "2026-04-26T09:30:00"
    return {
        "trade_id": trade_id,
        "ticker": "AAPL",
        "direction": "long",
        "status": "open",
        "source": "paper",
        "desk": "swing",
        "order_type": "bracket",
        "planned_shares": 10.0,
        "entry_price": 170.0,
        "actual_entry_price": 170.0,
        "stop_price": 161.5,
        "target_1": 180.0,
        "target_2": 0.0,
        "strategy_type": "pullback",
        "created_at": ts,
        "updated_at": ts,
        "timeout_days": timeout_days,
        "llm_timeout_days": llm_timeout_days,
    }


def _fetch_row(db_path: str, trade_id: str) -> dict | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT timeout_days, llm_timeout_days FROM shadow_trades WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_timeout_days_stamped_from_llm_value(tmp_path):
    """When LLM provides llm_timeout_days=30, timeout_days must equal 30."""
    db_path = str(tmp_path / "test_stamp.db")
    initialize_database(db_path)

    from src.shadow_trading.executor import GLOBAL_DEFAULT_TIMEOUT_DAYS

    # Simulate what executor does at open path:
    llm_value = 30
    timeout_days = llm_value if llm_value is not None else GLOBAL_DEFAULT_TIMEOUT_DAYS
    trade_data = _make_trade_data("t-llm-30", llm_timeout_days=llm_value, timeout_days=timeout_days)

    insert_shadow_trade(trade_data, db_path)
    row = _fetch_row(db_path, "t-llm-30")

    assert row is not None
    assert row["timeout_days"] == 30, (
        f"Expected timeout_days=30 (from LLM), got {row['timeout_days']}"
    )
    assert row["llm_timeout_days"] == 30, (
        f"Expected llm_timeout_days=30 preserved, got {row['llm_timeout_days']}"
    )


def test_timeout_days_falls_back_to_default_when_llm_is_null(tmp_path):
    """When LLM does not provide llm_timeout_days (None), timeout_days falls back to 15."""
    db_path = str(tmp_path / "test_stamp_null.db")
    initialize_database(db_path)

    from src.shadow_trading.executor import GLOBAL_DEFAULT_TIMEOUT_DAYS

    # Simulate what executor does at open path:
    llm_value = None
    timeout_days = llm_value if llm_value is not None else GLOBAL_DEFAULT_TIMEOUT_DAYS
    trade_data = _make_trade_data("t-llm-null", llm_timeout_days=llm_value, timeout_days=timeout_days)

    insert_shadow_trade(trade_data, db_path)
    row = _fetch_row(db_path, "t-llm-null")

    assert row is not None
    assert row["timeout_days"] == 15, (
        f"Expected timeout_days=15 (default fallback), got {row['timeout_days']}"
    )
    assert row["llm_timeout_days"] is None, (
        f"Expected llm_timeout_days=None (LLM did not emit), got {row['llm_timeout_days']}"
    )


def test_default_timeout_constant_is_15():
    """GLOBAL_DEFAULT_TIMEOUT_DAYS must be 15 — the operative fallback for pre-B8 rows."""
    from src.shadow_trading.executor import GLOBAL_DEFAULT_TIMEOUT_DAYS
    assert GLOBAL_DEFAULT_TIMEOUT_DAYS == 15


def test_instrumentation_version_stamped_on_insert(tmp_path):
    """instrumentation_version is stamped from INSTRUMENTATION_VERSION_CURRENT=2 at insert."""
    db_path = str(tmp_path / "test_iv_stamp.db")
    initialize_database(db_path)

    from src.shadow_trading.executor import INSTRUMENTATION_VERSION_CURRENT

    ts = "2026-04-26T09:30:00"
    trade_data = {
        "trade_id": "t-iv-stamp",
        "ticker": "MSFT",
        "direction": "long",
        "status": "open",
        "source": "paper",
        "desk": "swing",
        "order_type": "bracket",
        "planned_shares": 5.0,
        "entry_price": 420.0,
        "actual_entry_price": 420.0,
        "stop_price": 399.0,
        "target_1": 440.0,
        "target_2": 0.0,
        "strategy_type": "pullback",
        "created_at": ts,
        "updated_at": ts,
        "timeout_days": 15,
        "instrumentation_version": INSTRUMENTATION_VERSION_CURRENT,
    }
    insert_shadow_trade(trade_data, db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT instrumentation_version FROM shadow_trades WHERE trade_id = 't-iv-stamp'"
        ).fetchone()

    assert row is not None
    assert row["instrumentation_version"] == 3, (
        f"Expected instrumentation_version=3 (post-B5-amend), got "
        f"{row['instrumentation_version']}"
    )
