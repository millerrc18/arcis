"""Register the 18 data-collection SYSTEMs en-bloc.

Each *_collector.py module is registered as a SYSTEM in the capability
registry. Registrations are driven by a metadata table (dict of dicts) so
the module<->capability binding is reviewable as data rows.

The SYSTEM name MUST equal the collector module stem so Convention B
(tests/test_capability_registry_coverage.py) can derive the expected set
directly from the glob.

Import-light: only `date`, `register_system`, and `table_freshness_health`
are imported at module top. All heavy collector imports stay in the health
closure bodies (lazy import via table_freshness_health internals).

Called by: src.platform.capability_registry.bootstrap (import-time side effect)
Calls: src.platform.capability_registry.register_system (decorator/functional)
       src.data_collection._capability_health.table_freshness_health
Owns tables: none
Config keys: none
Tests: tests/test_capability_registry_coverage.py (Convention B)
"""
from __future__ import annotations

from datetime import date

from src.data_collection._capability_health import table_freshness_health
from src.platform.capability_registry import register_system

_TODAY = date(2026, 5, 21)

# Each row: (system_name, table, ts_col, stale_after_minutes, cadence, description)
# system_name must equal the *_collector.py module stem (Convention B oracle).
# stale_after_minutes: daily overnight collectors = 1500 (~25h), quarterly = 200160 (~139d)
_COLLECTORS: tuple[tuple[str, str, str, int, str, str], ...] = (
    (
        "analyst_collector",
        "analyst_estimates",
        "collected_at",
        1500,
        "nightly",
        "Consensus analyst recommendations and price targets for the S&P 100 universe "
        "(Finnhub /stock/recommendation). Rotates tickers over multiple nights.",
    ),
    (
        "cboe_collector",
        "cboe_ratios",
        "collected_at",
        1500,
        "nightly",
        "CBOE equity and index put/call ratio snapshots for options-sentiment regime signals.",
    ),
    (
        "company_executive_collector",
        "company_executives",
        "retrieved_at",
        1500,
        "nightly",
        "Finnhub /stock/executive data: executive names, positions, and compensation "
        "for the S&P 100 universe. Plan-gated (fundamental-1).",
    ),
    (
        "docs_collector",
        "research_docs",
        "updated_at",
        10080,
        "weekly",
        "Scans the docs/ tree and syncs markdown files into research_docs "
        "for cloud-side reading and documentation freshness tracking.",
    ),
    (
        "edgar_collector",
        "edgar_filings",
        "collected_at",
        1500,
        "nightly",
        "SEC EDGAR 8-K/10-Q/10-K filings for the universe; "
        "feeds the enrichment and LLM scoring pipelines.",
    ),
    (
        "fed_collector",
        "fed_communications",
        "collected_at",
        10080,
        "weekly",
        "Federal Reserve communications: FOMC statements, minutes, Beige Book, "
        "and speeches used in macro-regime analysis.",
    ),
    (
        "filings_sentiment_collector",
        "filings_sentiment",
        "retrieved_at",
        1500,
        "nightly",
        "Finnhub /stock/filings-sentiment sentiment scores for SEC filings "
        "(plan-gated fundamental-1). Distinct cadence from edgar_collector.",
    ),
    (
        "insider_collector",
        "insider_transactions",
        "collected_at",
        1500,
        "nightly",
        "SEC Form 4 insider buy/sell transactions for the S&P 100 universe "
        "via Finnhub; used in candidate scoring.",
    ),
    (
        "institutional_ownership_collector",
        "institutional_holdings",
        "retrieved_at",
        200160,
        "quarterly",
        "Finnhub /stock/ownership institutional-holder aggregate snapshots "
        "(plan-gated fundamental-1); keyed by (ticker, as_of_date).",
    ),
    (
        "macro_collector",
        "macro_snapshots",
        "collected_at",
        1500,
        "nightly",
        "FRED macro series snapshots (GDP growth, CPI, unemployment, yields, spreads) "
        "for macro-regime overlay and governor signals.",
    ),
    (
        "options_collector",
        "options_chains",
        "collected_at",
        1500,
        "nightly",
        "Full options-chain snapshots (strike/expiry/IV/OI/volume) "
        "for the S&P 100 universe; feeds the options-metrics enricher.",
    ),
    (
        "press_releases_collector",
        "press_releases",
        "retrieved_at",
        1500,
        "nightly",
        "Finnhub /press-releases material-event press releases "
        "(plan-gated fundamental-1). Separate from news_collector; "
        "lands in MATERIAL EVENTS.",
    ),
    (
        "price_target_collector",
        "price_targets",
        "retrieved_at",
        1500,
        "nightly",
        "Finnhub /stock/price-target plan-gated full-universe snapshot "
        "(fundamental-1). Distinct from analyst_collector's opportunistic columns.",
    ),
    (
        "research_collector",
        "research_papers",
        "collected_at",
        1500,
        "nightly",
        "Discovers and relevance-scores research papers from arXiv, SSRN, "
        "HuggingFace, Reddit, GitHub, and AI blogs. "
        "Papers scoring >= 0.4 stored for weekly synthesis.",
    ),
    (
        "short_interest_collector",
        "short_interest",
        "collected_at",
        1500,
        "nightly",
        "Short-interest data (short float, days-to-cover) for the universe; "
        "used in momentum and crowding signals.",
    ),
    (
        "stock_financials_collector",
        "stock_financials",
        "retrieved_at",
        1500,
        "nightly",
        "Finnhub /stock/metric?metric=all fundamental ratio snapshot "
        "(plan-gated fundamental-1); ~100 ratios per ticker per day.",
    ),
    (
        "trends_collector",
        "google_trends",
        "collected_at",
        1500,
        "nightly",
        "Google Trends search-interest scores for the S&P 100 tickers; "
        "proxy for retail attention and momentum confirmation.",
    ),
    (
        "vix_collector",
        "vix_term_structure",
        "collected_at",
        1500,
        "nightly",
        "VIX/VIX9D/VIX3M/VIX1Y term-structure snapshot for volatility-regime "
        "classification and the governor volatility-halt gate.",
    ),
)

for _name, _table, _ts, _stale, _cadence, _desc in _COLLECTORS:
    def _health(
        table: str = _table,
        ts: str = _ts,
        stale: int = _stale,
        cadence: str = _cadence,
    ) -> dict:
        return table_freshness_health(table, ts, stale, cadence)

    register_system(
        name=_name,
        description=_desc,
        category="data-collection",
        version="1.0",
        maintainer="ai_session",
        introduced_in="v0.36.49",
        last_reviewed_date=_TODAY,
        expected_runtime=_cadence,
    )(_health)
