"""Review and evaluation service.

Called by: api.routes.review, cli.commands
Calls: evaluation.scorecard, journal.store
Owns tables: none
Config keys: none
Tests: tests/test_services.py
"""
import logging

logger = logging.getLogger(__name__)


def get_pending_reviews() -> list[dict]:
    """Get recommendations pending Ryan's review."""
    from src.journal.store import get_recommendations_pending_review
    return get_recommendations_pending_review()


def get_recommendation(recommendation_id: str) -> dict | None:
    """Get a single recommendation with all detail."""
    from src.journal.store import get_recommendation_by_id
    return get_recommendation_by_id(recommendation_id)


def submit_review(recommendation_id: str, review_data: dict) -> bool:
    """Submit a review for a recommendation."""
    from src.journal.store import update_recommendation_review
    try:
        update_recommendation_review(recommendation_id, review_data)
        return True
    except Exception as e:
        logger.error("Failed to submit review: %s", e)
        return False


def mark_executed(ticker: str) -> bool:
    """Mark the most recent recommendation for a ticker as executed."""
    from src.journal.store import get_recommendations_by_ticker, update_recommendation
    recs = get_recommendations_by_ticker(ticker.upper(), limit=1)
    if not recs:
        return False
    update_recommendation(recs[0]["recommendation_id"], {"ryan_executed": 1})
    return True


def get_scorecard(weeks: int = 1) -> str:
    """Generate a weekly scorecard."""
    from src.evaluation.scorecard import generate_weekly_scorecard
    return generate_weekly_scorecard(weeks_back=weeks)


def get_bootcamp_report(days: int = 30) -> str:
    """Generate a bootcamp report."""
    from src.evaluation.scorecard import generate_bootcamp_scorecard
    return generate_bootcamp_scorecard(days=days)


def get_postmortems(limit: int = 10, ticker: str | None = None) -> list[dict]:
    """Get recent postmortems."""
    from src.journal.store import get_closed_shadow_trades, get_recommendation_by_id

    closed = get_closed_shadow_trades(days=90)
    if ticker:
        closed = [t for t in closed if t["ticker"] == ticker.upper()]
    closed = closed[:limit]

    results = []
    for t in closed:
        rec_id = t.get("recommendation_id")
        rec = get_recommendation_by_id(rec_id) if rec_id else None
        results.append({
            "ticker": t["ticker"],
            "date": (t.get("actual_exit_time") or t.get("created_at", ""))[:10],
            "exit_reason": t.get("exit_reason", "unknown"),
            "pnl_dollars": t.get("pnl_dollars", 0) or 0,
            "lesson_tag": (rec.get("lesson_tag") or "n/a") if rec else "n/a",
            "postmortem": (rec.get("assistant_postmortem") or "n/a") if rec else "n/a",
            "recommendation_id": rec_id,
        })
    return results


def get_postmortem_detail(recommendation_id: str) -> dict | None:
    """Get full postmortem for a recommendation."""
    from src.journal.store import get_recommendation_by_id
    return get_recommendation_by_id(recommendation_id)
