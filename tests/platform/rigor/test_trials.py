"""Tests for src.platform.rigor.trials — N_eff counter + variance estimator."""
import sqlite3

import pytest

from src.platform.rigor.trials import (
    get_current_n_eff,
    get_variance_for_strategy_family,
    record_trial,
    _VARIANCE_FALLBACK,
)


def _bootstrap_schema(db_path: str) -> None:
    """Load the schema into a fresh DB for tests."""
    from src.schema.sqlite import create_all_tables
    create_all_tables(db_path)


@pytest.fixture
def temp_db(tmp_path):
    db = tmp_path / "test.db"
    _bootstrap_schema(str(db))
    return str(db)


def test_get_current_n_eff_empty_returns_zero(temp_db):
    assert get_current_n_eff(temp_db) == 0


def test_record_trial_increments_n_eff(temp_db):
    record_trial("strat_A", "hash1", sr_raw=0.5, db_path=temp_db)
    assert get_current_n_eff(temp_db) == 1
    record_trial("strat_B", "hash2", sr_raw=0.3, db_path=temp_db)
    assert get_current_n_eff(temp_db) == 2


def test_trials_registry_increments_on_each_backtest(temp_db):
    """Non-negotiable gate per Bailey-López de Prado False Strategy theorem:
    30 strategies × 10 param grid points = 300 trials, not 30."""
    for strat in range(30):
        for grid in range(10):
            record_trial(
                f"strat_{strat}", f"hash_{strat}_{grid}",
                sr_raw=0.01 * (strat + grid),
                db_path=temp_db,
            )
    assert get_current_n_eff(temp_db) == 300


def test_get_variance_under_20_trials_returns_fallback(temp_db):
    """<20 trials → documented fallback + warning."""
    for i in range(5):
        record_trial(f"s{i}", f"h{i}", sr_raw=0.5, db_path=temp_db)
    with pytest.warns(RuntimeWarning):
        v = get_variance_for_strategy_family(db_path=temp_db)
    assert v == _VARIANCE_FALLBACK


def test_get_variance_with_20plus_trials_returns_empirical(temp_db):
    """>=20 trials with varying SR → empirical variance (not fallback)."""
    import numpy as np
    rng = np.random.default_rng(0)
    sr_values = rng.normal(0.1, 0.05, size=25).tolist()
    for i, sr in enumerate(sr_values):
        record_trial(f"s{i}", f"h{i}", sr_raw=sr, db_path=temp_db)
    v = get_variance_for_strategy_family(db_path=temp_db)
    expected = float(np.var(sr_values, ddof=1))
    assert abs(v - expected) < 1e-9
    assert v != _VARIANCE_FALLBACK  # empirical, not fallback


def test_record_trial_returns_valid_uuid(temp_db):
    import uuid
    tid = record_trial("s1", "h1", sr_raw=0.2, db_path=temp_db)
    # Should parse as UUID
    uuid.UUID(tid)
