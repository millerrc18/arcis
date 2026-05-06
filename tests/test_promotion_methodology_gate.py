"""Tests for Sprint 2 T2 — methodology gate wiring into platform.promotion.

Covers:
- _evaluate_strategy_methodology_gate helper aggregation / filtering
- AND-composition at all 7 return sites in _evaluate_shadow_trading_gate
- AND-composition at the 1 return site in _evaluate_production_gate
- walkforward_status placement (alongside walkforward_outcome_state)
- run_daily_gate_for_all_active_strategies orchestrator
- METHODOLOGY_GATE_ENABLED feature flag short-circuit
- 4-of-4 fallback when candidate_pool < 2

All tests are hermetic (no .env, no FRED, no Alpaca) per worktree-env-drift rule.
"""
from __future__ import annotations

import importlib
import os
import sqlite3
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.schema.sqlite import create_all_tables


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_db(tmp_path):
    db = str(tmp_path / "test_mg.db")
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
                profit_factor, code_git_sha, created_at)
               VALUES (?, ?, 1, 'abc123', '2020-01-01', '2024-12-31', 100000.0,
                       50, 0.3, 1.5, 1.0, 0.9, ?, ?, 1.8, 2.0, 0.1, 0.6, 2.5,
                       'sha', '2024-01-01T00:00:00+00:00')""",
            (rid, sid, pbo, oos_efficiency),
        )
        conn.commit()
    finally:
        conn.close()
    return rid


def _seed_backtest_trades(
    db: str, sid: str, n: int = 60,
    pnl_values: list[float] | None = None,
) -> None:
    rid = f"r_{sid}"
    if pnl_values is None:
        pnl_values = [0.01] * n
    conn = sqlite3.connect(db)
    try:
        for i, pnl in enumerate(pnl_values):
            conn.execute(
                """INSERT INTO backtest_trades
                   (trade_id, result_id, ticker, entry_date, exit_date,
                    pnl_pct)
                   VALUES (?, ?, 'AAPL', '2024-01-01', '2024-01-10', ?)""",
                (f"bt_{sid}_{i}", rid, pnl),
            )
        conn.commit()
    finally:
        conn.close()


def _seed_shadow_trades(
    db: str, sid: str, n: int = 20,
    entry_time: str = "2024-01-15T09:30:00+00:00",
    exit_time: str = "2024-01-20T16:00:00+00:00",
    pnl_pct: float = 0.015,
    missing_instrumentation: list[int] | None = None,
) -> None:
    """Seed shadow_trades for strategy sid.

    missing_instrumentation: list of 0-based trade indices where
    excess_return is NULL (making is_fully_instrumented return False).
    actual_entry_time and pnl_pct are always set so rows reach the
    is_fully_instrumented filter; the missing column is excess_return.
    """
    conn = sqlite3.connect(db)
    try:
        for i in range(n):
            is_missing = bool(missing_instrumentation and i in missing_instrumentation)
            conn.execute(
                """INSERT INTO shadow_trades
                   (trade_id, ticker, direction, status, actual_entry_time,
                    actual_exit_time, pnl_pct, excess_return,
                    desk, created_at, updated_at, instrumentation_version)
                   VALUES (?, 'AAPL', 'long', 'closed', ?, ?,
                           ?, ?, 'research_test', '2024-01-01T00:00:00+00:00',
                           '2024-01-01T00:00:00+00:00', 3)""",
                (
                    f"st_{sid}_{i}",
                    entry_time,
                    exit_time,
                    pnl_pct,
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


def _seed_walkforward_result(
    db: str, sid: str, state: str,
) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """INSERT INTO walkforward_results
               (run_id, strategy_id, spec_hash, outcome_state, reason,
                pooled_sharpe, pooled_mde, n_windows, n_windows_pass, n_windows_fail,
                n_windows_inconclusive_data, n_windows_inconclusive_power,
                heavy_tail_flag, created_at)
               VALUES ('wr_1', ?, 'abc123', ?, 'test reason',
                       1.5, 0.1, 3, 3, 0, 0, 0, 0,
                       '2024-01-01T00:00:00+00:00')""",
            (sid, state),
        )
        conn.commit()
    finally:
        conn.close()


# Promotion gate result shapes for mocking
def _make_passing_mg_result() -> dict:
    """Build a methodology gate result that means 'promote'."""
    return {
        "decision": "promote",
        "n_obs": 30,
        "mintrl": 5,
        "votes": {
            "cpcv": True,
            "block_bootstrap": True,
            "mc_perm": None,
            "psr_dsr": True,
            "white_rc": True,
        },
        "details": {
            "cpcv": {"value": 0.8, "threshold": 0.0},
            "block_bootstrap": {"value": 0.3, "threshold": 0.0},
            "mc_perm": {"value": None, "threshold": 0.05,
                        "details": {"reason": "mc_permutation_requires_real_directions"}},
            "psr_dsr": {"value": 0.75, "threshold": 0.5},
            "white_rc": {"value": 0.02, "threshold": 0.05},
            "inverse_hard_block": False,
            "n_pass": 4,
            "n_fail": 0,
            "n_abstentions": 1,
            "rf_source": "unwired",
        },
    }


def _make_failing_mg_result() -> dict:
    """Build a methodology gate result that means 'reject'."""
    return {
        "decision": "reject",
        "n_obs": 30,
        "mintrl": 5,
        "votes": {
            "cpcv": False,
            "block_bootstrap": False,
            "mc_perm": None,
            "psr_dsr": False,
            "white_rc": None,
        },
        "details": {
            "cpcv": {"value": -0.1, "threshold": 0.0},
            "block_bootstrap": {"value": -0.05, "threshold": 0.0},
            "mc_perm": {"value": None, "threshold": 0.05,
                        "details": {"reason": "mc_permutation_requires_real_directions"}},
            "psr_dsr": {"value": 0.3, "threshold": 0.5},
            "white_rc": {"value": None, "threshold": 0.05,
                         "details": {"reason": "white_rc_requires_candidate_pool"}},
            "inverse_hard_block": False,
            "n_pass": 0,
            "n_fail": 3,
            "n_abstentions": 2,
            "rf_source": "unwired",
        },
    }


# ---------------------------------------------------------------------------
# Helper: import promotion freshly (avoids cached env state)
# ---------------------------------------------------------------------------


def _get_promotion():
    import src.platform.promotion as promo
    return promo


# ---------------------------------------------------------------------------
# Test: helper aggregates shadow trades correctly
# ---------------------------------------------------------------------------


def test_helper_aggregates_shadow_trades_correctly(temp_db):
    """_evaluate_strategy_methodology_gate loads shadow_trades and calls promotion_gate."""
    sid = "s_agg"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_backtest_row(temp_db, sid, pbo=0.30)
    _seed_backtest_trades(temp_db, sid, n=60)
    _seed_shadow_trades(temp_db, sid, n=30)
    _seed_trials_registry(temp_db)

    from src.platform.promotion import _evaluate_strategy_methodology_gate

    passing_result = _make_passing_mg_result()

    with patch(
        "src.methods.promotion_gate.promotion_gate",
        return_value=passing_result,
    ) as mock_gate, patch(
        "src.platform.promotion._get_n_trials_for_strategy",
        return_value=1,
    ):
        passes, evidence = _evaluate_strategy_methodology_gate(sid, temp_db)

    assert mock_gate.called, "promotion_gate should have been called"
    call_kwargs = mock_gate.call_args
    returns_passed = call_kwargs[1].get("returns") if call_kwargs[1] else (call_kwargs[0][0] if call_kwargs[0] else None)
    assert returns_passed is not None
    assert len(returns_passed) == 30, (
        "All 30 instrumented shadow trades should reach the gate"
    )
    assert "methodology_gate" in evidence
    assert evidence["methodology_gate"]["decision"] == "promote"
    assert passes is True


# ---------------------------------------------------------------------------
# Test: partial instrumentation exclusion (Major 5)
# ---------------------------------------------------------------------------


def test_partial_instrumentation_excluded_from_gate_input(temp_db):
    """Trades failing is_fully_instrumented are excluded; count is recorded."""
    sid = "s_partial"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_backtest_row(temp_db, sid, pbo=0.30)
    _seed_backtest_trades(temp_db, sid, n=60)
    # 20 total trades, 10 missing instrumentation (indices 0-9)
    _seed_shadow_trades(
        temp_db, sid, n=20,
        missing_instrumentation=list(range(10)),
    )
    _seed_trials_registry(temp_db)

    from src.platform.promotion import _evaluate_strategy_methodology_gate

    with patch(
        "src.methods.promotion_gate.promotion_gate",
        return_value=_make_passing_mg_result(),
    ) as mock_gate, patch(
        "src.platform.promotion._get_n_trials_for_strategy",
        return_value=1,
    ):
        passes, evidence = _evaluate_strategy_methodology_gate(sid, temp_db)

    assert evidence["instrumentation_excluded_count"] == 10, (
        "10 rows failed is_fully_instrumented and should be counted as excluded"
    )
    # Only 10 fully-instrumented rows should reach the gate
    call_args = mock_gate.call_args
    returns_arg = call_args[1].get("returns") if call_args[1] else (call_args[0][0] if call_args[0] else None)
    assert len(returns_arg) == 10, (
        "Only the 10 instrumented rows should be passed to promotion_gate"
    )


# ---------------------------------------------------------------------------
# Test: 4-of-4 fallback when candidate_pool < 2 (Major 6)
# ---------------------------------------------------------------------------


def test_empty_candidate_pool_uses_4_of_4_fallback_with_threshold_key(temp_db):
    """When no active_research_strategies, threshold_used='4_of_4_no_white_rc'."""
    sid = "s_fallback"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_backtest_row(temp_db, sid, pbo=0.30)
    _seed_backtest_trades(temp_db, sid, n=60)
    _seed_shadow_trades(temp_db, sid, n=30)
    _seed_trials_registry(temp_db)

    # No other strategies -> candidate_pool will be empty -> 4-of-4 fallback
    from src.platform.promotion import _evaluate_strategy_methodology_gate

    # Mock promotion_gate to capture what it receives and return a result
    captured = {}

    def fake_gate(returns, n_trials, **kwargs):
        captured.update(kwargs)
        # Return a promote-like result with white_rc abstained
        result = _make_passing_mg_result()
        # white_rc abstains when no candidate_pool
        result["votes"]["white_rc"] = None
        return result

    with patch("src.methods.promotion_gate.promotion_gate", side_effect=fake_gate), patch(
        "src.platform.promotion._get_n_trials_for_strategy",
        return_value=1,
    ), patch(
        "src.platform.promotion.get_strategies_by_status",
        return_value=[sid],  # only 1 strategy, no candidate_pool
    ):
        passes, evidence = _evaluate_strategy_methodology_gate(sid, temp_db)

    # candidate_pool should be None (no other strategies)
    assert captured.get("candidate_pool") is None, (
        "candidate_pool should be None when no other strategies present"
    )
    assert evidence["threshold_used"] == "4_of_4_no_white_rc", (
        "threshold_used must be '4_of_4_no_white_rc' when fewer than 2 candidates"
    )


# ---------------------------------------------------------------------------
# Test: feature flag disabled short-circuits persistence (Decision 7)
# ---------------------------------------------------------------------------


def test_feature_flag_disabled_short_circuits_persistence(temp_db):
    """METHODOLOGY_GATE_ENABLED=false: gate returns (True, {'decision': 'skipped'})
    and writes NO strategy_promotion_events row."""
    sid = "s_ff"
    _register_strategy(temp_db, sid, status="backtested")

    with patch.dict(os.environ, {"METHODOLOGY_GATE_ENABLED": "false"}):
        # Reimport to pick up env flag in the helper itself
        import importlib
        import src.platform.promotion as promo_mod
        importlib.reload(promo_mod)

        passes, evidence = promo_mod._evaluate_strategy_methodology_gate(sid, temp_db)

    assert passes is True, (
        "Feature-flag disabled: helper must return (True, ...) so AND-composition passes"
    )
    assert evidence.get("decision") == "skipped", (
        "Evidence must contain {'decision': 'skipped'} in disabled mode"
    )

    # No persistence side-effect
    conn = sqlite3.connect(temp_db)
    count = conn.execute(
        "SELECT COUNT(*) FROM strategy_promotion_events WHERE strategy_id=?",
        (sid,),
    ).fetchone()[0]
    conn.close()
    assert count == 0, "No events should be written in METHODOLOGY_GATE_ENABLED=false mode"

    # Reload to reset env for other tests
    importlib.reload(promo_mod)


# ---------------------------------------------------------------------------
# Test: AND-composition — walkforward blocks but methodology only passes
# ---------------------------------------------------------------------------


def test_and_composition_with_walkforward_blocks_methodology_only_pass(temp_db):
    """When walkforward=FAIL and methodology=promote, overall is False."""
    sid = "s_wf_fail"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_backtest_row(temp_db, sid, pbo=0.30)
    _seed_backtest_trades(temp_db, sid, n=60)
    _seed_shadow_trades(temp_db, sid, n=30)
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
# Test: DA major fix 1 — methodology gate AND-composed at wf-PASS path (line 298)
# ---------------------------------------------------------------------------


def test_methodology_gate_and_composed_at_walkforward_pass_path(temp_db):
    """DA major fix 1: wf-PASS + PBO-PASS + DSR-PASS but methodology=False -> overall False.

    This directly tests that line 298 (the only True-returning walkforward branch)
    has AND-composition with the methodology gate.
    """
    sid = "s_wfpass_mgfail"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_backtest_row(temp_db, sid, pbo=0.30)
    _seed_backtest_trades(temp_db, sid, n=60)
    _seed_shadow_trades(temp_db, sid, n=30)
    _seed_trials_registry(temp_db)
    _seed_walkforward_result(temp_db, sid, "PASS")

    from src.platform.promotion import check_promotion_gate

    # DSR passes via real computation via mocked components
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
        "DA major fix 1: wf-PASS + methodology-FAIL must return False (line 298 AND-compose)"
    )
    # The methodology_gate key must appear in evidence
    assert "methodology_gate" in evidence, (
        "methodology_gate evidence must be present when composed"
    )


# ---------------------------------------------------------------------------
# Test: DA major fix 2 — evidence schema matches _decide function
# ---------------------------------------------------------------------------


def test_methodology_gate_evidence_schema_matches_decide_function(temp_db):
    """DA major fix 2: evidence['methodology_gate'] keys match spec §3.2 EXACTLY.

    Checks:
    - votes are flat {name: bool|None} (NOT {decision, value, threshold})
    - vote names: cpcv, block_bootstrap, mc_perm, psr_dsr, white_rc
    - no 'pbo' in votes
    - no top-level 'tally'
    - per-vote details under details[name]
    - n_pass, n_fail, n_abstentions under details (NOT top-level)
    """
    sid = "s_schema"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_backtest_row(temp_db, sid, pbo=0.30)
    _seed_backtest_trades(temp_db, sid, n=60)
    _seed_shadow_trades(temp_db, sid, n=30)
    _seed_trials_registry(temp_db)

    from src.platform.promotion import _evaluate_strategy_methodology_gate

    # Use the real promotion_gate output shape (mock with spec-matching result)
    real_gate_result = {
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

    with patch(
        "src.methods.promotion_gate.promotion_gate",
        return_value=real_gate_result,
    ), patch(
        "src.platform.promotion._get_n_trials_for_strategy",
        return_value=1,
    ):
        _, evidence = _evaluate_strategy_methodology_gate(sid, temp_db)

    mg = evidence["methodology_gate"]

    # Votes: must be flat {name: bool|None}
    assert "votes" in mg
    votes = mg["votes"]
    expected_vote_names = {"cpcv", "block_bootstrap", "mc_perm", "psr_dsr", "white_rc"}
    assert set(votes.keys()) == expected_vote_names, (
        f"vote keys must be exactly {expected_vote_names}, got {set(votes.keys())}"
    )
    # Each vote value must be bool or None (NOT a nested dict)
    for name, val in votes.items():
        assert val is None or isinstance(val, bool), (
            f"vote '{name}' must be bool|None, got {type(val)}: {val}"
        )

    # No 'pbo' in votes
    assert "pbo" not in votes, "pbo must NOT appear in methodology_gate votes"

    # No top-level 'tally'
    assert "tally" not in mg, "no top-level 'tally' key allowed in methodology_gate"

    # details must exist and contain per-vote info and counters
    assert "details" in mg
    det = mg["details"]
    for method_name in expected_vote_names:
        assert method_name in det, f"details must contain '{method_name}'"
        entry = det[method_name]
        assert "value" in entry, f"details['{method_name}'] must have 'value'"
        assert "threshold" in entry, f"details['{method_name}'] must have 'threshold'"

    # n_pass / n_fail / n_abstentions under details, NOT top-level
    for counter in ("n_pass", "n_fail", "n_abstentions"):
        assert counter in det, f"'{counter}' must be in details"
        assert counter not in mg or mg[counter] == det[counter], (
            f"'{counter}' must live under details, not duplicated at top-level"
        )


# ---------------------------------------------------------------------------
# Test: DA major fix 4 — walkforward_status populated for all four states
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state,expected_status", [
    ("PASS", "pass"),
    ("FAIL", "fail"),
    ("INCONCLUSIVE", "inconclusive"),
])
def test_walkforward_status_populated_for_all_four_states(
    state, expected_status, temp_db,
):
    """walkforward_status has the correct lowercase value for each outcome state."""
    sid = f"s_wfstatus_{state.lower()}"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_walkforward_result(temp_db, sid, state)

    from src.platform.promotion import _evaluate_walkforward_gate

    evidence: dict = {}
    _evaluate_walkforward_gate(sid, temp_db, evidence)

    assert "walkforward_status" in evidence, (
        "walkforward_status must be set by _evaluate_walkforward_gate"
    )
    assert evidence["walkforward_status"] == expected_status, (
        f"expected walkforward_status='{expected_status}', got '{evidence['walkforward_status']}'"
    )


def test_walkforward_status_no_data_yet_when_table_empty(temp_db):
    """walkforward_status='no_data_yet' when no walkforward_results row exists."""
    sid = "s_wf_nodata"
    _register_strategy(temp_db, sid, status="backtested")

    from src.platform.promotion import _evaluate_walkforward_gate

    evidence: dict = {}
    _evaluate_walkforward_gate(sid, temp_db, evidence)

    assert evidence.get("walkforward_status") == "no_data_yet", (
        "walkforward_status must be 'no_data_yet' when no walkforward_results row"
    )


# ---------------------------------------------------------------------------
# Test: DA major fix 4 — walkforward_outcome_state still populated (backwards-compat)
# ---------------------------------------------------------------------------


def test_walkforward_outcome_state_still_populated_for_backwards_compat(temp_db):
    """walkforward_outcome_state must STILL be set alongside walkforward_status."""
    sid = "s_wf_compat"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_walkforward_result(temp_db, sid, "PASS")

    from src.platform.promotion import _evaluate_walkforward_gate

    evidence: dict = {}
    _evaluate_walkforward_gate(sid, temp_db, evidence)

    # Both keys must be present
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
# Test: DA major fix 5 — production gate methodology compose with DSR only
# ---------------------------------------------------------------------------


def test_production_gate_methodology_compose_with_dsr_only(temp_db):
    """DA major fix 5: production gate AND-composes methodology with DSR only.

    - passing DSR + failing methodology -> overall False
    - pbo=None and oos_efficiency=None (Sprint-4 placeholders preserved)
    """
    sid = "s_prod_mg"
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
        "DA major fix 5: passing DSR + failing methodology -> overall False for production target"
    )
    # Sprint-4 placeholders must be preserved
    assert evidence.get("pbo") is None, "pbo must remain None (Sprint-4 placeholder)"
    assert evidence.get("oos_efficiency") is None, (
        "oos_efficiency must remain None (Sprint-4 placeholder)"
    )
    # methodology_gate must appear in evidence
    assert "methodology_gate" in evidence


# ---------------------------------------------------------------------------
# Test: gate_proposal row has from_status == to_status (Major 4)
# ---------------------------------------------------------------------------


def test_gate_proposal_row_has_from_status_eq_to_status(temp_db):
    """Daily gate writes gate_proposal rows with from_status==to_status."""
    sid = "s_proposal"
    _register_strategy(temp_db, sid, status="backtested")
    _seed_backtest_row(temp_db, sid, pbo=0.30)
    _seed_shadow_trades(temp_db, sid, n=20)
    _seed_trials_registry(temp_db)

    from src.platform.promotion import run_daily_gate_for_all_active_strategies

    with patch(
        "src.platform.promotion._evaluate_strategy_methodology_gate",
        return_value=(False, {"decision": "reject", "instrumentation_excluded_count": 0,
                              "existing_gates": {}, "composed_pass": False,
                              "threshold_used": "4_of_5",
                              "override_by": None, "override_reason": None}),
    ):
        run_daily_gate_for_all_active_strategies(temp_db)

    conn = sqlite3.connect(temp_db)
    row = conn.execute(
        """SELECT from_status, to_status, triggered_by, justification_note
           FROM strategy_promotion_events WHERE strategy_id=?""",
        (sid,),
    ).fetchone()
    conn.close()

    assert row is not None, "A gate_proposal event should have been written"
    from_s, to_s, triggered_by, just_note = row
    assert triggered_by == "gate_proposal", (
        f"triggered_by must be 'gate_proposal', got '{triggered_by}'"
    )
    assert from_s == to_s, (
        f"from_status ({from_s!r}) must equal to_status ({to_s!r}) for gate_proposal rows"
    )
    assert just_note is None, "justification_note must be NULL for gate_proposal rows"


# ---------------------------------------------------------------------------
# Test: run_daily iterates active strategies only
# ---------------------------------------------------------------------------


def test_run_daily_iterates_active_strategies_only(temp_db):
    """run_daily_gate_for_all_active_strategies only processes shadow_trading+backtested."""
    # Register: 1 backtested, 1 shadow_trading, 1 proposed (must be skipped), 1 production
    _register_strategy(temp_db, "s_bt", status="backtested")
    _register_strategy(temp_db, "s_sh", status="shadow_trading")
    _register_strategy(temp_db, "s_pr", status="proposed")
    _register_strategy(temp_db, "s_pd", status="production")

    from src.platform.promotion import run_daily_gate_for_all_active_strategies

    called_for = []

    def fake_evaluate(sid, db_path):
        called_for.append(sid)
        return (False, {"decision": "reject", "instrumentation_excluded_count": 0,
                        "existing_gates": {}, "composed_pass": False,
                        "threshold_used": "4_of_5",
                        "override_by": None, "override_reason": None})

    with patch(
        "src.platform.promotion._evaluate_strategy_methodology_gate",
        side_effect=fake_evaluate,
    ):
        run_daily_gate_for_all_active_strategies(temp_db)

    assert set(called_for) == {"s_bt", "s_sh"}, (
        f"Only shadow_trading and backtested should be processed; got {called_for}"
    )
    assert "s_pr" not in called_for, "proposed strategy must not be processed"
    assert "s_pd" not in called_for, "production strategy must not be processed"
