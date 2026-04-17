"""Tests for src.platform.promotion — state machine + gates.

Non-negotiable gates:
  - test_promote_shadow_trading_requires_justification_note
  - test_demote_requires_reason_at_least_20_chars
"""
import pytest

from src.platform.promotion import (
    GATE_DEMOTION_REASON_MIN_CHARS,
    GATE_JUSTIFICATION_MIN_CHARS,
    STATUSES,
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


def _seed_backtest_row(db: str, sid: str, dsr: float | None = None) -> None:
    """Seed a backtest_results row so check_promotion_gate finds something."""
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """INSERT INTO backtest_results
               (result_id, strategy_id, spec_version, spec_hash,
                start_date, end_date, initial_capital, total_trades,
                total_return_pct, sharpe, excess_sharpe, deflated_sharpe,
                sortino, calmar, max_drawdown_pct, win_rate,
                profit_factor, code_git_sha, created_at)
               VALUES (?, ?, 1, ?, '2020-01-01', '2024-12-31', 100000.0,
                       50, 0.3, 1.5, 1.0, ?, 1.8, 2.0, 0.1, 0.6, 2.5,
                       'sha', '2024-01-01T00:00:00+00:00')""",
            (f"r_{sid}", sid, "abc123", dsr),
        )
        conn.commit()
    finally:
        conn.close()


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
    _seed_strategy(temp_db)
    _seed_backtest_row(temp_db, "s1", dsr=0.96)
    passes, ev = check_promotion_gate("s1", "shadow_trading", db_path=temp_db)
    assert passes
    assert ev["dsr"] == 0.96


def test_check_gate_shadow_trading_fails_on_low_dsr(temp_db):
    _seed_strategy(temp_db)
    _seed_backtest_row(temp_db, "s1", dsr=0.80)
    passes, ev = check_promotion_gate("s1", "shadow_trading", db_path=temp_db)
    assert not passes
    assert ev["dsr"] == 0.80
    assert ev["passes_dsr_min"] is False


def test_promote_shadow_trading_requires_justification_note(temp_db):
    _seed_strategy(temp_db)
    _seed_backtest_row(temp_db, "s1", dsr=0.97)
    with pytest.raises(ValueError, match="justification_note"):
        promote("s1", "shadow_trading", triggered_by="manual",
                justification_note=None, db_path=temp_db)
    with pytest.raises(ValueError, match="justification_note"):
        promote("s1", "shadow_trading", triggered_by="manual",
                justification_note="too short", db_path=temp_db)


def test_promote_shadow_trading_succeeds_with_long_justification(temp_db):
    _seed_strategy(temp_db)
    _seed_backtest_row(temp_db, "s1", dsr=0.97)
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
    _seed_backtest_row(temp_db, "s1", dsr=0.96)
    promote("s1", "backtested", triggered_by="auto_gate", db_path=temp_db)
    note = "x" * 45
    promote("s1", "shadow_trading", triggered_by="manual",
            justification_note=note, db_path=temp_db)
    pause("s1", db_path=temp_db)
    assert get_strategies_by_status(["backtested"], db_path=temp_db) == ["s1"]


def test_get_strategies_by_status_empty_list_returns_empty(temp_db):
    assert get_strategies_by_status([], db_path=temp_db) == []


def test_promotion_event_logged(temp_db):
    """Every promote/demote writes a row to strategy_promotion_events."""
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
