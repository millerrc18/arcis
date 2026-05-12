"""FRED 3-month T-bill (DTB3) ingestion for canonical excess Sharpe.

Audit spec §5: `rf_adjusted_excess_sharpe(returns - rf_period)` is the canonical
metric. T1.02's Stage-1 baseline writer currently uses RF_PERIOD_CONSTANT as a
placeholder; once this module lands, that script can call `get_rf_rate(date)`
per row.

`get_rf_rate(d)` returns a per-day decimal rate ≈ annualized %% / 100 / 252.
e.g. DTB3 = 4.20 → 0.000167 per trading day. The 252 divisor mirrors the
PERIODS_PER_YEAR constant in src/analytics/canonical_sharpe.py — keep them in
lock-step if either changes.

Caching is in-process (a module-level dict keyed by ISO date). Re-imports clear
it. We do not persist to SQLite; FRED is cheap, and per-process caching is all
the canonical-Sharpe call sites need.

Called by: scripts/stage1_baseline_recompute.py (T1.02 follow-up, out of scope
  here), eventually src/analytics/canonical_sharpe.py callers needing per-row rf.
Calls: requests (HTTP), src.config.load_config, src.data_collection.errors.
Owns tables: none.
Config keys: FRED_API_KEY env (primary), data_enrichment.fred_api_key,
  fred.api_key, fred_api_key (mirrors macro_collector resolution order).
Tests: tests/data_ingestion/test_risk_free_rate.py.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
SERIES_ID = "DTB3"
TRADING_DAYS_PER_YEAR = 252

# Module-level cache: {iso_date: per_day_decimal_rate}.
_CACHE: dict[str, float] = {}


def _cache_clear() -> None:
    """Reset the in-process cache (test hook)."""
    _CACHE.clear()


def _get_fred_api_key() -> Optional[str]:
    """Same resolution order as macro_collector for consistency."""
    env_key = os.environ.get("FRED_API_KEY")
    if env_key:
        return env_key
    try:
        from src.config import load_config
        config = load_config()
        return (
            config.get("data_enrichment", {}).get("fred_api_key")
            or config.get("fred", {}).get("api_key")
            or config.get("fred_api_key")
        )
    except Exception:
        return None


def _fetch_dtb3_observations(api_key: str, on_or_before: dt.date) -> list[dict]:
    """Fetch DTB3 observations on or before `on_or_before`, newest first.

    A modest limit handles weekends/holidays via the prior-banking-day fallback.
    """
    if requests is None:
        raise ImportError(
            "requests is required for FRED fetch but is not installed. "
            "Add requests>=2.31,<3.0 to requirements-cloud.txt."
        )
    resp = requests.get(
        FRED_BASE,
        params={
            "series_id": SERIES_ID,
            "api_key": api_key,
            "sort_order": "desc",
            "limit": 10,
            "observation_end": on_or_before.isoformat(),
            "file_type": "json",
        },
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json().get("observations", [])


def get_rf_rate(date: dt.date) -> float:
    """Return the per-day decimal risk-free rate for `date`.

    DTB3 is annualized in percent. We convert to a per-trading-day decimal:
        per_day = (annualized_pct / 100) / 252

    Missing-date behavior: walks back through the FRED response until a valid
    observation is found (covers weekends/holidays). Raises KeyError if FRED
    returns zero usable rows so callers don't silently inherit a zero rate.

    Raises:
        CollectorConfigError: when FRED_API_KEY is not configured (per
          src/data_collection/errors.py — surfaces as a hard failure rather
          than a silent error dict).
        KeyError: when FRED has no usable observation on or before `date`.
    """
    cache_key = date.isoformat()
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    api_key = _get_fred_api_key()
    if not api_key:
        from src.data_collection.errors import CollectorConfigError
        raise CollectorConfigError(
            "FRED_API_KEY not configured — set in .env or "
            "config/settings.local.yaml (data_enrichment.fred_api_key)."
        )

    observations = _fetch_dtb3_observations(api_key, date)
    for obs in observations:
        raw = obs.get("value", ".")
        if raw == ".":
            continue
        try:
            annualized_pct = float(raw)
        except (TypeError, ValueError):
            continue
        per_day = (annualized_pct / 100.0) / TRADING_DAYS_PER_YEAR
        _CACHE[cache_key] = per_day
        return per_day

    raise KeyError(
        f"No usable DTB3 observation on or before {cache_key} — "
        "FRED returned zero non-sentinel rows."
    )
