"""Build a comprehensive market event calendar from machine-readable sources.

Sources:
  - FOMC meetings: Federal Reserve website (static schedule)
  - Economic releases: BLS, BEA schedules
  - Options expiration: Computed from calendar rules (3rd Friday)
  - Index rebalancing: Computed from quarterly schedule
  - Major market events: Curated list with S&P 500 drawdowns

Usage:
    python scripts/build_event_calendar.py
    python scripts/build_event_calendar.py --output data/reference/market_event_calendar.csv

Output: CSV with columns: date, event_type, event_subtype, description, historical_value, surprise_direction, market_impact_notes
"""

import argparse
import csv
import os
import sys
from datetime import date, datetime, timedelta
from calendar import monthcalendar, FRIDAY


# ─── FOMC MEETINGS ────────────────────────────────────────────────────────────
# Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# Historical decisions from Fed statements

FOMC_MEETINGS = [
    # 2020
    ("2020-01-29", "hold", "1.50-1.75%", ""),
    ("2020-03-03", "cut", "1.00-1.25%", "Emergency cut — COVID-19"),
    ("2020-03-15", "cut", "0.00-0.25%", "Emergency cut to zero — COVID-19 pandemic"),
    ("2020-04-29", "hold", "0.00-0.25%", ""),
    ("2020-06-10", "hold", "0.00-0.25%", ""),
    ("2020-07-29", "hold", "0.00-0.25%", ""),
    ("2020-09-16", "hold", "0.00-0.25%", "Forward guidance updated"),
    ("2020-11-05", "hold", "0.00-0.25%", ""),
    ("2020-12-16", "hold", "0.00-0.25%", "Guidance on asset purchases"),

    # 2021
    ("2021-01-27", "hold", "0.00-0.25%", ""),
    ("2021-03-17", "hold", "0.00-0.25%", ""),
    ("2021-04-28", "hold", "0.00-0.25%", ""),
    ("2021-06-16", "hold", "0.00-0.25%", "Dot plot shift hawkish"),
    ("2021-07-28", "hold", "0.00-0.25%", ""),
    ("2021-09-22", "hold", "0.00-0.25%", "Taper signal"),
    ("2021-11-03", "hold", "0.00-0.25%", "Taper announced"),
    ("2021-12-15", "hold", "0.00-0.25%", "Accelerated taper"),

    # 2022
    ("2022-01-26", "hold", "0.00-0.25%", "Signaled March hike"),
    ("2022-03-16", "hike", "0.25-0.50%", "+25bp — first hike since 2018"),
    ("2022-05-04", "hike", "0.75-1.00%", "+50bp"),
    ("2022-06-15", "hike", "1.50-1.75%", "+75bp — largest since 1994"),
    ("2022-07-27", "hike", "2.25-2.50%", "+75bp"),
    ("2022-09-21", "hike", "3.00-3.25%", "+75bp"),
    ("2022-11-02", "hike", "3.75-4.00%", "+75bp"),
    ("2022-12-14", "hike", "4.25-4.50%", "+50bp — pace slowed"),

    # 2023
    ("2023-02-01", "hike", "4.50-4.75%", "+25bp"),
    ("2023-03-22", "hike", "4.75-5.00%", "+25bp — SVB crisis context"),
    ("2023-05-03", "hike", "5.00-5.25%", "+25bp"),
    ("2023-06-14", "hold", "5.00-5.25%", "Skip — hawkish hold"),
    ("2023-07-26", "hike", "5.25-5.50%", "+25bp — final hike of cycle"),
    ("2023-09-20", "hold", "5.25-5.50%", "Higher for longer signal"),
    ("2023-11-01", "hold", "5.25-5.50%", ""),
    ("2023-12-13", "hold", "5.25-5.50%", "Pivot signal — dovish dot plot"),

    # 2024
    ("2024-01-31", "hold", "5.25-5.50%", ""),
    ("2024-03-20", "hold", "5.25-5.50%", ""),
    ("2024-05-01", "hold", "5.25-5.50%", ""),
    ("2024-06-12", "hold", "5.25-5.50%", ""),
    ("2024-07-31", "hold", "5.25-5.50%", "September cut signal"),
    ("2024-09-18", "cut", "4.75-5.00%", "-50bp — first cut since 2020"),
    ("2024-11-07", "cut", "4.50-4.75%", "-25bp"),
    ("2024-12-18", "cut", "4.25-4.50%", "-25bp"),

    # 2025
    ("2025-01-29", "hold", "4.25-4.50%", "Pause after 3 cuts"),
    ("2025-03-19", "hold", "4.25-4.50%", ""),

    # 2025-2026 scheduled (no decisions yet for future)
    ("2025-05-07", "", "", "Scheduled"),
    ("2025-06-18", "", "", "Scheduled"),
    ("2025-07-30", "", "", "Scheduled"),
    ("2025-09-17", "", "", "Scheduled"),
    ("2025-10-29", "", "", "Scheduled"),
    ("2025-12-10", "", "", "Scheduled"),
    ("2026-01-28", "", "", "Scheduled"),
    ("2026-03-18", "", "", "Scheduled"),
    ("2026-04-29", "", "", "Scheduled"),
    ("2026-06-17", "", "", "Scheduled"),
    ("2026-07-29", "", "", "Scheduled"),
    ("2026-09-16", "", "", "Scheduled"),
    ("2026-10-28", "", "", "Scheduled"),
    ("2026-12-09", "", "", "Scheduled"),
]


# ─── MAJOR MARKET EVENTS ─────────────────────────────────────────────────────

MAJOR_EVENTS = [
    ("2020-02-19", "MARKET_EVENT", "correction_start", "COVID-19 selloff begins — S&P 500 peaks at 3386", "", "", "S&P dropped 34% in 23 trading days"),
    ("2020-03-09", "MARKET_EVENT", "circuit_breaker", "Circuit breaker triggered — S&P 500 -7% at open", "", "", "First circuit breaker since 1997"),
    ("2020-03-12", "MARKET_EVENT", "circuit_breaker", "Circuit breaker triggered again — S&P 500 -9.5%", "", "", "Largest single-day drop since 1987"),
    ("2020-03-16", "MARKET_EVENT", "circuit_breaker", "Circuit breaker triggered — S&P 500 -12%", "", "", "Third circuit breaker in one week"),
    ("2020-03-23", "MARKET_EVENT", "bear_market_bottom", "COVID bear market bottom — S&P 500 at 2237", "", "", "34% drawdown from peak"),
    ("2022-01-03", "MARKET_EVENT", "correction_start", "2022 bear market begins — S&P 500 peaks at 4797", "", "", "Rate hike cycle selloff"),
    ("2022-06-16", "MARKET_EVENT", "bear_market", "S&P 500 enters bear market — 20% from peak", "", "", "Inflation + aggressive rate hikes"),
    ("2022-10-12", "MARKET_EVENT", "bear_market_bottom", "2022 bear market bottom — S&P 500 at 3577", "", "", "25.4% peak-to-trough drawdown"),
    ("2023-03-10", "MARKET_EVENT", "banking_crisis", "SVB failure — largest bank failure since 2008", "", "", "S&P 500 -4.5% in two sessions"),
    ("2023-03-12", "MARKET_EVENT", "banking_crisis", "Signature Bank closed — FDIC backstop announced", "", "", "Systemic risk fears"),
    ("2023-07-31", "MARKET_EVENT", "correction_start", "Aug-Oct 2023 correction begins", "", "", "Higher-for-longer fears, 10Y yields surge"),
    ("2023-10-27", "MARKET_EVENT", "correction_bottom", "Oct 2023 correction bottom — S&P 500 at 4117", "", "", "~10% correction"),
    ("2024-08-05", "MARKET_EVENT", "volatility_spike", "Yen carry trade unwind — VIX spikes to 65", "", "", "Largest VIX spike since COVID"),
]


def compute_third_friday(year: int, month: int) -> date:
    """Compute the third Friday of a given month (options expiration)."""
    cal = monthcalendar(year, month)
    # Find all Fridays (index 4 in the week)
    fridays = [week[FRIDAY] for week in cal if week[FRIDAY] != 0]
    return date(year, month, fridays[2])  # Third Friday (0-indexed)


def generate_options_expirations(start_year: int, end_year: int) -> list[dict]:
    """Generate monthly and quarterly options expiration dates."""
    events = []
    quarterly_months = {3, 6, 9, 12}

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            exp_date = compute_third_friday(year, month)
            is_quarterly = month in quarterly_months
            subtype = "triple_witching" if is_quarterly else "monthly"
            desc = f"{'Quadruple witching' if is_quarterly else 'Monthly options expiration'}"

            events.append({
                "date": exp_date.isoformat(),
                "event_type": "OPTIONS_EXPIRATION",
                "event_subtype": subtype,
                "description": desc,
                "historical_value": "",
                "surprise_direction": "",
                "market_impact_notes": "Higher volume and volatility typical" if is_quarterly else "",
            })

    return events


def generate_index_rebalances(start_year: int, end_year: int) -> list[dict]:
    """Generate S&P quarterly rebalancing dates (effective 3rd Friday of Mar/Jun/Sep/Dec)."""
    events = []
    rebalance_months = [3, 6, 9, 12]

    for year in range(start_year, end_year + 1):
        for month in rebalance_months:
            rebal_date = compute_third_friday(year, month)
            events.append({
                "date": rebal_date.isoformat(),
                "event_type": "INDEX_REBALANCE",
                "event_subtype": "sp500_quarterly",
                "description": f"S&P 500 quarterly rebalancing effective",
                "historical_value": "",
                "surprise_direction": "",
                "market_impact_notes": "Rebalancing flows affect added/removed stocks",
            })

    return events


def generate_economic_releases(start_year: int, end_year: int) -> list[dict]:
    """Generate approximate economic release dates.

    BLS releases CPI/PPI/NFP on fixed schedules:
    - NFP: First Friday of each month
    - CPI: ~10th-14th of each month
    - PPI: ~13th-16th of each month

    For exact dates, use BLS release calendar: https://www.bls.gov/schedule/
    This generates approximate dates that are close but not exact.
    """
    events = []

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            # NFP — first Friday
            cal = monthcalendar(year, month)
            fridays = [week[FRIDAY] for week in cal if week[FRIDAY] != 0]
            if fridays:
                nfp_date = date(year, month, fridays[0])
                events.append({
                    "date": nfp_date.isoformat(),
                    "event_type": "NFP",
                    "event_subtype": "employment_situation",
                    "description": f"Non-Farm Payrolls / Employment Situation ({year}-{month:02d})",
                    "historical_value": "",
                    "surprise_direction": "",
                    "market_impact_notes": "Major market mover — typically ±0.5-1.5% S&P impact on surprise",
                })

            # CPI — approximate 12th-14th
            cpi_day = min(13, 28)  # Approximate
            cpi_date = date(year, month, cpi_day)
            # Adjust to weekday
            while cpi_date.weekday() >= 5:
                cpi_date -= timedelta(days=1)
            events.append({
                "date": cpi_date.isoformat(),
                "event_type": "CPI",
                "event_subtype": "cpi_monthly",
                "description": f"Consumer Price Index ({year}-{month:02d})",
                "historical_value": "",
                "surprise_direction": "",
                "market_impact_notes": "Key inflation indicator — high impact on rate expectations",
            })

            # GDP — quarterly only (advance ~month after quarter end)
            if month in (1, 4, 7, 10):
                gdp_day = min(28, 28)
                gdp_date = date(year, month, gdp_day)
                while gdp_date.weekday() >= 5:
                    gdp_date -= timedelta(days=1)
                quarter = {1: "Q4", 4: "Q1", 7: "Q2", 10: "Q3"}[month]
                events.append({
                    "date": gdp_date.isoformat(),
                    "event_type": "GDP",
                    "event_subtype": "gdp_advance",
                    "description": f"GDP Advance Estimate — {quarter} {year if month > 1 else year-1}",
                    "historical_value": "",
                    "surprise_direction": "",
                    "market_impact_notes": "",
                })

    return events


def build_fomc_events() -> list[dict]:
    """Convert FOMC meeting data to event format."""
    events = []
    for date_str, action, rate, notes in FOMC_MEETINGS:
        desc_parts = ["FOMC Meeting"]
        if action:
            desc_parts.append(f"— {action} to {rate}")
        if notes:
            desc_parts.append(f"({notes})")

        events.append({
            "date": date_str,
            "event_type": "FOMC",
            "event_subtype": action if action else "scheduled",
            "description": " ".join(desc_parts),
            "historical_value": rate,
            "surprise_direction": "",
            "market_impact_notes": notes,
        })
    return events


def build_major_events() -> list[dict]:
    """Convert major market events to event format."""
    events = []
    for date_str, etype, subtype, desc, val, surprise, notes in MAJOR_EVENTS:
        events.append({
            "date": date_str,
            "event_type": etype,
            "event_subtype": subtype,
            "description": desc,
            "historical_value": val,
            "surprise_direction": surprise,
            "market_impact_notes": notes,
        })
    return events


def main():
    parser = argparse.ArgumentParser(description="Build market event calendar")
    parser.add_argument("--output", default="data/reference/market_event_calendar.csv",
                        help="Output CSV path")
    parser.add_argument("--start-year", type=int, default=2020, help="Start year")
    parser.add_argument("--end-year", type=int, default=2027, help="End year")
    args = parser.parse_args()

    all_events = []

    # FOMC meetings
    fomc = build_fomc_events()
    print(f"[CALENDAR] FOMC meetings: {len(fomc)}")
    all_events.extend(fomc)

    # Options expirations
    options = generate_options_expirations(args.start_year, args.end_year)
    print(f"[CALENDAR] Options expirations: {len(options)}")
    all_events.extend(options)

    # Index rebalances
    rebalances = generate_index_rebalances(args.start_year, args.end_year)
    print(f"[CALENDAR] Index rebalances: {len(rebalances)}")
    all_events.extend(rebalances)

    # Economic releases
    econ = generate_economic_releases(args.start_year, args.end_year)
    print(f"[CALENDAR] Economic releases: {len(econ)}")
    all_events.extend(econ)

    # Major market events
    major = build_major_events()
    print(f"[CALENDAR] Major market events: {len(major)}")
    all_events.extend(major)

    # Sort by date
    all_events.sort(key=lambda x: x["date"])

    # Write CSV
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    fieldnames = ["date", "event_type", "event_subtype", "description",
                  "historical_value", "surprise_direction", "market_impact_notes"]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_events)

    # Summary
    print(f"\n{'='*60}")
    print(f"CALENDAR SUMMARY")
    print(f"{'='*60}")
    print(f"Total events: {len(all_events)}")
    type_counts = {}
    for e in all_events:
        type_counts[e["event_type"]] = type_counts.get(e["event_type"], 0) + 1
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")
    print(f"Date range: {all_events[0]['date']} to {all_events[-1]['date']}")
    print(f"\n[CALENDAR] Wrote {len(all_events)} events to {args.output}")


if __name__ == "__main__":
    main()
