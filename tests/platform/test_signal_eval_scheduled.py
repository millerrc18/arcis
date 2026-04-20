"""Scheduled-kind find_candidates_for_date — Sprint A / #494.

Exercises the new scheduled branch in src.platform.signal_eval, plus
confirms the event-driven branch and backtest _run_scheduled path are
unchanged (regression guards).
"""
import sqlite3
from datetime import datetime
from unittest.mock import patch

import pytest

from src.platform.signal_eval import (
    _evaluate_event_signal,
    find_candidates_for_date,
)
from src.platform.strategy_spec import StrategySpec


# Fixed historical anchor: 2023-11-06 is a Monday, 2023-11-07 a Tuesday.
MONDAY = datetime(2023, 11, 6)
TUESDAY = datetime(2023, 11, 7)


def _bare_db(tmp_path) -> str:
    """Empty SQLite DB — scheduled path doesn't need edgar_filings rows,
    but _load_open_tickers_for_desk tolerates missing shadow_trades table
    (returns empty set on any Exception), so a bare DB suffices."""
    db = str(tmp_path / "test.db")
    sqlite3.connect(db).close()
    return db


def _sched_spec(
    strategy_id: str = "sched_v1",
    universe: dict | None = None,
    entry_overrides: dict | None = None,
) -> StrategySpec:
    entry = {"kind": "scheduled", "day_of_week": "Monday", "time": "close"}
    if entry_overrides:
        entry.update(entry_overrides)
    return StrategySpec(
        strategy_id=strategy_id,
        display_name=strategy_id.upper(),
        universe=universe or {"tickers": ["AAPL", "MSFT"]},
        entry=entry,
        exit={"kind": "mechanical", "timeout_days": 5,
              "stop": {"method": "pct", "value": 0.02},
              "target": {"method": "pct", "value": 0.03}},
        position_sizing={"method": "fixed_pct_equity", "pct": 0.15,
                         "max_concurrent": 2},
        attribution={"benchmark": "SPY_matched_window", "metrics": ["sharpe"]},
        raw={}, source="test",
    )


# ── Core behavior ─────────────────────────────────────────────────────────


def test_scheduled_kind_resolves_candidates_for_fixed_date(tmp_path):
    """Monday spec + Monday as_of + 2-ticker universe → 2 candidates."""
    db = _bare_db(tmp_path)
    spec = _sched_spec()
    candidates = find_candidates_for_date(spec, db_path=db, as_of=MONDAY)
    assert len(candidates) == 2
    assert {c["ticker"] for c in candidates} == {"AAPL", "MSFT"}
    for c in candidates:
        assert c["as_of"] == MONDAY.isoformat()
        assert c["shares"] == 1
        assert c["price"] == 0.0
        assert c["signal_strength"] == 0.5
        assert c["metadata"]["trigger"] == "scheduled"
        assert c["metadata"]["strategy_spec_hash"]
        # Event-only metadata keys are absent or empty
        assert c["metadata"].get("filing_accession") == ""


def test_scheduled_empty_filter_returns_full_universe(tmp_path):
    """Spec with no day_of_week trigger fires on any day → full universe."""
    db = _bare_db(tmp_path)
    spec = _sched_spec(entry_overrides={"day_of_week": None})
    # strip the None so _matches_scheduled_trigger treats it as absent
    del spec.entry["day_of_week"]
    for as_of in (MONDAY, TUESDAY):
        candidates = find_candidates_for_date(spec, db_path=db, as_of=as_of)
        assert {c["ticker"] for c in candidates} == {"AAPL", "MSFT"}


def test_scheduled_day_of_week_mismatch_returns_empty(tmp_path):
    db = _bare_db(tmp_path)
    spec = _sched_spec(entry_overrides={"day_of_week": "Friday"})
    assert find_candidates_for_date(spec, db_path=db, as_of=MONDAY) == []


def test_scheduled_empty_universe_returns_empty(tmp_path):
    db = _bare_db(tmp_path)
    spec = _sched_spec(universe={"tickers": []})
    assert find_candidates_for_date(spec, db_path=db, as_of=MONDAY) == []


# ── Filter-stack composition (v0.26.2-scoped additions) ───────────────────


def test_scheduled_sector_filter_applied(tmp_path):
    """sector_filter narrows the resolved universe before candidate build."""
    db = _bare_db(tmp_path)
    spec = _sched_spec(
        universe={"tickers": "sp100", "sector_filter": ["Technology"]},
    )
    from src.universe.sectors import SECTOR_MAP
    candidates = find_candidates_for_date(spec, db_path=db, as_of=MONDAY)
    assert candidates, "Technology sector on sp100 is non-empty"
    for c in candidates:
        assert SECTOR_MAP.get(c["ticker"]) == "Technology"


def test_scheduled_event_exclusion_applied(tmp_path):
    """entry.event_exclusion skips a known-event day regardless of trigger."""
    db = _bare_db(tmp_path)
    spec = _sched_spec(entry_overrides={
        "event_exclusion": {"categories": ["Trade Policy"]},
    })
    # Patch the exclusion evaluator to claim this Monday is a Trade Policy date.
    with patch(
        "src.platform.signal_eval.is_excluded_event_date",
        return_value=True,
    ):
        assert find_candidates_for_date(spec, db_path=db, as_of=MONDAY) == []
    # And confirms the path re-admits when the exclusion is off.
    assert find_candidates_for_date(spec, db_path=db, as_of=MONDAY)


def test_scheduled_dedupes_open_positions(tmp_path):
    """Tickers with open shadow_trades on desk research_<id> are excluded."""
    from src.schema.sqlite import create_all_tables
    db = str(tmp_path / "test.db")
    create_all_tables(db)
    conn = sqlite3.connect(db)
    conn.execute("""
        INSERT INTO shadow_trades
            (trade_id, ticker, planned_shares, entry_price, desk,
             source, status, direction, created_at, updated_at)
        VALUES ('t1', 'AAPL', 10, 100.0, 'research_sched_v1',
                'paper', 'open', 'long',
                '2023-11-04', '2023-11-04')
    """)
    conn.commit()
    conn.close()
    spec = _sched_spec()
    candidates = find_candidates_for_date(spec, db_path=db, as_of=MONDAY)
    assert {c["ticker"] for c in candidates} == {"MSFT"}


# ── Regression guards ──────────────────────────────────────────────────────


def test_unknown_operator_does_not_raise(tmp_path):
    """Sprint guardrail: match event_driven semantics — unknown operators
    evaluate to False without raising. The only raise path in
    find_candidates_for_date is unknown entry.kind and python_plugin."""
    sections = {"item_1a_cosine_yoy": 0.3}
    signal = [{"metric": "cosine_similarity", "target": "item_1a",
               "operator": "NOT_A_REAL_OP", "threshold": 0.5}]
    # AND: no condition passes → False.
    assert _evaluate_event_signal(sections, signal, combinator="all") is False
    # OR: no condition passes → False.
    assert _evaluate_event_signal(sections, signal, combinator="any") is False


def test_unknown_entry_kind_raises(tmp_path):
    db = _bare_db(tmp_path)
    spec = _sched_spec(entry_overrides={"kind": "not_a_real_kind"})
    with pytest.raises(ValueError, match="unknown entry.kind"):
        find_candidates_for_date(spec, db_path=db, as_of=MONDAY)


def test_walkforward_path_untouched(tmp_path):
    """#494 sprint must not affect backtest_engine._run_scheduled.
    Verifies by importing the dispatcher and confirming scheduled routes
    through _run_scheduled (not signal_eval)."""
    from src.platform import backtest_engine
    assert hasattr(backtest_engine, "_run_scheduled")
    # Pure sanity — the dispatcher code path is:
    #     run_backtest → spec.entry.kind=='scheduled' → _run_scheduled
    # (verified in Pass 2 research §3, docs/sprints/...)
    import inspect
    src = inspect.getsource(backtest_engine.run_backtest)
    assert "_run_scheduled(config)" in src
    assert "find_candidates_for_date" not in src
