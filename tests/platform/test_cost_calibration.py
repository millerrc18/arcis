"""Tests for src.platform.cost_calibration.

Non-negotiable gate: calibrated slippage_bps must be within 30% of the
hardcoded 3 bps default. If wildly off, the calibration is wrong OR
real swing data drifted far from the backtest assumption — investigate
rather than trust.
"""
import random
import sqlite3

import pytest


def _seed_swing_trades(db_path: str, n: int = 85) -> None:
    """Seed N closed swing trades with varied slippage_bps."""
    from src.schema.sqlite import create_all_tables
    create_all_tables(db_path)
    conn = sqlite3.connect(db_path)
    rng = random.Random(42)
    for i in range(n):
        entry_slip = 2.0 + rng.random() * 3.0  # 2-5 bps
        exit_slip = 2.0 + rng.random() * 3.0
        conn.execute(
            """INSERT INTO shadow_trades
               (trade_id, ticker, planned_shares, actual_shares, entry_price,
                actual_entry_price, actual_exit_price, desk,
                actual_entry_time, actual_exit_time,
                entry_slippage_bps, exit_slippage_bps, pnl_pct, created_at,
                updated_at)
               VALUES (?, ?, 10, 10, 100.0, ?, ?,
                       'swing', '2026-04-01', '2026-04-08',
                       ?, ?, 0.02, '2026-04-01', '2026-04-08')""",
            (
                f"t{i}", f"T{i % 20}",
                100.0 + entry_slip / 100,
                102.0 - exit_slip / 100,
                entry_slip, exit_slip,
            ),
        )
    conn.commit()
    conn.close()


def test_cost_calibration_within_30pct_of_default(tmp_path):
    """85 trades with realistic slippage should calibrate within 30%
    of the 3 bps hardcoded assumption."""
    db = str(tmp_path / "test.db")
    _seed_swing_trades(db, n=85)
    from src.platform.cost_calibration import calibrate_from_swing_history
    result = calibrate_from_swing_history(db_path=db)
    entry_bps = result["entry_slippage_bps"]
    exit_bps = result["exit_slippage_bps"]
    # Both should be in [2.1, 3.9] bps (within 30% of 3.0)
    assert 2.1 <= entry_bps <= 3.9, (
        f"calibrated entry_slippage_bps={entry_bps} more than 30% off from "
        f"hardcoded 3 bps; real data may have drifted far from assumption"
    )
    assert 2.1 <= exit_bps <= 3.9
    assert result["n_trades"] == 85
    assert result["source"] == "calibrated"


def test_cost_calibration_handles_empty_db(tmp_path):
    """Empty DB → return default 3 bps + warning."""
    db = str(tmp_path / "test.db")
    from src.schema.sqlite import create_all_tables
    create_all_tables(db)
    from src.platform.cost_calibration import calibrate_from_swing_history
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = calibrate_from_swing_history(db_path=db)
    assert result["entry_slippage_bps"] == 3.0
    assert result["exit_slippage_bps"] == 3.0
    assert result["n_trades"] == 0
    assert result["source"] == "default"
    assert any("no swing trades" in str(x.message).lower() for x in w)


def test_cost_calibration_under_10_trades_uses_default(tmp_path):
    """Sample too small → fallback to defaults with warning."""
    db = str(tmp_path / "test.db")
    _seed_swing_trades(db, n=5)
    from src.platform.cost_calibration import calibrate_from_swing_history
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = calibrate_from_swing_history(db_path=db)
    assert result["source"] == "default"
    assert result["entry_slippage_bps"] == 3.0
    assert result["n_trades"] == 5
    assert any("sample too small" in str(x.message).lower() for x in w)


def test_cost_calibration_uses_median_not_mean(tmp_path):
    """Median is robust to outliers (e.g. one extreme fill)."""
    db = str(tmp_path / "test.db")
    _seed_swing_trades(db, n=85)
    # Inject an outlier with 200 bps slippage
    conn = sqlite3.connect(db)
    conn.execute(
        """INSERT INTO shadow_trades
           (trade_id, ticker, planned_shares, actual_shares, entry_price,
            desk, actual_entry_time, actual_exit_time,
            entry_slippage_bps, exit_slippage_bps, pnl_pct, created_at,
            updated_at)
           VALUES ('outlier', 'OUTL', 1, 1, 100.0,
                   'swing', '2026-04-01', '2026-04-08',
                   200.0, 200.0, 0.0, '2026-04-01', '2026-04-08')""",
    )
    conn.commit()
    conn.close()
    from src.platform.cost_calibration import calibrate_from_swing_history
    result = calibrate_from_swing_history(db_path=db)
    # Median shouldn't move much from the outlier
    assert 2.1 <= result["entry_slippage_bps"] <= 3.9
    assert 2.1 <= result["exit_slippage_bps"] <= 3.9
