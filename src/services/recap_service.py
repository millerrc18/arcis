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


def _route_email_or_enqueue(
    *, event_type: str, subject: str, body: str, source_tag: str,
    via_cli: bool, send_email_flag: bool, extra_payload: dict | None = None,
) -> None:
    """DD-13/DD-25/DD-30: route email to direct-send OR digest enqueue."""
    from src.email.notifier import send_email
    if send_email_flag or via_cli:
        send_email(subject, body)
        return
    payload = {"rendered": body, "subject": subject, **(extra_payload or {})}
    try:
        from src.notifications.email_digest import enqueue_for_email_digest
        enqueue_for_email_digest(
            event_type, severity="normal", payload=payload, source_tag=source_tag,
        )
    except (ImportError, ModuleNotFoundError) as err:
        logger.critical("[RECAP] email_digest unavailable — fallback: %s", err)
        try:
            from src.notifications import safe_send
            safe_send("eod_recap_email", subject=subject)
        except Exception as _safe_err:
            logger.warning("[RECAP] safe_send fallback failed: %s", _safe_err)
        send_email(subject, body)


def _fetch_shadow_data_for_recap(config: dict):
    """Fetch shadow_data for the recap; returns None on failure or when disabled.

    Routes broker exceptions through ``log_and_persist`` so they appear in the
    BrokerExceptionsPanel dashboard (PR #690 O1). Caller proceeds with
    shadow_data=None (recap still rendered).
    """
    if not config.get("shadow_trading", {}).get("enabled", False):
        return None
    try:
        from src.packets.eod_recap import get_shadow_data_for_recap
        return get_shadow_data_for_recap()
    except Exception as _recap_err:
        from src.shadow_trading.broker_exception_logger import log_and_persist
        log_and_persist(
            ticker="(all)",
            operation="fetch_shadow_data",
            broker="n/a",
            exc=_recap_err,
            recoverable=True,
        )
        return None


def generate_eod_recap(
    config: dict,
    send_email_flag: bool = False,
    via_cli: bool = False,
) -> dict:
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
    shadow_data = _fetch_shadow_data_for_recap(config)

    body = build_eod_recap(
        candidates["packet_worthy"], candidates["watchlist"],
        journal_entries, date_str, shadow_data=shadow_data,
    )

    subject = f"[TRADE DESK] EOD Recap - {date_str}"
    _route_email_or_enqueue(
        event_type="eod_recap_email", subject=subject, body=body,
        source_tag="email:postclose", via_cli=via_cli,
        send_email_flag=send_email_flag, extra_payload={"date_str": date_str},
    )

    return {
        "timestamp": now.isoformat(),
        "date_str": date_str,
        "packets_today": len(journal_entries),
        "watchlist_count": len(candidates["watchlist"]),
        "shadow_summary": shadow_data,
        "email_body": body,
    }
