"""Tests for purge + embargo (R2)."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.platform.rigor.walkforward_purging import (
    _add_trading_days,
    classify_trades_for_audit,
    embargo_oos_trades,
    purge_is_trades,
)


@dataclass
class FakeTrade:
    entry_date: str
    exit_date: str | None


def test_purge_removes_entry_in_is_exit_in_oos():
    trades = [FakeTrade("2019-12-20", "2020-01-10")]
    kept = purge_is_trades(trades, "2020-01-01", "2020-06-30")
    assert kept == []


def test_purge_removes_entry_in_is_exit_in_is_but_straddling_boundary():
    """Entry + exit both BEFORE oos_start — should be kept."""
    trades = [FakeTrade("2019-11-01", "2019-12-15")]
    kept = purge_is_trades(trades, "2020-01-01", "2020-06-30")
    assert len(kept) == 1


def test_purge_keeps_trade_entirely_after_oos():
    """Entry after oos_end — kept (it's logically impossible IS, but the
    interval check should still tolerate it cleanly)."""
    trades = [FakeTrade("2021-01-01", "2021-02-01")]
    kept = purge_is_trades(trades, "2020-01-01", "2020-06-30")
    assert len(kept) == 1


def test_purge_handles_no_exit_date():
    """Open trade with entry inside IS and no exit is purged (conservative)."""
    trades = [FakeTrade("2019-11-01", None)]
    kept = purge_is_trades(trades, "2020-01-01", "2020-06-30")
    assert kept == []


def test_purge_rejects_inverted_oos_range():
    trades = [FakeTrade("2020-01-01", "2020-02-01")]
    with pytest.raises(ValueError, match="oos_end"):
        purge_is_trades(trades, "2020-06-30", "2020-01-01")


def test_embargo_removes_trades_in_first_5_trading_days():
    """Wednesday 2020-01-01 + 5 trading days = Wednesday 2020-01-08."""
    trades = [
        FakeTrade("2020-01-02", "2020-01-10"),  # day 1 — removed
        FakeTrade("2020-01-07", "2020-01-14"),  # day 4 — removed
        FakeTrade("2020-01-09", "2020-01-16"),  # day 6 — kept
    ]
    kept = embargo_oos_trades(trades, "2020-01-01", "2020-06-30", embargo_days=5)
    assert len(kept) == 1
    assert kept[0].entry_date == "2020-01-09"


def test_embargo_zero_days_is_passthrough():
    trades = [
        FakeTrade("2020-01-02", "2020-01-10"),
        FakeTrade("2020-01-03", "2020-01-11"),
    ]
    kept = embargo_oos_trades(trades, "2020-01-01", "2020-06-30", embargo_days=0)
    assert len(kept) == 2


def test_embargo_rejects_negative_days():
    with pytest.raises(ValueError, match=">="):
        embargo_oos_trades([], "2020-01-01", "2020-06-30", embargo_days=-1)


def test_add_trading_days_skips_weekends():
    """Friday 2020-01-03 + 1 trading day = Monday 2020-01-06."""
    from datetime import date
    result = _add_trading_days(date(2020, 1, 3), 1)
    assert result.isoformat() == "2020-01-06"


def test_add_trading_days_zero_is_identity():
    from datetime import date
    d = date(2020, 3, 16)
    assert _add_trading_days(d, 0) == d


def test_classify_trades_for_audit_split_shape():
    trades = [
        FakeTrade("2019-11-01", "2019-12-15"),  # IS kept
        FakeTrade("2019-12-20", "2020-01-10"),  # IS purged (straddle)
        FakeTrade("2020-01-02", "2020-01-10"),  # OOS embargoed
        FakeTrade("2020-02-01", "2020-02-15"),  # OOS kept
    ]
    out = classify_trades_for_audit(
        trades, "2020-01-01", "2020-06-30", embargo_days=5,
    )
    assert len(out["is_kept"]) == 1
    assert len(out["purged"]) == 1
    assert len(out["embargoed"]) == 1
    assert len(out["oos_kept"]) == 1


def test_classify_every_trade_counted_exactly_once():
    trades = [
        FakeTrade("2019-11-01", "2019-12-15"),
        FakeTrade("2019-12-20", "2020-01-10"),
        FakeTrade("2020-01-02", "2020-01-10"),
        FakeTrade("2020-02-01", "2020-02-15"),
        FakeTrade("2020-03-01", "2020-03-14"),
    ]
    out = classify_trades_for_audit(
        trades, "2020-01-01", "2020-06-30", embargo_days=5,
    )
    total = sum(len(v) for v in out.values())
    assert total == len(trades)


def test_purge_handles_dict_shape_trades():
    """Accept plain dicts — not just dataclasses — so callers needn't adapt."""
    trades = [{"entry_date": "2019-12-20", "exit_date": "2020-01-10"}]
    kept = purge_is_trades(trades, "2020-01-01", "2020-06-30")
    assert kept == []


def test_embargo_respects_weekend_in_cutoff():
    """Friday 2020-01-03 is the oos_start. + 5 trading days = 2020-01-10 Friday.
    A trade on 2020-01-09 Thursday is day 4, should be embargoed."""
    trades = [FakeTrade("2020-01-09", "2020-01-20")]
    kept = embargo_oos_trades(trades, "2020-01-03", "2020-06-30", embargo_days=5)
    assert kept == []
