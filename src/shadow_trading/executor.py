"""Shadow trade execution flow: entry and exit monitoring.

Called by: api.routes.shadow, cli.commands, evaluation.backtester, packets.eod_recap, risk.governor, scheduler.watch, services.scan_service, services.shadow_service, shadow_trading.ledger
Calls: config, data_ingestion.market_data, evaluation.postmortem, journal.store, llm.postmortem_writer, llm.validator, models, notifications.telegram, risk.governor, shadow_trading.alpaca_adapter, shadow_trading.models, utils.activity_logger
Owns tables: none
Config keys: bootcamp, enabled, live_trading, max_open_positions, max_positions, max_price, min_score, risk, shadow_trading, starting_capital, timeout_days
Tests: tests/test_expanded_notifications.py, tests/test_live_trading.py
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH, load_config
from src.utils.db import connect_db
from src.journal.store import (
    get_open_shadow_trades,
    get_open_shadow_trade_for_ticker,
    insert_shadow_trade,
    update_shadow_trade,
    close_shadow_trade,
    update_recommendation,
)
from src.models import TradePacket
from src.shadow_trading.models import ShadowTrade

logger = logging.getLogger(__name__)
FILLED_ORDER_STATUSES = {"filled", "partially_filled", "closed"}
PENDING_ORDER_STATUSES = {"new", "accepted", "pending_new", "accepted_for_bidding", "held"}


def _parse_price(value) -> float:
    """Parse a price value that may be a string like '$78.82 area' or a float."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace("$", "").replace(",", "").split()[0]
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0


def _is_filled_status(status: str | None) -> bool:
    """Return True when a broker order status represents a completed exit."""
    return str(status or "").lower() in FILLED_ORDER_STATUSES


def _is_pending_status(status: str | None) -> bool:
    """Return True when an exit order exists but has not filled yet."""
    return str(status or "").lower() in PENDING_ORDER_STATUSES


def _submit_exit_order(trade: dict, shares: int) -> dict:
    """Submit the appropriate broker exit order for a paper or live trade."""
    if trade.get("source") == "live":
        from src.shadow_trading.alpaca_adapter import place_live_exit

        return place_live_exit(trade["ticker"], 0)

    from src.shadow_trading.alpaca_adapter import place_paper_exit

    return place_paper_exit(trade["ticker"], shares)


def open_shadow_trade(
    recommendation_id: str,
    packet: TradePacket,
    features: dict,
    db_path: str = DB_PATH,
) -> str | None:
    """Open a shadow trade for a packet-worthy recommendation.

    Returns trade_id on success, None on failure.
    """
    config = load_config()
    shadow_cfg = config.get("shadow_trading", {})

    if not shadow_cfg.get("enabled", False):
        logger.info("Shadow trading disabled, skipping")
        return None

    # LLM output validation (catches hallucinated tickers, nonsensical prices, etc.)
    try:
        from src.llm.validator import validate_llm_output
        is_valid, reason = validate_llm_output(packet, features, config)
        if not is_valid:
            logger.warning("[VALIDATE] Trade rejected for %s: %s", packet.ticker, reason)
            return None
    except ImportError:
        logger.error("[VALIDATE] Validator import failed for %s — REJECTING trade", packet.ticker)
        return None
    except Exception as e:
        logger.error("[VALIDATE] Validation check failed for %s: %s — REJECTING trade", packet.ticker, e)
        return None  # Trade rejected — never proceed on validation failure

    # Risk governor check
    try:
        from src.risk.governor import RiskGovernor, get_portfolio_state
        governor = RiskGovernor(config)
        portfolio = get_portfolio_state(db_path)
        tl_mult = features.get("traffic_light_multiplier", 1.0)
        event_mult = features.get("event_risk_multiplier", 1.0)
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
            logger.warning("[RISK] Trade rejected for %s: %s", packet.ticker, reason)
            logger.info("[RISK] BLOCKED: %s — %s", packet.ticker, reason)
            return None
        packet.position_sizing.allocation_dollars = check.get(
            "effective_allocation_dollars",
            packet.position_sizing.allocation_dollars,
        )
        if packet.position_sizing.allocation_dollars <= 0:
            logger.warning("[RISK] Effective allocation reduced to zero for %s", packet.ticker)
            return None
    except ImportError:
        logger.error("[RISK] Governor import failed for %s — REJECTING trade", packet.ticker)
        return None
    except Exception as e:
        logger.error("[RISK] Governor check failed for %s: %s — REJECTING trade", packet.ticker, e)
        return None  # Trade rejected — never proceed on risk check failure

    # Position limit check (bootcamp overrides)
    bootcamp_cfg = config.get("bootcamp", {})
    if bootcamp_cfg.get("enabled", False):
        max_positions = bootcamp_cfg.get("max_positions", 50)
        logger.info(f"[BOOTCAMP] Position limit: {max_positions}")
    else:
        max_positions = shadow_cfg.get("max_positions", 10)

    open_trades = get_open_shadow_trades(db_path)
    if len(open_trades) >= max_positions:
        logger.info("[SHADOW] At position limit (%d), skipping", max_positions)
        return None

    ticker = packet.ticker

    # Atomic duplicate check: BEGIN IMMEDIATE to prevent race condition (#99)
    import sqlite3 as _sqlite3
    try:
        _dup_conn = _sqlite3.connect(db_path)
        _dup_conn.execute("BEGIN IMMEDIATE")
        _dup_row = _dup_conn.execute(
            "SELECT trade_id FROM shadow_trades WHERE ticker = ? AND status = 'open' LIMIT 1",
            (ticker,),
        ).fetchone()
        if _dup_row:
            _dup_conn.rollback()
            _dup_conn.close()
            logger.info("[SHADOW] Already have open trade for %s, skipping (atomic check)", ticker)
            return None
        _dup_conn.rollback()
        _dup_conn.close()
    except Exception as _dup_err:
        logger.warning("[SHADOW] Atomic duplicate check failed for %s: %s — falling back", ticker, _dup_err)
        existing = get_open_shadow_trade_for_ticker(ticker, db_path)
        if existing:
            logger.info("[SHADOW] Already have open trade for %s, skipping", ticker)
            return None

    # Parse packet values
    entry_price = _parse_price(packet.entry_zone)
    stop_price = _parse_price(packet.stop_invalidation)

    targets_parts = packet.targets.split("/")
    target_1 = _parse_price(targets_parts[0]) if len(targets_parts) >= 1 else 0.0
    target_2 = _parse_price(targets_parts[1]) if len(targets_parts) >= 2 else 0.0

    # Thorp-style graduated drawdown reduction
    try:
        from src.risk.governor import drawdown_adjusted_risk
        starting_capital = config.get("risk", {}).get("starting_capital", 100000)
        # Compute peak equity and current drawdown from closed trades
        with connect_db(db_path) as _conn:
            _row = _conn.execute(
                "SELECT COALESCE(SUM(pnl_dollars), 0) FROM shadow_trades WHERE status = 'closed'"
            ).fetchone()
            total_pnl = _row[0] if _row else 0
            _peak_row = _conn.execute(
                "SELECT MAX(running_pnl) FROM ("
                "  SELECT SUM(pnl_dollars) OVER (ORDER BY updated_at) AS running_pnl"
                "  FROM shadow_trades WHERE status = 'closed' AND pnl_dollars IS NOT NULL"
                ")"
            ).fetchone()
            peak_pnl = _peak_row[0] if _peak_row and _peak_row[0] else max(total_pnl, 0)
        peak_equity = starting_capital + peak_pnl
        current_equity = starting_capital + total_pnl
        current_dd_pct = max(0, (peak_equity - current_equity) / peak_equity * 100) if peak_equity > 0 else 0

        if current_dd_pct > 0:
            base_risk = config.get("risk", {}).get("planned_risk_pct_max", 0.02)
            adjusted = drawdown_adjusted_risk(base_risk, current_dd_pct)
            if adjusted <= 0:
                logger.warning("[RISK] Drawdown %.1f%% — trading halted (Thorp protocol)", current_dd_pct)
                try:
                    from src.notifications.telegram import send_telegram
                    send_telegram(
                        f"🔴 DRAWDOWN HALT: {current_dd_pct:.1f}%\n"
                        f"Trading halted per Thorp protocol (≥20% DD).\n"
                        f"Recovery needed: +{current_dd_pct / (100 - current_dd_pct) * 100:.1f}%"
                    )
                except Exception as e:
                    logger.warning("[RISK] Drawdown halt Telegram notification failed: %s", e)
                return None
            # Scale allocation proportionally
            scale_factor = adjusted / base_risk if base_risk > 0 else 1.0
            packet.position_sizing.allocation_dollars *= scale_factor
            logger.info("[RISK] Drawdown %.1f%% — risk scaled to %.0f%% (alloc $%.0f)",
                        current_dd_pct, scale_factor * 100, packet.position_sizing.allocation_dollars)

            # Telegram alerts at threshold crossings (5%, 10%, 15%)
            for threshold in [5.0, 10.0, 15.0]:
                if current_dd_pct >= threshold:
                    alert_key = f"dd_alert_{int(threshold)}"
                    # Check if we already alerted at this threshold today
                    try:
                        _alert_row = _conn.execute(
                            "SELECT 1 FROM activity_log WHERE event_type = ? AND detail LIKE ? AND created_at > date('now')",
                            (alert_key, f"%{int(threshold)}%")
                        ).fetchone()
                        if not _alert_row:
                            from src.notifications.telegram import send_telegram
                            from src.utils.activity_logger import log_activity
                            recovery_pct = current_dd_pct / (100 - current_dd_pct) * 100
                            send_telegram(
                                f"⚠️ DRAWDOWN ALERT: {current_dd_pct:.1f}%\n"
                                f"Position sizing at {scale_factor * 100:.0f}% of normal.\n"
                                f"Risk per trade: {adjusted:.3f} (base: {base_risk:.3f})\n"
                                f"Recovery needed: +{recovery_pct:.1f}%"
                            )
                            log_activity(alert_key, f"Drawdown {current_dd_pct:.1f}% crossed {int(threshold)}% threshold")
                    except Exception as e:
                        logger.warning("[RISK] Drawdown alert notification failed: %s", e)
                    break  # Only alert at highest crossed threshold
    except Exception as e:
        logger.error("[RISK] Drawdown check failed for %s: %s — REJECTING trade", packet.ticker, e)
        return None

    planned_shares = max(1, int(packet.position_sizing.allocation_dollars / entry_price)) if entry_price > 0 else 1
    planned_allocation = packet.position_sizing.allocation_dollars

    earnings_adjacent = features.get("event_risk_level", "none") in ("elevated", "imminent")

    et = ZoneInfo("America/New_York")
    now = datetime.now(et)

    trade = ShadowTrade(
        recommendation_id=recommendation_id,
        ticker=ticker,
        direction="long",
        status="pending",
        entry_price=entry_price,
        stop_price=stop_price,
        target_1=target_1,
        target_2=target_2,
        planned_shares=planned_shares,
        planned_allocation=planned_allocation,
        earnings_adjacent=earnings_adjacent,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )

    trade_data = trade.to_dict()

    # Try bracket order first, fall back to simple market order
    try:
        from src.shadow_trading.alpaca_adapter import place_bracket_order
        order = place_bracket_order(
            ticker,
            planned_shares,
            take_profit_price=target_1,
            stop_loss_price=stop_price,
        )
        trade_data["alpaca_order_id"] = order.get("order_id")
        trade_data["order_type"] = "bracket"

        fill_price = order.get("filled_avg_price")
        if fill_price:
            trade_data["actual_entry_price"] = fill_price
        else:
            trade_data["actual_entry_price"] = entry_price
        trade_data["actual_entry_time"] = now.isoformat()
        trade_data["status"] = "open"
        trade_data["max_favorable_excursion"] = 0.0
        trade_data["max_adverse_excursion"] = 0.0

    except Exception as e:
        logger.warning(f"[SHADOW] Bracket order failed for {ticker}: {e}, falling back to market")
        # Fall back to simple market order
        try:
            from src.shadow_trading.alpaca_adapter import place_paper_entry
            order = place_paper_entry(ticker, planned_shares)
            trade_data["alpaca_order_id"] = order.get("order_id")
            trade_data["order_type"] = "simple"

            fill_price = order.get("filled_avg_price")
            if fill_price:
                trade_data["actual_entry_price"] = fill_price
            else:
                trade_data["actual_entry_price"] = entry_price
            trade_data["actual_entry_time"] = now.isoformat()
            trade_data["status"] = "open"
            trade_data["max_favorable_excursion"] = 0.0
            trade_data["max_adverse_excursion"] = 0.0

        except Exception as e2:
            logger.warning(f"[SHADOW] Alpaca order failed for {ticker}: {e2}")
            logger.error("[SHADOW] Both bracket and fallback entry failed for %s: %s", ticker, e2)
            trade_data["actual_entry_price"] = entry_price
            trade_data["actual_entry_time"] = now.isoformat()
            trade_data["status"] = "failed"
            trade_data["order_type"] = "failed"
            trade_data["max_favorable_excursion"] = 0.0
            trade_data["max_adverse_excursion"] = 0.0

    # Source tagging: paper trades always tagged as "paper"
    trade_data["source"] = "paper"

    # Slippage tracking: signal price vs fill price
    actual_fill = trade_data.get("actual_entry_price", entry_price)
    trade_data["signal_entry_price"] = entry_price
    trade_data["fill_entry_price"] = actual_fill
    if entry_price > 0:
        slippage_bps = (actual_fill - entry_price) / entry_price * 10000
        trade_data["entry_slippage_bps"] = round(slippage_bps, 1)
        logger.info("[SLIPPAGE] %s entry: signal=$%.2f, fill=$%.2f, slippage=%.1f bps",
                    ticker, entry_price, actual_fill, slippage_bps)

    trade_id = insert_shadow_trade(trade_data, db_path)

    # Implementation Shortfall tracking
    signal_price = features.get("signal_price")
    actual_fill = trade_data.get("actual_entry_price", entry_price)
    if signal_price and signal_price > 0 and trade_id and trade_data.get("status") == "open":
        try:
            is_bps = ((actual_fill - signal_price) / signal_price) * 10000
            with connect_db(db_path) as _is_conn:
                _is_conn.execute(
                    "UPDATE shadow_trades SET signal_price = ?, implementation_shortfall_bps = ? "
                    "WHERE trade_id = ?",
                    (signal_price, round(is_bps, 2), trade_id),
                )
            logger.info("[IS] %s: signal=$%.2f fill=$%.2f IS=%.1f bps",
                        packet.ticker, signal_price, actual_fill, is_bps)
        except Exception as e:
            logger.warning("[IS] Failed to store IS for %s: %s", packet.ticker, e)

    # Update journal with shadow entry
    if recommendation_id and trade_data.get("status") == "open":
        update_recommendation(
            recommendation_id,
            {
                "shadow_entry_price": trade_data.get("actual_entry_price"),
                "shadow_entry_time": trade_data.get("actual_entry_time"),
            },
            db_path,
        )

    actual_price = trade_data.get("actual_entry_price", entry_price)
    if trade_data.get("status") == "open":
        logger.info(
            "[SHADOW] Opened shadow trade for %s at $%.2f (%d shares)",
            ticker, actual_price, planned_shares,
        )

        # 1F. Check for trade open milestones
        _check_open_milestones(db_path, source="paper")

        # 1K. Check sector exposure
        _check_sector_exposure(db_path)
    else:
        logger.error("[SHADOW] Recorded failed shadow trade for %s", ticker)

    return trade_id


def _retry_exit(trade: dict, db_path: str = DB_PATH) -> None:
    """Retry exit for trades stuck in exit_pending or exit_failed."""
    ticker = trade["ticker"]
    shares = trade.get("shares", trade.get("planned_shares", 0))
    try:
        exit_result = _submit_exit_order(trade, shares)
        exit_status = exit_result.get("status") if isinstance(exit_result, dict) else None
        if _is_filled_status(exit_status):
            fill_price = float(exit_result.get("filled_avg_price", 0))
            entry_price = trade.get("actual_entry_price") or trade.get("entry_price", 0)
            pnl_dollars = (fill_price - entry_price) * shares if entry_price else 0
            pnl_pct = ((fill_price - entry_price) / entry_price * 100) if entry_price else 0
            close_shadow_trade(
                trade["trade_id"],
                exit_price=fill_price,
                exit_time=datetime.now(ZoneInfo("America/New_York")).isoformat(),
                exit_reason=trade.get("exit_reason", "retry_exit"),
                pnl_dollars=round(pnl_dollars, 2),
                pnl_pct=round(pnl_pct, 2),
                db_path=db_path,
            )
            logger.info("[RETRY] Successfully closed %s on retry", ticker)
        elif _is_pending_status(exit_status):
            logger.info("[RETRY] Exit still pending for %s", ticker)
        else:
            update_shadow_trade(trade["trade_id"], {"status": "exit_failed"}, db_path)
            logger.warning("[RETRY] Exit retry failed for %s (status=%s)", ticker, exit_status)
    except Exception as e:
        update_shadow_trade(trade["trade_id"], {"status": "exit_failed"}, db_path)
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
    config = load_config()
    shadow_cfg = config.get("shadow_trading", {})
    timeout_days = shadow_cfg.get("timeout_days", 15)

    open_trades = get_open_shadow_trades(db_path)
    if source_filter:
        open_trades = [t for t in open_trades if t.get("source") == source_filter]
    actions = []

    et = ZoneInfo("America/New_York")
    now = datetime.now(et)

    # Track price fetch failures for Alpaca health monitoring (#102)
    _price_total = 0
    _price_failures = 0

    # Pre-fetch Alpaca positions for existence checking (single API call)
    _alpaca_tickers: set[str] = set()
    try:
        from src.shadow_trading.alpaca_adapter import get_all_positions
        _alpaca_tickers = {p["symbol"] for p in get_all_positions()}
    except Exception as e:
        logger.debug("[EXECUTOR] Could not fetch positions for existence check: %s", e)

    for trade in open_trades:
        # Retry exit for failed exits instead of skipping
        if trade.get("status") in ("exit_pending", "exit_failed"):
            _retry_exit(trade, db_path)
            continue

        ticker = trade["ticker"]
        entry_price = trade.get("actual_entry_price") or trade.get("entry_price", 0)
        stop_price = trade.get("stop_price", 0)
        target_1 = trade.get("target_1", 0)
        target_2 = trade.get("target_2", 0)

        if entry_price <= 0:
            continue

        # Get current price — track failures (#102)
        _price_total += 1
        current_price = _get_current_price_safe(ticker)
        if current_price is None:
            _price_failures += 1
            continue

        # Calculate unrealized P&L
        shares = trade.get("planned_shares", 1)
        unrealized_pnl = (current_price - entry_price) * shares
        unrealized_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

        # Update MFE/MAE
        mfe = trade.get("max_favorable_excursion") or 0.0
        mae = trade.get("max_adverse_excursion") or 0.0

        price_move = current_price - entry_price
        if price_move > mfe:
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

        # Update trade with current MFE/MAE and duration
        update_shadow_trade(
            trade["trade_id"],
            {
                "max_favorable_excursion": mfe,
                "max_adverse_excursion": mae,
                "duration_days": days_open,
            },
            db_path,
        )

        # For bracket orders, check Alpaca for exit fills
        bracket_exit = False
        exit_reason = None
        if trade.get("order_type") == "bracket" and trade.get("alpaca_order_id"):
            try:
                from src.shadow_trading.alpaca_adapter import get_order_status
                order_status = get_order_status(trade["alpaca_order_id"])
                parent_status = order_status.get("status", "")
                # Check parent order status
                if parent_status in FILLED_ORDER_STATUSES:
                    exit_price = order_status.get("filled_avg_price")
                    if exit_price:
                        current_price = exit_price
                        bracket_exit = True
                # Also check child/leg order statuses (stop-loss or take-profit may have fired)
                legs = order_status.get("legs", [])
                for leg in legs:
                    leg_status = leg.get("status", "")
                    if leg_status in ("filled", "partially_filled"):
                        leg_price = leg.get("filled_avg_price")
                        if leg_price:
                            current_price = leg_price
                            bracket_exit = True
                            # Identify leg type: stop legs have stop_price, limit legs are take-profit
                            leg_type = leg.get("order_type", "")
                            if leg_type == "stop" or leg.get("stop_price"):
                                exit_reason = "stop_loss"
                            elif leg_type == "limit" or leg.get("limit_price"):
                                exit_reason = "take_profit"
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
        if exit_reason is None:
            if current_price <= stop_price and stop_price > 0:
                exit_reason = "stop_hit"
            elif current_price >= target_2 and target_2 > 0:
                exit_reason = "target_2_hit"
            elif current_price >= target_1 and target_1 > 0:
                exit_reason = "target_1_hit"
            elif days_open >= timeout_days:
                exit_reason = "timeout"

        if exit_reason:
            # Exit slippage tracking
            signal_exit = current_price  # price that triggered exit
            exit_slippage_bps = 0.0

            if not bracket_exit:
                try:
                    exit_result = _submit_exit_order(trade, shares)
                except Exception as e:
                    logger.error("[EXIT] Broker exit failed for %s — trade remains open: %s", ticker, e)
                    continue

                exit_status = exit_result.get("status") if isinstance(exit_result, dict) else None
                if _is_filled_status(exit_status):
                    fill_exit = exit_result.get("filled_avg_price") if isinstance(exit_result, dict) else None
                    if fill_exit is not None:
                        current_price = float(fill_exit)
                        exit_slippage_bps = (
                            (current_price - signal_exit) / signal_exit * 10000
                            if signal_exit > 0
                            else 0
                        )
                        logger.info(
                            "[SLIPPAGE] %s exit: signal=$%.2f, fill=$%.2f, slippage=%.1f bps",
                            ticker,
                            signal_exit,
                            current_price,
                            exit_slippage_bps,
                        )
                elif _is_pending_status(exit_status):
                    update_shadow_trade(
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
                    )
                    update_shadow_trade(
                        trade["trade_id"],
                        {"status": "exit_failed", "exit_reason": exit_reason},
                        db_path,
                    )
                    try:
                        from src.notifications.telegram import send_telegram
                        send_telegram(
                            f"⚠️ Exit order FAILED for {ticker} — will retry next cycle"
                        )
                    except Exception:
                        pass
                    continue

            pnl_dollars = (current_price - entry_price) * shares
            pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

            close_shadow_trade(
                trade["trade_id"],
                exit_price=current_price,
                exit_time=now.isoformat(),
                exit_reason=exit_reason,
                pnl_dollars=round(pnl_dollars, 2),
                pnl_pct=round(pnl_pct, 2),
                db_path=db_path,
            )

            # Also update final MFE/MAE and duration on the closed trade
            update_shadow_trade(
                trade["trade_id"],
                {
                    "max_favorable_excursion": mfe,
                    "max_adverse_excursion": mae,
                    "duration_days": days_open,
                },
                db_path,
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

                update_recommendation(
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

            logger.info(
                "[SHADOW] Closed %s: %s | P&L=$%+.2f (%+.1f%%) | held %d days",
                ticker, exit_reason, pnl_dollars, pnl_pct, days_open,
            )

            try:
                from src.notifications.telegram import notify_trade_closed, is_telegram_enabled
                if is_telegram_enabled():
                    notify_trade_closed(
                        ticker,
                        pnl_dollars,
                        pnl_pct,
                        exit_reason,
                        days_open,
                        source=trade.get("source", "paper"),
                    )
            except Exception as e:
                logger.warning("[SHADOW] Telegram notify_trade_closed failed for %s: %s", ticker, e)

            # 1F. Check for trade close milestones
            _check_close_milestones(db_path)

            # 1G. Check for loss streak
            _check_loss_streak(db_path)

    # Alert if >50% of price checks failed in this cycle (#102)
    if _price_total > 0 and _price_failures / _price_total > 0.5:
        logger.warning(
            "[EXECUTOR] Price fetch failure rate %.0f%% (%d/%d) — possible Alpaca outage",
            _price_failures / _price_total * 100, _price_failures, _price_total,
        )
        try:
            from src.notifications.telegram import send_telegram
            send_telegram(
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

    Returns trade_id on success, None on failure.
    """
    config = load_config()
    live_cfg = config.get("live_trading", {})

    if not live_cfg.get("enabled", False):
        logger.info("[LIVE] Live trading disabled, skipping")
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
    entry_price = _parse_price(packet.entry_zone)
    if max_price is not None and entry_price > max_price:
        logger.info("[LIVE] Price $%.2f above max_price $%s for %s", entry_price, max_price, packet.ticker)
        return None

    # Safety guard: Capital check — halt if equity < 50% of starting capital
    starting_capital = live_cfg.get("starting_capital", 100)
    try:
        from src.shadow_trading.alpaca_adapter import get_live_account_info
        live_acct = get_live_account_info()
        live_equity = live_acct.get("equity", 0)

        if live_equity < starting_capital * 0.50:
            logger.warning(
                "[LIVE] CAPITAL GUARD: Equity $%.2f < 50%% of starting $%.2f — HALTING",
                live_equity, starting_capital,
            )
            try:
                from src.notifications.telegram import notify_risk_alert, is_telegram_enabled
                if is_telegram_enabled():
                    notify_risk_alert(
                        "LIVE CAPITAL GUARD",
                        f"Live equity ${live_equity:.2f} below 50% of starting ${starting_capital:.2f}. "
                        f"Live trading halted.",
                    )
            except Exception as e:
                logger.warning("[LIVE] Capital guard Telegram alert failed: %s", e)
            return None
    except Exception as e:
        logger.warning("[LIVE] Could not check live account: %s — skipping", e)
        return None

    # Safety guard: Daily loss limit — halt if daily P&L < -5% of capital
    try:
        from src.journal.store import get_open_shadow_trades
        live_trades_today = [
            t for t in get_open_shadow_trades(db_path)
            if t.get("source") == "live"
        ]
        daily_live_pnl = 0.0
        for t in live_trades_today:
            t_entry = t.get("actual_entry_price") or t.get("entry_price", 0)
            if t_entry > 0:
                current = _get_current_price_safe(t["ticker"])
                if current:
                    shares = t.get("planned_shares", 1)
                    daily_live_pnl += (current - t_entry) * shares

        if starting_capital > 0 and daily_live_pnl < -(starting_capital * 0.05):
            logger.warning(
                "[LIVE] DAILY LOSS GUARD: Live P&L $%.2f exceeds -5%% of $%.2f — HALTING for day",
                daily_live_pnl, starting_capital,
            )
            try:
                from src.notifications.telegram import notify_risk_alert, is_telegram_enabled
                if is_telegram_enabled():
                    notify_risk_alert(
                        "LIVE DAILY LOSS LIMIT",
                        f"Live daily P&L ${daily_live_pnl:.2f} exceeds -5% of ${starting_capital:.2f}. "
                        f"No more live trades today.",
                    )
            except Exception as e:
                logger.warning("[LIVE] Daily loss Telegram alert failed: %s", e)
            return None
    except Exception as e:
        logger.error("[LIVE] Daily loss guard failed for %s — REJECTING trade: %s", packet.ticker, e)
        return None

    # Position limit check (live-specific)
    max_positions = live_cfg.get("max_open_positions", 2)
    try:
        open_live_trades = [
            t for t in get_open_shadow_trades(db_path)
            if t.get("source") == "live"
        ]
        if len(open_live_trades) >= max_positions:
            logger.info("[LIVE] At live position limit (%d), skipping", max_positions)
            return None
    except Exception as e:
        logger.error("[LIVE] Position limit check failed for %s — REJECTING trade: %s", packet.ticker, e)
        return None

    # Duplicate check (live-specific)
    ticker = packet.ticker
    try:
        open_live_trades = [
            t for t in get_open_shadow_trades(db_path)
            if t.get("source") == "live"
        ]
        if any(t["ticker"] == ticker for t in open_live_trades):
            logger.info("[LIVE] Already have live trade for %s, skipping", ticker)
            return None
    except Exception as e:
        logger.error("[LIVE] Duplicate check failed for %s — REJECTING trade: %s", ticker, e)
        return None

    # Use live-specific risk parameters
    live_risk = live_cfg.get("risk", {})
    risk_pct_max = live_risk.get("planned_risk_pct_max", 0.02)
    stop_atr_mult = live_risk.get("stop_atr_multiplier", 1.0)
    target_atr_mult = live_risk.get("target_atr_multiplier", 2.0)
    timeout_days = live_risk.get("timeout_days", 7)

    # Calculate live position sizing based on live risk parameters
    stop_price = _parse_price(packet.stop_invalidation)
    atr = features.get("atr_14", 0)

    # Override stop/target with ATR-based if ATR available
    if atr > 0 and entry_price > 0:
        stop_price = entry_price - (atr * stop_atr_mult)
        target_price = entry_price + (atr * target_atr_mult)
    else:
        targets_parts = packet.targets.split("/")
        target_price = _parse_price(targets_parts[0]) if targets_parts else 0.0

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

    # Place live order
    try:
        from src.shadow_trading.alpaca_adapter import place_live_entry
        order = place_live_entry(ticker, planned_shares, notional=planned_allocation)
        trade_data["alpaca_order_id"] = order.get("order_id")
        trade_data["order_type"] = "simple"

        fill_price = order.get("filled_avg_price")
        if fill_price:
            trade_data["actual_entry_price"] = fill_price
        else:
            trade_data["actual_entry_price"] = entry_price
        trade_data["actual_entry_time"] = now.isoformat()
        trade_data["status"] = "open"
        trade_data["max_favorable_excursion"] = 0.0
        trade_data["max_adverse_excursion"] = 0.0

    except Exception as e:
        logger.warning("[LIVE] Live order failed for %s: %s", ticker, e)
        return None  # Do not record a live trade that failed to submit

    trade_id = insert_shadow_trade(trade_data, db_path)

    actual_price = trade_data.get("actual_entry_price", entry_price)
    logger.info(
        "[LIVE] Opened LIVE trade for %s at $%.2f (%d shares, risk $%.2f)",
        ticker, actual_price, planned_shares, risk_per_share * planned_shares,
    )

    # Telegram notification for live trade
    try:
        from src.notifications.telegram import notify_trade_opened, is_telegram_enabled
        if is_telegram_enabled():
            ps = packet.position_sizing
            notify_trade_opened(
                ticker, actual_price, stop_price, target_price,
                int(features.get("_score", 0)), planned_shares,
                setup_type=features.get("setup_type"),
                setup_confidence=features.get("setup_confidence"),
                source="live",
            )
    except Exception as e:
        logger.warning("[LIVE] Telegram notify_trade_opened failed: %s", e)

    # 1F. Check for live trade open milestones
    _check_open_milestones(db_path, source="live")

    # 1K. Check sector exposure
    _check_sector_exposure(db_path)

    return trade_id


def _check_open_milestones(db_path: str = DB_PATH,
                           source: str = "paper") -> None:
    """Check for trade open milestones and send notifications."""
    try:
        from src.notifications.telegram import notify_milestone, is_telegram_enabled
        if not is_telegram_enabled():
            return

        with connect_db(db_path) as conn:
            # Count total opened trades for this source
            total = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE COALESCE(source,'paper') = ?",
                (source,),
            ).fetchone()[0]

            label = "live" if source == "live" else "paper"

            if total == 1:
                notify_milestone(
                    f"First {label} trade opened!",
                    f"Your trading journey begins. Track progress in the Shadow Ledger."
                )
    except Exception as e:
        logger.debug("[MILESTONE] Open milestone check failed: %s", e)


def _check_close_milestones(db_path: str = DB_PATH) -> None:
    """Check for trade close milestones and send notifications."""
    try:
        from src.notifications.telegram import notify_milestone, is_telegram_enabled
        if not is_telegram_enabled():
            return

        with connect_db(db_path) as conn:

            closed_total = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE status='closed'"
            ).fetchone()[0]

            wins = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE status='closed' AND pnl_dollars > 0"
            ).fetchone()[0]
            losses = closed_total - wins

            # Check milestone thresholds
            milestones = {1: "1st trade closed!", 10: "10th closed trade!",
                          25: "25th closed trade!", 50: "50th closed trade — Phase 1 gate!"}
            if closed_total in milestones:
                win_rate = wins / closed_total if closed_total > 0 else 0

                avg_row = conn.execute(
                    "SELECT AVG(pnl_dollars) as expectancy, AVG(duration_days) as avg_hold "
                    "FROM shadow_trades WHERE status='closed'"
                ).fetchone()
                expectancy = avg_row["expectancy"] or 0
                avg_hold = avg_row["avg_hold"] or 0

                if closed_total == 50:
                    detail = (
                        f"🎉 Phase 1 gate reached!\n"
                        f"Current win rate: {win_rate:.0%} ({wins}W / {losses}L)\n"
                        f"Avg hold: {avg_hold:.1f} days | Expectancy: ${expectancy:+.2f}/trade"
                    )
                elif closed_total == 1:
                    detail = "Your first completed trade. Many more to come."
                else:
                    remaining = 50 - closed_total
                    detail = (
                        f"{remaining} more to Phase 1 gate (50 trades).\n"
                        f"Current win rate: {win_rate:.0%} ({wins}W / {losses}L)\n"
                        f"Avg hold: {avg_hold:.1f} days | Expectancy: ${expectancy:+.2f}/trade"
                    )
                notify_milestone(milestones[closed_total], detail)

            # First profitable trade
            if wins == 1:
                first_win = conn.execute(
                    "SELECT ticker, pnl_dollars, pnl_pct FROM shadow_trades "
                    "WHERE status='closed' AND pnl_dollars > 0 "
                    "ORDER BY actual_exit_time ASC LIMIT 1"
                ).fetchone()
                if first_win:
                    notify_milestone(
                        "First profitable trade!",
                        f"{first_win['ticker']}: ${first_win['pnl_dollars']:+.2f} ({first_win['pnl_pct']:+.1f}%)"
                    )

            # First live profit
            live_wins = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades "
                "WHERE status='closed' AND source='live' AND pnl_dollars > 0"
            ).fetchone()[0]
            if live_wins == 1:
                first_live_win = conn.execute(
                    "SELECT ticker, pnl_dollars, pnl_pct FROM shadow_trades "
                    "WHERE status='closed' AND source='live' AND pnl_dollars > 0 "
                    "ORDER BY actual_exit_time ASC LIMIT 1"
                ).fetchone()
                if first_live_win:
                    notify_milestone(
                        "First live trade profit!",
                        f"{first_live_win['ticker']}: ${first_live_win['pnl_dollars']:+.2f} ({first_live_win['pnl_pct']:+.1f}%)"
                    )

            # 3 consecutive wins
            last_3 = conn.execute(
                "SELECT pnl_dollars FROM shadow_trades WHERE status='closed' "
                "ORDER BY actual_exit_time DESC LIMIT 3"
            ).fetchall()
            if len(last_3) == 3 and all(r["pnl_dollars"] > 0 for r in last_3):
                last_4 = conn.execute(
                    "SELECT pnl_dollars FROM shadow_trades WHERE status='closed' "
                    "ORDER BY actual_exit_time DESC LIMIT 4"
                ).fetchall()
                # Only alert if the 4th-most-recent was NOT a win (to avoid repeat alerts)
                if len(last_4) < 4 or last_4[3]["pnl_dollars"] <= 0:
                    notify_milestone(
                        "3 consecutive wins!",
                        "Hot streak! Keep the discipline."
                    )

            # Best single trade P&L
            best_ever = conn.execute(
                "SELECT ticker, pnl_dollars, pnl_pct FROM shadow_trades "
                "WHERE status='closed' ORDER BY pnl_dollars DESC LIMIT 1"
            ).fetchone()
            # The most recent closed trade
            latest = conn.execute(
                "SELECT ticker, pnl_dollars FROM shadow_trades "
                "WHERE status='closed' ORDER BY actual_exit_time DESC LIMIT 1"
            ).fetchone()
            if (best_ever and latest and closed_total > 1
                    and best_ever["ticker"] == latest["ticker"]
                    and best_ever["pnl_dollars"] == latest["pnl_dollars"]
                    and best_ever["pnl_dollars"] > 0):
                notify_milestone(
                    "New best trade!",
                    f"{best_ever['ticker']}: ${best_ever['pnl_dollars']:+.2f} ({best_ever['pnl_pct']:+.1f}%)"
                )

    except Exception as e:
        logger.debug("[MILESTONE] Close milestone check failed: %s", e)


def _check_loss_streak(db_path: str = DB_PATH) -> None:
    """Check for consecutive losses and alert at 3+."""
    try:
        from src.notifications.telegram import notify_streak_alert, is_telegram_enabled
        if not is_telegram_enabled():
            return

        with connect_db(db_path) as conn:
            recent = conn.execute(
                "SELECT ticker, pnl_dollars, pnl_pct FROM shadow_trades "
                "WHERE status='closed' ORDER BY actual_exit_time DESC LIMIT 10"
            ).fetchall()

        if len(recent) < 3:
            return

        # Count consecutive losses from most recent
        streak = 0
        streak_trades = []
        for r in recent:
            if r["pnl_dollars"] < 0:
                streak += 1
                streak_trades.append((r["ticker"], r["pnl_pct"]))
            else:
                break

        if streak >= 3:
            # Only alert if this is exactly the streak boundary (3rd, 4th, etc.)
            # Check if streak was already 3+ before this trade
            prev_streak = 0
            for r in recent[1:]:
                if r["pnl_dollars"] < 0:
                    prev_streak += 1
                else:
                    break

            # Alert on first crossing of 3, or every additional loss after
            if streak == 3 or (streak > 3 and prev_streak < streak):
                max_dd = min(r["pnl_pct"] for r in recent[:streak])

                # Historical max streak
                with connect_db(db_path) as conn:
                    all_closed = conn.execute(
                        "SELECT pnl_dollars FROM shadow_trades WHERE status='closed' "
                        "ORDER BY actual_exit_time ASC"
                    ).fetchall()
                max_streak = 0
                current = 0
                for r in all_closed:
                    if r["pnl_dollars"] < 0:
                        current += 1
                        max_streak = max(max_streak, current)
                    else:
                        current = 0

                notify_streak_alert(
                    streak_length=streak,
                    recent_trades=streak_trades[:5],
                    max_drawdown_pct=max_dd,
                    risk_governor_status="NORMAL",
                    historical_max_streak=max_streak,
                )
    except Exception as e:
        logger.debug("[STREAK] Loss streak check failed: %s", e)


def _check_sector_exposure(db_path: str = DB_PATH) -> None:
    """Check sector concentration after each trade open."""
    try:
        from src.notifications.telegram import notify_exposure_alert, is_telegram_enabled
        if not is_telegram_enabled():
            return

        with connect_db(db_path) as conn:
            open_trades = conn.execute(
                "SELECT ticker FROM shadow_trades WHERE status='open'"
            ).fetchall()

        if len(open_trades) < 3:
            return

        # Get sector for each ticker (best-effort from recommendations)
        sectors: dict[str, list[str]] = {}
        with connect_db(db_path) as conn:
            for trade in open_trades:
                ticker = trade["ticker"]
                rec = conn.execute(
                    "SELECT setup_type FROM recommendations WHERE ticker = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (ticker,),
                ).fetchone()
                # Use setup_type as a proxy; in practice, sector info would come from features
                sector = "Unknown"
                try:
                    import yfinance as yf
                    info = yf.Ticker(ticker).info
                    sector = info.get("sector", "Unknown")
                except Exception as e:
                    logger.debug("[EXPOSURE] yfinance sector lookup failed for %s: %s", ticker, e)
                sectors.setdefault(sector, []).append(ticker)

        total_positions = len(open_trades)
        limit_pct = 30.0
        for sector, tickers in sectors.items():
            if sector == "Unknown":
                continue
            exposure_pct = (len(tickers) / total_positions) * 100
            if exposure_pct > limit_pct and len(tickers) >= 3:
                notify_exposure_alert(
                    sector=sector, count=len(tickers), tickers=tickers,
                    exposure_pct=exposure_pct, limit_pct=limit_pct,
                )
    except Exception as e:
        logger.debug("[EXPOSURE] Sector exposure check failed: %s", e)


def _get_current_price_safe(ticker: str) -> float | None:
    """Get current price, trying Alpaca first then falling back to yfinance."""
    try:
        from src.shadow_trading.alpaca_adapter import get_current_price
        price = get_current_price(ticker)
        if price:
            return price
    except Exception as e:
        logger.debug("[PRICE] Alpaca price fetch failed for %s: %s", ticker, e)

    # Fallback to yfinance
    try:
        from src.data_ingestion.market_data import fetch_ohlcv
        data = fetch_ohlcv([ticker], period="5d")
        if ticker in data and not data[ticker].empty:
            return float(data[ticker]["Close"].iloc[-1])
    except Exception as e:
        logger.debug("[PRICE] yfinance price fetch failed for %s: %s", ticker, e)

    return None
