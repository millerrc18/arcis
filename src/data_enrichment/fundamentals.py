"""SEC EDGAR fundamental data fetcher using XBRL API.

Called by: data_enrichment/enricher.py
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_enrichment.py

Free, no API key required. Rate limit: 10 requests/second.
Requires User-Agent header per SEC guidelines.
"""

# #544 — `import json` removed; was never referenced anywhere in this module.
import logging
import os
import pickle  # noqa: S403  # pre-existing — see #413 for migration plan
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from src.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

CACHE_DIR = Path(".cache/fundamentals")
SEC_USER_AGENT = "Arcis/1.0 (halcyonlabai@gmail.com)"
SEC_BASE = "https://data.sec.gov/api/xbrl/companyconcept"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# In-memory CIK cache
_cik_cache: dict[str, str] = {}


def _get_cache_path(ticker: str, as_of: str | None = None) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # #856 — encode as_of in the cache filename so PIT-bound and runtime
    # caches don't collide. as_of=None (runtime) keeps the historical filename
    # for cache-compat with pre-#856 entries.
    if as_of is None:
        return CACHE_DIR / f"{ticker}_fundamentals.pkl"
    return CACHE_DIR / f"{ticker}_fundamentals_asof_{as_of}.pkl"


def _load_cached(ticker: str, cache_hours: int = 24, as_of: str | None = None) -> dict | None:
    path = _get_cache_path(ticker, as_of=as_of)
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


def _save_cache(ticker: str, data: dict, as_of: str | None = None) -> None:
    data["_cached_at"] = datetime.now()
    path = _get_cache_path(ticker, as_of=as_of)
    try:
        with open(path, "wb") as f:
            pickle.dump(data, f)
    except Exception:
        pass


def _get_cik(ticker: str) -> str | None:
    """Map ticker to zero-padded 10-digit CIK."""
    global _cik_cache

    if ticker in _cik_cache:
        return _cik_cache[ticker]

    # Load the full ticker -> CIK map from SEC
    resp = retry_with_backoff(
        lambda: requests.get(SEC_TICKERS_URL, headers={"User-Agent": SEC_USER_AGENT}, timeout=10),
        max_retries=3, base_delay=2.0,
        exceptions=(requests.RequestException, ConnectionError, OSError),
    )
    if resp is None:
        logger.warning("Failed to fetch SEC ticker map after retries")
        return None
    try:
        resp.raise_for_status()
        data = resp.json()
        for entry in data.values():
            t = entry.get("ticker", "").upper()
            cik = str(entry.get("cik_str", "")).zfill(10)
            _cik_cache[t] = cik
    except Exception as e:
        logger.warning("Failed to fetch SEC ticker map: %s", e)
        return None

    return _cik_cache.get(ticker.upper())


def _fetch_concept(cik: str, concept: str) -> dict | None:
    """Fetch a single XBRL concept from SEC EDGAR."""
    url = f"{SEC_BASE}/CIK{cik}/us-gaap/{concept}.json"
    resp = retry_with_backoff(
        lambda: requests.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=15),
        max_retries=3, base_delay=2.0,
        exceptions=(requests.RequestException, ConnectionError, OSError),
    )
    if resp is None:
        logger.debug("Failed to fetch %s for CIK %s after retries", concept, cik)
        return None
    try:
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.debug("Failed to fetch %s for CIK %s: %s", concept, cik, e)
        return None


def _get_latest_value(
    concept_data: dict | None,
    form_filter: list[str] | None = None,
    as_of: str | None = None,
) -> tuple[float | None, str | None, str | None]:
    """Extract the most recent value from an XBRL concept response.

    Returns (value, filing_date, period_end).

    When ``as_of`` is None (runtime), entries are sorted by ``end`` desc
    (legacy behavior). When ``as_of`` is set (PIT/backtest), entries are
    first filtered by ``filed <= as_of`` (the data was actually available
    by ``as_of``), then sorted by ``filed`` desc with ``end`` desc as the
    secondary key. Closes #856.
    """
    if not concept_data:
        return None, None, None

    units = concept_data.get("units", {})
    # Try USD first, then USD/shares, then pure
    for unit_key in ["USD", "USD/shares", "pure"]:
        if unit_key in units:
            entries = units[unit_key]
            if form_filter:
                entries = [e for e in entries if e.get("form") in form_filter]
            if as_of is not None:
                # PIT filter: only include filings actually available by as_of.
                entries = [e for e in entries if e.get("filed", "") <= as_of]
            if not entries:
                continue
            if as_of is not None:
                # Sort by filed desc primary, end desc secondary.
                entries.sort(
                    key=lambda x: (x.get("filed", ""), x.get("end", "")),
                    reverse=True,
                )
            else:
                # Legacy: sort by end date descending.
                entries.sort(key=lambda x: x.get("end", ""), reverse=True)
            latest = entries[0]
            return latest.get("val"), latest.get("filed"), latest.get("end")

    return None, None, None


def _get_ttm_value(concept_data: dict | None, as_of: str | None = None) -> float | None:
    """Get trailing-twelve-month value by summing last 4 quarterly filings.

    When ``as_of`` is None (runtime), takes the last 4 by ``end`` desc.
    When ``as_of`` is set (PIT/backtest), filters to ``filed <= as_of``
    first, then takes the last 4 by ``filed`` desc. Closes #856.
    """
    if not concept_data:
        return None

    units = concept_data.get("units", {})
    for unit_key in ["USD", "USD/shares"]:
        if unit_key not in units:
            continue
        entries = units[unit_key]
        # Filter to 10-Q and 10-K quarterly data
        quarterly = [e for e in entries if e.get("form") in ("10-Q", "10-K")]
        if as_of is not None:
            quarterly = [e for e in quarterly if e.get("filed", "") <= as_of]
        if as_of is not None:
            # Sort by filed desc primary, end desc secondary.
            quarterly.sort(
                key=lambda x: (x.get("filed", ""), x.get("end", "")),
                reverse=True,
            )
        else:
            # Legacy: sort by end date descending.
            quarterly.sort(key=lambda x: x.get("end", ""), reverse=True)
        # Take last 4 quarters
        if len(quarterly) >= 4:
            return sum(e.get("val", 0) for e in quarterly[:4])
        elif quarterly:
            return quarterly[0].get("val")

    return None


def fetch_fundamental_snapshot(
    ticker: str,
    cache_hours: int = 24,
    as_of: str | None = None,
) -> dict | None:
    """Fetch the most recent fundamental data from SEC EDGAR XBRL API.

    Returns dict with revenue, income, margins, EPS, etc., or None if unavailable.

    When ``as_of`` is None (runtime), returns the latest fundamentals as
    sorted by period end date. When ``as_of`` is set (PIT/backtest), filters
    XBRL entries by ``filed <= as_of`` BEFORE sorting — so the LLM only sees
    data that was actually available on ``as_of`` (no leakage from filings
    submitted after the historical decision date). Closes #856.
    """
    # Check cache (cache key encodes as_of so PIT and runtime caches don't collide)
    cached = _load_cached(ticker, cache_hours, as_of=as_of)
    if cached:
        result = {k: v for k, v in cached.items() if not k.startswith("_")}
        return result if result else None

    cik = _get_cik(ticker)
    if not cik:
        logger.debug("No CIK found for %s", ticker)
        return None

    try:
        # Fetch concepts with rate limiting
        revenue_data = _fetch_concept(cik, "Revenues")
        time.sleep(0.1)

        # Try RevenueFromContractWithCustomerExcludingAssessedTax as fallback
        if not revenue_data:
            revenue_data = _fetch_concept(cik, "RevenueFromContractWithCustomerExcludingAssessedTax")
            time.sleep(0.1)

        net_income_data = _fetch_concept(cik, "NetIncomeLoss")
        time.sleep(0.1)

        eps_data = _fetch_concept(cik, "EarningsPerShareDiluted")
        time.sleep(0.1)

        # Extract values
        revenue_ttm = _get_ttm_value(revenue_data, as_of=as_of)
        net_income_ttm = _get_ttm_value(net_income_data, as_of=as_of)
        eps_val, _, _ = _get_latest_value(eps_data, ["10-Q", "10-K"], as_of=as_of)

        # Get filing date and period info
        _, filing_date, period_end = _get_latest_value(revenue_data, ["10-Q", "10-K"], as_of=as_of)
        if not filing_date:
            _, filing_date, period_end = _get_latest_value(net_income_data, ["10-Q", "10-K"], as_of=as_of)

        # Compute YoY revenue growth
        revenue_yoy = None
        if revenue_data and revenue_ttm:
            units = revenue_data.get("units", {})
            for unit_key in ["USD"]:
                if unit_key in units:
                    entries = [e for e in units[unit_key] if e.get("form") in ("10-Q", "10-K")]
                    if as_of is not None:
                        entries = [e for e in entries if e.get("filed", "") <= as_of]
                        entries.sort(
                            key=lambda x: (x.get("filed", ""), x.get("end", "")),
                            reverse=True,
                        )
                    else:
                        entries.sort(key=lambda x: x.get("end", ""), reverse=True)
                    if len(entries) >= 8:
                        prior_ttm = sum(e.get("val", 0) for e in entries[4:8])
                        if prior_ttm > 0:
                            revenue_yoy = round((revenue_ttm - prior_ttm) / prior_ttm, 3)
                    break

        # Compute margins
        gross_margin = None
        net_margin = None
        if revenue_ttm and revenue_ttm > 0:
            if net_income_ttm:
                net_margin = round(net_income_ttm / revenue_ttm, 3)
            # Gross margin — try GrossProfit concept
            gross_data = _fetch_concept(cik, "GrossProfit")
            time.sleep(0.1)
            gross_val = _get_ttm_value(gross_data, as_of=as_of)
            if gross_val:
                gross_margin = round(gross_val / revenue_ttm, 3)

        # Determine filing type
        filing_type = None
        if revenue_data:
            units = revenue_data.get("units", {})
            for unit_key in ["USD"]:
                if unit_key in units:
                    entries = [e for e in units[unit_key] if e.get("form") in ("10-Q", "10-K")]
                    if as_of is not None:
                        entries = [e for e in entries if e.get("filed", "") <= as_of]
                        entries.sort(
                            key=lambda x: (x.get("filed", ""), x.get("end", "")),
                            reverse=True,
                        )
                    else:
                        entries.sort(key=lambda x: x.get("end", ""), reverse=True)
                    if entries:
                        filing_type = entries[0].get("form")
                    break

        result = {
            "revenue_ttm": revenue_ttm,
            "revenue_yoy_growth": revenue_yoy,
            "net_income_ttm": net_income_ttm,
            "gross_margin": gross_margin,
            "operating_margin": net_margin,  # Actually net margin (net_income/revenue)
            "eps_diluted_ttm": float(eps_val) if eps_val else None,
            "pe_ratio": None,  # Computed externally if price available
            "last_filing_date": filing_date,
            "last_filing_type": filing_type,
            "data_as_of_quarter": period_end,
        }

        _save_cache(ticker, result, as_of=as_of)
        return result

    except Exception as e:
        logger.warning("Failed to fetch fundamentals for %s: %s", ticker, e)
        return None


def format_fundamental_summary(data: dict | None, price: float | None = None) -> str:
    """Format fundamental data into a concise text block for the LLM prompt."""
    if not data:
        return "No fundamental data available"

    parts = []

    rev = data.get("revenue_ttm")
    if rev is not None:
        rev_str = _format_dollars(rev)
        yoy = data.get("revenue_yoy_growth")
        yoy_str = f" ({yoy:+.1%} YoY)" if yoy is not None else ""
        parts.append(f"Revenue (TTM): {rev_str}{yoy_str}")

    ni = data.get("net_income_ttm")
    if ni is not None:
        parts.append(f"Net Income: {_format_dollars(ni)}")

    gm = data.get("gross_margin")
    if gm is not None:
        parts.append(f"Gross Margin: {gm:.1%}")

    om = data.get("operating_margin")  # Actually net margin
    if om is not None:
        parts.append(f"Net Margin: {om:.1%}")

    eps = data.get("eps_diluted_ttm")
    if eps is not None:
        parts.append(f"EPS: ${eps:.2f}")

    # Compute P/E if we have price and EPS
    if price and eps and eps > 0:
        pe = round(price / eps, 1)
        parts.append(f"P/E: {pe}")

    filed = data.get("last_filing_type")
    quarter = data.get("data_as_of_quarter")
    if filed and quarter:
        parts.append(f"Last filed: {filed} ({quarter})")

    return " | ".join(parts) if parts else "No fundamental data available"


def _format_dollars(value: float) -> str:
    """Format large dollar amounts readably."""
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1_000_000_000_000:
        return f"{sign}${abs_val / 1_000_000_000_000:.1f}T"
    elif abs_val >= 1_000_000_000:
        return f"{sign}${abs_val / 1_000_000_000:.1f}B"
    elif abs_val >= 1_000_000:
        return f"{sign}${abs_val / 1_000_000:.1f}M"
    else:
        return f"{sign}${abs_val:,.0f}"
