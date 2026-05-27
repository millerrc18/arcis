"""Cross-cutting integration tests — methodology gate wiring (Sprint 2 T8).

Locks the 15 critical and major safety properties across the following modules:
  - src/platform/promotion.py
  - src/scheduler/watch.py
  - src/cli/promotion_cmd.py
  - src/methods/promotion_gate.py
  - src/analytics/instrumentation_filter.py
  - src/training/trainer.py

Each test name corresponds 1:1 to a critical or major review finding.
All tests are hermetic (no .env, no FRED, no Alpaca) per worktree-env-drift rule.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.schema.sqlite import create_all_tables


# ---------------------------------------------------------------------------
# Fixtures and helpers shared across all 15 tests
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_db(tmp_path):
    db = str(tmp_path / "test_integration.db")
    create_all_tables(db)
    return db


def _register_strategy(db: str, sid: str, status: str = "backtested") -> None:
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


def _seed_backtest_row(
    db: str, sid: str,
    pbo: float | None = 0.30,
    oos_efficiency: float | None = None,
) -> str:
    rid = f"r_{sid}"
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """INSERT INTO backtest_results
               (result_id, strategy_id, spec_version, spec_hash,
                start_date, end_date, initial_capital, total_trades,
                total_return_pct, sharpe, excess_sharpe, deflated_sharpe,
                pbo, oos_efficiency,
                sortino, calmar, max_drawdown_pct, win_rate,
                profit_factor, code_git_sha, created_at, provenance_kind)
               VALUES (?, ?, 1, 'abc123', '2020-01-01', '2024-12-31', 100000.0,
                       50, 0.3, 1.5, 1.0, 0.9, ?, ?, 1.8, 2.0, 0.1, 0.6, 2.5,
                       'sha', '2024-01-01T00:00:00+00:00', 'quick_in_sample')""",
            (rid, sid, pbo, oos_efficiency),
        )
        conn.commit()
    finally:
        conn.close()
    return rid


def _seed_backtest_trades(db: str, sid: str, n: int = 60) -> None:
    rid = f"r_{sid}"
    conn = sqlite3.connect(db)
    try:
        for i in range(n):
            pnl = 0.01 + (i % 5 - 2) * 0.003
            conn.execute(
                """INSERT INTO backtest_trades
                   (trade_id, result_id, ticker, entry_date, exit_date, pnl_pct)
                   VALUES (?, ?, 'AAPL', '2024-01-01', '2024-01-10', ?)""",
                (f"bt_{sid}_{i}", rid, pnl),
            )
        conn.commit()
    finally:
        conn.close()


def _seed_shadow_trades(
    db: str,
    n: int = 30,
    missing_instrumentation: list[int] | None = None,
    null_entry_time_indices: list[int] | None = None,
) -> None:
    conn = sqlite3.connect(db)
    try:
        for i in range(n):
            is_missing = bool(missing_instrumentation and i in missing_instrumentation)
            is_null_entry = bool(null_entry_time_indices and i in null_entry_time_indices)
            day = (i % 28) + 1
            entry_time = None if is_null_entry else f"2024-01-{day:02d}T09:30:00+00:00"
            pnl = 0.01 + (i % 5 - 2) * 0.003
            conn.execute(
                """INSERT INTO shadow_trades
                   (trade_id, ticker, direction, status, actual_entry_time,
                    actual_exit_time, pnl_pct, excess_return,
                    desk, created_at, updated_at, instrumentation_version)
                   VALUES (?, 'AAPL', 'long', 'closed', ?,
                           '2024-01-20T16:00:00+00:00',
                           ?, ?, 'research_test', '2024-01-01T00:00:00+00:00',
                           '2024-01-01T00:00:00+00:00', 3)""",
                (
                    f"st_int_{i}",
                    entry_time,
                    pnl,
                    None if is_missing else 0.005,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _seed_trials_registry(db: str) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """INSERT INTO trials_registry
               (trial_id, strategy_id, spec_hash, n_params_searched,
                sr_raw, sr_ann, n_trades, skew, created_at)
               VALUES ('t1', 'global_strategy', 'abc', 1, 1.5, 2.0, 50, 0.1,
                       '2024-01-01T00:00:00+00:00')""",
        )
        conn.commit()
    finally:
        conn.close()


def _seed_walkforward_result(db: str, sid: str, state: str) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """INSERT INTO walkforward_results
               (run_id, strategy_id, spec_hash, outcome_state, reason,
                pooled_sharpe, pooled_mde, n_windows, n_windows_pass, n_windows_fail,
                n_windows_inconclusive_data, n_windows_inconclusive_power,
                heavy_tail_flag, created_at)
               VALUES ('wr_int_1', ?, 'abc123', ?, 'test reason',
                       1.5, 0.1, 3, 3, 0, 0, 0, 0,
                       '2024-01-01T00:00:00+00:00')""",
            (sid, state),
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


def _run_cli(
    args_list: list[str], db: str, input_text: str = "y\n",
) -> tuple[int, str, str]:
    from src.cli.promotion_cmd import cmd_confirm_promotion, build_confirm_promotion_parser
    import io
    import sys

    parser = build_confirm_promotion_parser()
    args = parser.parse_args(args_list)
    args.db_path = db

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
def _mock_fred(monkeypatch):
    with patch(
        "src.methods._rf_vector.compute_per_period_rf_vector",
        return_value=([0.0001] * 200, False),
    ):
        yield


# ---------------------------------------------------------------------------
# Test 1: Critical-1 — CLI delegates to promote(), never _apply_gate_outcome
# ---------------------------------------------------------------------------


def test_operator_confirm_calls_promote_not_synthetic_outcome(temp_db):
    """Critical 1: CLI must call promote() with triggered_by='operator_confirm'.
    _apply_gate_outcome must NOT be callable or present in the CLI module."""
    _register_strategy(temp_db, "i_s1", status="shadow_trading")
    _seed_gate_proposal(temp_db, "i_s1", decision="defer", composed_pass=True)

    with patch("src.platform.promotion.promote") as mock_promote:
        mock_promote.return_value = None
        exit_code, out, err = _run_cli(
            ["--strategy", "i_s1", "--justification",
             "This is a sufficiently long justification for the integration test",
             "--yes"],
            db=temp_db,
        )

    mock_promote.assert_called_once()
    call_kwargs = mock_promote.call_args
    triggered_by = call_kwargs.kwargs.get("triggered_by") or (
        call_kwargs.args[2] if len(call_kwargs.args) >= 3 else None
    )
    assert triggered_by == "operator_confirm", (
        f"promote() must be called with triggered_by='operator_confirm', got: {call_kwargs}"
    )

    import src.cli.promotion_cmd as cli_mod
    assert not hasattr(cli_mod, "_apply_gate_outcome"), (
        "promotion_cmd.py must not import or define _apply_gate_outcome"
    )
    assert "_apply_gate_outcome" not in dir(cli_mod), (
        "promotion_cmd.py must not expose _apply_gate_outcome in its namespace"
    )


# ---------------------------------------------------------------------------
# Test 2: Decision 4 — reject is not overridable
# ---------------------------------------------------------------------------


def test_reject_outcome_not_overridable_via_cli(temp_db):
    """Decision 4: CLI must exit non-zero when latest gate_proposal has decision='reject'."""
    _register_strategy(temp_db, "i_reject", status="shadow_trading")
    _seed_gate_proposal(
        temp_db, "i_reject",
        decision="reject",
        composed_pass=False,
    )

    exit_code, out, err = _run_cli(
        ["--strategy", "i_reject", "--justification",
         "This is a sufficiently long justification for rejection override test",
         "--yes"],
        db=temp_db,
    )

    assert exit_code != 0, "CLI must exit non-zero for reject proposals"
    combined = out + err
    assert "reject" in combined.lower(), "Error message must mention 'reject'"
    assert any(
        word in combined.lower()
        for word in ("not overridable", "cannot", "override", "overridable")
    ), "Error message must indicate reject is not overridable"


# ---------------------------------------------------------------------------
# Test 3: AND-composition — walkforward FAIL blocks methodology-only pass
# ---------------------------------------------------------------------------


def test_and_composition_with_walkforward_blocks_methodology_only_pass(temp_db):
    """Gate must AND-compose; methodology PASS + walkforward FAIL -> final result FAIL."""
    sid = "i_wf_fail"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_backtest_row(temp_db, sid, pbo=0.30)
    _seed_backtest_trades(temp_db, sid, n=60)
    _seed_shadow_trades(temp_db, n=30)
    _seed_trials_registry(temp_db)
    _seed_walkforward_result(temp_db, sid, "FAIL")

    from src.platform.promotion import check_promotion_gate

    with patch(
        "src.platform.promotion._evaluate_strategy_methodology_gate",
        return_value=(True, {"decision": "promote"}),
    ):
        passes, evidence = check_promotion_gate(sid, "shadow_trading", temp_db)

    assert passes is False, (
        "walkforward FAIL must block even when methodology gate passes"
    )
    assert "walkforward_outcome_state" in evidence
    assert evidence["walkforward_outcome_state"] == "FAIL"


# ---------------------------------------------------------------------------
# Test 4: DA major fix 1 — AND-compose at wf-PASS path (line 298)
# ---------------------------------------------------------------------------


def test_methodology_gate_and_composed_at_walkforward_pass_path(temp_db):
    """DA major fix 1: wf-PASS+PBO-PASS+DSR-PASS but methodology=False -> overall False."""
    sid = "i_wfpass_mgfail"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_backtest_row(temp_db, sid, pbo=0.30)
    _seed_backtest_trades(temp_db, sid, n=60)
    _seed_shadow_trades(temp_db, n=30)
    _seed_trials_registry(temp_db)
    _seed_walkforward_result(temp_db, sid, "PASS")

    from src.platform.promotion import check_promotion_gate

    with patch(
        "src.platform.promotion._evaluate_strategy_methodology_gate",
        return_value=(False, {"decision": "reject"}),
    ), patch(
        "src.platform.promotion._evaluate_dsr_evidence",
        return_value=(True, {"dsr": 0.97, "passes_dsr_min": True,
                             "n_eff_used_for_dsr": 5,
                             "trials_sr_variance_used": 0.1}),
    ):
        passes, evidence = check_promotion_gate(sid, "shadow_trading", temp_db)

    assert passes is False, (
        "DA major fix 1: wf-PASS + methodology-FAIL must return False"
    )
    assert "methodology_gate" in evidence, (
        "methodology_gate evidence must appear when composed"
    )


# ---------------------------------------------------------------------------
# Test 5: is_fully_instrumented filter excludes partial rows
# ---------------------------------------------------------------------------


def test_partial_instrumentation_excluded_from_gate_input(temp_db):
    """is_fully_instrumented filter excludes partial-instrumentation rows."""
    sid = "i_partial"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_backtest_row(temp_db, sid, pbo=0.30)
    _seed_backtest_trades(temp_db, sid, n=60)
    _seed_shadow_trades(temp_db, n=20, missing_instrumentation=list(range(10)))
    _seed_trials_registry(temp_db)

    from src.platform.promotion import _evaluate_strategy_methodology_gate

    captured = {}

    def fake_gate(returns, n_trials, **kwargs):
        captured["returns"] = returns
        return {
            "decision": "promote",
            "n_obs": len(returns),
            "mintrl": 5,
            "votes": {
                "cpcv": True,
                "block_bootstrap": True,
                "mc_perm": None,
                "psr_dsr": True,
                "white_rc": None,
            },
            "details": {
                "cpcv": {"value": 0.5, "threshold": 0.0},
                "block_bootstrap": {"value": 0.1, "threshold": 0.0},
                "mc_perm": {"value": None, "threshold": 0.05},
                "psr_dsr": {"value": 0.65, "threshold": 0.5},
                "white_rc": {"value": None, "threshold": 0.05},
                "n_pass": 3, "n_fail": 0, "n_abstentions": 2,
            },
        }

    with patch("src.methods.promotion_gate.promotion_gate", side_effect=fake_gate), \
         patch("src.platform.promotion._get_n_trials_for_strategy", return_value=1):
        passes, evidence = _evaluate_strategy_methodology_gate(sid, temp_db)

    assert evidence["instrumentation_excluded_count"] == 10, (
        "10 partially-instrumented rows must be excluded and counted"
    )
    assert len(captured.get("returns", [])) == 10, (
        "Only the 10 fully-instrumented rows must reach the gate"
    )


# ---------------------------------------------------------------------------
# Test 6: 4-of-4 fallback when candidate_pool < 2
# ---------------------------------------------------------------------------


def test_empty_candidate_pool_uses_4_of_4_fallback_with_threshold_key(temp_db):
    """When len(active_research_strategies) < 2, threshold_used='4_of_4_no_white_rc'."""
    sid = "i_fallback"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_backtest_row(temp_db, sid, pbo=0.30)
    _seed_backtest_trades(temp_db, sid, n=60)
    _seed_shadow_trades(temp_db, n=30)
    _seed_trials_registry(temp_db)

    from src.platform.promotion import _evaluate_strategy_methodology_gate

    def fake_gate(returns, n_trials, **kwargs):
        return {
            "decision": "promote",
            "n_obs": len(returns),
            "mintrl": 5,
            "votes": {
                "cpcv": True,
                "block_bootstrap": True,
                "mc_perm": None,
                "psr_dsr": True,
                "white_rc": None,
            },
            "details": {
                "cpcv": {"value": 0.5, "threshold": 0.0},
                "block_bootstrap": {"value": 0.1, "threshold": 0.0},
                "mc_perm": {"value": None, "threshold": 0.05},
                "psr_dsr": {"value": 0.65, "threshold": 0.5},
                "white_rc": {"value": None, "threshold": 0.05},
                "n_pass": 3, "n_fail": 0, "n_abstentions": 2,
            },
        }

    with patch("src.methods.promotion_gate.promotion_gate", side_effect=fake_gate), \
         patch("src.platform.promotion._get_n_trials_for_strategy", return_value=1), \
         patch(
             "src.platform.promotion.get_strategies_by_status",
             return_value=[sid],
         ):
        passes, evidence = _evaluate_strategy_methodology_gate(sid, temp_db)

    assert evidence["threshold_used"] == "4_of_4_no_white_rc", (
        "threshold_used must be '4_of_4_no_white_rc' when fewer than 2 candidates"
    )


# ---------------------------------------------------------------------------
# Test 7: Feature flag disabled short-circuits persistence
# ---------------------------------------------------------------------------


def test_feature_flag_disabled_short_circuits_persistence(temp_db):
    """METHODOLOGY_GATE_ENABLED=false -> (True, {'decision':'skipped'}), NO DB row."""
    sid = "i_ff"
    _register_strategy(temp_db, sid, status="backtested")

    with patch.dict(os.environ, {"METHODOLOGY_GATE_ENABLED": "false"}):
        import importlib
        import src.platform.promotion as promo_mod
        importlib.reload(promo_mod)

        passes, evidence = promo_mod._evaluate_strategy_methodology_gate(sid, temp_db)

    assert passes is True, (
        "Feature-flag disabled: helper must return True so AND-composition passes"
    )
    assert evidence.get("decision") == "skipped", (
        "Evidence must contain {'decision': 'skipped'} in disabled mode"
    )

    conn = sqlite3.connect(temp_db)
    count = conn.execute(
        "SELECT COUNT(*) FROM strategy_promotion_events WHERE strategy_id=?",
        (sid,),
    ).fetchone()[0]
    conn.close()
    assert count == 0, "No events must be written when METHODOLOGY_GATE_ENABLED=false"

    importlib.reload(promo_mod)


# ---------------------------------------------------------------------------
# Test 8: gate_proposal row has from_status == to_status
# ---------------------------------------------------------------------------


def test_gate_proposal_row_has_from_status_eq_to_status(temp_db):
    """triggered_by='gate_proposal' rows are informational; from_status == to_status."""
    sid = "i_proposal"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_backtest_row(temp_db, sid, pbo=0.30)
    _seed_shadow_trades(temp_db, n=20)
    _seed_trials_registry(temp_db)

    from src.platform.promotion import run_daily_gate_for_all_active_strategies

    with patch(
        "src.platform.promotion._evaluate_strategy_methodology_gate",
        return_value=(False, {"decision": "reject",
                              "instrumentation_excluded_count": 0}),
    ):
        run_daily_gate_for_all_active_strategies(temp_db)

    conn = sqlite3.connect(temp_db)
    row = conn.execute(
        """SELECT from_status, to_status, triggered_by, justification_note
           FROM strategy_promotion_events WHERE strategy_id=?""",
        (sid,),
    ).fetchone()
    conn.close()

    assert row is not None, "A gate_proposal event must be written"
    from_s, to_s, triggered_by, just_note = row
    assert triggered_by == "gate_proposal", (
        f"triggered_by must be 'gate_proposal', got '{triggered_by}'"
    )
    assert from_s == to_s, (
        f"from_status ({from_s!r}) must equal to_status ({to_s!r}) for gate_proposal rows"
    )
    assert just_note is None, "justification_note must be NULL for gate_proposal rows"


# ---------------------------------------------------------------------------
# Test 9: Major 4 — operator_confirm row has real status transition
# ---------------------------------------------------------------------------


def test_operator_confirm_row_has_real_transition(temp_db):
    """Major 4: operator_confirm rows show real status delta (backtested -> shadow_trading)."""
    _register_strategy(temp_db, "i_trans", status="backtested")
    _seed_gate_proposal(temp_db, "i_trans", decision="defer", composed_pass=True)

    with patch("src.platform.promotion.check_promotion_gate",
               return_value=(True, {"auto": True})):
        exit_code, out, err = _run_cli(
            ["--strategy", "i_trans", "--justification",
             "This is a sufficiently long justification for the transition test",
             "--target-status", "shadow_trading",
             "--yes"],
            db=temp_db,
        )

    assert exit_code == 0, (
        f"Expected exit 0 on success, got {exit_code}. out={out!r}, err={err!r}"
    )

    conn = sqlite3.connect(temp_db)
    row = conn.execute(
        """SELECT from_status, to_status FROM strategy_promotion_events
           WHERE strategy_id = ? AND triggered_by = 'operator_confirm'
           ORDER BY timestamp DESC LIMIT 1""",
        ("i_trans",),
    ).fetchone()
    conn.close()

    assert row is not None, "An operator_confirm event must be written"
    from_s, to_s = row
    assert from_s != to_s, (
        f"operator_confirm row must have from_status != to_status, got {from_s!r} -> {to_s!r}"
    )


# ---------------------------------------------------------------------------
# Test 10: DA major fix 2 — evidence schema matches _decide function
# ---------------------------------------------------------------------------


def test_methodology_gate_evidence_schema_matches_decide_function(temp_db):
    """DA major fix 2: vote keys flat bool|None; NO pbo in votes; NO top-level tally."""
    sid = "i_schema"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_backtest_row(temp_db, sid, pbo=0.30)
    _seed_backtest_trades(temp_db, sid, n=60)
    _seed_shadow_trades(temp_db, n=30)
    _seed_trials_registry(temp_db)

    from src.platform.promotion import _evaluate_strategy_methodology_gate

    spec_result = {
        "decision": "reject",
        "n_obs": 30,
        "mintrl": 5,
        "votes": {
            "cpcv": True,
            "block_bootstrap": True,
            "mc_perm": None,
            "psr_dsr": True,
            "white_rc": None,
        },
        "details": {
            "cpcv": {"value": 0.5, "threshold": 0.0},
            "block_bootstrap": {"value": 0.1, "threshold": 0.0},
            "mc_perm": {"value": None, "threshold": 0.05,
                        "details": {"reason": "mc_permutation_requires_real_directions"}},
            "psr_dsr": {"value": 0.65, "threshold": 0.5},
            "white_rc": {"value": None, "threshold": 0.05,
                         "details": {"reason": "white_rc_requires_candidate_pool"}},
            "inverse_hard_block": False,
            "n_pass": 3,
            "n_fail": 0,
            "n_abstentions": 2,
            "rf_source": "unwired",
        },
    }

    with patch("src.methods.promotion_gate.promotion_gate", return_value=spec_result), \
         patch("src.platform.promotion._get_n_trials_for_strategy", return_value=1):
        _, evidence = _evaluate_strategy_methodology_gate(sid, temp_db)

    mg = evidence["methodology_gate"]

    assert "votes" in mg
    votes = mg["votes"]
    expected_vote_names = {"cpcv", "block_bootstrap", "mc_perm", "psr_dsr", "white_rc"}
    assert set(votes.keys()) == expected_vote_names, (
        f"vote keys must be exactly {expected_vote_names}, got {set(votes.keys())}"
    )
    for name, val in votes.items():
        assert val is None or isinstance(val, bool), (
            f"vote '{name}' must be bool|None, got {type(val)}"
        )

    assert "pbo" not in votes, "pbo must NOT appear in methodology_gate votes"
    assert "tally" not in mg, "no top-level 'tally' key in methodology_gate"

    assert "details" in mg
    det = mg["details"]
    for method_name in expected_vote_names:
        assert method_name in det, f"details must contain '{method_name}'"
        assert "value" in det[method_name], f"details['{method_name}'] must have 'value'"
        assert "threshold" in det[method_name], (
            f"details['{method_name}'] must have 'threshold'"
        )

    for counter in ("n_pass", "n_fail", "n_abstentions"):
        assert counter in det, f"'{counter}' must be in details"


# ---------------------------------------------------------------------------
# Test 11: DA major fix 5 — production gate AND-composes methodology with DSR only
# ---------------------------------------------------------------------------


def test_production_gate_methodology_compose_with_dsr_only(temp_db):
    """DA major fix 5: production-gate AND-composes with DSR only (PBO/wf are Sprint-4)."""
    sid = "i_prod_mg"
    _register_strategy(temp_db, sid, status="shadow_trading")
    _seed_backtest_row(temp_db, sid, pbo=None, oos_efficiency=None)
    _seed_backtest_trades(temp_db, sid, n=60)
    _seed_trials_registry(temp_db)

    from src.platform.promotion import check_promotion_gate

    with patch(
        "src.platform.promotion._evaluate_strategy_methodology_gate",
        return_value=(False, {"decision": "reject"}),
    ), patch(
        "src.platform.promotion._evaluate_dsr_evidence",
        return_value=(True, {"dsr": 0.97, "passes_dsr_min": True,
                             "n_eff_used_for_dsr": 5,
                             "trials_sr_variance_used": 0.1}),
    ):
        passes, evidence = check_promotion_gate(sid, "production", temp_db)

    assert passes is False, (
        "DA major fix 5: passing DSR + failing methodology -> False for production target"
    )
    assert evidence.get("pbo") is None, "pbo must remain None (Sprint-4 placeholder)"
    assert evidence.get("oos_efficiency") is None, (
        "oos_efficiency must remain None (Sprint-4 placeholder)"
    )


# ---------------------------------------------------------------------------
# Test 12: DA major fix 4 — walkforward_status for all four states
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state,expected", [
    ("PASS", "pass"),
    ("FAIL", "fail"),
    ("INCONCLUSIVE", "inconclusive"),
])
def test_walkforward_status_populated_for_all_four_states(state, expected, temp_db):
    """DA major fix 4: walkforward_status takes values 'no_data_yet','pass','fail','inconclusive'."""
    sid = f"i_wfstatus_{state.lower()}"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_walkforward_result(temp_db, sid, state)

    from src.platform.promotion import _evaluate_walkforward_gate

    evidence: dict = {}
    _evaluate_walkforward_gate(sid, temp_db, evidence)

    assert "walkforward_status" in evidence
    assert evidence["walkforward_status"] == expected, (
        f"expected walkforward_status='{expected}', got '{evidence['walkforward_status']}'"
    )


def test_walkforward_status_no_data_yet_for_fourth_state(temp_db):
    """DA major fix 4: walkforward_status='no_data_yet' when no walkforward row exists."""
    sid = "i_wf_nodata"
    _register_strategy(temp_db, sid, status="backtested")

    from src.platform.promotion import _evaluate_walkforward_gate

    evidence: dict = {}
    _evaluate_walkforward_gate(sid, temp_db, evidence)

    assert evidence.get("walkforward_status") == "no_data_yet", (
        "walkforward_status must be 'no_data_yet' when no walkforward_results row"
    )


# ---------------------------------------------------------------------------
# Test 13: DA major fix 4 — walkforward_outcome_state still populated for backwards-compat
# ---------------------------------------------------------------------------


def test_walkforward_outcome_state_still_populated_for_backwards_compat(temp_db):
    """DA major fix 4: walkforward_outcome_state is still populated alongside walkforward_status."""
    sid = "i_wf_compat"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_walkforward_result(temp_db, sid, "PASS")

    from src.platform.promotion import _evaluate_walkforward_gate

    evidence: dict = {}
    _evaluate_walkforward_gate(sid, temp_db, evidence)

    assert "walkforward_outcome_state" in evidence, (
        "walkforward_outcome_state must still be set (backwards-compat)"
    )
    assert "walkforward_status" in evidence, (
        "walkforward_status must also be set (new key)"
    )
    assert evidence["walkforward_outcome_state"] == "PASS", (
        "walkforward_outcome_state must preserve the raw uppercase value"
    )
    assert evidence["walkforward_status"] == "pass", (
        "walkforward_status must be lowercase"
    )


# ---------------------------------------------------------------------------
# Test 14: Minor 1 / T5-T2 ratchet — CLI re-fire includes methodology gate
# ---------------------------------------------------------------------------


def test_cli_confirm_promotion_re_fire_includes_methodology_gate(temp_db):
    """Minor 1 / T5-T2 ordering ratchet: CLI promote() re-fire calls methodology gate."""
    _register_strategy(temp_db, "i_mg", status="shadow_trading")
    _seed_gate_proposal(temp_db, "i_mg", decision="defer", composed_pass=True)

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
               VALUES ('r_img', 'i_mg', 1, 'abc123', '2020-01-01', '2024-12-31', 100000.0,
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
            ["--strategy", "i_mg", "--justification",
             "This is a sufficiently long justification for the methodology gate integration test",
             "--yes"],
            db=temp_db,
        )

    assert mg_call_spy.called, (
        "_evaluate_strategy_methodology_gate must be called during promote() re-fire. "
        "T5 depends on T2 AND-compose wiring."
    )


# ---------------------------------------------------------------------------
# Test 15: Choice A regression-lock — trainer path cannot promote long-only
# ---------------------------------------------------------------------------


def test_trainer_promotion_gate_currently_cannot_promote_long_only(tmp_path, monkeypatch):
    """Choice A regression-lock: trainer path with long-only directions cannot reach 'promote'.

    With directions=[+1]*N, MC permutation shuffles a constant sequence — which
    is identity — giving p=1.0. That is a FAIL vote, so the gate ceiling is 3-of-5
    (or less), never reaching the 4-of-5 threshold. Decision must be 'reject' or
    'defer', never 'promote'. Locks spec §1.3.1 long-only degeneracy.

    Uses T3's canonical model_versions + init_training_tables pattern; mocks
    FRED per CLAUDE.md "Mock all external APIs in tests".
    """
    monkeypatch.setattr(
        "src.methods._rf_vector.compute_per_period_rf_vector",
        lambda dates: ([0.0001] * len(dates), False),
    )

    from src.training.versioning import init_training_tables
    from src.journal.store import initialize_database

    db = str(tmp_path / "test_lo.db")
    init_training_tables(db)
    initialize_database(db)

    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """INSERT INTO model_versions
               (version_id, version_name, created_at, training_examples_count,
                synthetic_examples_count, outcome_examples_count,
                model_file_path, status)
               VALUES ('v_lo_1', 'long-only-v1', datetime('now'), 10, 0, 0,
                       'test.gguf', 'active')""",
        )
        for i in range(60):
            pnl = 3.0 + (i % 5 - 2) * 0.3
            day = (i % 28) + 1
            conn.execute(
                """INSERT INTO shadow_trades
                   (trade_id, ticker, status, pnl_pct, actual_entry_time,
                    created_at, updated_at)
                   VALUES (?, 'AAPL', 'closed', ?, ?, datetime('now'), datetime('now'))""",
                (f"st_lo_{i}", pnl, f"2024-02-{day:02d}T10:00:00"),
            )
        conn.commit()
    finally:
        conn.close()

    from src.training.trainer import run_promotion_gate_for_version

    result = run_promotion_gate_for_version(
        version_id="v_lo_1",
        version_name="long-only-v1",
        db_path=db,
        n_trials=1,
    )

    decision = result.get("decision") if isinstance(result, dict) else None
    assert decision != "promote", (
        f"Choice A: long-only system must NOT promote via trainer path, "
        f"got decision={decision!r}. Locks spec §1.3.1 long-only MC-perm degeneracy."
    )

    n_pass = result.get("details", {}).get("n_pass") if isinstance(result, dict) else None
    if n_pass is not None:
        assert n_pass <= 3, (
            f"Spec §1.3.1 ceiling: trainer path cannot exceed 3-of-5 votes "
            f"under long-only directions; got n_pass={n_pass}. The gate threshold "
            f"is 4-of-5 — n_pass>=4 here would mean MC-perm degeneracy is no longer "
            f"deterministic and the regression lock has slipped."
        )
