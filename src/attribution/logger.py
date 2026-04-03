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


def resolve_pending_outcomes(db_path: str = DB_PATH) -> int:
    """Post-close job: resolve pending attribution outcomes using historical data.

    Called by the watch loop at 4:30 PM ET.
    Returns count of resolved rows.
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
                try:
                    import yfinance as yf
                    from datetime import timedelta

                    scan_date = row["scan_timestamp"][:10]
                    start = datetime.fromisoformat(scan_date) + timedelta(days=1)
                    end = start + timedelta(days=8)  # 7-day timeout + 1

                    data = yf.download(
                        row["ticker"], start=start.strftime("%Y-%m-%d"),
                        end=end.strftime("%Y-%m-%d"), progress=False,
                    )
                    if data.empty:
                        continue

                    ohlcv = data.reset_index().to_dict("records")
                    outcome, exit_price, days = simulate_mechanical_outcome(
                        row["ranker_only_entry"], row["ranker_only_stop"],
                        row["ranker_only_target"], 7, ohlcv,
                    )

                    pnl_pct = ((exit_price - row["ranker_only_entry"])
                               / row["ranker_only_entry"] * 100)

                    conn.execute(
                        "UPDATE attribution_trades SET ranker_only_outcome = ?, "
                        "ranker_only_pnl_pct = ? WHERE attribution_id = ?",
                        (outcome, round(pnl_pct, 2), row["attribution_id"]),
                    )
                    resolved += 1
                except Exception as e:
                    logger.warning("[ATTRIBUTION] Failed to resolve %s: %s",
                                   row["ticker"], e)

            conn.commit()
    except Exception as e:
        logger.warning("[ATTRIBUTION] resolve_pending_outcomes failed: %s", e)

    logger.info("[ATTRIBUTION] Resolved %d pending outcomes", resolved)
    return resolved


def get_attribution_stats(db_path: str = DB_PATH) -> dict:
    """Get attribution statistics for the dashboard."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute(
                "SELECT COUNT(*) FROM attribution_trades"
            ).fetchone()[0]

            by_action = {}
            for row in conn.execute(
                "SELECT llm_action, COUNT(*) as cnt FROM attribution_trades "
                "GROUP BY llm_action"
            ).fetchall():
                by_action[row["llm_action"]] = row["cnt"]

            by_pair = {}
            for row in conn.execute(
                "SELECT pair_type, COUNT(*) as cnt FROM attribution_trades "
                "GROUP BY pair_type"
            ).fetchall():
                by_pair[row["pair_type"]] = row["cnt"]

            # Win rates by portfolio
            ranker_resolved = conn.execute(
                "SELECT COUNT(*) FROM attribution_trades "
                "WHERE ranker_only_outcome != 'pending'"
            ).fetchone()[0]
            ranker_wins = conn.execute(
                "SELECT COUNT(*) FROM attribution_trades "
                "WHERE ranker_only_outcome = 'win'"
            ).fetchone()[0]

            llm_resolved = conn.execute(
                "SELECT COUNT(*) FROM attribution_trades "
                "WHERE llm_portfolio_outcome IS NOT NULL"
            ).fetchone()[0]
            llm_wins = conn.execute(
                "SELECT COUNT(*) FROM attribution_trades "
                "WHERE llm_portfolio_outcome = 'win'"
            ).fetchone()[0]

            return {
                "total_pairs": total,
                "by_action": by_action,
                "by_pair_type": by_pair,
                "ranker_only": {
                    "resolved": ranker_resolved,
                    "wins": ranker_wins,
                    "win_rate": round(ranker_wins / ranker_resolved, 3) if ranker_resolved else None,
                },
                "llm_portfolio": {
                    "resolved": llm_resolved,
                    "wins": llm_wins,
                    "win_rate": round(llm_wins / llm_resolved, 3) if llm_resolved else None,
                },
                "statistical_power": "insufficient" if total < 50 else (
                    "low" if total < 200 else "adequate"
                ),
            }
    except Exception as e:
        logger.warning("[ATTRIBUTION] get_attribution_stats failed: %s", e)
        return {"total_pairs": 0, "error": str(e)}
