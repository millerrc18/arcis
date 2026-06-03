"""v0.36.40 — orphan-source residual fix: recent-close-window exclusion.

Root cause (docs/audits/2026-W21-orphan-source): the reconciler matches Alpaca
positions to shadow_trades BY TICKER against a narrow status set
(open/exit_failed/exit_pending). When a trade is marked `closed` while the Alpaca
position LINGERS (phantom-close / reconciled_stale $0 close / sticky paper
position), the ticker drops out of `tracked_map` → the 09:01 reconcile re-discovers
it as an "orphan" → backfills a duplicate NULL-rec_id row → the orphan cycle.

The pre-existing Wave 5 guard only skipped re-backfill when the ticker was closed
`exit_reason='reconciled_stale'` within 6 HOURS. The residual ~1/day leaked through
because (a) the close had a DIFFERENT exit_reason (e.g. a phantom `timeout`), or
(b) the re-discovery happened >6h later (the next-morning 09:01 reconcile).

Fix: `_has_recent_close(...)` — a ticker with a paper/alpaca shadow_trade closed
within `_RECENT_CLOSE_WINDOW_HOURS` (24h, ANY exit_reason) is a "close-didn't-clear"
lingering position, NOT a fresh orphan. Used at BOTH the detection step (exclude +
warn) and the backfill step (defense-in-depth), replacing the narrow guard.

Positions carry no order-id (verified: Alpaca position dicts expose only
symbol/qty/avg_entry_price/market_value/P&L), so a recent-close TIME window is the
available discriminator — not order-id matching.
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

_ET = ZoneInfo("America/New_York")
_NOW = datetime(2026, 5, 20, 9, 1, tzinfo=_ET)  # a 09:01 morning-reconcile instant


@pytest.fixture
def tmp_db(tmp_path):
    from src.schema.sqlite import create_all_tables
    db = str(tmp_path / "test.db")
    create_all_tables(db)
    return db


def _insert_closed(db, ticker, exit_time_iso, *, exit_reason="reconciled_stale",
                   source="paper", broker="alpaca", desk="swing", status="closed"):
    """Insert a minimal closed shadow_trade row for the helper to find."""
    from src.utils.db import connect_db
    with connect_db(db) as conn:
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, ticker, status, source, broker, desk, actual_exit_time, "
            "exit_reason, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"tid-{ticker}-{exit_time_iso}", ticker, status, source, broker, desk,
             exit_time_iso, exit_reason, exit_time_iso, exit_time_iso),
        )
        conn.commit()


# ───────────────────────── helper behavior ─────────────────────────

def test_recent_close_within_window_is_true(tmp_db):
    """A close 1h before now is within the 24h window → lingering, not a fresh orphan."""
    from src.shadow_trading.reconcile import _has_recent_close, _RECENT_CLOSE_WINDOW_HOURS
    _insert_closed(tmp_db, "COP", (_NOW - timedelta(hours=1)).isoformat())
    assert _has_recent_close(tmp_db, "COP", _NOW, _RECENT_CLOSE_WINDOW_HOURS, "swing") is True


def test_old_close_outside_window_is_false(tmp_db):
    """A close 30h before now is OUTSIDE 24h → not recently closed (window expired)."""
    from src.shadow_trading.reconcile import _has_recent_close, _RECENT_CLOSE_WINDOW_HOURS
    _insert_closed(tmp_db, "COP", (_NOW - timedelta(hours=30)).isoformat())
    assert _has_recent_close(tmp_db, "COP", _NOW, _RECENT_CLOSE_WINDOW_HOURS, "swing") is False


def test_recent_close_matches_any_exit_reason(tmp_db):
    """The #2 generalization: a recent close with a NON-reconciled_stale reason
    (e.g. a phantom 'timeout') must still count — the old guard missed these."""
    from src.shadow_trading.reconcile import _has_recent_close, _RECENT_CLOSE_WINDOW_HOURS
    _insert_closed(tmp_db, "COP", (_NOW - timedelta(hours=2)).isoformat(),
                   exit_reason="timeout")
    assert _has_recent_close(tmp_db, "COP", _NOW, _RECENT_CLOSE_WINDOW_HOURS, "swing") is True


def test_re_discovery_after_6h_still_caught(tmp_db):
    """The residual the old 6h guard leaked: a prior-evening close re-discovered at
    the next-morning 09:01 reconcile (~11h later) must be caught by the 24h window."""
    from src.shadow_trading.reconcile import _has_recent_close, _RECENT_CLOSE_WINDOW_HOURS
    _insert_closed(tmp_db, "COP", (_NOW - timedelta(hours=11)).isoformat(),
                   exit_reason="reconciled_stale")
    assert _has_recent_close(tmp_db, "COP", _NOW, _RECENT_CLOSE_WINDOW_HOURS, "swing") is True


def test_no_close_means_genuine_orphan(tmp_db):
    """A ticker with no recent close is a GENUINE orphan — must NOT be excluded."""
    from src.shadow_trading.reconcile import _has_recent_close, _RECENT_CLOSE_WINDOW_HOURS
    # different ticker closed recently; COP has nothing
    _insert_closed(tmp_db, "AAPL", (_NOW - timedelta(hours=1)).isoformat())
    assert _has_recent_close(tmp_db, "COP", _NOW, _RECENT_CLOSE_WINDOW_HOURS, "swing") is False


def test_recent_close_respects_desk(tmp_db):
    """A close on a different desk must not mask an orphan on the queried desk."""
    from src.shadow_trading.reconcile import _has_recent_close, _RECENT_CLOSE_WINDOW_HOURS
    _insert_closed(tmp_db, "COP", (_NOW - timedelta(hours=1)).isoformat(), desk="research")
    assert _has_recent_close(tmp_db, "COP", _NOW, _RECENT_CLOSE_WINDOW_HOURS, "swing") is False


def test_window_default_is_24h():
    """The window must be 24h — covers the next-morning 09:01 re-discovery the 6h
    guard missed, while still surfacing genuinely-old positions for backfill."""
    from src.shadow_trading.reconcile import _RECENT_CLOSE_WINDOW_HOURS
    assert _RECENT_CLOSE_WINDOW_HOURS == 24


def test_tz_naive_exit_time_treated_as_recent(tmp_db):
    """A legacy tz-NAIVE actual_exit_time within the window must be treated as a
    recent close (coerced to ET), NOT silently bypassed into 'not recent'. The
    bypass (TypeError on aware−naive subtraction) would re-open the orphan cycle
    for legacy rows — both QA reviewers flagged this as the residual risk."""
    from src.shadow_trading.reconcile import _has_recent_close, _RECENT_CLOSE_WINDOW_HOURS
    naive_1h_ago = (_NOW - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    assert "+" not in naive_1h_ago and "Z" not in naive_1h_ago  # truly naive
    _insert_closed(tmp_db, "COP", naive_1h_ago)
    assert _has_recent_close(tmp_db, "COP", _NOW, _RECENT_CLOSE_WINDOW_HOURS, "swing") is True


def test_exactly_at_window_boundary_is_not_recent(tmp_db):
    """Boundary: a close exactly window_hours ago is NOT 'recent' (strict `<`), so it
    becomes backfillable. Documents the accepted trade-off — a position lingering
    beyond the window re-opens the cycle once (it should be cleared manually; the
    detection-step WARNING surfaces it, and #357 + bracket auto-attach contain it)."""
    from src.shadow_trading.reconcile import _has_recent_close, _RECENT_CLOSE_WINDOW_HOURS
    _insert_closed(tmp_db, "COP", (_NOW - timedelta(hours=24)).isoformat())
    assert _has_recent_close(tmp_db, "COP", _NOW, _RECENT_CLOSE_WINDOW_HOURS, "swing") is False


def test_multiple_closes_recent_one_wins(tmp_db):
    """With both an old (outside) and a recent (inside) close for a ticker, the
    recent one makes it 'recently closed' (helper scans all closed rows)."""
    from src.shadow_trading.reconcile import _has_recent_close, _RECENT_CLOSE_WINDOW_HOURS
    _insert_closed(tmp_db, "COP", (_NOW - timedelta(hours=40)).isoformat(), exit_reason="stop_loss")
    _insert_closed(tmp_db, "COP", (_NOW - timedelta(hours=2)).isoformat(), exit_reason="timeout")
    assert _has_recent_close(tmp_db, "COP", _NOW, _RECENT_CLOSE_WINDOW_HOURS, "swing") is True


# ───────── #132: _raw_ts_within_seconds — the < 1h stale-close guard parse ─────────
# Verify-by-mutation: the reconcile_paper_trades "skip trades < 1 hour old" guard
# previously did datetime.fromisoformat(created_at) inline; under PG created_at is a
# native datetime → TypeError → except:pass → guard SILENTLY DEFEATED → a fresh trade
# could be force-closed reconciled_stale (orphan source). The helper accepts both.

def test_raw_ts_within_seconds_accepts_pg_native_datetime():
    """A PG-native datetime within the window → True. Reverting the helper to a
    string-only fromisoformat makes the datetime raise → caught → False (guard
    defeated) → this assertion fails."""
    from src.shadow_trading.reconcile import _raw_ts_within_seconds
    created_dt = _NOW - timedelta(minutes=30)  # native datetime, 30 min old
    assert _raw_ts_within_seconds(created_dt, _NOW, 3600) is True


def test_raw_ts_within_seconds_accepts_iso_string():
    """SQLite path: an ISO string within the window → True (back-compat)."""
    from src.shadow_trading.reconcile import _raw_ts_within_seconds
    assert _raw_ts_within_seconds((_NOW - timedelta(minutes=30)).isoformat(), _NOW, 3600) is True


def test_raw_ts_within_seconds_coerces_naive_datetime():
    """A tz-naive datetime within the window is coerced to now's zone → True (no
    aware−naive TypeError bypass)."""
    from src.shadow_trading.reconcile import _raw_ts_within_seconds
    naive = (_NOW - timedelta(minutes=30)).replace(tzinfo=None)
    assert _raw_ts_within_seconds(naive, _NOW, 3600) is True


def test_raw_ts_within_seconds_outside_window_is_false():
    """A datetime older than the window → False (trade is NOT recent → reconcilable)."""
    from src.shadow_trading.reconcile import _raw_ts_within_seconds
    assert _raw_ts_within_seconds(_NOW - timedelta(hours=2), _NOW, 3600) is False


def test_raw_ts_within_seconds_unparseable_is_false():
    """Garbage / None → False (fail toward the caller's default path, never raise)."""
    from src.shadow_trading.reconcile import _raw_ts_within_seconds
    assert _raw_ts_within_seconds("not-a-timestamp", _NOW, 3600) is False
    assert _raw_ts_within_seconds(None, _NOW, 3600) is False


# ───────────────────────── wiring (regression-lock) ─────────────────────────

def test_detection_loop_excludes_recent_closes():
    """The orphan-detection loop must call _has_recent_close before appending to
    `orphaned` — so a lingering-post-close ticker is never flagged as an orphan."""
    src = pathlib.Path("src/shadow_trading/reconcile.py").read_text(encoding="utf-8")
    start = src.find("for ticker, pos in alpaca_tickers.items():")
    end = src.find("# Local has it, broker doesn't", start)
    assert start > 0 and end > start, "orphan-detection loop not found"
    loop = src[start:end]
    assert "_has_recent_close(" in loop, (
        "orphan-detection loop must call _has_recent_close before flagging an orphan"
    )


def test_old_narrow_6h_reconciled_stale_guard_is_gone():
    """The narrow guard (reconciled_stale-only, 6h literal) must be replaced by the
    generalized recent-close helper — otherwise the residual still leaks."""
    src = pathlib.Path("src/shadow_trading/reconcile.py").read_text(encoding="utf-8")
    assert "6 * 3600" not in src, "narrow 6h guard literal still present"
