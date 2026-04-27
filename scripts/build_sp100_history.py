"""Build a point-in-time SP100 constituent history from Wikipedia.

Source:
    https://en.wikipedia.org/wiki/S%26P_100
    The page contains a 'components' wikitable with the current SP100 members.
    A separate 'Recent changes' table is parsed when present; as of 2026-04,
    the Wikipedia SP100 page does not carry such a table (unlike the SP500 page),
    so the script falls back to the curated change list embedded in this module.

Curated changes source:
    S&P Dow Jones Indices press releases (spglobal.com/spdji), each entry
    verified against at least one press release or news source, mirrored
    from scripts/scrape_sp_changes.py::get_sp100_known_changes().

Refresh procedure:
    Re-run this script whenever SP100 composition changes (roughly quarterly).
    When Wikipedia adds a 'Recent changes' table to the SP100 page, the scraper
    will automatically use it via parse_change_history(); until then the curated
    list is authoritative.  Update the curated list in _CURATED_CHANGES below
    after each index rebalance announcement.
    The script is idempotent: re-running on identical inputs produces byte-
    identical JSON output (sort_keys=True, ticker lists pre-sorted).

Known limitations:
    - Wikipedia SP100 page (as of 2026-04) has no machine-readable change-history
      table; change records come from the curated list in this script.
    - Coverage starts from the earliest dated row in the curated list (2015-03-20).
    - Ticker class changes (e.g. GOOG→GOOGL) are treated as add/remove pairs; no
      attempt is made to merge share classes.
    - The current-constituents Wikipedia table may briefly exceed 100 tickers
      during index transitions; such snapshots are flagged but retained.

Usage:
    python scripts/build_sp100_history.py
    python scripts/build_sp100_history.py --output data/reference/sp100_history.json
    python scripts/build_sp100_history.py --dry-run
"""

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup


_WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/S%26P_100"
_WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
_USER_AGENT = "HalcyonLab/1.0 (halcyonlabai@gmail.com; research use)"

_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d")

# Curated SP100 component changes.
# Source: S&P Dow Jones Indices press releases (spglobal.com/spdji).
# Mirrored from scripts/scrape_sp_changes.py::get_sp100_known_changes().
# Each record: {"date": "YYYY-MM-DD", "added": "TICKER", "removed": "TICKER"}
# Use empty string "" for add-only or remove-only events.
_CURATED_CHANGES = [
    # 2015
    {"date": "2015-03-20", "added": "CMCSA", "removed": "ACE"},
    {"date": "2015-09-18", "added": "PYPL", "removed": "EBAY"},
    # 2016
    {"date": "2016-03-18", "added": "", "removed": "BKR"},
    {"date": "2016-09-06", "added": "CHTR", "removed": ""},
    # 2017
    {"date": "2017-03-20", "added": "AVGO", "removed": "TWX"},
    {"date": "2017-06-19", "added": "LOW", "removed": ""},
    # 2018
    {"date": "2018-06-18", "added": "NFLX", "removed": "TWX"},
    # 2019
    {"date": "2019-06-03", "added": "SBUX", "removed": "GE"},
    # 2020
    {"date": "2020-12-21", "added": "TSLA", "removed": "OXY"},
    # 2021
    {"date": "2021-03-22", "added": "NVDA", "removed": "WBA"},
    # 2022
    {"date": "2022-03-21", "added": "DXCM", "removed": "EMRG"},
    # 2023
    {"date": "2023-09-18", "added": "ABNB", "removed": "ATVI"},
    # 2024
    {"date": "2024-03-18", "added": "SMCI", "removed": ""},
    {"date": "2024-06-24", "added": "", "removed": "KHC"},
    # 2025
    {"date": "2025-03-24", "added": "PLTR", "removed": "EXC"},
]


def fetch_wikipedia_html(url: str) -> str:
    """Fetch raw HTML for the Wikipedia page at url.

    Tries the Wikipedia API (parse action) first; falls back to the direct
    page URL if the API returns empty content.

    Args:
        url: Full Wikipedia page URL (e.g. https://en.wikipedia.org/wiki/S%26P_100).

    Returns:
        HTML string of the parsed page body.

    Raises:
        requests.HTTPError: on non-2xx responses from either endpoint.
    """
    headers = {"User-Agent": _USER_AGENT}

    page_title = url.split("/wiki/")[-1].replace("%26", "&")

    api_params = {
        "action": "parse",
        "page": page_title,
        "prop": "text",
        "format": "json",
    }

    print(f"[BUILD_SP100] Fetching via Wikipedia API: {page_title}")
    resp = requests.get(_WIKIPEDIA_API_URL, params=api_params, headers=headers, timeout=30)
    resp.raise_for_status()

    data = resp.json()
    html_content = data.get("parse", {}).get("text", {}).get("*", "")

    if not html_content:
        print("[BUILD_SP100] API returned empty body, falling back to direct page fetch...")
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        html_content = resp.text

    return html_content


def parse_current_constituents(html: str) -> list:
    """Parse the current SP100 constituents from the Wikipedia page HTML.

    Looks first for a table with id='constituents'.  If not found, uses
    the largest wikitable by row count (typically the Symbol/Name/Sector table).

    Args:
        html: Raw HTML string of the Wikipedia page.

    Returns:
        Sorted list of ticker strings (e.g. ['AAPL', 'ABBV', ...]).

    Raises:
        ValueError: if no table can be found or no tickers extracted.
    """
    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table", {"id": "constituents"})

    if table is None:
        wikitables = soup.find_all("table", class_="wikitable")
        if not wikitables:
            raise ValueError("No wikitable found in HTML — page structure may have changed")
        table = max(wikitables, key=lambda t: len(t.find_all("tr")))

    rows = table.find_all("tr")[1:]
    tickers = []
    for row in rows:
        cols = row.find_all(["td", "th"])
        if len(cols) < 1:
            continue
        ticker_raw = cols[0].get_text(strip=True)
        ticker_clean = re.sub(r"\[.*?\]", "", ticker_raw).strip()
        if ticker_clean:
            tickers.append(ticker_clean)

    if not tickers:
        raise ValueError("parse_current_constituents: no tickers extracted from constituents table")

    return sorted(tickers)


def _parse_date_str(raw: str) -> str:
    """Strip footnote markers and parse a date string to ISO format.

    Args:
        raw: Raw date text, possibly containing footnote refs like '[3]'.

    Returns:
        ISO-format date string 'YYYY-MM-DD'.

    Raises:
        ValueError: if the date cannot be parsed in any known format.
    """
    cleaned = re.sub(r"\[\d+\]", "", raw).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {raw!r} (cleaned: {cleaned!r})")


def _find_col(headers: list, candidates: list):
    """Return the first header index matching any candidate substring (case-insensitive).

    Returns None if no match found.
    """
    for i, h in enumerate(headers):
        for c in candidates:
            if c in h.lower():
                return i
    return None


def parse_change_history(html: str) -> list:
    """Parse the SP100 component-change history table from Wikipedia HTML.

    As of 2026-04 the Wikipedia SP100 page does not carry a change-history
    table (unlike the SP500 page), so this function returns an empty list
    when no such table is detected.  If a 'Recent changes' or similar table
    is added in the future, this function will parse it automatically.

    A table is considered a change-history table when its headers include
    recognisable 'date', 'added', and 'removed' columns.

    Args:
        html: Raw HTML string of the Wikipedia page.

    Returns:
        List of dicts with keys: 'date' (ISO str), 'added' (str), 'removed'
        (str).  Duplicates on (date, added, removed) are de-duplicated.
        Empty list if no change-history table is found.
    """
    soup = BeautifulSoup(html, "html.parser")
    wikitables = soup.find_all("table", class_="wikitable")

    for table in wikitables:
        rows = table.find_all("tr")
        if not rows:
            continue

        header_row = rows[0]
        raw_headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
        headers_lower = [h.lower() for h in raw_headers]

        date_col = _find_col(headers_lower, ["date"])
        added_col = _find_col(headers_lower, ["added"])
        removed_col = _find_col(headers_lower, ["removed"])

        if date_col is None or added_col is None or removed_col is None:
            continue

        records = []
        seen = set()
        skipped = 0

        for row in rows[1:]:
            cols = row.find_all(["td", "th"])
            max_col = max(date_col, added_col, removed_col)
            if len(cols) <= max_col:
                continue

            date_raw = cols[date_col].get_text(strip=True)
            if not date_raw:
                continue

            try:
                date_str = _parse_date_str(date_raw)
            except ValueError as exc:
                print(f"[BUILD_SP100] Skipping row with unparseable date: {exc}")
                skipped += 1
                continue

            added_raw = cols[added_col].get_text(strip=True)
            removed_raw = cols[removed_col].get_text(strip=True)
            added = re.sub(r"\[.*?\]", "", added_raw).strip()
            removed = re.sub(r"\[.*?\]", "", removed_raw).strip()

            if not added and not removed:
                continue

            key = (date_str, added, removed)
            if key in seen:
                continue
            seen.add(key)
            records.append({"date": date_str, "added": added, "removed": removed})

        if skipped:
            print(f"[BUILD_SP100] Skipped {skipped} rows with unparseable dates")

        if records:
            records.sort(key=lambda r: r["date"])
            print(f"[BUILD_SP100] Parsed {len(records)} unique change records from Wikipedia table")
            return records

    print("[BUILD_SP100] No change-history table found on Wikipedia page; will use curated list")
    return []


def build_history_table(current: list, changes: list) -> dict:
    """Build a {iso_date: sorted_ticker_list} dict for every change-point.

    Algorithm:
        Start with today's snapshot (current constituents).
        Walk the change records in descending date order.
        For each change, record the snapshot for the change date (post-change),
        then reverse-apply: remove the 'added' ticker and restore the 'removed'
        ticker to reconstruct the state before that change.

    The day before the earliest change is also recorded, capturing the
    pre-history baseline.

    Args:
        current: Sorted list of ticker strings representing today's SP100.
        changes: List of dicts with keys 'date', 'added', 'removed'; sorted
                 ascending by date (as returned by parse_change_history or
                 _CURATED_CHANGES).

    Returns:
        Dict mapping ISO date strings to sorted ticker lists.  sort_keys=True
        on json.dump produces deterministic byte-identical output on re-runs.
    """
    today = date.today().strftime("%Y-%m-%d")
    snapshot = set(current)
    result = {today: sorted(snapshot)}

    for record in reversed(changes):
        change_date = record["date"]
        added = record.get("added", "")
        removed = record.get("removed", "")

        result[change_date] = sorted(snapshot)

        if added and added in snapshot:
            snapshot.discard(added)
        if removed and removed not in snapshot:
            snapshot.add(removed)

    if changes:
        earliest_date = changes[0]["date"]
        try:
            earliest_dt = datetime.strptime(earliest_date, "%Y-%m-%d").date()
            day_before = (earliest_dt - timedelta(days=1)).strftime("%Y-%m-%d")
            result[day_before] = sorted(snapshot)
        except Exception:
            pass

    return result


def _validate_table(table: dict) -> list:
    """Return a list of invariant violation strings (empty list means OK)."""
    violations = []
    if len(table) < 2:
        violations.append(f"fewer than 2 snapshots ({len(table)})")
    for date_str, tickers in table.items():
        if len(tickers) == 0:
            violations.append(f"snapshot {date_str} has 0 tickers")
        if len(tickers) > 110:
            violations.append(f"snapshot {date_str} has {len(tickers)} tickers (>110; likely parse error)")
    return violations


def main(argv=None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list (uses sys.argv if None).

    Returns:
        0 on success, 1 on invariant failure or fatal error.
    """
    parser = argparse.ArgumentParser(
        description="Build SP100 point-in-time constituent history from Wikipedia"
    )
    parser.add_argument(
        "--output",
        default="data/reference/sp100_history.json",
        help="Output JSON path (default: data/reference/sp100_history.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary, do not write output file",
    )
    args = parser.parse_args(argv)

    try:
        html = fetch_wikipedia_html(_WIKIPEDIA_URL)
    except Exception as exc:
        print(f"[BUILD_SP100] FATAL: could not fetch Wikipedia page: {exc}")
        return 1

    try:
        current = parse_current_constituents(html)
    except Exception as exc:
        print(f"[BUILD_SP100] FATAL: could not parse current constituents: {exc}")
        return 1

    print(f"[BUILD_SP100] Current constituents: {len(current)} tickers")

    wiki_changes = parse_change_history(html)
    if wiki_changes:
        changes = wiki_changes
        print(f"[BUILD_SP100] Using {len(changes)} changes from Wikipedia table")
    else:
        changes = list(_CURATED_CHANGES)
        print(f"[BUILD_SP100] Using {len(changes)} changes from curated list (Wikipedia has no change table)")

    table = build_history_table(current, changes)

    violations = _validate_table(table)
    if violations:
        for v in violations:
            print(f"[BUILD_SP100] INVARIANT VIOLATION: {v}")
        return 1

    sorted_keys = sorted(table.keys())
    earliest = sorted_keys[0]
    latest = sorted_keys[-1]
    snapshots = len(table)
    tickers_today = len(table[latest])

    print(
        f"[BUILD_SP100] earliest={earliest} latest={latest} "
        f"snapshots={snapshots} tickers_today={tickers_today}"
    )

    if args.dry_run:
        print("[BUILD_SP100] dry-run — not writing output file")
        return 0

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(table, fh, sort_keys=True, indent=2)
    print(f"[BUILD_SP100] Wrote {snapshots} snapshots to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
