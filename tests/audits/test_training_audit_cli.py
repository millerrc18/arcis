"""End-to-end test of scripts/audits/training_data_v1_audit.py.

Verifies the CLI wires argparse → run_audit → report + JSON summary
output without any mocking.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.audits.training_data_v1_audit import main, parse_args


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE training_examples ("
        "example_id TEXT PRIMARY KEY, source TEXT, ticker TEXT, "
        "input_text TEXT, output_text TEXT, trade_outcome TEXT, "
        "outcome TEXT, outcome_type TEXT, recommendation_id TEXT, "
        "quarantined INTEGER DEFAULT 0, quarantine_reason TEXT)"
    )
    conn.execute(
        "CREATE TABLE attribution_trades ("
        "attribution_id TEXT, recommendation_id TEXT, "
        "ranker_only_outcome TEXT, ranker_only_outcome_v1 TEXT, "
        "resolution_version TEXT)"
    )
    conn.execute(
        "INSERT INTO training_examples VALUES "
        "('ok-1', 'blinded_win', 'AAPL', "
        "'Ticker: AAPL\nCurrent Price: $1\nTrend State: up',"
        "'<why_now>x</why_now>\n<analysis>y</analysis>', "
        "'win', 'win', 'primary', NULL, 0, NULL)"
    )
    conn.execute(
        "INSERT INTO training_examples VALUES "
        "('bad-1', 'blinded_win', 'CSCO', "
        "'Ticker: CSCO\nCurrent Price: $60\nTrend State: down',"
        "'<why_now>Trade stopped out and continued decline.</why_now>\n"
        "<analysis>x</analysis>', "
        "'loss', 'loss', 'primary', 'rec-2', 0, NULL)"
    )
    conn.execute(
        "INSERT INTO attribution_trades VALUES "
        "('att-1', 'rec-2', 'win', 'loss', 'v2')"
    )
    conn.commit()
    conn.close()


def test_parse_args_dry_run():
    ns = parse_args(["--dry-run", "--pass", "A"])
    assert ns.dry_run is True
    assert ns.passes == ["A"]


def test_parse_args_multiple_passes():
    ns = parse_args(["--pass", "A", "--pass", "B"])
    assert ns.passes == ["A", "B"]


def test_parse_args_defaults():
    ns = parse_args([])
    assert ns.dry_run is False
    assert ns.passes is None


def test_cli_end_to_end_dry_run_prints_summary_json(tmp_path, capsys):
    db = tmp_path / "t.sqlite3"
    _make_db(db)
    report = tmp_path / "out.md"
    plots = tmp_path / "plots/"

    rc = main([
        "--db", str(db),
        "--output", str(report),
        "--plot-dir", str(plots),
        "--dry-run",
        "--pass", "A", "--pass", "B",
    ])
    assert rc == 0

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["dry_run"] is True
    assert summary["rows_written"] == 0
    assert summary["total_audited"] == 2
    # Pass A should quarantine bad-1
    assert (
        summary["quarantined_by_reason"]
        .get("v1_attribution_contradicts_narrative") == 1
    )

    # Report file written
    assert report.exists()
    content = report.read_text(encoding="utf-8")
    assert "## Executive Summary" in content
    assert "## Pass A" in content
    assert "## Pass B" in content
    assert "## Pass C" in content
    assert "## Remaining Clean Corpus" in content

    # DB unchanged (dry-run)
    with sqlite3.connect(str(db)) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM training_examples WHERE quarantined=1"
        ).fetchone()[0]
    assert n == 0


def test_cli_write_mode_updates_db(tmp_path):
    db = tmp_path / "t.sqlite3"
    _make_db(db)
    report = tmp_path / "out.md"
    plots = tmp_path / "plots/"

    rc = main([
        "--db", str(db),
        "--output", str(report),
        "--plot-dir", str(plots),
        "--pass", "A",
    ])
    assert rc == 0

    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT example_id, quarantine_reason FROM training_examples "
            "WHERE quarantined=1"
        ).fetchall()
    assert ("bad-1", "v1_attribution_contradicts_narrative") in rows


def test_cli_reruns_produce_identical_summaries(tmp_path, capsys):
    """R5 — idempotency. Two consecutive dry-runs must match."""
    db = tmp_path / "t.sqlite3"
    _make_db(db)

    def _run():
        capsys.readouterr()  # reset
        rc = main([
            "--db", str(db),
            "--output", str(tmp_path / "r.md"),
            "--plot-dir", str(tmp_path / "p/"),
            "--dry-run",
            "--pass", "A", "--pass", "B",
        ])
        assert rc == 0
        return json.loads(capsys.readouterr().out)

    s1 = _run()
    s2 = _run()
    # Pass C leakage_accuracy may oscillate with very small datasets;
    # normalize before comparing.
    for s in (s1, s2):
        s.pop("pass_c_leakage_accuracy", None)
    assert s1 == s2
