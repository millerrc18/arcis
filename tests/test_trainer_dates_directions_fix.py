"""T3 regression tests: trainer.py input-quality fix for promotion_gate call site.

Tests lock the following behaviors:
- _resolve_returns_for_gate returns a 3-tuple (returns, dates, directions)
- Length invariant: len(returns) == len(dates) == len(directions)
- NULL actual_entry_time rows are filtered by the SQL query (not by Python)
- Empty result returns ([], [], [])
- promotion_gate at trainer.py:1039 is called with dates= and directions= kwargs
- rf_placeholder pre-subtraction at lines 975-976 is removed
- directions list is all +1 for the long-only system
- Choice A regression-lock: healthy returns cannot produce decision='promote'
  from run_promotion_gate_for_version (MC-perm p=1.0 degeneracy under long-only)

Sprint 2 T3 — spec §1.3.1, DA major fixes 3, 6.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import uuid
from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

from src.training.versioning import init_training_tables


@pytest.fixture(autouse=True)
def _mock_fred(monkeypatch):
    """Mock FRED rf-rate fetch so tests don't make outbound network calls.

    Per CLAUDE.md "Mock all external APIs in tests" — pytest must never hit
    api.stlouisfed.org. Without this fixture, gate evaluation reaches
    src.methods._rf_vector.compute_per_period_rf_vector which fetches DTB3.
    Returns a constant 0.0001 rf-rate per date with `truncated=False`.
    The trainer test mocks promotion_gate directly so it doesn't always
    trip on a missing FRED key, but adding the fixture defensively per
    QA reviewer flag matches the test-discipline invariant.
    """
    monkeypatch.setattr(
        "src.methods._rf_vector.compute_per_period_rf_vector",
        lambda dates: ([0.0001] * len(dates), False),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    return path


def _insert_version(db_path: str, version_name: str = "test-v1", status: str = "active") -> str:
    init_training_tables(db_path)
    version_id = str(uuid.uuid4())
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO model_versions
               (version_id, version_name, created_at, training_examples_count,
                synthetic_examples_count, outcome_examples_count,
                model_file_path, status)
               VALUES (?, ?, datetime('now'), 10, 0, 0, 'test.gguf', ?)""",
            (version_id, version_name, status),
        )
        conn.commit()
    return version_id


def _seed_shadow_trade(
    db_path: str,
    pnl_pct: float | None,
    actual_entry_time: str | None,
    status: str = "closed",
) -> str:
    """Insert one shadow_trade row. Returns the trade_id."""
    from src.journal.store import initialize_database
    initialize_database(db_path)
    trade_id = str(uuid.uuid4())
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO shadow_trades
               (trade_id, ticker, status, pnl_pct, actual_entry_time, created_at, updated_at)
               VALUES (?, 'AAPL', ?, ?, ?, datetime('now'), datetime('now'))""",
            (trade_id, status, pnl_pct, actual_entry_time),
        )
        conn.commit()
    return trade_id


# ---------------------------------------------------------------------------
# Test: _resolve_returns_for_gate returns 3-tuple
# ---------------------------------------------------------------------------

def test_resolve_returns_for_gate_returns_tuple_shape():
    """_resolve_returns_for_gate must return a 3-tuple (returns, dates, directions)."""
    db = _tmp_db()
    _seed_shadow_trade(db, 2.5, "2024-03-15T10:30:00")

    from src.training.trainer import _resolve_returns_for_gate
    result = _resolve_returns_for_gate(db)
    assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
    assert len(result) == 3, f"Expected 3-tuple, got length {len(result)}"
    returns, dates, directions = result
    assert isinstance(returns, list), f"returns must be list, got {type(returns)}"
    assert isinstance(dates, list), f"dates must be list, got {type(dates)}"
    assert isinstance(directions, list), f"directions must be list, got {type(directions)}"


def test_resolve_returns_for_gate_returns_length_matched_tuple():
    """len(returns) == len(dates) == len(directions) invariant must hold."""
    db = _tmp_db()
    _seed_shadow_trade(db, 1.5, "2024-01-10T09:30:00")
    _seed_shadow_trade(db, 3.0, "2024-02-20T14:00:00")
    _seed_shadow_trade(db, -0.5, "2024-03-05T11:15:00")

    from src.training.trainer import _resolve_returns_for_gate
    returns, dates, directions = _resolve_returns_for_gate(db)
    assert len(returns) == len(dates) == len(directions), (
        f"Length mismatch: returns={len(returns)}, dates={len(dates)}, directions={len(directions)}"
    )
    assert len(returns) == 3


def test_resolve_returns_for_gate_handles_null_entry_times():
    """Rows with NULL actual_entry_time must be filtered by SQL — no TypeError from None[:10]."""
    db = _tmp_db()
    _seed_shadow_trade(db, 2.0, "2024-05-01T09:30:00")  # valid row
    _seed_shadow_trade(db, 1.5, None)                   # NULL entry — must be filtered

    from src.training.trainer import _resolve_returns_for_gate
    returns, dates, directions = _resolve_returns_for_gate(db)
    # Only the valid row with a non-NULL entry should be returned
    assert len(returns) == 1, f"Expected 1 valid row, got {len(returns)}"
    assert len(dates) == 1
    assert len(directions) == 1


def test_resolve_returns_for_gate_returns_empty_when_all_undated():
    """When all rows have NULL actual_entry_time, returns ([], [], [])."""
    db = _tmp_db()
    _seed_shadow_trade(db, 2.0, None)
    _seed_shadow_trade(db, 1.5, None)

    from src.training.trainer import _resolve_returns_for_gate
    result = _resolve_returns_for_gate(db)
    assert result == ([], [], []), f"Expected ([], [], []), got {result!r}"


# ---------------------------------------------------------------------------
# Test: directions encoding
# ---------------------------------------------------------------------------

def test_directions_default_long_for_long_only_system():
    """directions must be all +1 for every trade (long-only system per registry.py:202)."""
    db = _tmp_db()
    _seed_shadow_trade(db, 2.5, "2024-03-15T10:30:00")
    _seed_shadow_trade(db, -1.0, "2024-03-16T10:30:00")
    _seed_shadow_trade(db, 0.5, "2024-03-17T10:30:00")

    from src.training.trainer import _resolve_returns_for_gate
    _, _, directions = _resolve_returns_for_gate(db)
    assert all(d == 1 for d in directions), (
        f"All directions must be +1 for long-only system, got {directions}"
    )


# ---------------------------------------------------------------------------
# Test: rf_placeholder pre-subtraction is gone
# ---------------------------------------------------------------------------

def test_rf_placeholder_subtraction_removed():
    """Raw pnl_pct/100 is returned — no rf_placeholder pre-subtraction."""
    db = _tmp_db()
    pnl_pct = 5.0
    _seed_shadow_trade(db, pnl_pct, "2024-06-01T09:30:00")

    from src.training.trainer import _resolve_returns_for_gate
    returns, _, _ = _resolve_returns_for_gate(db)
    assert len(returns) == 1
    expected_raw = pnl_pct / 100.0
    assert returns[0] == pytest.approx(expected_raw), (
        f"Expected raw return {expected_raw}, got {returns[0]}. "
        "rf_placeholder pre-subtraction must NOT be applied."
    )


# ---------------------------------------------------------------------------
# Test: promotion_gate called with dates and directions kwargs
# ---------------------------------------------------------------------------

def test_promotion_gate_called_with_dates_and_directions():
    """promotion_gate at trainer.py:1039 must receive dates= and directions= kwargs."""
    db = _tmp_db()
    version_id = _insert_version(db)
    entry_time = "2024-04-10T09:30:00"
    _seed_shadow_trade(db, 2.0, entry_time)

    expected_date = date.fromisoformat(entry_time[:10])
    captured_kwargs = {}

    def mock_gate(returns, n_trials, **kwargs):
        captured_kwargs.update(kwargs)
        return {
            "decision": "reject",
            "votes": {},
            "n_obs": len(returns),
            "mintrl": 50,
            "details": {"n_pass": 0, "n_fail": 5, "n_abstentions": 0},
        }

    from src.training.trainer import run_promotion_gate_for_version
    with patch("src.training.trainer.promotion_gate", side_effect=mock_gate):
        run_promotion_gate_for_version(
            version_id=version_id,
            version_name="test-v1",
            db_path=db,
        )

    assert "dates" in captured_kwargs, (
        "promotion_gate was NOT called with dates= kwarg. Bug A is not fixed."
    )
    assert "directions" in captured_kwargs, (
        "promotion_gate was NOT called with directions= kwarg. Bug A is not fixed."
    )
    assert captured_kwargs["dates"] == [expected_date], (
        f"Expected dates=[{expected_date!r}], got {captured_kwargs['dates']!r}"
    )
    assert captured_kwargs["directions"] == [1], (
        f"Expected directions=[1], got {captured_kwargs['directions']!r}"
    )


# ---------------------------------------------------------------------------
# Test: kpis_compute.py:376 fix
# ---------------------------------------------------------------------------

def test_kpi_compute_promotion_gate_passes_dates_and_directions():
    """_compute_promotion_gate_kpi must call promotion_gate with dates= and directions= kwargs."""
    from src.api.cloud_routes.kpis_compute import _compute_promotion_gate_kpi, N_MINIMUM_TRL

    n = N_MINIMUM_TRL + 10
    returns = [0.01] * n
    dates = [date(2024, 1, 1)] * n
    directions = [1] * n

    captured_kwargs = {}

    def mock_gate(returns_arg, n_trials, **kwargs):
        captured_kwargs.update(kwargs)
        return {
            "decision": "reject",
            "votes": {
                "cpcv": False,
                "block_bootstrap": False,
                "mc_perm": False,
                "psr_dsr": False,
                "white_rc": None,
            },
            "n_obs": len(returns_arg),
            "mintrl": 50,
            "details": {"n_pass": 0, "n_fail": 4, "n_abstentions": 1},
        }

    with patch("src.methods.promotion_gate.promotion_gate", mock_gate):
        result = _compute_promotion_gate_kpi(n_trades=n, returns=returns,
                                             dates=dates, directions=directions)

    assert "dates" in captured_kwargs, (
        "promotion_gate in kpis_compute was NOT called with dates= kwarg. Bug C is not fixed."
    )
    assert "directions" in captured_kwargs, (
        "promotion_gate in kpis_compute was NOT called with directions= kwarg. Bug C is not fixed."
    )
    assert captured_kwargs["dates"] == dates
    assert captured_kwargs["directions"] == directions


# ---------------------------------------------------------------------------
# Test: Choice A regression-lock
# ---------------------------------------------------------------------------

def test_trainer_promotion_gate_currently_cannot_promote_long_only():
    """Choice A regression-lock: healthy returns cannot promote via trainer path.

    With directions=[+1]*N, MC permutation always produces p=1.0 (shuffling a
    constant array is identity). This is a hard FAIL vote, so the gate cannot
    reach 4-of-5. Decision must be 'reject' or 'defer', never 'promote'.
    The MC-perm vote evidence must show passed=False and value≈1.0.

    Spec §1.3.1.
    """
    db = _tmp_db()
    version_id = _insert_version(db)

    # Seed healthy positive returns with valid timestamps + non-zero variance.
    # Identical returns produce zero-variance signed returns, which makes
    # rf_adjusted_excess_sharpe undefined and the gate fails before reaching
    # the MC-perm degeneracy step. Varied returns let the gate run end-to-end
    # so we actually exercise Choice A: MC perm shuffle with directions=[+1]*N
    # is identity → p=1.0 → vote fails → decision != promote.
    for i in range(60):
        pnl = 3.0 + (i % 5 - 2) * 0.3  # cycles 2.4, 2.7, 3.0, 3.3, 3.6
        _seed_shadow_trade(db, pnl, f"2024-01-{(i % 28) + 1:02d}T09:30:00")

    from src.training.trainer import run_promotion_gate_for_version
    result = run_promotion_gate_for_version(
        version_id=version_id,
        version_name="test-v1",
        db_path=db,
        n_trials=1,
    )

    decision = result.get("decision")
    assert decision in {"reject", "defer"}, (
        f"Choice A violation: long-only system must not promote via trainer path, "
        f"got decision={decision!r}. This locks the documented degeneracy in spec §1.3.1."
    )

    gate_result = result.get("gate_result", {})
    votes = gate_result.get("votes", {})
    details = gate_result.get("details", {})

    mc_perm_vote_passed = votes.get("mc_perm")
    assert mc_perm_vote_passed is False, (
        f"MC-perm must FAIL (passed=False) under long-only directions, "
        f"got mc_perm.passed={mc_perm_vote_passed!r}"
    )

    mc_perm_value = details.get("mc_perm", {}).get("value")
    if mc_perm_value is not None:
        assert mc_perm_value == pytest.approx(1.0, abs=1e-6), (
            f"MC-perm p-value must be ≈1.0 under constant directions, got {mc_perm_value}"
        )
