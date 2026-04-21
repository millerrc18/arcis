"""Mean reversion scan service — dedicated MR candidate scanning and trade opening.

Called by: scheduler.watch (via _run_mr_scan)
Calls: features.mean_reversion, llm.packet_writer, shadow_trading.executor,
       journal.recommendation_logger
Owns tables: none (delegates to executor and recommendation logger)

Runs after the main pullback scan. Uses Connors-style RSI(2) mean reversion
criteria (separate from the setup_classifier's MR tagging).
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import load_config

logger = logging.getLogger(__name__)


def run_mr_scan(config: dict | None = None, dry_run: bool = False) -> dict:
    """Scan universe for mean reversion candidates and open shadow trades.

    Returns a summary dict with scan results.
    """
    # #392 (Sprint 2 L): Reset per-cycle BP counter on every scan entry.
    # MR scan shares the module-level _scan_cycle_committed with the main
    # universe scan; resetting here prevents committed from persisting
    # across the interval between scans when only one path runs per cycle.
    from src.shadow_trading.executor import reset_scan_cycle_committed
    reset_scan_cycle_committed()

    config = config or load_config()
    mr_cfg = config.get("strategies", {}).get("mean_reversion", {})

    if not mr_cfg.get("enabled", False):
        logger.debug("[MR] Mean reversion strategy disabled in config")
        return {"status": "disabled", "candidates": 0, "trades_opened": 0}

    shadow_cfg = config.get("shadow_trading", {})
    shadow_enabled = shadow_cfg.get("enabled", False)
    paper_only = mr_cfg.get("paper_only", True)

    et = ZoneInfo("America/New_York")
    timestamp = datetime.now(et).isoformat()

    # Fetch OHLCV for universe
    from src.data_ingestion.market_data import fetch_ohlcv
    from src.universe.sp100 import get_sp100_universe

    universe = get_sp100_universe()
    ohlcv_dict = fetch_ohlcv(universe, period="1y")

    # Scan for MR candidates
    from src.features.mean_reversion import scan_for_mr_candidates

    candidates = scan_for_mr_candidates(ohlcv_dict, config)

    if not candidates:
        logger.info("[MR] No mean reversion candidates found")
        return {"status": "no_candidates", "candidates": 0, "trades_opened": 0,
                "timestamp": timestamp}

    logger.info("[MR] Found %d mean reversion candidates", len(candidates))

    # Post-scan enrichment: attach traffic_light_multiplier, event_risk_multiplier,
    # and top-level regime_label to every candidate's feature dict. Before this,
    # MR candidates fell back to defaults (0.5 traffic_light → zero-allocation
    # rejection; NULL market_regime in recommendations). 2026-04-14 regression guard.
    if not dry_run:
        try:
            from src.features.enrichment import attach_post_scan_features
            features_map = {c["ticker"]: c.get("features", c) for c in candidates}
            spy_df = ohlcv_dict.get("SPY") if isinstance(ohlcv_dict, dict) else None
            vix_val = None
            try:
                import sqlite3
                _db = config.get("db_path", "data/ai_research_desk.sqlite3")
                with sqlite3.connect(_db) as vc:
                    r = vc.execute(
                        "SELECT vix FROM vix_term_structure "
                        "ORDER BY collected_date DESC LIMIT 1"
                    ).fetchone()
                    if r:
                        vix_val = float(r[0])
            except Exception:
                pass
            attach_post_scan_features(
                features_map, config=config, spy=spy_df, vix_value=vix_val,
            )
        except Exception as e:
            logger.warning("[MR] Post-scan enrichment failed: %s", e)

    trades_opened = 0
    results = []

    for candidate in candidates:
        ticker = candidate["ticker"]
        feat = candidate.get("features", candidate)

        # Tag as MR strategy for executor routing
        feat["strategy_type"] = "mean_reversion"
        feat["_score"] = candidate.get("score", feat.get("rsi_2", 50))
        feat["signal_price"] = float(feat.get("current_price", 0))

        if dry_run:
            results.append({"ticker": ticker, "rsi_2": feat.get("rsi_2"),
                            "action": "dry_run"})
            continue

        # Build packet and enhance with MR-specific LLM prompt
        from src.llm.prompts import get_system_prompt
        from src.packets.template import build_packet_from_features
        from src.llm.packet_writer import enhance_packet_with_llm

        packet = build_packet_from_features(ticker, feat, config)

        # Sprint 2 K: pre-LLM BP check. Skip Ollama for un-fundable packets.
        from src.shadow_trading.executor import (
            _check_paper_buying_power_allocation,
            _record_bp_rejection_pre_llm,
        )
        _alloc = packet.position_sizing.allocation_dollars
        if not _check_paper_buying_power_allocation(_alloc):
            logger.info(
                "[MR] BP pre-check rejected %s: $%.2f exceeds effective BP",
                ticker, _alloc,
            )
            _record_bp_rejection_pre_llm(packet)
            continue

        packet = enhance_packet_with_llm(packet, feat, config)

        # Log recommendation
        from src.journal.store import log_recommendation
        from src.training.versioning import get_active_model_name

        model_ver = get_active_model_name()
        rec_id = log_recommendation(
            packet, feat, candidate.get("score", 0), "mr_oversold",
            model_version=model_ver,
            llm_conviction=getattr(packet, "llm_conviction", None),
        )

        # Open shadow trade
        if shadow_enabled and rec_id:
            from src.shadow_trading.executor import open_shadow_trade
            trade_id = open_shadow_trade(rec_id, packet, feat)
            if trade_id:
                trades_opened += 1
                results.append({"ticker": ticker, "rsi_2": feat.get("rsi_2"),
                                "trade_id": trade_id, "action": "opened"})
            else:
                results.append({"ticker": ticker, "rsi_2": feat.get("rsi_2"),
                                "action": "rejected"})
        else:
            results.append({"ticker": ticker, "rsi_2": feat.get("rsi_2"),
                            "action": "no_shadow"})

    logger.info("[MR] Scan complete: %d candidates, %d trades opened",
                len(candidates), trades_opened)

    return {
        "status": "complete",
        "candidates": len(candidates),
        "trades_opened": trades_opened,
        "results": results,
        "timestamp": timestamp,
    }
