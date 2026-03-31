"""Macroeconomic context from FRED API.

Called by: data_enrichment/enricher.py
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_enrichment.py

Free tier: 120 requests/minute.
Series: FEDFUNDS, DGS10, DGS2, CPIAUCSL, UNRATE
"""

import logging
import pickle
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

CACHE_DIR = Path(".cache/macro")
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# FRED series IDs
SERIES = {
    "fed_funds": "FEDFUNDS",
    "treasury_10y": "DGS10",
    "treasury_2y": "DGS2",
    "cpi": "CPIAUCSL",
    "unemployment": "UNRATE",
}


def _get_cache_path() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / "macro_context.pkl"


def _load_cached(cache_hours: int = 24) -> dict | None:
    path = _get_cache_path()
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
        if datetime.now() - data.get("_cached_at", datetime.min) < timedelta(hours=cache_hours):
            return data
    except Exception:
        pass
    return None


def _save_cache(data: dict) -> None:
    data["_cached_at"] = datetime.now()
    path = _get_cache_path()
    try:
        with open(path, "wb") as f:
            pickle.dump(data, f)
    except Exception:
        pass


def _fetch_series(series_id: str, api_key: str, limit: int = 1) -> float | None:
    """Fetch the latest value from a FRED series."""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "sort_order": "desc",
        "limit": limit,
        "file_type": "json",
    }
    try:
        resp = requests.get(FRED_BASE, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        observations = data.get("observations", [])
        if observations:
            val = observations[0].get("value", ".")
            if val != ".":
                return float(val)
    except Exception as e:
        logger.debug("Failed to fetch FRED series %s: %s", series_id, e)
    return None


def _fetch_cpi_yoy(api_key: str) -> float | None:
    """Compute YoY CPI from last 13 monthly values."""
    params = {
        "series_id": "CPIAUCSL",
        "api_key": api_key,
        "sort_order": "desc",
        "limit": 13,
        "file_type": "json",
    }
    try:
        resp = requests.get(FRED_BASE, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        observations = data.get("observations", [])
        values = []
        for obs in observations:
            val = obs.get("value", ".")
            if val != ".":
                values.append(float(val))

        if len(values) >= 13:
            current = values[0]
            year_ago = values[12]
            if year_ago > 0:
                return round((current - year_ago) / year_ago * 100, 1)
    except Exception as e:
        logger.debug("Failed to compute CPI YoY: %s", e)
    return None


def _classify_fed_stance(rate: float | None) -> str:
    if rate is None:
        return "unknown"
    if rate > 4:
        return "restrictive"
    elif rate >= 2:
        return "neutral"
    else:
        return "accommodative"


def _classify_yield_curve(spread: float | None) -> str:
    if spread is None:
        return "unknown"
    if spread < 0:
        return "inverted"
    elif spread <= 0.5:
        return "flat"
    elif spread <= 1.5:
        return "normal"
    else:
        return "steep"


def _classify_economic_regime(
    yield_curve_signal: str,
    unemployment: float | None,
    cpi_yoy: float | None,
    fed_stance: str,
) -> str:
    """Classify economic regime based on multiple indicators."""
    if yield_curve_signal == "inverted":
        return "recession"

    if fed_stance == "accommodative":
        return "early_cycle"

    if fed_stance == "restrictive" and cpi_yoy is not None and cpi_yoy > 3:
        return "late_cycle"

    if unemployment is not None and unemployment > 5:
        return "recession"

    return "mid_cycle"


def fetch_macro_context(fred_api_key: str | None = None, cache_hours: int = 24) -> dict:
    """Fetch current macroeconomic context from FRED API.

    Returns dict with Fed rate, yield curve, CPI, unemployment, and regime classification.
    Returns sensible defaults if FRED is unavailable.
    """
    # Check cache
    cached = _load_cached(cache_hours)
    if cached:
        return {k: v for k, v in cached.items() if not k.startswith("_")}

    # Defaults if FRED unavailable
    defaults = {
        "fed_funds_rate": None,
        "fed_stance": "unknown",
        "yield_curve_10y2y": None,
        "yield_curve_signal": "unknown",
        "cpi_yoy": None,
        "unemployment_rate": None,
        "economic_regime": "mid_cycle",
        "last_fomc_action": "unknown",
        "last_fomc_date": None,
    }

    if not fred_api_key:
        logger.info("[MACRO] No FRED API key configured, using defaults")
        return defaults

    try:
        # Fetch each series
        fed_rate = _fetch_series("FEDFUNDS", fred_api_key)
        time.sleep(0.1)

        treasury_10y = _fetch_series("DGS10", fred_api_key)
        time.sleep(0.1)

        treasury_2y = _fetch_series("DGS2", fred_api_key)
        time.sleep(0.1)

        cpi_yoy = _fetch_cpi_yoy(fred_api_key)
        time.sleep(0.1)

        unemployment = _fetch_series("UNRATE", fred_api_key)

        # Compute spread
        yield_spread = None
        if treasury_10y is not None and treasury_2y is not None:
            yield_spread = round(treasury_10y - treasury_2y, 2)

        # Classify
        fed_stance = _classify_fed_stance(fed_rate)
        yield_signal = _classify_yield_curve(yield_spread)
        regime = _classify_economic_regime(yield_signal, unemployment, cpi_yoy, fed_stance)

        result = {
            "fed_funds_rate": fed_rate,
            "fed_stance": fed_stance,
            "yield_curve_10y2y": yield_spread,
            "yield_curve_signal": yield_signal,
            "cpi_yoy": cpi_yoy,
            "unemployment_rate": unemployment,
            "economic_regime": regime,
            "last_fomc_action": "hold",  # Would need FOMC calendar parsing for accuracy
            "last_fomc_date": None,
        }

        _save_cache(result)
        return result

    except Exception as e:
        logger.warning("[MACRO] Failed to fetch macro context: %s", e)
        return defaults


def format_macro_summary(data: dict) -> str:
    """Format macro data into a concise text block."""
    parts = []

    fed_rate = data.get("fed_funds_rate")
    fed_stance = data.get("fed_stance", "unknown")
    if fed_rate is not None:
        fomc_action = data.get("last_fomc_action", "unknown")
        fomc_date = data.get("last_fomc_date")
        fomc_str = f" — last action: {fomc_action}"
        if fomc_date:
            fomc_str += f" ({fomc_date})"
        parts.append(f"Fed: {fed_stance.title()} ({fed_rate:.2f}%){fomc_str}")
    else:
        parts.append(f"Fed: {fed_stance.title()}")

    yield_spread = data.get("yield_curve_10y2y")
    yield_signal = data.get("yield_curve_signal", "unknown")
    if yield_spread is not None:
        parts.append(f"Yield curve: {yield_signal.title()} ({yield_spread:+.2f}%)")

    cpi = data.get("cpi_yoy")
    if cpi is not None:
        parts.append(f"CPI: {cpi:.1f}% YoY")

    unemp = data.get("unemployment_rate")
    if unemp is not None:
        parts.append(f"Unemployment: {unemp:.1f}%")

    regime = data.get("economic_regime", "unknown")
    parts.append(f"Regime: {regime.replace('_', ' ').title()}")

    return ". ".join(parts) + "."
