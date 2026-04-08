"""Universe scanner — Tier 2 (30-min) full universe scan pipeline.

Extracted from watch.py._run_scan() to separate scan logic from
watch loop state management. The scan pipeline is stateless: it
receives config, performs the full scan, and returns results. All
state mutations (email dispatch, Telegram notifications, scan metrics)
are handled by the caller (watch.py).

Called by: scheduler.watch.WatchLoop._run_scan()
Calls: data_ingestion, features, ranking, llm, packets, attribution, shadow_trading
Owns tables: none (writes to recommendations, shadow_trades, attribution_trades via called modules)
Config keys: bootcamp.*, shadow_trading.*, live_trading.*
Tests: tests/test_universe_scanner.py
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


@dataclass
class ScanContext:
    """Input context for a universe scan."""
    config: dict
    db_path: str = DB_PATH
    scan_id: str | None = None


@dataclass
class ScanResult:
    """Output from a universe scan cycle."""
    universe_count: int = 0
    features_count: int = 0
    packet_worthy_count: int = 0
    watchlist_count: int = 0
    trades_opened: int = 0
    trades_closed: int = 0
    packets_rendered: list = field(default_factory=list)
    trade_actions: list = field(default_factory=list)
    candidates: dict = field(default_factory=dict)
    packet_worthy: list = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""
    conviction_parsed: int = 0  # #329: count of tickers with non-default conviction
    conviction_total: int = 0   # #329: total tickers that went through LLM


def run_universe_scan(ctx: ScanContext) -> ScanResult:
    """Tier 2: Full universe scan pipeline (30-min cadence).

    Performs: universe fetch -> features -> enrichment -> traffic light ->
    ranking -> packet building -> LLM enhancement -> attribution logging ->
    shadow/live trade execution -> trade management.

    Returns a ScanResult with all outputs. The caller handles email
    dispatch, Telegram notifications, and scan metrics recording.
    """
    from src.api.websocket import broadcast_sync
    from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark
    from src.features.engine import compute_all_features
    from src.journal.store import log_recommendation
    from src.llm.packet_writer import enhance_packet_with_llm, _build_feature_prompt
    from src.packets.template import build_packet_from_features, render_packet
    from src.training.versioning import get_active_model_name
    from src.ranking.ranker import rank_universe, get_top_candidates
    from src.universe.sp100 import get_sp100_universe

    result = ScanResult()

    print("[SCAN] Running market scan...")
    try:
        broadcast_sync("scan_started", {"time": datetime.now(ET).isoformat()})
    except Exception as e:
        logger.warning("[SCAN] broadcast scan_started failed: %s", e)

    # ── Phase 1: Universe fetch + feature computation ────────────────
    universe = get_sp100_universe()
    ohlcv = fetch_ohlcv(universe)
    spy = fetch_spy_benchmark()
    result.universe_count = len(universe)

    if spy.empty:
        print("[SCAN] ERROR: Could not fetch SPY benchmark. Skipping scan.")
        result.aborted = True
        result.abort_reason = "no_spy_data"
        return result

    features = compute_all_features(ohlcv, spy)
    result.features_count = len(features)

    # Enrich features with fundamental, insider, and macro data
    try:
        from src.data_enrichment.enricher import enrich_features
        features = enrich_features(features, ctx.config)
    except Exception as e:
        logger.warning("[SCAN] Data enrichment failed: %s", e)

    # ── Phase 2: Traffic light ───────────────────────────────────────
    try:
        from src.features.traffic_light import compute_traffic_light
        import sqlite3 as _sq
        _vix_val = None
        try:
            with _sq.connect(ctx.db_path) as _vc:
                _vr = _vc.execute(
                    "SELECT vix FROM vix_term_structure ORDER BY collected_date DESC LIMIT 1"
                ).fetchone()
                if _vr:
                    _vix_val = float(_vr[0])
        except Exception:
            pass
        tl = compute_traffic_light(spy, vix=_vix_val)
        for _t in features:
            features[_t]["traffic_light"] = tl
            features[_t]["traffic_light_multiplier"] = tl.get("sizing_multiplier", 1.0)
        logger.info("[SCAN] Traffic Light: score=%d mult=%.1f regime=%s vix=%.1f",
                    tl.get("total_score", -1), tl.get("sizing_multiplier", 1.0),
                    tl.get("regime_label", "unknown"), _vix_val or 0.0)
    except Exception as e:
        logger.warning("[SCAN] Traffic Light failed: %s — using default", e)
        for _t in features:
            features[_t]["traffic_light_multiplier"] = 1.0

    # ── Phase 3: Ranking + candidate selection ───────────────────────
    ranked = rank_universe(features)
    candidates = get_top_candidates(ranked)
    packet_worthy = candidates["packet_worthy"]
    result.candidates = candidates
    result.watchlist_count = len(candidates.get("watchlist", []))

    # Cap packets per scan
    bootcamp_cfg = ctx.config.get("bootcamp", {})
    max_packets = bootcamp_cfg.get("max_packets_per_scan", 8)
    if len(packet_worthy) > max_packets:
        overflow = packet_worthy[max_packets:]
        packet_worthy = packet_worthy[:max_packets]
        print(f"[SCAN] Capped at {max_packets} packets "
              f"({len(overflow)} deferred to next scan)")

    if not packet_worthy:
        print(f"[SCAN] No packet-worthy setups. {result.watchlist_count} on watchlist.")
        try:
            broadcast_sync("scan_complete", {"tickers_scanned": len(universe), "packets": 0})
        except Exception as e:
            logger.warning("[SCAN] broadcast scan_complete (empty) failed: %s", e)
        return result

    result.packet_worthy_count = len(packet_worthy)
    result.packet_worthy = packet_worthy
    print(f"[SCAN] Found {len(packet_worthy)} packet-worthy names.")

    # ── Phase 4: Per-packet pipeline (LLM + attribution + trades) ────
    for candidate in packet_worthy:
        ticker = candidate["ticker"]
        feat = candidate["features"]
        feat["_score"] = candidate["score"]

        packet = build_packet_from_features(ticker, feat, ctx.config)

        # Attribution Phase 1: BEFORE LLM
        attr_id = None
        try:
            from src.attribution.logger import log_attribution_before_llm
            from src.shadow_trading.executor import _parse_price
            _entry = _parse_price(packet.entry_zone)
            _stop = _parse_price(packet.stop_invalidation)
            _tgt = _parse_price(packet.targets.split("/")[0]) if packet.targets else 0
            attr_id = log_attribution_before_llm(
                ticker, candidate["score"], _entry, _stop, _tgt)
        except Exception as e:
            logger.debug("[SCAN] Attribution Phase 1 failed for %s: %s", ticker, e)

        packet = enhance_packet_with_llm(packet, feat, ctx.config)
        # #329: Track conviction parse rate (5 = default when parsing fails)
        result.conviction_total += 1
        if getattr(packet, 'llm_conviction', 5) != 5:
            result.conviction_parsed += 1
        enriched_prompt = _build_feature_prompt(packet, feat)
        rendered = render_packet(packet)

        model_ver = get_active_model_name()
        rec_id = log_recommendation(
            packet, feat, candidate["score"], candidate["qualification"],
            model_version=model_ver,
            enriched_prompt=enriched_prompt,
            llm_conviction=getattr(packet, 'llm_conviction', None),
        )

        # Attribution Phase 2: AFTER LLM
        if attr_id:
            try:
                from src.attribution.logger import log_attribution_after_llm
                conviction = getattr(packet, 'llm_conviction', None)
                action = "taken" if conviction is not None else "conviction_none"
                log_attribution_after_llm(attr_id, action, conviction, rec_id)
            except Exception as e:
                logger.debug("[SCAN] Attribution Phase 2 failed: %s", e)
        print(f"  -> Logged {ticker}: {rec_id}")

        # Shadow trade execution
        trade_id = None
        try:
            from src.shadow_trading.executor import open_shadow_trade
            trade_id = open_shadow_trade(rec_id, packet, feat)
            if trade_id:
                print(f"  -> Shadow trade opened: {trade_id}")
                result.trades_opened += 1
            else:
                print(f"  -> Shadow trade skipped (risk governor or position limit)")
        except Exception as e:
            logger.warning("[SCAN] Shadow trade failed for %s: %s", ticker, e)

        # Attribution: log rejected trades
        if attr_id and not trade_id:
            try:
                from src.attribution.logger import log_attribution_after_llm
                log_attribution_after_llm(attr_id, "rejected")
            except Exception:
                pass

        if trade_id:
            # Live trade execution (dual execution if enabled)
            live_cfg = ctx.config.get("live_trading", {})
            now_live = datetime.now(ET)
            hour_live = now_live.hour
            if (live_cfg.get("enabled", False)
                    and getattr(packet, 'llm_conviction', None) is not None
                    and not (hour_live == 9 and now_live.minute < 31)):
                try:
                    from src.shadow_trading.executor import open_live_trade
                    live_id = open_live_trade(rec_id, packet, feat)
                    if live_id:
                        print(f"  -> LIVE trade opened: {live_id}")
                except Exception as e:
                    logger.warning("[SCAN] Live trade failed for %s: %s", ticker, e)

            try:
                broadcast_sync("trade_opened", {"ticker": ticker, "side": "BUY",
                                                "score": candidate["score"]})
            except Exception as e:
                logger.warning("[SCAN] broadcast trade_opened failed: %s", e)

            # Telegram trade notification
            try:
                from src.notifications.telegram import notify_trade_opened, is_telegram_enabled
                if is_telegram_enabled():
                    from src.notifications.telegram import send_telegram
                    from src.shadow_trading.executor import _parse_price

                    entry_price = _parse_price(packet.entry_zone)
                    stop_price = _parse_price(packet.stop_invalidation)
                    target_price = _parse_price(packet.targets.split("/")[0])
                    shares = (
                        max(1, int(packet.position_sizing.allocation_dollars / entry_price))
                        if entry_price > 0
                        else 1
                    )
                    try:
                        notify_trade_opened(
                            ticker, entry_price, stop_price, target_price,
                            int(candidate["score"]), shares,
                            setup_type=feat.get("setup_type"),
                            setup_confidence=feat.get("setup_confidence"),
                        )
                    except Exception:
                        send_telegram(
                            f"\U0001f7e2 <b>TRADE OPENED: {ticker}</b>\n"
                            f"Score: {int(candidate['score'])}/100 | Shares: {shares}"
                        )
            except Exception as e:
                logger.warning("[SCAN] notify_trade_opened failed: %s", e)

            # Store rendered packet for email dispatch by caller
            result.packets_rendered.append({
                "ticker": ticker,
                "rendered": rendered,
                "score": candidate["score"],
            })

    # ── Phase 5: Manage existing open trades ─────────────────────────
    try:
        from src.shadow_trading.executor import check_and_manage_open_trades
        actions = check_and_manage_open_trades()
        result.trade_actions = actions
        result.trades_closed = len([a for a in actions if a.get("type") == "closed"])
        for action in actions:
            action_type = action.get("type", action.get("action", "unknown"))
            print(f"  -> Trade action: {action.get('ticker', '?')} -- {action_type} "
                  f"(P&L: ${action.get('pnl_dollars', 0):+.2f})")
    except Exception as e:
        logger.warning("[SCAN] Trade management failed: %s", e)

    # Independent live trade check
    try:
        from src.shadow_trading.executor import check_and_manage_open_trades as _check_live
        _live_actions = _check_live(source_filter="live")
        _live_closed = len([a for a in _live_actions if a.get("type") == "closed"])
        if _live_closed:
            logger.info("[SCAN] Live trade check: %d trades closed", _live_closed)
    except Exception as e:
        logger.warning("[SCAN] Independent live trade check failed: %s", e)

    # Summary line
    print(f"[SCAN] {datetime.now(ET).strftime('%H:%M')} ET -- Scan complete: "
          f"{result.universe_count} tickers -> {result.features_count} scored -> "
          f"{result.packet_worthy_count} packets -> {result.trades_opened} trades")

    try:
        broadcast_sync("scan_complete", {"tickers_scanned": result.universe_count,
                                         "packets": result.packet_worthy_count})
    except Exception as e:
        logger.warning("[SCAN] broadcast scan_complete failed: %s", e)

    return result
