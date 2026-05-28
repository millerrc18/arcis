"""Order-lifecycle helpers and exit-monitor + live-entry orchestration.

Extracted from ``executor.py`` during the Phase 5 PR-C T10 refactor. Houses:

  - Status sets and constants: ``FILLED_ORDER_STATUSES``,
    ``PENDING_ORDER_STATUSES``, ``_MAX_EXIT_RETRIES``,
    ``_CANCEL_TERMINAL_NO_SUBMIT``.
  - Status predicates: ``_is_filled_status``, ``_is_pending_status``.
  - Exit-submission helper: ``_submit_exit_order``.
  - Lifecycle helpers: ``_handle_pre_exit_cancel``,
    ``_next_exit_retry_count``, ``_should_abandon_exit``,
    ``_sync_exit_qty``, ``_close_from_broker_fill``, ``_retry_exit``.
  - The two top-level orchestration entry points that depend on the above:
    ``check_and_manage_open_trades`` (exit-monitor loop) and
    ``open_live_trade`` (real-money entry).

Late-binding pattern for test-patchability
==========================================
``check_and_manage_open_trades``, ``open_live_trade``, ``_retry_exit``, and
``_close_from_broker_fill`` historically lived in ``executor.py``. Many
tests + ``scripts/daily_repo_audit.py`` use
``unittest.mock.patch("src.shadow_trading.executor.<name>")`` to patch
symbols (``_submit_exit_order``, ``close_shadow_trade``,
``update_shadow_trade``, ``get_open_shadow_trades``,
``_get_current_price_safe``, ``_check_close_milestones``,
``_check_loss_streak``, ``load_config``, etc.) the moved functions call
into.

If those functions resolved the names against this module's namespace,
the ``executor.<name>`` patches would be bypassed. To preserve the
existing patch contract verbatim, each such call site does a lazy
``from src.shadow_trading import executor as _exec`` and reads
``_exec.<name>`` — an attribute lookup that resolves at call time, so the
patched value is honoured. The lazy import (inside the function body)
also avoids the circular-import that a module-top
``from src.shadow_trading import executor`` would create with the
``executor`` -> ``order_lifecycle`` re-export edge.

Called by: shadow_trading.executor (re-export only; real callers reach functions via executor)
Calls: config, data_ingestion.market_data, journal.store, notifications, notifications.telegram, shadow_trading._status_sql, shadow_trading.broker_exception_logger, shadow_trading.exit_reason, shadow_trading.models, shadow_trading.qty_mismatch, shadow_trading.reconciliation_engine, utils.db
Owns tables: none (reads/writes shadow_trades via journal.store)
Config keys: bootcamp, enabled, live_trading, max_open_positions, max_positions, max_price, min_score, risk, shadow_trading, starting_capital, timeout_days
Tests: tests/test_expanded_notifications.py, tests/test_executor_import.py, tests/test_live_trading.py
"""

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH, load_config
from src.utils.db import connect_db
from src.journal.store import (
    get_open_shadow_trades,
    insert_shadow_trade,
    update_shadow_trade,
    close_shadow_trade,
    update_recommendation,
)
from src.models import TradePacket
from src.shadow_trading._status_sql import (
    active_in_clause,
    terminal_in_clause,
)
from src.shadow_trading.broker_exception_logger import log_and_persist
from src.shadow_trading.exit_reason import coerce_exit_reason
from src.shadow_trading.models import ShadowTrade
from src.shadow_trading.qty_mismatch import parse_qty_mismatch, should_abort_retry
from src.notifications import safe_send
from src.notifications.telegram import send_telegram

logger = logging.getLogger(__name__)

# Alpaca order status sets — used by exit monitoring to decide whether to
# close the trade record (filled) or wait for broker (pending).
# GOTCHA: Alpaca SDK enums stringify as "OrderStatus.filled" — the adapter's
# _strip_enum() (Fix for #248) normalizes these before they reach here.
# Fix for #278: Removed "partially_filled" — partial exits must NOT be treated as
# fully closed. A 50/100 share exit recorded as fully closed orphans the remaining
# shares on Alpaca with no tracking, and the P&L is calculated on full shares
# (wrong). Partial fills are now handled explicitly in check_and_manage_open_trades.
FILLED_ORDER_STATUSES = {"filled", "closed"}
PENDING_ORDER_STATUSES = {"new", "accepted", "pending_new", "accepted_for_bidding", "held"}

# Fix for #196: Cap exit retries to prevent infinite exit order spam.
# After 3 failures, mark as exit_abandoned for reconciliation to handle.
_MAX_EXIT_RETRIES = 3

# #609 — Terminal states a cancel response can report when the order raced
# the cancel and filled (or partially filled) at the broker. When we see one
# of these, the executor MUST NOT submit another SELL — the position is
# already gone (or partially gone). Pre-fix, the cancel return value was
# dropped at executor.py:1575 → executor proceeded to submit, opening shorts
# (C 4/21, AMD 4/22).
_CANCEL_TERMINAL_NO_SUBMIT = ("filled", "partially_filled")


def _is_filled_status(status: str | None) -> bool:
    """Return True when a broker order status represents a completed exit."""
    return str(status or "").lower() in FILLED_ORDER_STATUSES


def _is_pending_status(status: str | None) -> bool:
    """Return True when an exit order exists but has not filled yet."""
    return str(status or "").lower() in PENDING_ORDER_STATUSES


def _submit_exit_order(trade: dict, shares: int) -> dict:
    """Submit the appropriate broker exit order for a paper or live trade.

    Live trades route through the broker factory (IB or Alpaca, config-driven).
    Paper trades continue calling alpaca_adapter directly (unchanged).
    """
    if trade.get("source") == "live":
        # Route through broker abstraction for live trades
        from src.trading.broker_factory import get_live_broker
        broker = get_live_broker(load_config())
        result = broker.place_exit(trade["ticker"], 0)
        return {"order_id": result.order_id, "status": result.status,
                "filled_avg_price": result.filled_avg_price,
                "filled_qty": result.filled_qty}

    from src.shadow_trading.alpaca_adapter import place_paper_exit

    return place_paper_exit(trade["ticker"], shares)


def _handle_pre_exit_cancel(cancel_result: dict | None) -> bool:
    """Inspect a `cancel_paper_order` response and signal whether the caller
    should SKIP submitting a new SELL (because the order already executed).

    Returns True when the cancel race detected a terminal state that means
    "the position is already moving / gone" — caller must NOT submit.
    """
    if not isinstance(cancel_result, dict):
        return False
    return cancel_result.get("terminal_state") in _CANCEL_TERMINAL_NO_SUBMIT


def _next_exit_retry_count(trade: dict) -> int:
    """Compute the next exit_retry_count for a trade about to be marked
    exit_failed. Centralizes the increment so both _retry_exit and the
    first-time exit path stay consistent (#610)."""
    current = trade.get("exit_retry_count")
    try:
        return int(current or 0) + 1
    except (TypeError, ValueError):
        return 1


def _should_abandon_exit(retry_count: int) -> bool:
    """True when retry_count has hit the abandonment threshold (#196 / #610)."""
    return retry_count >= _MAX_EXIT_RETRIES


def _sync_exit_qty(
    ticker: str,
    requested_shares: int,
    broker_positions: dict[str, float] | None,
) -> tuple[int, str | None]:
    """Sync the requested exit quantity against the broker's current position.

    D3 fix (sprint fix/paper-exit-qty-asymmetry): before submitting a paper
    exit, verify the broker still has the position and at least the
    requested quantity. Prevents two failure modes:

      1. Phantom exit (C 2026-04-21 09:43): DB row says status='open' with
         planned_shares=65, but Alpaca's bracket target leg already filled
         and closed the position. Submitting a sell against qty=0 → Alpaca
         accepts as sell_to_open → opens a short.
      2. Qty mismatch (CVS 2026-04-21 09:48): DB says planned_shares=130,
         Alpaca has 4 after a partial-fill exit. Submitting 130 → Alpaca
         rejects "insufficient qty" → reconcile reverts to open → loop.

    Args:
        ticker: The symbol to exit.
        requested_shares: What the caller wants to sell (DB planned_shares).
        broker_positions: Cached dict of symbol → current qty at the broker,
            built once per exit-check cycle at check_and_manage_open_trades.
            None means cache unavailable — fall back to requested_shares for
            backward compatibility.

    Returns:
        (actual_qty_to_submit, skip_reason).
        - If broker_positions is None: (requested_shares, None) — legacy.
        - If broker_qty <= 0: (0, "position_already_closed") — caller must skip.
        - If 0 < broker_qty < requested: (broker_qty, None) — clip to broker.
        - If broker_qty >= requested: (requested_shares, None) — unchanged.
    """
    if broker_positions is None:
        return requested_shares, None
    try:
        broker_qty = float(broker_positions.get(ticker, 0))
    except (TypeError, ValueError):
        broker_qty = 0.0
    if broker_qty <= 0:
        return 0, "position_already_closed"
    return min(requested_shares, int(broker_qty)), None


def _close_from_broker_fill(trade: dict, filled_order: dict, db_path: str) -> None:
    """Close a shadow trade using a broker-reported fill rather than submitting
    a new exit order.

    Called when we detect a prior exit order already reached terminal 'filled'
    state at the broker (either via pre-check or by the cancel race). Without
    this path, _retry_exit would blindly re-submit a SELL and extend a short
    position — the 2026-04-14 NVDA/GOOGL feedback loop.

    v0.36.28 SAFETY GUARD: refuse to close-from-fill when the supplied order is
    a BUY. The BUY's filled_avg_price is the ENTRY price, not an exit. Writing
    it as exit_price creates the phantom-close pattern (commit baa8466d,
    2026-04-13 → fixed 2026-05-19). Callers that fall back to the bracket-
    parent order id when `exit_order_id` is None (sites at lines 1430-1434
    and 2007-2009 elsewhere in this file) would otherwise hand us the BUY
    entry order — this guard catches them.
    """
    from src.shadow_trading import executor as _exec

    side = str(filled_order.get("side") or "").lower()
    if "sell" not in side:
        logger.error(
            "[CLOSE_FROM_FILL] Refused: order side=%r is not SELL (order_id=%s, ticker=%s). "
            "Writing a BUY-fill price as exit_price would create the v0.36.28 phantom-close "
            "pattern. Caller passed the wrong order — likely fell back to alpaca_order_id "
            "(the bracket parent BUY) when exit_order_id was None.",
            side or "<missing>",
            filled_order.get("order_id"),
            trade.get("ticker"),
        )
        return

    fill_price = float(filled_order.get("filled_avg_price") or 0)
    entry_price = float(trade.get("actual_entry_price") or trade.get("entry_price") or 0)
    shares = int(float(trade.get("planned_shares") or trade.get("shares") or 0))
    pnl_dollars = (fill_price - entry_price) * shares if entry_price else 0.0
    pnl_pct = ((fill_price - entry_price) / entry_price * 100) if entry_price else 0.0
    exit_time = (filled_order.get("filled_at")
                 or datetime.now(ZoneInfo("America/New_York")).isoformat())
    _exec.close_shadow_trade(
        trade["trade_id"],
        exit_price=fill_price,
        exit_time=exit_time,
        exit_reason=coerce_exit_reason(trade.get("exit_reason") or "late_fill_reconciled", ticker=trade.get("ticker", "")),
        pnl_dollars=round(pnl_dollars, 2),
        pnl_pct=round(pnl_pct, 2),
        db_path=db_path,
    )


def _retry_exit(
    trade: dict,
    db_path: str = DB_PATH,
    broker_positions: dict[str, float] | None = None,
) -> None:
    """Retry exit for trades stuck in exit_pending or exit_failed.

    Cancels any pending exit order before resubmitting. Gives up after
    _MAX_EXIT_RETRIES attempts and marks the trade as exit_abandoned
    for reconciliation to handle.

    Fix for #196: Without this, duplicate exit orders were being placed
    every scan cycle for stuck trades, sometimes causing Alpaca rejections.

    2026-04-14 hardening: before canceling and resubmitting, check whether
    the prior exit order already filled at the broker (two paths). If it
    did, close the trade from the broker fill data and return — resubmitting
    would create duplicate SELLs and inflate a short position.

    D3 fix (sprint fix/paper-exit-qty-asymmetry): `broker_positions` is the
    cache populated in check_and_manage_open_trades. When passed, the retry
    uses `_sync_exit_qty` to resize or skip the exit against actual broker
    state, preventing the CVS-style qty-mismatch retry loop.
    """
    from src.shadow_trading import executor as _exec
    from src.shadow_trading.alpaca_adapter import cancel_paper_order, get_order_status

    ticker = trade["ticker"]
    retry_count = int(trade.get("exit_retry_count") or 0)

    # Enforce max retry limit
    if retry_count >= _MAX_EXIT_RETRIES:
        logger.error("[RETRY] Max retries (%d) reached for %s — abandoning exit",
                     _MAX_EXIT_RETRIES, ticker)
        _exec.update_shadow_trade(trade["trade_id"], {"status": "exit_abandoned"}, db_path)
        return

    pending_order_id = trade.get("exit_order_id") or trade.get("alpaca_order_id")

    # Background-fill detection path 1 (pre-check): ask the broker if the
    # prior order already filled before we touch it. Cheapest path.
    if pending_order_id and trade.get("source") != "live":
        try:
            prior = get_order_status(pending_order_id)
            if prior and _is_filled_status(prior.get("status")):
                logger.info("[RETRY] Late fill detected for %s — reconciling from broker",
                            ticker)
                _exec._close_from_broker_fill(trade, prior, db_path)
                return
        except Exception as e:
            logger.warning("[RETRY] Pre-check failed for %s: %s (falling back to cancel)",
                           ticker, e)

    # Cancel any existing pending exit order before resubmitting
    # Task 5: Use broker factory for live/IB trades, Alpaca direct for paper
    if pending_order_id:
        if trade.get("source") == "live":
            try:
                from src.trading.broker_factory import get_live_broker as _glb_t5
                _glb_t5(load_config()).cancel_order(pending_order_id)
            except Exception as _e_t5:
                _exec.log_and_persist(
                    ticker=ticker,
                    operation="cancel_order",
                    broker="alpaca_live",
                    exc=_e_t5,
                    recoverable=False,
                    outcome="persisted",
                )
                logger.warning("[RETRY] Live cancel failed for %s: %s", ticker, _e_t5)
        else:
            cancel_result = cancel_paper_order(pending_order_id)
            # Background-fill detection path 2 (cancel race): order filled
            # in the window between our pre-check and cancel attempt — the
            # broker tells us via "already in 'filled' state". Re-fetch and
            # close from fill data.
            if (isinstance(cancel_result, dict)
                    and cancel_result.get("terminal_state") == "filled"):
                try:
                    filled = get_order_status(pending_order_id)
                    if filled and _is_filled_status(filled.get("status")):
                        logger.info(
                            "[RETRY] Cancel raced fill for %s — reconciling from broker",
                            ticker,
                        )
                        _exec._close_from_broker_fill(trade, filled, db_path)
                        return
                except Exception as e:
                    logger.warning(
                        "[RETRY] Post-cancel fill fetch failed for %s: %s",
                        ticker, e,
                    )
        time.sleep(1)  # Brief pause for broker to process cancellation

    # Increment retry counter
    _exec.update_shadow_trade(trade["trade_id"],
                              {"exit_retry_count": retry_count + 1}, db_path)

    shares = int(float(trade.get("shares") or trade.get("planned_shares") or 0))

    # D3 sync: don't retry against stale qty. If broker no longer holds the
    # position (qty <= 0), skip the submit and let reconcile close the trade.
    actual_qty, skip_reason = _exec._sync_exit_qty(ticker, shares, broker_positions)
    if skip_reason:
        logger.warning(
            "[RETRY] %s position already closed at broker (qty=0) — "
            "marking exit_pending:%s for reconcile to finalize",
            ticker, skip_reason,
        )
        _exec.update_shadow_trade(
            trade["trade_id"],
            {"status": "exit_pending", "exit_reason": coerce_exit_reason(skip_reason, ticker=ticker)},
            db_path,
        )
        return
    if actual_qty != shares:
        logger.warning(
            "[RETRY] %s qty sync: planned=%d, broker=%d, submitting %d",
            ticker, shares, int(broker_positions.get(ticker, 0)) if broker_positions else shares, actual_qty,
        )
        shares = actual_qty

    try:
        exit_result = _exec._submit_exit_order(trade, shares)
        # Fix #360: Store exit order ID immediately for audit trail
        if isinstance(exit_result, dict) and exit_result.get("order_id"):
            _exec.update_shadow_trade(trade["trade_id"],
                                      {"exit_order_id": exit_result["order_id"]}, db_path)
        exit_status = exit_result.get("status") if isinstance(exit_result, dict) else None
        if _is_filled_status(exit_status):
            fill_price = float(exit_result.get("filled_avg_price", 0))
            entry_price = float(trade.get("actual_entry_price") or trade.get("entry_price") or 0)
            pnl_dollars = (fill_price - entry_price) * shares if entry_price else 0
            pnl_pct = ((fill_price - entry_price) / entry_price * 100) if entry_price else 0
            _exec.close_shadow_trade(
                trade["trade_id"],
                exit_price=fill_price,
                exit_time=datetime.now(ZoneInfo("America/New_York")).isoformat(),
                exit_reason=coerce_exit_reason(trade.get("exit_reason") or "retry_exit", ticker=ticker),
                pnl_dollars=round(pnl_dollars, 2),
                pnl_pct=round(pnl_pct, 2),
                db_path=db_path,
            )
            logger.info("[RETRY] Successfully closed %s on retry", ticker)
        elif _is_pending_status(exit_status):
            logger.info("[RETRY] Exit still pending for %s (retry %d/%d)",
                        ticker, retry_count + 1, _MAX_EXIT_RETRIES)
        else:
            _exec.update_shadow_trade(trade["trade_id"], {"status": "exit_failed"}, db_path)
            logger.warning("[RETRY] Exit retry failed for %s (status=%s)", ticker, exit_status)
    except Exception as e:
        qty_pair = parse_qty_mismatch(str(e))
        if qty_pair is not None:
            requested, available = qty_pair
            consecutive = retry_count + 1
            persist_outcome = (
                "alert_qty_mismatch" if should_abort_retry(consecutive) else "persisted"
            )
            _exec.log_and_persist(
                ticker=ticker,
                operation="place_exit",
                broker="alpaca_paper",
                exc=e,
                recoverable=False,
                retry_count=consecutive,
                outcome=persist_outcome,
            )
            if should_abort_retry(consecutive):
                logger.error(
                    "[QTY_MISMATCH] %s requested=%d available=%d — aborting retry, "
                    "marking exit_failed (qty_mismatch_partial_fill)",
                    ticker, requested, available,
                )
                _exec.update_shadow_trade(
                    trade["trade_id"],
                    {
                        "status": "exit_failed",
                        "exit_reason": "qty_mismatch_partial_fill",
                    },
                    db_path,
                )
            else:
                logger.warning(
                    "[QTY_MISMATCH] %s requested=%d available=%d (consecutive=%d/%d)",
                    ticker, requested, available, consecutive, 3,
                )
                _exec.update_shadow_trade(trade["trade_id"], {"status": "exit_failed"}, db_path)
        else:
            # Invariant (#758): exit_retry_count was already incremented at the
            # "Increment retry counter" block above (before the try/except). Any
            # exception from _submit_exit_order reaches this branch only after
            # that increment, so the counter correctly reflects this attempt.
            # If reconcile resets exit_failed → open, the next scan will see
            # retry_count = N+1 and will continue toward MAX_EXIT_RETRIES.
            _exec.log_and_persist(
                ticker=ticker,
                operation="place_exit",
                broker="alpaca_paper",
                exc=e,
                recoverable=False,
                outcome="persisted",
            )
            _exec.update_shadow_trade(trade["trade_id"], {"status": "exit_failed"}, db_path)
            logger.error("[RETRY] Exit retry exception for %s: %s", ticker, e)


def check_and_manage_open_trades(
    db_path: str = DB_PATH,
    source_filter: str | None = None,
) -> list[dict]:
    """Check all open shadow trades and manage exits.

    Args:
        source_filter: If set, only manage trades with this source (e.g., "live", "paper").

    Returns a list of action dicts describing what happened.
    """
    from src.shadow_trading import executor as _exec

    config = _exec.load_config()
    shadow_cfg = config.get("shadow_trading", {})
    # Fix #245: timeout_days can be an int, a string (from YAML quoting or
    # SQLite TEXT affinity), or a dict {"default": 15, "pullback": 7} when
    # edited via the dashboard override API.  Resolve to int to prevent
    # "'<=' not supported between instances of 'str' and 'int'" at the
    # `days_open >= timeout_days` comparison below.
    _raw_timeout = shadow_cfg.get("timeout_days", 15)
    if isinstance(_raw_timeout, dict):
        _raw_timeout = _raw_timeout.get("default", 15)
    config_timeout_days = int(_raw_timeout)

    open_trades = _exec.get_open_shadow_trades(db_path)
    if source_filter:
        open_trades = [t for t in open_trades if t.get("source") == source_filter]
    actions = []
    _exit_attempts = 0
    _exit_failures = 0

    et = ZoneInfo("America/New_York")
    now = datetime.now(et)

    # Track price fetch failures for Alpaca health monitoring (#102)
    _price_total = 0
    _price_failures = 0

    # Pre-fetch broker positions for existence checking (single API call).
    # #320: use live broker positions when source_filter="live", paper otherwise.
    #
    # D3 fix (sprint fix/paper-exit-qty-asymmetry): also capture qty per ticker
    # into `_alpaca_positions` so `_sync_exit_qty` can resize or skip exits
    # when the broker's actual qty diverges from DB planned_shares. `_alpaca_tickers`
    # is preserved as a set-view for the existing existence-check at line ~1398.
    _alpaca_positions: dict[str, float] = {}
    _alpaca_tickers: set[str] = set()
    try:
        if source_filter == "live":
            from src.trading.broker_factory import get_live_broker
            live_broker = get_live_broker(_exec.load_config())
            if live_broker:
                _live_positions = live_broker.get_all_positions()
                _alpaca_positions = {p.ticker: float(p.quantity) for p in _live_positions}
        else:
            from src.shadow_trading.alpaca_adapter import get_all_positions
            _alpaca_positions = {
                p["symbol"]: float(p.get("qty") or 0)
                for p in get_all_positions()
            }
        _alpaca_tickers = set(_alpaca_positions.keys())
    except Exception as e:
        _broker_name = "alpaca_live" if source_filter == "live" else "alpaca_paper"
        _exec.log_and_persist(
            ticker="(all)",
            operation="fetch_positions",
            broker=_broker_name,
            exc=e,
            recoverable=True,
            outcome="persisted",
        )

    for trade in open_trades:
        # Retry exit for failed exits instead of skipping
        if trade.get("status") in ("exit_pending", "exit_failed"):
            _exec._retry_exit(trade, db_path, broker_positions=_alpaca_positions)
            continue

        ticker = trade["ticker"]
        entry_price = float(trade.get("actual_entry_price") or trade.get("entry_price") or 0)
        stop_price = float(trade.get("stop_price") or 0)
        target_1 = float(trade.get("target_1") or 0)
        target_2 = float(trade.get("target_2") or 0)

        if entry_price <= 0:
            continue

        # Get current price — track failures (#102)
        _price_total += 1
        current_price = _exec._get_current_price_safe(ticker)
        if current_price is None:
            _price_failures += 1
            continue

        # Calculate unrealized P&L
        shares = int(float(trade.get("planned_shares") or 1))
        unrealized_pnl = (current_price - entry_price) * shares
        unrealized_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

        # Update MFE/MAE
        mfe = float(trade.get("max_favorable_excursion") or 0)
        mae = float(trade.get("max_adverse_excursion") or 0)

        price_move = current_price - entry_price
        # DB-FINAL Task 1: track when MFE peaks. Only update the day/timestamp
        # on a *new high* so flat or adverse days preserve the true peak.
        mfe_increased = price_move > mfe
        if mfe_increased:
            mfe = price_move
        if price_move < mae:
            mae = price_move

        # Calculate days open
        entry_time_str = trade.get("actual_entry_time") or trade.get("created_at", "")
        try:
            entry_time = datetime.fromisoformat(entry_time_str)
            days_open = (now - entry_time).days
        except (ValueError, TypeError):
            days_open = 999  # Force timeout if timestamp unparseable
            logger.warning("[EXECUTOR] Could not parse entry time '%s' for trade %s — defaulting to days_open=999",
                           entry_time_str, trade.get("trade_id"))

        if mfe_increased:
            mfe_days = days_open
            mfe_ts = now.isoformat()
        else:
            mfe_days = trade.get("time_to_mfe_days")
            mfe_ts = trade.get("mfe_timestamp")

        # Update trade with current MFE/MAE and duration
        _exec.update_shadow_trade(
            trade["trade_id"],
            {
                "max_favorable_excursion": mfe,
                "max_adverse_excursion": mae,
                "duration_days": days_open,
                "time_to_mfe_days": mfe_days,
                "mfe_timestamp": mfe_ts,
            },
            db_path,
        )

        # ═══ Strategy-aware exit: Mean Reversion RSI exit ═══
        # MR trades have different exit logic than pullback trades: they exit
        # when RSI reverts to neutral (not via bracket stops/targets). MR trades
        # also have shorter holding periods (default 5 days) with a hard timeout.
        # The `continue` after MR exit skips the bracket check below.
        if trade.get("strategy_type") == "mean_reversion":
            try:
                from src.features.mean_reversion import compute_mr_exit_signal
                _mr_ohlcv = _exec._get_recent_ohlcv_safe(ticker, days=10)
                if _mr_ohlcv is not None:
                    mr_exit = compute_mr_exit_signal(
                        ticker, _mr_ohlcv, entry_price, config)
                    if mr_exit:
                        mr_exit_price = mr_exit["exit_price"]
                        pnl = (mr_exit_price - entry_price) * shares
                        pnl_pct = ((mr_exit_price - entry_price) / entry_price * 100) if entry_price else 0
                        # Fix for #271: was missing exit_time and pnl_pct — caused TypeError
                        # silently swallowed by the except block at line 688.
                        _exec.close_shadow_trade(
                            trade["trade_id"],
                            exit_price=mr_exit_price,
                            exit_time=datetime.now(ZoneInfo("America/New_York")).isoformat(),
                            exit_reason=coerce_exit_reason(mr_exit["exit_reason"], ticker=ticker),
                            pnl_dollars=round(pnl, 2),
                            pnl_pct=round(pnl_pct, 2),
                            db_path=db_path,
                        )
                        actions.append({
                            "ticker": ticker,
                            "type": "closed",
                            "action": mr_exit["exit_reason"],
                            "pnl_dollars": pnl,
                        })
                        # Attribution: link MR exit outcome
                        _mr_rec_id = trade.get("recommendation_id")
                        if _mr_rec_id:
                            try:
                                from src.attribution.logger import link_trade_outcome
                                link_trade_outcome(_mr_rec_id, "win" if pnl_pct > 0 else "loss", round(pnl_pct, 2))
                            except Exception as e:
                                logger.warning("[EXECUTOR] MR exit attribution logging failed: %s", e)
                        continue  # Skip bracket logic
            except Exception as e:
                logger.debug("[EXECUTOR] MR exit check failed for %s: %s", ticker, e)

            # MR timeout exit
            mr_cfg = config.get("strategies", {}).get("mean_reversion", {})
            # Fix #245: Cast to int — config values may arrive as strings.
            mr_timeout = int(mr_cfg.get("holding_period", 5))
            if days_open >= mr_timeout:
                pnl = (current_price - entry_price) * shares
                pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price else 0
                # Fix for #271: was missing exit_time and pnl_pct
                _exec.close_shadow_trade(
                    trade["trade_id"],
                    exit_price=current_price,
                    exit_time=datetime.now(ZoneInfo("America/New_York")).isoformat(),
                    exit_reason=coerce_exit_reason("mr_timeout", ticker=ticker),
                    pnl_dollars=round(pnl, 2),
                    pnl_pct=round(pnl_pct, 2),
                    db_path=db_path,
                )
                actions.append({
                    "ticker": ticker,
                    "type": "closed",
                    "action": "mr_timeout",
                    "pnl_dollars": pnl,
                })
                # Attribution: link MR timeout outcome
                _mr_rec_id = trade.get("recommendation_id")
                if _mr_rec_id:
                    try:
                        from src.attribution.logger import link_trade_outcome
                        link_trade_outcome(_mr_rec_id, "win" if pnl_pct > 0 else "loss", round(pnl_pct, 2))
                    except Exception as e:
                        logger.warning("[EXECUTOR] MR timeout attribution logging failed: %s", e)
                continue

        # Capture signal price BEFORE bracket detection can overwrite current_price.
        # B1 Risk R2: bracket detection sets current_price = leg_price (fill price);
        # if signal_exit is assigned after that, slippage is trivially 0.
        _signal_exit_pre_bracket = current_price

        # For bracket orders, check Alpaca for exit fills.
        # Strategy Decision #18: Bracket orders have server-side stop-loss and
        # take-profit legs that fire automatically. We check Alpaca's order status
        # to detect if a leg filled, rather than relying solely on price polling.
        # This handles overnight gaps and fast moves that price polling would miss.
        bracket_exit = False
        exit_reason = None
        if trade.get("order_type") == "bracket" and trade.get("alpaca_order_id"):
            try:
                # Task 4: Route bracket status check through broker factory for
                # live/IB trades, keep Alpaca direct for paper. IB bracket fills
                # were previously invisible because get_order_status called Alpaca
                # unconditionally.
                if trade.get("source") == "live":
                    from src.trading.broker_factory import get_live_broker as _glb_t4
                    _broker_t4 = _glb_t4(_exec.load_config())
                    try:
                        _bo = _broker_t4.get_order_status(trade["alpaca_order_id"])
                        order_status = {
                            "status": _bo.status,
                            "filled_avg_price": _bo.filled_avg_price,
                            "filled_qty": _bo.filled_qty,
                            "legs": [],
                        }
                    except ValueError:
                        order_status = {"status": "unknown", "legs": []}

                    # Check IB child orders for bracket leg fills
                    if trade.get("ib_child_order_ids"):
                        import json as _json_t4
                        child_ids = _json_t4.loads(trade["ib_child_order_ids"])
                        for idx, child_id in enumerate(child_ids):
                            try:
                                child_order = _broker_t4.get_order_status(child_id)
                                if child_order.status == "filled":
                                    current_price = child_order.filled_avg_price
                                    bracket_exit = True
                                    # child_ids[0] = take_profit, child_ids[1] = stop_loss
                                    exit_reason = coerce_exit_reason("take_profit" if idx == 0 else "stop_loss", ticker=ticker)
                                    break
                            except ValueError:
                                continue
                else:
                    from src.shadow_trading.alpaca_adapter import get_order_status
                    order_status = get_order_status(trade["alpaca_order_id"])

                if not bracket_exit:
                    # v0.36.28: the parent-status-filled branch was removed here.
                    # For an Alpaca OCO bracket, the "parent" IS the BUY entry
                    # order — its `filled` status is the NORMAL state of every
                    # open bracket position, not an exit signal. Pre-fix the
                    # code treated this as bracket_exit=True with
                    # current_price=entry_fill_price, gating out the timeout-
                    # exit SELL submission below at line 1954 (`if not
                    # bracket_exit:`). Result: shadow_trade marked closed with
                    # phantom pnl, Alpaca position stayed open, reconciler
                    # later discovered it as an orphan. The legs check below
                    # correctly detects real exits (stop/target SELL legs
                    # actually firing).
                    legs = order_status.get("legs", [])
                    for leg in legs:
                        leg_status = leg.get("status", "")
                        if leg_status in ("filled", "partially_filled"):
                            leg_price = leg.get("filled_avg_price")
                            if leg_price:
                                current_price = leg_price
                                bracket_exit = True
                                leg_type = leg.get("order_type", "")
                                if leg_type == "stop" or leg.get("stop_price"):
                                    exit_reason = coerce_exit_reason("stop_loss", ticker=ticker)
                                elif leg_type == "limit" or leg.get("limit_price"):
                                    exit_reason = coerce_exit_reason("take_profit", ticker=ticker)
                                break
            except Exception as e:
                logger.warning("[SHADOW] Bracket order status check failed for %s: %s — falling back to price polling", ticker, e)

        # Position existence check — log-only alarm for reconciliation
        if not bracket_exit and _alpaca_tickers and ticker not in _alpaca_tickers:
            logger.warning(
                "[EXECUTOR] %s not in Alpaca positions (trade_id=%s) "
                "— will be caught by next reconciliation cycle",
                ticker, trade.get("trade_id"),
            )

        # Check exit conditions (bracket leg detection may have already set exit_reason)
        if not bracket_exit:
            exit_reason = None
        # Sprint 0 / Wave 2b — per-trade timeout_days honored.
        # Track 1.5 / B8 persists the LLM's Expected Holding Period on the
        # row at line 1126. Before this fix the timeout comparison only used
        # the config global (config_timeout_days), so the per-trade value
        # was dead data. Fall back to config when the row carries None /
        # unparseable / 0.
        _trade_timeout_raw = trade.get("timeout_days")
        try:
            _trade_timeout_int = int(_trade_timeout_raw) if _trade_timeout_raw not in (None, "") else 0
        except (TypeError, ValueError):
            _trade_timeout_int = 0
        effective_timeout_days = _trade_timeout_int if _trade_timeout_int > 0 else config_timeout_days
        if exit_reason is None:
            if current_price <= stop_price and stop_price > 0:
                exit_reason = coerce_exit_reason("stop_hit", ticker=ticker)
            elif current_price >= target_2 and target_2 > 0:
                exit_reason = coerce_exit_reason("target_2_hit", ticker=ticker)
            elif current_price >= target_1 and target_1 > 0:
                exit_reason = coerce_exit_reason("target_1_hit", ticker=ticker)
            elif days_open >= effective_timeout_days:
                exit_reason = coerce_exit_reason("timeout", ticker=ticker)

        if exit_reason:
            # #345: If the entry order never filled, cancel it instead of selling
            entry_status = trade.get("status", "")
            entry_order_id = trade.get("alpaca_order_id")
            if entry_status in ("pending", "pending_entry") and entry_order_id:
                try:
                    from src.shadow_trading.alpaca_adapter import cancel_paper_order
                    cancel_paper_order(entry_order_id)
                    logger.info(
                        "[EXIT] Cancelled unfilled entry order for %s (order=%s, reason=%s)",
                        ticker, entry_order_id, exit_reason,
                    )
                except Exception as cancel_err:
                    logger.warning("[EXIT] Failed to cancel entry order for %s: %s", ticker, cancel_err)
                _exec.update_shadow_trade(
                    trade["trade_id"],
                    {
                        "status": "cancelled",
                        "exit_reason": coerce_exit_reason("entry_unfilled", ticker=ticker),
                    },
                    db_path,
                )
                actions.append({
                    "type": "cancelled_unfilled",
                    "ticker": ticker,
                    "trade_id": trade["trade_id"],
                    "reason": exit_reason,
                })
                continue

            # Exit slippage tracking — signal captured before bracket detection (B1 R2)
            signal_exit = _signal_exit_pre_bracket if _signal_exit_pre_bracket > 0 else current_price
            exit_slippage_bps = None

            if not bracket_exit:
                # D3 sync: verify broker has a position with sufficient qty
                # before submitting the sell. Prevents phantom exits (qty=0)
                # and qty-mismatch retries (planned > broker).
                _exit_qty, _skip_reason = _exec._sync_exit_qty(
                    ticker, shares, _alpaca_positions,
                )
                if _skip_reason:
                    logger.warning(
                        "[EXIT] %s position already closed at broker "
                        "(qty=0) — marking exit_pending:%s for reconcile",
                        ticker, _skip_reason,
                    )
                    _exec.update_shadow_trade(
                        trade["trade_id"],
                        {"status": "exit_pending", "exit_reason": _skip_reason},
                        db_path,
                    )
                    actions.append({
                        "type": "exit_skipped_no_position",
                        "ticker": ticker,
                        "trade_id": trade["trade_id"],
                        "exit_reason_trigger": exit_reason,
                    })
                    continue
                if _exit_qty != shares:
                    logger.warning(
                        "[EXIT] %s qty sync: planned=%d, broker=%d, submitting %d",
                        ticker, shares,
                        int(_alpaca_positions.get(ticker, 0)) if _alpaca_positions else shares,
                        _exit_qty,
                    )
                    shares = _exit_qty

                # Cancel any stale pending order before initial exit attempt (#310)
                _pending_oid = trade.get("exit_order_id") or trade.get("alpaca_order_id")
                if _pending_oid:
                    try:
                        from src.shadow_trading.alpaca_adapter import (
                            cancel_paper_order, get_order_status,
                        )
                        _cancel_result = cancel_paper_order(_pending_oid)
                        # #608/#609 — If the cancel raced a fill, the order is
                        # already executed at the broker. Do NOT submit another
                        # SELL — that's how C 4/21 and AMD 4/22 went short. Route
                        # to _close_from_broker_fill instead.
                        if _handle_pre_exit_cancel(_cancel_result):
                            logger.info(
                                "[EXIT] %s cancel raced fill (terminal_state=%s) "
                                "— closing from broker fill, not submitting new SELL",
                                ticker, _cancel_result.get("terminal_state"),
                            )
                            try:
                                _filled = get_order_status(_pending_oid)
                                if _filled and _is_filled_status(_filled.get("status")):
                                    _exec._close_from_broker_fill(trade, _filled, db_path)
                            except Exception as _fetch_err:
                                logger.warning(
                                    "[EXIT] Post-cancel fill fetch failed for %s: %s",
                                    ticker, _fetch_err,
                                )
                            actions.append({
                                "type": "exit_skipped_cancel_race",
                                "ticker": ticker,
                                "trade_id": trade["trade_id"],
                                "exit_reason_trigger": exit_reason,
                            })
                            continue
                        time.sleep(0.5)
                    except Exception as e:
                        _exec.log_and_persist(
                            ticker=ticker,
                            operation="cancel_order",
                            broker="alpaca_paper",
                            exc=e,
                            recoverable=True,
                            outcome="persisted",
                        )
                        logger.error(
                            "[EXECUTOR] Stale exit order cancellation failed for %s "
                            "(order_id=%s): %s — proceeding to new exit submission; "
                            "stale order may still be live at broker",
                            ticker, _pending_oid, e,
                        )

                try:
                    exit_result = _exec._submit_exit_order(trade, shares)
                    # Fix #360: Store exit order ID immediately for audit trail
                    if isinstance(exit_result, dict) and exit_result.get("order_id"):
                        _exec.update_shadow_trade(trade["trade_id"],
                                                  {"exit_order_id": exit_result["order_id"]}, db_path)
                except Exception as e:
                    # #610 — Increment exit_retry_count on first-time failure too.
                    # Pre-fix, this path wrote status=exit_failed without bumping
                    # the counter; reconciler then flipped status back to open;
                    # next scan re-entered THIS path; counter never grew. CVS
                    # retried 33× on 4/21 without ever hitting MAX_EXIT_RETRIES.
                    _exec.log_and_persist(
                        ticker=ticker,
                        operation="place_exit",
                        broker="alpaca_paper",
                        exc=e,
                        recoverable=False,
                        outcome="persisted",
                    )
                    _next_retry = _next_exit_retry_count(trade)
                    _failed_status = "exit_abandoned" if _should_abandon_exit(_next_retry) else "exit_failed"
                    logger.error(
                        "[EXIT] Broker exit failed for %s — marking %s (retry=%d): %s",
                        ticker, _failed_status, _next_retry, e,
                        extra={"ctx": {
                            "event": "exit_failed", "ticker": ticker,
                            "trade_id": trade["trade_id"], "error": type(e).__name__,
                            "exit_retry_count": _next_retry,
                        }},
                    )
                    # Sprint 0 / Wave 2b — exception type is already captured in
                    # the structured [BROKER_EXCEPTION] log above; the
                    # exit_reason field is controlled vocabulary, so we route
                    # the canonical token through coerce instead of stuffing
                    # the dynamic class name in (which previously coerced to
                    # 'unknown' and lost the broker-vs-other distinction).
                    _exec.update_shadow_trade(
                        trade["trade_id"],
                        {
                            "status": _failed_status,
                            "exit_reason": coerce_exit_reason("broker_exception", ticker=ticker),
                            "exit_retry_count": _next_retry,
                        },
                        db_path,
                    )
                    _exit_attempts += 1
                    _exit_failures += 1
                    # Circuit breaker: halt exits if majority failing (#310)
                    if _exit_failures > 3 and _exit_failures > _exit_attempts * 0.5:
                        logger.critical(
                            "[EXIT] Circuit breaker: %d/%d exits failed — halting remaining exits",
                            _exit_failures, _exit_attempts)
                        try:
                            _exec.send_telegram(
                                f"\U0001f6a8 EXIT CIRCUIT BREAKER: {_exit_failures}/{_exit_attempts} "
                                f"exits failed this cycle. Remaining exits paused."
                            )
                        except Exception as e:
                            logger.warning("[EXECUTOR] Exit circuit breaker notification failed: %s", e)
                        break
                    continue

                exit_status = exit_result.get("status") if isinstance(exit_result, dict) else None
                if _is_filled_status(exit_status):
                    fill_exit = exit_result.get("filled_avg_price") if isinstance(exit_result, dict) else None
                    if fill_exit is not None:
                        current_price = float(fill_exit)
                        if signal_exit and signal_exit > 0:
                            exit_slippage_bps = (
                                (current_price - signal_exit) / signal_exit * 10000
                            )
                            logger.info(
                                "[SLIPPAGE] %s exit: signal=$%.2f, fill=$%.2f, slippage=%.1f bps",
                                ticker,
                                signal_exit,
                                current_price,
                                exit_slippage_bps,
                            )
                elif str(exit_status or "").lower() == "partially_filled":
                    # Fix for #278: Handle partial fills explicitly.
                    # Record the partial fill but keep the trade open. The next
                    # cycle will see remaining shares and try to exit again.
                    filled_qty = int(float(exit_result.get("filled_qty", 0) or 0))
                    total_qty = shares
                    remaining = max(0, total_qty - filled_qty)
                    logger.warning(
                        "[EXIT] Partial fill for %s: %d/%d shares filled. %d remaining.",
                        ticker, filled_qty, total_qty, remaining,
                    )
                    if remaining > 0:
                        _exec.update_shadow_trade(
                            trade["trade_id"],
                            {
                                "status": "open",
                                "exit_reason": coerce_exit_reason("partial_exit", ticker=ticker),
                                "actual_shares": remaining,
                            },
                            db_path,
                        )
                    else:
                        # All shares filled despite "partially_filled" status
                        fill_exit = exit_result.get("filled_avg_price")
                        if fill_exit is not None:
                            current_price = float(fill_exit)
                    actions.append({
                        "type": "partial_exit",
                        "ticker": ticker,
                        "filled": filled_qty,
                        "remaining": remaining,
                        "trade_id": trade["trade_id"],
                    })
                    if remaining > 0:
                        continue
                    # If remaining == 0, fall through to close the trade
                elif _is_pending_status(exit_status):
                    _exec.update_shadow_trade(
                        trade["trade_id"],
                        {"status": "exit_pending", "exit_reason": exit_reason},
                        db_path,
                    )
                    logger.warning(
                        "[EXIT] Order submitted but not filled for %s: %s",
                        ticker,
                        exit_result.get("order_id"),
                    )
                    actions.append(
                        {
                            "type": "exit_pending",
                            "ticker": ticker,
                            "exit_reason": exit_reason,
                            "trade_id": trade["trade_id"],
                        }
                    )
                    continue
                else:
                    logger.error(
                        "[EXIT] Broker exit failed for %s — marking exit_failed (status=%s)",
                        ticker,
                        exit_status,
                        extra={"ctx": {"event": "exit_failed", "ticker": ticker, "trade_id": trade["trade_id"], "status": str(exit_status)}},
                    )
                    _exec.update_shadow_trade(
                        trade["trade_id"],
                        {"status": "exit_failed", "exit_reason": exit_reason},
                        db_path,
                    )
                    try:
                        _exec.send_telegram(
                            f"⚠️ Exit order FAILED for {ticker} — will retry next cycle"
                        )
                    except Exception as exc:
                        logger.warning("[EXIT] Telegram notification failed for %s: %s", ticker, exc)
                    _exit_attempts += 1
                    _exit_failures += 1
                    continue

            _exit_attempts += 1  # Successful exit attempt
            pnl_dollars = (current_price - entry_price) * shares
            pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

            _exec.close_shadow_trade(
                trade["trade_id"],
                exit_price=current_price,
                exit_time=now.isoformat(),
                exit_reason=exit_reason,
                pnl_dollars=round(pnl_dollars, 2),
                pnl_pct=round(pnl_pct, 2),
                db_path=db_path,
            )
            logger.info(
                "[EXIT] Closed %s — P&L $%.2f (%.1f%%)", ticker, pnl_dollars, pnl_pct,
                extra={"ctx": {"event": "exit_success", "ticker": ticker,
                               "trade_id": trade["trade_id"],
                               "pnl_dollars": round(pnl_dollars, 2),
                               "pnl_pct": round(pnl_pct, 2),
                               "exit_reason": exit_reason}},
            )

            # Also update final MFE/MAE, duration, and exit slippage on the closed trade
            _exec.update_shadow_trade(
                trade["trade_id"],
                {
                    "max_favorable_excursion": mfe,
                    "max_adverse_excursion": mae,
                    "duration_days": days_open,
                    "signal_exit_price": signal_exit if signal_exit and signal_exit > 0 else None,
                    "exit_slippage_bps": exit_slippage_bps,
                },
                db_path,
            )
            logger.info(
                "[SLIPPAGE] %s exit persisted: signal=$%.2f, slippage=%s bps",
                ticker,
                signal_exit or 0.0,
                f"{exit_slippage_bps:.1f}" if exit_slippage_bps is not None else "NULL",
            )

            # Update journal recommendation and generate postmortem
            rec_id = trade.get("recommendation_id")
            if rec_id:
                from src.journal.store import get_recommendation_by_id
                rec = get_recommendation_by_id(rec_id, db_path)

                # Build combined trade data for postmortem
                trade_for_postmortem = dict(trade)
                trade_for_postmortem.update({
                    "actual_exit_price": current_price,
                    "exit_reason": exit_reason,
                    "pnl_dollars": round(pnl_dollars, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "max_favorable_excursion": mfe,
                    "max_adverse_excursion": mae,
                    "duration_days": days_open,
                })
                if rec:
                    trade_for_postmortem["thesis_text"] = rec.get("thesis_text", "")
                    trade_for_postmortem["atr"] = rec.get("atr", 0)

                # Generate postmortem (rule-based, then LLM-enhanced)
                from src.evaluation.postmortem import generate_postmortem, determine_lesson_tag
                from src.llm.postmortem_writer import enhance_postmortem_with_llm
                rule_based_postmortem = generate_postmortem(trade_for_postmortem)
                postmortem_text = enhance_postmortem_with_llm(trade_for_postmortem, rule_based_postmortem)
                lesson_tag = determine_lesson_tag(trade_for_postmortem)

                _exec.update_recommendation(
                    rec_id,
                    {
                        "shadow_exit_price": current_price,
                        "shadow_exit_time": now.isoformat(),
                        "shadow_pnl_dollars": round(pnl_dollars, 2),
                        "shadow_pnl_pct": round(pnl_pct, 2),
                        "max_favorable_excursion": mfe,
                        "max_adverse_excursion": mae,
                        "shadow_duration_days": days_open,
                        "thesis_success": 1 if pnl_dollars > 0 else 0,
                        "assistant_postmortem": postmortem_text,
                        "lesson_tag": lesson_tag,
                    },
                    db_path,
                )

            action = {
                "type": "closed",
                "ticker": ticker,
                "exit_reason": exit_reason,
                "pnl_dollars": round(pnl_dollars, 2),
                "pnl_pct": round(pnl_pct, 2),
                "days_held": days_open,
                "trade_id": trade["trade_id"],
                "recommendation_id": rec_id,
            }
            actions.append(action)

            # Attribution: link trade outcome to attribution record
            if rec_id:
                try:
                    from src.attribution.logger import link_trade_outcome
                    outcome = "win" if pnl_pct > 0 else "loss"
                    link_trade_outcome(rec_id, outcome, round(pnl_pct, 2))
                except Exception as e:
                    logger.debug("[ATTRIBUTION] link_trade_outcome failed for %s: %s", ticker, e)

            logger.info(
                "[SHADOW] Closed %s: %s | P&L=$%+.2f (%+.1f%%) | held %d days",
                ticker, exit_reason, pnl_dollars, pnl_pct, days_open,
            )

            # Enriched context — fields are all nullable in shadow_trades;
            # notify_trade_closed renders only what's present.
            from src.notifications.telegram import TradeClosedPayload
            safe_send(
                "trade_closed",
                payload=TradeClosedPayload(
                    ticker=ticker,
                    pnl_dollars=pnl_dollars,
                    pnl_pct=pnl_pct,
                    exit_reason=exit_reason,
                    days_held=days_open,
                    source=trade.get("source", "paper"),
                    sector=trade.get("realized_sector"),
                    regime_at_entry=trade.get("regime_at_entry"),
                    regime_at_exit=trade.get("regime_at_exit"),
                    mfe_pct=trade.get("max_favorable_excursion"),
                    mae_pct=trade.get("max_adverse_excursion"),
                    excess_return=trade.get("excess_return"),
                    spy_return_over_hold=trade.get("spy_return_over_hold"),
                    drawdown_from_mfe=trade.get("drawdown_from_mfe"),
                    entry_slippage_bps=trade.get("entry_slippage_bps"),
                    exit_slippage_bps=trade.get("exit_slippage_bps"),
                ),
            )

            # 1F. Check for trade close milestones
            _exec._check_close_milestones(db_path)

            # 1G. Check for loss streak
            _exec._check_loss_streak(db_path)

    # Alert if >50% of price checks failed in this cycle (#102).
    # WHY 50% threshold: individual failures happen (ticker delisted, API blip).
    # Mass failures indicate an Alpaca outage, which needs immediate attention
    # because it means all exit monitoring is blind.
    if _price_total > 0 and _price_failures / _price_total > 0.5:
        logger.warning(
            "[EXECUTOR] Price fetch failure rate %.0f%% (%d/%d) — possible Alpaca outage",
            _price_failures / _price_total * 100, _price_failures, _price_total,
        )
        try:
            _exec.send_telegram(
                f"PRICE FETCH ALERT: {_price_failures}/{_price_total} price checks failed "
                f"({_price_failures / _price_total * 100:.0f}%). Possible Alpaca API outage."
            )
        except Exception as _tg_err:
            logger.warning("[EXECUTOR] Price failure Telegram alert failed: %s", _tg_err)

    return actions


def open_live_trade(
    recommendation_id: str,
    packet: TradePacket,
    features: dict,
    db_path: str = DB_PATH,
) -> str | None:
    """Open a LIVE trade for a packet-worthy recommendation.

    Uses live_trading config section with separate risk parameters.
    Includes additional safety guards beyond paper trading:
    - Capital guard: halt if equity < 50% of starting capital
    - Daily loss limit: halt if daily P&L < -5% of capital
    - LLM commentary required (no template fallback)
    - First scan of day (9:30 AM) is skipped (handled by caller)

    WHY separate from open_shadow_trade: Live trades use notional ordering
    (dollar amounts for fractional shares), different risk parameters,
    and stricter safety guards. The code paths diverge enough that
    combining them would create a fragile if/else maze.

    Returns trade_id on success, None on failure.
    """
    from src.shadow_trading import executor as _exec

    config = _exec.load_config()
    live_cfg = config.get("live_trading", {})

    if not live_cfg.get("enabled", False):
        logger.info("[LIVE] Live trading disabled, skipping")
        return None

    # Fix for #272: LLM output validation — same as paper path (lines 140-154).
    # Live trades MUST pass the same hallucination checks as paper trades.
    # Without this, a hallucinated ticker or nonsensical price from the LLM
    # could be submitted as a real-money order.
    try:
        from src.llm.validator import validate_llm_output
        is_valid, reason = validate_llm_output(packet, features, config)
        if not is_valid:
            logger.warning("[LIVE][VALIDATE] Trade rejected for %s: %s", packet.ticker, reason)
            return None
    except ImportError:
        logger.error("[LIVE][VALIDATE] Validator import failed for %s — REJECTING live trade", packet.ticker)
        return None
    except Exception as e:
        logger.error("[LIVE][VALIDATE] Validation failed for %s: %s — REJECTING live trade", packet.ticker, e)
        return None

    # Fix for #272: Risk governor check — same as paper path (lines 156-188).
    # Live trades MUST pass all 8 risk governor checks including the kill switch,
    # sector concentration, VIX circuit breaker, and drawdown-adjusted sizing.
    try:
        from src.risk.governor import RiskGovernor, get_portfolio_state
        governor = RiskGovernor(config)
        portfolio = get_portfolio_state(db_path)
        # Fix for #267: Default to 0.5 (fail-conservative) when multiplier
        # features are missing, not 1.0 (no penalty). Same logic as shadow path.
        tl_mult = features.get("traffic_light_multiplier")
        if tl_mult is None:
            tl_mult = 0.5
            logger.warning("[LIVE][RISK] traffic_light_multiplier missing for %s — defaulting to 0.5 (conservative)", packet.ticker)
        event_mult = _exec._resolve_event_risk_multiplier(features, packet.ticker, path="LIVE")
        check = governor.check_trade(
            packet.ticker,
            packet.position_sizing.allocation_dollars,
            features,
            portfolio,
            traffic_light_multiplier=tl_mult,
            event_risk_multiplier=event_mult,
        )
        if not check["approved"]:
            reason = check.get("rejection_reason", "Risk check failed")
            logger.warning("[LIVE][RISK] Trade rejected for %s: %s", packet.ticker, reason)
            return None
    except ImportError:
        logger.error("[LIVE][RISK] Governor import failed for %s — REJECTING live trade", packet.ticker)
        return None
    except Exception as e:
        from src.risk.governor import GovernorInputMissingError
        if isinstance(e, GovernorInputMissingError):
            logger.critical(
                "[LIVE][RISK] GovernorInputMissingError for %s: %s — REJECTING live trade",
                packet.ticker, e,
            )
            try:
                _exec.send_telegram(
                    f"🚨 CRITICAL: GovernorInputMissingError for {packet.ticker}\n"
                    f"Required risk key missing — live trade REJECTED.\n"
                    f"Detail: {e}"
                )
            except Exception as _tg_err:
                logger.warning("[LIVE][RISK] Telegram alert failed: %s", _tg_err)
        else:
            logger.error(
                "[LIVE][RISK] Governor check failed for %s: %s — REJECTING live trade",
                packet.ticker, e,
            )
        return None

    # Safety guard: Must have LLM commentary (not template fallback)
    llm_conviction = getattr(packet, 'llm_conviction', None)
    if llm_conviction is None:
        logger.warning("[LIVE] No LLM conviction — skipping live trade for %s", packet.ticker)
        return None

    # Safety guard: min_score filter
    min_score = live_cfg.get("min_score")
    if min_score is not None:
        score = features.get("_score", 0)
        if score < min_score:
            logger.info("[LIVE] Score %.1f below min_score %s for %s", score, min_score, packet.ticker)
            return None

    # Safety guard: max_price filter
    max_price = live_cfg.get("max_price")
    entry_price = _exec._parse_price(packet.entry_zone)
    if max_price is not None and entry_price > max_price:
        logger.info("[LIVE] Price $%.2f above max_price $%s for %s", entry_price, max_price, packet.ticker)
        return None

    # Safety guard: Capital check — halt if equity < 50% of starting capital
    starting_capital = live_cfg.get("starting_capital", 100)
    try:
        # Route through broker factory — works for both IB and Alpaca
        from src.trading.broker_factory import get_live_broker
        _broker = get_live_broker(config)
        _acct = _broker.get_account()
        live_acct = {
            "equity": _acct.equity,
            "cash": _acct.cash,
            "buying_power": _acct.buying_power,
            "portfolio_value": _acct.portfolio_value,
        }
        live_equity = live_acct.get("equity", 0)

        if live_equity < starting_capital * 0.50:
            logger.warning(
                "[LIVE] CAPITAL GUARD: Equity $%.2f < 50%% of starting $%.2f — HALTING",
                live_equity, starting_capital,
            )
            safe_send(
                "risk_alert",
                alert_type="LIVE CAPITAL GUARD",
                detail=f"Live equity ${live_equity:.2f} below 50% of starting ${starting_capital:.2f}. "
                       f"Live trading halted.",
            )
            return None
    except Exception as e:
        logger.warning("[LIVE] Could not check live account: %s — skipping", e)
        return None

    # Fix for #275: Daily loss guard — uses today's REALIZED losses from closed trades
    # plus unrealized P&L on today's open trades. The old version used all-time
    # unrealized P&L from all open trades (including positions opened weeks ago),
    # which meant a single old losing position could permanently block new entries,
    # while today's realized losses from closed trades were invisible.
    try:
        import sqlite3 as _sql275
        today_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        _t_frag275, _t_params275 = terminal_in_clause()
        _a_frag275, _a_params275 = active_in_clause()
        with _sql275.connect(db_path, timeout=10) as _conn275:
            _conn275.row_factory = _sql275.Row
            # Today's realized losses from closed live trades
            _realized_row = _conn275.execute(
                "SELECT COALESCE(SUM(pnl_dollars), 0) as total FROM shadow_trades "
                f"WHERE status IN ({_t_frag275}) AND source='live' AND actual_exit_time LIKE ?"
                " AND COALESCE(quarantined, 0) = 0",
                (*_t_params275, f"{today_str}%"),
            ).fetchone()
            today_realized = float(_realized_row["total"]) if _realized_row else 0.0

            # Today's unrealized P&L on live trades opened today
            _open_today = _conn275.execute(
                "SELECT ticker, actual_entry_price, entry_price, planned_shares "
                f"FROM shadow_trades WHERE status IN ({_a_frag275}) AND source='live' AND created_at LIKE ?"
                " AND COALESCE(quarantined, 0) = 0",
                (*_a_params275, f"{today_str}%"),
            ).fetchall()

        today_unrealized = 0.0
        for t in _open_today:
            t_entry = float(t["actual_entry_price"] or t["entry_price"] or 0)
            if t_entry > 0:
                current = _exec._get_current_price_safe(t["ticker"])
                if current:
                    today_unrealized += (current - t_entry) * int(float(t["planned_shares"] or 1))

        daily_live_pnl = today_realized + today_unrealized

        if starting_capital > 0 and daily_live_pnl < -(starting_capital * 0.05):
            logger.warning(
                "[LIVE] DAILY LOSS GUARD: Today's live P&L $%.2f (realized $%.2f + unrealized $%.2f) "
                "exceeds -5%% of $%.2f — HALTING for day",
                daily_live_pnl, today_realized, today_unrealized, starting_capital,
            )
            safe_send(
                "risk_alert",
                alert_type="LIVE DAILY LOSS LIMIT",
                detail=f"Live daily P&L ${daily_live_pnl:.2f} (realized ${today_realized:.2f} "
                       f"+ unrealized ${today_unrealized:.2f}) exceeds -5% of ${starting_capital:.2f}. "
                       f"No more live trades today.",
            )
            return None
    except Exception as e:
        logger.error("[LIVE] Daily loss guard failed for %s — REJECTING trade: %s", packet.ticker, e)
        return None

    # Position limit + duplicate check (live-specific) — single DB call for both.
    # #759: DB errors here must fire a Telegram critical alert; a locked DB blocks
    # ALL new live entries without operator awareness if only an ERROR log is emitted.
    ticker = packet.ticker
    max_positions = live_cfg.get("max_open_positions", 2)
    try:
        open_live_trades = [
            t for t in _exec.get_open_shadow_trades(db_path)
            if t.get("source") == "live"
        ]
        if len(open_live_trades) >= max_positions:
            logger.info("[LIVE] At live position limit (%d), skipping", max_positions)
            return None
        if any(t["ticker"] == ticker for t in open_live_trades):
            logger.info("[LIVE] Already have live trade for %s, skipping", ticker)
            return None
    except Exception as e:
        logger.error(
            "[LIVE] DB error in position/dup check for %s — REJECTING trade: %s",
            ticker, e,
        )
        try:
            _exec.send_telegram(
                f"🚨 CRITICAL: Live trade DB error for {ticker}\n"
                f"Position/duplicate check failed — live trade REJECTED.\n"
                f"All new live entries blocked until DB recovers.\n"
                f"Detail: {e}"
            )
        except Exception as _tg_err:
            logger.warning("[LIVE] Telegram alert failed: %s", _tg_err)
        return None

    # Hard governor cap (#hotfix 2026-04-13): DB-level count + combined caps,
    # so paper + live combined can never exceed the stricter configured limit.
    if not _exec._enforce_position_cap(config, db_path, packet.ticker, path="LIVE"):
        return None

    # Use live-specific risk parameters
    live_risk = live_cfg.get("risk", {})
    risk_pct_max = live_risk.get("planned_risk_pct_max", 0.02)
    stop_atr_mult = live_risk.get("stop_atr_multiplier", 1.0)
    target_atr_mult = live_risk.get("target_atr_multiplier", 2.0)
    # Fix #245: Cast to int — config values may arrive as strings.
    timeout_days = int(live_risk.get("timeout_days", 7))

    # Calculate live position sizing based on live risk parameters
    stop_price = _exec._parse_price(packet.stop_invalidation)
    atr = features.get("atr_14", 0)

    # Override stop/target with ATR-based if ATR available
    if atr > 0 and entry_price > 0:
        stop_price = entry_price - (atr * stop_atr_mult)
        target_price = entry_price + (atr * target_atr_mult)
    else:
        targets_parts = packet.targets.split("/")
        target_price = _exec._parse_price(targets_parts[0]) if targets_parts else 0.0

    # #326: Reject live bracket orders with invalid stop price.
    if not stop_price or float(stop_price) <= 0:
        logger.error(
            "[LIVE] Refusing bracket order for %s: stop_price=%s (must be > 0)",
            ticker, stop_price,
        )
        return None

    # Position size: risk_pct_max of live equity
    risk_per_share = entry_price - stop_price if entry_price > stop_price > 0 else entry_price * 0.02
    if risk_per_share > 0:
        max_risk_dollars = live_equity * risk_pct_max
        planned_shares = max(1, int(max_risk_dollars / risk_per_share))
    else:
        planned_shares = 1

    # Ensure we don't exceed available buying power
    buying_power = live_acct.get("buying_power", 0)
    max_shares_by_bp = int(buying_power / entry_price) if entry_price > 0 else 0
    planned_shares = min(planned_shares, max(1, max_shares_by_bp))

    # Use notional (dollar) ordering for fractional share support
    # Cap at 95% of buying power to buffer for market price movement
    planned_allocation = planned_shares * entry_price
    if planned_allocation > buying_power and buying_power > 1.0:
        planned_allocation = round(buying_power * 0.95, 2)
        planned_shares = max(1, int(planned_allocation / entry_price))

    et = ZoneInfo("America/New_York")
    now = datetime.now(et)

    trade = ShadowTrade(
        recommendation_id=recommendation_id,
        ticker=ticker,
        direction="long",
        status="pending",
        entry_price=entry_price,
        stop_price=stop_price,
        target_1=target_price,
        target_2=0.0,
        planned_shares=planned_shares,
        planned_allocation=planned_allocation,
        earnings_adjacent=features.get("event_risk_level", "none") in ("elevated", "imminent"),
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )

    trade_data = trade.to_dict()
    trade_data["source"] = "live"

    # Place live order via broker factory (IB or Alpaca, config-driven).
    # Uses bracket order so the broker manages stop-loss and take-profit exits.
    # #651 — pass limit_price=entry_price so the parent fill is bounded; combined
    # with the bracket's broker-side stop+target legs this gives full slippage
    # protection on entry plus survivability if our process dies.
    try:
        from src.trading.broker_factory import get_live_broker
        broker = get_live_broker(config)
        order = broker.place_bracket_order(
            ticker=ticker,
            quantity=planned_shares,
            take_profit_price=target_price,
            stop_loss_price=stop_price,
            limit_price=entry_price,
        )
        # Hotfix 2026-04-13: do NOT store IB integer IDs in alpaca_order_id
        # (see bug #420).  Route by broker to the correct typed column.
        if order.broker == "ib":
            trade_data["broker_order_id"] = str(order.order_id)
            trade_data["alpaca_order_id"] = None
        else:
            trade_data["alpaca_order_id"] = order.order_id
            trade_data["broker_order_id"] = str(order.order_id)
        trade_data["order_type"] = order.order_type
        trade_data["broker"] = order.broker  # Track which broker executed
        # Task 3: Store IB child order IDs for bracket health monitoring
        if order.child_order_ids:
            import json as _json_t3
            trade_data["ib_child_order_ids"] = _json_t3.dumps(order.child_order_ids)

        if order.filled_avg_price:
            trade_data["actual_entry_price"] = order.filled_avg_price
        else:
            trade_data["actual_entry_price"] = entry_price
        trade_data["actual_entry_time"] = now.isoformat()
        trade_data["status"] = "open"
        trade_data["max_favorable_excursion"] = 0.0
        trade_data["max_adverse_excursion"] = 0.0

    except Exception as e:
        _exec.log_and_persist(
            ticker=ticker,
            operation="place_bracket_order",
            broker="alpaca_live",
            exc=e,
            recoverable=False,
            outcome="persisted",
        )
        logger.warning("[LIVE] Live order failed for %s: %s", ticker, e)
        return None  # Do not record a live trade that failed to submit

    trade_id = _exec.insert_shadow_trade(trade_data, db_path)

    actual_price = trade_data.get("actual_entry_price", entry_price)
    logger.info(
        "[LIVE] Opened LIVE trade for %s at $%.2f (%d shares, risk $%.2f)",
        ticker, actual_price, planned_shares, risk_per_share * planned_shares,
    )

    # Telegram notification for live trade
    safe_send(
        "trade_opened",
        ticker=ticker, entry_price=actual_price, stop=stop_price, target=target_price,
        score=int(features.get("_score", 0)), shares=planned_shares,
        setup_type=features.get("setup_type"),
        setup_confidence=features.get("setup_confidence"),
        source="live",
    )

    # 1F. Check for live trade open milestones
    _exec._check_open_milestones(db_path, source="live")

    # 1K. Check sector exposure
    _exec._check_sector_exposure(db_path)

    # IB Shadow logging — non-blocking comparison data (#368)
    # SD#41 — Gated by trading.ib_enabled. When dormant, skip the import + write.
    try:
        ib_enabled = config.get("trading", {}).get("ib_enabled", False)
        ib_shadow_cfg = config.get("live_trading", {}).get("ib", {})
        if ib_enabled and ib_shadow_cfg.get("shadow_mode") and trade_data.get("status") == "open":
            from src.trading.ib_shadow import IBShadowLogger
            _ib_shadow = IBShadowLogger(config)
            _ib_shadow.log_shadow_trade(
                trade_id=trade_id, ticker=ticker, quantity=planned_shares,
                entry_price=float(entry_price), stop_price=float(stop_price),
                target_price=float(target_price),
                alpaca_order_id=str(trade_data.get("alpaca_order_id") or ""),
                alpaca_fill_price=float(trade_data.get("actual_entry_price") or entry_price),
                db_path=db_path,
            )
    except Exception as e:
        logger.warning("[SHADOW-IB] Shadow logging failed (non-fatal): %s", e)

    return trade_id
