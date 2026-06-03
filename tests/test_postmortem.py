"""Tests for postmortem generation."""

import pytest
from src.evaluation.postmortem import generate_postmortem, determine_lesson_tag


def _make_trade(
    ticker="AAPL",
    entry=100.0,
    exit_p=110.0,
    pnl=10.0,
    pnl_pct=10.0,
    exit_reason="target_1_hit",
    duration=5,
    mfe=12.0,
    mae=-2.0,
    stop=95.0,
    target_1=110.0,
    target_2=120.0,
    thesis="Strong trend pullback",
    atr=2.5,
):
    return {
        "ticker": ticker,
        "actual_entry_price": entry,
        "actual_exit_price": exit_p,
        "pnl_dollars": pnl,
        "pnl_pct": pnl_pct,
        "exit_reason": exit_reason,
        "duration_days": duration,
        "max_favorable_excursion": mfe,
        "max_adverse_excursion": mae,
        "stop_price": stop,
        "target_1": target_1,
        "target_2": target_2,
        "actual_entry_time": "2026-03-15T09:30:00-04:00",
        "actual_exit_time": "2026-03-20T15:30:00-04:00",
        "thesis_text": thesis,
        "atr": atr,
        "entry_price": entry,
    }


def test_postmortem_handles_pg_native_datetimes_without_crashing():
    """PG-cutover regression (#132): psycopg2 returns timestamp columns as native
    datetime objects (connect_db's RealDictCursor does NOT stringify), not ISO
    strings. generate_postmortem sliced ``actual_entry_time[:10]`` to extract the
    date, which raised "'datetime.datetime' object is not subscriptable" and
    aborted check_and_manage_open_trades mid-close — leaving the broker position
    open ("close-didn't-clear" → orphan source).

    Boundary-touch / verify-by-mutation: reverting the str()-coercion at
    postmortem.py:42-43 makes this test raise TypeError, not just lose an
    assertion (the function never returns).
    """
    from datetime import datetime, timezone

    trade = _make_trade()
    trade["actual_entry_time"] = datetime(2026, 3, 15, 13, 30, tzinfo=timezone.utc)
    trade["actual_exit_time"] = datetime(2026, 3, 20, 19, 30, tzinfo=timezone.utc)

    # Pre-fix this raised TypeError; post-fix it returns a normal postmortem with
    # the date prefix extracted from the datetime (str(dt)[:10] == "YYYY-MM-DD").
    pm = generate_postmortem(trade)
    assert "POSTMORTEM" in pm
    assert "2026-03-15" in pm  # entry date rendered from a native datetime
    assert "2026-03-20" in pm  # exit date rendered from a native datetime


def test_winning_trade_target_hit():
    trade = _make_trade(exit_reason="target_1_hit", pnl=10.0, pnl_pct=10.0)
    pm = generate_postmortem(trade)

    assert "POSTMORTEM" in pm
    assert "AAPL" in pm
    assert "target_1_hit" in pm
    assert "Trade Summary:" in pm
    assert "What went right:" in pm
    assert "What went wrong:" in pm
    assert "Thesis evaluation:" in pm
    assert "Lessons:" in pm
    assert "Repeatability:" in pm
    assert "Validated" in pm


def test_losing_trade_stop_hit():
    trade = _make_trade(
        exit_reason="stop_hit",
        exit_p=95.0,
        pnl=-5.0,
        pnl_pct=-5.0,
        mfe=2.0,
        mae=-5.0,
    )
    pm = generate_postmortem(trade)

    assert "Invalidated" in pm
    assert "stop_hit" in pm


def test_timeout_trade_positive_mfe():
    trade = _make_trade(
        exit_reason="timeout",
        exit_p=101.0,
        pnl=1.0,
        pnl_pct=1.0,
        mfe=5.0,
        mae=-1.0,
        duration=15,
    )
    pm = generate_postmortem(trade)

    assert "timeout" in pm
    # Positive P&L with timeout = partially validated
    assert "Partially validated" in pm or "Validated" in pm


def test_timeout_trade_negative():
    trade = _make_trade(
        exit_reason="timeout",
        exit_p=99.0,
        pnl=-1.0,
        pnl_pct=-1.0,
        mfe=3.0,
        mae=-3.0,
        duration=15,
    )
    pm = generate_postmortem(trade)

    assert "timeout" in pm
    assert "Inconclusive" in pm


def test_all_sections_present():
    trade = _make_trade()
    pm = generate_postmortem(trade)

    required_sections = [
        "POSTMORTEM",
        "Trade Summary:",
        "What went right:",
        "What went wrong:",
        "Thesis evaluation:",
        "Lessons:",
        "Repeatability:",
    ]
    for section in required_sections:
        assert section in pm, f"Missing section: {section}"


def test_lesson_tag_target_hit():
    trade = _make_trade(exit_reason="target_1_hit", pnl=10.0)
    assert determine_lesson_tag(trade) == "thesis_validated"


def test_lesson_tag_stop_hit():
    trade = _make_trade(exit_reason="stop_hit", pnl=-5.0, mfe=0)
    assert determine_lesson_tag(trade) == "thesis_invalidated"


def test_lesson_tag_timeout():
    trade = _make_trade(exit_reason="timeout", pnl=-1.0)
    assert determine_lesson_tag(trade) == "thesis_inconclusive"


def test_lesson_tag_manual():
    trade = _make_trade(exit_reason="manual", pnl=5.0)
    assert determine_lesson_tag(trade) == "manual_close"
