"""Tests for main.py refactor — verify CLI dispatches and size."""

import pytest
import os


def test_main_py_line_count():
    """main.py should be under 1000 lines (grew with live trading + reconciliation + validation commands)."""
    main_path = os.path.join(os.path.dirname(__file__), "..", "src", "main.py")
    with open(main_path, encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) < 1000, f"main.py is {len(lines)} lines (target: < 1000)"


def test_all_commands_registered():
    """All required commands should be in the argument parser."""
    from src.main import build_parser
    parser = build_parser()

    # Get all subcommand names
    subparsers_actions = [
        action for action in parser._subparsers._actions
        if hasattr(action, '_name_parser_map')
    ]
    assert len(subparsers_actions) == 1

    commands = set(subparsers_actions[0]._name_parser_map.keys())

    # Core pipeline
    assert "scan" in commands
    assert "morning-watchlist" in commands
    assert "eod-recap" in commands
    assert "ingest" in commands
    assert "init-db" in commands
    assert "demo-packet" in commands

    # Shadow ledger
    assert "shadow-status" in commands
    assert "shadow-history" in commands
    assert "shadow-close" in commands
    assert "shadow-account" in commands

    # Review
    assert "review" in commands
    assert "mark-executed" in commands
    assert "review-scorecard" in commands
    assert "review-bootcamp" in commands
    assert "postmortems" in commands

    # Training
    assert "training-status" in commands
    assert "training-history" in commands
    assert "training-report" in commands
    assert "bootstrap-training" in commands
    assert "backfill-training" in commands
    assert "train" in commands

    # New training quality commands
    assert "classify-training-data" in commands
    assert "score-training-data" in commands
    assert "validate-training-data" in commands
    assert "generate-contrastive" in commands
    assert "generate-preferences" in commands

    # Evaluation
    assert "cto-report" in commands
    assert "evaluate-holdout" in commands
    assert "model-evaluation-status" in commands
    assert "promote-model" in commands
    assert "feature-importance" in commands
    assert "backtest" in commands
    assert "compare-models" in commands

    # Operations
    assert "halt-trading" in commands
    assert "resume-trading" in commands
    assert "preflight" in commands
    assert "watch" in commands
    assert "dashboard" in commands


def test_scan_command_has_flags():
    """Scan command should support --verbose, --email, --dry-run, --no-shadow."""
    from src.main import build_parser
    parser = build_parser()
    args = parser.parse_args(["scan", "--verbose", "--dry-run"])
    assert args.verbose is True
    assert args.dry_run is True


def test_cto_report_command_has_flags():
    """CTO report should support --days, --json, --email."""
    from src.main import build_parser
    parser = build_parser()
    args = parser.parse_args(["cto-report", "--days", "14", "--json"])
    assert args.days == 14
    assert args.json is True


def test_backtest_command_has_flags():
    from src.main import build_parser
    parser = build_parser()
    args = parser.parse_args(["backtest", "--model", "test-model", "--months", "3"])
    assert args.model == "test-model"
    assert args.months == 3


def test_generate_contrastive_has_max_pairs():
    from src.main import build_parser
    parser = build_parser()
    args = parser.parse_args(["generate-contrastive", "--max-pairs", "25"])
    assert args.max_pairs == 25


def test_generate_preferences_has_count():
    from src.main import build_parser
    parser = build_parser()
    args = parser.parse_args(["generate-preferences", "--count", "200"])
    assert args.count == 200
