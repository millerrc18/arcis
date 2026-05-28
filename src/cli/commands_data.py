"""CLI command implementations — data domain (Arcis).

Called by: cli.commands (re-export), main (via re-export)
Calls: config, data_ingestion.market_data, journal.store, risk.governor, services.recap_service, services.scan_service, services.shadow_service, services.watchlist_service, shadow_trading.alpaca_adapter, shadow_trading.executor, shadow_trading.exit_reason, shadow_trading.reconcile, universe.sp100
Owns tables: none
Config keys: live_trading, shadow_trading, starting_capital
Tests: tests/cli/test_cli_split_integrity.py, tests/cli/test_email_cli_passthrough.py, tests/shadow_trading/test_exit_reason_writer_coverage.py
"""

import logging

from src.config import DB_PATH
from src.utils.db import connect_db
from src.journal.store import initialize_database
from src.shadow_trading.exit_reason import coerce_exit_reason
from src.cli.commands_ops import _safe_print

logger = logging.getLogger(__name__)


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


def cmd_scan(args):
    from src.config import load_config
    from src.services.scan_service import run_scan

    config = load_config()
    result = run_scan(
        config,
        dry_run=getattr(args, "dry_run", False),
        send_email_flag=getattr(args, "email", False),
        run_shadow=not getattr(args, "no_shadow", False),
        via_cli=True,
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
        via_cli=True,
    )
    print(result["email_body"])


def cmd_eod_recap(args):
    from src.config import load_config
    from src.services.recap_service import generate_eod_recap

    result = generate_eod_recap(
        load_config(),
        send_email_flag=getattr(args, "email", False) and not getattr(args, "dry_run", False),
        via_cli=True,
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
        exit_reason=coerce_exit_reason(reason, ticker=ticker),
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
        with connect_db(DB_PATH) as conn:
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
    reason = coerce_exit_reason(getattr(args, "reason", "manual"), ticker=ticker)

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
