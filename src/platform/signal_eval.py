"""Signal evaluation helpers extracted from backtest_engine.

Called by: src.platform.backtest_engine.
Calls: sqlite3 (event-table queries), src.platform.strategy_spec.
Owns tables: none.
Config keys: PLATFORM_EDGAR_DB (optional env override for event-table DB).
Tests: tests/platform/test_backtest_engine.py (exercised via backtest_engine).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime

from src.platform.strategy_spec import StrategySpec

logger = logging.getLogger(__name__)

_DAY_OF_WEEK_MAP = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
}


def _matches_scheduled_trigger(day: datetime, entry_spec: dict) -> bool:
    """For MVP: fire if day_of_week matches entry.day_of_week (if present)."""
    dow_name = entry_spec.get("day_of_week")
    if dow_name is None:
        return True
    target = _DAY_OF_WEEK_MAP.get(dow_name)
    return target is not None and day.weekday() == target


def _evaluate_event_signal(
    sections: dict,
    signal: list[dict],
    combinator: str = "all",
) -> bool:
    """Evaluate signal conditions against sections dict.

    combinator: "all" (default, AND logic) or "any" (OR logic).
    Hotfix v0.24.0-alpha2.1: was hardcoded to AND; now respects "any"
    combinator so spec.entry.combinator=any fires when ANY filter passes.
    """
    use_any = combinator.lower() == "any"
    any_passed = False
    for condition in signal:
        if condition.get("metric") != "cosine_similarity":
            continue
        target = condition.get("target", "")
        # map target like "item_1a" → key "item_1a_cosine_yoy"
        key = f"{target}_cosine_yoy"
        if key not in sections:
            if not use_any:
                return False  # AND: missing key means condition can't pass
            continue  # ANY: skip missing keys (not a failure)
        value = sections[key]
        threshold = float(condition.get("threshold", 0.0))
        op = condition.get("operator", "less_than")
        condition_passes = (
            (op == "less_than" and value < threshold)
            or (op == "greater_than" and value > threshold)
        )
        if use_any:
            if condition_passes:
                return True  # OR: short-circuit on first pass
        else:
            if not condition_passes:
                return False  # AND: short-circuit on first failure
            any_passed = True
    if use_any:
        return False  # OR: no condition passed
    return True  # AND: all conditions passed (or no cosine conditions found)


_UNIVERSE_ALIASES: dict[str, str] = {
    "sp100": "src.universe.sp100.get_sp100_universe",
}


def _resolve_universe(tickers_spec) -> list[str]:
    """Resolve a universe spec value to a concrete list of ticker strings.

    Accepts:
      - A list of tickers (returned as-is).
      - A string alias like "sp100" (resolved via _UNIVERSE_ALIASES).
    Returns an empty list for unrecognised inputs.
    """
    if isinstance(tickers_spec, list):
        return tickers_spec
    if isinstance(tickers_spec, str):
        fn_path = _UNIVERSE_ALIASES.get(tickers_spec.lower())
        if fn_path:
            module_path, fn_name = fn_path.rsplit(".", 1)
            import importlib
            mod = importlib.import_module(module_path)
            return getattr(mod, fn_name)()
        logger.warning("[PLATFORM] unknown universe alias %r — returning []", tickers_spec)
    return []


def _query_event_rows(spec: StrategySpec, cfg) -> list[dict]:
    """Query spec.entry.event_table for matching rows in [start, end].

    cfg is a BacktestConfig; typed as Any here to avoid a circular import.
    Hotfix v0.24.0-alpha2.1: resolve universe string aliases (e.g. "sp100")
    to concrete ticker lists instead of returning [] for non-list values.
    """
    entry = spec.entry
    table = entry.get("event_table", "edgar_filings")
    form_types = entry.get("event_filter", {}).get("form_type", [])
    tickers = _resolve_universe(spec.universe.get("tickers", []))
    if not tickers:
        return []

    db_path = os.environ.get("PLATFORM_EDGAR_DB")
    if not db_path:
        from src.config import DB_PATH
        db_path = DB_PATH
    if not os.path.exists(db_path):
        return []

    rows: list[dict] = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            placeholders_t = ",".join("?" for _ in tickers)
            placeholders_f = ",".join("?" for _ in form_types)
            sql = (
                f"SELECT * FROM {table} WHERE ticker IN ({placeholders_t}) "
                f"AND form_type IN ({placeholders_f}) "
                "AND filing_date BETWEEN ? AND ?"
            )
            params = (*tickers, *form_types, cfg.start_date, cfg.end_date)
            for r in conn.execute(sql, params).fetchall():
                rows.append({k: r[k] for k in r.keys()})
    except Exception as exc:
        logger.warning("[PLATFORM] event-table query failed: %s", exc)
    return rows
