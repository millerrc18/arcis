"""Persist backtest results to SQLite.

Extracted from scripts/run_backtest.py so that both the CLI script and
cloud_routes/platform.py can import without crossing the scripts/ boundary
(Render deploys don't ship scripts/).

Calls: none (pure persistence — sqlite3 only)
Called by: scripts/run_backtest.py, api/cloud_routes/platform.py
Owns tables: writes backtest_results, backtest_trades
Config keys: none
Tests: tests/platform/test_platform_api.py (integration via cloud route)
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from src.utils.db import connect_db
import uuid
from datetime import datetime, timezone


def spec_hash(raw: dict) -> str:
    """Deterministic SHA-256 of a strategy spec dict."""
    return hashlib.sha256(
        json.dumps(raw, sort_keys=True).encode()
    ).hexdigest()


def persist_backtest_result(
    result, *, db_path: str, provenance_kind: str, git_sha: str = "unknown",
) -> str:
    """Write backtest result + trades to SQLite. Returns result_id (UUID).

    provenance_kind (#110) is REQUIRED — one of 'quick_in_sample' |
    'wf_is_window' | 'wf_is_window_orphan_partial_run'. The CHECK
    constraint on backtest_results refuses NULL; the caller always knows.
    git_sha is CLI's git rev-parse output or RENDER_GIT_COMMIT env var.
    """
    result_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    m = result.metrics
    conn = connect_db(db_path)
    try:
        conn.execute(
            """INSERT INTO backtest_results
               (result_id, strategy_id, spec_version, spec_hash, start_date,
                end_date, initial_capital, total_trades, total_return_pct,
                sharpe, excess_sharpe, deflated_sharpe, pbo, oos_efficiency,
                sortino, calmar, max_drawdown_pct, win_rate, profit_factor,
                code_git_sha, created_at, provenance_kind)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result_id, result.strategy_id,
                result.config.strategy.raw.get("spec_version", 1),
                spec_hash(result.config.strategy.raw),
                result.config.start_date, result.config.end_date,
                result.config.initial_capital, m.get("n_trades"),
                m.get("total_return_pct"), m.get("sharpe"),
                m.get("excess_sharpe"), None,  # deflated_sharpe — Sprint 2 wires this
                m.get("pbo"),               # NULL until param-sweep campaign (Sprint 4)
                m.get("oos_efficiency"),    # NULL unless populated via /arcis:strategy backtest
                m.get("sortino"), m.get("calmar"),
                m.get("max_drawdown_pct"),
                m.get("win_rate"), m.get("profit_factor"),
                git_sha, created_at, provenance_kind,
            ),
        )
        for t in result.trades:
            conn.execute(
                """INSERT INTO backtest_trades
                   (trade_id, result_id, ticker, entry_date, exit_date,
                    entry_price, exit_price, shares, pnl_dollars, pnl_pct,
                    exit_reason, hold_days, spy_return_over_hold,
                    excess_return, realized_sector, regime_at_entry)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    t.trade_id, result_id, t.ticker, t.entry_date,
                    t.exit_date, t.entry_price, t.exit_price, t.shares,
                    t.pnl_dollars, t.pnl_pct, t.exit_reason, t.hold_days,
                    t.spy_return_over_hold, t.excess_return,
                    t.realized_sector, t.regime_at_entry,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return result_id
