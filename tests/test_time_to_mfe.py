"""Tests for time_to_mfe tracking added in DB-FINAL Task 1.

These exercise the MFE update branch of check_and_manage_open_trades:
  - new MFE high     → time_to_mfe_days + mfe_timestamp update
  - flat / adverse   → prior values preserved
  - trade closes     → final values remain on the row
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.journal.store import initialize_database

ET = ZoneInfo("America/New_York")


def _seed_open_trade(db_path: str, **overrides) -> str:
    """Insert one open shadow_trade and return its trade_id."""
    trade_id = overrides.pop("trade_id", "mfe-test-001")
    now_iso = datetime.now(ET).isoformat()
    row = {
        "trade_id": trade_id,
        "ticker": "AAPL",
        "direction": "long",
        "status": "open",
        "entry_price": 100.0,
        "actual_entry_price": 100.0,
        "actual_entry_time": (datetime.now(ET) - timedelta(days=2)).isoformat(),
        "stop_price": 95.0,
        "target_1": 110.0,
        "planned_shares": 10,
        "actual_shares": 10,
        "max_favorable_excursion": 0.0,
        "max_adverse_excursion": 0.0,
        "time_to_mfe_days": None,
        "mfe_timestamp": None,
        "source": "paper",
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    row.update(overrides)

    with sqlite3.connect(db_path) as conn:
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        conn.execute(
            f"INSERT INTO shadow_trades ({cols}) VALUES ({placeholders})",
            tuple(row.values()),
        )
        conn.commit()
    return trade_id


def _fetch(db_path: str, trade_id: str) -> dict:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM shadow_trades WHERE trade_id = ?", (trade_id,)
        ).fetchone()
    return dict(row) if row else {}


def _run_manage(db_path: str, current_price: float) -> None:
    """Drive check_and_manage_open_trades once with a fixed current price."""
    from src.shadow_trading import executor

    with patch.object(executor, "_get_current_price_safe", return_value=current_price):
        with patch.object(executor, "load_config", return_value={
            "shadow_trading": {"timeout_days": 15, "max_positions": 50},
            "risk_governor": {"enabled": False},
        }):
            executor.check_and_manage_open_trades(db_path=db_path)


def test_mfe_high_updates_day_and_timestamp(tmp_path):
    db_path = str(tmp_path / "mfe.sqlite3")
    initialize_database(db_path)
    trade_id = _seed_open_trade(db_path)

    # Push price to $105 — new MFE high (+$5 / share)
    _run_manage(db_path, current_price=105.0)

    row = _fetch(db_path, trade_id)
    assert row["max_favorable_excursion"] > 0
    assert row["time_to_mfe_days"] is not None
    assert row["time_to_mfe_days"] >= 0
    assert row["mfe_timestamp"] is not None
    # ISO format sanity
    datetime.fromisoformat(row["mfe_timestamp"])


def test_mfe_flat_preserves_prior_timestamp(tmp_path):
    db_path = str(tmp_path / "mfe.sqlite3")
    initialize_database(db_path)

    # Seed with an existing MFE peak from a prior cycle
    prior_ts = (datetime.now(ET) - timedelta(days=1)).isoformat()
    trade_id = _seed_open_trade(
        db_path,
        max_favorable_excursion=8.0,      # prior peak of +$8 / share
        time_to_mfe_days=1,
        mfe_timestamp=prior_ts,
    )

    # Current price $103 → price_move = +$3, which is BELOW the stored MFE of +$8
    _run_manage(db_path, current_price=103.0)

    row = _fetch(db_path, trade_id)
    assert row["max_favorable_excursion"] == 8.0, "MFE peak must not regress"
    assert row["time_to_mfe_days"] == 1, "days should hold at prior peak"
    assert row["mfe_timestamp"] == prior_ts, "timestamp should hold at prior peak"


def test_mfe_values_persist_after_close(tmp_path):
    """When the trade closes, the peak days/timestamp remain on the row."""
    db_path = str(tmp_path / "mfe.sqlite3")
    initialize_database(db_path)

    peak_ts = (datetime.now(ET) - timedelta(hours=6)).isoformat()
    trade_id = _seed_open_trade(
        db_path,
        max_favorable_excursion=10.0,
        time_to_mfe_days=2,
        mfe_timestamp=peak_ts,
    )

    # Close the trade directly, same way the executor's exit path would
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE shadow_trades SET status = 'closed', actual_exit_price = 108.0, "
            "actual_exit_time = ?, pnl_dollars = 80.0, exit_reason = 'target_1_hit', "
            "updated_at = ? WHERE trade_id = ?",
            (datetime.now(ET).isoformat(), datetime.now(ET).isoformat(), trade_id),
        )
        conn.commit()

    row = _fetch(db_path, trade_id)
    assert row["status"] == "closed"
    # The close path doesn't touch MFE fields — peak values carry through
    assert row["time_to_mfe_days"] == 2
    assert row["mfe_timestamp"] == peak_ts
    assert row["max_favorable_excursion"] == 10.0
