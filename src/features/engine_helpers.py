"""Helpers for features.engine — loaders, fan-out, per-ticker enrichment.

Called by: features.engine
Calls: features.earnings, features.event_proximity, features.regime, features.setup_classifier, universe.sectors
Owns tables: none
Config keys: none
Tests: tests/features/test_pit_correctness.py, tests/test_features.py

Split out of engine.py during Sprint 0/Wave 5a so engine.py stays under
the 400-line repo-structure limit while the new ENGINE-FAIL-LOUD code
path stays explicit. compute_all_features() in engine.py calls these
helpers; engine.py re-exports the `_load_*` and `_add_sector_features`
symbols so existing tests that patch `src.features.engine._load_*` keep
working.

The module guarantees:
  - load_shared_enrichments() resolves _load_* via src.features.engine, so
    when a test patches src.features.engine._load_options_metrics the
    patched callable is used (not the bare implementation here).
  - enrich_ticker() resolves _add_sector_features + compute_features via
    src.features.engine for the same reason.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

from src.config import DB_PATH

logger = logging.getLogger(__name__)


_DEFAULT_EVENT_FEATURES = {
    "event_proximity_type": None,
    "event_proximity_days": None,
    "event_proximity_desc": None,
    "events_within_3d": 0,
}


# ---------------------------------------------------------------------------
# Shared-enrichment loaders (exposed via engine for back-compat with tests)
# ---------------------------------------------------------------------------


def _load_options_metrics() -> dict[str, dict]:
    """Load latest options metrics per ticker from the database.

    Returns empty dict when the options_metrics table has no rows
    (legitimate empty-state, not a failure). Raises when the DB is
    unreachable or the query fails — orchestrator counts that as a
    shared-enrichment failure contributing to the >50% fail-loud threshold.
    """
    # #590 — connect_db (busy_timeout=30s) prevents the "database is locked"
    # cluster seen during overnight write bursts; raw sqlite3.connect did not
    # apply the timeout.
    from src.utils.db import connect_db
    result = {}
    with connect_db(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT ticker, iv_rank, put_call_volume_ratio, put_call_oi_ratio,
                      iv_skew, unusual_volume_flag
               FROM options_metrics
               WHERE collected_at = (SELECT MAX(collected_at) FROM options_metrics)"""
        ).fetchall()
        for row in rows:
            result[row["ticker"]] = {
                "iv_rank": row["iv_rank"],
                "put_call_vol_ratio": row["put_call_volume_ratio"],
                "put_call_oi_ratio": row["put_call_oi_ratio"],
                "iv_skew": row["iv_skew"],
                "unusual_options_activity": bool(row["unusual_volume_flag"]),
            }
    return result


def _load_event_proximity(as_of: date | None = None) -> dict:
    """Load event proximity features (shared across all tickers).

    Sprint 0/Wave 5a: accepts as_of to plumb PIT cutoff through to
    event_proximity. None preserves live-scan behavior (today).
    """
    from src.features.event_proximity import get_event_proximity_features
    return get_event_proximity_features(reference_date=as_of)


def _load_sector_profiles() -> dict:
    """Load sector profiles from JSON reference file.

    Missing reference file is a legitimate empty-state (returns {}).
    Malformed JSON or read errors raise — the orchestrator counts that
    as a shared-enrichment failure.
    """
    path = Path("data/reference/sector_profiles.json")
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _add_sector_features(feat: dict, ticker: str, sector_profiles: dict) -> bool:
    """Add GICS sector and sector-specific context to feature dict.

    Returns True on success, False on failure (so the per-ticker partial
    failure counter in compute_all_features can record it). The feature
    dict is still populated with explicit "Unknown" defaults on failure
    so downstream code never reads missing keys.
    """
    try:
        from src.universe.sectors import SECTOR_MAP
        sector = SECTOR_MAP.get(ticker, "Unknown")
        feat["sector"] = sector

        profile = sector_profiles.get(sector, {})
        feat["sector_pullback_depth"] = profile.get("typical_pullback_depth", "n/a")
        feat["sector_recovery_speed"] = profile.get("recovery_speed", "n/a")
        feat["sector_key_factors"] = profile.get("key_factors", [])
        return True
    except Exception as e:
        logger.warning("Sector lookup failed for %s: %s", ticker, e)
        feat["sector"] = "Unknown"
        feat["sector_pullback_depth"] = "n/a"
        feat["sector_recovery_speed"] = "n/a"
        feat["sector_key_factors"] = []
        return False


# ---------------------------------------------------------------------------
# Fan-out + per-ticker enrichment
# ---------------------------------------------------------------------------


def load_shared_enrichments(
    spy: pd.DataFrame,
    ohlcv_data: dict[str, pd.DataFrame],
    sector_enabled: bool,
    cutoff: date | None,
) -> tuple[dict, dict, dict, dict, int]:
    """Load the 4 shared enrichment loaders, counting failures.

    Returns (regime, options_data, event_features, sector_profiles, fail_count).
    Each loader's exception is logged at WARNING and counted; caller decides
    whether to raise based on the fail-loud threshold.

    Loader callables are resolved via `src.features.engine` so existing
    tests that `patch("src.features.engine._load_options_metrics", ...)`
    continue to take effect.
    """
    from src.features import engine
    from src.features.regime import compute_market_regime
    failures = 0

    try:
        regime = compute_market_regime(spy, ohlcv_data)
    except Exception as e:
        logger.warning("Failed to compute market regime: %s", e)
        regime = {}
        failures += 1

    try:
        options_data = engine._load_options_metrics()
    except Exception as e:
        logger.warning("Failed to load options metrics: %s", e)
        options_data = {}
        failures += 1

    try:
        event_features = engine._load_event_proximity(as_of=cutoff)
    except Exception as e:
        logger.warning("Failed to load event proximity features: %s", e)
        event_features = dict(_DEFAULT_EVENT_FEATURES)
        failures += 1

    if sector_enabled:
        try:
            sector_profiles = engine._load_sector_profiles()
        except Exception as e:
            logger.warning("Failed to load sector profiles: %s", e)
            sector_profiles = {}
            failures += 1
    else:
        sector_profiles = {}

    return regime, options_data, event_features, sector_profiles, failures


def _classify_setup_for_ticker(
    feat: dict, df: pd.DataFrame, ticker: str, regime: dict,
) -> bool:
    """Run setup_classifier for one ticker. Returns True on success.

    Setup classifier has a circular-import risk with features.indicators,
    so the import is deferred. Failure is per-ticker partial; engine still
    emits features but with setup_type=unknown.
    """
    try:
        from src.features.setup_classifier import classify_setup, log_setup_signal
        classification = classify_setup(feat, df)
        feat["setup_type"] = classification["setup_type"]
        feat["setup_confidence"] = classification["confidence"]
        feat["setup_desk"] = classification["tradeable_by_desk"]
        log_setup_signal(ticker, classification, feat,
                         regime=regime.get("regime_label", ""))
        return True
    except Exception as e:
        logger.warning("Setup classification failed for %s: %s", ticker, e)
        feat["setup_type"] = "unknown"
        feat["setup_confidence"] = 0.0
        feat["setup_desk"] = "none"
        return False


def enrich_ticker(
    ticker: str,
    df: pd.DataFrame,
    spy: pd.DataFrame,
    cutoff: date | None,
    regime: dict,
    options_data: dict,
    event_features: dict,
    sector_profiles: dict,
    sector_enabled: bool,
) -> dict:
    """Compute + enrich one ticker's feature dict.

    Tracks per-ticker partial failures (sector lookup, setup classifier)
    and attaches `_partial_failure_count` only when nonzero (to preserve
    sprint_F fixture hashes for healthy tickers).
    """
    from src.features import engine
    from src.features.earnings import check_earnings_overlap, get_next_earnings_date

    feat = engine.compute_features(ticker, df, spy, as_of=cutoff)
    partial_failures = 0

    earnings_date = get_next_earnings_date(ticker, as_of=cutoff)
    earnings_info = check_earnings_overlap(earnings_date, as_of=cutoff)
    feat["earnings_date"] = earnings_info["earnings_date"]
    feat["hold_overlaps_earnings"] = earnings_info["hold_overlaps_earnings"]
    feat["days_to_earnings"] = earnings_info["days_to_earnings"]
    feat["event_risk_level"] = earnings_info["event_risk_level"]

    feat.update(regime)
    if ticker in options_data:
        feat.update(options_data[ticker])
    feat.update(event_features)

    if sector_enabled:
        if not engine._add_sector_features(feat, ticker, sector_profiles):
            partial_failures += 1

    if not _classify_setup_for_ticker(feat, df, ticker, regime):
        partial_failures += 1

    if partial_failures > 0:
        feat["_partial_failure_count"] = partial_failures
    return feat
