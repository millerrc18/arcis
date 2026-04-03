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

    # 1. Check and manage open trades (stop/target/timeout/MR exits)
    try:
        from src.shadow_trading.executor import check_and_manage_open_trades
        actions = check_and_manage_open_trades(db_path=db_path)
        summary["actions"] = actions
        if actions:
            logger.info("[POSITION] %d trade actions taken", len(actions))
    except Exception as e:
        logger.warning("[POSITION] Trade management failed: %s", e)
        summary["errors"] += 1

    # 2. Independent live trade check
    try:
        from src.shadow_trading.executor import check_and_manage_open_trades as _check_live
        live_actions = _check_live(source_filter="live", db_path=db_path)
        live_closed = len([a for a in live_actions if a.get("type") == "closed"])
        if live_closed:
            logger.info("[POSITION] Live trade check: %d trades closed", live_closed)
    except Exception as e:
        logger.warning("[POSITION] Live trade check failed: %s", e)
        summary["errors"] += 1

    # 3. Intra-day reconciliation
    try:
        from src.shadow_trading.reconcile import reconcile_paper_trades
        result = reconcile_paper_trades(dry_run=False)
        closed = result.get("marked_closed", [])
        summary["reconciled"] = len(closed)
        if closed:
            logger.info("[POSITION] Reconciliation closed %d stale trades: %s",
                        len(closed), closed)
    except Exception as e:
        logger.warning("[POSITION] Reconciliation failed: %s", e)
        summary["errors"] += 1

    return summary
