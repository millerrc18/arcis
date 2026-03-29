"""Scan pipeline service."""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def run_scan(config: dict, dry_run: bool = False, send_email_flag: bool = False,
             run_shadow: bool = True) -> dict:
    """Execute the full scan pipeline and return structured results.

    Returns a dict with keys: timestamp, tickers_scanned, tickers_succeeded, tickers_failed,
    packet_worthy (list of dicts with ticker, score, qualification, features, packet_rendered, earnings_risk),
    watchlist (list of dicts), packets_generated, packets_emailed, shadow_trades_opened, shadow_trades_closed, model_version
    """
    from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark
    from src.features.engine import compute_all_features
    from src.journal.store import log_recommendation
    from src.llm.packet_writer import enhance_packet_with_llm, _build_feature_prompt
    from src.packets.template import build_packet_from_features, render_packet
    from src.ranking.ranker import rank_universe, get_top_candidates
    from src.training.versioning import get_active_model_name
    from src.universe.sp100 import get_sp100_universe
    from src.universe.company_names import get_company_name

    now = datetime.now(ET)
    universe = get_sp100_universe()

    ohlcv = fetch_ohlcv(universe)
    spy = fetch_spy_benchmark()

    succeeded = len(ohlcv)
    failed = len(universe) - succeeded

    if spy.empty:
        logger.error("Could not fetch SPY benchmark. Aborting scan.")
        return {
            "timestamp": now.isoformat(),
            "tickers_scanned": len(universe),
            "tickers_succeeded": succeeded,
            "tickers_failed": failed,
            "packet_worthy": [],
            "watchlist": [],
            "packets_generated": 0,
            "packets_emailed": 0,
            "shadow_trades_opened": 0,
            "shadow_trades_closed": 0,
            "model_version": get_active_model_name(),
        }

    features = compute_all_features(ohlcv, spy)

    # Enrich features with fundamental, insider, and macro data
    try:
        from src.data_enrichment.enricher import enrich_features
        features = enrich_features(features, config)
    except Exception as e:
        logger.warning("[SCAN] Data enrichment failed: %s — continuing without enrichment", e)

    # Traffic Light regime overlay
    traffic_light = {"sizing_multiplier": 1.0, "total_score": -1, "regime_label": "unknown"}
    try:
        from src.features.traffic_light import compute_traffic_light
        vix_value = None
        for _t, _f in features.items():
            if "vix_proxy" in _f:
                vix_value = _f["vix_proxy"]
                break
        traffic_light = compute_traffic_light(spy, vix=vix_value)
        for _t in features:
            features[_t]["traffic_light"] = traffic_light
            features[_t]["traffic_light_multiplier"] = traffic_light.get("sizing_multiplier", 1.0)
        logger.info("[SCAN] Traffic Light: score=%d mult=%.1f regime=%s",
                    traffic_light.get("total_score", -1),
                    traffic_light.get("sizing_multiplier", 1.0),
                    traffic_light.get("regime_label", "unknown"))
    except Exception as e:
        logger.warning("[SCAN] Traffic Light failed: %s — using default", e)
        for _t in features:
            features[_t]["traffic_light_multiplier"] = 1.0

    # Event calendar risk overlay
    event_risk_summary = {"total_score": 0, "components": {}, "sizing_multiplier": 1.0}
    try:
        from src.features.event_risk_score import attach_event_risk_scores
        event_risk_summary = attach_event_risk_scores(features, settings=config)
        logger.info(
            "[SCAN] Event risk: score=%d mult=%.2f components=%s",
            event_risk_summary.get("total_score", 0),
            event_risk_summary.get("sizing_multiplier", 1.0),
            event_risk_summary.get("components", {}),
        )
        alert_threshold = config.get("event_risk", {}).get("alert_threshold", 6)
        if event_risk_summary.get("total_score", 0) >= alert_threshold and not dry_run:
            try:
                from src.notifications.telegram import send_telegram
                send_telegram(
                    f"⚠️ Elevated event risk: {event_risk_summary['total_score']}/10 — "
                    f"{event_risk_summary.get('components', {})}"
                )
            except Exception as exc:
                logger.warning("[SCAN] Event-risk Telegram alert failed: %s", exc)
    except Exception as e:
        logger.warning("[SCAN] Event risk scoring failed: %s — using default", e)
        for _t in features:
            features[_t]["event_risk_score"] = 0
            features[_t]["event_risk_components"] = {}
            features[_t]["event_risk_multiplier"] = 1.0

    # Data integrity validation — filter out tickers with invalid features
    try:
        from src.data_integrity import validate_features, validate_universe
        validated_universe = validate_universe(list(features.keys()))
        invalid_tickers = []
        for ticker in list(features.keys()):
            if ticker not in validated_universe:
                logger.warning("[INTEGRITY] Ticker %s removed by universe validation", ticker)
                invalid_tickers.append(ticker)
            elif not validate_features(ticker, features[ticker]):
                invalid_tickers.append(ticker)
        for ticker in invalid_tickers:
            features.pop(ticker, None)
        if invalid_tickers:
            logger.warning("[INTEGRITY] Removed %d tickers with invalid data: %s",
                           len(invalid_tickers), invalid_tickers)
    except Exception as e:
        logger.warning("[INTEGRITY] Data integrity check failed: %s", e)

    ranked = rank_universe(features)
    candidates = get_top_candidates(ranked)

    packet_worthy_raw = candidates["packet_worthy"]
    watchlist_raw = candidates["watchlist"]

    shadow_cfg = config.get("shadow_trading", {})
    shadow_enabled = shadow_cfg.get("enabled", False) and run_shadow and not dry_run
    trades_opened = 0
    trades_closed = 0
    packets_emailed = 0

    packet_worthy_results = []

    for candidate in packet_worthy_raw:
        ticker = candidate["ticker"]
        feat = candidate["features"]
        feat["_score"] = candidate["score"]

        # Capture signal price for IS tracking
        feat["signal_price"] = float(feat.get("current_price", 0))

        packet = build_packet_from_features(ticker, feat, config)
        packet = enhance_packet_with_llm(packet, feat, config)
        enriched_prompt = _build_feature_prompt(packet, feat)
        rendered = render_packet(packet)

        rec_id = None
        if not dry_run:
            model_ver = get_active_model_name()
            rec_id = log_recommendation(
                packet, feat, candidate["score"], candidate["qualification"],
                model_version=model_ver,
                enriched_prompt=enriched_prompt,
                llm_conviction=getattr(packet, 'llm_conviction', None),
            )

        if send_email_flag and not dry_run:
            from src.email.notifier import send_email
            subject = f"[TRADE DESK] Action Packet - {ticker}"
            if send_email(subject, rendered):
                packets_emailed += 1

        if shadow_enabled and rec_id:
            from src.shadow_trading.executor import open_shadow_trade
            trade_id = open_shadow_trade(rec_id, packet, feat)
            if trade_id:
                trades_opened += 1

        packet_worthy_results.append({
            "ticker": ticker,
            "company_name": get_company_name(ticker),
            "score": candidate["score"],
            "qualification": candidate["qualification"],
            "trend_state": feat.get("trend_state"),
            "relative_strength_state": feat.get("relative_strength_state"),
            "pullback_depth_pct": feat.get("pullback_depth_pct"),
            "earnings_risk": candidate.get("earnings_risk", False),
            "rendered_text": rendered,
            "features": feat,
        })

        alert_threshold = config.get("event_risk", {}).get("alert_threshold", 6)
        if feat.get("event_risk_score", 0) >= alert_threshold and not dry_run:
            try:
                from src.notifications.telegram import send_telegram
                send_telegram(
                    f"⚠️ Elevated event risk: {feat['event_risk_score']}/10 — "
                    f"{feat.get('event_risk_components', {})}"
                )
            except Exception as exc:
                logger.warning("[SCAN] Ticker event-risk Telegram alert failed for %s: %s", ticker, exc)

    if shadow_enabled:
        from src.shadow_trading.executor import check_and_manage_open_trades
        actions = check_and_manage_open_trades()
        trades_closed = len([a for a in actions if a["type"] == "closed"])

    watchlist_results = []
    for w in watchlist_raw:
        feat = w["features"]
        watchlist_results.append({
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
        "tickers_scanned": len(universe),
        "tickers_succeeded": succeeded,
        "tickers_failed": failed,
        "packet_worthy": packet_worthy_results,
        "watchlist": watchlist_results,
        "packets_generated": len(packet_worthy_results),
        "packets_emailed": packets_emailed,
        "shadow_trades_opened": trades_opened,
        "shadow_trades_closed": trades_closed,
        "model_version": get_active_model_name(),
        "ranked": ranked,  # Include full ranked list for verbose output
    }
