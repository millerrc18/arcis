"""Shared seed helper for outcome_stats_filter_sql tests.

Module: tests._helpers.seed_closed_trades
Purpose: Seed shadow_trades rows with normal-closed, reconciled_stale, and
         reconciled exit_reasons to test that outcome_stats_filter_sql() correctly
         excludes reconciled_stale rows from outcome statistics.
Called by: tests across evaluation, council, email, scheduler, api, notifications, cost_model.
Owns tables: none
Config keys: none
"""

import sqlite3
import uuid


_CREATE_SHADOW_TRADES = """
CREATE TABLE IF NOT EXISTS shadow_trades (
    trade_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    exit_reason TEXT,
    pnl_dollars REAL,
    pnl_pct REAL,
    quarantined INTEGER DEFAULT 0,
    source TEXT DEFAULT 'paper',
    actual_exit_time TEXT,
    entry_price REAL,
    actual_entry_price REAL,
    actual_exit_price REAL,
    planned_shares REAL DEFAULT 1,
    actual_shares REAL DEFAULT 1,
    signal_entry_price REAL,
    signal_exit_price REAL,
    fill_entry_price REAL,
    fill_exit_price REAL,
    max_adverse_excursion REAL,
    created_at TEXT DEFAULT (datetime('now'))
)
"""


def _make_conn() -> sqlite3.Connection:
    """Return a fresh in-memory connection with shadow_trades table."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_SHADOW_TRADES)
    conn.commit()
    return conn


def seed_closed_trades(
    conn: sqlite3.Connection,
    n_normal: int = 10,
    n_reconciled_stale: int = 5,
    n_reconciled: int = 2,
) -> None:
    """Seed N normal-closed (target_1, pnl_dollars=100, pnl_pct=2.0) + M reconciled_stale (pnl=0) + K reconciled (legacy, pnl=50) shadow_trades for outcome_stats_filter testing."""
    rows = []

    for i in range(n_normal):
        rows.append((
            str(uuid.uuid4()),
            f"TICK{i:02d}",
            "closed",
            "target_1",
            100.0,
            2.0,
            0,
            "paper",
            f"2026-01-{(i % 28) + 1:02d}T15:00:00",
            100.0,
            100.0,
            102.0,
            10.0,
            10.0,
            100.0,
            102.0,
            100.20,
            101.80,
            1.5,
        ))

    for i in range(n_reconciled_stale):
        rows.append((
            str(uuid.uuid4()),
            f"STALE{i:02d}",
            "closed",
            "reconciled_stale",
            0.0,
            0.0,
            0,
            "paper",
            f"2026-01-{(i % 28) + 1:02d}T16:00:00",
            50.0,
            0.0,
            0.0,
            5.0,
            5.0,
            50.0,
            50.0,
            0.0,
            0.0,
            0.0,
        ))

    for i in range(n_reconciled):
        rows.append((
            str(uuid.uuid4()),
            f"RECON{i:02d}",
            "closed",
            "reconciled",
            50.0,
            1.0,
            0,
            "paper",
            f"2026-01-{(i % 28) + 1:02d}T17:00:00",
            50.0,
            50.5,
            51.0,
            5.0,
            5.0,
            50.0,
            51.0,
            50.10,
            50.90,
            0.5,
        ))

    conn.executemany(
        """INSERT INTO shadow_trades (
            trade_id, ticker, status, exit_reason,
            pnl_dollars, pnl_pct, quarantined, source,
            actual_exit_time, entry_price, actual_entry_price, actual_exit_price,
            planned_shares, actual_shares,
            signal_entry_price, signal_exit_price,
            fill_entry_price, fill_exit_price,
            max_adverse_excursion
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
