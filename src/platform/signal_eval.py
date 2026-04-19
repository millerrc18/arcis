"""Signal evaluation helpers extracted from backtest_engine.

Called by: src.platform.backtest_engine,
           src.platform.shadow_harness (via find_candidates_for_date).
Calls: sqlite3 (event-table queries), src.platform.strategy_spec,
       src.platform.backtest_attribution (_inject_cosine_scores).
Owns tables: none.
Config keys: PLATFORM_EDGAR_DB (optional env override for event-table DB).
Tests: tests/platform/test_backtest_engine.py (exercised via backtest_engine),
       tests/platform/test_find_candidates.py.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta

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


def is_excluded_event_date(entry_iso: str, entry_spec: dict) -> bool:
    """True if entry_iso matches any category in entry.event_exclusion.categories.

    v0.26.2-scoped schema extension — applied in _run_event_driven after
    resolving the filing to its entry date.
    """
    cats = (entry_spec.get("event_exclusion") or {}).get("categories", [])
    if not cats:
        return False
    from src.diagnostics.known_events import is_known_event
    return any(is_known_event(entry_iso, category=c) for c in cats)


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
    sector_filter = spec.universe.get("sector_filter")
    if sector_filter:
        from src.universe.sectors import SECTOR_MAP
        tickers = [t for t in tickers if SECTOR_MAP.get(t) in sector_filter]
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


# ── Live candidate generation (Sprint 4 cont. Step A) ────────────────────────


def find_candidates_for_date(
    spec: StrategySpec,
    db_path: str,
    as_of: datetime,
) -> list[dict]:
    """Return candidate trades the strategy signal would fire at as_of.

    For event_driven specs: queries spec.entry.event_table for rows within
    entry.event_filter.filing_date_within_days of as_of, evaluates the signal
    + combinator, returns one dict per qualifying event.

    Candidates are deduplicated against currently-open shadow_trades for the
    strategy's desk (research_<strategy_id>) — no double-entry on consecutive
    ticks.

    For scheduled specs: returns [] with a warning (scheduled live-flow
    integration is v0.24.1 follow-up).

    For python_plugin specs: raises NotImplementedError (Task 2 / issue #474).

    Called by: src.platform.shadow_harness.ShadowHarness._find_candidates.
    Returns: list of {ticker, as_of (ISO str), shares, price,
                      signal_strength, metadata}.
    """
    kind = spec.entry.get("kind")
    if kind == "event_driven":
        return _find_candidates_event_driven(spec, db_path, as_of)
    if kind == "scheduled":
        logger.warning(
            "[SIGNAL_EVAL] scheduled-kind find_candidates_for_date not yet "
            "supported for live flow; returning []. "
            "backtest_engine._run_scheduled still works for backtests. "
            "Track v0.24.1 follow-up."
        )
        return []
    if kind == "python_plugin":
        raise NotImplementedError(
            "python_plugin find_candidates_for_date is Task 2 (issue #474)"
        )
    raise ValueError(f"unknown entry.kind: {kind!r}")


def _find_candidates_event_driven(
    spec: StrategySpec, db_path: str, as_of: datetime,
) -> list[dict]:
    """Event-driven candidate generation at a single as_of date.

    1. Resolve universe.
    2. Query event table for rows within filing_date_within_days of as_of.
    3. Inject cosine scores + evaluate signal via _evaluate_event_signal.
    4. Dedupe against open shadow_trades for this strategy's desk.
    5. Return one candidate dict per qualifying event.
    """
    from src.platform.backtest_attribution import _inject_cosine_scores

    entry = spec.entry
    signal = entry.get("signal", [])
    combinator = entry.get("combinator", "all")
    within_days = int(entry.get("event_filter", {}).get("filing_date_within_days", 5))
    tickers = _resolve_universe(spec.universe.get("tickers", []))
    if not tickers:
        logger.warning("[SIGNAL_EVAL] empty universe for %s; returning []", spec.strategy_id)
        return []

    live_db = os.environ.get("PLATFORM_EDGAR_DB", db_path)
    event_rows = _query_event_rows_for_date(spec, tickers, as_of, within_days, live_db)
    if event_rows is None:
        return []

    desk = f"research_{spec.strategy_id}"
    open_tickers = _load_open_tickers_for_desk(desk, live_db)
    spec_hash = _spec_hash(spec)

    candidates: list[dict] = []
    as_of_iso = as_of.isoformat()
    for row in event_rows:
        ticker = row.get("ticker", "")
        if ticker in open_tickers:
            logger.debug("[SIGNAL_EVAL] %s already open on desk %s — skipping", ticker, desk)
            continue
        try:
            sections = json.loads(row.get("sections_json") or "{}")
        except json.JSONDecodeError:
            sections = {}
        accession = row.get("accession_number", "")
        sections = _inject_cosine_scores(sections, signal, ticker, accession, live_db)
        if not _evaluate_event_signal(sections, signal, combinator):
            continue
        signal_strength = _compute_signal_strength(sections, signal, combinator)
        candidates.append(_build_candidate(ticker, as_of_iso, signal_strength, row, spec_hash))
    return candidates


def _query_event_rows_for_date(
    spec: StrategySpec,
    tickers: list[str],
    as_of: datetime,
    within_days: int,
    db_path: str,
) -> list[dict] | None:
    """Query spec.entry.event_table for rows within [as_of - within_days, as_of].

    Returns None on fatal DB error (caller returns []); returns [] when no rows found.
    """
    entry = spec.entry
    table = entry.get("event_table", "edgar_filings")
    form_types = entry.get("event_filter", {}).get("form_type", [])
    window_start = (as_of - timedelta(days=within_days)).strftime("%Y-%m-%d")
    window_end = as_of.strftime("%Y-%m-%d")
    rows: list[dict] = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            ph_t = ",".join("?" for _ in tickers)
            if form_types:
                ph_f = ",".join("?" for _ in form_types)
                sql = (
                    f"SELECT * FROM {table} WHERE ticker IN ({ph_t}) "
                    f"AND form_type IN ({ph_f}) AND filing_date BETWEEN ? AND ?"
                )
                params = (*tickers, *form_types, window_start, window_end)
            else:
                sql = (
                    f"SELECT * FROM {table} WHERE ticker IN ({ph_t}) "
                    "AND filing_date BETWEEN ? AND ?"
                )
                params = (*tickers, window_start, window_end)
            for r in conn.execute(sql, params).fetchall():
                rows.append({k: r[k] for k in r.keys()})
    except Exception as exc:
        logger.warning("[SIGNAL_EVAL] event-table query failed for %s: %s", spec.strategy_id, exc)
        return None
    return rows


def _load_open_tickers_for_desk(desk: str, db_path: str) -> set[str]:
    """Return set of tickers with open shadow_trades rows for desk.

    Returns empty set on any error (table may not exist yet — safe to skip dedup).
    """
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT ticker FROM shadow_trades "
                "WHERE desk = ? AND actual_exit_time IS NULL",
                (desk,),
            ).fetchall()
            return {r[0] for r in rows}
    except Exception:
        return set()


def _build_candidate(
    ticker: str, as_of_iso: str, signal_strength: float, row: dict, spec_hash: str,
) -> dict:
    """Construct a candidate dict from a qualifying event row."""
    return {
        "ticker": ticker,
        "as_of": as_of_iso,
        "shares": 1,      # position sizing is the harness's responsibility
        "price": 0.0,     # live price fetched by harness at order time
        "signal_strength": signal_strength,
        "metadata": {
            "filing_accession": row.get("accession_number", ""),
            "filing_date": row.get("filing_date"),
            "form_type": row.get("form_type"),
            "strategy_spec_hash": spec_hash,
        },
    }


def _compute_signal_strength(
    sections: dict, signal: list[dict], combinator: str,
) -> float:
    """Return a [0,1] signal strength heuristic.

    For less_than conditions: distance = (threshold - value) / threshold.
    Higher distance → stronger signal. Returns max distance across passing
    cosine conditions (or 0.5 if none found).
    """
    distances: list[float] = []
    for condition in signal:
        if condition.get("metric") != "cosine_similarity":
            continue
        target = condition.get("target", "")
        key = f"{target}_cosine_yoy"
        value = sections.get(key)
        if value is None:
            continue
        threshold = float(condition.get("threshold", 0.0))
        op = condition.get("operator", "less_than")
        if op == "less_than" and threshold > 0 and value < threshold:
            distances.append((threshold - value) / threshold)
        elif op == "greater_than" and threshold > 0 and value > threshold:
            distances.append((value - threshold) / (1.0 - threshold + 1e-9))
    return max(distances) if distances else 0.5


def _spec_hash(spec: StrategySpec) -> str:
    """Short deterministic hash of the strategy spec for metadata tagging."""
    import hashlib
    raw = f"{spec.strategy_id}:{spec.entry}:{spec.exit}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]
