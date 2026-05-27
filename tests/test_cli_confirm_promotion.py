"""Tests for Sprint 2 T5 — confirm-promotion CLI command.

Critical-1 lock: the CLI MUST delegate to platform.promotion.promote() with
triggered_by='operator_confirm'. It MUST NOT call _apply_gate_outcome directly.

All tests are hermetic (no .env, no FRED, no Alpaca) per worktree-env-drift rule.
"""
from __future__ import annotations

import importlib
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from io import StringIO
from unittest.mock import MagicMock, call, patch

import pytest

from src.schema.sqlite import create_all_tables


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_db(tmp_path):
    db = str(tmp_path / "test_cp.db")
    create_all_tables(db)
    return db


def _register_strategy(db: str, sid: str, status: str = "shadow_trading") -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """INSERT INTO strategy_registry
               (strategy_id, display_name, spec_source, current_status,
                current_spec_hash, survivorship_haircut_bps, created_at,
                last_status_change)
               VALUES (?, ?, ?, ?, ?, 75, '2024-01-01T00:00:00+00:00',
                       '2024-01-01T00:00:00+00:00')""",
            (sid, sid.upper(), f"yaml:specs/{sid}.yaml", status, "abc123"),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_gate_proposal(
    db: str,
    strategy_id: str,
    decision: str = "defer",
    composed_pass: bool = True,
    hours_ago: float = 1.0,
) -> int:
    """Seed a gate_proposal row. Returns event_id."""
    gate_result = {
        "decision": decision,
        "composed_pass": composed_pass,
        "votes": {
            "cpcv": True,
            "block_bootstrap": True,
            "mc_perm": None,
            "psr_dsr": True,
            "white_rc": None,
        },
        "walkforward_status": "pass",
        "threshold_used": "4_of_5",
        "n_obs": 30,
        "mintrl": 5,
        "details": {
            "n_pass": 3,
            "n_fail": 0,
            "n_abstentions": 2,
        },
    }
    ts = (
        datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    ).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    conn = sqlite3.connect(db)
    try:
        cursor = conn.execute(
            """INSERT INTO strategy_promotion_events
               (strategy_id, from_status, to_status, triggered_by,
                gate_result_json, justification_note, timestamp)
               VALUES (?, ?, ?, 'gate_proposal', ?, NULL, ?)""",
            (
                strategy_id,
                "shadow_trading",
                "shadow_trading",
                json.dumps(gate_result),
                ts,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def _run_cli(args_list: list[str], db: str, input_text: str = "y\n") -> tuple[int, str, str]:
    """
    Import and call cmd_confirm_promotion with patched sys.argv + stdin.
    Returns (exit_code, stdout, stderr).
    """
    from src.cli.promotion_cmd import cmd_confirm_promotion, build_confirm_promotion_parser

    parser = build_confirm_promotion_parser()
    args = parser.parse_args(args_list)
    args.db_path = db

    import io
    old_stdin = sys.stdin
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdin = io.StringIO(input_text)
    captured_out = io.StringIO()
    captured_err = io.StringIO()
    sys.stdout = captured_out
    sys.stderr = captured_err

    exit_code = 0
    try:
        result = cmd_confirm_promotion(args)
        if isinstance(result, int):
            exit_code = result
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 1
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    return exit_code, captured_out.getvalue(), captured_err.getvalue()


# autouse fixture: mock FRED calls to prevent network access in any test
@pytest.fixture(autouse=True)
def mock_fred(monkeypatch):
    with patch(
        "src.methods._rf_vector.compute_per_period_rf_vector",
        return_value=([0.0001] * 200, False),
    ):
        yield


# ---------------------------------------------------------------------------
# Critical-1 lock: CLI delegates to promote(), NOT _apply_gate_outcome
# ---------------------------------------------------------------------------


def test_operator_confirm_calls_promote_not_synthetic_outcome(temp_db):
    """Critical 1: CLI must call promote() with triggered_by='operator_confirm'.
    _apply_gate_outcome must NOT be callable or imported in the CLI module."""
    _register_strategy(temp_db, "s1", status="shadow_trading")
    _seed_gate_proposal(temp_db, "s1", decision="defer", composed_pass=True)

    with patch("src.platform.promotion.promote") as mock_promote:
        mock_promote.return_value = None

        exit_code, out, err = _run_cli(
            ["--strategy", "s1", "--justification",
             "This is a sufficiently long justification for the operator confirm action",
             "--yes"],
            db=temp_db,
        )

    # promote() MUST be called with triggered_by='operator_confirm'
    mock_promote.assert_called_once()
    call_kwargs = mock_promote.call_args
    assert call_kwargs.kwargs.get("triggered_by") == "operator_confirm" or (
        len(call_kwargs.args) >= 3 and call_kwargs.args[2] == "operator_confirm"
    ), f"promote() must be called with triggered_by='operator_confirm', got: {call_kwargs}"

    # Structural guard: _apply_gate_outcome must NOT be an attribute or import in the CLI module
    import src.cli.promotion_cmd as mod
    assert not hasattr(mod, "_apply_gate_outcome"), (
        "promotion_cmd.py must not import or define _apply_gate_outcome — "
        "CLI is a thin wrapper around promote(), not a synthetic-outcome path"
    )


def test_apply_gate_outcome_not_imported_in_promotion_cmd():
    """Structural guard: promotion_cmd.py must not import _apply_gate_outcome.
    This test checks the module's namespace (not source text) to be precise."""
    import importlib
    mod = importlib.import_module("src.cli.promotion_cmd")
    # The function must not exist as an attribute in the CLI module's namespace
    assert not hasattr(mod, "_apply_gate_outcome"), (
        "promotion_cmd.py must not import or alias _apply_gate_outcome"
    )
    # Verify it also doesn't smuggle it in via a wildcard import
    # (hasattr covers both direct def and * imports)
    assert "_apply_gate_outcome" not in dir(mod), (
        "promotion_cmd.py must not expose _apply_gate_outcome in its namespace"
    )


# ---------------------------------------------------------------------------
# Decision 4: reject is not overridable
# ---------------------------------------------------------------------------


def test_reject_outcome_not_overridable_via_cli(temp_db, capsys):
    """Decision 4: CLI must refuse if latest gate_proposal has decision='reject'."""
    _register_strategy(temp_db, "s_reject", status="shadow_trading")
    _seed_gate_proposal(
        temp_db, "s_reject",
        decision="reject",
        composed_pass=False,
    )

    exit_code, out, err = _run_cli(
        ["--strategy", "s_reject", "--justification",
         "This is a sufficiently long justification for an operator override attempt",
         "--yes"],
        db=temp_db,
    )

    assert exit_code != 0, "CLI must exit non-zero for reject proposals"
    combined = out + err
    assert "reject" in combined.lower(), (
        "Error message must mention 'reject'"
    )
    assert "not overridable" in combined.lower() or "cannot" in combined.lower() or \
           "override" in combined.lower() or "overridable" in combined.lower(), (
        "Error message must indicate reject is not overridable"
    )


# ---------------------------------------------------------------------------
# Decision 14: stale proposal guard
# ---------------------------------------------------------------------------


def test_stale_proposal_rejected_by_cli(temp_db):
    """Decision 14: proposal older than 24h must cause CLI to exit 4 without calling promote()."""
    _register_strategy(temp_db, "s_stale", status="shadow_trading")
    _seed_gate_proposal(temp_db, "s_stale", decision="defer", composed_pass=True, hours_ago=25.0)

    with patch("src.platform.promotion.promote") as mock_promote:
        exit_code, out, err = _run_cli(
            ["--strategy", "s_stale", "--justification",
             "This is a sufficiently long justification for the stale test case",
             "--yes"],
            db=temp_db,
        )

    assert exit_code == 4, f"Expected exit 4 for stale proposal, got {exit_code}"
    mock_promote.assert_not_called()


# ---------------------------------------------------------------------------
# Short justification rejected client-side
# ---------------------------------------------------------------------------


def test_short_justification_rejected_client_side(temp_db):
    """Client-side check: justification < 40 chars must cause exit 4 without calling promote()."""
    _register_strategy(temp_db, "s_short", status="shadow_trading")
    _seed_gate_proposal(temp_db, "s_short", decision="defer", composed_pass=True)

    with patch("src.platform.promotion.promote") as mock_promote:
        exit_code, out, err = _run_cli(
            ["--strategy", "s_short", "--justification", "too short", "--yes"],
            db=temp_db,
        )

    assert exit_code == 4, f"Expected exit 4 for short justification, got {exit_code}"
    mock_promote.assert_not_called()


# ---------------------------------------------------------------------------
# No gate_proposal row — exit 4
# ---------------------------------------------------------------------------


def test_no_gate_proposal_exits_4(temp_db):
    """CLI must exit 4 if no gate_proposal row exists for the strategy."""
    _register_strategy(temp_db, "s_nogp", status="shadow_trading")

    with patch("src.platform.promotion.promote") as mock_promote:
        exit_code, out, err = _run_cli(
            ["--strategy", "s_nogp", "--justification",
             "This is a sufficiently long justification for no-proposal case",
             "--yes"],
            db=temp_db,
        )

    assert exit_code == 4, f"Expected exit 4 when no gate_proposal row, got {exit_code}"
    mock_promote.assert_not_called()


# ---------------------------------------------------------------------------
# promote() re-fire rejection — exit non-zero, no event_id printed
# ---------------------------------------------------------------------------


def test_promote_re_fires_gate_server_side(temp_db):
    """Server-side re-fire rejection: promote() raises ValueError on gate failure.
    CLI must catch, exit non-zero, and NOT print event_id."""
    _register_strategy(temp_db, "s_refire", status="shadow_trading")
    _seed_gate_proposal(temp_db, "s_refire", decision="defer", composed_pass=True)

    with patch("src.platform.promotion.promote",
               side_effect=ValueError("promotion gate failed: data drift detected")):
        exit_code, out, err = _run_cli(
            ["--strategy", "s_refire", "--justification",
             "This is a sufficiently long justification for the re-fire test case",
             "--yes"],
            db=temp_db,
        )

    assert exit_code != 0, "CLI must exit non-zero when promote() raises"
    # event_id must NOT appear in output (success indicator)
    combined = out + err
    assert "event_id" not in combined.lower(), (
        "CLI must not print event_id when promote() raises"
    )


# ---------------------------------------------------------------------------
# Major 4: verify from_status != to_status on the row written by promote()
# ---------------------------------------------------------------------------


def test_operator_confirm_row_has_real_transition(temp_db):
    """Major 4: The promote() call must produce a from_status != to_status row.
    We register the strategy as 'backtested' and promote to 'shadow_trading'
    so the event row shows a real status transition."""
    _register_strategy(temp_db, "s_trans", status="backtested")
    _seed_gate_proposal(temp_db, "s_trans", decision="defer", composed_pass=True)

    # patch check_promotion_gate to pass, so promote() doesn't hit real gate logic
    with patch("src.platform.promotion.check_promotion_gate",
               return_value=(True, {"auto": True})):
        exit_code, out, err = _run_cli(
            ["--strategy", "s_trans", "--justification",
             "This is a sufficiently long justification for the transition test",
             "--target-status", "shadow_trading",
             "--yes"],
            db=temp_db,
        )

    assert exit_code == 0, f"Expected exit 0 on success, got {exit_code}. out={out!r}, err={err!r}"

    # Check that the operator_confirm event has from_status != to_status
    conn = sqlite3.connect(temp_db)
    try:
        row = conn.execute(
            """SELECT from_status, to_status FROM strategy_promotion_events
               WHERE strategy_id = ? AND triggered_by = 'operator_confirm'
               ORDER BY timestamp DESC LIMIT 1""",
            ("s_trans",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, "An operator_confirm event must be written"
    from_s, to_s = row
    assert from_s != to_s, (
        f"operator_confirm row must have from_status != to_status, got {from_s!r} -> {to_s!r}"
    )


# ---------------------------------------------------------------------------
# Success path: event_id printed, exit 0
# ---------------------------------------------------------------------------


def test_successful_confirm_prints_event_id(temp_db):
    """On success, CLI must print event_id and exit 0."""
    _register_strategy(temp_db, "s_ok", status="shadow_trading")
    _seed_gate_proposal(temp_db, "s_ok", decision="defer", composed_pass=True)

    with patch("src.platform.promotion.check_promotion_gate",
               return_value=(True, {"auto": True})):
        exit_code, out, err = _run_cli(
            ["--strategy", "s_ok", "--justification",
             "This is a sufficiently long justification for the success test case",
             "--yes"],
            db=temp_db,
        )

    assert exit_code == 0, f"Expected exit 0, got {exit_code}. out={out!r}, err={err!r}"
    # event_id printed to stdout
    assert "event" in out.lower() or any(c.isdigit() for c in out), (
        "CLI must print event_id on success"
    )


# ---------------------------------------------------------------------------
# Minor 1 / T5-T2 ordering ratchet: promote() re-fire uses AND-compose methodology gate
# ---------------------------------------------------------------------------


def test_cli_confirm_promotion_re_fire_includes_methodology_gate(temp_db):
    """Minor 1 / T5-T2 ratchet: when CLI calls promote() -> check_promotion_gate
    -> _evaluate_shadow_trading_gate, the methodology gate (_evaluate_strategy_methodology_gate)
    IS in the call graph. This locks that T5 only works correctly after T2 merged.

    We verify by patching _evaluate_strategy_methodology_gate and asserting it's
    called during the CLI's promote() execution path."""
    _register_strategy(temp_db, "s_mg", status="shadow_trading")
    _seed_gate_proposal(temp_db, "s_mg", decision="defer", composed_pass=True)

    # Seed backtest data so _evaluate_shadow_trading_gate doesn't fail on missing data
    conn = sqlite3.connect(temp_db)
    try:
        conn.execute(
            """INSERT INTO backtest_results
               (result_id, strategy_id, spec_version, spec_hash,
                start_date, end_date, initial_capital, total_trades,
                total_return_pct, sharpe, excess_sharpe, deflated_sharpe,
                pbo, oos_efficiency,
                sortino, calmar, max_drawdown_pct, win_rate,
                profit_factor, code_git_sha, created_at, provenance_kind)
               VALUES ('r1', 's_mg', 1, 'abc123', '2020-01-01', '2024-12-31', 100000.0,
                       50, 0.3, 1.5, 1.0, 0.9, 0.30, 0.35, 1.8, 2.0, 0.1, 0.6, 2.5,
                       'sha', '2024-01-01T00:00:00+00:00', 'quick_in_sample')""",
        )
        conn.commit()
    finally:
        conn.close()

    mg_call_spy = MagicMock(return_value=(True, {
        "decision": "promote",
        "composed_pass": True,
        "votes": {},
        "threshold_used": "4_of_5",
        "n_obs": 30,
        "mintrl": 5,
        "details": {},
    }))

    with patch("src.platform.promotion._evaluate_strategy_methodology_gate", mg_call_spy):
        _run_cli(
            ["--strategy", "s_mg", "--justification",
             "This is a sufficiently long justification for the methodology gate test",
             "--yes"],
            db=temp_db,
        )

    # The methodology gate must have been called during promote()'s re-fire
    assert mg_call_spy.called, (
        "_evaluate_strategy_methodology_gate must be called in the promote() re-fire path. "
        "T5 depends on T2's AND-compose wiring."
    )
