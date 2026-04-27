"""End-to-end integration test for Track 1.5 instrumentation pipeline.

Synthetic open → run → close (mocked broker, in-memory SQLite).
Verifies all 9 Track 1.5 instrumentation fields survive a full
open → check_and_manage → close cycle without regression to NULL.

Track 1.5 fields under test:
  B1  — signal_exit_price, exit_slippage_bps
  B3  — exit_reason ∈ EXIT_REASON_VOCAB
  B4  — llm_conviction_reason (on recommendations row)
  B5  — instrumentation_version = 3
  B8  — llm_timeout_days, timeout_days (= LLM value OR default 15)
  T1.05 — quarantined = 0
  pre-existing — llm_conviction (on recommendations row)
"""
from __future__ import annotations

import sqlite3
import uuid
from unittest.mock import patch

import pytest

from src.journal.store import initialize_database, insert_shadow_trade, log_recommendation
from src.shadow_trading.exit_reason import CONTROLLED_VOCAB
from src.shadow_trading.executor import INSTRUMENTATION_VERSION_CURRENT


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TICKER = "INTG"
_ENTRY_PRICE = 100.0
_TARGET_1 = 110.0
_STOP_PRICE = 93.0
_PLANNED_SHARES = 10.0
_LLM_CONVICTION = 7
_LLM_CONVICTION_REASON = "Key Risk: macro headwind from Fed rate path."
_LLM_TIMEOUT_DAYS = 8
_ENTRY_TS = "2026-04-20T09:30:00"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path) -> str:
    db = str(tmp_path / "pipeline_test.db")
    initialize_database(db)
    return db


def _seed_recommendation(db_path: str) -> str:
    """Insert a recommendation row with conviction fields; return rec_id."""
    from src.schemas import TradePacket, PositionSizing
    packet = TradePacket(
        ticker=_TICKER,
        company_name="Integration Corp",
        recommendation="BUY",
        setup_type="pullback",
        why_now="Test catalyst",
        entry_zone=str(_ENTRY_PRICE),
        stop_invalidation=str(_STOP_PRICE),
        targets=f"{_TARGET_1}/120.00",
        expected_hold_period=f"{_LLM_TIMEOUT_DAYS} days",
        confidence=_LLM_CONVICTION,
        event_risk="Normal",
        position_sizing=PositionSizing(
            allocation_dollars=_PLANNED_SHARES * _ENTRY_PRICE,
            allocation_pct=1.0,
            estimated_risk_dollars=70.0,
        ),
        deeper_analysis="Integration test thesis.",
        llm_conviction=_LLM_CONVICTION,
        llm_conviction_reason=_LLM_CONVICTION_REASON,
        llm_timeout_days=_LLM_TIMEOUT_DAYS,
    )
    return log_recommendation(
        packet=packet,
        features={"strategy_type": "pullback"},
        score=0.85,
        qualification="packet_worthy",
        db_path=db_path,
        llm_conviction=_LLM_CONVICTION,
        llm_conviction_reason=_LLM_CONVICTION_REASON,
        llm_timeout_days=_LLM_TIMEOUT_DAYS,
    )


def _seed_open_trade(db_path: str, trade_id: str, rec_id: str) -> None:
    """Insert an open shadow trade with full Track 1.5 stamps."""
    insert_shadow_trade(
        {
            "trade_id": trade_id,
            "recommendation_id": rec_id,
            "ticker": _TICKER,
            "direction": "long",
            "status": "open",
            "source": "paper",
            "desk": "swing",
            "order_type": "market",
            "planned_shares": _PLANNED_SHARES,
            "entry_price": _ENTRY_PRICE,
            "actual_entry_price": _ENTRY_PRICE,
            "stop_price": _STOP_PRICE,
            "target_1": _TARGET_1,
            "target_2": 0.0,
            "strategy_type": "pullback",
            "created_at": _ENTRY_TS,
            "updated_at": _ENTRY_TS,
            "actual_entry_time": _ENTRY_TS,
            "instrumentation_version": INSTRUMENTATION_VERSION_CURRENT,
            "llm_timeout_days": _LLM_TIMEOUT_DAYS,
            "timeout_days": _LLM_TIMEOUT_DAYS,
            "quarantined": 0,
        },
        db_path,
    )


def _run_exit_cycle(db_path: str, fill_price: float) -> None:
    """Run check_and_manage_open_trades with target_1 hit, mocked broker."""
    from src.shadow_trading import executor as exec_mod

    mock_exit = {
        "order_id": "mock-exit-001",
        "status": "filled",
        "filled_avg_price": fill_price,
        "filled_qty": int(_PLANNED_SHARES),
    }

    with patch.object(exec_mod, "_get_current_price_safe", return_value=_TARGET_1), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions",
               return_value=[{"symbol": _TICKER, "qty": str(_PLANNED_SHARES),
                               "avg_entry_price": str(_ENTRY_PRICE)}]), \
         patch("src.shadow_trading.alpaca_adapter.place_paper_exit",
               return_value=mock_exit), \
         patch("src.shadow_trading.alpaca_adapter.get_order_status",
               return_value={"status": "open", "filled_avg_price": None, "legs": []}), \
         patch("src.shadow_trading.alpaca_adapter.cancel_paper_order",
               return_value={"cancelled": True}), \
         patch.object(exec_mod, "load_config", return_value={
             "shadow_trading": {"timeout_days": 15, "max_positions": 10},
             "strategies": {"mean_reversion": {}},
             "trading": {"ib_enabled": False},
         }):
        exec_mod.check_and_manage_open_trades(db_path=db_path, source_filter="paper")


def _fetch_shadow_row(db_path: str, trade_id: str) -> dict | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT signal_exit_price, exit_slippage_bps, exit_reason, "
            "instrumentation_version, quarantined, llm_timeout_days, timeout_days "
            "FROM shadow_trades WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()
    return dict(row) if row else None


def _fetch_rec_row(db_path: str, rec_id: str) -> dict | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT llm_conviction, llm_conviction_reason "
            "FROM recommendations WHERE recommendation_id = ?",
            (rec_id,),
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

def _assert_shadow_fields(row: dict, trade_id: str) -> None:
    """Assert all shadow_trades instrumentation columns are correctly set."""
    assert row is not None, f"shadow_trade {trade_id} not found in DB"

    assert row["signal_exit_price"] is not None, \
        "B1: signal_exit_price must be non-NULL after close"
    assert abs(row["signal_exit_price"] - _TARGET_1) < 0.01, \
        f"B1: signal_exit_price expected {_TARGET_1}, got {row['signal_exit_price']}"

    assert row["exit_slippage_bps"] is not None, \
        "B1: exit_slippage_bps must be non-NULL after close"

    assert row["exit_reason"] is not None, \
        "B3: exit_reason must be non-NULL after close"
    assert row["exit_reason"] in CONTROLLED_VOCAB, \
        f"B3: exit_reason={row['exit_reason']!r} not in EXIT_REASON_VOCAB"

    assert row["instrumentation_version"] == 3, \
        f"B5: instrumentation_version expected 3, got {row['instrumentation_version']}"

    assert row["llm_timeout_days"] is not None, \
        "B8: llm_timeout_days must be non-NULL"
    assert row["llm_timeout_days"] == _LLM_TIMEOUT_DAYS, \
        f"B8: llm_timeout_days expected {_LLM_TIMEOUT_DAYS}, got {row['llm_timeout_days']}"

    assert row["timeout_days"] is not None, \
        "B8: timeout_days must be non-NULL"
    assert row["timeout_days"] == _LLM_TIMEOUT_DAYS, \
        f"B8: timeout_days expected {_LLM_TIMEOUT_DAYS}, got {row['timeout_days']}"

    # PR-690 O7 pin (2026-04-26): shadow_trades.quarantined is NOT NULL
    # DEFAULT 0. Every row must have an explicit 0/1 value — no None.
    assert row["quarantined"] == 0, \
        f"PR-690 O7: quarantined must be 0 (NOT NULL DEFAULT 0), got {row['quarantined']}"


def _assert_recommendation_fields(row: dict, rec_id: str) -> None:
    """Assert recommendation conviction fields are non-NULL."""
    assert row is not None, f"recommendation {rec_id} not found in DB"

    assert row["llm_conviction"] is not None, \
        "pre-existing: llm_conviction must be non-NULL"
    assert row["llm_conviction"] == _LLM_CONVICTION, \
        f"pre-existing: llm_conviction expected {_LLM_CONVICTION}, got {row['llm_conviction']}"

    assert row["llm_conviction_reason"] is not None, \
        "B4: llm_conviction_reason must be non-NULL"
    assert len(row["llm_conviction_reason"]) > 0, \
        "B4: llm_conviction_reason must not be empty string"


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def test_full_pipeline_all_9_instrumentation_fields(tmp_path):
    """Synthetic open → run → close verifies all 9 Track 1.5 columns.

    Mocks broker only; uses in-memory SQLite via initialize_database.
    The fill_price is set slightly above target_1 to exercise the
    exit_slippage_bps calculation (non-zero bps).
    """
    db_path = _make_db(tmp_path)
    rec_id = _seed_recommendation(db_path)
    trade_id = str(uuid.uuid4())
    _seed_open_trade(db_path, trade_id, rec_id)

    fill_price = _TARGET_1 + 0.15
    _run_exit_cycle(db_path, fill_price)

    shadow_row = _fetch_shadow_row(db_path, trade_id)
    rec_row = _fetch_rec_row(db_path, rec_id)

    _assert_shadow_fields(shadow_row, trade_id)
    _assert_recommendation_fields(rec_row, rec_id)

    expected_slippage = (fill_price - _TARGET_1) / _TARGET_1 * 10000
    assert abs(shadow_row["exit_slippage_bps"] - expected_slippage) < 0.5, (
        f"B1: exit_slippage_bps expected ~{expected_slippage:.1f}, "
        f"got {shadow_row['exit_slippage_bps']}"
    )


# ---------------------------------------------------------------------------
# PR-690 O4 — Negative-path integration tests
#
# The happy-path test above exercises exactly one shape (open → target_1 →
# clean fill). PR-690 review item O4 calls out four under-tested negative
# paths that the operator can plausibly observe in production. Each test
# below pins the expected DB state for one of those paths so a future
# silent regression in any branch fails CI rather than corrupting trades.
# ---------------------------------------------------------------------------


def _run_exit_cycle_with_no_fill(db_path: str) -> None:
    """Variant of _run_exit_cycle that returns filled status WITHOUT a fill price.

    Models broker reporting a filled order whose `filled_avg_price` is None
    (real Alpaca scenarios: dark-pool prints arriving on a delay, paper-engine
    edge cases, sandbox stub responses). The executor must (a) fall through
    the slippage-calculation branch without raising, and (b) still close the
    trade using the pre-fill signal price as the exit price.
    """
    from src.shadow_trading import executor as exec_mod

    mock_exit = {
        "order_id": "mock-exit-no-fill",
        "status": "filled",
        "filled_avg_price": None,  # ← the regression surface
        "filled_qty": int(_PLANNED_SHARES),
    }

    with patch.object(exec_mod, "_get_current_price_safe", return_value=_TARGET_1), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions",
               return_value=[{"symbol": _TICKER, "qty": str(_PLANNED_SHARES),
                               "avg_entry_price": str(_ENTRY_PRICE)}]), \
         patch("src.shadow_trading.alpaca_adapter.place_paper_exit",
               return_value=mock_exit), \
         patch("src.shadow_trading.alpaca_adapter.get_order_status",
               return_value={"status": "open", "filled_avg_price": None, "legs": []}), \
         patch("src.shadow_trading.alpaca_adapter.cancel_paper_order",
               return_value={"cancelled": True}), \
         patch.object(exec_mod, "load_config", return_value={
             "shadow_trading": {"timeout_days": 15, "max_positions": 10},
             "strategies": {"mean_reversion": {}},
             "trading": {"ib_enabled": False},
         }):
        exec_mod.check_and_manage_open_trades(db_path=db_path, source_filter="paper")


def test_full_pipeline_when_fill_price_is_none(tmp_path):
    """Broker returns filled status with no fill price → trade closes gracefully.

    PR-690 O4 negative path #1. When `filled_avg_price` is None the executor's
    slippage-calc branch is gated by `if fill_exit is not None` (executor.py
    line 2027) so it must NOT divide-by-None and must NOT raise. The trade
    should still close at signal_exit price; exit_slippage_bps should be NULL
    because the broker never reported a fill price to compare against.
    """
    db_path = _make_db(tmp_path)
    rec_id = _seed_recommendation(db_path)
    trade_id = str(uuid.uuid4())
    _seed_open_trade(db_path, trade_id, rec_id)

    # Must not raise.
    _run_exit_cycle_with_no_fill(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, exit_reason, signal_exit_price, exit_slippage_bps, "
            "actual_exit_price FROM shadow_trades WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()

    assert row is not None, "shadow_trade row vanished after exit cycle"
    # Trade still closes — graceful path, not exit_failed.
    assert row["status"] == "closed", (
        f"O4#1: trade should close cleanly when fill_price is None; "
        f"got status={row['status']!r}"
    )
    # exit_reason in vocab (target_1_hit from the price polling path).
    assert row["exit_reason"] in CONTROLLED_VOCAB, (
        f"O4#1: exit_reason={row['exit_reason']!r} not in EXIT_REASON_VOCAB"
    )
    # Signal price is captured even when broker didn't fill.
    assert row["signal_exit_price"] is not None and abs(
        row["signal_exit_price"] - _TARGET_1
    ) < 0.01, (
        f"O4#1: signal_exit_price expected {_TARGET_1}, got "
        f"{row['signal_exit_price']}"
    )
    # exit_slippage_bps must be NULL — there is no fill to compare against.
    # The slippage-calc branch is GATED on `fill_exit is not None`, so leaving
    # exit_slippage_bps NULL is the correct, non-fabricated answer.
    assert row["exit_slippage_bps"] is None, (
        f"O4#1: exit_slippage_bps should be NULL when broker reports no fill, "
        f"got {row['exit_slippage_bps']!r}"
    )
    # Exit price falls back to the pre-bracket signal price.
    assert row["actual_exit_price"] is not None and abs(
        row["actual_exit_price"] - _TARGET_1
    ) < 0.01, (
        f"O4#1: actual_exit_price expected {_TARGET_1}, got "
        f"{row['actual_exit_price']}"
    )


def _run_exit_cycle_signal_zero(db_path: str) -> None:
    """Run the exit cycle with current_price=0 so signal_exit collapses to 0.

    This drives the executor's slippage-divisor guard at line 2029
    (`if signal_exit and signal_exit > 0:`). With signal_exit=0 the guard
    must short-circuit; otherwise (signal-zero gone unguarded) the code
    would compute (current_price - 0) / 0 → ZeroDivisionError. exit_reason
    becomes 'stop_loss' because current_price=0 ≤ stop_price=93.
    """
    from src.shadow_trading import executor as exec_mod

    mock_exit = {
        "order_id": "mock-exit-zero-signal",
        "status": "filled",
        "filled_avg_price": 0.0,  # broker reports 0 fill price
        "filled_qty": int(_PLANNED_SHARES),
    }

    with patch.object(exec_mod, "_get_current_price_safe", return_value=0.0), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions",
               return_value=[{"symbol": _TICKER, "qty": str(_PLANNED_SHARES),
                               "avg_entry_price": str(_ENTRY_PRICE)}]), \
         patch("src.shadow_trading.alpaca_adapter.place_paper_exit",
               return_value=mock_exit), \
         patch("src.shadow_trading.alpaca_adapter.get_order_status",
               return_value={"status": "open", "filled_avg_price": None, "legs": []}), \
         patch("src.shadow_trading.alpaca_adapter.cancel_paper_order",
               return_value={"cancelled": True}), \
         patch.object(exec_mod, "load_config", return_value={
             "shadow_trading": {"timeout_days": 15, "max_positions": 10},
             "strategies": {"mean_reversion": {}},
             "trading": {"ib_enabled": False},
         }):
        exec_mod.check_and_manage_open_trades(db_path=db_path, source_filter="paper")


def test_full_pipeline_when_signal_exit_is_zero(tmp_path):
    """Boundary on slippage divisor — ZeroDivisionError must NOT propagate.

    PR-690 O4 negative path #2. When the price feed is stale or the broker
    reports a 0 fill, signal_exit collapses to 0. The slippage formula
    `(current_price - signal_exit) / signal_exit * 10000` would raise
    ZeroDivisionError without the explicit `signal_exit > 0` guard at
    executor.py line 2029. This test pins both:
      (a) no exception bubbles out of check_and_manage_open_trades, and
      (b) exit_slippage_bps is NULL (the appropriate sentinel — slippage
          is undefined when the divisor is 0, NOT silently 0.0).
    """
    db_path = _make_db(tmp_path)
    rec_id = _seed_recommendation(db_path)
    trade_id = str(uuid.uuid4())
    _seed_open_trade(db_path, trade_id, rec_id)

    # Must not raise ZeroDivisionError.
    _run_exit_cycle_signal_zero(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, exit_reason, signal_exit_price, exit_slippage_bps "
            "FROM shadow_trades WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()

    assert row is not None, "shadow_trade row vanished after exit cycle"
    # Trade still closed — the divisor guard short-circuits gracefully.
    assert row["status"] == "closed", (
        f"O4#2: trade should still close when signal_exit is 0; "
        f"got status={row['status']!r}"
    )
    # exit_reason captured from the price-polling branch (stop_loss when
    # current_price=0 ≤ stop_price=93).
    assert row["exit_reason"] in CONTROLLED_VOCAB, (
        f"O4#2: exit_reason={row['exit_reason']!r} not in EXIT_REASON_VOCAB"
    )
    # signal_exit_price NULL (the executor only persists it when > 0; see
    # executor.py line 2148 — `signal_exit if signal_exit and signal_exit > 0
    # else None`).
    assert row["signal_exit_price"] is None, (
        f"O4#2: signal_exit_price should be NULL when signal collapsed to 0, "
        f"got {row['signal_exit_price']!r}"
    )
    # exit_slippage_bps NULL — undefined when divisor is 0. The guard at
    # executor.py:2029 must short-circuit BEFORE computing the ratio.
    assert row["exit_slippage_bps"] is None, (
        f"O4#2: exit_slippage_bps should be NULL when signal_exit is 0 "
        f"(division-by-zero guard); got {row['exit_slippage_bps']!r}"
    )


def _seed_recommendation_no_reason(db_path: str) -> str:
    """Insert a recommendation row with conviction but NULL conviction_reason.

    Models the B4 graceful-degradation path: the LLM returned a numeric
    conviction (1-10) but failed to emit the `key_risks` paragraph. The
    pipeline should still ingest the recommendation; the column is NULL.
    """
    from src.schemas import TradePacket, PositionSizing
    packet = TradePacket(
        ticker=_TICKER,
        company_name="Integration Corp",
        recommendation="BUY",
        setup_type="pullback",
        why_now="Test catalyst",
        entry_zone=str(_ENTRY_PRICE),
        stop_invalidation=str(_STOP_PRICE),
        targets=f"{_TARGET_1}/120.00",
        expected_hold_period=f"{_LLM_TIMEOUT_DAYS} days",
        confidence=_LLM_CONVICTION,
        event_risk="Normal",
        position_sizing=PositionSizing(
            allocation_dollars=_PLANNED_SHARES * _ENTRY_PRICE,
            allocation_pct=1.0,
            estimated_risk_dollars=70.0,
        ),
        deeper_analysis="Integration test thesis without conviction reason.",
        llm_conviction=_LLM_CONVICTION,
        llm_conviction_reason=None,  # ← LLM didn't emit key_risks
        llm_timeout_days=_LLM_TIMEOUT_DAYS,
    )
    return log_recommendation(
        packet=packet,
        features={"strategy_type": "pullback"},
        score=0.85,
        qualification="packet_worthy",
        db_path=db_path,
        llm_conviction=_LLM_CONVICTION,
        llm_conviction_reason=None,
        llm_timeout_days=_LLM_TIMEOUT_DAYS,
    )


def test_full_pipeline_when_conviction_reason_is_null(tmp_path):
    """LLM emitted conviction but no reason → pipeline completes; reason stays NULL.

    PR-690 O4 negative path #3. B4 instrumentation guarantees graceful
    degradation when the local LLM fails to emit the `key_risks` paragraph.
    Pre-B4 the row was rejected outright; B4 inserts the row with
    llm_conviction populated and llm_conviction_reason=NULL. This test pins:
      (a) log_recommendation succeeds with reason=None (no schema barf), and
      (b) the full open → close cycle still produces a closed trade with
          all OTHER instrumentation fields populated.
    """
    db_path = _make_db(tmp_path)
    rec_id = _seed_recommendation_no_reason(db_path)
    trade_id = str(uuid.uuid4())
    _seed_open_trade(db_path, trade_id, rec_id)

    fill_price = _TARGET_1 + 0.15
    _run_exit_cycle(db_path, fill_price)

    rec_row = _fetch_rec_row(db_path, rec_id)
    shadow_row = _fetch_shadow_row(db_path, trade_id)

    # Recommendation persisted with conviction but NULL reason.
    assert rec_row is not None, "recommendation row should still be inserted"
    assert rec_row["llm_conviction"] == _LLM_CONVICTION, (
        f"O4#3: llm_conviction must populate even when reason is NULL; "
        f"got {rec_row['llm_conviction']!r}"
    )
    assert rec_row["llm_conviction_reason"] is None, (
        f"O4#3: llm_conviction_reason should be NULL (B4 graceful degradation); "
        f"got {rec_row['llm_conviction_reason']!r}"
    )
    # Trade closes normally — instrumentation other than conviction_reason
    # is unaffected by the reason being NULL.
    assert shadow_row is not None
    assert shadow_row["instrumentation_version"] == 3, (
        f"O4#3: instrumentation_version still 3 when conviction_reason NULL; "
        f"got {shadow_row['instrumentation_version']!r}"
    )
    assert shadow_row["exit_reason"] in CONTROLLED_VOCAB
    assert shadow_row["exit_slippage_bps"] is not None


def _fetch_broker_exception_rows(db_path: str, ticker: str) -> list[dict]:
    """Read all broker_exceptions rows for `ticker` ordered by id."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ticker, operation, broker, exception_class, recoverable, "
            "outcome FROM broker_exceptions WHERE ticker = ? ORDER BY id ASC",
            (ticker,),
        ).fetchall()
    return [dict(r) for r in rows]


def _run_exit_cycle_broker_raises(db_path: str) -> None:
    """Run the exit cycle with `place_paper_exit` raising APIError.

    Routes broker_exception_logger.connect_db to the test DB so the
    persisted row lands in the same SQLite file we're inspecting (the
    executor calls log_and_persist with no db_path arg, which would
    otherwise hit the real DB_PATH from src.utils.db).
    """
    from src.shadow_trading import executor as exec_mod
    from src.shadow_trading import broker_exception_logger as bel
    from src.utils.db import connect_db as _real_connect_db
    from alpaca.common.exceptions import APIError

    def _connect_to_test_db(db_path_arg: str = db_path) -> object:
        # Force broker_exception_logger writes to the test DB regardless of
        # whether the executor passes a db_path arg.
        return _real_connect_db(db_path)

    api_err = APIError({"code": 42210000, "message": "broker rejected exit"})

    with patch.object(exec_mod, "_get_current_price_safe", return_value=_TARGET_1), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions",
               return_value=[{"symbol": _TICKER, "qty": str(_PLANNED_SHARES),
                               "avg_entry_price": str(_ENTRY_PRICE)}]), \
         patch("src.shadow_trading.alpaca_adapter.place_paper_exit",
               side_effect=api_err), \
         patch("src.shadow_trading.alpaca_adapter.get_order_status",
               return_value={"status": "open", "filled_avg_price": None, "legs": []}), \
         patch("src.shadow_trading.alpaca_adapter.cancel_paper_order",
               return_value={"cancelled": True}), \
         patch.object(bel, "connect_db", side_effect=_connect_to_test_db), \
         patch.object(exec_mod, "load_config", return_value={
             "shadow_trading": {"timeout_days": 15, "max_positions": 10},
             "strategies": {"mean_reversion": {}},
             "trading": {"ib_enabled": False},
         }):
        exec_mod.check_and_manage_open_trades(db_path=db_path, source_filter="paper")


def test_full_pipeline_when_broker_exception_during_exit(tmp_path):
    """Broker raises during exit → B2 structured logging fires; trade marked failed.

    PR-690 O4 negative path #4. The B2 structured logger
    (src/shadow_trading/broker_exception_logger.py) must (a) be invoked from
    the executor's place_exit catch block at executor.py line 1978, (b) write
    a broker_exceptions row with the expected ticker / operation / broker /
    exception_class, and (c) leave the shadow trade in a non-orphan state
    (status=exit_failed first attempt; reconciler retries; never silently
    succeed).

    Pre-B2 the executor swallowed broker exceptions silently — the trade
    appeared open but was effectively orphaned. Tests must catch any future
    swallow regression.
    """
    db_path = _make_db(tmp_path)
    rec_id = _seed_recommendation(db_path)
    trade_id = str(uuid.uuid4())
    _seed_open_trade(db_path, trade_id, rec_id)

    _run_exit_cycle_broker_raises(db_path)

    # (a) broker_exceptions row created with correct ticker/op/broker.
    bx_rows = _fetch_broker_exception_rows(db_path, _TICKER)
    assert bx_rows, (
        "O4#4 (B2): no broker_exceptions row was persisted — the structured "
        "logger never fired. This is the bug B2 was designed to prevent."
    )
    # The place_exit catch block uses operation='place_exit', broker='alpaca_paper'.
    place_exit_rows = [r for r in bx_rows if r["operation"] == "place_exit"]
    assert place_exit_rows, (
        f"O4#4 (B2): expected at least one row with operation='place_exit'; "
        f"got operations={[r['operation'] for r in bx_rows]!r}"
    )
    bx = place_exit_rows[0]
    assert bx["ticker"] == _TICKER, (
        f"O4#4 (B2): broker_exceptions.ticker expected {_TICKER!r}, got "
        f"{bx['ticker']!r}"
    )
    assert bx["broker"] == "alpaca_paper", (
        f"O4#4 (B2): broker_exceptions.broker expected 'alpaca_paper', got "
        f"{bx['broker']!r}"
    )
    assert bx["exception_class"] == "APIError", (
        f"O4#4 (B2): broker_exceptions.exception_class expected 'APIError', "
        f"got {bx['exception_class']!r}"
    )

    # (b) shadow trade marked exit_failed (not silently closed) with vocab-valid
    # exit_reason. _MAX_EXIT_RETRIES=3, so first failure → exit_failed (not
    # exit_abandoned).
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, exit_reason, exit_retry_count "
            "FROM shadow_trades WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()
    assert row is not None
    assert row["status"] in ("exit_failed", "exit_abandoned"), (
        f"O4#4 (B2): trade must NOT be silently closed when broker raises; "
        f"expected status in {{exit_failed, exit_abandoned}}, got "
        f"{row['status']!r}"
    )
    # Wave 2b promoted 'broker_exception' to first-class CONTROLLED_VOCAB so
    # coerce_exit_reason("broker_exception") returns "broker_exception" (not
    # "unknown"). The old comment was written before that promotion.
    assert row["exit_reason"] in CONTROLLED_VOCAB, (
        f"O4#4 (B3): exit_reason={row['exit_reason']!r} not in "
        f"EXIT_REASON_VOCAB"
    )
    assert row["exit_reason"] == "broker_exception", (
        f"O4#4: exit_reason should be 'broker_exception' (Wave 2b first-class "
        f"vocab token for broker-side exceptions); got {row['exit_reason']!r}"
    )
    assert (row["exit_retry_count"] or 0) >= 1, (
        f"O4#4: exit_retry_count must be incremented on broker exception "
        f"(see #610); got {row['exit_retry_count']!r}"
    )
