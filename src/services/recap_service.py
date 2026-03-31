"""EOD recap service.

Called by: api.routes.scan, cli.commands
Calls: data_ingestion.market_data, email.notifier, features.engine, journal.store, packets.eod_recap, ranking.ranker, universe.sp100
Owns tables: none
Config keys: shadow_trading
Tests: tests/test_services.py
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def generate_eod_recap(config: dict, send_email_flag: bool = False) -> dict:
    """Generate the end-of-day recap.

    Returns dict with: timestamp, date_str, packets_today, watchlist_count, email_body
    """
    from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark
    from src.features.engine import compute_all_features
    from src.journal.store import get_todays_recommendations
    from src.packets.eod_recap import build_eod_recap
    from src.ranking.ranker import rank_universe, get_top_candidates
    from src.universe.sp100 import get_sp100_universe

    now = datetime.now(ET)
    date_str = now.strftime("%Y-%m-%d")

    universe = get_sp100_universe()
    ohlcv = fetch_ohlcv(universe)
    spy = fetch_spy_benchmark()

    if spy.empty:
        logger.error("Could not fetch SPY benchmark. Aborting.")
        return {
            "timestamp": now.isoformat(),
            "date_str": date_str,
            "packets_today": 0,
            "watchlist_count": 0,
            "email_body": "ERROR: Could not fetch SPY benchmark.",
        }

    features = compute_all_features(ohlcv, spy)
    ranked = rank_universe(features)
    candidates = get_top_candidates(ranked)

    journal_entries = get_todays_recommendations()

    shadow_data = None
    if config.get("shadow_trading", {}).get("enabled", False):
        try:
            from src.packets.eod_recap import get_shadow_data_for_recap
            shadow_data = get_shadow_data_for_recap()
        except Exception:
            pass

    body = build_eod_recap(
        candidates["packet_worthy"], candidates["watchlist"],
        journal_entries, date_str, shadow_data=shadow_data,
    )

    if send_email_flag:
        from src.email.notifier import send_email
        subject = f"[TRADE DESK] EOD Recap - {date_str}"
        send_email(subject, body)

    return {
        "timestamp": now.isoformat(),
        "date_str": date_str,
        "packets_today": len(journal_entries),
        "watchlist_count": len(candidates["watchlist"]),
        "shadow_summary": shadow_data,
        "email_body": body,
    }
