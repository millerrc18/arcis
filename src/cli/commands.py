"""CLI command implementations for Arcis.

Called by: main
Calls: config, council.engine, data_collection.cboe_collector, data_collection.macro_collector, data_collection.options_collector, data_collection.options_metrics, data_collection.trends_collector, data_collection.vix_collector, data_ingestion.market_data, email.notifier, evaluation.backtester, evaluation.cto_report, evaluation.feature_importance, evaluation.gate_evaluator, evaluation.system_validator, journal.store, notifications.telegram, packets.template, risk.governor, scheduler.watch, services.recap_service, services.review_service, services.scan_service, services.shadow_service, services.system_service, services.training_service, services.watchlist_service, shadow_trading.alpaca_adapter, shadow_trading.executor, shadow_trading.reconcile, training.ab_evaluation, training.backfill, training.bootstrap, training.curriculum, training.dpo_pipeline, training.leakage_detector, training.quality_filter, training.trainer, training.validation, training.versioning, universe.sp100
Owns tables: none
Config keys: enabled, live_trading, shadow_trading, starting_capital
Tests: none
"""

import json
import logging
import sys

from src.config import DB_PATH
from src.email.notifier import send_email
from src.journal.store import initialize_database
from src.packets.template import build_demo_packet

logger = logging.getLogger(__name__)


def cmd_init_db(args):
    initialize_database(args.db_path)
    print(f"Initialized journal database at {args.db_path}")


def cmd_demo_packet(args):
    print(build_demo_packet())


def cmd_send_test_email(args):
    success = send_email(
        "[TRADE DESK] Test Email",
        "This is a test from Arcis. Email delivery is working.",
    )
    print("Test email sent successfully." if success else "Failed to send test email.")


def cmd_send_test_telegram(args):
    from src.notifications.telegram import is_telegram_enabled, send_telegram

    if not is_telegram_enabled():
        print("Telegram not configured. Add telegram section to config/settings.local.yaml:")
        print("  telegram:")
        print("    enabled: true")
        print('    bot_token: "your-bot-token"')
        print('    chat_id: "your-chat-id"')
        return
    success = send_telegram(
        "🧪 <b>ARCIS — TEST</b>\n"
        "Telegram notifications are working!\n"
        "You'll receive alerts for:\n"
        "  • Trade opens/closes\n"
        "  • Earnings warnings\n"
        "  • Overnight data collection\n"
        "  • System events"
    )
    _safe_print("Telegram test sent successfully! ✓" if success else "Failed to send Telegram message.")


def cmd_ingest(args):
    from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark
    from src.universe.sp100 import get_sp100_universe

    universe = get_sp100_universe()
    print(f"Fetching OHLCV data for {len(universe)} tickers + SPY...")
    ohlcv = fetch_ohlcv(universe)
    spy = fetch_spy_benchmark()
    print(f"Ingestion complete: {len(ohlcv)} succeeded, {len(universe) - len(ohlcv)} failed")
    if ohlcv:
        sample = next(iter(ohlcv.values()))
        print(f"  Date range: {sample.index.min().date()} to {sample.index.max().date()}")
    print(f"  SPY benchmark: {'OK' if not spy.empty else 'FAILED'}")


def _safe_print(text: str) -> None:
    """Print text without crashing on Windows console encoding mismatches."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        if hasattr(sys.stdout, "buffer"):
            sys.stdout.buffer.write(text.encode(encoding, errors="replace") + b"\n")
            sys.stdout.flush()
        else:
            print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def cmd_scan(args):
    from src.config import load_config
    from src.services.scan_service import run_scan

    config = load_config()
    result = run_scan(
        config,
        dry_run=getattr(args, "dry_run", False),
        send_email_flag=getattr(args, "email", False),
        run_shadow=not getattr(args, "no_shadow", False),
    )
    verbose = getattr(args, "verbose", False)
    if verbose:
        print(f"Universe: {result['tickers_scanned']} ({result['tickers_succeeded']} OK)")
        for ranked in (result.get("ranked") or [])[:15]:
            feat = ranked["features"]
            tag = "  [EARNINGS]" if feat.get("event_risk_level") in ("elevated", "imminent") else ""
            print(f"  {ranked['ticker']:6s}  score={ranked['score']:5.1f}  {ranked['qualification']}{tag}")
    if not result["packet_worthy"]:
        print(f"No packet-worthy setups. {len(result['watchlist'])} on watchlist.")
    else:
        print(f"\nPACKET-WORTHY: {len(result['packet_worthy'])}")
        for packet in result["packet_worthy"]:
            _safe_print(packet["rendered_text"])
    if result["watchlist"]:
        print(f"\nWATCHLIST ({len(result['watchlist'])}):")
        for watch in result["watchlist"]:
            print(f"  {watch['ticker']:6s}  score={watch['score']:5.1f}  trend={watch.get('trend_state', 'n/a')}")
    if getattr(args, "dry_run", False):
        print("\n[DRY RUN] No journal entries written.")


def cmd_morning_watchlist(args):
    from src.config import load_config
    from src.services.watchlist_service import generate_morning_watchlist

    result = generate_morning_watchlist(
        load_config(),
        send_email_flag=getattr(args, "email", False) and not getattr(args, "dry_run", False),
    )
    print(result["email_body"])


def cmd_eod_recap(args):
    from src.config import load_config
    from src.services.recap_service import generate_eod_recap

    result = generate_eod_recap(
        load_config(),
        send_email_flag=getattr(args, "email", False) and not getattr(args, "dry_run", False),
    )
    print(result["email_body"])


def cmd_shadow_status(args):
    from src.config import load_config
    from src.services.shadow_service import get_shadow_status

    config = load_config()
    if not config.get("shadow_trading", {}).get("enabled", False):
        print("SHADOW LEDGER — Disabled in config.")
        print("  Set shadow_trading.enabled: true in settings.local.yaml")
        return

    result = get_shadow_status(config)
    if not result["open_trades"]:
        print("SHADOW LEDGER — No open trades.")
        return
    print(f"\nSHADOW LEDGER — OPEN TRADES ({result['open_count']}):")
    for trade in result["open_trades"]:
        pnl = (
            f"${trade['pnl_dollars']:+.2f} {trade['pnl_pct']:+.1f}%"
            if trade["pnl_dollars"] is not None
            else "n/a"
        )
        cur = f"${trade['current_price']:.2f}" if trade["current_price"] else "n/a"
        print(
            f"  {trade['ticker']:6s}  entry=${trade['entry_price']:.2f}  "
            f"current={cur}  P&L={pnl}  day {trade['duration_days'] or 0}/{trade['timeout_days']}"
        )


def cmd_shadow_history(args):
    from src.services.shadow_service import get_shadow_history

    result = get_shadow_history(days=getattr(args, "days", 30))
    if not result["trades"]:
        print(f"SHADOW LEDGER — No closed trades in the last {args.days} days.")
        return
    print("\nSHADOW LEDGER — CLOSED TRADES:")
    for trade in result["trades"]:
        print(f"  {trade['ticker']:6s}  P&L=${trade.get('pnl_dollars', 0):+.2f}  {trade.get('exit_reason', '?')}")
    metrics = result["metrics"]
    print(f"\n  {metrics['total_trades']} trades | {metrics['win_rate']:.0f}% WR | expectancy ${metrics['expectancy']:+.2f}")


def cmd_shadow_close(args):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.journal.store import close_shadow_trade, get_open_shadow_trades
    from src.shadow_trading.executor import _get_current_price_safe

    ticker = args.ticker.upper()
    reason = getattr(args, "reason", "manual")
    trade = next((row for row in get_open_shadow_trades() if row["ticker"] == ticker), None)
    if not trade:
        print(f"No open shadow trade found for {ticker}.")
        return
    entry = trade.get("actual_entry_price") or trade.get("entry_price", 0)
    current = _get_current_price_safe(ticker) or entry
    shares = trade.get("planned_shares", 1)
    pnl_dollars = round((current - entry) * shares, 2)
    pnl_pct = round((current - entry) / entry * 100, 2) if entry > 0 else 0
    now = datetime.now(ZoneInfo("America/New_York"))
    try:
        from src.shadow_trading.alpaca_adapter import place_paper_exit
        from alpaca.common.exceptions import APIError

        place_paper_exit(ticker, shares)
    except ImportError as exc:
        # alpaca adapter not installed — fall back to local-only close
        print(f"  Warning: alpaca adapter not available, skipping paper exit for {ticker}: {exc}")
        logger.error("[CLI] alpaca_adapter unavailable for %s close", ticker, exc_info=True)
    except (ConnectionError, TimeoutError) as exc:
        # Network failure — broker may or may not have received the exit.
        # Surface mismatch loudly so reconciliation can catch it.
        print(f"  Warning: NETWORK error on paper exit for {ticker}: {exc}")
        print(f"  Reconciliation will catch any ledger/broker mismatch for {ticker}")
        logger.error("[CLI] Network error on paper exit for %s", ticker, exc_info=True)
    except APIError as exc:
        # Alpaca rejected the exit — log clearly; local close still proceeds.
        print(f"  Warning: Alpaca rejected paper exit for {ticker}: {exc}")
        logger.error("[CLI] Alpaca APIError on exit for %s", ticker, exc_info=True)
    except Exception:
        # Unknown failure — surface and re-raise so the operator sees the bug.
        logger.error("[CLI] Unexpected error on paper exit for %s", ticker, exc_info=True)
        raise
    close_shadow_trade(
        trade["trade_id"],
        exit_price=current,
        exit_time=now.isoformat(),
        exit_reason=reason,
        pnl_dollars=pnl_dollars,
        pnl_pct=pnl_pct,
    )
    print(f"Closed {ticker}: {reason} | P&L=${pnl_dollars:+.2f} ({pnl_pct:+.1f}%)")


def cmd_shadow_account(args):
    from src.services.shadow_service import get_shadow_account

    try:
        result = get_shadow_account()
        account = result["account"]
        print(f"\nALPACA PAPER ACCOUNT: equity=${account['equity']:.2f} cash=${account['cash']:.2f}")
        for position in result.get("positions", []):
            print(f"  {position['symbol']:6s}  qty={position['qty']}  P&L=${position['unrealized_pl']:+.2f}")
    except Exception as exc:
        print(f"Failed to connect to Alpaca: {exc}")


def cmd_live_status(args):
    """Show live account balance and open positions."""
    from src.config import load_config

    config = load_config()
    live_cfg = config.get("live_trading", {})

    if not live_cfg.get("enabled", False):
        print("LIVE TRADING — Disabled in config.")
        print("  Set live_trading.enabled: true in settings.local.yaml")
        return

    try:
        from src.shadow_trading.alpaca_adapter import get_live_account_info, get_live_positions

        account = get_live_account_info()
        print("\nLIVE ACCOUNT:")
        print(f"  Equity:       ${account['equity']:.2f}")
        print(f"  Cash:         ${account['cash']:.2f}")
        print(f"  Buying Power: ${account['buying_power']:.2f}")
        print(f"  Status:       {account['status']}")

        starting = live_cfg.get("starting_capital", 100)
        pnl = account["equity"] - starting
        pnl_pct = (pnl / starting * 100) if starting > 0 else 0
        print(f"  Starting:     ${starting:.2f}")
        print(f"  Total P&L:    ${pnl:+.2f} ({pnl_pct:+.1f}%)")

        positions = get_live_positions()
        if positions:
            print(f"\n  OPEN POSITIONS ({len(positions)}):")
            for position in positions:
                print(
                    f"    {position['symbol']:6s}  qty={position['qty']}  "
                    f"entry=${position['avg_entry_price']:.2f}  "
                    f"current=${position['current_price']:.2f}  "
                    f"P&L=${position['unrealized_pl']:+.2f}"
                )
        else:
            print("\n  No open positions.")
    except Exception as exc:
        print(f"Failed to connect to live Alpaca account: {exc}")


def cmd_live_history(args):
    """Show live trade history from the journal."""
    import sqlite3

    try:
        initialize_database()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT ticker, actual_entry_price, actual_exit_price,
                          pnl_dollars, pnl_pct, exit_reason, created_at, actual_exit_time,
                          status
                   FROM shadow_trades
                   WHERE source = 'live' AND COALESCE(quarantined, 0) = 0
                   ORDER BY created_at DESC
                   LIMIT 50"""
            ).fetchall()

        if not rows:
            print("LIVE TRADING — No live trades recorded.")
            return

        open_trades = [row for row in rows if row["status"] == "open"]
        closed_trades = [row for row in rows if row["status"] == "closed"]

        print("\nLIVE TRADE HISTORY:")

        if open_trades:
            print(f"\n  OPEN ({len(open_trades)}):")
            for trade in open_trades:
                print(
                    f"    {trade['ticker']:6s}  entry=${(trade['actual_entry_price'] or 0):.2f}  "
                    f"opened={trade['created_at'][:10]}"
                )

        if closed_trades:
            print(f"\n  CLOSED ({len(closed_trades)}):")
            total_pnl = 0.0
            wins = 0
            for trade in closed_trades:
                pnl = trade["pnl_dollars"] or 0
                total_pnl += pnl
                if pnl > 0:
                    wins += 1
                print(
                    f"    {trade['ticker']:6s}  P&L=${pnl:+.2f} ({(trade['pnl_pct'] or 0):+.1f}%)  "
                    f"{trade['exit_reason'] or '?'}  {(trade['actual_exit_time'] or '')[:10]}"
                )

            win_rate = (wins / len(closed_trades) * 100) if closed_trades else 0
            print(f"\n  Total: ${total_pnl:+.2f} | {len(closed_trades)} trades | {win_rate:.0f}% win rate")
    except Exception as exc:
        print(f"Error loading live trade history: {exc}")


def cmd_live_close(args):
    """Manually close a live position."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.journal.store import (
        close_shadow_trade,
        get_open_shadow_trades,
        update_shadow_trade,
    )
    from src.shadow_trading.executor import (
        _get_current_price_safe,
        _is_filled_status,
        _is_pending_status,
        _submit_exit_order,
    )

    ticker = args.ticker.upper()
    reason = getattr(args, "reason", "manual")

    open_trades = get_open_shadow_trades()
    trade = next(
        (row for row in open_trades if row["ticker"] == ticker and row.get("source") == "live"),
        None,
    )
    if not trade:
        print(f"No open LIVE trade found for {ticker}.")
        return

    entry = trade.get("actual_entry_price") or trade.get("entry_price", 0)
    current = _get_current_price_safe(ticker) or entry
    shares = trade.get("planned_shares", 1)
    pnl_dollars = round((current - entry) * shares, 2)
    pnl_pct = round((current - entry) / entry * 100, 2) if entry > 0 else 0
    now = datetime.now(ZoneInfo("America/New_York"))

    try:
        broker_result = _submit_exit_order(trade, shares)
    except Exception as exc:
        print(f"Live sell order failed: {exc}")
        print("Journal left open until broker exit succeeds.")
        return

    status = broker_result.get("status") if isinstance(broker_result, dict) else None
    if _is_filled_status(status):
        fill_price = broker_result.get("filled_avg_price") if isinstance(broker_result, dict) else None
        if fill_price is not None:
            current = float(fill_price)
            pnl_dollars = round((current - entry) * shares, 2)
            pnl_pct = round((current - entry) / entry * 100, 2) if entry > 0 else 0
    elif _is_pending_status(status):
        update_shadow_trade(
            trade["trade_id"],
            {"status": "exit_pending", "exit_reason": reason},
        )
        print(f"Exit submitted for LIVE {ticker}; awaiting broker fill.")
        return
    else:
        print("Live sell order was not accepted by broker.")
        print("Journal left open until broker exit succeeds.")
        return

    close_shadow_trade(
        trade["trade_id"],
        exit_price=current,
        exit_time=now.isoformat(),
        exit_reason=reason,
        pnl_dollars=pnl_dollars,
        pnl_pct=pnl_pct,
    )
    print(f"Closed LIVE {ticker}: {reason} | P&L=${pnl_dollars:+.2f} ({pnl_pct:+.1f}%)")


def cmd_reconcile_live(args):
    """Reconcile Alpaca live positions with shadow_trades DB."""
    from src.shadow_trading.reconcile import reconcile_live_trades

    dry_run = getattr(args, "dry_run", False)
    result = reconcile_live_trades(desk="swing", dry_run=dry_run)
    _safe_print(f"\nAlpaca positions: {result['alpaca_positions']}")
    _safe_print(f"Tracked in DB:    {result['tracked_positions']}")
    if result["orphaned"]:
        _safe_print(f"\nOrphaned (on Alpaca, not in DB): {result['orphaned']}")
        if not dry_run:
            _safe_print(f"  -> Backfilled: {result['backfilled']}")
    if result["stale"]:
        _safe_print(f"\nStale (in DB, not on Alpaca): {result['stale']}")
        if not dry_run:
            _safe_print(f"  -> Marked closed: {result['marked_closed']}")
    if not result["orphaned"] and not result["stale"]:
        _safe_print("\nAll positions reconciled -- no discrepancies.")
    if dry_run:
        _safe_print("\n(dry run -- no changes made)")


def cmd_review(args):
    from src.services.review_service import get_pending_reviews, get_recommendation, submit_review

    sub = getattr(args, "review_sub", "list")
    if sub == "list" or not sub:
        pending = get_pending_reviews()
        if not pending:
            print("No trades pending review.")
            return
        print(f"\nTRADES PENDING REVIEW ({len(pending)}):")
        for row in pending:
            pnl = f"${row.get('shadow_pnl_dollars', 0):+.2f}" if row.get("shadow_pnl_dollars") is not None else "n/a"
            print(f"  {row['recommendation_id'][:8]}..  {row.get('ticker', '?'):6s}  {row.get('created_at', '')[:10]}  P&L={pnl}")
        return
    recommendation = get_recommendation(sub)
    if not recommendation:
        print(f"Recommendation {sub} not found.")
        return
    print(f"\nREVIEW: {recommendation['ticker']} — score {recommendation.get('confidence_score', 'n/a')}/10")
    try:
        approved = input("  Approved? (y/n): ").strip().lower()
        grade = input("  Grade (A/B/C/D/F): ").strip().upper()
        notes = input("  Notes: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return
    submit_review(
        sub,
        {
            "ryan_approved": 1 if approved == "y" else 0,
            "user_grade": grade if grade in "ABCDF" else None,
            "ryan_notes": notes or None,
        },
    )
    print(f"Review saved for {recommendation['ticker']}.")


def cmd_mark_executed(args):
    from src.services.review_service import mark_executed

    if mark_executed(args.ticker):
        print(f"Marked {args.ticker.upper()} as executed.")
    else:
        print(f"No recommendation found for {args.ticker.upper()}.")


def cmd_review_scorecard(args):
    from src.services.review_service import get_scorecard

    print(get_scorecard(weeks=getattr(args, "weeks", 1)))


def cmd_review_bootcamp(args):
    from src.services.review_service import get_bootcamp_report

    print(get_bootcamp_report(days=getattr(args, "days", 30)))


def cmd_postmortems(args):
    from src.services.review_service import get_postmortems

    results = get_postmortems(limit=getattr(args, "limit", 10), ticker=getattr(args, "ticker", None))
    if not results:
        print("No postmortems available.")
        return
    for row in results:
        print(f"  {row['ticker']:6s}  {row['date']}  {row['exit_reason']:>12s}  ${row['pnl_dollars']:+.2f}  {row['postmortem'][:60]}")


def cmd_postmortem_detail(args):
    from src.services.review_service import get_postmortem_detail

    recommendation = get_postmortem_detail(args.recommendation_id)
    if not recommendation:
        print(f"Not found: {args.recommendation_id}")
        return
    print(f"\nPOSTMORTEM: {recommendation['ticker']}")
    if recommendation.get("assistant_postmortem"):
        print(recommendation["assistant_postmortem"])


def cmd_training_status(args):
    from src.services.training_service import get_training_status

    status = get_training_status()
    print("\nTRAINING STATUS")
    print(f"  Model: {status['model_name']} | Dataset: {status['dataset_total']} examples | New: {status['new_since_last_train']}")
    print(f"  Train queued: {status['train_queued']} ({status['train_reason']})")
    print(f"  Rollback: {status['rollback_status']}")


def cmd_training_history(args):
    from src.services.training_service import get_training_history

    history = get_training_history()
    print("\nMODEL VERSION HISTORY")
    for version in history["versions"]:
        win_rate = f"{version['win_rate']:.1f}%" if version.get("win_rate") else "n/a"
        print(f"  {version['version_name']:<14s} {version['status']:<10s} trades={version['trade_count']}  WR={win_rate}")


def cmd_training_report(args):
    from src.services.training_service import get_training_report

    print(get_training_report())


def cmd_bootstrap_training(args):
    from src.training.bootstrap import estimate_bootstrap_cost, generate_synthetic_training_data

    count = getattr(args, "count", 500)
    cost = estimate_bootstrap_cost(count)
    print(f"Bootstrap: {count} examples, est. ${cost:.2f}")
    if not getattr(args, "yes", False) and input("Proceed? [y/N] ").strip().lower() != "y":
        print("Aborted.")
        return
    created = generate_synthetic_training_data(count)
    print(f"Bootstrap complete: {created} examples created")


def cmd_backfill_training(args):
    from src.training.backfill import estimate_backfill_cost, run_historical_backfill

    months = getattr(args, "months", 12)
    max_examples = getattr(args, "max_examples", 2000)
    quality_filter = ["clean_win", "clean_loss"]
    if getattr(args, "include_messy", False):
        quality_filter = ["clean_win", "clean_loss", "messy", "timeout"]
    cost = estimate_backfill_cost(max_examples)
    print(f"Backfill: {months}mo, max {max_examples} examples, est. ${cost:.2f}")
    if not getattr(args, "yes", False) and input("Proceed? [y/N] ").strip().lower() != "y":
        print("Aborted.")
        return
    stats = run_historical_backfill(
        months=months,
        min_score=getattr(args, "min_score", 70),
        quality_filter=quality_filter,
        max_examples=max_examples,
    )
    print(f"Backfill complete: {stats['examples_generated']} examples, ${stats['estimated_cost']:.2f}")


def cmd_train(args):
    from src.training.ab_evaluation import check_promotion_ready
    from src.training.trainer import export_training_data, run_fine_tune, should_train
    from src.training.versioning import (
        get_active_model_version,
        promote_evaluation_model,
        register_model_version,
        rollback_model,
        update_config_model,
    )

    if getattr(args, "register", False):
        active = get_active_model_version()
        if active and active["version_name"].startswith("halcyon-v1."):
            print(f"Active model already registered: {active['version_name']}")
            return
        version_name = "halcyon-v1.0.0"
        if active:
            import sqlite3

            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(
                    "UPDATE model_versions SET version_name = ? WHERE version_id = ?",
                    (version_name, active["version_id"]),
                )
            _safe_print(f"Renamed {active['version_name']} -> {version_name}")
        else:
            version_id = register_model_version(
                version_name=version_name,
                examples_count=969,
                synthetic_count=0,
                outcome_count=0,
                model_file_path="halcyonlatest",
            )
            print(f"Registered {version_name} (id={version_id})")
        import subprocess

        try:
            subprocess.run(["ollama", "cp", "halcyonlatest", version_name], capture_output=True, text=True, timeout=60)
            print(f"Created Ollama tag: {version_name}")
        except Exception as exc:
            print(f"Ollama tag failed (do manually: ollama cp halcyonlatest {version_name}): {exc}")
        update_config_model(version_name)
        print(f"Config updated. Dashboard will show {version_name} after restart.")
        return
    if getattr(args, "rollback", False):
        restored = rollback_model()
        print(f"Rolled back to {restored['version_name']}" if restored else "Rollback failed.")
        return
    if getattr(args, "export", False):
        split, count = export_training_data()
        print(f"Exported {count} examples ({split.get('training', 0)} train, {split.get('holdout', 0)} holdout)")
        return
    if not getattr(args, "force", False):
        trigger, reason = should_train()
        if not trigger:
            print(f"Training not needed: {reason}\nUse --force to train anyway.")
            return
    result = run_fine_tune()
    print(f"Training complete: {result['version_name']}" if result else "Training failed.")


def cmd_classify_training(args):
    from src.training.curriculum import classify_all_examples

    result = classify_all_examples()
    print(f"Classified {result['classified']} examples")
    print(f"  Difficulty: {result['difficulty']}")
    print(f"  Stages: {result['stage']}")


def cmd_score_training(args):
    from src.training.quality_filter import score_all_unscored

    result = score_all_unscored()
    print(f"Scored {result['scored']} examples (avg: {result['avg_score']:.2f}), skipped {result['skipped']}")


def cmd_validate_training(args):
    from src.training.validation import validate_training_dataset

    result = validate_training_dataset()
    print(f"\nDATASET VALIDATION ({result['total_examples']} examples)")
    print(f"  Health: {result['overall_health']}")
    print(f"  Format compliance: {result['format_compliance']:.0%}")
    print(f"  Win/loss: {result['wins']}W/{result['losses']}L ({result['win_pct']:.0%})")
    print(f"  Tickers: {result['tickers_represented']} | Sectors: {result['sectors_covered']}")
    print(f"  Duplicates: {result['exact_duplicates']} exact, {result['near_duplicates']} near")
    if result["issues"]:
        print(f"  Issues: {'; '.join(result['issues'])}")


def cmd_generate_contrastive(args):
    from src.training.curriculum import generate_contrastive_training_data

    count = generate_contrastive_training_data(max_pairs=getattr(args, "max_pairs", 50))
    print(f"Generated {count} contrastive training examples")


def cmd_generate_preferences(args):
    from src.training.dpo_pipeline import generate_preference_pairs

    count = generate_preference_pairs(n_pairs=getattr(args, "count", 100))
    print(f"Generated {count} preference pairs")


def cmd_cto_report(args):
    from src.evaluation.cto_report import format_cto_report, generate_cto_report

    report = generate_cto_report(days=getattr(args, "days", 7))
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_cto_report(report))
    if getattr(args, "email", False):
        body = json.dumps(report, indent=2, default=str) if getattr(args, "json", False) else format_cto_report(report)
        send_email("[TRADE DESK] CTO Report", body)


def cmd_evaluate_holdout(args):
    from src.training.trainer import evaluate_on_holdout

    print(json.dumps(evaluate_on_holdout(model_name=getattr(args, "model", "halcyon-latest")), indent=2))


def cmd_model_evaluation_status(args):
    from src.training.ab_evaluation import get_evaluation_status

    status = get_evaluation_status()
    if not status:
        print("No model in A/B evaluation.")
        return
    print(f"A/B: {status['model_name']} | {status['evaluations']} evals | WR={status['win_rate']:.0%} | {status['recommendation']}")


def cmd_promote_model(args):
    from src.training.ab_evaluation import check_promotion_ready
    from src.training.versioning import get_evaluation_model, promote_evaluation_model

    evaluation_model = get_evaluation_model()
    if not evaluation_model:
        print("No model in evaluation.")
        return
    if not getattr(args, "force", False):
        status = check_promotion_ready(evaluation_model["version_name"])
        if not status["ready"]:
            print(f"Not ready: {status['recommendation']}. Use --force.")
            return
    promoted = promote_evaluation_model()
    print(f"Promoted {promoted['version_name']}" if promoted else "Promotion failed.")


def cmd_feature_importance(args):
    from src.evaluation.feature_importance import compute_feature_importance

    result = compute_feature_importance(days=getattr(args, "days", 30))
    print(f"\nFEATURE IMPORTANCE ({result['closed_trades']} trades)")
    for feature in result.get("features", []):
        print(f"  {feature['name']:25s}  corr={feature['correlation_with_pnl']:+.3f}  [{feature['predictive_power']}]")


def cmd_backtest(args):
    from src.evaluation.backtester import backtest_model

    print(json.dumps(backtest_model(getattr(args, "model", "halcyon-latest"), months=getattr(args, "months", 6)), indent=2, default=str))


def cmd_compare_models(args):
    from src.evaluation.backtester import compare_models

    print(json.dumps(compare_models(args.model_a, args.model_b, months=getattr(args, "months", 3)), indent=2, default=str))


def cmd_check_leakage(args):
    from src.training.leakage_detector import check_outcome_leakage

    result = check_outcome_leakage()
    print("\n=== OUTCOME LEAKAGE TEST ===")
    if result.get("balanced_accuracy") is None:
        print(f"  {result.get('note', 'Insufficient data')}")
    else:
        print(f"  Status:            {result['status']}")
        print(f"  Balanced Accuracy: {result['balanced_accuracy']:.1%} (CLEAN ≤55%, MARGINAL 55-65%, LEAKING >65%)")
        print(f"  Raw Accuracy:      {result['raw_accuracy']:.1%}")
        print(f"  Majority Baseline: {result['majority_baseline']:.1%} (predicting all-majority-class)")
        print(f"  Above Baseline:    {result['accuracy_above_baseline']:+.1%}")
        class_balance = result.get("class_balance", {})
        print(f"  Class Balance:     {class_balance.get('wins', 0)} wins / {class_balance.get('losses', 0)} losses ({class_balance.get('win_pct', 0)}% win)")
        print(f"  Examples:          {result['n_examples']}")
        if result.get("feature_importance"):
            importance = result["feature_importance"]
            print(f"  Win predictors:    {', '.join(importance['win_predictors'][:3])}")
            print(f"  Loss predictors:   {', '.join(importance['loss_predictors'][:3])}")
        if result["is_leaking"]:
            print("\n  ACTION: Commentary text predicts outcomes beyond feature-level signal.")
            print("  Investigate whether language reveals directional expectations.")
        elif result["status"] == "MARGINAL":
            print("\n  MARGINAL: Some signal detected, likely feature-level (not outcome leakage).")
            print("  Safe to proceed with training. Monitor on future datasets.")
        else:
            print("\n  Commentary is outcome-independent. Safe to fine-tune.")


def cmd_halt_trading(args):
    from src.risk.governor import _global_halt

    _global_halt(True, source="cli", reason="manual halt via halt-trading command")
    print("[RISK] All trading halted. Use 'resume-trading' to resume.")


def cmd_resume_trading(args):
    from src.risk.governor import _global_halt

    _global_halt(False, source="cli", reason="manual resume via resume-trading command")
    print("[RISK] Trading resumed.")


def cmd_cancel_all_pending(args):
    """Cancel all pending Alpaca orders for emergency recovery (#310)."""
    from src.shadow_trading.alpaca_adapter import cancel_all_orders

    result = cancel_all_orders()
    count = result.get("cancelled", 0)
    error = result.get("error")
    print(f"[CANCEL] Cancelled {count} pending orders")
    if error:
        print(f"[CANCEL] Warning: {error}")


def cmd_preflight(args):
    from src.config import load_config
    from src.services.system_service import get_system_status

    status = get_system_status(load_config())
    print("\nARCIS - PREFLIGHT CHECK")
    print(f"  Config:    {'OK' if status['config_loaded'] else 'FAIL'}")
    print(f"  Source:    {status.get('config_source', 'unknown')}")
    print(f"  Email:     {'OK' if status['email_configured'] else 'FAIL'}")
    print(f"  Alpaca:    {'OK' if status['alpaca_connected'] else 'FAIL'} {'$' + str(int(status['alpaca_equity'])) if status['alpaca_equity'] else ''}")
    print(f"  Shadow:    {'Enabled' if status['shadow_trading_enabled'] else 'Disabled'}")
    print(f"  Live:      {'Enabled' if status['live_trading_enabled'] else 'Disabled'}")
    print(f"  Telegram:  {'OK' if status['telegram_configured'] else 'FAIL'}")
    print(f"  Halt:      {'ACTIVE' if status['kill_switch_halted'] else 'clear'}")
    print(f"  Ollama:    {'OK' if status['ollama_available'] else 'FAIL'}")
    print(f"  LLM:       {'OK (' + status['llm_model'] + ')' if status['llm_enabled'] and status['ollama_available'] else 'Disabled'}")
    print(f"  Model:     {status['model_version']}")
    print(f"  Journal:   {status['journal_recommendations']} recs, {status['journal_shadow_trades']} trades")
    print(f"  Training:  {'Enabled (' + str(status['training_examples']) + ' examples)' if status['training_enabled'] else 'Disabled'}")
    print(f"  Bootcamp:  {'Phase ' + str(status['bootcamp_phase']) if status['bootcamp_enabled'] else 'Disabled'}")

    if status.get("config_source") == "example":
        _safe_print("\nWARNING: Running on config/settings.example.yaml (template defaults).")
        print("   Create config/settings.local.yaml with real credentials and enabled flags.")


def cmd_config_fix(args):
    """Merge missing keys from settings.example.yaml into settings.local.yaml.

    Uses ruamel.yaml for round-trip parsing — preserves comments, blank lines,
    and formatting in the local config. Falls back to PyYAML if ruamel unavailable.
    """
    from pathlib import Path
    import shutil

    local_path = Path("config/settings.local.yaml")
    example_path = Path("config/settings.example.yaml")

    if not local_path.exists():
        print("ERROR: config/settings.local.yaml not found.")
        print("  Create it first: cp config/settings.example.yaml config/settings.local.yaml")
        return

    if not example_path.exists():
        print("ERROR: config/settings.example.yaml not found.")
        return

    try:
        from ruamel.yaml import YAML
        ryaml = YAML()
        ryaml.preserve_quotes = True
        ryaml.width = 120

        with open(local_path, "r", encoding="utf-8") as f:
            local = ryaml.load(f) or {}
        with open(example_path, "r", encoding="utf-8") as f:
            example = ryaml.load(f) or {}

        use_ruamel = True
    except ImportError:
        import yaml
        print("(ruamel.yaml not installed — formatting will not be preserved)")
        print("  pip install ruamel.yaml")
        with open(local_path, "r", encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}
        with open(example_path, "r", encoding="utf-8") as f:
            example = yaml.safe_load(f) or {}
        use_ruamel = False

    added = []

    def _merge_missing(ex, loc, prefix=""):
        for key in ex:
            full = f"{prefix}.{key}" if prefix else key
            if key not in loc:
                loc[key] = ex[key]
                # Add a blank line before new top-level sections for readability
                if use_ruamel and not prefix and hasattr(loc, 'ca'):
                    try:
                        from ruamel.yaml.tokens import CommentToken
                        from ruamel.yaml.error import CommentMark
                        loc.ca.items[key] = [
                            CommentToken("\n\n", CommentMark(0), None),
                            None, None, None,
                        ]
                    except Exception:
                        pass
                added.append(full)
            elif isinstance(ex[key], dict) and isinstance(loc.get(key), dict):
                _merge_missing(ex[key], loc[key], full)

    _merge_missing(example, local)

    if not added:
        print("Config is up to date — no missing keys.")
        return

    # Backup before writing
    backup_path = local_path.with_suffix(".yaml.bak")
    shutil.copy2(local_path, backup_path)

    if use_ruamel:
        with open(local_path, "w", encoding="utf-8") as f:
            ryaml.dump(local, f)
    else:
        import yaml
        with open(local_path, "w", encoding="utf-8") as f:
            yaml.dump(local, f, default_flow_style=False, sort_keys=False)

    print(f"Added {len(added)} missing keys (backup: {backup_path})")
    for k in added:
        print(f"  + {k}")


def cmd_config_diff(args):
    """Show keys in settings.example.yaml missing from settings.local.yaml."""
    from pathlib import Path
    import yaml

    local_path = Path("config/settings.local.yaml")
    example_path = Path("config/settings.example.yaml")

    if not local_path.exists():
        print("ERROR: config/settings.local.yaml not found.")
        return
    if not example_path.exists():
        print("ERROR: config/settings.example.yaml not found.")
        return

    with open(local_path, "r", encoding="utf-8") as f:
        local = yaml.safe_load(f) or {}
    with open(example_path, "r", encoding="utf-8") as f:
        example = yaml.safe_load(f) or {}

    from src.startup import _find_missing_keys
    missing = []
    _find_missing_keys(example, local, "", missing)

    if not missing:
        print("Config is up to date — no missing keys.")
    else:
        print(f"{len(missing)} missing keys:")
        for k in missing:
            print(f"  - {k}")


def cmd_train_pipeline(args):
    """Run the complete training pipeline end-to-end."""
    from src.training.curriculum import classify_all_examples
    from src.training.leakage_detector import check_outcome_leakage
    from src.training.quality_filter import score_all_unscored
    from src.training.trainer import run_fine_tune

    print("\n=== ARCIS TRAINING PIPELINE ===\n")

    print("[1/5] Scoring unscored training examples...")
    result = score_all_unscored()
    print(f"  Scored {result.get('scored', 0)} examples")

    print("\n[2/5] Running outcome leakage test...")
    leakage = check_outcome_leakage()
    if leakage.get("is_leaking"):
        print(f"  LEAKING — balanced accuracy {leakage['balanced_accuracy']:.1%}")
        if not getattr(args, "force", False):
            print("  ABORT: Fix leakage before training. Use --force to override.")
            return
        print("  --force: Proceeding despite leakage warning")
    else:
        balanced_accuracy = leakage.get("balanced_accuracy")
        status = leakage.get("status", "CLEAN")
        print(f"  {status} — balanced accuracy {balanced_accuracy:.1%}" if balanced_accuracy else f"  {status}")

    print("\n[3/5] Classifying training examples...")
    classify_result = classify_all_examples()
    print(f"  Classified {classify_result.get('classified', 0)} examples")

    print("\n[4/5] Exporting training data...")
    print("\n[5/5] Starting fine-tuning...")
    fine_tune_result = run_fine_tune()
    if fine_tune_result:
        print(f"\n  Model registered: {fine_tune_result.get('version_name', 'halcyon-latest')}")
        print("  TRAINING PIPELINE COMPLETE")
    else:
        print("\n  Training failed. Check logs.")


def cmd_evaluate_gate(args):
    """Run the 50-trade gate evaluation."""
    from src.evaluation.gate_evaluator import evaluate_50_trade_gate

    print("\n=== 50-TRADE GATE EVALUATION ===\n")
    result = evaluate_50_trade_gate()

    gates = result.get("gates", {})
    for key, gate in gates.items():
        status_icon = {"green": "[OK]", "yellow": "[WARN]", "red": "[FAIL]"}.get(gate.get("status"), "[--]")
        _safe_print(f"  {status_icon} {gate.get('label', key)}: {gate.get('value', 'n/a')} (green: {gate.get('green', 'n/a')}, yellow: {gate.get('yellow', 'n/a')})")

    print(f"\n  Trade count: {result.get('trade_count', 0)}")
    print(f"  Greens: {result.get('greens', 0)}, Reds: {result.get('reds', 0)}")
    print(f"\n  DECISION: {result.get('decision', 'insufficient data')}\n")

    if result.get("psr") is not None:
        print(f"  PSR(0): {result['psr']:.1%}")
    if result.get("bootstrap_ci"):
        ci = result["bootstrap_ci"]
        print(f"  Bootstrap Sharpe CI: [{ci[0]:.3f}, {ci[2]:.3f}]")


def cmd_performance_report(args):
    """Generate a performance report."""
    from src.evaluation.cto_report import format_cto_report, generate_cto_report

    days = getattr(args, "days", 30)
    print(f"\n=== PERFORMANCE REPORT (last {days} days) ===\n")
    try:
        data = generate_cto_report(days=days)
        print(format_cto_report(data))
    except Exception as exc:
        print(f"Error generating report: {exc}")


def cmd_collect_data(args):
    """Run data collection pipeline manually."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.data_collection.analyst_collector import collect_analyst_estimates
    from src.data_collection.cboe_collector import collect_cboe_ratios
    from src.data_collection.edgar_collector import collect_new_filings
    from src.data_collection.fed_collector import collect_fed_communications
    from src.data_collection.insider_collector import collect_insider_transactions
    from src.data_collection.macro_collector import collect_macro_snapshots
    from src.data_collection.options_collector import collect_options_chains
    from src.data_collection.options_metrics import compute_options_metrics
    from src.data_collection.short_interest_collector import collect_short_interest
    from src.data_collection.trends_collector import collect_google_trends
    from src.data_collection.vix_collector import collect_vix_term_structure
    from src.universe.sp100 import get_sp100_universe

    def _run(label: str, fn, *call_args, **call_kwargs):
        print(label)
        try:
            result = fn(*call_args, **call_kwargs)
            print(f"  {result}")
            return result
        except Exception as exc:
            print(f"  failed: {exc}")
            return {"error": str(exc)}

    print("\n=== DATA COLLECTION ===\n")
    universe = get_sp100_universe()
    now = datetime.now(ZoneInfo("America/New_York"))
    results = {}

    results["options"] = _run("[1/12] Collecting options chains...", collect_options_chains, universe)
    results["metrics"] = _run("[2/12] Computing options metrics...", compute_options_metrics, universe)
    results["vix"] = _run("[3/12] VIX term structure...", collect_vix_term_structure)
    results["cboe"] = _run("[4/12] CBOE ratios...", collect_cboe_ratios)
    results["macro"] = _run("[5/12] FRED macro indicators...", collect_macro_snapshots)
    results["trends"] = _run("[6/12] Google Trends (batch)...", collect_google_trends, universe, batch_size=20)

    print("[7/12] Earnings calendar...")
    try:
        from scripts.fetch_earnings_calendar import fetch_earnings_dates

        results["earnings"] = fetch_earnings_dates(universe)
        print(f"  {results['earnings']}")
        upcoming = results["earnings"].get("upcoming_7d", [])
        if upcoming:
            _safe_print("\n  WARNING - EARNINGS THIS WEEK:")
            for item in upcoming:
                print(f"    • {item}")
    except Exception as exc:
        results["earnings"] = {"error": str(exc)}
        print(f"  Earnings fetch failed: {exc}")

    results["edgar"] = _run("[8/12] SEC EDGAR filings...", collect_new_filings, universe)
    results["insider"] = _run("[9/12] Insider transactions...", collect_insider_transactions, universe)

    if now.day in (1, 2, 15, 16):
        results["short_interest"] = _run("[10/12] Short interest...", collect_short_interest, universe)
    else:
        results["short_interest"] = {"status": "skipped", "reason": "not settlement date"}
        print("[10/12] Short interest...")
        print("  skipped (not settlement date)")

    results["fed"] = _run("[11/12] Fed communications...", collect_fed_communications)
    results["analyst"] = _run("[12/12] Analyst estimates (batch)...", collect_analyst_estimates, universe, batch_size=20)

    failed_collectors = [name for name, result in results.items() if isinstance(result, dict) and "error" in result]
    print(f"\nData collection complete. Collectors: {len(results)}, failures: {len(failed_collectors)}")
    if failed_collectors:
        print(f"Failed collectors: {', '.join(failed_collectors)}")


def cmd_fetch_earnings(args):
    """Fetch upcoming earnings dates for S&P 100."""
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from scripts.fetch_earnings_calendar import fetch_earnings_dates, get_all_upcoming_earnings
    from src.universe.sp100 import get_sp100_universe

    universe = get_sp100_universe()
    print(f"\n{'=' * 60}")
    print("EARNINGS CALENDAR — S&P 100")
    print(f"{'=' * 60}")
    print(f"Fetching for {len(universe)} tickers...\n")

    result = fetch_earnings_dates(universe)
    print(f"\nResults: {result['tickers_with_dates']} tickers with dates, {result['errors']} errors")

    if result["upcoming_7d"]:
        _safe_print(f"\nWARNING - EARNINGS THIS WEEK ({len(result['upcoming_7d'])}):")
        for item in result["upcoming_7d"]:
            print(f"  • {item}")

    upcoming = get_all_upcoming_earnings(days=14)
    if upcoming:
        print(f"\n📅 NEXT 14 DAYS ({len(upcoming)} stocks):")
        for item in upcoming:
            print(f"  • {item['ticker']:6s} {item['earnings_date']} ({item['days_away']}d) {item.get('earnings_time') or ''}")


def cmd_council(args):
    from src.council.engine import CouncilEngine

    session_type = getattr(args, "type", "daily")
    question = getattr(args, "question", None)
    if question:
        session_type = "strategic"
    print(f"Running AI Council session (type: {session_type})...")
    if question:
        print(f"Question: {question}")
    engine = CouncilEngine()
    result = engine.run_session(
        session_type=session_type,
        trigger_reason=question or f"CLI {session_type}",
        custom_question=question,
    )
    direction = result.get("consensus", "unknown")
    consensus_type = result.get("consensus_type", "?")
    contested = result.get("is_contested", False)
    print(f"\nDirection: {direction.upper()} ({consensus_type}){' — CONTESTED' if contested else ''}")
    print(f"Score: {result.get('aggregated_score', 0):+.2f} | Confidence: {result.get('confidence_avg', 0):.0%}")
    print(f"Rounds: {result.get('rounds_completed', 0)} | Cost: ${result.get('total_cost', 0):.4f}")
    for assessment in result.get("agent_assessments", []):
        direction = assessment.get("direction", "?")
        confidence = assessment.get("confidence", 0)
        marker = {"bullish": "[BUY]", "neutral": "[---]", "bearish": "[SELL]"}.get(direction, "[---]")
        _safe_print(f"  {marker} {assessment.get('agent', '?')}: {direction} ({confidence:.0%}) -- {assessment.get('key_reasoning', '')[:80]}")


def _assert_safe_live_governor_combo(config: dict, force: bool) -> None:
    """#574 — Refuse to launch when live trading is on but the risk
    governor is disabled. That combination auto-approves every trade
    with no daily-loss cap, no per-position size limit, no VIX circuit
    breaker, no sector concentration check, and no correlation cap —
    the textbook system-blow-up scenario.

    The --force flag bypasses the check (logs critically, then proceeds)
    so the operator retains an explicit escape hatch for emergencies.
    """
    live_enabled = bool(config.get("live_trading", {}).get("enabled"))
    governor_enabled = bool(config.get("risk_governor", {}).get("enabled"))
    if live_enabled and not governor_enabled:
        msg = (
            "REFUSING TO LAUNCH: live_trading.enabled=true AND "
            "risk_governor.enabled=false. This auto-approves every trade "
            "with NO daily-loss cap, NO position-size limit, NO VIX "
            "circuit breaker, NO sector concentration cap, NO correlation "
            "limit. Set risk_governor.enabled=true OR pass --force to "
            "bypass (logs critically). (#574)"
        )
        if not force:
            raise RuntimeError(msg)
        # Force-bypass — log critically so the audit trail is unmistakable
        import logging
        logging.getLogger("src.cli.commands").critical(
            "[STARTUP] %s — operator passed --force, proceeding anyway.", msg,
        )


def cmd_startup(args):
    """Validate system and launch watch loop — single startup command."""
    import sys
    import time as _time
    from src.config import load_config
    from src.startup import (
        is_watch_loop_running, persist_startup_result, STARTUP_CATEGORIES,
    )

    config = load_config()
    check_only = getattr(args, "check_only", False)
    force = getattr(args, "force", False)

    # #574 — fail-fast on dangerous live+governor combination BEFORE
    # touching any state. Skip when --check-only since check-only mode
    # is non-destructive by definition.
    if not check_only:
        _assert_safe_live_governor_combo(config, force=force)

    if not check_only:
        existing_pid = is_watch_loop_running()
        if existing_pid:
            print(f"Another watch loop is already running (PID {existing_pid}).")
            print(f"Kill it first:  taskkill /PID {existing_pid} /F")
            sys.exit(1)

    print("=" * 44)
    print("         ARCIS — STARTUP SEQUENCE")
    print("=" * 44)

    # #630 — Capture deployed git SHA so the operator (and future log dives)
    # can spot when a long-running watch loop is running stale bytecode.
    try:
        from src.utils.deploy_info import log_deployment_info
        info = log_deployment_info("watch_start")
        print(f"  Deployed: {info.get('git_short_sha')} ({info.get('git_branch')}) — committed {info.get('git_commit_age')}")
    except Exception as exc:
        # Never let banner code crash startup.
        print(f"  Deployed: unknown (banner failed: {exc})")

    all_checks = []
    start = _time.time()
    for i, (label, check_fn) in enumerate(STARTUP_CATEGORIES, 1):
        print(f"\n[{i}/{len(STARTUP_CATEGORIES)}] {label}")
        results = check_fn(config, DB_PATH)
        all_checks.extend(results)
        for c in results:
            _print_startup_check(c)

    result = _build_startup_result(all_checks, int((_time.time() - start) * 1000))

    try:
        persist_startup_result(result, DB_PATH)
    except Exception as e:
        print(f"\n  (Could not persist startup result: {e})")

    p, w, c = len(result.passed), len(result.warnings), len(result.criticals)
    print(f"\n--- {p} passed | {w} warnings | "
          f"{c} {'CRITICAL' if c else 'critical'} " + "-" * 8)

    _notify_startup_telegram(result, args, check_only)
    _startup_decision(result, args, config, check_only)


def _build_startup_result(all_checks, elapsed_ms):
    """Build a StartupResult from collected checks."""
    import re
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.startup import StartupResult
    result = StartupResult(
        checks=all_checks, schema_fixes_applied=0,
        duration_ms=elapsed_ms,
        timestamp=datetime.now(ZoneInfo("America/New_York")).isoformat(),
    )
    for c in all_checks:
        if c.category == "schema" and "auto-fixed" in c.detail:
            m = re.search(r"(\d+) auto-fixed", c.detail)
            if m:
                result.schema_fixes_applied = int(m.group(1))
    return result


def _notify_startup_telegram(result, args, check_only):
    """Send Telegram notification with startup results."""
    try:
        from src.notifications.telegram import notify_startup_complete, is_telegram_enabled
        force = getattr(args, "force", False)
        p, w, c = len(result.passed), len(result.warnings), len(result.criticals)
        if is_telegram_enabled():
            notify_startup_complete(
                overall_status=result.overall_status,
                passed=p, warnings=w, criticals=c,
                warning_details=[ch.detail for ch in result.warnings[:5]],
                critical_details=[ch.detail for ch in result.criticals[:5]],
                launching=(c == 0 or force) and not check_only,
                email_mode=getattr(args, "email_mode", "digest"),
                overnight=not getattr(args, "no_overnight", False),
            )
    except Exception:
        pass


def _startup_decision(result, args, config, check_only):
    """Handle startup decision: block, check-only exit, or launch watch loop."""
    import sys
    force = getattr(args, "force", False)
    if result.criticals and not force:
        print("\nStartup blocked — resolve critical issues above.")
        print("Use --force to override at your own risk.")
        sys.exit(1)
    if check_only:
        sys.exit(2 if result.warnings else 0)
    overnight = not getattr(args, "no_overnight", False)
    email_mode = getattr(args, "email_mode", "digest")
    print(f"\nLaunching watch loop (overnight={'yes' if overnight else 'no'}"
          f" + {email_mode})...")
    from src.scheduler.watch import WatchLoop
    WatchLoop(config, email_mode=email_mode, overnight=overnight).run()


def _print_startup_check(check):
    """Print a single check result with color if supported."""
    import os
    use_color = os.isatty(1) and not os.environ.get("NO_COLOR")

    status_map = {
        "ok": ("OK  ", "\033[32m" if use_color else ""),
        "warn": ("WARN", "\033[33m" if use_color else ""),
        "critical": ("FAIL", "\033[31m" if use_color else ""),
    }
    label, color = status_map.get(check.status, ("??  ", ""))
    reset = "\033[0m" if use_color else ""

    print(f"       {color}{label}{reset} {check.detail}")
    if check.status != "ok" and check.fix_hint:
        print(f"            -> {check.fix_hint}")


def cmd_watch(args):
    from src.config import load_config
    from src.scheduler.watch import WatchLoop

    WatchLoop(
        load_config(),
        email_mode=getattr(args, "email_mode", None),
        overnight=getattr(args, "overnight", False),
    ).run()


def cmd_dashboard(args):
    import uvicorn

    port = getattr(args, "port", 8000)
    print(f"Starting dashboard at http://localhost:{port}")
    uvicorn.run("src.api.app:app", host="127.0.0.1", port=port, reload=False)


def cmd_validate_system(args):
    """Run system validation checks across all subsystems."""
    import json as _json

    from src.evaluation.system_validator import run_full_validation, save_validation_result

    print("Running system validation...")
    result = run_full_validation()

    if getattr(args, "json", False):
        print(_json.dumps(result, indent=2))
    else:
        status_icon = {"healthy": "[OK]", "degraded": "[WARN]", "critical": "[FAIL]"}.get(result["overall_status"], "?")
        _safe_print(f"\n{status_icon} Overall: {result['overall_status'].upper()}")
        _safe_print(f"   Passed: {result['checks_passed']}  |  Warnings: {result['checks_warning']}  |  Failed: {result['checks_failed']}")
        _safe_print(f"   Total checks: {result['checks_total']}\n")

        for category, checks in result["categories"].items():
            cat_fails = sum(1 for check in checks if check["status"] == "fail")
            cat_warns = sum(1 for check in checks if check["status"] == "warn")
            cat_pass = sum(1 for check in checks if check["status"] == "pass")
            icon = "[FAIL]" if cat_fails else "[WARN]" if cat_warns else "[OK]"
            _safe_print(f"  {icon} {category.upper()} ({cat_pass}P / {cat_warns}W / {cat_fails}F)")
            for check in checks:
                marker = {"pass": "  [OK]", "warn": "  [WARN]", "fail": "  [FAIL]"}.get(check["status"], "  ?")
                _safe_print(f"    {marker} {check['name']}: {check['detail']}")
            print()

    result_id = save_validation_result(result)
    print(f"Result saved: {result_id}")

    if getattr(args, "fix", False):
        print("\n--fix: Attempting auto-fixes...")
        initialize_database()
        print("  Re-ran initialize_database() to ensure all tables exist.")


def cmd_validate_schema(args):
    """Validate database schema against the schema registry."""
    from src.schema.validator import validate_sqlite, validate_codebase, fix_issues

    print("Validating SQLite schema...")
    issues = validate_sqlite(DB_PATH)
    code_issues = validate_codebase()

    all_issues = issues + code_issues
    for issue in all_issues:
        print(f"  {issue}")

    if not all_issues:
        print("Schema OK — no issues found.")
        return

    print(f"\n{len(issues)} database issues, {len(code_issues)} codebase violations")

    if getattr(args, "fix", False) and issues:
        actions = fix_issues(issues, DB_PATH)
        for a in actions:
            print(f"  FIX: {a}")
