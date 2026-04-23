"""Shadow trade execution flow: entry and exit monitoring.

This is the core trade lifecycle manager. Two main entry points:
  - open_shadow_trade(): Decision chain for paper trade entry (validation ->
    risk governor -> position limits -> duplicate check -> bracket order).
  - check_and_manage_open_trades(): Exit monitoring loop that checks all open
    positions against stops, targets, timeouts, and bracket fills.

Also includes open_live_trade() for real-money execution with additional
safety guards (capital guard, daily loss limit, LLM conviction required).

Key issue cross-references:
  - #99: Race condition duplicate check (BEGIN IMMEDIATE)
  - #187: Failed shadow trades buying power check
  - #196: Duplicate exit orders (exit_retry_count + _MAX_EXIT_RETRIES)

Called by: api.routes.shadow, cli.commands, evaluation.backtester, packets.eod_recap, risk.governor, scheduler.watch, services.scan_service, services.shadow_service, shadow_trading.ledger
Calls: config, data_ingestion.market_data, evaluation.postmortem, journal.store, llm.postmortem_writer, llm.validator, models, notifications.telegram, risk.governor, shadow_trading.alpaca_adapter (cancel_paper_order), shadow_trading.models, utils.activity_logger
Owns tables: none (reads/writes shadow_trades.exit_retry_count)
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
    get_open_shadow_trade_for_ticker,
    insert_shadow_trade,
    update_shadow_trade,
    close_shadow_trade,
    update_recommendation,
)
from src.models import TradePacket
from src.shadow_trading.models import ShadowTrade
from alpaca.common.exceptions import APIError

logger = logging.getLogger(__name__)


def _count_live_open_positions(db_path: str) -> int:
    """Count all non-quarantined open/exit_pending shadow trades regardless of source.

    Returns a fresh count straight from SQLite so every entry path (shadow,
    live, any future router) agrees.  Used by the hard governor cap.
    """
    from src.utils.db import connect_db
    with connect_db(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades "
            "WHERE status IN ('open', 'exit_pending') "
            "AND COALESCE(quarantined, 0) = 0"
        ).fetchone()
    return int(row[0] or 0)


def _governor_cap(config: dict) -> int:
    """Return the effective open-position cap, respecting bootcamp overrides.

    Bootcamp mode intentionally raises the breadth ceiling to teach the
    model portfolio diversification.  When ``bootcamp.enabled`` is True, the
    cap comes from ``bootcamp.max_positions`` — matching the existing
    ternaries at ``executor.open_shadow_trade`` (line 297-303) and
    ``risk.governor.RiskGovernor.check_trade`` (line 500-502) so all three
    governor surfaces agree on the effective limit.

    When bootcamp is disabled, falls back to the stricter of
    ``risk.max_open_positions`` and ``shadow_trading.max_positions`` so
    neither alone can be bypassed.

    The original #430 investigation (2026-04-13) showed 19 open positions
    against an intuitive cap of 10 — the intended bootcamp ceiling of 50
    was active but the hotfix's early helper ignored it, making the
    effective cap drop to 5 post-merge and blocking all new entries.
    """
    bootcamp = config.get("bootcamp", {})
    if bootcamp.get("enabled", False):
        bc_cap = bootcamp.get("max_positions", 50)
        if isinstance(bc_cap, int) and bc_cap > 0:
            return bc_cap
        return 50
    risk_cap = config.get("risk", {}).get("max_open_positions")
    shadow_cap = config.get("shadow_trading", {}).get("max_positions")
    caps = [c for c in (risk_cap, shadow_cap) if isinstance(c, int) and c > 0]
    return min(caps) if caps else 10


def _enforce_position_cap(config: dict, db_path: str, ticker: str, path: str = "SHADOW") -> bool:
    """Return True if a new trade is allowed.  Log + return False if at cap.

    Belt-and-braces defence: counts *all* non-quarantined open trades (not
    just per-source subsets) against the stricter of the configured caps.
    Called from both ``open_shadow_trade`` and ``open_live_trade`` so no
    entry path can accidentally exceed the limit.
    """
    cap = _governor_cap(config)
    open_count = _count_live_open_positions(db_path)
    if open_count >= cap:
        logger.warning(
            "[GOVERNOR] Max positions reached (%d/%d), rejecting %s (path=%s)",
            open_count, cap, ticker, path,
        )
        return False
    return True


def _resolve_event_risk_multiplier(features: dict, ticker: str, path: str = "") -> float:
    """Return the event-risk sizing multiplier, computing on-demand when missing.

    Fix for #422: ``features.get("event_risk_multiplier")`` was returning
    ``None`` for tickers whose feature builder never ran through
    ``attach_event_risk_scores`` (single call site at
    ``services.scan_service:115``).  The previous 0.5 fallback silently halved
    allocations even when calendar data existed — confirmed for BMY, BK, CSCO,
    C, TXN on 2026-04-13.

    Resolution order (#422):
      1. Use ``features["event_risk_multiplier"]`` if present (scan-service path).
      2. Compute via ``event_risk_score.compute_event_risk_score(ticker)``.
         Succeeds when ``earnings_calendar`` is populated — the realistic case.
      3. Fall back to 0.5 (fail-conservative, per #267) only if compute also
         fails, e.g. DB unavailable.  Respecting #267's defensive default
         means the worst case now is a sized-down trade, never an
         unknown-unknowns oversized trade.

    Mutates ``features`` in-place with the resolved value so downstream readers
    see the correct number.  ``path`` is purely cosmetic for log prefixes.
    """
    prefix = f"[{path}]" if path else ""
    existing = features.get("event_risk_multiplier")
    if existing is not None:
        return float(existing)
    try:
        from src.features.event_risk_score import compute_event_risk_score
        ticker_risk = compute_event_risk_score(ticker)
        computed = float(ticker_risk.get("sizing_multiplier", 1.0))
        features["event_risk_multiplier"] = computed
        logger.warning(
            "%s[RISK] event_risk_multiplier missing from features for %s "
            "— computed on-demand=%.3f (feature pipeline did not call "
            "attach_event_risk_scores)",
            prefix, ticker, computed,
        )
        return computed
    except Exception as exc:
        logger.warning(
            "%s[RISK] event_risk_multiplier missing AND compute failed for "
            "%s (%s) — defaulting to 0.5 (fail-conservative per #267)",
            prefix, ticker, exc,
        )
        features["event_risk_multiplier"] = 0.5
        return 0.5
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


_consecutive_bp_failures = 0
_BP_ALERT_THRESHOLD = 3
# #392: Track capital committed within the current scan cycle to prevent
# race condition where multiple trades each pass the buying power check
# individually but together exceed available capital.
_scan_cycle_committed = 0.0


def reset_scan_cycle_committed() -> None:
    """Reset the per-cycle committed capital tracker. Call at scan start."""
    global _scan_cycle_committed
    _scan_cycle_committed = 0.0


def _check_paper_buying_power(entry_price: float, shares: int) -> bool:
    """Check if paper account has sufficient buying power for the trade.

    Fix for #187: Trades were failing silently at Alpaca when the paper account
    ran out of buying power. Now we pre-check and record the trade as
    'rejected_buying_power' so the dashboard shows why it was skipped.

    #392: Also subtracts capital committed by earlier trades in the same scan
    cycle to prevent the race condition where N trades each pass individually
    but together exhaust buying power.
    """
    global _consecutive_bp_failures, _scan_cycle_committed
    try:
        from src.shadow_trading.alpaca_adapter import get_account_info
        acct = get_account_info()
        buying_power = float(acct.get("buying_power", 0))
        # Subtract capital already committed in this scan cycle
        effective_bp = buying_power - _scan_cycle_committed
        required = entry_price * shares
        if required > effective_bp:
            logger.warning(
                "[SHADOW] Insufficient buying power: need $%.2f, have $%.2f (committed $%.2f this cycle)",
                required, effective_bp, _scan_cycle_committed,
            )
            _consecutive_bp_failures += 1
            if _consecutive_bp_failures >= _BP_ALERT_THRESHOLD:
                try:
                    from src.notifications.telegram import send_telegram
                    send_telegram(
                        f"⚠️ BUYING POWER CRISIS: {_consecutive_bp_failures} consecutive rejections\n"
                        f"Available: ${buying_power:,.2f} / Need: ${required:,.2f}\n"
                        f"Check for orphaned positions consuming capital."
                    )
                except Exception as e:
                    logger.warning("[EXECUTOR] Buying-power crisis notification failed: %s", e)
            return False
        _consecutive_bp_failures = 0
        _scan_cycle_committed += required
        return True
    except Exception as exc:
        # Fail CLOSED — if we can't verify buying power, skip the trade.
        # A missed trade is recoverable (next scan picks it up). An orphaned
        # position from a trade that should have been blocked is not.
        # Changed from fail-open after production incident where API blips
        # let trades through that exhausted buying power and created
        # 15 orphaned positions.
        logger.warning("[SHADOW] Buying power check failed: %s — blocking trade (fail-closed)", exc)
        return False


def _check_paper_buying_power_allocation(allocation_dollars: float) -> bool:
    """Cheap BP precheck at packet-allocation granularity (Sprint 2 K).

    Called from scan entry points BEFORE Ollama LLM inference to avoid
    wasting ~17s of compute on tickers that can't be funded. Returns
    True if the trade is fundable given current buying power and the
    committed-this-cycle counter, False otherwise.

    Does NOT increment ``_scan_cycle_committed``. The full
    ``_check_paper_buying_power`` at the later ``open_shadow_trade``
    call site remains the authoritative gate and the only increment
    point, so submission-vs-not accounting stays consistent even if BP
    changes between the pre-LLM precheck and order submission.

    Fail-closed on any error: if we cannot verify BP, skip the LLM
    (safer to miss a trade than to commit compute we can't fund).
    """
    global _scan_cycle_committed
    try:
        from src.shadow_trading.alpaca_adapter import get_account_info
        acct = get_account_info()
        buying_power = float(acct.get("buying_power", 0))
        effective_bp = buying_power - _scan_cycle_committed
        return allocation_dollars <= effective_bp
    except Exception as exc:
        logger.warning(
            "[SHADOW] Pre-LLM BP check failed: %s -- skipping LLM (fail-closed)",
            exc,
        )
        return False


def _record_bp_rejection_pre_llm(packet, db_path: str | None = None) -> None:
    """Record a BP-rejected shadow trade without LLM or order submission (Sprint 2 K).

    Mirrors the rejection-recording path at ``open_shadow_trade`` line 598
    so the dashboard and audit trail still show why a pre-LLM candidate
    was skipped, without the Ollama round-trip. Produces a
    ``status='rejected'`` / ``order_type='rejected_buying_power'`` row
    with no recommendation_id (no LLM rec was logged).
    """
    from src.journal.store import insert_shadow_trade
    from src.shadow_trading.models import ShadowTrade

    entry_price = _parse_price(packet.entry_zone)
    stop_price = _parse_price(packet.stop_invalidation)
    target_1_raw = packet.targets.split("/")[0] if packet.targets else "0"
    target_1 = _parse_price(target_1_raw)
    planned_allocation = packet.position_sizing.allocation_dollars
    planned_shares = (
        max(1, int(planned_allocation / entry_price)) if entry_price > 0 else 1
    )

    et = ZoneInfo("America/New_York")
    now = datetime.now(et)
    trade = ShadowTrade(
        recommendation_id=None,
        ticker=packet.ticker,
        direction="long",
        status="rejected",
        entry_price=entry_price,
        stop_price=stop_price,
        target_1=target_1,
        target_2=0.0,
        planned_shares=planned_shares,
        planned_allocation=planned_allocation,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )
    trade_data = trade.to_dict()
    trade_data["order_type"] = "rejected_buying_power"
    trade_data["actual_entry_price"] = entry_price
    trade_data["actual_entry_time"] = now.isoformat()
    trade_data["max_favorable_excursion"] = 0.0
    trade_data["max_adverse_excursion"] = 0.0
    if db_path is not None:
        insert_shadow_trade(trade_data, db_path)
    else:
        insert_shadow_trade(trade_data)


def _verify_and_update(trade_data: dict) -> None:
    """Verify order was accepted by Alpaca; update trade_data if rejected.

    Fix #352: Post-submission verification catches orders that Alpaca
    rejected after the SDK returned success.
    """
    if trade_data.get("alpaca_order_id"):
        from src.shadow_trading.alpaca_adapter import verify_order_accepted
        v = verify_order_accepted(trade_data["alpaca_order_id"])
        if v["verified"] is False:
            logger.error("[SHADOW] Order %s REJECTED (status=%s)",
                         trade_data["alpaca_order_id"], v["status"])
            trade_data["status"] = "rejected"
            trade_data["order_type"] = "rejected_by_broker"


def _parse_price(value) -> float:
    """Parse a price value that may be a string like '$78.82 area' or a float.

    WHY this exists: LLM output for entry_zone/stop_invalidation/targets is
    freeform text (e.g., "$78.82 area", "~195.00", "$42.50-43.00"). We need
    a reliable numeric extraction. The .split()[0] takes the first token
    after stripping $ and commas, which handles most LLM output formats.

    Fix for #181: Returns 0.0 on unparseable input instead of crashing.
    Callers check for entry_price <= 0 before proceeding.
    """
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


def _select_paper_broker(config: dict, score: float) -> tuple[str, object | None]:
    """Select paper broker based on score threshold.

    Returns (broker_name, broker_instance). When paper_routing is enabled
    and score >= threshold, routes to IB paper. Otherwise returns ("alpaca", None).
    If IB Gateway is down, falls back to Alpaca with a warning.
    """
    # SD#41 — IB cold storage. Skip IB paper routing entirely when dormant.
    if not config.get("trading", {}).get("ib_enabled", False):
        return "alpaca", None

    ib_cfg = config.get("live_trading", {}).get("ib", {})
    if not ib_cfg.get("paper_routing"):
        return "alpaca", None

    threshold = ib_cfg.get("paper_routing_threshold", 80)
    if score < threshold:
        return "alpaca", None

    # Score qualifies for IB — try to connect
    try:
        from src.trading.ib_broker import IBBroker
        broker = IBBroker(
            host=ib_cfg.get("host", "127.0.0.1"),
            port=ib_cfg.get("port", 4002),
            client_id=ib_cfg.get("client_id", 1),
            timeout=ib_cfg.get("timeout", 5),
        )
        broker._ensure_connected()
        logger.info("[ROUTING] Score %.0f >= %d threshold — routing to IB paper", score, threshold)
        return "ib", broker
    except Exception as e:
        logger.warning("[ROUTING] IB Gateway down — falling back to Alpaca (score %.0f): %s",
                       score, e)
        return "alpaca", None


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
    # WHY reject on ImportError: If the validator module can't load, we have no
    # guardrails against LLM hallucinations. Safer to skip the trade entirely.
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
        # Fix for #267: Default to 0.5 (fail-conservative) when multiplier
        # features are missing, not 1.0 (no penalty). A missing feature means
        # the upstream enrichment failed — we should reduce size, not ignore it.
        tl_mult = features.get("traffic_light_multiplier")
        if tl_mult is None:
            tl_mult = 0.5
            logger.warning("[RISK] traffic_light_multiplier missing for %s — defaulting to 0.5 (conservative)", packet.ticker)
        event_mult = _resolve_event_risk_multiplier(features, packet.ticker)
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

    # Hard governor cap (#hotfix 2026-04-13): DB-level count + combined caps.
    # Protects against the 20-open-vs-10-cap divergence observed today.
    if not _enforce_position_cap(config, db_path, packet.ticker, path="SHADOW"):
        return None

    ticker = packet.ticker

    # Fix for #99: Race condition duplicate check. Two scan cycles could both
    # see "no open trade for AAPL" and both try to open one. BEGIN IMMEDIATE
    # acquires an exclusive lock on the database before the SELECT, preventing
    # concurrent reads from seeing the same state. Falls back to non-atomic
    # check if the lock fails (e.g., another process holds the DB).
    #
    # Known limitation (#276): The BEGIN IMMEDIATE lock is released (ROLLBACK)
    # before the actual INSERT happens ~100 lines later, leaving a race window.
    # A second scan cycle could sneak in between the check and the insert.
    # Acceptable because the watch loop is single-threaded — concurrent scans
    # don't happen in practice. A true fix would keep the transaction open or
    # use INSERT ... WHERE NOT EXISTS, but that requires restructuring the
    # entire trade-creation flow.
    import sqlite3 as _sqlite3
    try:
        _dup_conn = _sqlite3.connect(db_path)
        _dup_conn.execute("BEGIN IMMEDIATE")
        _dup_row = _dup_conn.execute(
            "SELECT trade_id FROM shadow_trades WHERE ticker = ? AND status = 'open'"
            " AND COALESCE(quarantined, 0) = 0 LIMIT 1",
            (ticker,),
        ).fetchone()
        if _dup_row:
            _dup_conn.rollback()
            _dup_conn.close()
            logger.info("[SHADOW] Already have open trade for %s, skipping (atomic check)", ticker)
            return None
        _dup_conn.rollback()  # #276: lock released before insert — see comment above
        _dup_conn.close()
    except Exception as _dup_err:
        logger.warning("[SHADOW] Atomic duplicate check failed for %s: %s — falling back", ticker, _dup_err)
        existing = get_open_shadow_trade_for_ticker(ticker, db_path)
        if existing:
            logger.info("[SHADOW] Already have open trade for %s, skipping", ticker)
            return None

    # Fix #357: Also check Alpaca for ghost positions not tracked in DB
    try:
        from src.shadow_trading.alpaca_adapter import get_all_positions
        if any(p["symbol"] == ticker for p in get_all_positions()):
            logger.warning("[SHADOW] Ghost position detected for %s on Alpaca — skipping entry", ticker)
            return None
    except Exception as e:
        logger.warning("[SHADOW] Alpaca position check failed for %s: %s — proceeding with DB check only", ticker, e)

    # Parse packet values
    entry_price = _parse_price(packet.entry_zone)
    stop_price = _parse_price(packet.stop_invalidation)

    targets_parts = packet.targets.split("/")
    target_1 = _parse_price(targets_parts[0]) if len(targets_parts) >= 1 else 0.0
    target_2 = _parse_price(targets_parts[1]) if len(targets_parts) >= 2 else 0.0

    # #326: Reject bracket orders with invalid stop price. A stop_price of 0
    # means no stop-loss protection — the position has unlimited downside if the
    # system crashes or Alpaca doesn't fill a polling-based exit.
    if not stop_price or float(stop_price) <= 0:
        logger.error(
            "[EXECUTOR] Refusing bracket order for %s: stop_price=%s (must be > 0)",
            ticker, stop_price,
        )
        return None

    # Thorp-style graduated drawdown reduction — as drawdown increases,
    # position sizes decrease proportionally. At 20%+ DD, trading halts entirely.
    # Based on Kelly criterion / Thorp's risk management: the deeper the hole,
    # the harder it is to climb out, so reduce bet size to survive.
    try:
        from src.risk.governor import drawdown_adjusted_risk
        starting_capital = config.get("risk", {}).get("starting_capital", 100000)
        # Compute peak equity and current drawdown from closed trades
        with connect_db(db_path) as _conn:
            _row = _conn.execute(
                "SELECT COALESCE(SUM(pnl_dollars), 0) FROM shadow_trades WHERE status = 'closed'"
                " AND COALESCE(quarantined, 0) = 0"
            ).fetchone()
            total_pnl = _row[0] if _row else 0
            _peak_row = _conn.execute(
                "SELECT MAX(running_pnl) FROM ("
                "  SELECT SUM(pnl_dollars) OVER (ORDER BY updated_at) AS running_pnl"
                "  FROM shadow_trades WHERE status = 'closed' AND pnl_dollars IS NOT NULL"
                "  AND COALESCE(quarantined, 0) = 0"
                ")"
            ).fetchone()
            peak_pnl = _peak_row[0] if _peak_row and _peak_row[0] else max(total_pnl, 0)
        peak_equity = starting_capital + peak_pnl
        current_equity = starting_capital + total_pnl
        current_dd_pct = max(0, (peak_equity - current_equity) / peak_equity * 100) if peak_equity > 0 else 0

        if current_dd_pct > 0:
            from src.risk.governor import get_effective_risk_pct
            base_risk, _tier = get_effective_risk_pct(config, db_path)
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

    # Buying power check before paper entry
    if not _check_paper_buying_power(entry_price, planned_shares):
        trade_data["status"] = "rejected"
        trade_data["order_type"] = "rejected_buying_power"
        trade_data["actual_entry_price"] = entry_price
        trade_data["actual_entry_time"] = now.isoformat()
        trade_data["max_favorable_excursion"] = 0.0
        trade_data["max_adverse_excursion"] = 0.0
        insert_shadow_trade(trade_data, db_path)
        # Return None — trade was NOT opened. Callers check `if trade_id:`
        # to decide whether to count it as opened, send notifications, etc.
        # Returning trade_id here caused rejected trades to be counted as
        # opened trades, triggering false Telegram notifications and
        # inflating scan metrics.
        return None

    # Select paper broker: IB for high-score trades, Alpaca for the rest
    _paper_score = features.get("_score", 0)
    _paper_broker_name, _paper_broker = _select_paper_broker(config, _paper_score)
    trade_data["broker"] = _paper_broker_name

    # Strategy Decision #18: Mechanical bracket exits with 2.0 ATR multiplier.
    # Try bracket order first (entry + stop-loss + take-profit as one atomic
    # order). If bracket fails, fall back to simple market order.
    try:
        if _paper_broker_name == "ib" and _paper_broker is not None:
            # IB paper path — use broker abstraction.
            # Hotfix 2026-04-13: route IB integer order IDs to broker_order_id,
            # leaving alpaca_order_id NULL.  The #420 bug was caused by storing
            # IB integers in the Alpaca-UUID column, which made every
            # bracket_monitor / alpaca_adapter lookup fail with "badly formed
            # hexadecimal UUID string" and triggered the fall-through that
            # eventually led to premature stale-closure (today: COP/TGT/NEE).
            order = _paper_broker.place_bracket_order(
                ticker, planned_shares,
                take_profit_price=target_1, stop_loss_price=stop_price,
            )
            trade_data["broker_order_id"] = str(order.order_id)
            trade_data["alpaca_order_id"] = None
            trade_data["broker"] = "ib"
            trade_data["order_type"] = order.order_type
            if order.child_order_ids:
                import json as _json_route
                trade_data["ib_child_order_ids"] = _json_route.dumps(order.child_order_ids)
            fill_price = order.filled_avg_price
        else:
            # Alpaca paper path (default)
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
        if _paper_broker_name == "alpaca":
            _verify_and_update(trade_data)

    except Exception as e:
        logger.warning(f"[SHADOW] Bracket order failed for {ticker}: {e}, falling back to market")
        # Fix for #274: Bracket fallback — place market entry then IMMEDIATELY
        # submit a standalone stop-loss order. A naked entry without a broker-side
        # stop is unacceptable: if the system sleeps or crashes, unlimited downside.
        try:
            from src.shadow_trading.alpaca_adapter import place_paper_entry
            order = place_paper_entry(ticker, planned_shares)
            trade_data["alpaca_order_id"] = order.get("order_id")
            trade_data["order_type"] = "simple_with_stop"

            fill_price = order.get("filled_avg_price")
            if fill_price:
                trade_data["actual_entry_price"] = fill_price
            else:
                trade_data["actual_entry_price"] = entry_price
            trade_data["actual_entry_time"] = now.isoformat()
            trade_data["status"] = "open"
            trade_data["max_favorable_excursion"] = 0.0
            trade_data["max_adverse_excursion"] = 0.0
            _verify_and_update(trade_data)

            # Fix for #274: Immediately place standalone stop-loss protection.
            # If stop submission fails, CLOSE the position — an unprotected
            # position is worse than no position.
            try:
                from src.shadow_trading.alpaca_adapter import place_paper_exit
                from alpaca.trading.requests import StopOrderRequest
                from alpaca.trading.enums import OrderSide, TimeInForce
                client = None
                try:
                    from src.shadow_trading.alpaca_adapter import _get_trading_client
                    client = _get_trading_client()
                    stop_req = StopOrderRequest(
                        symbol=ticker,
                        qty=planned_shares,
                        side=OrderSide.SELL,
                        time_in_force=TimeInForce.GTC,
                        stop_price=round(stop_price, 2),
                    )
                    client.submit_order(stop_req)
                    logger.info("[SHADOW] Standalone stop placed for %s at $%.2f", ticker, stop_price)
                except Exception as stop_err:
                    logger.error(
                        "[SHADOW] CRITICAL: Entry filled but stop-loss failed for %s: %s — CLOSING position",
                        ticker, stop_err,
                    )
                    try:
                        place_paper_exit(ticker, planned_shares)
                        trade_data["status"] = "failed"
                        trade_data["order_type"] = "failed_no_stop"
                    except Exception as close_err:
                        logger.error("[SHADOW] EMERGENCY: Cannot close unprotected position %s: %s", ticker, close_err)
                    try:
                        from src.notifications.telegram import send_telegram
                        send_telegram(
                            f"🚨 UNPROTECTED POSITION: {ticker}\n"
                            f"Entry filled but stop-loss submission failed.\n"
                            f"Attempted emergency close: {'success' if trade_data.get('status') == 'failed' else 'FAILED'}"
                        )
                    except Exception as e:
                        logger.warning("[EXECUTOR] Unprotected position notification failed: %s", e)
            except ImportError:
                logger.warning("[SHADOW] Stop order imports unavailable for %s — position unprotected", ticker)

        except (ConnectionError, TimeoutError, OSError) as e2:
            # Network error — order may have been accepted by Alpaca.
            # Fix #359: Check Alpaca, retry if position doesn't exist.
            logger.warning("[SHADOW] Network error for %s: %s — checking Alpaca", ticker, e2)
            import time as _time
            _time.sleep(1)
            try:
                from src.shadow_trading.alpaca_adapter import get_all_positions
                if any(p["symbol"] == ticker for p in get_all_positions()):
                    logger.warning("[SHADOW] Ghost position detected for %s after network error", ticker)
                    trade_data["status"] = "submission_uncertain"
                    trade_data["order_type"] = "ghost_detected"
                else:
                    try:
                        order = place_paper_entry(ticker, planned_shares)
                        trade_data["alpaca_order_id"] = order.get("order_id")
                        trade_data["order_type"] = "retry_after_network_error"
                        fill_price = order.get("filled_avg_price")
                        trade_data["actual_entry_price"] = fill_price if fill_price else entry_price
                        trade_data["status"] = "open"
                    except Exception as retry_err:
                        logger.error("[SHADOW] Retry also failed for %s: %s", ticker, retry_err)
                        trade_data["status"] = "failed"
                        trade_data["order_type"] = "failed_after_retry"
            except Exception as check_err:
                logger.error("[SHADOW] Cannot verify Alpaca for %s: %s", ticker, check_err)
                trade_data["status"] = "submission_uncertain"
                trade_data["order_type"] = "failed_network"
            trade_data["actual_entry_price"] = trade_data.get("actual_entry_price", entry_price)
            trade_data["actual_entry_time"] = now.isoformat()
            trade_data["max_favorable_excursion"] = 0.0
            trade_data["max_adverse_excursion"] = 0.0
        except APIError as e2:
            # Alpaca API error. 400/403/422 = true rejection. 500+ = maybe accepted.
            sc = getattr(e2, 'status_code', None)
            if sc and sc >= 500:
                logger.warning("[SHADOW] Alpaca server error for %s (HTTP %s): %s", ticker, sc, e2)
                trade_data["status"] = "submission_uncertain"
                trade_data["order_type"] = f"api_error_{sc}"
            else:
                logger.error("[SHADOW] Alpaca rejected order for %s (HTTP %s): %s", ticker, sc, e2)
                trade_data["status"] = "rejected"
                trade_data["order_type"] = f"rejected_api_{sc}"
            trade_data["actual_entry_price"] = entry_price
            trade_data["actual_entry_time"] = now.isoformat()
            trade_data["max_favorable_excursion"] = 0.0
            trade_data["max_adverse_excursion"] = 0.0
        except Exception as e2:
            # Unknown error — code bug, not a broker issue
            logger.error("[SHADOW] Unexpected error for %s: %s", ticker, e2)
            trade_data["actual_entry_price"] = entry_price
            trade_data["actual_entry_time"] = now.isoformat()
            trade_data["status"] = "failed"
            trade_data["order_type"] = "failed"
            trade_data["max_favorable_excursion"] = 0.0
            trade_data["max_adverse_excursion"] = 0.0

    # Source tagging: paper trades always tagged as "paper"
    trade_data["source"] = "paper"

    # Strategy type tagging
    strategy_type = features.get("strategy_type", "pullback")
    trade_data["strategy_type"] = strategy_type

    # paper_only enforcement: override source for paper_only strategies
    strategy_cfg = config.get("strategies", {}).get(strategy_type, {})
    if strategy_cfg.get("paper_only", False):
        trade_data["source"] = "paper"

    # Strategy Decision #24: Outcome metadata for regime-conditional analysis.
    # Captures market context at entry so we can later slice performance by
    # regime (bull/bear), VIX level, and portfolio concentration. This data
    # feeds the CTO report and attribution system.
    trade_data["regime_at_entry"] = features.get("traffic_light", {}).get("regime_label", "")
    trade_data["ranking_at_entry"] = features.get("_rank", 0)
    try:
        open_count = len(get_open_shadow_trades(db_path))
        trade_data["concurrent_positions"] = open_count
    except Exception as exc:
        logger.warning("[ENTRY] Failed to count open positions: %s", exc)
        trade_data["concurrent_positions"] = 0
    try:
        import sqlite3 as _sq3
        with _sq3.connect(db_path) as _vc:
            _vr = _vc.execute(
                "SELECT vix FROM vix_term_structure ORDER BY collected_date DESC LIMIT 1"
            ).fetchone()
            trade_data["vix_at_entry"] = float(_vr[0]) if _vr else None
    except Exception as exc:
        logger.warning("[ENTRY] Failed to fetch VIX at entry: %s", exc)
        trade_data["vix_at_entry"] = None

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
            update_shadow_trade(trade_id, {
                "signal_price": signal_price,
                "implementation_shortfall_bps": round(is_bps, 2),
            }, db_path=db_path)
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
            extra={"ctx": {"event": "trade_open", "ticker": ticker}},
        )
        try:
            from src.api.websocket import broadcast_sync

            broadcast_sync(
                "trade_opened",
                {
                    "ticker": ticker,
                    "side": "BUY",
                    "source": trade_data.get("source", "paper"),
                    "trade_id": trade_id,
                    "broker": trade_data.get("broker", "alpaca"),
                    "shares": planned_shares,
                },
            )
        except Exception as exc:
            logger.warning("[SHADOW] broadcast trade_opened failed for %s: %s", ticker, exc)

        # 1F. Check for trade open milestones
        _check_open_milestones(db_path, source="paper")

        # 1K. Check sector exposure
        _check_sector_exposure(db_path)
    else:
        logger.error("[SHADOW] Recorded failed shadow trade for %s", ticker)

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
                target_price=float(target_1),
                alpaca_order_id=str(trade_data.get("alpaca_order_id") or ""),
                alpaca_fill_price=float(trade_data.get("actual_entry_price") or entry_price),
                db_path=db_path,
            )
    except Exception as e:
        logger.warning("[SHADOW-IB] Shadow logging failed (non-fatal): %s", e)

    return trade_id


# Fix for #196: Cap exit retries to prevent infinite exit order spam.
# After 3 failures, mark as exit_abandoned for reconciliation to handle.
_MAX_EXIT_RETRIES = 3


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
    """
    fill_price = float(filled_order.get("filled_avg_price") or 0)
    entry_price = float(trade.get("actual_entry_price") or trade.get("entry_price") or 0)
    shares = int(float(trade.get("planned_shares") or trade.get("shares") or 0))
    pnl_dollars = (fill_price - entry_price) * shares if entry_price else 0.0
    pnl_pct = ((fill_price - entry_price) / entry_price * 100) if entry_price else 0.0
    exit_time = (filled_order.get("filled_at")
                 or datetime.now(ZoneInfo("America/New_York")).isoformat())
    close_shadow_trade(
        trade["trade_id"],
        exit_price=fill_price,
        exit_time=exit_time,
        exit_reason=trade.get("exit_reason") or "late_fill_reconciled",
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
    from src.shadow_trading.alpaca_adapter import cancel_paper_order, get_order_status

    ticker = trade["ticker"]
    retry_count = int(trade.get("exit_retry_count") or 0)

    # Enforce max retry limit
    if retry_count >= _MAX_EXIT_RETRIES:
        logger.error("[RETRY] Max retries (%d) reached for %s — abandoning exit",
                     _MAX_EXIT_RETRIES, ticker)
        update_shadow_trade(trade["trade_id"], {"status": "exit_abandoned"}, db_path)
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
                _close_from_broker_fill(trade, prior, db_path)
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
                        _close_from_broker_fill(trade, filled, db_path)
                        return
                except Exception as e:
                    logger.warning(
                        "[RETRY] Post-cancel fill fetch failed for %s: %s",
                        ticker, e,
                    )
        time.sleep(1)  # Brief pause for broker to process cancellation

    # Increment retry counter
    update_shadow_trade(trade["trade_id"],
                        {"exit_retry_count": retry_count + 1}, db_path)

    shares = int(float(trade.get("shares") or trade.get("planned_shares") or 0))

    # D3 sync: don't retry against stale qty. If broker no longer holds the
    # position (qty <= 0), skip the submit and let reconcile close the trade.
    actual_qty, skip_reason = _sync_exit_qty(ticker, shares, broker_positions)
    if skip_reason:
        logger.warning(
            "[RETRY] %s position already closed at broker (qty=0) — "
            "marking exit_pending:%s for reconcile to finalize",
            ticker, skip_reason,
        )
        update_shadow_trade(
            trade["trade_id"],
            {"status": "exit_pending", "exit_reason": skip_reason},
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
        exit_result = _submit_exit_order(trade, shares)
        # Fix #360: Store exit order ID immediately for audit trail
        if isinstance(exit_result, dict) and exit_result.get("order_id"):
            update_shadow_trade(trade["trade_id"],
                                {"exit_order_id": exit_result["order_id"]}, db_path)
        exit_status = exit_result.get("status") if isinstance(exit_result, dict) else None
        if _is_filled_status(exit_status):
            fill_price = float(exit_result.get("filled_avg_price", 0))
            entry_price = float(trade.get("actual_entry_price") or trade.get("entry_price") or 0)
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
            logger.info("[RETRY] Exit still pending for %s (retry %d/%d)",
                        ticker, retry_count + 1, _MAX_EXIT_RETRIES)
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
    # Fix #245: timeout_days can be an int, a string (from YAML quoting or
    # SQLite TEXT affinity), or a dict {"default": 15, "pullback": 7} when
    # edited via the dashboard override API.  Resolve to int to prevent
    # "'<=' not supported between instances of 'str' and 'int'" at the
    # `days_open >= timeout_days` comparison below.
    _raw_timeout = shadow_cfg.get("timeout_days", 15)
    if isinstance(_raw_timeout, dict):
        _raw_timeout = _raw_timeout.get("default", 15)
    timeout_days = int(_raw_timeout)

    open_trades = get_open_shadow_trades(db_path)
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
            live_broker = get_live_broker(load_config())
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
        logger.debug("[EXECUTOR] Could not fetch positions for existence check: %s", e)

    for trade in open_trades:
        # Retry exit for failed exits instead of skipping
        if trade.get("status") in ("exit_pending", "exit_failed"):
            _retry_exit(trade, db_path, broker_positions=_alpaca_positions)
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
        current_price = _get_current_price_safe(ticker)
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
        update_shadow_trade(
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
                _mr_ohlcv = _get_recent_ohlcv_safe(ticker, days=10)
                if _mr_ohlcv is not None:
                    mr_exit = compute_mr_exit_signal(
                        ticker, _mr_ohlcv, entry_price, config)
                    if mr_exit:
                        mr_exit_price = mr_exit["exit_price"]
                        pnl = (mr_exit_price - entry_price) * shares
                        pnl_pct = ((mr_exit_price - entry_price) / entry_price * 100) if entry_price else 0
                        # Fix for #271: was missing exit_time and pnl_pct — caused TypeError
                        # silently swallowed by the except block at line 688.
                        close_shadow_trade(
                            trade["trade_id"],
                            exit_price=mr_exit_price,
                            exit_time=datetime.now(ZoneInfo("America/New_York")).isoformat(),
                            exit_reason=mr_exit["exit_reason"],
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
                close_shadow_trade(
                    trade["trade_id"],
                    exit_price=current_price,
                    exit_time=datetime.now(ZoneInfo("America/New_York")).isoformat(),
                    exit_reason="mr_timeout",
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
                    _broker_t4 = _glb_t4(load_config())
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
                                    exit_reason = "take_profit" if idx == 0 else "stop_loss"
                                    break
                            except ValueError:
                                continue
                else:
                    from src.shadow_trading.alpaca_adapter import get_order_status
                    order_status = get_order_status(trade["alpaca_order_id"])

                if not bracket_exit:
                    parent_status = order_status.get("status", "")
                    if parent_status in FILLED_ORDER_STATUSES:
                        exit_price = order_status.get("filled_avg_price")
                        if exit_price:
                            current_price = exit_price
                            bracket_exit = True
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
                update_shadow_trade(
                    trade["trade_id"],
                    {"status": "cancelled", "exit_reason": f"entry_unfilled_{exit_reason}"},
                    db_path,
                )
                actions.append({
                    "type": "cancelled_unfilled",
                    "ticker": ticker,
                    "trade_id": trade["trade_id"],
                    "reason": exit_reason,
                })
                continue

            # Exit slippage tracking
            signal_exit = current_price  # price that triggered exit
            exit_slippage_bps = 0.0

            if not bracket_exit:
                # D3 sync: verify broker has a position with sufficient qty
                # before submitting the sell. Prevents phantom exits (qty=0)
                # and qty-mismatch retries (planned > broker).
                _exit_qty, _skip_reason = _sync_exit_qty(
                    ticker, shares, _alpaca_positions,
                )
                if _skip_reason:
                    logger.warning(
                        "[EXIT] %s position already closed at broker "
                        "(qty=0) — marking exit_pending:%s for reconcile",
                        ticker, _skip_reason,
                    )
                    update_shadow_trade(
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
                        from src.shadow_trading.alpaca_adapter import cancel_paper_order
                        cancel_paper_order(_pending_oid)
                        time.sleep(0.5)
                    except Exception as e:
                        logger.warning("[EXECUTOR] Stale exit order cancellation failed: %s", e)

                try:
                    exit_result = _submit_exit_order(trade, shares)
                    # Fix #360: Store exit order ID immediately for audit trail
                    if isinstance(exit_result, dict) and exit_result.get("order_id"):
                        update_shadow_trade(trade["trade_id"],
                                            {"exit_order_id": exit_result["order_id"]}, db_path)
                except Exception as e:
                    logger.error("[EXIT] Broker exit failed for %s — marking exit_failed: %s", ticker, e, extra={"ctx": {"event": "exit_failed", "ticker": ticker, "trade_id": trade["trade_id"], "error": type(e).__name__}})
                    update_shadow_trade(
                        trade["trade_id"],
                        {"status": "exit_failed", "exit_reason": f"broker_exception:{type(e).__name__}"},
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
                            from src.notifications.telegram import send_telegram
                            send_telegram(
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
                        update_shadow_trade(
                            trade["trade_id"],
                            {
                                "status": "open",
                                "exit_reason": f"partial_{exit_reason}",
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
                        extra={"ctx": {"event": "exit_failed", "ticker": ticker, "trade_id": trade["trade_id"], "status": str(exit_status)}},
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
                    except Exception as exc:
                        logger.warning("[EXIT] Telegram notification failed for %s: %s", ticker, exc)
                    _exit_attempts += 1
                    _exit_failures += 1
                    continue

            _exit_attempts += 1  # Successful exit attempt
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
            logger.info(
                "[EXIT] Closed %s — P&L $%.2f (%.1f%%)", ticker, pnl_dollars, pnl_pct,
                extra={"ctx": {"event": "exit_success", "ticker": ticker,
                               "trade_id": trade["trade_id"],
                               "pnl_dollars": round(pnl_dollars, 2),
                               "pnl_pct": round(pnl_pct, 2),
                               "exit_reason": exit_reason}},
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

            try:
                from src.notifications.telegram import notify_trade_closed, is_telegram_enabled
                if is_telegram_enabled():
                    # Enriched context — fields are all nullable in shadow_trades;
                    # notify_trade_closed renders only what's present.
                    notify_trade_closed(
                        ticker,
                        pnl_dollars,
                        pnl_pct,
                        exit_reason,
                        days_open,
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
                    )
            except Exception as e:
                logger.warning("[SHADOW] Telegram notify_trade_closed failed for %s: %s", ticker, e)

            # 1F. Check for trade close milestones
            _check_close_milestones(db_path)

            # 1G. Check for loss streak
            _check_loss_streak(db_path)

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

    WHY separate from open_shadow_trade: Live trades use notional ordering
    (dollar amounts for fractional shares), different risk parameters,
    and stricter safety guards. The code paths diverge enough that
    combining them would create a fragile if/else maze.

    Returns trade_id on success, None on failure.
    """
    config = load_config()
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
        event_mult = _resolve_event_risk_multiplier(features, packet.ticker, path="LIVE")
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
        logger.error("[LIVE][RISK] Governor check failed for %s: %s — REJECTING live trade", packet.ticker, e)
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

    # Fix for #275: Daily loss guard — uses today's REALIZED losses from closed trades
    # plus unrealized P&L on today's open trades. The old version used all-time
    # unrealized P&L from all open trades (including positions opened weeks ago),
    # which meant a single old losing position could permanently block new entries,
    # while today's realized losses from closed trades were invisible.
    try:
        import sqlite3 as _sql275
        today_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        with _sql275.connect(db_path, timeout=10) as _conn275:
            _conn275.row_factory = _sql275.Row
            # Today's realized losses from closed live trades
            _realized_row = _conn275.execute(
                "SELECT COALESCE(SUM(pnl_dollars), 0) as total FROM shadow_trades "
                "WHERE status='closed' AND source='live' AND actual_exit_time LIKE ?"
                " AND COALESCE(quarantined, 0) = 0",
                (f"{today_str}%",),
            ).fetchone()
            today_realized = float(_realized_row["total"]) if _realized_row else 0.0

            # Today's unrealized P&L on live trades opened today
            _open_today = _conn275.execute(
                "SELECT ticker, actual_entry_price, entry_price, planned_shares "
                "FROM shadow_trades WHERE status='open' AND source='live' AND created_at LIKE ?"
                " AND COALESCE(quarantined, 0) = 0",
                (f"{today_str}%",),
            ).fetchall()

        today_unrealized = 0.0
        for t in _open_today:
            t_entry = float(t["actual_entry_price"] or t["entry_price"] or 0)
            if t_entry > 0:
                current = _get_current_price_safe(t["ticker"])
                if current:
                    today_unrealized += (current - t_entry) * int(float(t["planned_shares"] or 1))

        daily_live_pnl = today_realized + today_unrealized

        if starting_capital > 0 and daily_live_pnl < -(starting_capital * 0.05):
            logger.warning(
                "[LIVE] DAILY LOSS GUARD: Today's live P&L $%.2f (realized $%.2f + unrealized $%.2f) "
                "exceeds -5%% of $%.2f — HALTING for day",
                daily_live_pnl, today_realized, today_unrealized, starting_capital,
            )
            try:
                from src.notifications.telegram import notify_risk_alert, is_telegram_enabled
                if is_telegram_enabled():
                    notify_risk_alert(
                        "LIVE DAILY LOSS LIMIT",
                        f"Live daily P&L ${daily_live_pnl:.2f} (realized ${today_realized:.2f} "
                        f"+ unrealized ${today_unrealized:.2f}) exceeds -5% of ${starting_capital:.2f}. "
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

    # Hard governor cap (#hotfix 2026-04-13): DB-level count + combined caps,
    # so paper + live combined can never exceed the stricter configured limit.
    if not _enforce_position_cap(config, db_path, packet.ticker, path="LIVE"):
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
    # Fix #245: Cast to int — config values may arrive as strings.
    timeout_days = int(live_risk.get("timeout_days", 7))

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
    try:
        from src.trading.broker_factory import get_live_broker
        broker = get_live_broker(config)
        order = broker.place_bracket_order(
            ticker=ticker,
            quantity=planned_shares,
            take_profit_price=target_price,
            stop_loss_price=stop_price,
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
                "SELECT COUNT(*) FROM shadow_trades WHERE COALESCE(source,'paper') = ?"
                " AND COALESCE(quarantined, 0) = 0",
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
                " AND COALESCE(quarantined, 0) = 0"
            ).fetchone()[0]

            wins = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE status='closed' AND pnl_dollars > 0"
                " AND COALESCE(quarantined, 0) = 0"
            ).fetchone()[0]
            losses = closed_total - wins

            # Check milestone thresholds
            milestones = {1: "1st trade closed!", 10: "10th closed trade!",
                          25: "25th closed trade!", 50: "50th closed trade — Phase 1 gate!"}
            if closed_total in milestones:
                win_rate = wins / closed_total if closed_total > 0 else 0

                avg_row = conn.execute(
                    "SELECT AVG(pnl_dollars) as expectancy, AVG(duration_days) as avg_hold "
                    "FROM shadow_trades WHERE status='closed' AND COALESCE(quarantined, 0) = 0"
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
                    "WHERE status='closed' AND pnl_dollars > 0 AND COALESCE(quarantined, 0) = 0 "
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
                " AND COALESCE(quarantined, 0) = 0"
            ).fetchone()[0]
            if live_wins == 1:
                first_live_win = conn.execute(
                    "SELECT ticker, pnl_dollars, pnl_pct FROM shadow_trades "
                    "WHERE status='closed' AND source='live' AND pnl_dollars > 0 "
                    "AND COALESCE(quarantined, 0) = 0 "
                    "ORDER BY actual_exit_time ASC LIMIT 1"
                ).fetchone()
                if first_live_win:
                    notify_milestone(
                        "First live trade profit!",
                        f"{first_live_win['ticker']}: ${first_live_win['pnl_dollars']:+.2f} ({first_live_win['pnl_pct']:+.1f}%)"
                    )

            # 3 consecutive wins
            last_3 = conn.execute(
                "SELECT pnl_dollars FROM shadow_trades WHERE status='closed'"
                " AND COALESCE(quarantined, 0) = 0 "
                "ORDER BY actual_exit_time DESC LIMIT 3"
            ).fetchall()
            if len(last_3) == 3 and all(float(r["pnl_dollars"] or 0) > 0 for r in last_3):
                last_4 = conn.execute(
                    "SELECT pnl_dollars FROM shadow_trades WHERE status='closed'"
                    " AND COALESCE(quarantined, 0) = 0 "
                    "ORDER BY actual_exit_time DESC LIMIT 4"
                ).fetchall()
                # Only alert if the 4th-most-recent was NOT a win (to avoid repeat alerts)
                if len(last_4) < 4 or float(last_4[3]["pnl_dollars"] or 0) <= 0:
                    notify_milestone(
                        "3 consecutive wins!",
                        "Hot streak! Keep the discipline."
                    )

            # Best single trade P&L
            best_ever = conn.execute(
                "SELECT ticker, pnl_dollars, pnl_pct FROM shadow_trades "
                "WHERE status='closed' AND COALESCE(quarantined, 0) = 0"
                " ORDER BY pnl_dollars DESC LIMIT 1"
            ).fetchone()
            # The most recent closed trade
            latest = conn.execute(
                "SELECT ticker, pnl_dollars FROM shadow_trades "
                "WHERE status='closed' AND COALESCE(quarantined, 0) = 0"
                " ORDER BY actual_exit_time DESC LIMIT 1"
            ).fetchone()
            if (best_ever and latest and closed_total > 1
                    and best_ever["ticker"] == latest["ticker"]
                    and float(best_ever["pnl_dollars"] or 0) == float(latest["pnl_dollars"] or 0)
                    and float(best_ever["pnl_dollars"] or 0) > 0):
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
                "WHERE status='closed' AND COALESCE(quarantined, 0) = 0"
                " ORDER BY actual_exit_time DESC LIMIT 10"
            ).fetchall()

        if len(recent) < 3:
            return

        # Count consecutive losses from most recent
        streak = 0
        streak_trades = []
        for r in recent:
            if float(r["pnl_dollars"] or 0) < 0:
                streak += 1
                streak_trades.append((r["ticker"], r["pnl_pct"]))
            else:
                break

        if streak >= 3:
            # Only alert if this is exactly the streak boundary (3rd, 4th, etc.)
            # Check if streak was already 3+ before this trade
            prev_streak = 0
            for r in recent[1:]:
                if float(r["pnl_dollars"] or 0) < 0:
                    prev_streak += 1
                else:
                    break

            # Alert on first crossing of 3, or every additional loss after
            if streak == 3 or (streak > 3 and prev_streak < streak):
                max_dd = min(float(r["pnl_pct"] or 0) for r in recent[:streak])

                # Historical max streak
                with connect_db(db_path) as conn:
                    all_closed = conn.execute(
                        "SELECT pnl_dollars FROM shadow_trades WHERE status='closed'"
                        " AND COALESCE(quarantined, 0) = 0 "
                        "ORDER BY actual_exit_time ASC"
                    ).fetchall()
                max_streak = 0
                current = 0
                for r in all_closed:
                    if float(r["pnl_dollars"] or 0) < 0:
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
                " AND COALESCE(quarantined, 0) = 0"
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


def _get_recent_ohlcv_safe(ticker: str, days: int = 10):
    """Fetch recent OHLCV for a ticker (for MR exit checks). Returns DataFrame or None."""
    try:
        import yfinance as yf
        data = yf.download(ticker, period=f"{days}d", progress=False)
        if data is not None and not data.empty:
            return data
    except Exception as e:
        logger.debug("[OHLCV] yfinance fetch failed for %s: %s", ticker, e)
    return None


from src.risk.price_utils import _get_current_price_safe  # noqa: F401 — re-exported for back-compat
