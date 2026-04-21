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

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.platform.strategy_spec import StrategySpec


def attach_post_scan_features(
    features: dict,
    *,
    config: dict,
    spy,
    vix_value: float | None = None,
    db_path: str | None = None,
    strategy: "StrategySpec" | None = None,
) -> dict:
    """Attach traffic_light_multiplier, event_risk_multiplier, and a top-level
    regime_label to every ticker's feature dict. Mutates `features` in place.

    The helper never raises on sub-step failures — on error it sets conservative
    defaults (multiplier=1.0 for event_risk, regime unchanged for traffic_light)
    so the scan cycle continues. Failures are logged as warnings.
    """
    chain = _strategy_post_scan_chain(strategy)
    if chain is None:
        chain = ("traffic_light", "event_risk")

    for helper_name in chain:
        if helper_name == "traffic_light":
            _apply_traffic_light(features, config=config, spy=spy, vix_value=vix_value)
        elif helper_name == "event_risk":
            _apply_event_risk(
                features,
                config=config,
                db_path=db_path,
                strategy=strategy,
            )

    return features


def _strategy_post_scan_chain(strategy: "StrategySpec" | None) -> tuple[str, ...] | None:
    if strategy is None:
        return None
    raw = getattr(strategy, "raw", {}) or {}
    post_scan = raw.get("post_scan")
    if not isinstance(post_scan, dict):
        return None
    chain = post_scan.get("chain")
    if not isinstance(chain, list) or not chain:
        return None
    items = tuple(item for item in chain if isinstance(item, str) and item)
    return items or None


def _strategy_quarantine_categories(strategy: "StrategySpec" | None) -> set[str]:
    if strategy is None:
        return set()
    raw = getattr(strategy, "raw", {}) or {}
    event_risk = raw.get("event_risk")
    if not isinstance(event_risk, dict):
        return set()
    items = event_risk.get("quarantine_categories")
    if not isinstance(items, list):
        return set()
    return {item for item in items if isinstance(item, str) and item}


def _apply_traffic_light(
    features: dict,
    *,
    config: dict,
    spy,
    vix_value: float | None,
) -> None:
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
            feat.setdefault("regime_label", regime_label)
        logger.info(
            "[ENRICH] Traffic Light: mult=%.2f (effective=%.2f) regime=%s",
            base_mult, effective_mult, regime_label,
        )
    except Exception as e:
        logger.warning("[ENRICH] Traffic Light failed: %s — using default", e)
        for feat in features.values():
            feat.setdefault("traffic_light_multiplier", 1.0)


def _apply_event_risk(
    features: dict,
    *,
    config: dict,
    db_path: str | None,
    strategy: "StrategySpec" | None,
) -> None:
    try:
        from src.features.event_risk_score import attach_event_risk_scores
        kwargs = {"settings": config}
        if db_path is not None:
            kwargs["db_path"] = db_path
        attach_event_risk_scores(features, **kwargs)
        _apply_event_risk_quarantine(features, strategy)
    except Exception as e:
        logger.warning("[ENRICH] Event risk failed: %s — using default", e)
        for feat in features.values():
            feat.setdefault("event_risk_multiplier", 1.0)
            feat.setdefault("event_risk_score", 0)
            feat.setdefault("event_risk_quarantined", False)
            feat.setdefault("event_risk_quarantine_matches", [])


def _apply_event_risk_quarantine(features: dict, strategy: "StrategySpec" | None) -> None:
    quarantine = _strategy_quarantine_categories(strategy)
    if not quarantine:
        for feat in features.values():
            feat.setdefault("event_risk_quarantined", False)
            feat.setdefault("event_risk_quarantine_matches", [])
        return

    for feat in features.values():
        active = _active_event_risk_categories(feat)
        matches = sorted(active & quarantine)
        feat["event_risk_quarantine_matches"] = matches
        feat["event_risk_quarantined"] = bool(matches)
        if matches:
            feat["event_risk_multiplier"] = 0.0


def _active_event_risk_categories(feat: dict) -> set[str]:
    categories: set[str] = set()
    components = feat.get("event_risk_components", {}) or {}

    for key in ("fomc", "nfp", "cpi"):
        if components.get(key, 0):
            categories.add(key)

    earnings_days = components.get("earnings_days")
    earnings_forces_block = bool(components.get("earnings_forces_block"))
    event_risk_level = feat.get("event_risk_level", "none")

    if isinstance(earnings_days, (int, float)) and earnings_days <= 3:
        categories.add("earnings_imminent")
    elif event_risk_level == "imminent":
        categories.add("earnings_imminent")
    elif earnings_forces_block or event_risk_level == "elevated":
        categories.add("earnings_elevated")

    return categories
