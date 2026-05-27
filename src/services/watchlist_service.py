"""Morning watchlist service.

Called by: api.routes.scan, cli.commands
Calls: data_ingestion.market_data, email.notifier, features.engine, llm.watchlist_writer, packets.watchlist, ranking.ranker, universe.company_names, universe.sp100
Owns tables: none
Config keys: none
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
        logger.critical("[WATCHLIST] email_digest unavailable — fallback: %s", err)
        try:
            from src.notifications import safe_send
            safe_send(event_type, subject=subject)
        except Exception as _safe_err:
            logger.warning("[WATCHLIST] safe_send fallback failed: %s", _safe_err)
        send_email(subject, body)


def generate_morning_watchlist(
    config: dict,
    send_email_flag: bool = False,
    via_cli: bool = False,
) -> dict:
    """Generate the morning watchlist with optional LLM narrative.

    Returns dict with: timestamp, date_str, narrative, packet_worthy, watchlist, email_body
    """
    from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark
    from src.features.engine import compute_all_features
    from src.llm.watchlist_writer import generate_watchlist_narrative
    from src.packets.watchlist import build_morning_watchlist
    from src.ranking.ranker import rank_universe, get_top_candidates
    from src.universe.sp100 import get_sp100_universe
    from src.universe.company_names import get_company_name

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
            "narrative": None,
            "packet_worthy": [],
            "watchlist": [],
            "email_body": "ERROR: Could not fetch SPY benchmark.",
        }

    features = compute_all_features(ohlcv, spy)
    ranked = rank_universe(features)
    candidates = get_top_candidates(ranked)

    packet_worthy = candidates["packet_worthy"]
    watchlist = candidates["watchlist"]

    narrative = generate_watchlist_narrative(packet_worthy, watchlist, config)
    body = build_morning_watchlist(watchlist, packet_worthy, date_str, narrative=narrative)

    subject = f"[TRADE DESK] Morning Watchlist - {date_str}"
    _route_email_or_enqueue(
        event_type="morning_watchlist", subject=subject, body=body,
        source_tag="email:preopen", via_cli=via_cli,
        send_email_flag=send_email_flag, extra_payload={"date_str": date_str},
    )

    pw_results = []
    for c in packet_worthy:
        feat = c["features"]
        pw_results.append({
            "ticker": c["ticker"],
            "company_name": get_company_name(c["ticker"]),
            "score": c["score"],
            "qualification": c["qualification"],
            "trend_state": feat.get("trend_state"),
            "relative_strength_state": feat.get("relative_strength_state"),
            "pullback_depth_pct": feat.get("pullback_depth_pct"),
            "earnings_risk": c.get("earnings_risk", False),
        })

    wl_results = []
    for w in watchlist:
        feat = w["features"]
        wl_results.append({
            "ticker": w["ticker"],
            "company_name": get_company_name(w["ticker"]),
            "score": w["score"],
            "qualification": w["qualification"],
            "trend_state": feat.get("trend_state"),
            "relative_strength_state": feat.get("relative_strength_state"),
            "pullback_depth_pct": feat.get("pullback_depth_pct"),
            "earnings_risk": False,
        })

    return {
        "timestamp": now.isoformat(),
        "date_str": date_str,
        "narrative": narrative,
        "packet_worthy": pw_results,
        "watchlist": wl_results,
        "email_body": body,
        "raw_candidates": candidates,  # For email packet generation
    }
