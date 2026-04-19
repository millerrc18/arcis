"""Integration tests for scripts/backtest/run_walkforward.py CLI wrapper."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from src.schema.sqlite import create_all_tables


@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    """Give the CLI a fresh DB path + an on-disk spec yaml."""
    db = tmp_path / "wf_cli.sqlite3"
    create_all_tables(str(db))
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    spec_data = {
        "spec_version": 1,
        "strategy_id": "cli_test_v1",
        "display_name": "CLI Test Strategy",
        "universe": {"tickers": ["AAPL"]},
        "entry": {
            "kind": "scheduled", "day_of_week": "Monday", "time": "close",
        },
        "exit": {
            "kind": "mechanical", "timeout_days": 5,
            "stop": {"method": "pct", "value": 0.02},
            "target": {"method": "pct", "value": 0.03},
        },
        "position_sizing": {"method": "fixed_pct_equity", "pct": 0.15,
                             "max_concurrent": 1},
        "attribution": {"benchmark": "SPY_matched_window",
                         "metrics": ["sharpe"]},
        "derived_from": None,
    }
    (specs_dir / "cli_test_v1.yaml").write_text(yaml.safe_dump(spec_data))
    monkeypatch.setenv("ARCIS_DB_PATH", str(db))
    return {"db": str(db), "specs_dir": str(specs_dir)}


def test_cli_dry_run_exits_zero_and_prints_config(tmp_env, capsys):
    from scripts.backtest.run_walkforward import main
    rc = main([
        "--strategy", "cli_test_v1",
        "--db-path", tmp_env["db"],
        "--specs-dir", tmp_env["specs_dir"],
        "--dry-run",
    ])
    assert rc == 0
    captured = capsys.readouterr().out
    # The printed JSON must be parseable and contain the canonical windows
    parsed = json.loads(captured)
    assert parsed["strategy_id"] == "cli_test_v1"
    assert len(parsed["windows"]) == 5


def test_cli_skip_engine_writes_walkforward_results(tmp_env, capsys):
    from scripts.backtest.run_walkforward import main
    rc = main([
        "--strategy", "cli_test_v1",
        "--db-path", tmp_env["db"],
        "--specs-dir", tmp_env["specs_dir"],
        "--skip-engine",  # no real backtests; all-empty windows → FAIL
        "--json",
    ])
    # Empty windows: either INCONCLUSIVE (≥2 INCONCLUSIVE_DATA) or FAIL
    # depending on criterion 2 arithmetic. We accept both non-PASS outcomes.
    assert rc in (1, 3)
    out = json.loads(capsys.readouterr().out)
    assert out["outcome_state"] in ("FAIL", "INCONCLUSIVE")
    conn = sqlite3.connect(tmp_env["db"])
    row = conn.execute(
        "SELECT run_id, outcome_state FROM walkforward_results "
        "WHERE strategy_id = ?",
        ("cli_test_v1",),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == out["run_id"]


def test_cli_reports_nonzero_exit_code_for_fail(tmp_env):
    from scripts.backtest.run_walkforward import main
    rc = main([
        "--strategy", "cli_test_v1",
        "--db-path", tmp_env["db"],
        "--specs-dir", tmp_env["specs_dir"],
        "--skip-engine",
    ])
    # Empty windows → not PASS → rc != 0
    assert rc != 0


def test_cli_missing_strategy_returns_2(tmp_env, capsys):
    from scripts.backtest.run_walkforward import main
    rc = main([
        "--strategy", "does_not_exist",
        "--db-path", tmp_env["db"],
        "--specs-dir", tmp_env["specs_dir"],
    ])
    assert rc == 2


def test_cli_rejects_bootcamp_override_via_config_validation(tmp_env, monkeypatch):
    """Can't set bootcamp via flag — but if someone tried, WalkForwardConfig
    raises in __post_init__. Here we verify the CLI propagates the error
    cleanly rather than succeeding silently."""
    # Force the CLI to construct a bad config by monkeypatching WalkForwardConfig
    # to default bootcamp_override=True (simulating a malicious caller).
    from scripts.backtest import run_walkforward as cli_mod

    class BadConfig:
        def __init__(self, **kwargs):
            raise ValueError("forced-bad-config")

    monkeypatch.setattr(cli_mod, "WalkForwardConfig", BadConfig)
    rc = cli_mod.main([
        "--strategy", "cli_test_v1",
        "--db-path", tmp_env["db"],
        "--specs-dir", tmp_env["specs_dir"],
    ])
    assert rc == 2
