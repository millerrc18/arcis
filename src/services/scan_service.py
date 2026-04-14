"""Scan pipeline service.

Called by: api.routes.actions, api.routes.scan, cli.commands
Calls: data_enrichment.enricher, data_ingestion.market_data, data_integrity, email.notifier, features.engine, features.event_risk_score, features.traffic_light, journal.store, llm.packet_writer, notifications.telegram, packets.template, ranking.ranker, shadow_trading.executor, training.versioning, universe.company_names, universe.sp100
Owns tables: none
Config keys: enabled, event_risk, shadow_trading
Tests: tests/test_services.py
"""
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

    # #392: Reset per-cycle buying power tracker to prevent stale state
    from src.shadow_trading.executor import reset_scan_cycle_committed
    reset_scan_cycle_committed()

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

    # Post-scan enrichment (traffic_light + event_risk + regime_label).
    # Consolidated onto the shared helper (Phase 3.1) so universe_scanner,
    # mr_scan_service, and this path all use the same enrichment code.
    try:
        from src.features.enrichment import attach_post_scan_features
        vix_value = None
        for _t, _f in features.items():
            if "vix_proxy" in _f:
                vix_value = _f["vix_proxy"]
                break
        attach_post_scan_features(
            features, config=config, spy=spy, vix_value=vix_value,
        )
        # scan_service-specific behavior: Telegram alert for elevated market-
        # level event risk. attach_post_scan_features sets feat["market_event_risk"]
        # via attach_event_risk_scores — pull the shared market score from any feature.
        if not dry_run:
            first_feat = next(iter(features.values()), {})
            market_event_risk = first_feat.get("market_event_risk", {}) or {}
            event_risk_total = market_event_risk.get("total_score", 0)
            alert_threshold = config.get("event_risk", {}).get("alert_threshold", 6)
            if event_risk_total >= alert_threshold:
                try:
                    from src.notifications.telegram import send_telegram
                    send_telegram(
                        f"⚠️ Elevated event risk: {event_risk_total}/10 — "
                        f"{market_event_risk.get('components', {})}"
                    )
                except Exception as exc:
                    logger.warning("[SCAN] Event-risk Telegram alert failed: %s", exc)
    except Exception as e:
        logger.warning("[SCAN] Feature enrichment failed: %s — using defaults", e)
        for _t in features:
            features[_t].setdefault("traffic_light_multiplier", 1.0)
            features[_t].setdefault("event_risk_multiplier", 1.0)

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

        # Attribution Phase 1: log ranker-only snapshot before LLM
        attribution_id = None
        try:
            from src.attribution.logger import log_attribution_before_llm
            entry_price = float(feat.get("current_price", 0))
            atr = float(feat.get("atr_14", 0))
            stop_price = entry_price - 2 * atr if atr > 0 else entry_price * 0.97
            target_price = entry_price + 1.5 * atr if atr > 0 else entry_price * 1.02
            attribution_id = log_attribution_before_llm(
                ticker=ticker,
                ranker_score=candidate["score"],
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=target_price,
            )
        except Exception as e:
            logger.debug("[ATTRIBUTION] Phase 1 failed for %s: %s", ticker, e)

        packet = build_packet_from_features(ticker, feat, config)
        packet = enhance_packet_with_llm(packet, feat, config)
        enriched_prompt = _build_feature_prompt(feat, packet.ticker)
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

        # Attribution Phase 2: log LLM decision after recommendation
        if attribution_id:
            try:
                from src.attribution.logger import log_attribution_after_llm
                llm_action = "buy" if rec_id else "skip"
                log_attribution_after_llm(
                    attribution_id=attribution_id,
                    llm_action=llm_action,
                    llm_conviction=getattr(packet, 'llm_conviction', None),
                    recommendation_id=rec_id,
                )
            except Exception as e:
                logger.debug("[ATTRIBUTION] Phase 2 failed for %s: %s", ticker, e)

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
                # Telegram notification for trade open
                try:
                    from src.notifications.telegram import notify_trade_opened, is_telegram_enabled
                    if is_telegram_enabled():
                        from src.shadow_trading.executor import _parse_price
                        _entry = _parse_price(packet.entry_zone)
                        _stop = _parse_price(packet.stop_invalidation)
                        _target = _parse_price(packet.targets.split("/")[0])
                        _shares = max(1, int(packet.position_sizing.allocation_dollars / _entry)) if _entry > 0 else 1
                        notify_trade_opened(
                            ticker, _entry, _stop, _target,
                            int(candidate["score"]), _shares,
                            setup_type=feat.get("setup_type"),
                            setup_confidence=feat.get("setup_confidence"),
                        )
                except Exception as _tg_err:
                    logger.debug("[SCAN] notify_trade_opened failed for %s: %s", ticker, _tg_err)

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
