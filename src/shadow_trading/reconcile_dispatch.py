"""Per-desk reconcile dispatch helper.

Called by: src.scheduler.overnight, src.scheduler.position_monitor,
           src.scheduler.watch.
Calls: src.platform.promotion.get_strategies_by_status,
       src.shadow_trading.reconcile.reconcile_paper_trades.
Owns tables: none (reads strategy_registry, writes via reconcile_paper_trades).
Config keys: none.
Tests: tests/scheduler/test_overnight_reconcile_dispatch.py.

Extracted from the 3 scheduler call sites so the "swing + every active
research desk" pattern lives in one place. If a strategy's desk raises,
others continue — failure isolation.
"""
from __future__ import annotations

import logging
from typing import Any

from src.platform.promotion import get_strategies_by_status
from src.shadow_trading.reconcile import reconcile_paper_trades

logger = logging.getLogger(__name__)


def reconcile_all_paper_trades(
    db_path: str | None = None, dry_run: bool = False,
) -> dict[str, Any]:
    """Reconcile swing + every strategy in shadow_trading state.

    Returns dict keyed by desk with per-desk result payloads.
    Failure on one desk does not stop others.
    """
    results: dict[str, Any] = {}
    try:
        results["swing"] = reconcile_paper_trades(
            desk="swing", dry_run=dry_run, db_path=db_path,
        )
    except Exception as e:
        logger.exception("[RECONCILE] swing reconcile failed")
        results["swing"] = {"error": str(e)}

    try:
        active = get_strategies_by_status(
            ["shadow_trading"], db_path=db_path,
        )
    except Exception:
        logger.exception("[RECONCILE] get_strategies_by_status failed")
        active = []

    for strategy_id in active:
        desk = f"research_{strategy_id}"
        try:
            results[desk] = reconcile_paper_trades(
                desk=desk, dry_run=dry_run, db_path=db_path,
            )
        except Exception as e:
            logger.exception(
                "[RECONCILE] %s reconcile failed — continuing", desk,
            )
            results[desk] = {"error": str(e)}

    return results
