"""Overnight and off-hours task functions extracted from watch.py.

These are standalone module-level functions for tasks that run outside
market hours: post-close capture, training collection, data collection,
VRAM handoffs, pre-market pipeline, council sessions, etc.

Originally methods on the WatchLoop class; moved here to reduce watch.py
line count and improve testability. Each function takes explicit parameters
instead of relying on ``self``.
"""

import logging
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.notifications import safe_send
from src.utils.db import _scalar, connect_db

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


def _is_collector_error(result) -> bool:
    """Classify a collector return value as success or failure.

    #623 — Pre-fix used `'error' in str(result).lower()` which matched
    successful return dicts containing `'errors': 0` as a substring,
    producing 8 false ERROR rows / 3-day window. Now interrogates the
    structure directly: an explicit `error` key (or a string starting with
    "Error") signals failure; an `errors` count of 0 with at least one
    processed item is success.
    """
    if isinstance(result, str):
        return result.lower().startswith("error")
    if isinstance(result, dict):
        if result.get("error") not in (None, "", 0, False):
            return True
        # All-failed batch: errors > 0 AND nothing processed.
        errors = result.get("errors")
        if isinstance(errors, int) and errors > 0:
            processed = result.get("tickers_processed", 0)
            if not processed:
                return True
    return False


def run_postclose_reconciliation():
    """Reconcile paper positions against Alpaca and send Telegram summary."""
    from src.shadow_trading.reconcile_dispatch import reconcile_all_paper_trades

    all_results = reconcile_all_paper_trades(db_path=DB_PATH)

    # Use swing result for the Telegram summary; research desk failures are
    # already logged inside reconcile_all_paper_trades.
    result = all_results.get("swing", {})

    if result.get("error"):
        msg = f"[Reconcile] Alpaca API error -- skipped: {result['error']}"
        logger.warning("[WATCH] %s", msg)
        try:
            from src.notifications.telegram import send_telegram, is_telegram_enabled
            if is_telegram_enabled():
                send_telegram(f"\u26a0\ufe0f {msg}")
        except Exception:
            pass
        return

    orphaned = result["orphaned"]
    unresolved_stale = result.get("unresolved_stale", result["stale"])
    resolved_stale = result.get("resolved_stale", result.get("marked_closed", []))
    discrep = result["discrepancies"]
    backfilled = result["backfilled"]

    if not orphaned and not unresolved_stale and not discrep:
        msg = (
            f"[OK] Reconciliation: {result['local_count']} local / "
            f"{result['alpaca_count']} Alpaca -- all matched"
        )
        if resolved_stale:
            msg += f" (auto-closed stale: {resolved_stale})"
    else:
        parts = []
        if orphaned:
            parts.append(f"{len(orphaned)} orphaned (backfilled: {backfilled})")
        if unresolved_stale:
            tickers = [s["ticker"] for s in unresolved_stale]
            parts.append(f"{len(unresolved_stale)} unresolved stale: {tickers}")
        if resolved_stale:
            parts.append(f"{len(resolved_stale)} auto-closed stale: {resolved_stale}")
        if discrep:
            parts.append(f"{len(discrep)} mismatched")
        msg = f"[FAIL] Reconciliation: {', '.join(parts)}"

    logger.info("[WATCH] %s", msg)
    try:
        from src.notifications.telegram import send_telegram, is_telegram_enabled
        if is_telegram_enabled():
            send_telegram(msg)
    except Exception as e:
        logger.warning("[WATCH] Reconciliation Telegram alert failed: %s", e)


def run_daily_audit():
    """Run the daily auditor agent."""
    from src.evaluation.auditor import run_daily_audit, check_escalation
    from src.email.notifier import send_email
    from src.shadow_trading.exit_reconciliation import run_exit_reconciliation

    print("[WATCH] Running daily audit...")
    audit = run_daily_audit()
    assessment = audit.get("overall_assessment", "green")
    summary = (audit.get("summary") or "")[:200]
    print(f"[WATCH] Audit: {assessment} -- {summary}")

    # Check for escalation
    actions = check_escalation(audit)
    for action in actions:
        print(f"[WATCH] Escalation: {action['action']} ({action['severity']})")

    # Send alert if red or yellow
    if assessment == "red":
        subject = "[TRADE DESK] DAILY AUDIT -- RED"
        send_email(subject, f"Assessment: RED\n\n{audit.get('summary', '')}")
    elif assessment == "yellow":
        logger.info("[AUDIT] Yellow assessment -- included in EOD recap")

    # CUSUM performance change detection
    try:
        from src.evaluation.change_detector import check_performance_drift
        change = check_performance_drift()
        if change and change.get("alarm"):
            alarm_msg = f"[CUSUM] Performance change detected: {change.get('direction', 'negative')} shift"
            logger.warning(alarm_msg)
            print(f"[WATCH] {alarm_msg}")
            try:
                from src.notifications.telegram import send_telegram
                send_telegram(f"\u26a0\ufe0f CUSUM ALARM\n{alarm_msg}\nDetails: {change.get('detail', '')}")
            except Exception as e:
                logger.warning("[WATCH] CUSUM Telegram alert failed: %s", e)
    except Exception as e:
        logger.debug("[AUDIT] CUSUM check failed: %s", e)

    # Leakage detection
    try:
        from src.training.leakage_detector import run_leakage_check
        leakage = run_leakage_check()
        if leakage and leakage.get("balanced_accuracy", 0) > 0.65:
            leak_msg = f"[LEAKAGE] Balanced accuracy {leakage['balanced_accuracy']:.1%} > 65% threshold"
            logger.warning(leak_msg)
            try:
                from src.notifications.telegram import send_telegram
                send_telegram(f"\U0001f534 LEAKAGE ALERT\n{leak_msg}")
            except Exception as e:
                logger.warning("[WATCH] Leakage Telegram alert failed: %s", e)
    except ImportError:
        pass
    except Exception as e:
        logger.debug("[AUDIT] Leakage check failed: %s", e)

    try:
        run_exit_reconciliation()
    except Exception as e:
        logger.warning("[AUDIT] Exit reconciliation failed: %s", e)


def run_training_collection():
    """Collect training data from closed trades."""
    from src.training.data_collector import collect_training_examples_from_closed_trades
    print("[WATCH] Running training data collection...")
    count = collect_training_examples_from_closed_trades()
    print(f"[WATCH] Training data collection: {count} new examples generated")


def run_training_check():
    """Check if fine-tuning should be triggered."""
    from src.training.trainer import should_train, run_fine_tune
    trigger, reason = should_train()
    if trigger:
        print(f"[WATCH] Training triggered: {reason}")
        result = run_fine_tune()
        if result:
            print(f"[WATCH] Training complete: {result['version_name']}")
            # ── Telegram: notify_model_event ──
            safe_send(
                "model_event",
                event="TRAINING COMPLETE",
                model_name=result.get("version_name", "unknown"),
                detail=f"Reason: {reason}",
            )
        else:
            print("[WATCH] Training failed. Check logs.")
    else:
        print(f"[WATCH] Training not needed: {reason}")


def run_saturday_reports(db_path: str = DB_PATH):
    """Generate and send Saturday training and CTO reports."""
    from src.training.report import generate_training_report
    from src.email.notifier import send_email

    # Training report
    print("[WATCH] Generating Saturday training report...")
    report = generate_training_report()
    print(report)
    subject = "[TRADE DESK] Weekly Training Report"
    send_email(subject, report)
    print("[WATCH] Training report email sent.")

    # ── Telegram: notify_retrain_report ──
    from src.training.versioning import get_active_model_name, get_training_example_counts
    model_name = get_active_model_name()
    counts = get_training_example_counts()
    _retrain_total = counts.get("total", 0)
    try:
        from datetime import timedelta as _td
        with connect_db(db_path) as _rc:
            _week_ago = (datetime.now(ET) - _td(days=7)).isoformat()
            _row = _rc.execute(
                "SELECT COUNT(*) FROM training_examples WHERE created_at > ?",
                (_week_ago,)
            ).fetchone()
            _new_wk = _scalar(_row)
            _row = _rc.execute(
                "SELECT COUNT(*) FROM training_examples WHERE created_at > ? AND source LIKE '%paper%'",
                (_week_ago,)
            ).fetchone()
            _new_paper = _scalar(_row)
    except Exception:
        _new_wk = 0
        _new_paper = 0
    safe_send(
        "retrain_report",
        model_name=model_name,
        training_examples=_retrain_total,
        prev_examples=_retrain_total - _new_wk,
        new_this_week=_new_wk,
        new_paper=_new_paper,
        new_live=0,
        canary_status="STABLE",
        perplexity=0.0,
        prev_perplexity=0.0,
        distinct2=0.0,
        prev_distinct2=0.0,
        champion_challenger="N/A",
    )

    # Weekly deep audit
    try:
        from src.evaluation.auditor import run_weekly_audit
        print("[WATCH] Running weekly deep audit...")
        weekly = run_weekly_audit(days=7)
        print(f"[WATCH] Weekly audit: {weekly.get('overall_assessment', 'n/a')}")
    except Exception as e:
        logger.error("[WATCH] Weekly audit failed: %s", e)
        print(f"[WATCH] Weekly audit failed: {e}")

    # CTO performance report
    try:
        from src.evaluation.cto_report import generate_cto_report, format_cto_report
        print("[WATCH] Generating CTO performance report...")
        cto_data = generate_cto_report(days=7)
        cto_text = format_cto_report(cto_data)
        print(cto_text)
        cto_subject = f"[TRADE DESK] CTO Performance Report ({cto_data['report_period']['start']} to {cto_data['report_period']['end']})"
        send_email(cto_subject, cto_text)
        print("[WATCH] CTO report email sent.")
    except Exception as e:
        logger.error("[WATCH] CTO report failed: %s", e)
        print(f"[WATCH] CTO report failed: {e}")


def log_overnight_task(task_name: str, status: str,
                       started_at: str, finished_at: str | None = None,
                       result: str | None = None, error: str | None = None):
    """Log overnight task result to activity log."""
    try:
        from src.logging.activity import log_activity
        detail = f"{task_name}: {status}"
        if result:
            detail += f" -- {result}"
        if error:
            detail += f" -- ERROR: {error}"
        log_activity("overnight_task", detail)
    except Exception as e:
        logger.debug("[WATCH] Failed to log overnight task: %s", e)


def run_model_regression_check():
    """5:05 PM ET — Check if current model underperforms previous on live trades."""
    from src.evaluation.model_monitor import check_model_regression

    result = check_model_regression()
    logger.info("[MODEL_MONITOR] Regression check: %s -- %s",
                result["status"], result["message"])

    if result["status"] == "critical":
        try:
            from src.notifications.telegram import send_telegram
            send_telegram(
                f"\U0001f6a8 MODEL REGRESSION CRITICAL\n{result['message']}")
        except Exception as e:
            logger.warning("[MODEL_MONITOR] Telegram alert failed: %s", e)
    elif result["status"] == "warning":
        try:
            from src.notifications.telegram import send_telegram
            send_telegram(
                f"\u26a0\ufe0f Model regression warning\n{result['message']}")
        except Exception as e:
            logger.warning("[MODEL_MONITOR] Telegram alert failed: %s", e)


def run_post_close_capture():
    """5:30 PM ET — Capture final closing prices, update MFE/MAE on open positions."""
    from src.api.websocket import broadcast_sync
    from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark
    from src.journal.store import get_open_shadow_trades, update_shadow_trade
    from src.universe.sp100 import get_sp100_universe

    try:
        broadcast_sync("overnight_task", {"task": "post_close_capture", "status": "started"})
    except Exception as e:
        logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

    logger.info("[OVERNIGHT] Running post-close capture...")
    print("[WATCH] Running post-close capture...")

    universe = get_sp100_universe()
    ohlcv = fetch_ohlcv(universe)
    count = len(ohlcv)
    print(f"[WATCH] Fetched closing data for {count} tickers")

    # Update MFE/MAE on open positions
    open_trades = get_open_shadow_trades()
    updated = 0
    for trade in open_trades:
        ticker = trade["ticker"]
        if ticker in ohlcv and not ohlcv[ticker].empty:
            try:
                close_price = float(ohlcv[ticker].iloc[-1].get("close", 0))
                entry = trade.get("actual_entry_price") or trade.get("entry_price", 0)
                if entry and close_price:
                    pnl_pct = (close_price - entry) / entry * 100
                    current_mfe = trade.get("mfe_pct") or 0
                    current_mae = trade.get("mae_pct") or 0
                    new_mfe = max(current_mfe, pnl_pct)
                    new_mae = min(current_mae, pnl_pct)
                    update_shadow_trade(trade["trade_id"],
                                        {"mfe_pct": new_mfe, "mae_pct": new_mae})
                    updated += 1
            except Exception as e:
                logger.warning("[OVERNIGHT] MFE/MAE update failed for %s: %s", ticker, e)

    # Log daily regime from SPY close (with retry and fallback)
    spy = fetch_spy_benchmark()
    spy_close = spy.iloc[-1].get("close", 0) if not spy.empty else 0
    if spy_close == 0:
        import time as _time
        logger.info("[OVERNIGHT] SPY close returned $0, retrying in 5 minutes...")
        _time.sleep(300)
        spy = fetch_spy_benchmark()
        spy_close = spy.iloc[-1].get("close", 0) if not spy.empty else 0
    if spy_close == 0 and "SPY" in ohlcv and not ohlcv["SPY"].empty:
        spy_close = float(ohlcv["SPY"].iloc[-1].get("close", 0))
        logger.info("[OVERNIGHT] SPY close from OHLCV fallback: %.2f", spy_close)
    if spy_close > 0:
        logger.info("[OVERNIGHT] SPY close: %.2f", spy_close)
    else:
        logger.warning("[OVERNIGHT] SPY close unavailable")

    print(f"[WATCH] Post-close capture complete: {count} tickers, {updated} MFE/MAE updates")
    log_overnight_task("post_close_capture", "completed",
                       datetime.now(ET).isoformat(), datetime.now(ET).isoformat(),
                       result=f"tickers={count}, mfe_mae={updated}")

    try:
        broadcast_sync("overnight_task", {"task": "post_close_capture", "status": "complete",
                                          "tickers_updated": count, "mfe_mae_updated": updated})
    except Exception as e:
        logger.warning("[WATCH] broadcast overnight_task failed: %s", e)


def _alert_training_silent_failure(result) -> None:
    """Emit ERROR log + Telegram alert when collection produced 0 examples
    despite real work (stage-1 failures or rejections). #615 — without
    this, the 4/13–4/23 outage was indistinguishable from "no closed
    trades to collect from"."""
    logger.error(
        "[TRAINING] Collection produced 0 examples despite work — "
        "stage1_failures=%s rejected=%s halted=%s halt_reason=%s",
        result.stage1_failures, result.rejected, result.halted, result.halt_reason,
    )
    try:
        from src.notifications.telegram import send_telegram, is_telegram_enabled
        if is_telegram_enabled():
            send_telegram(
                f"🛑 TRAINING SILENT FAILURE: 0 examples written despite "
                f"{result.stage1_failures} Stage-1 failures + "
                f"{result.rejected} validator rejections. "
                f"Halt reason: {result.halt_reason or 'none'}"
            )
    except Exception as exc:
        logger.warning("[TRAINING] silent-failure alert failed: %s", exc)


def run_overnight_training_collection():
    """6:00 PM ET — Collect training examples from today's closed trades."""
    from src.api.websocket import broadcast_sync
    from src.training.data_collector import (
        collect_training_examples_from_closed_trades_detailed,
    )

    try:
        broadcast_sync("overnight_task", {"task": "training_collection", "status": "started"})
    except Exception as e:
        logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

    logger.info("[OVERNIGHT] Running training data collection...")
    print("[WATCH] Running overnight training data collection...")
    result = collect_training_examples_from_closed_trades_detailed()
    count = result.count
    print(f"[WATCH] Training collection: {count} new examples")

    # #615 — Structured payload distinguishes "no work" from "100% failed".
    summary = (
        f"examples={count} attempted={result.attempted} "
        f"rejected={result.rejected} stage1_failures={result.stage1_failures} "
        f"skipped_no_features={result.skipped_no_features} "
        f"halted={result.halted}"
    )
    if result.is_silent_failure:
        _alert_training_silent_failure(result)

    log_overnight_task(
        "training_collection",
        "failed" if result.is_silent_failure else "completed",
        datetime.now(ET).isoformat(),
        datetime.now(ET).isoformat(),
        result=summary,
    )

    try:
        broadcast_sync("overnight_task", {"task": "training_collection", "status": "complete",
                                          "examples_collected": count})
    except Exception as e:
        logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

    # ── Telegram: notify_overnight_training_complete ──
    safe_send(
        "overnight_training_complete",
        tasks_completed=1,
        tasks_total=1,
        details={"training_collection": {"success": True}},
    )


def run_news_ingestion():
    """10:00 PM ET — Full universe news pull and caching."""
    from src.api.websocket import broadcast_sync
    from src.universe.sp100 import get_sp100_universe

    try:
        broadcast_sync("overnight_task", {"task": "news_ingestion", "status": "started"})
    except Exception as e:
        logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

    logger.info("[OVERNIGHT] Running news ingestion...")
    print("[WATCH] Running news ingestion...")

    universe = get_sp100_universe()
    articles_cached = 0

    for ticker in universe:
        try:
            from src.data_enrichment.news import fetch_recent_news
            result = fetch_recent_news(ticker, lookback_days=1)
            if result and result.get("articles"):
                articles_cached += len(result["articles"])
        except Exception as e:
            logger.warning("[OVERNIGHT] News fetch failed for %s: %s", ticker, e)

    print(f"[WATCH] News ingestion complete: {len(universe)} tickers, {articles_cached} articles cached")

    try:
        broadcast_sync("overnight_task", {"task": "news_ingestion", "status": "complete",
                                          "tickers_scanned": len(universe), "articles_cached": articles_cached})
    except Exception as e:
        logger.warning("[WATCH] broadcast overnight_task failed: %s", e)


def run_attribution_resolution_and_notify(db_path: str = DB_PATH) -> int:
    """Run `resolve_pending_outcomes` + post a Telegram summary.

    Extracted here (rather than inlined in watch.py) so the 4:30 PM ET
    attribution-resolve branch in `_run_sync_body` stays one line. Counts
    the pending-remaining total after the resolver finishes so operators
    can see how many rows are still waiting for their 8-day window.
    """
    from src.attribution.logger import resolve_pending_outcomes
    

    resolved = resolve_pending_outcomes(db_path)
    try:
        with connect_db(db_path) as conn:
            _row = conn.execute(
                "SELECT COUNT(*) FROM attribution_trades "
                "WHERE ranker_only_outcome = 'pending'"
            ).fetchone()
            pending_remaining = _scalar(_row)
    except Exception as exc:
        logger.warning("[ATTRIBUTION] pending-count lookup failed: %s", exc)
        pending_remaining = -1
    safe_send("attribution_resolve_complete", resolved=resolved, pending_remaining=max(pending_remaining, 0))
    return resolved


def run_1min_bar_collection():
    """11:30 PM ET — Collect 1-minute OHLCV bars for S&P 100 (Phase 6 intraday data).

    Runs after enrichment to avoid contending with the other overnight
    collectors for network bandwidth. yfinance only keeps ~7 trading days
    of 1-minute history, so daily collection is required to avoid gaps.
    Returns empty on weekends/holidays (handled gracefully by the collector).
    """
    from scripts.collect_1min_bars import collect, _previous_trading_day
    target = _previous_trading_day()
    logger.info("[OVERNIGHT] Collecting 1-minute bars for %s...", target.date())
    result = collect(target_dates=[target])
    logger.info("[OVERNIGHT] 1-minute bar collection complete: %s", result)
    safe_send(
        "1min_bar_collection",
        bars_collected=result.get("bars_collected", 0),
        tickers=result.get("tickers", 0),
        empty_ticker_days=result.get("empty_ticker_days", 0),
        dates=result.get("dates", 1),
    )


def run_enrichment_precache(config: dict):
    """11:00 PM ET — Pre-fetch fundamentals, insider data, macro for all tickers."""
    from src.api.websocket import broadcast_sync
    from src.data_enrichment.enricher import enrich_features
    from src.universe.sp100 import get_sp100_universe

    try:
        broadcast_sync("overnight_task", {"task": "enrichment_precache", "status": "started"})
    except Exception as e:
        logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

    logger.info("[OVERNIGHT] Running enrichment pre-cache...")
    print("[WATCH] Running enrichment pre-cache...")

    universe = get_sp100_universe()
    # Build minimal feature dict just for cache warming
    stub_features = {t: {} for t in universe}
    try:
        enrich_features(stub_features, config)
        count = len(universe)
    except Exception as e:
        logger.error("[OVERNIGHT] Enrichment pre-cache failed: %s", e)
        count = 0

    print(f"[WATCH] Enrichment pre-cache complete: {count} tickers enriched")

    try:
        broadcast_sync("overnight_task", {"task": "enrichment_precache", "status": "complete",
                                          "tickers_enriched": count})
    except Exception as e:
        logger.warning("[WATCH] broadcast overnight_task failed: %s", e)


def run_pre_market_refresh():
    """6:00 AM ET — Quick pre-market data check before morning watchlist."""
    from src.api.websocket import broadcast_sync
    from src.universe.sp100 import get_sp100_universe

    try:
        broadcast_sync("overnight_task", {"task": "pre_market_refresh", "status": "started"})
    except Exception as e:
        logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

    logger.info("[OVERNIGHT] Running pre-market refresh...")
    print("[WATCH] Running pre-market refresh...")

    universe = get_sp100_universe()
    # Fetch pre-market data if available (best-effort)
    try:
        from src.data_ingestion.market_data import fetch_ohlcv
        ohlcv = fetch_ohlcv(universe[:20])  # Quick check on top tickers
        print(f"[WATCH] Pre-market refresh: checked {len(ohlcv)} tickers")
    except Exception as e:
        logger.warning("[OVERNIGHT] Pre-market refresh failed: %s", e)
        print(f"[WATCH] Pre-market refresh: partial ({e})")

    try:
        broadcast_sync("overnight_task", {"task": "pre_market_refresh", "status": "complete"})
    except Exception as e:
        logger.warning("[WATCH] broadcast overnight_task failed: %s", e)


def run_data_collection(db_path: str = DB_PATH,
                        collector_failures: dict | None = None):
    """9:30 PM ET — Comprehensive market data collection."""
    from src.api.websocket import broadcast_sync
    from src.data_collection.options_collector import collect_options_chains
    from src.data_collection.options_metrics import compute_options_metrics
    from src.data_collection.vix_collector import collect_vix_term_structure
    from src.data_collection.trends_collector import collect_google_trends
    from src.data_collection.macro_collector import collect_macro_snapshots
    from src.data_collection.cboe_collector import collect_cboe_ratios
    from src.universe.sp100 import get_sp100_universe

    if collector_failures is None:
        collector_failures = {}

    try:
        broadcast_sync("overnight_task", {"task": "data_collection", "status": "started"})
    except Exception as e:
        logger.warning("[WATCH] broadcast overnight_task failed: %s", e)

    logger.info("[OVERNIGHT] Running comprehensive data collection...")
    print("[WATCH] Running comprehensive data collection...")

    universe = get_sp100_universe()
    now = datetime.now(ET)
    results = {}

    # 1. Options chains (most important)
    print("[WATCH]   [1/12] Options chains...")
    try:
        results["options"] = collect_options_chains(universe)
    except Exception as e:
        logger.error("[COLLECT] options_chains: FAILED -- %s", e)
        results["options"] = {"error": str(e)}

    # 2. Derived metrics from chains
    print("[WATCH]   [2/12] Options metrics...")
    try:
        results["metrics"] = compute_options_metrics(universe)
    except Exception as e:
        logger.error("[COLLECT] options_metrics: FAILED -- %s", e)
        results["metrics"] = {"error": str(e)}

    # 3. VIX term structure
    print("[WATCH]   [3/12] VIX term structure...")
    try:
        results["vix"] = collect_vix_term_structure()
    except Exception as e:
        logger.error("[COLLECT] vix_term_structure: FAILED -- %s", e)
        results["vix"] = {"error": str(e)}

    # 4. CBOE ratios
    print("[WATCH]   [4/12] CBOE ratios...")
    try:
        results["cboe"] = collect_cboe_ratios()
    except Exception as e:
        logger.error("[COLLECT] cboe_ratios: FAILED -- %s", e)
        results["cboe"] = {"error": str(e)}

    # 5. FRED macro (35+ series)
    print("[WATCH]   [5/12] FRED macro indicators...")
    try:
        results["macro"] = collect_macro_snapshots()
    except Exception as e:
        logger.error("[COLLECT] macro_snapshots: FAILED -- %s", e)
        results["macro"] = {"error": str(e)}

    # 6. Google Trends (market-wide sentiment terms)
    print("[WATCH]   [6/12] Google Trends (sentiment)...")
    try:
        results["trends"] = collect_google_trends(universe, batch_size=20)
    except Exception as e:
        logger.error("[COLLECT] google_trends: FAILED -- %s", e)
        results["trends"] = {"error": str(e)}

    # 7. Earnings calendar
    print("[WATCH]   [7/12] Earnings calendar...")
    try:
        from scripts.fetch_earnings_calendar import fetch_earnings_dates
        results["earnings"] = fetch_earnings_dates(universe)
        upcoming = results["earnings"].get("upcoming_7d", [])
        if upcoming:
            logger.warning("[EARNINGS] %d stocks report this week: %s",
                           len(upcoming), ", ".join(upcoming))
            # Telegram earnings warning
            safe_send("earnings_warning", tickers=upcoming)
    except Exception as e:
        logger.debug("[WATCH] Earnings fetch failed: %s", e)
        results["earnings"] = {"error": str(e)}

    # 8. SEC EDGAR filings (new filings only)
    print("[WATCH]   [8/12] SEC EDGAR filings...")
    try:
        from src.data_collection.edgar_collector import collect_new_filings
        results["edgar"] = collect_new_filings(universe)
    except Exception as e:
        logger.warning("[WATCH] EDGAR collection failed: %s", e)
        results["edgar"] = {"error": str(e)}

    # 9. Insider transactions
    print("[WATCH]   [9/12] Insider transactions...")
    try:
        from src.data_collection.insider_collector import collect_insider_transactions
        results["insider"] = collect_insider_transactions(universe)
    except Exception as e:
        logger.warning("[WATCH] Insider collection failed: %s", e)
        results["insider"] = {"error": str(e)}

    # 10. FINRA short interest (biweekly — around settlement dates)
    # WHY only days 1,2,15,16: FINRA publishes short interest data twice
    # monthly on settlement dates. Collecting on other days wastes API calls.
    if now.day in (1, 2, 15, 16):
        print("[WATCH]   [10/12] Short interest...")
        try:
            from src.data_collection.short_interest_collector import collect_short_interest
            results["short_interest"] = collect_short_interest(universe)
        except Exception as e:
            logger.warning("[WATCH] Short interest collection failed: %s", e)
            results["short_interest"] = {"error": str(e)}
    else:
        results["short_interest"] = "skipped (not settlement date)"

    # 10b. FINRA short volume (Mon-Fri only — FINRA publishes T+1 on trading days)
    # v0.36.13 — replaces defunct Finnhub /stock/short-interest (403).
    # NOTE: short_volume != short_interest (see short_volume_finra.py docstring).
    if now.weekday() < 5:
        try:
            from src.data_collection.short_volume_finra import collect_finra_short_volume
            results["short_volume_finra"] = collect_finra_short_volume()
        except Exception as e:
            logger.warning("[SHORT_VOLUME_FINRA] Collection failed: %s", e)
            results["short_volume_finra"] = {"error": str(e)}
    else:
        results["short_volume_finra"] = "skipped (weekend — no FINRA publication)"

    # 11. Fed communications
    print("[WATCH]   [11/12] Fed communications...")
    try:
        from src.data_collection.fed_collector import collect_fed_communications
        results["fed"] = collect_fed_communications()
    except Exception as e:
        logger.warning("[WATCH] Fed collection failed: %s", e)
        results["fed"] = {"error": str(e)}

    # 11b. Institutional ownership (plan-gated; Sprint 5 Wave C7b.1 / T21).
    # No-op when finnhub_plan != fundamental-1; collector returns None at gate.
    print("[WATCH]   [11b] Institutional ownership (plan-gated)...")
    try:
        from src.data_collection.institutional_ownership_collector import (
            collect_institutional_ownership,
        )
        inst_rows = 0
        for _t in universe:
            if collect_institutional_ownership(_t) is not None:
                inst_rows += 1
        results["institutional_ownership"] = {"tickers_with_data": inst_rows}
    except Exception as e:
        logger.warning("[WATCH] Institutional ownership collection failed: %s", e)
        results["institutional_ownership"] = {"error": str(e)}

    # 11c. Filings sentiment (plan-gated; Sprint 5 Wave C7b.2 / T22).
    # No-op when finnhub_plan != fundamental-1; collector returns None at gate.
    print("[WATCH]   [11c] Filings sentiment (plan-gated)...")
    try:
        from src.data_collection.filings_sentiment_collector import (
            collect_filings_sentiment,
        )
        fs_rows = 0
        for _t in universe:
            if collect_filings_sentiment(_t) is not None:
                fs_rows += 1
        results["filings_sentiment"] = {"tickers_with_data": fs_rows}
    except Exception as e:
        logger.warning("[WATCH] Filings sentiment collection failed: %s", e)
        results["filings_sentiment"] = {"error": str(e)}

    # 11d. Press releases (plan-gated; Sprint 5 Wave C7b.3 / T23).
    # No-op when finnhub_plan != fundamental-1; collector returns None at gate.
    print("[WATCH]   [11d] Press releases (plan-gated)...")
    try:
        from src.data_collection.press_releases_collector import (
            collect_press_releases,
        )
        pr_rows = 0
        for _t in universe:
            if collect_press_releases(_t) is not None:
                pr_rows += 1
        results["press_releases"] = {"tickers_with_data": pr_rows}
    except Exception as e:
        logger.warning("[WATCH] Press releases collection failed: %s", e)
        results["press_releases"] = {"error": str(e)}

    # 12. Analyst estimates (batch 20/night to stay under FMP limit)
    print("[WATCH]   [12/12] Analyst estimates (batch)...")
    try:
        from src.data_collection.analyst_collector import collect_analyst_estimates
        results["analyst"] = collect_analyst_estimates(universe, batch_size=20)
    except Exception as e:
        logger.warning("[WATCH] Analyst collection failed: %s", e)
        results["analyst"] = {"error": str(e)}

    # 13. Research papers
    print("[WATCH]   [13/13] Research papers...")
    try:
        from src.data_collection.research_collector import collect_research_papers
        research_results = collect_research_papers()
        results["research"] = research_results
        print(f"[WATCH]   [13/13] Research: {research_results.get('total_new', 0)} new papers "
              f"(crawled {research_results.get('total_crawled', 0)})")
    except Exception as e:
        logger.warning("[COLLECTORS] Research collection failed: %s", e)
        results["research"] = {"error": str(e)}

    summary = {k: str(v) for k, v in results.items()}
    print(f"[WATCH] Data collection complete: {summary}")

    # DB-2 Task 17: explicit per-collector success/failure visibility in
    # the log. The code already isolates each collector in its own
    # try/except; this loop adds a consistent one-line summary so
    # failures are greppable without digging through warning-level
    # messages scattered through the 12-step block above.
    for name, result in results.items():
        if _is_collector_error(result):
            logger.error("[COLLECT] %s: FAILED -- %s", name, str(result)[:120])
        elif isinstance(result, str) and result.startswith("skipped"):
            logger.info("[COLLECT] %s: skipped", name)
        else:
            logger.info("[COLLECT] %s: success", name)

    # Log collection results to activity log
    try:
        from src.utils.activity_logger import log_activity, DATA_COLLECTION
        log_activity(DATA_COLLECTION, f"Overnight collection: {len(results)} collectors", results)
    except Exception as e:
        logger.warning("[WATCH] log_activity failed: %s", e)

    # Run retention policy to prune old rows (#123) — prevents SQLite bloat
    # from unbounded data collection. Each table has a configurable max age.
    try:
        from src.data_collection.retention import run_retention
        retention_result = run_retention()
        if retention_result:
            results["retention"] = retention_result
            logger.info("[WATCH] Retention pruned: %s", retention_result)
    except Exception as e:
        logger.warning("[WATCH] Retention failed: %s", e)

    # 1J. Track collector failures and alert at 3+ consecutive
    for name, result in results.items():
        if _is_collector_error(result):
            collector_failures[name] = collector_failures.get(name, 0) + 1
            if collector_failures[name] >= 3:
                other_status = {
                    n: collector_failures.get(n, 0) < 3
                    for n in results if n != name
                }
                safe_send(
                    "collection_failure",
                    collector_name=name,
                    consecutive_failures=collector_failures[name],
                    last_error=str(result)[:80],
                    last_success_ago="unknown",
                    other_collectors=other_status,
                )
        else:
            collector_failures[name] = 0  # Reset on success

    # H3. Notify new research papers via Telegram
    if research_results.get("total_new", 0) > 0:
        with connect_db(db_path) as _cn:
            top = _cn.execute(
                "SELECT title, relevance_score FROM research_papers ORDER BY collected_at DESC LIMIT 1"
            ).fetchone()
        top_title = top[0] if top else "Unknown"
        top_score = top[1] if top else 0
        safe_send(
            "research_papers",
            total_new=research_results["total_new"],
            top_paper=top_title,
            top_score=top_score,
        )

    # Telegram overnight summary
    safe_send("overnight_complete", results=results)

    try:
        broadcast_sync("overnight_task", {"task": "data_collection", "status": "complete",
                                          "results": summary})
    except Exception as e:
        logger.warning("[WATCH] broadcast overnight_task failed: %s", e)


def run_evening_handoff(vram_manager=None):
    """6:50 PM ET — Unload Ollama, launch overnight training subprocess.

    WHY VRAM handoff: RTX 3060 12GB cannot run Ollama (inference) and
    PyTorch (training) simultaneously. The evening handoff frees VRAM
    for overnight fine-tuning, morning handoff reloads Ollama for scans.

    Returns the VRAMManager instance (caller should store it for morning handoff).
    """
    from pathlib import Path
    from src.scheduler.vram_manager import VRAMManager

    vm = VRAMManager()
    if vm.handoff_to_training():
        try:
            from src.scheduler.metrics import upsert_daily_metric

            upsert_daily_metric(
                "vram_handoff_training_ok",
                1.0,
                '{"direction":"training","detail":"overnight training handoff succeeded"}',
            )
        except Exception as metric_err:
            logger.debug("[WATCH] vram_handoff_training_ok metric failed: %s", metric_err)
        vm.launch_training_subprocess(
            "overnight",
            ["-m", "scripts.overnight_train"],
        )
        print("[WATCH] VRAM handoff complete -- overnight training started")
        safe_send("vram_handoff", direction="training", success=True)
        return vm
    else:
        try:
            from src.scheduler.metrics import upsert_daily_metric

            upsert_daily_metric(
                "vram_handoff_training_ok",
                0.0,
                '{"direction":"training","detail":"handoff failed; staying in inference mode"}',
            )
        except Exception as metric_err:
            logger.debug("[WATCH] vram_handoff_training_ok metric failed: %s", metric_err)
        print("[WATCH] VRAM handoff FAILED -- staying in inference mode")
        safe_send("vram_handoff", direction="training", success=False, detail="Staying in inference mode")
        return vram_manager


def run_morning_handoff(vram_manager=None):
    """5:15 AM ET — Kill training subprocess, reload Ollama."""
    from pathlib import Path
    from src.scheduler.vram_manager import VRAMManager

    # Signal overnight pipeline to stop
    stop_flag = Path("data/STOP_OVERNIGHT")
    stop_flag.parent.mkdir(parents=True, exist_ok=True)
    stop_flag.touch()

    # Give subprocess time to checkpoint and exit
    time.sleep(60)

    vm = vram_manager or VRAMManager()
    if vm.handoff_to_inference():
        try:
            from src.scheduler.metrics import upsert_daily_metric

            upsert_daily_metric(
                "vram_handoff_inference_ok",
                1.0,
                '{"direction":"inference","detail":"morning inference handoff succeeded"}',
            )
        except Exception as metric_err:
            logger.debug("[WATCH] vram_handoff_inference_ok metric failed: %s", metric_err)
        stop_flag.unlink(missing_ok=True)
        print("[WATCH] Morning handoff complete -- Ollama loaded and warm")
        safe_send("vram_handoff", direction="inference", success=True)
    else:
        try:
            from src.scheduler.metrics import upsert_daily_metric

            upsert_daily_metric(
                "vram_handoff_inference_ok",
                0.0,
                '{"direction":"inference","detail":"handoff failed; attempting restart"}',
            )
        except Exception as metric_err:
            logger.debug("[WATCH] vram_handoff_inference_ok metric failed: %s", metric_err)
        print("[WATCH] Morning handoff FAILED -- attempting Ollama restart")
        safe_send("vram_handoff", direction="inference", success=False, detail="Attempting restart")
        # Fallback: try reload anyway
        stop_flag.unlink(missing_ok=True)
        try:
            vm._reload_ollama()
        except Exception as e:
            logger.error("[WATCH] Ollama restart failed: %s", e)


def run_daily_council():
    """8:30 AM ET — Run the daily AI Council session."""
    print("[WATCH] Running daily AI Council session...")
    try:
        from src.council.engine import CouncilEngine
        engine = CouncilEngine()
        result = engine.run_session(session_type="daily")
        consensus = result.get("consensus", "unknown")
        cost = result.get("total_cost", 0)
        rounds = result.get("rounds_completed", 0)
        contested = result.get("is_contested", False)
        print(f"[WATCH] Council complete: {consensus} "
              f"({'CONTESTED' if contested else 'agreed'}) "
              f"({rounds} rounds, ${cost:.2f})")

        # Telegram notification
        try:
            from src.notifications.telegram import send_telegram, is_telegram_enabled
            if is_telegram_enabled():
                now = datetime.now(ET).strftime("%H:%M ET")
                msg = f"\U0001f3db\ufe0f <b>AI COUNCIL SESSION</b> ({now})\n"
                msg += f"Consensus: <b>{consensus.upper()}</b>"
                if contested:
                    msg += " \u26a0\ufe0f CONTESTED"
                msg += f"\nCost: ${cost:.2f} | Rounds: {rounds}"
                send_telegram(msg)
        except Exception as e:
            logger.warning("[WATCH] send_telegram failed: %s", e)
    except Exception as e:
        logger.error("[WATCH] Council session failed: %s", e)
        print(f"[WATCH] Council session failed: {e}")
        # Notify on failure so ops knows the council didn't run
        try:
            from src.notifications.telegram import send_telegram, is_telegram_enabled
            if is_telegram_enabled():
                send_telegram(
                    f"\U0001f6a8 <b>COUNCIL FAILED</b>\n{type(e).__name__}: {e}"
                )
        except Exception:
            pass  # Don't cascade failures


def run_ollama_warmup():
    """9:25 AM ET — Full-length warm-up inference before first scan.

    Not just a health check — runs a real prompt of similar length to
    what the scan will generate, warming up the KV cache and CUDA kernels.

    WHY: First Ollama inference after reload takes 3-5x longer (CUDA kernel
    compilation, KV cache allocation). Running a warm-up prompt 5 minutes
    before market open ensures the first real scan gets normal latency.
    """
    from pathlib import Path
    from src.llm.client import generate, is_llm_available

    if not is_llm_available():
        print("[WATCH] Ollama not available -- skipping warm-up")
        return

    warmup_path = Path("data/reference/warmup_prompt.txt")
    if warmup_path.exists():
        warmup_prompt = warmup_path.read_text(encoding="utf-8")
    else:
        warmup_prompt = (
            "Analyze a hypothetical pullback trade in AAPL at $195.00. "
            "The stock has pulled back 6% from its 50-day high in a strong uptrend. "
            "SMA50 is rising, price is 3% above SMA200. Volume is contracting on "
            "the pullback (0.7x average). RSI is at 42. The broader market regime "
            "is calm_uptrend with healthy breadth (68% above 50d MA). "
            "Provide conviction (1-10), why_now analysis, and deeper analysis."
        )

    import time as _time
    start = _time.time()
    system_prompt = "You are a senior equity research analyst. Analyze the setup."
    result = generate(warmup_prompt, system_prompt)
    elapsed = _time.time() - start

    if result:
        print(f"[WATCH] Ollama warm-up complete -- {elapsed:.1f}s -- ready for first scan")
    else:
        print(f"[WATCH] WARNING: Ollama warm-up failed ({elapsed:.1f}s) -- "
              "first scan may be slow")


def run_premarket_rolling_features():
    """6:02 AM ET — Pre-compute rolling features for faster scans."""
    from src.scheduler.premarket import PreMarketPipeline
    pipeline = PreMarketPipeline()
    result = pipeline.run_rolling_features()
    print(f"[WATCH] Rolling features: {result['computed']} computed")


def run_premarket_training():
    """7:00 AM ET — Verify Ollama + generate self-blinded training data."""
    from src.scheduler.premarket import PreMarketPipeline
    pipeline = PreMarketPipeline()
    if not pipeline.verify_ollama_warm():
        print("[WATCH] Ollama not warm -- skipping training generation")
        return
    result = pipeline.run_training_generation()
    print(f"[WATCH] Premarket training: {result['generated']} generated, "
          f"{result['unscored']} unscored")


def run_premarket_news_scoring():
    """8:02 AM ET — Score overnight news for market impact."""
    from src.scheduler.premarket import PreMarketPipeline
    pipeline = PreMarketPipeline()
    result = pipeline.run_news_scoring()
    print(f"[WATCH] News scoring: {result['scored']} articles scored")


def run_premarket_candidates():
    """9:00 AM ET — Pre-analyze candidates for first scan."""
    from src.scheduler.premarket import PreMarketPipeline
    pipeline = PreMarketPipeline()
    result = pipeline.run_candidate_analysis()
    print(f"[WATCH] Pre-analyzed {result['count']} candidates")


def _patch_timestamp_utcnow():
    """Replace deprecated pd.Timestamp.utcnow with Timestamp.now('UTC').

    yfinance calls pd.Timestamp.utcnow() which triggers Pandas4Warning.
    This warning is emitted from Cython C code and bypasses Python's
    warnings.filterwarnings. Patching the method with the recommended
    replacement eliminates the warning at the source.
    """
    try:
        import pandas as pd
        if hasattr(pd.Timestamp, 'utcnow'):
            pd.Timestamp.utcnow = staticmethod(lambda: pd.Timestamp.now(tz="UTC"))
    except Exception:
        pass


def run_stress_test():
    """Run historical stress test across all 3 crisis scenarios."""
    from scripts.stress_test import run_scenario, store_result, SCENARIOS
    _patch_timestamp_utcnow()
    print("[WATCH] Running stress test (3 scenarios)...")
    results: list[dict] = []
    failed = 0
    for name, dates in SCENARIOS.items():
        try:
            result = run_scenario(name, dates["start"], dates["end"])
            if "error" not in result:
                store_result(result)
                results.append({"name": name, **result})
                print(f"  -> {name}: {result.get('total_trades', 0)} trades, "
                      f"WR={result.get('win_rate', 0):.0%}, "
                      f"DD={result.get('max_drawdown_pct', 0):.1f}%")
            else:
                failed += 1
        except Exception as e:
            failed += 1
            logger.warning("[WATCH] Stress test %s failed: %s", name, e)
    print("[WATCH] Stress test complete")
    notes = " | ".join(
        f"{r['name']}: WR {r.get('win_rate', 0):.0%}, DD {r.get('max_drawdown_pct', 0):.1f}%"
        for r in results
    )
    safe_send(
        "stress_test_complete",
        scenarios_run=len(SCENARIOS), passed=len(results), failed=failed,
        notes=notes,
    )


def run_simulation_engine():
    """Run full 13-scenario simulation with Monte Carlo."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "scripts/simulation_engine.py", "--monte-carlo", "1000"],
        capture_output=True, text=True, timeout=7200,
    )
    if result.returncode != 0:
        logger.error("[WATCH] Simulation engine failed: %s", result.stderr[:500])
    else:
        logger.info("[WATCH] Simulation engine completed")
    return result.returncode == 0


def run_research_synthesis():
    """Sunday 6 PM ET — Run weekly research synthesis."""
    from src.data_collection.research_synthesizer import run_weekly_synthesis
    print("[WATCH] Running weekly research synthesis...")
    result = run_weekly_synthesis()
    papers_count = result.get("papers_reviewed", 0)
    actionable = result.get("actionable_count", 0)
    print(f"[WATCH] Research synthesis: {papers_count} papers reviewed, {actionable} actionable")

    # ── Telegram: notify_research_papers (new papers discovered) ──
    if papers_count > 0:
        top_paper = result.get("top_paper_title", "Unknown")
        top_score = result.get("top_paper_score", 0.0)
        safe_send(
            "research_papers",
            total_new=papers_count,
            top_paper=top_paper,
            top_score=top_score,
        )

    # ── Telegram: notify_research_digest (synthesis complete) ──
    digest = result.get("digest_summary", "No digest generated")
    safe_send(
        "research_digest",
        papers_count=papers_count,
        actionable_count=actionable,
        digest_summary=digest,
    )
