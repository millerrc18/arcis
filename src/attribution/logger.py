"""Attribution logger — two-phase alpha attribution for ranker vs LLM evaluation.

Called by: scheduler.watch
Calls: none
Owns tables: attribution_trades
Config keys: none
Tests: tests/test_attribution.py
"""

import logging
import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

_ALLOWED_ATTRIBUTION_COLUMNS = {
    "llm_action", "llm_conviction", "recommendation_id", "pair_type",
}


def log_attribution_before_llm(
    ticker: str,
    ranker_score: float,
    entry_price: float,
    stop_price: float,
    target_price: float,
    recommendation_id: str | None = None,
    db_path: str = DB_PATH,
) -> str:
    """Phase 1: Log attribution row BEFORE LLM processing.

    Returns the attribution_id for later update.
    """
    attribution_id = str(uuid.uuid4())
    now = datetime.now(ET).isoformat()

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO attribution_trades "
                "(attribution_id, recommendation_id, ticker, scan_timestamp, "
                "ranker_score, llm_action, ranker_only_entry, ranker_only_stop, "
                "ranker_only_target, ranker_only_outcome, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (attribution_id, recommendation_id, ticker, now,
                 ranker_score, "pending", entry_price, stop_price,
                 target_price, "pending", now),
            )
            conn.commit()
        logger.info("[ATTRIBUTION] Phase 1: logged %s (score=%.1f)", ticker, ranker_score)
    except Exception as e:
        logger.warning("[ATTRIBUTION] Phase 1 failed for %s: %s", ticker, e)

    return attribution_id


def log_attribution_after_llm(
    attribution_id: str,
    llm_action: str,
    llm_conviction: int | None = None,
    recommendation_id: str | None = None,
    db_path: str = DB_PATH,
) -> None:
    """Phase 2: Update attribution row AFTER LLM processing.

    llm_action: 'taken', 'rejected', 'parse_failed', 'conviction_none'
    """
    try:
        with sqlite3.connect(db_path) as conn:
            fields = ["llm_action = ?"]
            values = [llm_action]

            if llm_conviction is not None:
                fields.append("llm_conviction = ?")
                values.append(llm_conviction)

            if recommendation_id:
                fields.append("recommendation_id = ?")
                values.append(recommendation_id)

            # Determine pair_type
            if llm_action == "taken":
                pair_type = "both_taken"
            elif llm_action == "rejected":
                pair_type = "llm_rejected"
            elif llm_action in ("parse_failed", "conviction_none"):
                pair_type = "llm_rejected"
            else:
                pair_type = "unknown"
            fields.append("pair_type = ?")
            values.append(pair_type)

            col_names = {f.split(" = ")[0].strip() for f in fields}
            if not col_names.issubset(_ALLOWED_ATTRIBUTION_COLUMNS):
                raise ValueError(f"Invalid columns in attribution update: {col_names - _ALLOWED_ATTRIBUTION_COLUMNS}")

            values.append(attribution_id)
            conn.execute(
                f"UPDATE attribution_trades SET {', '.join(fields)} "
                "WHERE attribution_id = ?",
                values,
            )
            conn.commit()
        logger.info("[ATTRIBUTION] Phase 2: %s -> %s", attribution_id[:8], llm_action)
    except Exception as e:
        logger.warning("[ATTRIBUTION] Phase 2 failed: %s", e)


def link_trade_outcome(
    recommendation_id: str,
    outcome: str,
    pnl_pct: float,
    db_path: str = DB_PATH,
) -> bool:
    """Link actual trade outcome to attribution record via recommendation_id.

    Called when a shadow/live trade closes. Updates llm_portfolio_outcome
    and llm_portfolio_pnl_pct on the matching attribution_trades row.
    Returns True if a row was updated.
    """
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                "UPDATE attribution_trades SET llm_portfolio_outcome = ?, "
                "llm_portfolio_pnl_pct = ? WHERE recommendation_id = ?",
                (outcome, pnl_pct, recommendation_id),
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.info("[ATTRIBUTION] Linked outcome %s (%.2f%%) to rec %s",
                            outcome, pnl_pct, recommendation_id[:8])
                return True
            return False
    except Exception as e:
        logger.warning("[ATTRIBUTION] link_trade_outcome failed: %s", e)
        return False


def simulate_mechanical_outcome(
    entry_price: float,
    stop_price: float,
    target_price: float,
    timeout_days: int,
    ohlcv: list[dict],
) -> tuple[str, float, int]:
    """Simulate mechanical bracket outcome from historical OHLCV.

    Returns (outcome, exit_price, days_held).
    outcome: 'win', 'loss', 'timeout'
    """
    # Hotfix (SD#41 D2 follow-up) — guard against bad input data. A handful of
    # early-pipeline attribution rows have entry_price = 0.0 (or None). The
    # caller's pnl math divides by entry, so anything <= 0 would trip
    # ZeroDivisionError. Return a harmless timeout so the caller can skip.
    if entry_price is None or entry_price <= 0:
        return "timeout", 0.0, 0

    for day_idx, bar in enumerate(ohlcv):
        low = bar.get("Low", bar.get("low", 0))
        high = bar.get("High", bar.get("high", 0))
        close = bar.get("Close", bar.get("close", 0))

        # Check stop first (conservative)
        if low <= stop_price:
            return "loss", stop_price, day_idx + 1
        if high >= target_price:
            return "win", target_price, day_idx + 1

    # Timeout — exit at last close
    if ohlcv:
        last_close = ohlcv[-1].get("Close", ohlcv[-1].get("close", entry_price))
        return "timeout", last_close, len(ohlcv)
    return "timeout", entry_price, 0


def _resolve_one_row(conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
    """Fetch OHLCV for a single pending row and update its outcome.

    Returns True if the row was resolved, False if yfinance returned empty
    or the lookup failed. Handles the SD#41 D2 MultiIndex fix — yfinance
    returns tuple-keyed columns for single-ticker requests; flatten before
    building the ohlcv dict list so `bar.get("Low")` hits a string key.
    """
    # Hotfix (SD#41 D2 follow-up) — guard against bad input data. See the
    # sibling guard in simulate_mechanical_outcome for context. Returning
    # False skips the row cleanly instead of letting the pnl division crash
    # inside the except block and silently dropping the trade.
    if row["ranker_only_entry"] is None or row["ranker_only_entry"] == 0:
        return False
    try:
        import yfinance as yf
        from datetime import timedelta
        scan_date = row["scan_timestamp"][:10]
        start = datetime.fromisoformat(scan_date) + timedelta(days=1)
        end = start + timedelta(days=8)  # 7-day timeout + 1
        data = yf.download(
            row["ticker"], start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"), progress=False, auto_adjust=True,
        )
        if data.empty:
            return False
        if hasattr(data.columns, "get_level_values"):
            data.columns = data.columns.get_level_values(0)
        ohlcv = data.reset_index().to_dict("records")
        outcome, exit_price, _ = simulate_mechanical_outcome(
            row["ranker_only_entry"], row["ranker_only_stop"],
            row["ranker_only_target"], 7, ohlcv,
        )
        pnl_pct = (exit_price - row["ranker_only_entry"]) / row["ranker_only_entry"] * 100
        conn.execute(
            "UPDATE attribution_trades SET ranker_only_outcome = ?, "
            "ranker_only_pnl_pct = ? WHERE attribution_id = ?",
            (outcome, round(pnl_pct, 2), row["attribution_id"]),
        )
        return True
    except Exception as e:
        logger.warning("[ATTRIBUTION] Failed to resolve %s: %s", row["ticker"], e)
        return False


def resolve_pending_outcomes(db_path: str = DB_PATH) -> int:
    """Post-close job: resolve pending attribution outcomes using historical data.

    Called by the watch loop at 4:30 PM ET. Returns count of resolved rows.
    Per-row work delegated to `_resolve_one_row` to keep this function under
    the 60-line cap.
    """
    resolved = 0
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            pending = conn.execute(
                "SELECT attribution_id, ticker, ranker_only_entry, "
                "ranker_only_stop, ranker_only_target, scan_timestamp "
                "FROM attribution_trades WHERE ranker_only_outcome = 'pending'"
            ).fetchall()
            if not pending:
                return 0
            for row in pending:
                if _resolve_one_row(conn, row):
                    resolved += 1
            conn.commit()
    except Exception as e:
        logger.warning("[ATTRIBUTION] resolve_pending_outcomes failed: %s", e)
    logger.info("[ATTRIBUTION] Resolved %d pending outcomes", resolved)
    return resolved


def _win_rate(wins: int, resolved: int) -> float | None:
    return round(wins / resolved, 3) if resolved else None


def get_attribution_stats(db_path: str = DB_PATH) -> dict:
    """Get attribution statistics for the dashboard."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute("SELECT COUNT(*) FROM attribution_trades").fetchone()[0]

            by_action = {r["llm_action"]: r["cnt"] for r in conn.execute(
                "SELECT llm_action, COUNT(*) as cnt FROM attribution_trades GROUP BY llm_action"
            ).fetchall()}
            by_pair = {r["pair_type"]: r["cnt"] for r in conn.execute(
                "SELECT pair_type, COUNT(*) as cnt FROM attribution_trades GROUP BY pair_type"
            ).fetchall()}

            # Win rates by portfolio
            ranker_resolved = conn.execute(
                "SELECT COUNT(*) FROM attribution_trades WHERE ranker_only_outcome != 'pending'"
            ).fetchone()[0]
            ranker_wins = conn.execute(
                "SELECT COUNT(*) FROM attribution_trades WHERE ranker_only_outcome = 'win'"
            ).fetchone()[0]
            llm_resolved = conn.execute(
                "SELECT COUNT(*) FROM attribution_trades WHERE llm_portfolio_outcome IS NOT NULL"
            ).fetchone()[0]
            llm_wins = conn.execute(
                "SELECT COUNT(*) FROM attribution_trades WHERE llm_portfolio_outcome = 'win'"
            ).fetchone()[0]

            return {
                "total_pairs": total,
                "by_action": by_action,
                "by_pair_type": by_pair,
                "ranker_only": {"resolved": ranker_resolved, "wins": ranker_wins,
                                "win_rate": _win_rate(ranker_wins, ranker_resolved)},
                "llm_portfolio": {"resolved": llm_resolved, "wins": llm_wins,
                                  "win_rate": _win_rate(llm_wins, llm_resolved)},
                "statistical_power": "insufficient" if total < 50 else (
                    "low" if total < 200 else "adequate"),
            }
    except Exception as e:
        logger.warning("[ATTRIBUTION] get_attribution_stats failed: %s", e)
        return {"total_pairs": 0, "error": str(e)}
