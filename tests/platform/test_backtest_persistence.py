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




def test_backtest_uses_registry_survivorship_haircut(tmp_path):
    """Bonus: CLI/engine must pick up survivorship_haircut_bps from
    strategy_registry rather than always defaulting to 75."""
    db = tmp_path / "test.db"
    from src.schema.sqlite import create_all_tables
    create_all_tables(str(db))
    # Register strategy with explicit haircut=200 (momentum default)
    from src.platform.promotion import register_strategy
    register_strategy(
        strategy_id="mom_test", display_name="Mom Test",
        spec_source="test", spec_hash="x",
        survivorship_haircut_bps=200, db_path=str(db),
    )
    # Read back and verify the value is stored
    import sqlite3
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT survivorship_haircut_bps FROM strategy_registry "
        "WHERE strategy_id = 'mom_test'"
    ).fetchone()
    conn.close()
    assert row[0] == 200
    # The CLI wiring check — run_backtest.py::main must read this.
    # Test the helper rather than shelling out the CLI.
    from scripts.run_backtest import _get_survivorship_haircut_bps
    assert _get_survivorship_haircut_bps("mom_test", str(db)) == 200
    # Unknown strategy → default 75
    assert _get_survivorship_haircut_bps("nonexistent", str(db)) == 75
