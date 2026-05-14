"""Tests for src.platform.promotion — state machine + gates.

Non-negotiable gates:
  - test_promote_shadow_trading_requires_justification_note
  - test_demote_requires_reason_at_least_20_chars
"""
import json
import pytest
from unittest.mock import patch

from src.platform.promotion import (
    GATE_DEMOTION_REASON_MIN_CHARS,
    GATE_DSR_MIN,
    GATE_JUSTIFICATION_MIN_CHARS,
    GATE_OOS_EFFICIENCY_MIN,
    GATE_PBO_MAX,
    STATUSES,
    _evaluate_walkforward_gate,
    check_promotion_gate,
    demote,
    get_strategies_by_status,
    pause,
    promote,
    register_strategy,
)


@pytest.fixture
def temp_db(tmp_path):
    db = str(tmp_path / "test.db")
    from src.schema.sqlite import create_all_tables
    create_all_tables(db)
    return db


def _seed_strategy(db: str, sid: str = "s1") -> None:
    register_strategy(
        strategy_id=sid, display_name=sid.upper(),
        spec_source=f"yaml:specs/{sid}.yaml",
        spec_hash="abc123", db_path=db,
    )


def _seed_backtest_row(
    db: str,
    sid: str,
    dsr: float | None = None,
    pbo: float | None = None,
    oos_efficiency: float | None = None,
) -> None:
    """Seed a backtest_results row so check_promotion_gate finds something.

    `dsr` is stored in deflated_sharpe for legacy use but the gate now
    recomputes DSR from backtest_trades rows — see _seed_backtest_trades.
    `pbo` and `oos_efficiency` default to None (gate fails if NULL).
    """
    import sqlite3
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
               VALUES (?, ?, 1, ?, '2020-01-01', '2024-12-31', 100000.0,
                       50, 0.3, 1.5, 1.0, ?, ?, ?, 1.8, 2.0, 0.1, 0.6, 2.5,
                       'sha', '2024-01-01T00:00:00+00:00')""",
            (f"r_{sid}", sid, "abc123", dsr, pbo, oos_efficiency),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_backtest_trades(
    db: str, sid: str,
    pnl_values: list[float] | None = None,
    n: int | None = None,
) -> None:
    """Seed backtest_trades rows tied to the result_id seeded by _seed_backtest_row.

    `pnl_values` defaults to a 60-trade series with positive mean so
    the recomputed DSR passes the 0.95 gate. Pass `n` to seed n trades
    using the default positive-skewed unit value (convenience for new tests).
    """
    import sqlite3
    if pnl_values is None:
        if n is not None:
            # Repeat a single positive return value n times
            pnl_values = [0.01] * n
        else:
            # Positive-skewed series: DSR will comfortably exceed 0.95
            pnl_values = [0.01, 0.012, 0.015, 0.008, 0.009] * 12
    result_id = f"r_{sid}"
    conn = sqlite3.connect(db)
    try:
        for i, pnl in enumerate(pnl_values):
            conn.execute(
                """INSERT INTO backtest_trades
                   (trade_id, result_id, ticker, entry_date, exit_date,
                    entry_price, exit_price, shares, pnl_dollars, pnl_pct,
                    exit_reason, hold_days, spy_return_over_hold, excess_return,
                    realized_sector, regime_at_entry)
                   VALUES (?, ?, 'AAPL', '2024-01-01', '2024-01-10',
                           100.0, 101.0, 10, 10.0, ?, 'win', 5,
                           0.005, 0.005, 'Tech', 'bull')""",
                (f"t_{sid}_{i}", result_id, float(pnl)),
            )
        conn.commit()
    finally:
        conn.close()


def _seed_trials(db: str, n: int = 25) -> None:
    """Seed n trials so get_variance_for_strategy_family returns empirical V."""
    from src.platform.rigor.trials import record_trial
    for i in range(n):
        record_trial(
            f"strat_{i}", f"hash_{i}",
            sr_raw=0.1 + 0.01 * i,
            db_path=db,
        )


def test_statuses_set_is_locked():
    assert STATUSES == {
        "proposed", "backtested", "shadow_trading",
        "production", "deprecated",
    }


def test_check_gate_backtested_is_automatic(temp_db):
    _seed_strategy(temp_db)
    passes, ev = check_promotion_gate("s1", "backtested", db_path=temp_db)
    assert passes
    assert ev["auto"] is True


def test_check_gate_deprecated_is_automatic(temp_db):
    _seed_strategy(temp_db)
    passes, ev = check_promotion_gate("s1", "deprecated", db_path=temp_db)
    assert passes


def test_check_gate_unknown_target_raises(temp_db):
    _seed_strategy(temp_db)
    with pytest.raises(ValueError):
        check_promotion_gate("s1", "nonsense", db_path=temp_db)


def test_check_gate_shadow_trading_requires_dsr(temp_db):
    """No backtest row → gate fails with 'no backtest_results row'."""
    _seed_strategy(temp_db)
    passes, ev = check_promotion_gate("s1", "shadow_trading", db_path=temp_db)
    assert not passes
    assert "error" in ev


def test_check_gate_shadow_trading_passes_on_dsr_above_threshold(temp_db):
    """Gate passes when recomputed DSR from trade returns exceeds 0.95
    and pbo + oos_efficiency are within thresholds."""
    _seed_strategy(temp_db)
    _seed_backtest_row(temp_db, "s1", dsr=0.96, pbo=0.3, oos_efficiency=0.5)
    _seed_backtest_trades(temp_db, "s1")  # positive-skewed returns → DSR >= 0.95
    _seed_trials(temp_db, n=25)
    passes, ev = check_promotion_gate("s1", "shadow_trading", db_path=temp_db)
    assert passes
    assert ev["dsr"] >= GATE_DSR_MIN
    assert ev["passes_dsr_min"] is True
    assert "trials_sr_variance_used" in ev
    assert ev["trials_sr_variance_used"] is not None


def test_check_gate_shadow_trading_fails_on_low_dsr(temp_db):
    """Gate fails when recomputed DSR from (losing) trade returns is < 0.95."""
    _seed_strategy(temp_db)
    _seed_backtest_row(temp_db, "s1", dsr=0.80)
    # Negative-mean series → DSR will be very low
    _seed_backtest_trades(temp_db, "s1", pnl_values=[-0.02, -0.01, -0.015] * 20)
    _seed_trials(temp_db, n=25)
    passes, ev = check_promotion_gate("s1", "shadow_trading", db_path=temp_db)
    assert not passes
    assert ev["dsr"] < GATE_DSR_MIN
    assert ev["passes_dsr_min"] is False


def test_promote_shadow_trading_requires_justification_note(temp_db):
    _seed_strategy(temp_db)
    _seed_backtest_row(temp_db, "s1", dsr=0.97)
    # Justification check fires before gate evaluation — no trades/trials needed.
    with pytest.raises(ValueError, match="justification_note"):
        promote("s1", "shadow_trading", triggered_by="manual",
                justification_note=None, db_path=temp_db)
    with pytest.raises(ValueError, match="justification_note"):
        promote("s1", "shadow_trading", triggered_by="manual",
                justification_note="too short", db_path=temp_db)


def test_promote_shadow_trading_succeeds_with_long_justification(temp_db):
    _seed_strategy(temp_db)
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=0.3, oos_efficiency=0.5)
    _seed_backtest_trades(temp_db, "s1")  # gate recomputes DSR from trades
    _seed_trials(temp_db, n=25)           # gate uses real V from trials
    # 40 chars exactly
    note = "x" * GATE_JUSTIFICATION_MIN_CHARS
    promote("s1", "shadow_trading", triggered_by="manual",
            justification_note=note, db_path=temp_db)
    # Status updated
    assert get_strategies_by_status(["shadow_trading"], db_path=temp_db) == ["s1"]


def test_promote_auto_gate_does_not_require_justification(temp_db):
    _seed_strategy(temp_db)
    _seed_backtest_row(temp_db, "s1", dsr=0.97)
    promote("s1", "backtested", triggered_by="auto_gate",
            justification_note=None, db_path=temp_db)
    assert get_strategies_by_status(["backtested"], db_path=temp_db) == ["s1"]


def test_demote_requires_reason_at_least_20_chars(temp_db):
    _seed_strategy(temp_db)
    with pytest.raises(ValueError, match="reason"):
        demote("s1", reason="short", db_path=temp_db)
    with pytest.raises(ValueError, match="reason"):
        demote("s1", reason=None, db_path=temp_db)


def test_demote_succeeds_with_valid_reason(temp_db):
    _seed_strategy(temp_db)
    demote("s1", reason="x" * GATE_DEMOTION_REASON_MIN_CHARS, db_path=temp_db)
    assert get_strategies_by_status(["deprecated"], db_path=temp_db) == ["s1"]


def test_pause_moves_to_backtested_and_no_close(temp_db):
    _seed_strategy(temp_db)
    _seed_backtest_row(temp_db, "s1", dsr=0.96, pbo=0.3, oos_efficiency=0.5)
    _seed_backtest_trades(temp_db, "s1")  # gate recomputes DSR from trades
    _seed_trials(temp_db, n=25)           # gate uses real V from trials
    promote("s1", "backtested", triggered_by="auto_gate", db_path=temp_db)
    note = "x" * 45
    promote("s1", "shadow_trading", triggered_by="manual",
            justification_note=note, db_path=temp_db)
    pause("s1", db_path=temp_db)
    assert get_strategies_by_status(["backtested"], db_path=temp_db) == ["s1"]


def test_get_strategies_by_status_empty_list_returns_empty(temp_db):
    assert get_strategies_by_status([], db_path=temp_db) == []


def test_promotion_event_logged(temp_db):
    """Every promote/demote writes a row to strategy_promotion_events.
    backtested is auto — no trades/trials needed."""
    import sqlite3
    _seed_strategy(temp_db)
    _seed_backtest_row(temp_db, "s1", dsr=0.97)
    promote("s1", "backtested", triggered_by="auto_gate", db_path=temp_db)
    conn = sqlite3.connect(temp_db)
    count = conn.execute(
        "SELECT COUNT(*) FROM strategy_promotion_events WHERE strategy_id='s1'"
    ).fetchone()[0]
    conn.close()
    assert count == 1


def test_promotion_gate_uses_real_trials_sr_variance(temp_db):
    """Carryover non-negotiable gate: check_promotion_gate must pass a
    real trials_sr_variance from trials_registry into deflated_sharpe_ratio;
    the null fallback warning in dsr.py must not fire."""
    import warnings
    from src.platform.rigor.trials import record_trial

    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97)
    # Seed backtest_trades rows so the gate has a return series
    import sqlite3
    conn = sqlite3.connect(temp_db)
    for i, pnl in enumerate([0.01, -0.005, 0.015, 0.008, -0.003] * 12):
        conn.execute(
            """INSERT INTO backtest_trades
               (trade_id, result_id, ticker, entry_date, exit_date,
                entry_price, exit_price, shares, pnl_dollars, pnl_pct,
                exit_reason, hold_days, spy_return_over_hold, excess_return,
                realized_sector, regime_at_entry)
               VALUES (?, ?, 'AAPL', '2024-01-01', '2024-01-10',
                       100.0, 101.0, 10, 10.0, ?, 'win', 5,
                       0.005, 0.005, 'Tech', 'bull')""",
            (f"t_{i}", "r_s1", float(pnl)),
        )
    conn.commit()
    conn.close()
    # Seed >= 20 trials so get_variance returns empirical, not fallback.
    # Close conn first to avoid "database is locked" on Windows.
    for i in range(25):
        record_trial(f"strat_{i}", f"hash_{i}", sr_raw=0.1 + 0.01 * i,
                     db_path=temp_db)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        passes, evidence = check_promotion_gate(
            "s1", "shadow_trading", db_path=temp_db,
        )

    # No null-fallback warning fired
    null_fallback_warnings = [
        x for x in w if "trials_sr_variance missing" in str(x.message)
    ]
    assert not null_fallback_warnings, \
        f"null fallback fired — should never happen in production: {null_fallback_warnings}"

    # Evidence carries the real variance
    assert "trials_sr_variance_used" in evidence
    assert evidence["trials_sr_variance_used"] is not None
    assert evidence["n_eff_used_for_dsr"] >= 25


def test_promotion_gate_raises_if_variance_is_none(temp_db, monkeypatch):
    """Defense-in-depth: if get_variance_for_strategy_family somehow
    returns None (it shouldn't), check_promotion_gate must raise rather
    than silently falling back."""
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97)
    import sqlite3
    conn = sqlite3.connect(temp_db)
    for i in range(50):
        conn.execute(
            """INSERT INTO backtest_trades
               (trade_id, result_id, ticker, entry_date, exit_date,
                entry_price, exit_price, shares, pnl_dollars, pnl_pct,
                exit_reason, hold_days, spy_return_over_hold, excess_return,
                realized_sector, regime_at_entry)
               VALUES (?, ?, 'AAPL', '2024-01-01', '2024-01-10',
                       100.0, 101.0, 10, 10.0, 0.01, 'win', 5,
                       0.005, 0.005, 'Tech', 'bull')""",
            (f"t_{i}", "r_s1"),
        )
    conn.commit()
    conn.close()

    # Force get_variance to return None
    import src.platform.rigor.trials as trials_mod
    monkeypatch.setattr(
        trials_mod, "get_variance_for_strategy_family",
        lambda **kwargs: None,
    )
    import pytest
    with pytest.raises(RuntimeError, match="trials_sr_variance"):
        check_promotion_gate("s1", "shadow_trading", db_path=temp_db)


# ---------------------------------------------------------------------------
# New tests — PBO + OOS_efficiency gate (#475)
# ---------------------------------------------------------------------------

def test_promotion_gate_requires_pbo_not_null(temp_db):
    """PBO NULL → shadow_trading gate fails with clear message."""
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=None, oos_efficiency=0.5)
    _seed_backtest_trades(temp_db, "s1", n=50)
    _seed_trials(temp_db, n=25)
    passes, evidence = check_promotion_gate("s1", "shadow_trading", db_path=temp_db)
    assert not passes
    assert "pbo" in evidence["error"].lower() or evidence["pbo"] is None


def test_promotion_gate_requires_oos_efficiency_not_null(temp_db):
    """OOS_efficiency NULL → gate fails."""
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=0.3, oos_efficiency=None)
    _seed_backtest_trades(temp_db, "s1", n=50)
    _seed_trials(temp_db, n=25)
    passes, evidence = check_promotion_gate("s1", "shadow_trading", db_path=temp_db)
    assert not passes
    assert "walk-forward" in evidence["error"].lower() or \
           "oos" in evidence["error"].lower() or \
           evidence["oos_efficiency"] is None


def test_walkforward_gate_disabled_bypasses_check(temp_db, monkeypatch):
    """WALKFORWARD_GATE_ENABLED=false → short-circuits, returns (None, evidence)
    with walkforward_status='disabled'; _fetch_latest_walkforward_outcome not called."""
    monkeypatch.setenv("WALKFORWARD_GATE_ENABLED", "false")
    with patch("src.platform.promotion._fetch_latest_walkforward_outcome") as mock_fetch:
        result, ev = _evaluate_walkforward_gate("s1", temp_db, {})
    mock_fetch.assert_not_called()
    assert result is None
    assert ev["walkforward_status"] == "disabled"


def test_walkforward_gate_enabled_by_default(temp_db, monkeypatch):
    """No env override → gate runs (default true); fetch is called."""
    monkeypatch.delenv("WALKFORWARD_GATE_ENABLED", raising=False)
    with patch("src.platform.promotion._fetch_latest_walkforward_outcome",
               return_value=None) as mock_fetch:
        result, ev = _evaluate_walkforward_gate("s1", temp_db, {})
    mock_fetch.assert_called_once_with("s1", temp_db)
    assert result is None
    assert ev.get("walkforward_status") == "no_data_yet"


def test_walkforward_gate_enabled_true_explicit(temp_db, monkeypatch):
    """WALKFORWARD_GATE_ENABLED=true → gate runs normally; fetch is called."""
    monkeypatch.setenv("WALKFORWARD_GATE_ENABLED", "true")
    with patch("src.platform.promotion._fetch_latest_walkforward_outcome",
               return_value=None) as mock_fetch:
        result, ev = _evaluate_walkforward_gate("s1", temp_db, {})
    mock_fetch.assert_called_once_with("s1", temp_db)
    assert result is None
    assert ev.get("walkforward_status") == "no_data_yet"


def test_promotion_gate_rejects_pbo_over_threshold(temp_db):
    """PBO = 0.60 > 0.50 → gate fails."""
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=0.60, oos_efficiency=0.5)
    _seed_backtest_trades(temp_db, "s1", n=50)
    _seed_trials(temp_db, n=25)
    passes, evidence = check_promotion_gate("s1", "shadow_trading", db_path=temp_db)
    assert not passes
    assert evidence["pbo"] == 0.60
    assert evidence["passes_pbo_max"] is False


def test_promotion_gate_rejects_oos_efficiency_under_threshold(temp_db):
    """OOS_efficiency = 0.20 < 0.30 → gate fails."""
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=0.3, oos_efficiency=0.20)
    _seed_backtest_trades(temp_db, "s1", n=50)
    _seed_trials(temp_db, n=25)
    passes, evidence = check_promotion_gate("s1", "shadow_trading", db_path=temp_db)
    assert not passes
    assert evidence["oos_efficiency"] == 0.20
    assert evidence["passes_oos_efficiency_min"] is False


def test_promotion_gate_passes_with_all_three_gates(temp_db):
    """DSR=0.97, PBO=0.3, OOS=0.5 → all three pass → gate passes."""
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=0.30, oos_efficiency=0.5)
    # Use default pnl_values (varied, positive-skewed series) so DSR computes cleanly
    _seed_backtest_trades(temp_db, "s1")
    _seed_trials(temp_db, n=25)
    passes, evidence = check_promotion_gate("s1", "shadow_trading", db_path=temp_db)
    assert passes
    assert evidence["pbo"] == 0.30
    assert evidence["oos_efficiency"] == 0.5


# ---------------------------------------------------------------------------
# T9 — Promotion-gate sentinel guard tests (SP-WF-009)
# ---------------------------------------------------------------------------

def test_evaluate_promotion_gate_wf_disabled_skips_wf(temp_db, monkeypatch):
    """WALKFORWARD_GATE_ENABLED=false → _evaluate_walkforward_gate NOT called;
    gate still produces a verdict via DSR + methodology composition."""
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=0.30, oos_efficiency=0.5)
    _seed_backtest_trades(temp_db, "s1")
    _seed_trials(temp_db, n=25)
    monkeypatch.setenv("WALKFORWARD_GATE_ENABLED", "false")
    with patch("src.platform.promotion._evaluate_walkforward_gate") as mock_wf:
        passes, evidence = check_promotion_gate("s1", "shadow_trading", db_path=temp_db)
    mock_wf.assert_not_called()
    assert isinstance(passes, bool)
    assert evidence["walkforward_gate_enabled"] is False


def test_evaluate_promotion_gate_wf_enabled_calls_wf(temp_db, monkeypatch):
    """WALKFORWARD_GATE_ENABLED=true → _evaluate_walkforward_gate IS called;
    verdict composes all 3 gates."""
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=0.30, oos_efficiency=0.5)
    _seed_backtest_trades(temp_db, "s1")
    _seed_trials(temp_db, n=25)
    monkeypatch.setenv("WALKFORWARD_GATE_ENABLED", "true")
    with patch("src.platform.promotion._evaluate_walkforward_gate",
               return_value=(True, {"walkforward_status": "pass",
                                    "walkforward_outcome_state": "PASS"})) as mock_wf:
        passes, evidence = check_promotion_gate("s1", "shadow_trading", db_path=temp_db)
    mock_wf.assert_called_once()
    assert evidence["walkforward_gate_enabled"] is True


def test_evaluate_promotion_gate_evidence_carries_gate_enabled_flag(
    temp_db, monkeypatch,
):
    """Evidence dict carries walkforward_gate_enabled bool in both sentinel states."""
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=0.30, oos_efficiency=0.5)
    _seed_backtest_trades(temp_db, "s1")
    _seed_trials(temp_db, n=25)

    monkeypatch.setenv("WALKFORWARD_GATE_ENABLED", "true")
    _, ev_on = check_promotion_gate("s1", "shadow_trading", db_path=temp_db)
    assert ev_on["walkforward_gate_enabled"] is True

    monkeypatch.setenv("WALKFORWARD_GATE_ENABLED", "false")
    _, ev_off = check_promotion_gate("s1", "shadow_trading", db_path=temp_db)
    assert ev_off["walkforward_gate_enabled"] is False


# ---------------------------------------------------------------------------
# T14 — Production-gate walkforward composition (SP-WF-014)
# ---------------------------------------------------------------------------

def _seed_walkforward_row(
    db: str,
    sid: str,
    outcome_state: str = "PASS",
    code_git_sha: str = "abc123sha",
    created_at: str | None = None,
) -> None:
    import sqlite3 as _sqlite3
    import uuid
    if created_at is None:
        created_at = "2026-04-15T00:00:00+00:00"
    conn = _sqlite3.connect(db)
    try:
        conn.execute(
            """INSERT INTO walkforward_results
               (run_id, strategy_id, spec_hash, code_git_sha, random_seed,
                outcome_state, reason, pooled_sharpe, pooled_mde,
                heavy_tail_flag, n_windows, n_windows_pass, n_windows_fail,
                n_windows_inconclusive_data, n_windows_inconclusive_power,
                created_at)
               VALUES (?, ?, 'spec1', ?, 42, ?, 'walkforward_pass',
                       1.5, 0.3, 0, 4, 3, 0, 1, 0, ?)""",
            (str(uuid.uuid4()), sid, code_git_sha, outcome_state, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def test_production_gate_passes_with_walkforward_pass(temp_db, monkeypatch):
    """WF PASS + DSR PASS + MG PASS → production gate passes.
    Evidence contains all required walkforward_* keys."""
    monkeypatch.setenv("WALKFORWARD_GATE_ENABLED", "true")
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=0.30, oos_efficiency=0.5)
    _seed_backtest_trades(temp_db, "s1")
    _seed_trials(temp_db, n=25)
    # code_git_sha='sha' matches _seed_backtest_row default; created_at is recent
    _seed_walkforward_row(
        temp_db, "s1", outcome_state="PASS",
        code_git_sha="sha", created_at="2026-05-10T00:00:00+00:00",
    )
    with patch(
        "src.platform.promotion._evaluate_strategy_methodology_gate",
        return_value=(True, {"decision": "promote"}),
    ):
        passes, evidence = check_promotion_gate("s1", "production", db_path=temp_db)
    assert passes is True
    for key in (
        "walkforward_gate_enabled",
        "walkforward_outcome_state",
        "walkforward_status",
        "walkforward_reason",
        "walkforward_run_id",
        "walkforward_pooled_sharpe",
        "walkforward_pooled_mde",
        "walkforward_heavy_tail_flag",
    ):
        assert key in evidence, f"missing evidence key: {key}"
    assert evidence["walkforward_gate_enabled"] is True
    assert evidence["walkforward_outcome_state"] == "PASS"


def test_production_gate_fails_with_walkforward_fail(temp_db, monkeypatch):
    """WF FAIL → production gate returns False even when DSR + MG pass."""
    monkeypatch.setenv("WALKFORWARD_GATE_ENABLED", "true")
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=0.30, oos_efficiency=0.5)
    _seed_backtest_trades(temp_db, "s1")
    _seed_trials(temp_db, n=25)
    _seed_walkforward_row(temp_db, "s1", outcome_state="FAIL")
    with patch(
        "src.platform.promotion._evaluate_strategy_methodology_gate",
        return_value=(True, {"decision": "promote"}),
    ):
        passes, evidence = check_promotion_gate("s1", "production", db_path=temp_db)
    assert passes is False
    assert evidence.get("walkforward_outcome_state") == "FAIL"


def test_production_gate_fails_with_walkforward_inconclusive(temp_db, monkeypatch):
    """WF INCONCLUSIVE → production gate returns False (never collapse three-state)."""
    monkeypatch.setenv("WALKFORWARD_GATE_ENABLED", "true")
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=0.30, oos_efficiency=0.5)
    _seed_backtest_trades(temp_db, "s1")
    _seed_trials(temp_db, n=25)
    _seed_walkforward_row(temp_db, "s1", outcome_state="INCONCLUSIVE")
    with patch(
        "src.platform.promotion._evaluate_strategy_methodology_gate",
        return_value=(True, {"decision": "promote"}),
    ):
        passes, evidence = check_promotion_gate("s1", "production", db_path=temp_db)
    assert passes is False
    assert evidence.get("walkforward_outcome_state") == "INCONCLUSIVE"


def test_production_gate_fails_when_no_walkforward_row(temp_db, monkeypatch):
    """No walkforward_results row → production gate returns False.
    STRICTER than shadow_trading — no legacy fall-through."""
    monkeypatch.setenv("WALKFORWARD_GATE_ENABLED", "true")
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=0.30, oos_efficiency=0.5)
    _seed_backtest_trades(temp_db, "s1")
    _seed_trials(temp_db, n=25)
    # No walkforward row seeded
    with patch(
        "src.platform.promotion._evaluate_strategy_methodology_gate",
        return_value=(True, {"decision": "promote"}),
    ):
        passes, evidence = check_promotion_gate("s1", "production", db_path=temp_db)
    assert passes is False


def test_production_gate_skips_walkforward_when_sentinel_disabled(
    temp_db, monkeypatch,
):
    """WALKFORWARD_GATE_ENABLED=false → bypass active; v0.35.0 composition preserved.
    Evidence has walkforward_gate_enabled=False."""
    monkeypatch.setenv("WALKFORWARD_GATE_ENABLED", "false")
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=0.30, oos_efficiency=0.5)
    _seed_backtest_trades(temp_db, "s1")
    _seed_trials(temp_db, n=25)
    with patch(
        "src.platform.promotion._evaluate_strategy_methodology_gate",
        return_value=(True, {"decision": "promote"}),
    ):
        passes, evidence = check_promotion_gate("s1", "production", db_path=temp_db)
    assert passes is True
    assert evidence["walkforward_gate_enabled"] is False


def test_production_gate_rejects_stale_walkforward_code_git_sha(
    temp_db, monkeypatch,
):
    """DA-1: walkforward_results.code_git_sha != latest backtest code_git_sha
    → passes=False, walkforward_stale=True, reason='code_git_sha mismatch'."""
    monkeypatch.setenv("WALKFORWARD_GATE_ENABLED", "true")
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=0.30, oos_efficiency=0.5)
    _seed_backtest_trades(temp_db, "s1")
    _seed_trials(temp_db, n=25)
    # WF row has OLD_SHA; backtest row has 'sha' (from _seed_backtest_row fixture)
    _seed_walkforward_row(temp_db, "s1", outcome_state="PASS", code_git_sha="OLD_SHA")
    with patch(
        "src.platform.promotion._evaluate_strategy_methodology_gate",
        return_value=(True, {"decision": "promote"}),
    ):
        passes, evidence = check_promotion_gate("s1", "production", db_path=temp_db)
    assert passes is False
    assert evidence.get("walkforward_stale") is True
    assert evidence.get("walkforward_stale_reason") == "code_git_sha mismatch"


def test_production_gate_rejects_walkforward_older_than_30_days(
    temp_db, monkeypatch,
):
    """DA-1: walkforward_results.created_at older than 30 days → staleness block."""
    import sqlite3 as _sqlite3
    monkeypatch.setenv("WALKFORWARD_GATE_ENABLED", "true")
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=0.30, oos_efficiency=0.5)
    _seed_backtest_trades(temp_db, "s1")
    _seed_trials(temp_db, n=25)
    # Seed WF row 31 days ago with matching sha ('sha' matches _seed_backtest_row fixture)
    old_ts = "2026-04-12T00:00:00+00:00"  # > 30 days before 2026-05-13
    _seed_walkforward_row(
        temp_db, "s1", outcome_state="PASS",
        code_git_sha="sha", created_at=old_ts,
    )
    with patch(
        "src.platform.promotion._evaluate_strategy_methodology_gate",
        return_value=(True, {"decision": "promote"}),
    ):
        passes, evidence = check_promotion_gate("s1", "production", db_path=temp_db)
    assert passes is False
    assert evidence.get("walkforward_stale") is True
    assert evidence.get("walkforward_stale_reason") == "older than 30 days"


def test_promote_persists_walkforward_outcome_state_in_gate_result_json(
    temp_db, monkeypatch,
):
    """DA-5: promote() persists walkforward_outcome_state in gate_result_json."""
    import sqlite3 as _sqlite3
    monkeypatch.setenv("WALKFORWARD_GATE_ENABLED", "true")
    _seed_strategy(temp_db, "s1")
    _seed_backtest_row(temp_db, "s1", dsr=0.97, pbo=0.30, oos_efficiency=0.5)
    _seed_backtest_trades(temp_db, "s1")
    _seed_trials(temp_db, n=25)
    _seed_walkforward_row(temp_db, "s1", outcome_state="PASS", code_git_sha="sha")
    with patch(
        "src.platform.promotion._evaluate_strategy_methodology_gate",
        return_value=(True, {"decision": "promote"}),
    ):
        promote(
            "s1", "production",
            triggered_by="auto_gate",
            db_path=temp_db,
        )
    conn = _sqlite3.connect(temp_db)
    row = conn.execute(
        "SELECT gate_result_json FROM strategy_promotion_events "
        "WHERE strategy_id='s1' AND to_status='production'"
    ).fetchone()
    conn.close()
    assert row is not None
    gate_json = json.loads(row[0])
    assert gate_json.get("walkforward_outcome_state") == "PASS"
