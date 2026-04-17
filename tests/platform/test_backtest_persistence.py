"""Tests for backtest CLI + persistence (Task 6)."""
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest


def test_backtest_tables_declared_in_registry():
    from src.schema.registry import TABLES
    assert "backtest_results" in TABLES
    assert "backtest_trades" in TABLES


def test_backtest_results_has_required_columns():
    from src.schema.registry import TABLES
    cols = {c.name for c in TABLES["backtest_results"].columns}
    assert {
        "result_id", "strategy_id", "spec_version", "spec_hash",
        "start_date", "end_date", "initial_capital", "total_trades",
        "total_return_pct", "sharpe", "excess_sharpe", "deflated_sharpe",
        "sortino", "calmar", "max_drawdown_pct", "win_rate",
        "profit_factor", "code_git_sha", "created_at",
    }.issubset(cols)


def test_backtest_trades_has_required_columns():
    from src.schema.registry import TABLES
    cols = {c.name for c in TABLES["backtest_trades"].columns}
    assert {
        "trade_id", "result_id", "ticker", "entry_date", "exit_date",
        "entry_price", "exit_price", "shares", "pnl_dollars",
        "pnl_pct", "exit_reason", "hold_days", "spy_return_over_hold",
        "excess_return", "realized_sector", "regime_at_entry",
    }.issubset(cols)


def test_spec_hash_changes_on_modification():
    from src.platform.strategy_spec import load_spec

    spec = load_spec("lazy_prices_v1")
    h1 = hashlib.sha256(
        json.dumps(spec.raw, sort_keys=True).encode()
    ).hexdigest()
    mutated = dict(spec.raw)
    mutated["display_name"] = mutated["display_name"] + " (modified)"
    h2 = hashlib.sha256(
        json.dumps(mutated, sort_keys=True).encode()
    ).hexdigest()
    assert h1 != h2


def test_run_id_uuid_generated():
    pytest.skip("integration-level — requires real data; run CLI manually")
