"""Shadow trade execution flow: entry and exit monitoring.

This is the core trade lifecycle manager. Two main entry points:
  - open_shadow_trade(): Decision chain for paper trade entry (validation ->
    risk governor -> position limits -> duplicate check -> bracket order).
  - check_and_manage_open_trades(): Exit monitoring loop that checks all open
    positions against stops, targets, timeouts, and bracket fills.

Also includes open_live_trade() for real-money execution with additional
safety guards (capital guard, daily loss limit, LLM conviction required).

Phase 5 PR-C T10 split (2026-05-27): order-lifecycle helpers and the
``check_and_manage_open_trades`` / ``open_live_trade`` orchestrators were
extracted to ``src.shadow_trading.order_lifecycle``; state-reconciliation
primitives (``quarantine_trade``, milestone notifiers, sector exposure
alarm, OHLCV helper) moved to ``src.shadow_trading.reconciliation_engine``.
This module re-exports the moved symbols at top so the public-API contract
(``from src.shadow_trading.executor import X``) and the ``@patch(
"src.shadow_trading.executor.X")`` patch contract used by tests and
``scripts/daily_repo_audit.py`` remain intact.

Key issue cross-references:
  - #99: Race condition duplicate check (BEGIN IMMEDIATE)
  - #187: Failed shadow trades buying power check
  - #196: Duplicate exit orders (exit_retry_count + _MAX_EXIT_RETRIES)

Called by: api.routes.shadow, cli.commands, evaluation.backtester, packets.eod_recap, risk.governor, scheduler.watch, services.scan_service, services.shadow_service, shadow_trading.ledger
Calls: config, data_ingestion.market_data, evaluation.postmortem, journal.store, llm.postmortem_writer, llm.validator, models, notifications.telegram, risk.governor, shadow_trading.alpaca_adapter (cancel_paper_order), shadow_trading.models, shadow_trading.order_lifecycle, shadow_trading.reconciliation_engine, utils.activity_logger
Owns tables: none (reads/writes shadow_trades.exit_retry_count)
Config keys: bootcamp, enabled, live_trading, max_open_positions, max_positions, max_price, min_score, risk, shadow_trading, starting_capital, timeout_days
Tests: tests/test_expanded_notifications.py, tests/test_executor_import.py, tests/test_live_trading.py
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
from src.shadow_trading._status_sql import (
    active_in_clause,
    terminal_in_clause,
)
from src.shadow_trading.broker_exception_logger import log_and_persist
from src.shadow_trading.exit_reason import coerce_exit_reason
from src.shadow_trading.models import ShadowTrade
from src.notifications import safe_send
from src.notifications.telegram import send_telegram
from alpaca.common.exceptions import APIError

# Phase 5 PR-C T10: re-exports for backward-compatibility. Anything imported
# by `from src.shadow_trading.executor import X` MUST continue to resolve, and
# anything patched by `@patch("src.shadow_trading.executor.X")` MUST find an
# attribute on this module. The order_lifecycle / reconciliation_engine
# modules expose the canonical implementations; this file binds them as
# module attributes so both contracts hold.
from src.shadow_trading.order_lifecycle import (
    FILLED_ORDER_STATUSES,
    PENDING_ORDER_STATUSES,
    _MAX_EXIT_RETRIES,
    _CANCEL_TERMINAL_NO_SUBMIT,
    _is_filled_status,
    _is_pending_status,
    _submit_exit_order,
    _handle_pre_exit_cancel,
    _next_exit_retry_count,
    _should_abandon_exit,
    _sync_exit_qty,
    _close_from_broker_fill,
    _retry_exit,
    check_and_manage_open_trades,
    open_live_trade,
)
from src.shadow_trading.reconciliation_engine import (
    _sector_cache,
    _SECTOR_CACHE_TTL_S,
    quarantine_trade,
    _count_live_open_positions,
    _check_open_milestones,
    _check_close_milestones,
    _check_loss_streak,
    _check_sector_exposure,
    _get_recent_ohlcv_safe,
)

# #436 — alpaca.trading.requests / alpaca.trading.enums are hoisted to
# the module top so an ImportError surfaces at startup instead of
# silently bypassing the standalone-stop-loss fallback (which would
# leave a live position unprotected). _ALPACA_BRACKET_AVAILABLE is the
# canary callers check before attempting bracket / stop-order paths;
# when False, the executor must refuse new entries rather than enter
# unprotected.
try:
    from alpaca.trading.requests import StopOrderRequest  # noqa: F401
    from alpaca.trading.enums import OrderSide, TimeInForce  # noqa: F401
    _ALPACA_BRACKET_AVAILABLE = True
except ImportError:  # pragma: no cover — only fires when alpaca-py absent
    StopOrderRequest = None  # type: ignore[assignment]
    OrderSide = None  # type: ignore[assignment]
    TimeInForce = None  # type: ignore[assignment]
    _ALPACA_BRACKET_AVAILABLE = False

logger = logging.getLogger(__name__)

# Track 1.5 / B5 — instrumentation era sentinel.
# v3 = full instrumentation: B1 (exit slippage, e8ccf52) + B3 (exit_reason
# taxonomy + reconciliation, 8b94b95) + B4 (Key Risk persistence, 8c854c0)
# + B8 (LLM-set Expected Holding Period, 8c854c0) + this Round-1 schema
# stamping (c976a0c). Trades opened with this constant set to 3 are
# guaranteed to carry every Track 1.5 instrumentation field.
INSTRUMENTATION_VERSION_CURRENT = 3

# Track 1.5 / B8 — global fallback when LLM does not emit Expected Holding Period.
GLOBAL_DEFAULT_TIMEOUT_DAYS = 15


def _governor_cap(config: dict) -> int:
    """Return the effective open-position cap.

    Delegates to ``src.risk.governor.effective_position_cap`` so that the
    in-process governor (``RiskGovernor.__init__``) and this executor-side
    pre-flight check always agree on the strictest configured limit
    across the 4 cap namespaces (risk / risk_governor / live_trading /
    bootcamp).

    T1.04: the bootcamp early-return that previously short-circuited to
    ``bootcamp.max_positions`` was folded into the min-rule. Reason: an
    operator who set ``risk.max_open_positions: 5`` for live-trading
    safety and forgot to disable bootcamp would silently inherit the
    looser bootcamp cap (50). Under the min-rule the strictest setting
    always wins, which matches the 'deny by default' posture in §F-7
    of the 2026-04-27 trading-readiness audit.
    """
    from src.risk.governor import effective_position_cap
    return effective_position_cap(config)


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
        log_and_persist(
            ticker="UNKNOWN",
            operation="fetch_buying_power",
            broker="alpaca_paper",
            exc=exc,
            recoverable=False,
            outcome="persisted",
        )
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
        log_and_persist(
            ticker="UNKNOWN",
            operation="fetch_buying_power",
            broker="alpaca_paper",
            exc=exc,
            recoverable=False,
            outcome="persisted",
        )
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


def open_shadow_trade_with_reason(
    recommendation_id: str,
    packet: "TradePacket",
    features: dict,
    db_path: str = DB_PATH,
) -> "tuple[str | None, str | None]":
    """Same as open_shadow_trade but also returns the rejection reason.

    #511 — diagnostic wrapper for callers that need to surface why a
    candidate was rejected (mr_scan_service, dashboard rejection feed).
    Avoids changing open_shadow_trade's signature which has many callers.

    Strategy: run the governor check explicitly first to capture
    rejection_reason from the structured result. If approved, delegate
    to open_shadow_trade for actual execution. The governor pre-check is
    redundant (open_shadow_trade re-runs it internally) but harmless and
    necessary to obtain the reason string before the executor's [GOVERNOR]
    log line consumes it.

    Returns:
        (trade_id, None) on success
        (None, "rejection reason") on rejection (governor / BP / dup / etc.)
        (None, "internal error: ...") on unexpected exception
    """
    try:
        from src.risk.governor import RiskGovernor, get_portfolio_state
        cfg = load_config()
        portfolio = get_portfolio_state(db_path)
        gov = RiskGovernor(cfg)
        tl_mult = features.get("traffic_light_multiplier", 0.5)
        event_mult = _resolve_event_risk_multiplier(features, packet.ticker, path="MR")
        check = gov.check_trade(
            packet.ticker,
            packet.position_sizing.allocation_dollars,
            features,
            portfolio,
            traffic_light_multiplier=tl_mult,
            event_risk_multiplier=event_mult,
        )
        if not check["approved"]:
            return (None, check.get("rejection_reason", "rejected (no reason captured)"))
    except Exception as e:
        logger.debug(
            "[MR-WRAPPER] governor pre-check failed for %s: %s",
            packet.ticker, e,
        )
        # Fall through — let open_shadow_trade do its own checks

    try:
        trade_id = open_shadow_trade(recommendation_id, packet, features, db_path)
        if trade_id:
            return (trade_id, None)
        return (
            None,
            "rejected by executor (post-governor check failed — "
            "see [SHADOW] log for detail)",
        )
    except Exception as e:
        logger.warning(
            "[MR-WRAPPER] open_shadow_trade raised for %s: %s",
            packet.ticker, e,
        )
        return (None, f"internal error: {type(e).__name__}: {e}")


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

    # Graceful PAUSE gate (design D10): block NEW autonomous trades while the
    # operator has engaged a graceful pause. Positions / monitoring / reconcile
    # are NOT gated here — only this new-trade entry point. Distinct from the
    # governor's hard kill switch; this is a cheap single-row DB read.
    from src.console.pause import is_paused
    if is_paused():
        logger.info("[PAUSE] Graceful pause active — skipping new shadow trade for %s", packet.ticker)
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
    # see "no open trade for AAPL" and both try to open one. SQLite needs
    # BEGIN IMMEDIATE to acquire a reserved lock before the SELECT, preventing
    # concurrent reads from seeing the same state. PG's default READ COMMITTED
    # isolation provides equivalent semantics without an explicit BEGIN
    # (and BEGIN IMMEDIATE is a SQLite-only keyword that throws on PG).
    #
    # Known limitation (#276): The lock is released before the actual INSERT
    # happens ~100 lines later, leaving a race window. A second scan cycle
    # could sneak in between the check and the insert. Acceptable because
    # the watch loop is single-threaded — concurrent scans don't happen in
    # practice. A true fix would keep the transaction open or use INSERT ...
    # WHERE NOT EXISTS, but that requires restructuring the entire
    # trade-creation flow.
    #
    # W21 cleanup (P0-2): engine-aware to silence the noisy
    # `syntax error at or near "IMMEDIATE"` warning that fired ~18 times in
    # the last week of logs since the PG cutover. The fallback path was
    # always running correctly; only the warning was misleading.
    from src.utils.db import PostgresConnectionWrapper
    try:
        with connect_db(db_path) as _dup_conn:
            _is_pg_conn = isinstance(_dup_conn, PostgresConnectionWrapper)
            if not _is_pg_conn:
                _dup_conn.execute("BEGIN IMMEDIATE")
            _a_frag_dup, _a_params_dup = active_in_clause()
            _dup_row = _dup_conn.execute(
                f"SELECT trade_id FROM shadow_trades WHERE ticker = ? AND status IN ({_a_frag_dup})"
                " AND COALESCE(quarantined, 0) = 0 LIMIT 1",
                (ticker, *_a_params_dup),
            ).fetchone()
            if _dup_row:
                if not _is_pg_conn:
                    _dup_conn.rollback()
                logger.info("[SHADOW] Already have open trade for %s, skipping (atomic check)", ticker)
                return None
            if not _is_pg_conn:
                _dup_conn.rollback()  # #276: lock released before insert — see comment above
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
        log_and_persist(
            ticker=ticker,
            operation="fetch_positions",
            broker="alpaca_paper",
            exc=e,
            recoverable=True,
            outcome="persisted",
        )
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
        _t_frag_dd, _t_params_dd = terminal_in_clause()
        with connect_db(db_path) as _conn:
            _row = _conn.execute(
                f"SELECT COALESCE(SUM(pnl_dollars), 0) FROM shadow_trades WHERE status IN ({_t_frag_dd})"
                " AND COALESCE(quarantined, 0) = 0",
                _t_params_dd,
            ).fetchone()
            total_pnl = _row[0] if _row else 0
            _peak_row = _conn.execute(
                "SELECT MAX(running_pnl) FROM ("
                "  SELECT SUM(pnl_dollars) OVER (ORDER BY updated_at) AS running_pnl"
                f"  FROM shadow_trades WHERE status IN ({_t_frag_dd}) AND pnl_dollars IS NOT NULL"
                "  AND COALESCE(quarantined, 0) = 0"
                ")",
                _t_params_dd,
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
                        _today_iso = datetime.now().date().isoformat()
                        _alert_row = _conn.execute(
                            "SELECT 1 FROM activity_log WHERE event_type = ? AND detail LIKE ? AND created_at > ?",
                            (alert_key, f"%{int(threshold)}%", _today_iso)
                        ).fetchone()
                        if not _alert_row:
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
        # B2.B: persist bracket failure but DO NOT re-raise — the fallback to
        # market order below is deliberate resilience. Re-raising would abandon
        # the trade entirely instead of entering with a standalone stop.
        # Per B2 design Risk R1: this is the one site where persist + continue
        # is correct policy. (All other sites use persist + re-raise.)
        log_and_persist(
            ticker=ticker,
            operation="place_bracket_order",
            broker="alpaca_paper",
            exc=e,
            recoverable=True,
            outcome="persisted",
        )
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

            # Fix for #274 + #436: Immediately place standalone stop-loss
            # protection. If stop submission fails, CLOSE the position —
            # an unprotected position is worse than no position. The
            # alpaca.trading symbols are hoisted to module top (#436), so
            # an SDK-missing failure surfaces at startup. If somehow this
            # branch is reached without the SDK, fail-loud and emergency-
            # close instead of silently leaving the position unprotected.
            from src.shadow_trading.alpaca_adapter import place_paper_exit
            if not _ALPACA_BRACKET_AVAILABLE:
                logger.error(
                    "[SHADOW] CRITICAL: alpaca.trading SDK unavailable for %s — "
                    "cannot place stop. Emergency-closing position to avoid "
                    "unprotected exposure (#436).", ticker,
                )
                try:
                    place_paper_exit(ticker, planned_shares)
                    trade_data["status"] = "failed"
                    trade_data["order_type"] = "failed_sdk_missing"
                except Exception as close_err:
                    log_and_persist(
                        ticker=ticker,
                        operation="place_exit",
                        broker="alpaca_paper",
                        exc=close_err,
                        recoverable=False,
                        outcome="persisted",
                    )
                    logger.error(
                        "[SHADOW] EMERGENCY: Cannot close unprotected position %s: %s",
                        ticker, close_err,
                    )
                try:
                    send_telegram(
                        f"🚨 UNPROTECTED POSITION (SDK MISSING): {ticker}\n"
                        f"alpaca.trading imports unavailable. Attempted emergency "
                        f"close: {'success' if trade_data.get('status') == 'failed' else 'FAILED'}"
                    )
                except Exception as notify_err:
                    logger.warning(
                        "[EXECUTOR] Unprotected position notification failed: %s",
                        notify_err,
                    )
            else:
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
                    log_and_persist(
                        ticker=ticker,
                        operation="place_stop_order",
                        broker="alpaca_paper",
                        exc=stop_err,
                        recoverable=False,
                        outcome="persisted",
                    )
                    logger.error(
                        "[SHADOW] CRITICAL: Entry filled but stop-loss failed for %s: %s — CLOSING position",
                        ticker, stop_err,
                    )
                    try:
                        place_paper_exit(ticker, planned_shares)
                        trade_data["status"] = "failed"
                        trade_data["order_type"] = "failed_no_stop"
                    except Exception as close_err:
                        log_and_persist(
                            ticker=ticker,
                            operation="place_exit",
                            broker="alpaca_paper",
                            exc=close_err,
                            recoverable=False,
                            outcome="persisted",
                        )
                        logger.error("[SHADOW] EMERGENCY: Cannot close unprotected position %s: %s", ticker, close_err)
                    try:
                        send_telegram(
                            f"🚨 UNPROTECTED POSITION: {ticker}\n"
                            f"Entry filled but stop-loss submission failed.\n"
                            f"Attempted emergency close: {'success' if trade_data.get('status') == 'failed' else 'FAILED'}"
                        )
                    except Exception as e:
                        logger.warning("[EXECUTOR] Unprotected position notification failed: %s", e)

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
                        log_and_persist(
                            ticker=ticker,
                            operation="place_market_order",
                            broker="alpaca_paper",
                            exc=retry_err,
                            recoverable=False,
                            outcome="persisted",
                        )
                        logger.error("[SHADOW] Retry also failed for %s: %s", ticker, retry_err)
                        trade_data["status"] = "failed"
                        trade_data["order_type"] = "failed_after_retry"
            except Exception as check_err:
                log_and_persist(
                    ticker=ticker,
                    operation="fetch_positions",
                    broker="alpaca_paper",
                    exc=check_err,
                    recoverable=False,
                    outcome="persisted",
                )
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
            log_and_persist(
                ticker=ticker,
                operation="place_market_order",
                broker="alpaca_paper",
                exc=e2,
                recoverable=False,
                outcome="persisted",
            )
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

    # Track 1.5 / B5 + B8 — open-path instrumentation stamps.
    trade_data["instrumentation_version"] = INSTRUMENTATION_VERSION_CURRENT
    llm_timeout = getattr(packet, "llm_timeout_days", None)
    trade_data["llm_timeout_days"] = llm_timeout
    trade_data["timeout_days"] = llm_timeout if llm_timeout is not None else GLOBAL_DEFAULT_TIMEOUT_DAYS

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

    # #614 — Persist trade-open to activity_log for the dashboard feed.
    # Pre-fix the TRADE_OPENED constant existed but had zero writers.
    #
    # Sprint 0 / Wave 1c / EXEC-TRADEOPENED: the original payload referenced
    # `shares` and `source_filter`, neither of which is in scope here. The
    # local for share count is `planned_shares`; `source_filter` is a parameter
    # of `check_and_manage_open_trades` (a DIFFERENT function). Pre-fix the
    # NameError was silently swallowed by the catch handler below (DEBUG
    # level), so the dashboard "trades opened" feed had been blind since
    # this commit shipped. Now the payload uses the in-scope locals and the
    # catch handler logs at WARNING — observability infra failures must not
    # be invisible. We also forward the executor's db_path so callers running
    # against a non-default DB (tests, multi-DB tooling) write to the right
    # place.
    try:
        import json as _json_to
        from src.utils.activity_logger import TRADE_OPENED, log_activity
        log_activity(
            TRADE_OPENED,
            _json_to.dumps({
                "trade_id": trade_id,
                "ticker": ticker,
                "shares": planned_shares,
                "entry_price": entry_price,
                "source": trade_data.get("source", "paper"),
            }),
            db_path=db_path,
        )
    except Exception as _e_to:
        logger.warning("[EXECUTOR] activity_log TRADE_OPENED failed: %s", _e_to)

    return trade_id


from src.risk.price_utils import _get_current_price_safe  # noqa: F401 — re-exported for back-compat
