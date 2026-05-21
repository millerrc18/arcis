"""v0.36.42 — reconcile_live_trades parity with the paper-path orphan fix (v0.36.40).

reconcile_live_trades had the SAME orphan-backfill cycle bug as the paper path but
UNGUARDED: ticker-only match against source='live' AND status='open', then backfill
with no recent-close check. A live position that lingers after a close was
re-discovered as an orphan and backfilled as a duplicate NULL-rec_id row.

Fix: `_has_recent_close` is parameterized (`source`, optional `desk`) and applied at
the live detection step with source='live', desk=None (the live tracked-query is
desk-agnostic). Broker stays alpaca-scoped — IB orphans intentionally unguarded.
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

_ET = ZoneInfo("America/New_York")
_NOW = datetime(2026, 5, 20, 9, 1, tzinfo=_ET)


@pytest.fixture
def tmp_db(tmp_path):
    from src.schema.sqlite import create_all_tables
    db = str(tmp_path / "test.db")
    create_all_tables(db)
    return db


def _insert_closed(db, ticker, exit_iso, *, source, desk="swing", broker="alpaca",
                   exit_reason="stop_loss"):
    from src.utils.db import connect_db
    with connect_db(db) as conn:
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, ticker, status, source, broker, desk, actual_exit_time, "
            "exit_reason, created_at, updated_at) "
            "VALUES (?, ?, 'closed', ?, ?, ?, ?, ?, ?, ?)",
            (f"tid-{ticker}-{source}-{exit_iso}", ticker, source, broker, desk,
             exit_iso, exit_reason, exit_iso, exit_iso),
        )
        conn.commit()


# ─────────────── parameterized helper ───────────────

def test_source_live_finds_live_close_not_paper(tmp_db):
    """source='live' must match live closes, and a paper close must NOT mask a live orphan."""
    from src.shadow_trading.reconcile import _has_recent_close, _RECENT_CLOSE_WINDOW_HOURS
    _insert_closed(tmp_db, "COP", (_NOW - timedelta(hours=1)).isoformat(), source="paper")
    # only a PAPER close exists → a LIVE query must NOT see it
    assert _has_recent_close(tmp_db, "COP", _NOW, _RECENT_CLOSE_WINDOW_HOURS,
                             desk=None, source="live") is False
    _insert_closed(tmp_db, "COP", (_NOW - timedelta(hours=1)).isoformat(), source="live")
    assert _has_recent_close(tmp_db, "COP", _NOW, _RECENT_CLOSE_WINDOW_HOURS,
                             desk=None, source="live") is True


def test_desk_none_is_desk_agnostic(tmp_db):
    """desk=None must match a recent close regardless of desk (mirrors the live
    tracked-query which does not filter desk)."""
    from src.shadow_trading.reconcile import _has_recent_close, _RECENT_CLOSE_WINDOW_HOURS
    _insert_closed(tmp_db, "COP", (_NOW - timedelta(hours=1)).isoformat(),
                   source="live", desk="research")
    assert _has_recent_close(tmp_db, "COP", _NOW, _RECENT_CLOSE_WINDOW_HOURS,
                             desk=None, source="live") is True


def test_paper_default_unchanged(tmp_db):
    """Regression: the paper path's positional call (desk passed, source defaulting to
    'paper') still behaves exactly as in v0.36.40."""
    from src.shadow_trading.reconcile import _has_recent_close, _RECENT_CLOSE_WINDOW_HOURS
    _insert_closed(tmp_db, "COP", (_NOW - timedelta(hours=1)).isoformat(),
                   source="paper", desk="swing")
    assert _has_recent_close(tmp_db, "COP", _NOW, _RECENT_CLOSE_WINDOW_HOURS, "swing") is True
    # a live close must not satisfy the default (paper) query
    _insert_closed(tmp_db, "MSFT", (_NOW - timedelta(hours=1)).isoformat(),
                   source="live", desk="swing")
    assert _has_recent_close(tmp_db, "MSFT", _NOW, _RECENT_CLOSE_WINDOW_HOURS, "swing") is False


# ─────────────── behavioral: reconcile_live_trades ───────────────

def _run_live_reconcile(tmp_db, position_ticker):
    """Drive reconcile_live_trades with a real tmp DB and a mocked live broker that
    holds one Alpaca position for `position_ticker`. Uses real `now` (no datetime
    mock) — the behavioral tests insert closes relative to real now."""
    from src.shadow_trading import reconcile as recon

    pos = SimpleNamespace(ticker=position_ticker, quantity=10.0, avg_cost=100.0,
                          current_price=101.0, unrealized_pnl=10.0, market_value=1010.0)
    broker = SimpleNamespace(get_all_positions=lambda: [pos])

    with patch("src.trading.broker_factory.get_live_broker", return_value=broker):
        return recon.reconcile_live_trades(desk="swing", dry_run=False, db_path=tmp_db)


def test_live_recent_close_not_backfilled(tmp_db):
    """A live ticker closed 1h ago whose Alpaca position still shows must NOT be
    backfilled as an orphan (close-didn't-clear)."""
    recent = (datetime.now(_ET) - timedelta(hours=1)).isoformat()
    _insert_closed(tmp_db, "COP", recent, source="live")
    result = _run_live_reconcile(tmp_db, "COP")
    assert "COP" not in result["backfilled"], f"close-didn't-clear COP wrongly backfilled: {result}"


def test_live_genuine_orphan_still_backfilled(tmp_db):
    """A live ticker with NO recent close IS a genuine orphan and must be backfilled."""
    result = _run_live_reconcile(tmp_db, "NVDA")  # nothing in DB for NVDA
    assert "NVDA" in result["backfilled"], f"genuine live orphan NVDA not backfilled: {result}"


def test_live_old_close_is_backfilled(tmp_db):
    """A live ticker whose only close is OUTSIDE the window is a genuine orphan again
    (the accepted >window trade-off) and IS backfilled."""
    old = (datetime.now(_ET) - timedelta(hours=48)).isoformat()
    _insert_closed(tmp_db, "AMD", old, source="live")
    result = _run_live_reconcile(tmp_db, "AMD")
    assert "AMD" in result["backfilled"], f"old-close AMD should be backfillable: {result}"


# ─────────────── wiring lock ───────────────

def test_live_path_wires_recent_close_with_source_live():
    src = pathlib.Path("src/shadow_trading/reconcile.py").read_text(encoding="utf-8")
    start = src.find("def reconcile_live_trades")
    end = src.find("def reconcile_paper_trades", start)
    live_body = src[start:end]
    assert '_has_recent_close(' in live_body and 'source="live"' in live_body, (
        "reconcile_live_trades must call _has_recent_close with source='live'"
    )
