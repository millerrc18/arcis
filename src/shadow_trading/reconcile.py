"""Reconcile Alpaca positions with shadow_trades database.

Called by: cli.commands, scheduler.watch
Calls: journal.store, shadow_trading.alpaca_adapter
Owns tables: none
Config keys: none
Tests: tests/test_reconcile.py

Detects orphaned positions (on Alpaca but not in DB) and stale records
(in DB but not on Alpaca). Backfills missing records and marks stale ones.

Why reconciliation?
~~~~~~~~~~~~~~~~~~~
The local shadow_trades database and Alpaca's actual positions can
drift apart for several reasons:
  1. Manual trades placed directly through the Alpaca dashboard
  2. Orders filled while the system was offline (e.g. BSOD, restart)
  3. Bracket legs filling without the monitor catching them
  4. Race conditions during order placement (#99)

Two discrepancy types:
  - Orphaned: Alpaca has a position, local DB doesn't know about it.
    Action: backfill a shadow_trade record so it's tracked.
  - Stale: local DB says a trade is open, but Alpaca has no position.
    Action: mark the trade as closed (the position was likely sold).

Negative shares guard (#188): the system is long-only.  If Alpaca
reports negative qty (short position), the backfill is rejected to
prevent database corruption from unexpected short positions.

Both live and paper reconciliation follow the same logic, but paper
trades include a 1-hour safety guard to avoid false closures from
transient Alpaca API blips (Alpaca's paper API occasionally returns
incomplete position lists).
"""

import logging
import sqlite3
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.shadow_trading._status_sql import active_in_clause
from src.shadow_trading.alpaca_adapter import (
    cancel_orders_for_ticker,
    get_all_positions,
    get_live_positions,
)
from src.shadow_trading.exit_reason import coerce_exit_reason
from src.utils.db import connect_db

logger = logging.getLogger(__name__)

# #628 — Dedup guard for the IB cold-storage INFO log.
# reconcile_paper_trades() runs every ~13 minutes (111×/day). When an IB
# trade is cold-stored, the "[RECONCILE] N IB position(s) tracked but
# trading.ib_enabled=false" message fires every cycle. Storing today's
# ET date-string here limits that to once-per-calendar-day per process.
_ib_cold_storage_warned_dates: set[str] = set()

# Wave 6 — minimum number of active alpaca-broker trades that must be present
# before an empty Alpaca response is treated as a transient fetch issue rather
# than a legitimate flat-broker state.  Mirrors the IB-side threshold at
# line ~578.  Rationale: 1-2 active trades could plausibly be manually closed
# by the operator between cycles; 3+ is very unlikely to happen simultaneously
# with a broker returning empty — far more likely a transient API issue.
_TRANSIENT_EMPTY_FETCH_THRESHOLD = 3


def _backfill_trade_data(ticker, entry_price, qty, allocation, source, now):
    """Build a trade_data dict for backfilling an orphaned position.

    Creates a minimal shadow_trade record with safe defaults.  The trade
    is tagged with order_type='reconciled' so it's distinguishable from
    normal entries in analytics.

    WARNING: backfilled trades have stop_price=0 and target_1=0 because
    we don't know the original intent.  The operator must manually set
    stop-loss and targets — the warning log makes this visible.
    """
    # Negative shares guard (#188): reject short positions to prevent
    # corruption in a long-only system.  Alpaca can report negative qty
    # if a short position was opened manually or via a margin event.
    if qty <= 0:
        logger.warning(
            "[RECONCILE] Rejecting backfill for %s: qty=%s (long-only system)",
            ticker, qty,
        )
        return None
    return {
        "trade_id": str(uuid4()), "ticker": ticker,
        "direction": "long", "status": "open", "source": source,
        "entry_price": entry_price, "actual_entry_price": entry_price,
        "planned_shares": float(qty), "planned_allocation": allocation,
        "actual_entry_time": now.isoformat(),
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
        "order_type": "reconciled", "recommendation_id": None,
        # Fix #354: Set protective defaults instead of zero.
        # 5% stop / 5% T1 / 10% T2 — enough for exit loop to manage.
        "stop_price": round(entry_price * 0.95, 2) if entry_price > 0 else 0,
        "target_1": round(entry_price * 1.05, 2) if entry_price > 0 else 0,
        "target_2": round(entry_price * 1.10, 2) if entry_price > 0 else 0,
        "max_favorable_excursion": 0, "max_adverse_excursion": 0,
    }


def _resolve_stuck_pnl(
    trade: dict,
    exit_reason: str,
    current_price_provider=None,
):
    """Compute pnl_dollars for a stuck trade being force-closed by reconcile.

    #624 — Pre-fix the inline switch defaulted to `exit_px = entry_px` for
    `timeout` exits, writing literal `pnl=$0.00` to training_examples and
    corrupting the corpus (CLAUDE.md: "Training data quality is #1"). This
    helper returns None when the price source is unknown so the caller can
    write NULL pnl rather than synthesize zero.

    For known reasons (target/stop hits) the planned levels are used.
    For 'timeout' / unknown reasons, the optional `current_price_provider`
    callback is invoked to fetch the last-known market price; if it returns
    None, pnl is None (UNKNOWN).
    """
    entry_px = float(trade.get("actual_entry_price") or trade.get("entry_price") or 0)
    shares = float(trade.get("planned_shares") or trade.get("shares") or 1)
    if entry_px <= 0:
        return None

    if exit_reason in ("stop_hit", "stop_loss"):
        exit_px = trade.get("stop_price")
    elif exit_reason in ("target_1_hit", "take_profit"):
        exit_px = trade.get("target_1")
    elif exit_reason == "target_2_hit":
        exit_px = trade.get("target_2")
    else:
        # timeout, reconciled_stale, or anything else → fetch current price
        if current_price_provider is None:
            current_price_provider = _default_current_price_provider
        try:
            exit_px = current_price_provider(trade.get("ticker"))
        except Exception as exc:
            logger.warning("[RECONCILE] _resolve_stuck_pnl price fetch failed: %s", exc)
            exit_px = None

    if exit_px is None:
        return None
    try:
        exit_px_f = float(exit_px)
    except (TypeError, ValueError):
        return None
    if exit_px_f <= 0:
        return None
    return (exit_px_f - entry_px) * shares


def _default_current_price_provider(ticker: str | None) -> float | None:
    """Default last-bar fetcher used by _resolve_stuck_pnl (#624)."""
    if not ticker:
        return None
    try:
        from src.data_ingestion.market_data import fetch_ohlcv
        data = fetch_ohlcv([ticker], period="5d")
        if ticker in data and not data[ticker].empty:
            return float(data[ticker]["Close"].iloc[-1])
    except Exception as exc:
        logger.debug("[RECONCILE] _default_current_price_provider %s failed: %s", ticker, exc)
    return None


def _estimate_exit_pnl(ticker, entry_px, shares):
    """Estimate exit P&L via last known market price.

    Used when closing stale trades — we don't know the actual exit price
    (the position may have been closed on Alpaca during an outage), so
    we use the last available close price as a best-effort estimate.
    This P&L is approximate and may not match the actual fill price.
    """
    try:
        from src.data_ingestion.market_data import fetch_ohlcv
        data = fetch_ohlcv([ticker], period="5d")
        if ticker in data and not data[ticker].empty:
            exit_price = float(data[ticker]["Close"].iloc[-1])
            pnl = round((exit_price - entry_px) * shares, 2)
            pct = round((exit_price - entry_px) / entry_px * 100, 2)
            return exit_price, pnl, pct
    except Exception as exc:
        logger.warning("[RECONCILE] Failed to estimate exit PnL for %s: %s", ticker, exc)
    return 0.0, 0.0, 0.0


def reconcile_live_trades(
    desk: str = "swing",
    dry_run: bool = False,
    db_path: str = DB_PATH,
) -> dict:
    """Reconcile Alpaca live positions with local shadow_trades.

    Live is swing-only — research desks are forbidden here (parallel to
    place_live_entry's ValueError guard in Task 7b). Research strategies
    are paper-only in Sprint 4 scope.

    Live reconciliation runs with source='live' and has NO safety guard
    (unlike paper trades) because live position discrepancies are more
    urgent and the live API is more reliable than paper.

    Args:
        desk: Trading desk; must be 'swing'. Any other value raises ValueError
            before touching any state.
        dry_run: If True, report discrepancies but don't modify DB.
        db_path: Path to SQLite database.

    Returns:
        {
            "desk": str,
            "alpaca_positions": int,
            "tracked_positions": int,
            "orphaned": [str],
            "stale": [str],
            "backfilled": [str],
            "marked_closed": [str],
        }
    """
    if desk != "swing":
        raise ValueError(
            f"live reconcile only supports swing desk; got desk={desk!r}. "
            "Research strategies are paper-only."
        )

    et = ZoneInfo("America/New_York")
    now = datetime.now(et)

    # Wave 7 — empty-fetch guard mirrors Wave 6 paper-side pattern.
    live_fetch_ok = True
    _live_fetch_error: str | None = None

    # Broker-aware position lookup: IB trades check IB positions, Alpaca checks Alpaca.
    # If IB Gateway is disconnected, skip IB trades (don't mark them stale).
    try:
        from src.trading.broker_factory import get_live_broker
        from src.config import load_config
        broker = get_live_broker(load_config())
        broker_positions = broker.get_all_positions()
        alpaca_positions = [
            {"symbol": p.ticker, "qty": p.quantity, "avg_entry_price": p.avg_cost,
             "current_price": p.current_price, "unrealized_pl": p.unrealized_pnl,
             "market_value": p.market_value}
            for p in broker_positions
        ]
    except Exception as e:
        logger.warning("[RECONCILE-LIVE] Broker unreachable, falling back to Alpaca direct: %s", e)
        try:
            alpaca_positions = get_live_positions(desk=desk)
        except Exception as e2:
            logger.warning("[RECONCILE-LIVE] Alpaca direct fetch also failed: %s", e2)
            alpaca_positions = []
            live_fetch_ok = False
            _live_fetch_error = str(e2)

    alpaca_tickers = {p["symbol"]: p for p in alpaca_positions}

    # STATUS-NARROW: orphan-check requires the broker to ALREADY have
    # this position. 'pending' has not been submitted yet; 'submission_
    # uncertain' is post-submit limbo handled by its own resolver. Only
    # 'open' satisfies the precondition that the broker should hold this
    # position right now (regression caught by
    # test_uncertain_trade_marked_failed_when_alpaca_has_no_position).
    with connect_db(db_path) as conn:
        tracked = conn.execute(
            "SELECT trade_id, ticker FROM shadow_trades "
            "WHERE source = 'live' AND status = 'open'"
        ).fetchall()
    tracked_tickers = {r["ticker"]: r["trade_id"] for r in tracked}

    # Wave 7 — Alpaca transient-empty guard for live path.  Mirror of Wave 6
    # paper-side pattern (reconcile_paper_trades lines ~594-615).
    # If the live broker successfully connected but returned 0 positions while
    # local has _TRANSIENT_EMPTY_FETCH_THRESHOLD or more active live trades,
    # treat the empty response as a transient fetch issue rather than a
    # mass-close signal.
    live_trade_count = len(tracked_tickers)
    if live_fetch_ok and len(alpaca_tickers) == 0 and live_trade_count >= _TRANSIENT_EMPTY_FETCH_THRESHOLD:
        logger.warning(
            "[RECONCILE-LIVE] Live broker returned 0 positions but local has %d active "
            "live trades — likely transient fetch issue, skipping live stale closure",
            live_trade_count,
        )
        live_fetch_ok = False

    # IB-parity warning: emit explicit "skipping stale closure for N" when
    # live_fetch_ok is False and we have active live trades.
    if not live_fetch_ok and live_trade_count > 0:
        logger.warning(
            "[RECONCILE-LIVE] Skipping stale closure for %d live-broker trades "
            "— live fetch failed this cycle", live_trade_count,
        )

    # Find discrepancies.
    # stale detection is suppressed when live_fetch_ok is False — a failed or
    # transient-empty fetch cannot distinguish "position gone" from "API hiccup".
    orphaned = [t for t in alpaca_tickers if t not in tracked_tickers]
    stale = [] if not live_fetch_ok else [t for t in tracked_tickers if t not in alpaca_tickers]

    backfilled = []
    marked_closed = []

    if not dry_run:
        from src.journal.store import insert_shadow_trade, close_shadow_trade

        for ticker in orphaned:
            pos = alpaca_tickers[ticker]
            entry_px = float(pos.get("avg_entry_price", 0))
            qty = float(pos.get("qty", 0))
            trade_data = _backfill_trade_data(
                ticker, entry_px, qty,
                float(pos.get("market_value", 0)), "live", now,
            )
            if trade_data is None:
                continue
            insert_shadow_trade(trade_data, db_path)
            backfilled.append(ticker)
            logger.info(
                "[RECONCILE] Backfilled orphaned position: %s (%.4f shares @ $%.2f)",
                ticker, qty, entry_px,
            )
            logger.info(
                "[RECONCILE] Backfilled %s with protective stop/targets (5%% stop, 5%% T1, 10%% T2)",
                ticker,
            )

        for ticker in stale:
            # Wave 7 — skip stale-marking when live fetch failed this cycle.
            if not live_fetch_ok:
                continue
            trade_id = tracked_tickers[ticker]
            exit_price, pnl_dollars, pnl_pct = 0.0, 0.0, 0.0
            try:
                with connect_db(db_path) as conn:
                    row = conn.execute(
                        "SELECT actual_entry_price, entry_price, planned_shares "
                        "FROM shadow_trades WHERE trade_id = ?",
                        (trade_id,),
                    ).fetchone()
                if row:
                    ep = float(row["actual_entry_price"] or row["entry_price"] or 0)
                    sh = float(row["planned_shares"] or 1)
                    if ep > 0:
                        exit_price, pnl_dollars, pnl_pct = _estimate_exit_pnl(ticker, ep, sh)
            except Exception as exc:
                logger.warning("[RECONCILE] Failed to compute PnL for stale trade %s: %s", trade_id, exc)

            # Task 7: Cancel IB/broker orders before closing stale live trades.
            # Without this, GTC bracket orders remain live on the IB side after
            # the local record is marked closed.
            #
            # RECONCILE-NAMEERR (Sprint 0 Wave 1c): the prior implementation
            # included a dead `for _oid in [... for s in [stale_entry]]:` block
            # that referenced an out-of-scope variable (`stale_entry` is the
            # paper loop var; live's loop var is `ticker`). That NameError
            # was silently swallowed by the surrounding except, so the
            # cancel-before-close logic NEVER executed on live stale closes —
            # GTC bracket orders leaked on the broker side. Removed.
            try:
                from src.trading.broker_factory import get_live_broker as _glb_t7
                from src.config import load_config as _lc_t7
                _broker_t7 = _glb_t7(_lc_t7())
                # Fetch the actual order IDs from the trade row
                with connect_db(db_path) as _conn_t7:
                    _trade_t7 = _conn_t7.execute(
                        "SELECT alpaca_order_id, exit_order_id, ib_child_order_ids "
                        "FROM shadow_trades WHERE trade_id = ?", (trade_id,),
                    ).fetchone()
                if _trade_t7:
                    for _cancel_id in [_trade_t7["alpaca_order_id"], _trade_t7["exit_order_id"]]:
                        if _cancel_id:
                            _broker_t7.cancel_order(str(_cancel_id))
                    if _trade_t7["ib_child_order_ids"]:
                        import json as _json_t7
                        for _child_id in _json_t7.loads(_trade_t7["ib_child_order_ids"]):
                            _broker_t7.cancel_order(_child_id)
            except Exception as _cancel_err:
                logger.warning(
                    "[RECONCILE-LIVE] Pre-close broker cancel failed for "
                    "ticker=%s trade_id=%s: %s — proceeding with local close, "
                    "but broker-side bracket orders may remain open and "
                    "require manual cancellation",
                    ticker, trade_id, _cancel_err,
                )

            close_shadow_trade(
                trade_id=trade_id,
                exit_price=exit_price,
                exit_time=now.isoformat(),
                exit_reason=coerce_exit_reason("reconciled_stale", ticker=ticker),
                pnl_dollars=pnl_dollars,
                pnl_pct=pnl_pct,
                db_path=db_path,
            )
            marked_closed.append(ticker)
            logger.info(
                "[RECONCILE] Marked stale record as closed: %s (trade_id=%s, pnl=%s)",
                ticker, trade_id,
                f"${pnl_dollars:.2f}" if pnl_dollars != 0.0 else "UNKNOWN",
                extra={"ctx": {"event": "stale_close", "ticker": ticker}},
            )
            # Telegram notification for reconciled close
            try:
                from src.notifications.telegram import notify_trade_closed, TradeClosedPayload, is_telegram_enabled
                if is_telegram_enabled():
                    # Compute days held from trade created_at
                    _days = 0
                    try:
                        with connect_db(db_path) as _c:
                            _cr = _c.execute("SELECT created_at FROM shadow_trades WHERE trade_id = ?", (trade_id,)).fetchone()
                            if _cr and _cr["created_at"]:
                                from datetime import datetime as _dt
                                _created = _dt.fromisoformat(_cr["created_at"].replace("Z", "+00:00"))
                                _days = max(0, (now - _created).days)
                    except (ValueError, TypeError):
                        pass
                    notify_trade_closed(TradeClosedPayload(
                        ticker=ticker,
                        pnl_dollars=pnl_dollars,
                        pnl_pct=pnl_pct,
                        exit_reason="reconciled_stale",
                        days_held=_days,
                    ))
            except Exception as _tg_err:
                logger.debug("[RECONCILE] Telegram notify failed for %s: %s", ticker, _tg_err)

    return {
        "desk": desk,
        "alpaca_positions": len(alpaca_positions),
        "tracked_positions": len(tracked),
        "orphaned": orphaned,
        "stale": stale,
        "backfilled": backfilled,
        "marked_closed": marked_closed,
        "error": _live_fetch_error,
    }


def reconcile_paper_trades(
    desk: str = "swing",
    dry_run: bool = False,
    db_path: str = DB_PATH,
) -> dict:
    """Reconcile Alpaca paper positions with local shadow_trades.

    Desk-aware: filters shadow_trades by desk= and routes all Alpaca
    queries through the matching desk's client (via desk= kwarg on
    alpaca_adapter public API functions added in Task 7b).

    Stale paper trades (in DB but not on Alpaca) are auto-closed with
    exit_reason='reconciled_stale' after a 1-hour safety guard to avoid
    false closures from transient Alpaca API blips.

    The 1-hour guard exists because the Alpaca paper API occasionally
    returns incomplete position lists during high-load periods.  Without
    it, the reconciler would close a trade that Alpaca still knows about,
    then the next cycle would re-detect it as an orphan and backfill it.
    This creates ghost duplicate records and corrupts P&L tracking.

    Also resolves stuck exit_failed/exit_pending trades: if Alpaca still
    has the position, revert to 'open'; if Alpaca doesn't, close it with
    estimated P&L based on the exit reason (stop_hit uses stop_price,
    target_1_hit uses target_1, etc.).

    Args:
        desk: 'swing' (default, backward-compatible) or 'research_<id>'.
            Filters shadow_trades rows AND routes Alpaca queries to the
            matching desk's client.
        dry_run: If True, report discrepancies but don't modify DB.
        db_path: Path to SQLite database.

    Returns:
        {
            "desk": str,
            "alpaca_count": int,
            "local_count": int,
            "matched": int,
            "orphaned": [{"ticker": str, "qty": float, "avg_price": float}],
            "stale": [{"ticker": str, "trade_id": str}],
            "discrepancies": [{"ticker": str, "issue": str}],
            "backfilled": [str],
            "marked_closed": [str],
            "error": str | None,
        }
    """
    alpaca_fetch_ok = True
    _alpaca_fetch_error: str | None = None
    try:
        alpaca_positions = get_all_positions(desk=desk)
    except Exception as e:
        logger.warning("[RECONCILE-PAPER] Alpaca API unreachable: %s", e)
        alpaca_positions = []
        alpaca_fetch_ok = False
        _alpaca_fetch_error = str(e)

    # Dual-broker support: also fetch IB paper positions if any trades use IB.
    # Tracks whether the fetch succeeded so we don't falsely close IB trades
    # when IB Gateway is unreachable.  On 2026-04-13 the #419 outage made the
    # reconciler see 0 IB positions and force-close COP/TGT/NEE as stale —
    # those positions actually existed at IB, just couldn't be fetched.
    ib_positions: dict = {}
    ib_fetch_ok = False
    ib_enabled = False
    ib_globally_enabled = False  # SD#41 — distinct from local ib_enabled (cycle attempt flag)
    try:
        from src.config import load_config as _lc_reconcile
        _cfg_r = _lc_reconcile()
        ib_globally_enabled = _cfg_r.get("trading", {}).get("ib_enabled", False)
        # SD#41 — Skip IB connection entirely when cold-stored. TGT/COP brackets
        # resolve naturally on Alpaca side without active reconciler intervention.
        if ib_globally_enabled and _cfg_r.get("live_trading", {}).get("ib", {}).get("paper_routing"):
            ib_enabled = True
            from src.trading.ib_broker import IBBroker
            _ib_cfg = _cfg_r.get("live_trading", {}).get("ib", {})
            _ib_broker = IBBroker(
                host=_ib_cfg.get("host", "127.0.0.1"),
                port=_ib_cfg.get("port", 4002),
                client_id=_ib_cfg.get("client_id", 1) + 20,
                timeout=_ib_cfg.get("timeout", 5),
            )
            try:
                _ib_broker._ensure_connected()
                for p in _ib_broker.get_all_positions():
                    ib_positions[p.ticker] = {
                        "symbol": p.ticker, "qty": p.quantity,
                        "avg_price": p.avg_cost, "current_price": p.current_price,
                    }
                ib_fetch_ok = True
                logger.info("[RECONCILE-PAPER] IB positions fetched: %d", len(ib_positions))
            except Exception as ib_err:
                logger.warning(
                    "[RECONCILE-PAPER] IB Gateway unreachable — IB-broker trades "
                    "will NOT be closed this cycle (prevents false stale-close "
                    "during broker outage): %s", ib_err,
                )
    except Exception as _ib_setup_err:
        logger.warning(
            "[RECONCILE-PAPER] IB setup failed — IB positions will not be "
            "reconciled this cycle: %s", _ib_setup_err,
        )

    et = ZoneInfo("America/New_York")
    now = datetime.now(et)

    alpaca_tickers = {p["symbol"]: p for p in alpaca_positions}

    # Get tracked paper trades (including broker field)
    with connect_db(db_path) as conn:
        conn.row_factory = sqlite3.Row
        # STATUS-NARROW: orphan-check requires the broker to ALREADY have
        # this position. 'pending' has not been submitted yet; 'submission_
        # uncertain' is post-submit limbo handled by its own resolver. Only
        # 'open' satisfies the precondition that the broker should hold
        # this position right now (regression caught by
        # test_uncertain_trade_marked_failed_when_alpaca_has_no_position).
        tracked = conn.execute(
            "SELECT trade_id, ticker, planned_shares, COALESCE(broker, 'alpaca') as broker "
            "FROM shadow_trades "
            "WHERE source = 'paper' AND status = 'open' AND desk = ?",
            (desk,),
        ).fetchall()
    tracked_map = {r["ticker"]: dict(r) for r in tracked}

    # Build combined broker position map per trade
    # Each trade checks its own broker's positions
    _all_broker_tickers = set(alpaca_tickers.keys()) | set(ib_positions.keys())

    orphaned = []
    stale = []
    discrepancies = []
    matched = 0
    backfilled = []
    marked_closed = []
    skipped = []

    # Alpaca has it, local doesn't -> orphaned.
    # Also checks for qty mismatches between Alpaca and local records,
    # which can happen from partial fills or manual position adjustments.
    for ticker, pos in alpaca_tickers.items():
        if ticker not in tracked_map:
            orphaned.append({
                "ticker": ticker,
                "qty": float(pos.get("qty", 0)),
                "avg_price": float(pos.get("avg_entry_price", 0)),
            })
        else:
            # Both have it — check qty
            local_qty = float(tracked_map[ticker].get("planned_shares", 0))
            alpaca_qty = float(pos.get("qty", 0))
            if abs(local_qty - alpaca_qty) > 0.001:
                discrepancies.append({
                    "ticker": ticker,
                    "issue": f"qty mismatch: local={local_qty}, alpaca={alpaca_qty}",
                })
            else:
                matched += 1

    # Local has it, broker doesn't → stale.
    # Broker-unreachable guard: if we could not fetch positions from a broker,
    # any trade on that broker is "unknown this cycle" and NOT marked stale.
    # Also: if IB returned 0 positions while local shows several active IB
    # trades, treat that as a transient fetch issue rather than a mass-close
    # signal — the same pattern that burned us in the 2026-04-13 outage.
    ib_trade_count = sum(1 for rec in tracked_map.values() if rec.get("broker") == "ib")
    if not ib_globally_enabled and ib_trade_count > 0:
        # #628 — Deduplicate to once-per-calendar-day. Without this the same
        # message fires 111×/day for every stuck IB cold-storage trade.
        _today_et = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        if _today_et not in _ib_cold_storage_warned_dates:
            _ib_cold_storage_warned_dates.add(_today_et)
            logger.info(
                "[RECONCILE] %d IB position(s) tracked but trading.ib_enabled=false (SD#41). "
                "Letting brackets resolve naturally.", ib_trade_count,
            )
    if ib_enabled and not ib_fetch_ok and ib_trade_count > 0:
        logger.warning(
            "[RECONCILE-PAPER] Skipping stale closure for %d IB-broker trades "
            "— IB fetch failed this cycle", ib_trade_count,
        )
    if ib_enabled and ib_fetch_ok and len(ib_positions) == 0 and ib_trade_count >= 3:
        logger.warning(
            "[RECONCILE-PAPER] IB returned 0 positions but local has %d active "
            "IB trades — likely transient fetch issue, skipping IB stale closure",
            ib_trade_count,
        )
        ib_fetch_ok = False  # treat as unreachable for this cycle

    # Wave 6 — Alpaca transient-empty guard.  Mirror of the IB pattern above.
    # If Alpaca successfully connected but returned 0 positions while local has
    # _TRANSIENT_EMPTY_FETCH_THRESHOLD or more active alpaca-broker trades, treat
    # the empty response as a transient fetch issue rather than a mass-close signal.
    # This closes the root cause of the 2026-05-04 incident (13 real broker
    # positions falsely marked reconciled_stale in a single cycle).
    alpaca_trade_count = sum(
        1 for rec in tracked_map.values()
        if rec.get("broker", "alpaca") == "alpaca"
    )
    if alpaca_fetch_ok and len(alpaca_tickers) == 0 and alpaca_trade_count >= _TRANSIENT_EMPTY_FETCH_THRESHOLD:
        logger.warning(
            "[RECONCILE-PAPER] Alpaca returned 0 positions but local has %d active "
            "alpaca trades — likely transient fetch issue, skipping Alpaca stale closure",
            alpaca_trade_count,
        )
        alpaca_fetch_ok = False  # treat as unreachable for this cycle

    # Wave 6 — IB-pattern parity: emit explicit "skipping stale closure for N"
    # warning when alpaca is unreachable AND we have active alpaca trades.
    # Mirror of the IB-side log at lines ~574-578.  Operational benefit: incident
    # triage can answer "how many trades did Alpaca preserve during that hiccup?"
    # from a single log line rather than having to infer from absence-of-stale.
    if not alpaca_fetch_ok and alpaca_trade_count > 0:
        logger.warning(
            "[RECONCILE-PAPER] Skipping stale closure for %d alpaca-broker trades "
            "— Alpaca fetch failed this cycle", alpaca_trade_count,
        )

    for ticker, rec in tracked_map.items():
        trade_broker = rec.get("broker", "alpaca")
        if trade_broker == "ib":
            if not ib_fetch_ok:
                # Broker unreachable — leave row open, try again next cycle.
                continue
            if ticker not in ib_positions:
                stale.append({"ticker": ticker, "trade_id": rec["trade_id"]})
            else:
                matched += 1
        else:
            # alpaca-broker trade
            if not alpaca_fetch_ok:
                # Broker unreachable — leave row open, try again next cycle.
                continue
            if ticker not in alpaca_tickers:
                stale.append({"ticker": ticker, "trade_id": rec["trade_id"]})

    if not dry_run:
        from src.journal.store import insert_shadow_trade, close_shadow_trade

        for orph in orphaned:
            # Wave 5 anti-re-backfill guard (closes phantom-position cycle bug, task #18).
            # Don't re-backfill an orphan that was marked reconciled_stale within the last
            # 6 hours — almost certainly an Alpaca paper account phantom position.
            #
            # Scope: Alpaca paper only. The query filters on broker='alpaca' AND source='paper'
            # so the guard does NOT fire for IB-reconciled orphans (per Wave 5 brief: "DO NOT
            # add a similar guard for IB orphans without operator authorization — they may have
            # different semantics"). IB cold-storage handling at lines ~562-583 is a separate
            # mechanism with its own broker-fetch-failure guards.
            with connect_db(db_path) as conn:
                stale_rows = conn.execute(
                    """
                    SELECT actual_exit_time FROM shadow_trades
                    WHERE ticker = ?
                      AND order_type = 'reconciled'
                      AND exit_reason = 'reconciled_stale'
                      AND COALESCE(broker, 'alpaca') = 'alpaca'
                      AND COALESCE(source, 'paper') = 'paper'
                      AND actual_exit_time IS NOT NULL
                    """,
                    (orph["ticker"],),
                ).fetchall()
            recent_stale = False
            for _row in stale_rows:
                try:
                    _exit_t = datetime.fromisoformat(_row["actual_exit_time"])
                    if (now - _exit_t).total_seconds() < 6 * 3600:
                        recent_stale = True
                        break
                except (ValueError, TypeError):
                    pass
            if recent_stale:
                logger.warning(
                    "[RECONCILE-PAPER] Phantom orphan skipped — %s was reconciled_stale "
                    "within last 6 hours (likely Alpaca paper account stuck position; "
                    "operator should clear orders manually). See Wave 5 / #18.",
                    orph["ticker"],
                )
                skipped.append(orph["ticker"])
                continue

            trade_data = _backfill_trade_data(
                orph["ticker"], orph["avg_price"], orph["qty"],
                orph["qty"] * orph["avg_price"], "paper", now,
            )
            if trade_data is None:
                continue
            # Sprint 2 C2-partial: cancel any dangling open orders for the
            # orphan ticker before backfilling the DB row. Without this,
            # the backfilled trade can race with residual bracket legs on
            # Alpaca (a TP/stop leg from the original entry that the
            # executor never tracked), producing the overshoot pattern
            # observed 2026-04-20 (12 shorts matching long-side planned
            # quantities). Uses the existing helper already imported for
            # the stale-close path at line 546.
            try:
                cancelled = cancel_orders_for_ticker(orph["ticker"], desk=desk)
                if cancelled > 0:
                    logger.info(
                        "[RECONCILE-PAPER] Cancelled %d dangling orders for %s "
                        "before backfill",
                        cancelled, orph["ticker"],
                    )
            except Exception as e:
                logger.warning(
                    "[RECONCILE-PAPER] cancel_orders_for_ticker(%s) failed: %s "
                    "— proceeding with backfill",
                    orph["ticker"], e,
                )
            insert_shadow_trade(trade_data, db_path)
            backfilled.append(orph["ticker"])
            logger.info(
                "[RECONCILE-PAPER] Backfilled orphaned position: %s (%.4f shares @ $%.2f)",
                orph["ticker"],
                orph["qty"],
                orph["avg_price"],
            )
            # 2026-05-15 bracket-protection gap fix: backfilled orphans
            # previously lacked broker-side stop/target legs (see
            # docs/audits/2026-05-15-bracket-protection-gap). Auto-attach
            # an OCO so the position is protected on the next reconcile
            # cycle without operator intervention. Wrapped in try/except
            # so a transient broker failure can't abort the reconcile pass.
            try:
                from src.shadow_trading.bracket_attach import (
                    attach_brackets_for_unprotected_positions,
                )
                bracket_result = attach_brackets_for_unprotected_positions(
                    db_path=db_path,
                    ticker_filter=[orph["ticker"]],
                )
                if bracket_result["submitted"]:
                    _, oid, qty = bracket_result["submitted"][0]
                    logger.info(
                        "[RECONCILE-PAPER] Auto-attached OCO for %s (oid=%s, qty=%d)",
                        orph["ticker"], oid, qty,
                    )
                elif bracket_result["skipped"]:
                    logger.info(
                        "[RECONCILE-PAPER] Bracket auto-attach for %s skipped: %s",
                        orph["ticker"], bracket_result["skipped"][0][1],
                    )
                elif bracket_result["failed"]:
                    logger.warning(
                        "[RECONCILE-PAPER] Bracket auto-attach for %s failed: %s",
                        orph["ticker"], bracket_result["failed"][0][1],
                    )
            except Exception as exc:
                logger.warning(
                    "[RECONCILE-PAPER] Bracket auto-attach for %s raised (non-fatal): %s",
                    orph["ticker"], exc,
                )

        # Auto-close stale paper trades with 1-hour safety guard.
        # The guard prevents false closures from transient Alpaca API
        # inconsistencies — see docstring above for full rationale.
        for stale_entry in stale:
            ticker = stale_entry["ticker"]
            trade_id = stale_entry["trade_id"]

            # Safety: skip trades less than 1 hour old to avoid false closures
            # from transient Alpaca API blips
            with connect_db(db_path) as conn:
                trade_row = conn.execute(
                    "SELECT actual_entry_price, entry_price, planned_shares, created_at "
                    "FROM shadow_trades WHERE trade_id = ?",
                    (trade_id,),
                ).fetchone()

            if trade_row:
                created_at_str = trade_row["created_at"] or ""
                try:
                    created = datetime.fromisoformat(created_at_str)
                    if (now - created).total_seconds() < 3600:
                        logger.info(
                            "[RECONCILE-PAPER] Skipping recent trade %s (< 1 hour old)",
                            ticker,
                        )
                        continue
                except (ValueError, TypeError):
                    pass

            # Fix #356: Cancel pending orders before closing to prevent
            # held_for_orders deadlock.
            try:
                cancelled = cancel_orders_for_ticker(ticker, desk=desk)
                if cancelled > 0:
                    import time
                    time.sleep(1)  # Let cancellations settle
            except Exception as cancel_err:
                logger.warning("[RECONCILE-PAPER] Could not cancel orders for %s: %s",
                               ticker, cancel_err)

            exit_price, pnl_dollars, pnl_pct = 0.0, 0.0, 0.0
            if trade_row:
                ep = float(trade_row["actual_entry_price"] or trade_row["entry_price"] or 0)
                sh = float(trade_row["planned_shares"] or 1)
                if ep > 0:
                    exit_price, pnl_dollars, pnl_pct = _estimate_exit_pnl(ticker, ep, sh)

            close_shadow_trade(
                trade_id=trade_id,
                exit_price=exit_price,
                exit_time=now.isoformat(),
                exit_reason=coerce_exit_reason("reconciled_stale", ticker=ticker),
                pnl_dollars=pnl_dollars,
                pnl_pct=pnl_pct,
                db_path=db_path,
            )
            marked_closed.append(ticker)
            logger.info(
                "[RECONCILE-PAPER] Auto-closed stale paper trade: %s (trade_id=%s, pnl=%s)",
                ticker, trade_id,
                f"${pnl_dollars:.2f}" if pnl_dollars != 0.0 else "UNKNOWN",
            )
            # Telegram notification for reconciled close
            try:
                from src.notifications.telegram import notify_trade_closed, TradeClosedPayload, is_telegram_enabled
                if is_telegram_enabled():
                    _days = 0
                    if trade_row and trade_row["created_at"]:
                        try:
                            _created = datetime.fromisoformat(trade_row["created_at"])
                            _days = max(0, (now - _created).days)
                        except (ValueError, TypeError):
                            pass
                    notify_trade_closed(TradeClosedPayload(
                        ticker=ticker,
                        pnl_dollars=pnl_dollars,
                        pnl_pct=pnl_pct,
                        exit_reason="reconciled_stale",
                        days_held=_days,
                    ))
            except Exception as _tg_err:
                logger.debug("[RECONCILE-PAPER] Telegram notify failed for %s: %s", ticker, _tg_err)

    if stale and not marked_closed:
        logger.warning(
            "[RECONCILE-PAPER] %d stale paper trades detected (skipped — too recent): %s",
            len(stale),
            [s["ticker"] for s in stale],
        )

    # Resolve stuck exit_failed / exit_pending trades.
    # These are trades where the exit order was submitted but something
    # went wrong (Alpaca rejection, timeout, network error).  We check
    # if Alpaca still has the position:
    #   - Yes: revert to 'open' (the exit didn't actually happen)
    #   - No:  close with estimated P&L based on exit_reason
    resolved_closed = []
    resolved_reopened = []
    with connect_db(db_path) as conn:
        conn.row_factory = sqlite3.Row
        # STATUS-NARROW: this is the stuck-exit recovery path — it must
        # only target trades whose exit attempt explicitly failed or is
        # pending. Broadening to ACTIVE_STATUSES would scan healthy 'open'
        # trades and misclassify them as needing recovery.
        stuck = conn.execute(
            "SELECT trade_id, ticker, exit_reason, actual_entry_price, "
            "       entry_price, planned_shares, stop_price, target_1, target_2 "
            "FROM shadow_trades "
            "WHERE source = 'paper' AND status IN ('exit_failed', 'exit_pending') "
            "AND desk = ?",
            (desk,),
        ).fetchall()

    if stuck and not dry_run:
        for row in stuck:
            ticker = row["ticker"]
            trade_id = row["trade_id"]
            if ticker in alpaca_tickers:
                # 2026-04-14 regression guard: before reverting a stuck
                # exit_failed/exit_pending trade to 'open', verify the
                # position is in the EXPECTED direction. A long-only system
                # seeing a short (qty < 0) or flat (qty == 0) means the exit
                # SELL filled (possibly multiple times). Reverting to 'open'
                # would re-trigger the exit loop and extend the short.
                alpaca_qty = 0.0
                try:
                    alpaca_qty = float(alpaca_tickers[ticker].get("qty") or 0)
                except (TypeError, ValueError):
                    alpaca_qty = 0.0
                try:
                    planned_shares = float(row["planned_shares"] or 0)
                except (TypeError, ValueError):
                    planned_shares = 0.0
                if alpaca_qty <= 0:
                    with connect_db(db_path) as conn:
                        conn.execute(
                            "UPDATE shadow_trades SET status = 'needs_manual_review', "
                            "exit_reason = ?, updated_at = ? "
                            "WHERE trade_id = ?",
                            (coerce_exit_reason("exit_overshoot_detected", ticker=ticker),
                             now.isoformat(), trade_id),
                        )
                    logger.error(
                        "[RECONCILE-PAPER] Exit overshoot on %s (alpaca_qty=%.0f) — "
                        "halted for manual review", ticker, alpaca_qty,
                    )
                    continue
                # D2 fix (sprint fix/paper-exit-qty-asymmetry): the broker has
                # a position but fewer shares than the trade's planned_shares.
                # This happens when a prior exit partially filled (126/130) and
                # Alpaca canceled the residual. Reverting to 'open' with the
                # original planned_shares re-triggers the qty-mismatch retry
                # loop (CVS `00330e8d` ran 17+ cycles on 2026-04-21 before
                # manual quarantine). Surface as needs_manual_review with a
                # distinct reason so cleanup tooling can tell these apart from
                # overshoot zombies.
                if 0 < alpaca_qty < planned_shares:
                    with connect_db(db_path) as conn:
                        conn.execute(
                            "UPDATE shadow_trades SET status = 'needs_manual_review', "
                            "exit_reason = ?, updated_at = ? "
                            "WHERE trade_id = ?",
                            (coerce_exit_reason("qty_mismatch_partial_fill", ticker=ticker),
                             now.isoformat(), trade_id),
                        )
                    logger.warning(
                        "[RECONCILE-PAPER] Qty mismatch on %s (alpaca_qty=%.0f, "
                        "planned=%.0f) — halted for manual review",
                        ticker, alpaca_qty, planned_shares,
                    )
                    continue
                with connect_db(db_path) as conn:
                    conn.execute(
                        "UPDATE shadow_trades SET status = 'open', exit_reason = NULL, "
                        "updated_at = ? WHERE trade_id = ?",
                        (now.isoformat(), trade_id),
                    )
                resolved_reopened.append(ticker)
                logger.info("[RECONCILE-PAPER] Reverted premature exit to open: %s", ticker)
            else:
                trade_dict = dict(row)
                reason = trade_dict.get("exit_reason") or "reconciled_stale"
                # #624 — Use the helper so timeout closures fetch the actual
                # current price instead of defaulting to entry_px (which wrote
                # literal pnl=$0.00 into training_examples and corrupted the
                # corpus). When current price is unknown the helper returns
                # None — we then write NULL pnl rather than synthesize 0.
                pnl_dollars_calc = _resolve_stuck_pnl(trade_dict, exit_reason=reason)
                entry_px = float(trade_dict.get("actual_entry_price") or trade_dict.get("entry_price") or 0)
                shares = float(trade_dict.get("planned_shares") or 1)

                if pnl_dollars_calc is None:
                    # Unknown PnL — store NULL not 0.0; close_shadow_trade will
                    # log a warning so the operator sees the unknown closure.
                    exit_px = 0.0
                    pnl_dollars = None
                    pnl_pct = None
                    logger.warning(
                        "[RECONCILE-PAPER] Closing %s with UNKNOWN pnl (no price source for %s)",
                        ticker, reason,
                    )
                else:
                    pnl_dollars = round(pnl_dollars_calc, 2)
                    # Reconstruct exit_px from pnl for the close call.
                    if shares > 0 and entry_px > 0:
                        exit_px = round(pnl_dollars_calc / shares + entry_px, 4)
                        pnl_pct = round((exit_px - entry_px) / entry_px * 100, 2)
                    else:
                        exit_px = entry_px
                        pnl_pct = 0.0

                close_shadow_trade(
                    trade_id=trade_id, exit_price=exit_px,
                    exit_time=now.isoformat(),
                    exit_reason=coerce_exit_reason(reason, ticker=ticker),
                    pnl_dollars=pnl_dollars or 0.0, pnl_pct=pnl_pct or 0.0, db_path=db_path,
                )
                resolved_closed.append(ticker)
                logger.info(
                    "[RECONCILE-PAPER] Closed stuck %s trade: %s (pnl=%s)",
                    reason, ticker,
                    f"${pnl_dollars:.2f}" if pnl_dollars is not None else "UNKNOWN",
                )
    elif stuck:
        logger.info(
            "[RECONCILE-PAPER] %d stuck exit_failed/exit_pending trades found (dry_run): %s",
            len(stuck), [dict(r)["ticker"] for r in stuck],
        )

    # Resolve submission_uncertain trades: entries where we don't
    # know if Alpaca received the order (network error during submission).
    with connect_db(db_path) as conn:
        conn.row_factory = sqlite3.Row
        # STATUS-NARROW: post-submit verification recovery path — must
        # only target trades whose submission verification failed (the
        # submission_uncertain limbo state). Broadening would scan all
        # active trades and misroute them to recovery.
        uncertain = conn.execute(
            "SELECT trade_id, ticker, entry_price, planned_shares "
            "FROM shadow_trades "
            "WHERE source = 'paper' AND status = 'submission_uncertain' "
            "AND desk = ?",
            (desk,),
        ).fetchall()

    if uncertain and not dry_run:
        for row in uncertain:
            ticker = row["ticker"]
            trade_id = row["trade_id"]
            if ticker in alpaca_tickers:
                # Alpaca has it — promote to open
                with connect_db(db_path) as conn:
                    conn.execute(
                        "UPDATE shadow_trades SET status = 'open', updated_at = ? "
                        "WHERE trade_id = ?", (now.isoformat(), trade_id),
                    )
                logger.info("[RECONCILE-PAPER] Promoted uncertain trade to open: %s", ticker)
            else:
                # Alpaca doesn't have it — close as failed
                with connect_db(db_path) as conn:
                    conn.execute(
                        "UPDATE shadow_trades SET status = 'failed', updated_at = ? "
                        "WHERE trade_id = ?", (now.isoformat(), trade_id),
                    )
                logger.info("[RECONCILE-PAPER] Closed uncertain trade as failed: %s", ticker)

    return {
        "desk": desk,
        "alpaca_count": len(alpaca_positions),
        "local_count": len(tracked),
        "matched": matched,
        "orphaned": orphaned,
        "stale": stale,
        "discrepancies": discrepancies,
        "backfilled": backfilled,
        "skipped": skipped,
        "marked_closed": marked_closed,
        "resolved_closed": resolved_closed,
        "resolved_reopened": resolved_reopened,
        "error": _alpaca_fetch_error,
    }
