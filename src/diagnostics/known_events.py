"""Known macro events for regime / cluster diagnostics.

Called by: diagnostics.analyses, src.platform.rigor.walkforward_* (planned v0.26.2)
Calls: none
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_known_events.py

Two categories of data live here:

1. `KNOWN_EVENTS` / `EVENT_CATEGORIES` — point-in-time date → label map,
   consumed by `diagnostics.analyses.event_day_clusters` (A2 tertiary).
   Stable since v0.20.0; do not remove keys without a migration note.

2. `EVENT_METADATA` (new, v0.25.1) — parallel dict keyed on the same dates,
   carrying rich per-event attributes (description, affected sectors,
   primary-source citation). Required by the v0.26.2 post-audit ruleset
   tariff-exclusion rule; also useful for dashboard tooltips.

All 2019-2024 additions verified against primary-source announcements
(treasury.gov/OFAC, USTR, White House EO archive, DOD, or Maersk press
releases) and cross-checked against Reuters/WSJ/Bloomberg market-move
coverage. See `docs/sprints/known_events_and_drift_repair_research.md`
for per-event verdict reasoning.

Schema extension rationale: the existing `dict[str, str]` shape was kept
intact to avoid touching consumers (`src/diagnostics/analyses.py:210-213`).
Metadata lives in a parallel dict with the invariant
`set(KNOWN_EVENTS) == set(EVENT_METADATA)`, enforced by tests.
"""
from __future__ import annotations

from datetime import date as _date
from typing import TypedDict


class EventMeta(TypedDict):
    """Per-event metadata. Empty `affected_sectors` list = broad-market shock."""

    description: str
    affected_sectors: list[str]
    primary_source: str
    market_impact_note: str


# ---------------------------------------------------------------------------
# KNOWN_EVENTS — date → event label
#
# ISO-8601 date strings (YYYY-MM-DD) map to uppercase event labels.
# Point-in-time only — multi-day events (e.g., Russia sanctions rounds)
# are encoded as multiple distinct keys with `_ESCALATION` suffix.
# Consumed by `diagnostics.analyses.event_day_clusters` to attribute
# bad-day clusters to repeatable event categories.
# ---------------------------------------------------------------------------

KNOWN_EVENTS: dict[str, str] = {
    # 2019 — Trump I trade war tail
    "2019-10-11": "TARIFF_PAUSE",          # Phase One "in principle"
    "2019-12-12": "TARIFF_ANNOUNCEMENT",   # Phase One agreement (market-impact date; USTR formal release 12-13)

    # 2022 — Russia/Ukraine sanctions
    "2022-02-24": "SANCTIONS_INITIAL",     # Invasion + OFAC Tranche 2 (EO 14024)
    "2022-03-08": "SANCTIONS_ESCALATION",  # EO 14066 — Russian oil/gas/LNG/coal import ban

    # 2022 — Industrial policy
    "2022-07-27": "INDUSTRIAL_POLICY",     # Manchin-Schumer IRA deal + CHIPS Senate passage
    "2022-08-09": "INDUSTRIAL_POLICY",     # CHIPS Act signed (PL 117-167)

    # 2022 — Export controls
    "2022-10-07": "EXPORT_CONTROLS",       # BIS advanced-chip / semi-equipment controls on China

    # 2023 — Red Sea disruption
    "2023-12-18": "TRADE_DISRUPTION",      # Maersk/Hapag-Lloyd halt + Operation Prosperity Guardian

    # 2024 — Biden Section 301
    "2024-05-14": "TARIFF_ESCALATION",     # $18B Section 301 tariff increases on China

    # 2026 — March (existing entries — retained from v0.20.0)
    "2026-03-18": "FOMC_DECISION",
    "2026-03-19": "FOMC_DECISION",
    "2026-03-28": "QUARTER_END_REBALANCE",

    # 2026 — April (existing entries — retained from v0.20.0)
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
    # Pre-existing — do not remove
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
    # Added v0.25.1 — all roll up to Trade Policy for consumer uniformity
    "SANCTIONS_INITIAL": "Trade Policy",
    "SANCTIONS_ESCALATION": "Trade Policy",
    "EXPORT_CONTROLS": "Trade Policy",
    "INDUSTRIAL_POLICY": "Trade Policy",
    "TRADE_DISRUPTION": "Trade Policy",
}


# ---------------------------------------------------------------------------
# EVENT_METADATA — parallel rich metadata, same keys as KNOWN_EVENTS.
#
# Invariant (enforced by test): set(KNOWN_EVENTS) == set(EVENT_METADATA).
# Existing 2026 entries carry minimal metadata so the invariant holds; they
# are not primary-source-cited because they're CC's forward-planning data,
# not historical events (market-impact fields are forward-looking).
# ---------------------------------------------------------------------------

EVENT_METADATA: dict[str, EventMeta] = {
    # --- 2019 ---
    "2019-10-11": {
        "description": (
            "Phase One trade deal agreed 'in principle' between US and China. "
            "Scheduled Oct 15 tariff step-up (List 1/2/3: 25→30%) suspended; "
            "framework covered ag purchases, IP, currency, structural commitments."
        ),
        "affected_sectors": [],  # broad-market
        "primary_source": "https://ustr.gov/about-us/policy-offices/press-office/press-releases/2019/october",
        "market_impact_note": "SPY +1.07% close; VIX -2.8 to ~15.6; intraday peak ~+1.9% before fading.",
    },
    "2019-12-12": {
        "description": (
            "Phase One text-level agreement reached (announced Dec 13 by USTR; "
            "market moved Dec 12 on Reuters leak). List 4A tariffs halved "
            "(15→7.5%); scheduled Dec 15 tariffs on $160B consumer goods cancelled."
        ),
        "affected_sectors": [],  # broad-market; XRT extra
        "primary_source": "https://ustr.gov/about-us/policy-offices/press-office/press-releases/2019/december",
        "market_impact_note": "SPY +0.86% Dec 12 on leak; Dec 13 formal release closed flat (sell-the-news).",
    },
    # --- 2022 ---
    "2022-02-24": {
        "description": (
            "Russia invades Ukraine. Biden announces OFAC Tranche 2 sanctions under "
            "EO 14024: CAPTA directive on Sberbank correspondent accounts, full "
            "blocks on VTB + 3 others, Directive 3 debt/equity restrictions on "
            "13 entities, broad export controls."
        ),
        "affected_sectors": [],  # broad-market; ITA (defense) + XLE (energy) secondary
        "primary_source": "https://home.treasury.gov/news/press-releases/jy0608",
        "market_impact_note": "SPY open -2.6%, close +1.5% (4%+ intraday range); VIX intraday ~37, close ~30.",
    },
    "2022-03-08": {
        "description": (
            "EO 14066 prohibits imports of Russian crude, petroleum products, LNG, "
            "and coal; bans new US investment in Russian energy sector. Federal "
            "Register 87 FR 14381."
        ),
        "affected_sectors": ["XLE", "XOP", "OIH"],
        "primary_source": "https://www.whitehouse.gov/briefing-room/presidential-actions/2022/03/08/executive-order-on-prohibiting-certain-imports-and-new-investments-with-respect-to-continued-russian-federation-efforts-to-undermine-the-sovereignty-and-territorial-integrity-of-ukraine/",
        "market_impact_note": "WTI close $123.70 (+3.6%); intraday high $130.50. XLE 2-day move +4.4% (Mar 7-8).",
    },
    "2022-07-27": {
        "description": (
            "Manchin-Schumer Inflation Reduction Act framework agreement announced "
            "(post months of stall) paired with CHIPS Act final Senate passage. "
            "Clean-energy + semiconductor industrial-policy thesis validated in "
            "one session."
        ),
        "affected_sectors": ["TAN", "ICLN", "SOX", "SMH", "XLB"],
        "primary_source": "https://www.congress.gov/bill/117th-congress/house-bill/4346",
        "market_impact_note": "TAN +5.7%, ICLN +3.9%, SOX +2.8% on the day.",
    },
    "2022-08-09": {
        "description": (
            "CHIPS and Science Act signed into law (PL 117-167). $52.7B "
            "semiconductor manufacturing + R&D subsidies; ~$24B Section 48D "
            "investment tax credit."
        ),
        "affected_sectors": ["SOX", "SMH", "SOXX"],
        "primary_source": "https://www.whitehouse.gov/briefing-room/statements-releases/2022/08/09/fact-sheet-chips-and-science-act-will-lower-costs-create-jobs-strengthen-supply-chains-and-counter-china/",
        "market_impact_note": "SOX -4.6% (sell-the-news + Micron pre-announce neg guide same morning); NVDA -3.97%.",
    },
    "2022-10-07": {
        "description": (
            "BIS advanced-chip + semiconductor manufacturing equipment export "
            "controls on China. Controls advanced-node logic/memory, HBM, "
            "advanced-compute ICs, and semi manufacturing equipment destined "
            "for PRC end users; US-person restriction on supporting PRC fab "
            "development. Federal Register IFR 87 FR 62186."
        ),
        "affected_sectors": ["SOX", "SMH", "SOXX"],
        "primary_source": "https://www.bis.doc.gov/index.php/documents/about-bis/newsroom/press-releases",
        "market_impact_note": "SOX -6.06%, NVDA -8.03%, AMD -13.87%, AMAT -6.83%, LRCX -6.46%. Largest single-day semi sector shock in window.",
    },
    # --- 2023 ---
    "2023-12-18": {
        "description": (
            "Maersk + Hapag-Lloyd confirm Red Sea transit halts following Galaxy "
            "Leader seizure and Maersk Hangzhou incident. DOD launches Operation "
            "Prosperity Guardian same day."
        ),
        "affected_sectors": ["ZIM", "MATX", "XLE", "ITA"],
        "primary_source": "https://www.maersk.com/news/articles/2023/12/15/maersk-pauses-all-transit-through-the-red-sea",
        "market_impact_note": "ZIM +8.4%, Matson +2.1%, WTI +1.8%, Brent +1.8%. Container spot rates +20-40% over next 2 weeks.",
    },
    # --- 2024 ---
    "2024-05-14": {
        "description": (
            "Biden Section 301 tariff increases on ~$18B Chinese imports: EVs "
            "25→100%, EV batteries 7.5→25%, solar cells 25→50%, semis 25→50%, "
            "steel/aluminum to 25%, ship-to-shore cranes to 25%, syringes/PPE "
            "increases. USTR 4-year-review release."
        ),
        "affected_sectors": ["KWEB", "FXI", "LIT"],
        "primary_source": "https://www.whitehouse.gov/briefing-room/statements-releases/2024/05/14/fact-sheet-president-biden-takes-action-to-protect-american-workers-and-businesses-from-chinas-unfair-trade-practices/",
        "market_impact_note": "KWEB -1.6%, FXI -2.1%, BYDDY -1.8%, NIO -3.9% through May 15. SPY muted +0.48% but targeted-sector rotation cleared 2σ. Category-perfect tariff event.",
    },
    # --- 2026 (placeholder metadata for existing forward-planning entries) ---
    "2026-03-18": {
        "description": "FOMC rate decision day 1 (projected).",
        "affected_sectors": [],
        "primary_source": "internal",
        "market_impact_note": "forward-planning entry",
    },
    "2026-03-19": {
        "description": "FOMC rate decision day 2 (projected).",
        "affected_sectors": [],
        "primary_source": "internal",
        "market_impact_note": "forward-planning entry",
    },
    "2026-03-28": {
        "description": "Quarter-end institutional rebalance flows (projected).",
        "affected_sectors": [],
        "primary_source": "internal",
        "market_impact_note": "forward-planning entry",
    },
    "2026-04-02": {
        "description": "Tariff announcement (projected).",
        "affected_sectors": [],
        "primary_source": "internal",
        "market_impact_note": "forward-planning entry",
    },
    "2026-04-03": {
        "description": "US non-farm payrolls release (projected).",
        "affected_sectors": [],
        "primary_source": "internal",
        "market_impact_note": "forward-planning entry",
    },
    "2026-04-04": {
        "description": "Tariff escalation (projected).",
        "affected_sectors": [],
        "primary_source": "internal",
        "market_impact_note": "forward-planning entry",
    },
    "2026-04-07": {
        "description": "Tariff escalation (projected).",
        "affected_sectors": [],
        "primary_source": "internal",
        "market_impact_note": "forward-planning entry",
    },
    "2026-04-09": {
        "description": "Tariff pause / de-escalation (projected).",
        "affected_sectors": [],
        "primary_source": "internal",
        "market_impact_note": "forward-planning entry",
    },
    "2026-04-10": {
        "description": "US CPI print (projected).",
        "affected_sectors": [],
        "primary_source": "internal",
        "market_impact_note": "forward-planning entry",
    },
    "2026-04-11": {
        "description": "US PPI print (projected).",
        "affected_sectors": [],
        "primary_source": "internal",
        "market_impact_note": "forward-planning entry",
    },
    "2026-04-17": {
        "description": "Weekly options expiration (projected).",
        "affected_sectors": [],
        "primary_source": "internal",
        "market_impact_note": "forward-planning entry",
    },
    "2026-04-18": {
        "description": "Monthly options expiration (projected).",
        "affected_sectors": [],
        "primary_source": "internal",
        "market_impact_note": "forward-planning entry",
    },
}


def is_known_event(date_str: str, category: str | None = None) -> bool:
    """Return True iff `date_str` maps to a known event (optionally in a given category).

    Args:
        date_str: ISO-8601 date string (YYYY-MM-DD).
        category: optional category filter (e.g., "Trade Policy"). When
            provided, returns True only when the event's category matches.

    Returns:
        bool — True when the date is in KNOWN_EVENTS and, if a category
        filter is given, the event's category equals the filter.
    """
    label = KNOWN_EVENTS.get(date_str)
    if label is None:
        return False
    if category is None:
        return True
    return EVENT_CATEGORIES.get(label) == category


def _iter_dates_in_window(start: _date, end: _date) -> list[str]:
    """Return KNOWN_EVENTS keys whose dates fall inside [start, end]."""
    return [
        d for d in KNOWN_EVENTS
        if start <= _date.fromisoformat(d) <= end
    ]
