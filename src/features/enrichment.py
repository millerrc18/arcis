"""Shared post-scan feature enrichment.

Called by: services.scan_service, services.mr_scan_service, scheduler.universe_scanner
Calls: features.traffic_light, features.event_risk_score
Owns tables: none
Config keys: bootcamp.enabled, bootcamp.traffic_light_floor
Tests: tests/test_features_enrichment.py

Why this exists: before 2026-04-14 each scanner attached (or omitted) traffic_light
and event_risk scores in its own way. The mean-reversion scanner omitted both,
which caused all MR candidates to fall back to conservative defaults (0.5
traffic_light, 1.0 event_risk) AND to store market_regime=NULL in the recommendations
table. Centralizing the attachment here ensures every scanner that goes through
a shadow_trades insert has consistently enriched features.
"""

import logging

logger = logging.getLogger(__name__)


def attach_post_scan_features(
    features: dict,
    *,
    config: dict,
    spy,
    vix_value: float | None = None,
    db_path: str | None = None,
) -> dict:
    """Attach traffic_light_multiplier, event_risk_multiplier, and a top-level
    regime_label to every ticker's feature dict. Mutates `features` in place.

    The helper never raises on sub-step failures — on error it sets conservative
    defaults (multiplier=1.0 for event_risk, regime unchanged for traffic_light)
    so the scan cycle continues. Failures are logged as warnings.
    """
    # ── Traffic light ─────────────────────────────────────────────────
    try:
        from src.features.traffic_light import compute_traffic_light
        tl = compute_traffic_light(spy, vix=vix_value)
        base_mult = tl.get("sizing_multiplier", 1.0)
        effective_mult = base_mult
        bootcamp_cfg = (config or {}).get("bootcamp", {})
        if bootcamp_cfg.get("enabled", False):
            floor = bootcamp_cfg.get("traffic_light_floor", 0.5)
            if base_mult < floor:
                logger.info(
                    "[ENRICH] Bootcamp override: traffic_light mult %.2f -> %.2f",
                    base_mult, floor,
                )
                effective_mult = floor
        regime_label = tl.get("regime_label", "unknown")
        for feat in features.values():
            feat["traffic_light"] = tl
            feat["traffic_light_multiplier"] = effective_mult
            # Spread regime_label to top level if upstream pipeline didn't.
            # setdefault preserves features.engine's engine-computed regime
            # (which has full regime metadata) when present.
            feat.setdefault("regime_label", regime_label)
        logger.info(
            "[ENRICH] Traffic Light: mult=%.2f (effective=%.2f) regime=%s",
            base_mult, effective_mult, regime_label,
        )
    except Exception as e:
        logger.warning("[ENRICH] Traffic Light failed: %s — using default", e)
        for feat in features.values():
            feat.setdefault("traffic_light_multiplier", 1.0)

    # ── Event risk ────────────────────────────────────────────────────
    try:
        from src.features.event_risk_score import attach_event_risk_scores
        kwargs = {"settings": config}
        if db_path is not None:
            kwargs["db_path"] = db_path
        attach_event_risk_scores(features, **kwargs)
    except Exception as e:
        logger.warning("[ENRICH] Event risk failed: %s — using default", e)
        for feat in features.values():
            feat.setdefault("event_risk_multiplier", 1.0)
            feat.setdefault("event_risk_score", 0)

    return features
