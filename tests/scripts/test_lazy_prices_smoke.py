"""Tests for scripts/backtest/lazy_prices_smoke_test.py."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.schema.sqlite import create_all_tables


def test_smoke_test_reaches_all_three_outcome_states(tmp_path, monkeypatch):
    """The synthetic-fallback smoke test must produce PASS, FAIL, and
    INCONCLUSIVE runs in the walkforward_results table, and write the
    report file."""
    db = tmp_path / "lazy_smoke.sqlite3"
    create_all_tables(str(db))
    report_dir = tmp_path / "validation"

    from scripts.backtest.lazy_prices_smoke_test import main
    rc = main([
        "--db-path", str(db),
        "--report-dir", str(report_dir),
        "--force-synthetic",
    ])
    assert rc == 0

    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT outcome_state FROM walkforward_results "
        "WHERE strategy_id = 'lazy_prices_v1'",
    ).fetchall()
    conn.close()
    states = {r[0] for r in rows}
    assert states == {"PASS", "FAIL", "INCONCLUSIVE"}


def test_smoke_test_writes_markdown_report(tmp_path):
    db = tmp_path / "db.sqlite3"
    create_all_tables(str(db))
    report_dir = tmp_path / "out"

    from scripts.backtest.lazy_prices_smoke_test import main
    rc = main([
        "--db-path", str(db),
        "--report-dir", str(report_dir),
    ])
    assert rc == 0
    reports = list(report_dir.glob("lazy-prices-v1-walkforward-*.md"))
    assert len(reports) == 1
    text = reports[0].read_text()
    assert "SYNTHETIC FALLBACK" in text
    assert "R8(a) declaration" in text
    assert "must NOT report PASS" in text
    # All three outcome states must appear.
    assert "PASS" in text and "FAIL" in text and "INCONCLUSIVE" in text


def test_smoke_test_respects_derived_from_null(tmp_path):
    """The spec declares derived_from: null — smoke test must not raise
    R8ViolationError and must record the null declaration in the report."""
    db = tmp_path / "db.sqlite3"
    create_all_tables(str(db))
    report_dir = tmp_path / "out"
    from scripts.backtest.lazy_prices_smoke_test import main
    rc = main([
        "--db-path", str(db), "--report-dir", str(report_dir),
    ])
    assert rc == 0
    reports = list(report_dir.glob("lazy-prices-v1-walkforward-*.md"))
    text = reports[0].read_text()
    assert "derived_from: None" in text


def test_smoke_test_report_contains_per_window_table(tmp_path):
    db = tmp_path / "db.sqlite3"
    create_all_tables(str(db))
    report_dir = tmp_path / "out"
    from scripts.backtest.lazy_prices_smoke_test import main
    rc = main([
        "--db-path", str(db), "--report-dir", str(report_dir),
    ])
    assert rc == 0
    reports = list(report_dir.glob("lazy-prices-v1-walkforward-*.md"))
    text = reports[0].read_text()
    assert "| Window | N trades | Sharpe | MDE | State |" in text
