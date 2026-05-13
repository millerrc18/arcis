"""Shared Finnhub helpers for data-collection modules.

Called by: data_collection.institutional_ownership_collector,
           data_collection.filings_sentiment_collector,
           data_collection.press_releases_collector,
           data_collection.insider_collector,
           data_collection.short_interest_collector,
           data_collection.analyst_collector
Calls: src.config.load_config
Owns tables: none
Config keys: FINNHUB_API_KEY (env), data_enrichment.finnhub_api_key (YAML)
Tests: tests/data_collection/test_finnhub_shared.py

Sprint 6 Wave A — WA1 extraction.

Previously each of the six collectors above defined a byte-identical
``_get_finnhub_key()`` helper (sibling-search confirmed 6 sites;
PR reviews #1082/#1083/#1084 flagged the duplication). This module
centralises the helper so the duplication can never drift apart.
"""

from __future__ import annotations

import os


def get_finnhub_key() -> str | None:
    """Return the Finnhub API key.

    Precedence: FINNHUB_API_KEY env var first (honours .env / Render env),
    then ``data_enrichment.finnhub_api_key`` from YAML config, then None
    when neither source is populated.
    """
    env_key = os.environ.get("FINNHUB_API_KEY")
    if env_key:
        return env_key
    try:
        from src.config import load_config
        config = load_config()
        return config.get("data_enrichment", {}).get("finnhub_api_key")
    except Exception:
        return None
