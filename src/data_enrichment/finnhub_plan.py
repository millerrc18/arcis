"""Finnhub plan and feature gating helpers.

Called by: data_collection.analyst_collector, data_enrichment.enricher
Calls: src.config.load_config
Owns tables: none
Config keys: data_enrichment.finnhub_plan, FINNHUB_PLAN
Tests: tests/test_enrichment.py

The user may move between free and paid Finnhub plans over time. This module
centralizes the feature gating so runtime enrichment can opportunistically use
paid endpoints when enabled, while collectors avoid known-403 endpoints on
plans that do not include them.
"""

from __future__ import annotations

import os

DEFAULT_FINNHUB_PLAN = "auto"

_PLAN_ALIASES = {
    "auto": "auto",
    "free": "free",
    "fundamental-1": "fundamental-1",
    "fundamental_1": "fundamental-1",
    "fundamental1": "fundamental-1",
}

_FEATURE_MATRIX: dict[str, set[str]] = {
    "free": {
        "company_news",
        "insider_transactions",
        "recommendation_trends",
        "short_interest",
    },
    "fundamental-1": {
        "company_news",
        "company_executive",
        "filings",
        "filings_sentiment",
        "fund_ownership",
        "insider_transactions",
        "institutional_ownership",
        "news_sentiment",
        "press_releases",
        "price_target",
        "recommendation_trends",
        "short_interest",
        "stock_financials",
        "stock_ownership",
    },
}


def normalize_finnhub_plan(raw: str | None) -> str:
    """Return one of: auto, free, fundamental-1."""
    if not raw:
        return DEFAULT_FINNHUB_PLAN
    key = str(raw).strip().lower()
    return _PLAN_ALIASES.get(key, DEFAULT_FINNHUB_PLAN)


def get_finnhub_plan(config: dict | None = None) -> str:
    """Resolve Finnhub plan from env first, then config, then default."""
    env_plan = os.environ.get("FINNHUB_PLAN")
    if env_plan:
        return normalize_finnhub_plan(env_plan)

    cfg = config
    if cfg is None:
        try:
            from src.config import load_config
            cfg = load_config()
        except Exception:
            cfg = {}

    raw = ((cfg or {}).get("data_enrichment") or {}).get("finnhub_plan")
    return normalize_finnhub_plan(raw)


def finnhub_plan_supports(feature: str, config: dict | None = None) -> bool:
    """Whether the configured Finnhub plan should attempt a feature.

    `auto` behaves like `fundamental-1` for the currently wired premium
    features. Individual fetchers still degrade gracefully on 403 so the
    user can keep `auto` during plan transitions without breaking scans.
    """
    plan = get_finnhub_plan(config)
    if plan == "auto":
        plan = "fundamental-1"
    return feature in _FEATURE_MATRIX.get(plan, set())
