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

    assert row["quarantined"] == 0 or row["quarantined"] is None, \
        f"T1.05: quarantined must be 0, got {row['quarantined']}"


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
