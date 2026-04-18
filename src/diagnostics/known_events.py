"""Known macro events for the March-April 2026 trade window.

Called by: diagnostics.analyses
Calls: none
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""

# Dict of ISO date string -> event label.
# Used by day-clustering analysis (A2 tertiary) to determine whether
# a bad-day cluster maps to a repeatable event category.
KNOWN_EVENTS: dict[str, str] = {
    # March 2026
    "2026-03-18": "FOMC_DECISION",
    "2026-03-19": "FOMC_DECISION",
    "2026-03-28": "QUARTER_END_REBALANCE",
    # April 2026
    "2026-04-02": "TARIFF_ANNOUNCEMENT",
    "2026-04-03": "NFP_FRIDAY",
    "2026-04-04": "TARIFF_ESCALATION",
    "2026-04-07": "TARIFF_ESCALATION",
    "2026-04-09": "TARIFF_PAUSE",
    "2026-04-10": "CPI_PRINT",
    "2026-04-11": "PPI_PRINT",
    "2026-04-17": "OPEX_WEEKLY",
    "2026-04-18": "OPEX_MONTHLY",
}

EVENT_CATEGORIES: dict[str, str] = {
    "FOMC_DECISION": "Monetary Policy",
    "TARIFF_ANNOUNCEMENT": "Trade Policy",
    "TARIFF_ESCALATION": "Trade Policy",
    "TARIFF_PAUSE": "Trade Policy",
    "NFP_FRIDAY": "Employment Data",
    "CPI_PRINT": "Inflation Data",
    "PPI_PRINT": "Inflation Data",
    "OPEX_WEEKLY": "Options Expiration",
    "OPEX_MONTHLY": "Options Expiration",
    "QUARTER_END_REBALANCE": "Calendar Effect",
}
