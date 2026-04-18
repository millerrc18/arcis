"""Position monitor — Tier 1 (15-min) held position management.

Extracted from watch.py for multi-cadence scanning architecture.
Manages open positions: stop/target proximity, MR RSI exits,
intra-day reconciliation.

Called by: scheduler.watch
Calls: shadow_trading.executor, features.mean_reversion, shadow_trading.reconcile
Owns tables: none
Config keys: strategies.mean_reversion.*, shadow_trading.*
Tests: tests/test_position_monitor.py
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH, load_config

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def run_position_monitor(config: dict | None = None, db_path: str = DB_PATH) -> dict:
    """Run Tier 1 position monitoring (15-min cadence).

    Returns summary dict with actions taken.
    """
    config = config or load_config()
    summary = {"actions": [], "reconciled": 0, "errors": 0}

    # 1. Check and manage paper trades (stop/target/timeout/MR exits)
    try:
        from src.shadow_trading.executor import check_and_manage_open_trades
        actions = check_and_manage_open_trades(
            db_path=db_path, source_filter="paper")
        summary["actions"] = actions
        if actions:
            logger.info("[POSITION] %d paper trade actions taken", len(actions))
    except Exception as e:
        logger.warning("[POSITION] Paper trade management failed: %s", e)
        summary["errors"] += 1

    # 2. Check and manage live trades (separate error handling)
    try:
        from src.shadow_trading.executor import check_and_manage_open_trades
        live_actions = check_and_manage_open_trades(
            db_path=db_path, source_filter="live")
        summary["actions"].extend(live_actions)
        live_closed = len([a for a in live_actions if a.get("type") == "closed"])
        if live_closed:
            logger.info("[POSITION] Live trade check: %d trades closed", live_closed)
    except Exception as e:
        logger.warning("[POSITION] Live trade check failed: %s", e)
        summary["errors"] += 1

    # 2.5. Check for stale price data on open positions
    try:
        from src.data_enrichment.staleness import get_stale_tickers
        stale = get_stale_tickers("price", threshold="warning", db_path=db_path)
        if stale:
            logger.warning("[POSITION] Stale price data for %d tickers: %s",
                           len(stale), stale[:5])
    except Exception:
        pass  # Staleness check is advisory only

    # 3. Intra-day reconciliation (swing + every active research desk)
    try:
        from src.shadow_trading.reconcile_dispatch import reconcile_all_paper_trades
        all_results = reconcile_all_paper_trades(db_path=db_path, dry_run=False)
        total_closed: list = []
        for desk, result in all_results.items():
            closed = result.get("marked_closed", [])
            total_closed.extend(closed)
        summary["reconciled"] = len(total_closed)
        if total_closed:
            logger.info("[POSITION] Reconciliation closed %d stale trades: %s",
                        len(total_closed), total_closed)
    except Exception as e:
        logger.warning("[POSITION] Reconciliation failed: %s", e)
        summary["errors"] += 1

    return summary
