"""Scan pipeline phase helpers (collect / score / persist).

Called by: services.scan_service.run_scan
Calls: data_enrichment.enricher, data_ingestion.market_data, data_integrity, features.engine, features.enrichment, journal.store, llm.packet_writer, packets.template, ranking.ranker, risk.governor, shadow_trading.executor, training.versioning, universe.company_names, universe.sectors, universe.sp100
Owns tables: none
Config keys: enabled, event_risk, risk, shadow_trading
Tests: tests/test_services.py, tests/services/test_scan_service_email_routing.py, tests/services/test_via_cli_propagation.py

Phase 5 PR-C T15 extraction (KC-12 / DA9): the ~401-line inner body of
``run_scan`` is decomposed into three coherent phases that live in this
underscore-private sibling module:

  - ``_phase_collect``: build the universe, fetch OHLCV + the SPY benchmark,
    compute + enrich features, run the data-integrity filter, and rank the
    universe into packet-worthy / watchlist candidates.
  - ``_phase_score``: iterate the packet-worthy candidates — pre-LLM filters,
    attribution, packet build, LLM enhancement, recommendation persistence,
    shadow-trade open, and per-candidate email + Telegram side effects.
  - ``_phase_persist``: manage open trades (close milestones), assemble the
    watchlist rows, and build the final structured result dict.

``run_scan`` (in scan_service.py) calls the three phases in order. The
email-routing helper (``_route_packet_email``), the regime forensic logger
(``_log_regime_capture_failure``), the attribution-hook resolver
(``_resolve_attribution_hooks``), and the trade-opened Telegram emitter
(``_emit_trade_opened_telegram``) remain in scan_service.py — the scoring
phase imports them function-locally to avoid a circular import at module load.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from src.notifications.telegram import send_telegram

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

if TYPE_CHECKING:
    from src.platform.strategy_spec import StrategySpec


def _phase_collect(
    config: dict,
    dry_run: bool,
    strategy: "StrategySpec" | None,
) -> dict:
    """Phase 1 — gather the universe, features, and ranked candidates.

    Returns a dict with keys: now, universe, succeeded, failed, abort
    (True when the SPY benchmark is empty), features, ranked, candidates.
    When ``abort`` is True the caller short-circuits with an empty result.
    """
    from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark
    from src.features.engine import compute_all_features
    from src.ranking.ranker import rank_universe, get_top_candidates
    from src.universe.sp100 import get_sp100_universe

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
            "now": now,
            "universe": universe,
            "succeeded": succeeded,
            "failed": failed,
            "abort": True,
            "features": {},
            "ranked": [],
            "candidates": {"packet_worthy": [], "watchlist": []},
        }

    if strategy is None:
        features = compute_all_features(ohlcv, spy)
    else:
        features = compute_all_features(ohlcv, spy, strategy=strategy)

    # Enrich features with fundamental, insider, and macro data
    try:
        from src.data_enrichment.enricher import enrich_features
        if strategy is None:
            features = enrich_features(features, config)
        else:
            features = enrich_features(features, config, strategy=strategy)
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
        if strategy is None:
            attach_post_scan_features(
                features, config=config, spy=spy, vix_value=vix_value,
            )
        else:
            attach_post_scan_features(
                features, config=config, strategy=strategy, spy=spy, vix_value=vix_value,
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

    if strategy is None:
        ranked = rank_universe(features)
    else:
        ranked = rank_universe(features, strategy=strategy)
    candidates = get_top_candidates(ranked)

    return {
        "now": now,
        "universe": universe,
        "succeeded": succeeded,
        "failed": failed,
        "abort": False,
        "features": features,
        "ranked": ranked,
        "candidates": candidates,
    }


def _phase_score(
    config: dict,
    dry_run: bool,
    send_email_flag: bool,
    run_shadow: bool,
    strategy: "StrategySpec" | None,
    via_cli: bool,
    candidates: dict,
) -> dict:
    """Phase 2 — score the packet-worthy candidates.

    Iterates ``candidates["packet_worthy"]`` applying the pre-LLM filters,
    attribution logging, packet build + LLM enhancement, recommendation
    persistence, shadow-trade open, and the per-candidate email + Telegram
    side effects. Returns a dict with keys: packet_worthy_results,
    packets_emailed, trades_opened.
    """
    from src.llm.packet_writer import enhance_packet_with_llm, _build_feature_prompt
    from src.packets.template import build_packet_from_features, render_packet
    from src.universe.company_names import get_company_name
    from src.services.scan_service import (
        _emit_trade_opened_telegram,
        _persist_recommendation,
        _resolve_attribution_hooks,
        _route_packet_email,
    )

    packet_worthy_raw = candidates["packet_worthy"]
    log_before_llm, log_after_llm = _resolve_attribution_hooks(strategy)

    shadow_cfg = config.get("shadow_trading", {})
    shadow_enabled = shadow_cfg.get("enabled", False) and run_shadow and not dry_run
    trades_opened = 0
    packets_emailed = 0

    # #627 — Pre-LLM portfolio snapshot for sector concentration pre-filter.
    # Fetched once before the loop so we don't call get_portfolio_state() per-candidate.
    # Tests can inject via config["_pre_llm_portfolio_snapshot"] to avoid Alpaca calls.
    _pre_llm_portfolio = config.get("_pre_llm_portfolio_snapshot")
    if _pre_llm_portfolio is None:
        try:
            from src.risk.governor import get_portfolio_state
            _pre_llm_portfolio = get_portfolio_state()
        except Exception as _pf_err:
            logger.debug("[SCAN] Pre-LLM portfolio snapshot unavailable: %s", _pf_err)
            _pre_llm_portfolio = {}
    _pre_llm_sector_exposure = (_pre_llm_portfolio or {}).get("sector_exposure", {})
    _pre_llm_equity = (_pre_llm_portfolio or {}).get("equity", 0)
    _risk_cfg = config.get("risk", {})
    _sector_cap = float(_risk_cfg.get("max_sector_pct", 0.30))
    _pre_llm_filtered_sector = 0
    _pre_llm_filtered_event = 0

    packet_worthy_results = []

    for candidate in packet_worthy_raw:
        ticker = candidate["ticker"]
        feat = candidate["features"]
        feat["_score"] = candidate["score"]

        # Capture signal price for IS tracking
        feat["signal_price"] = float(feat.get("current_price", 0))

        # #627 — Pre-LLM filter: event risk hard block (multiplier=0 means earnings imminent).
        # The governor will reject this anyway; skip the ~17s LLM call.
        _event_mult = feat.get("event_risk_multiplier", 1.0)
        if _event_mult is not None and float(_event_mult) <= 0:
            logger.info(
                "[SCAN] Pre-LLM filter: %s skipped — event risk hard block "
                "(event_risk_multiplier=%.2f)", ticker, float(_event_mult),
            )
            _pre_llm_filtered_event += 1
            continue

        # #627 — Pre-LLM filter: sector concentration check.
        # If the sector is already at or above the cap, the governor will reject this trade.
        # Avoid the LLM call for a trade we know will be blocked.
        if _pre_llm_equity > 0:
            from src.universe.sectors import SECTOR_MAP
            _ticker_sector = feat.get("sector") or feat.get("realized_sector") or SECTOR_MAP.get(ticker, "Unknown")
            _current_sector_pct = _pre_llm_sector_exposure.get(_ticker_sector, 0)
            if _current_sector_pct >= _sector_cap:
                logger.info(
                    "[SCAN] Pre-LLM filter: %s skipped — %s sector already at %.0f%% "
                    "(cap %.0f%%)", ticker, _ticker_sector,
                    _current_sector_pct * 100, _sector_cap * 100,
                )
                _pre_llm_filtered_sector += 1
                continue


        # Attribution Phase 1: log ranker-only snapshot before LLM
        attribution_id = None
        if log_before_llm:
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

        # T1.06: scan_service drives the pullback desk. When no StrategySpec
        # is provided, pass strategy_name="pullback" so template.py reads
        # strategies.pullback.stop_atr_* instead of the hardcoded 2.0x
        # fallback. When a spec IS provided, its own mechanical bracket
        # config (exit.stop.atr_multiple) overrides via
        # _resolve_strategy_brackets — the strategy_name fallback is unused.
        # Audit F-6b.
        if strategy is None:
            packet = build_packet_from_features(
                ticker, feat, config, strategy_name="pullback"
            )
        else:
            packet = build_packet_from_features(ticker, feat, config, strategy=strategy)

        # #621 / task #52: build_packet_from_features returns None for tickers
        # with current_price <= 0 (silent feature-fetch failure). Skip the ticker
        # rather than crash the pullback scan via NoneType in enhance_packet_with_llm.
        if packet is None:
            logger.warning("[SCAN] Skipping %s — build_packet_from_features returned None (current_price invalid)", ticker)
            continue

        # Sprint 2 K: pre-LLM BP check. Skip Ollama for un-fundable packets.
        # Defensive on packets that lack position_sizing (test mocks).
        _ps = getattr(packet, "position_sizing", None)
        _alloc = getattr(_ps, "allocation_dollars", None) if _ps else None
        if isinstance(_alloc, (int, float)) and _alloc > 0:
            from src.shadow_trading.executor import (
                _check_paper_buying_power_allocation,
                _record_bp_rejection_pre_llm,
            )
            if not _check_paper_buying_power_allocation(_alloc):
                logger.info(
                    "[SCAN] BP pre-check rejected %s: $%.2f exceeds effective BP",
                    ticker, _alloc,
                )
                _record_bp_rejection_pre_llm(packet)
                continue

        packet = enhance_packet_with_llm(packet, feat, config)
        enriched_prompt = _build_feature_prompt(feat, packet.ticker)
        rendered = render_packet(packet)

        rec_id = None
        if not dry_run:
            rec_id = _persist_recommendation(packet, feat, candidate, enriched_prompt)

        # Attribution Phase 2: log LLM decision after recommendation.
        #
        # #846 fix: previously wrote non-canonical "buy"/"skip" labels which
        # were silently excluded from the §4 selection-alpha t-test in the
        # attribution_readout audit. Mirror universe_scanner.py:248-253
        # semantics:
        #   - rec_id + conviction present → "taken"
        #   - rec_id + no conviction      → "conviction_none"
        #   - no rec_id (dry_run path)    → "rejected"
        if attribution_id and log_after_llm:
            try:
                from src.attribution.logger import log_attribution_after_llm
                conviction = getattr(packet, 'llm_conviction', None)
                if rec_id and conviction is not None:
                    llm_action = "taken"
                elif rec_id and conviction is None:
                    llm_action = "conviction_none"
                else:
                    llm_action = "rejected"
                log_attribution_after_llm(
                    attribution_id=attribution_id,
                    llm_action=llm_action,
                    llm_conviction=conviction,
                    recommendation_id=rec_id,
                    parse_failed=getattr(packet, 'llm_conviction_parse_failed', False),
                )
            except Exception as e:
                logger.debug("[ATTRIBUTION] Phase 2 failed for %s: %s", ticker, e)

        if not dry_run:
            subject = f"[TRADE DESK] Action Packet - {ticker}"
            if _route_packet_email(
                ticker=ticker, subject=subject, rendered=rendered,
                via_cli=via_cli, send_email_flag=send_email_flag,
            ):
                packets_emailed += 1

        if shadow_enabled and rec_id:
            from src.shadow_trading.executor import open_shadow_trade
            trade_id = open_shadow_trade(rec_id, packet, feat)
            if trade_id:
                trades_opened += 1
                _emit_trade_opened_telegram(ticker, feat, candidate, packet)

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
                send_telegram(
                    f"⚠️ Elevated event risk: {feat['event_risk_score']}/10 — "
                    f"{feat.get('event_risk_components', {})}"
                )
            except Exception as exc:
                logger.warning("[SCAN] Ticker event-risk Telegram alert failed for %s: %s", ticker, exc)

    # #627 — Log pre-LLM filter summary
    if _pre_llm_filtered_sector > 0 or _pre_llm_filtered_event > 0:
        logger.info(
            "[SCAN] Pre-LLM filter saved %d LLM calls: sector=%d, event_risk=%d",
            _pre_llm_filtered_sector + _pre_llm_filtered_event,
            _pre_llm_filtered_sector,
            _pre_llm_filtered_event,
        )

    return {
        "packet_worthy_results": packet_worthy_results,
        "packets_emailed": packets_emailed,
        "trades_opened": trades_opened,
    }


def _phase_persist(
    config: dict,
    dry_run: bool,
    run_shadow: bool,
    candidates: dict,
    score_result: dict,
    scan_meta: dict,
    ranked: list,
) -> dict:
    """Phase 3 — manage open trades and assemble the result dict.

    Runs the open-trade close-milestone management, builds the watchlist
    result rows, and assembles the final structured ``run_scan`` return dict
    from ``scan_meta`` (now/universe/succeeded/failed) + ``score_result``.
    """
    from src.training.versioning import get_active_model_name
    from src.universe.company_names import get_company_name

    shadow_cfg = config.get("shadow_trading", {})
    shadow_enabled = shadow_cfg.get("enabled", False) and run_shadow and not dry_run
    trades_closed = 0

    if shadow_enabled:
        from src.shadow_trading.executor import check_and_manage_open_trades
        actions = check_and_manage_open_trades()
        trades_closed = len([a for a in actions if a["type"] == "closed"])

    watchlist_results = []
    for w in candidates["watchlist"]:
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

    packet_worthy_results = score_result["packet_worthy_results"]
    return {
        "timestamp": scan_meta["now"].isoformat(),
        "tickers_scanned": len(scan_meta["universe"]),
        "tickers_succeeded": scan_meta["succeeded"],
        "tickers_failed": scan_meta["failed"],
        "packet_worthy": packet_worthy_results,
        "watchlist": watchlist_results,
        "packets_generated": len(packet_worthy_results),
        "packets_emailed": score_result["packets_emailed"],
        "shadow_trades_opened": score_result["trades_opened"],
        "shadow_trades_closed": trades_closed,
        "model_version": get_active_model_name(),
        "ranked": ranked,  # Include full ranked list for verbose output
    }
